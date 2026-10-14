#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from dataclasses import dataclass

import requests
import serial
from serial import SerialException
from serial.tools import list_ports


PREFERRED_PORT_WORDS = ("cp210", "ch340", "usb serial", "usb-serial", "silicon labs", "uart")


def available_ports() -> list[tuple[str, str]]:
    return [(item.device, item.description or "") for item in list_ports.comports()]


def choose_port(explicit: str = "") -> str:
    if explicit:
        return explicit
    ports = available_ports()
    if not ports:
        raise RuntimeError("找不到 USB 序列埠；請確認照片中的 USB 線已接上 ESP32 與電腦。")
    preferred = [
        device
        for device, description in ports
        if any(word in description.casefold() for word in PREFERRED_PORT_WORDS)
    ]
    if len(preferred) == 1:
        return preferred[0]
    if len(ports) == 1:
        return ports[0][0]
    choices = "、".join(f"{device} ({description})" for device, description in ports)
    raise RuntimeError(f"找到多個序列埠：{choices}；請用 --port 指定 ESP32。")


def parse_event_line(line: str) -> tuple[int, str] | None:
    parts = line.strip().split("|")
    if len(parts) != 3 or parts[0] != "EVENT":
        return None
    try:
        slot = int(parts[1])
    except ValueError:
        return None
    event_type = parts[2]
    if slot not in (1, 2, 3) or event_type not in ("opened", "closed"):
        return None
    return slot, event_type


def parse_pir_line(line: str) -> str | None:
    value = line.strip()
    if value == "PIR|detected":
        return "presence_detected"
    if value == "PIR|clear":
        return "presence_cleared"
    return None


@dataclass
class BridgeConfig:
    port: str
    baud: int
    api_url: str
    token: str
    device_id: str
    user_name: str
    heartbeat_seconds: int

    @property
    def events_url(self) -> str:
        return f"{self.api_url.rstrip('/')}/sensors/events/"

    @property
    def state_url(self) -> str:
        return f"{self.api_url.rstrip('/')}/hardware/state/"


class UsbSerialBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Device-Token": config.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.stop = False
        self.last_state_command = ""

    def post_event(self, event_type: str, slot: int | None = None) -> dict:
        payload: dict[str, object] = {
            "device_id": self.config.device_id,
            "user_name": self.config.user_name,
            "event_type": event_type,
            "source": "esp32_usb_serial",
        }
        if slot is not None:
            payload["slot"] = slot
        response = self.session.post(self.config.events_url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()

    def state_command(self) -> tuple[str, float]:
        response = self.session.get(
            self.config.state_url,
            params={"device_id": self.config.device_id, "user_name": self.config.user_name},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        slots = sorted(payload.get("slots") or [], key=lambda item: int(item.get("slot", 0)))
        leds = [1 if item.get("led_on") else 0 for item in slots[:3]]
        while len(leds) < 3:
            leds.append(0)
        buzzer = 1 if payload.get("buzzer_on") else 0
        command = f"STATE|{leds[0]}|{leds[1]}|{leds[2]}|{buzzer}\n"
        poll_seconds = max(1.0, float(payload.get("poll_after_ms", 5000)) / 1000.0)
        return command, poll_seconds

    def handle_device_line(self, line: str) -> None:
        if not line:
            return
        print(f"ESP32 > {line}")
        event = parse_event_line(line)
        if event:
            slot, event_type = event
            result = self.post_event(event_type, slot)
            matched = result.get("matched_reminder")
            print(
                f"Django：{slot} 格 {event_type} 已上傳；"
                f"配對提醒={matched.get('id') if isinstance(matched, dict) else '無'}"
            )
        elif pir_event := parse_pir_line(line):
            self.post_event(pir_event)
            print(f"Django：PIR {pir_event} 已上傳")
        elif line == "HEARTBEAT":
            self.post_event("heartbeat")

    def run_connected(self, port: str) -> None:
        print(f"連接 {port} @ {self.config.baud}，裝置 ID={self.config.device_id}")
        with serial.Serial(port, self.config.baud, timeout=0.25, write_timeout=2) as device:
            time.sleep(1.2)
            device.reset_input_buffer()
            self.post_event("heartbeat")
            last_heartbeat = time.monotonic()
            next_state_poll = 0.0
            poll_seconds = 5.0

            while not self.stop:
                raw = device.readline()
                if raw:
                    self.handle_device_line(raw.decode("utf-8", errors="replace").strip())

                now = time.monotonic()
                if now >= next_state_poll:
                    try:
                        command, poll_seconds = self.state_command()
                        if command != self.last_state_command:
                            device.write(command.encode("ascii"))
                            self.last_state_command = command
                            print(f"Django > ESP32：{command.strip()}")
                    except requests.RequestException as exc:
                        print(f"Django 狀態讀取失敗：{exc}", file=sys.stderr)
                    next_state_poll = now + poll_seconds

                if now - last_heartbeat >= self.config.heartbeat_seconds:
                    try:
                        self.post_event("heartbeat")
                    except requests.RequestException as exc:
                        print(f"心跳上傳失敗：{exc}", file=sys.stderr)
                    last_heartbeat = now

    def run(self) -> int:
        while not self.stop:
            try:
                port = choose_port(self.config.port)
                self.run_connected(port)
            except (RuntimeError, SerialException, OSError, requests.RequestException) as exc:
                if self.stop:
                    break
                print(f"USB 橋接暫時中斷：{exc}；3 秒後重試。", file=sys.stderr)
                time.sleep(3)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="照片中 ESP32 藥盒的 USB 序列埠 ↔ Django API 橋接器")
    parser.add_argument("--port", default=os.getenv("SMARTPILL_SERIAL_PORT", ""), help="例如 COM5；留空時自動偵測")
    parser.add_argument("--baud", type=int, default=int(os.getenv("SMARTPILL_SERIAL_BAUD", "115200")))
    parser.add_argument(
        "--api-url",
        default=os.getenv("SMARTPILL_API_URL", "http://127.0.0.1:8000/api/v1/"),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SMARTPILL_DEVICE_TOKEN", "smartpill-dev-token"),
    )
    parser.add_argument("--device-id", default=os.getenv("SMARTPILL_DEVICE_ID", "pillbox-01"))
    parser.add_argument("--user-name", default=os.getenv("SMARTPILL_USER_NAME", ""))
    parser.add_argument("--heartbeat", type=int, default=30)
    parser.add_argument("--list-ports", action="store_true", help="只列出可用序列埠後結束")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.list_ports:
        ports = available_ports()
        if not ports:
            print("沒有偵測到序列埠。")
            return 1
        for device, description in ports:
            print(f"{device}\t{description}")
        return 0

    config = BridgeConfig(
        port=args.port,
        baud=max(1200, args.baud),
        api_url=args.api_url,
        token=args.token,
        device_id=args.device_id.strip() or "pillbox-01",
        user_name=args.user_name.strip(),
        heartbeat_seconds=max(15, args.heartbeat),
    )
    bridge = UsbSerialBridge(config)

    def stop_bridge(*_args):
        bridge.stop = True

    signal.signal(signal.SIGINT, stop_bridge)
    signal.signal(signal.SIGTERM, stop_bridge)
    return bridge.run()


if __name__ == "__main__":
    raise SystemExit(main())
