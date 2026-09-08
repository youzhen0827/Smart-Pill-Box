#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import threading
import time
from datetime import datetime
from functools import partial

from gpiozero import Button

from common import DeviceApiError, api_request


def parse_pin_map(value: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for piece in value.split(","):
        if not piece.strip():
            continue
        try:
            slot_text, pin_text = piece.split(":", 1)
            slot, pin = int(slot_text), int(pin_text)
        except ValueError as exc:
            raise ValueError("SLOT_PINS 格式必須像 1:5,2:6,3:13。") from exc
        if not 1 <= slot <= 3:
            raise ValueError("格位必須是 1 到 3（早、中、晚）。")
        mapping[slot] = pin
    if not mapping:
        raise ValueError("至少設定一個感測器腳位。")
    return mapping


def post_event(device_id: str, user_name: str, slot: int | None, event_type: str, source: str) -> None:
    payload = {
        "device_id": device_id,
        "user_name": user_name,
        "slot": slot,
        "event_type": event_type,
        "detected_at": datetime.now().astimezone().isoformat(),
        "source": source,
    }
    try:
        result = api_request("POST", "sensors/events/", json_body=payload)
        matched = result.get("matched_reminder")
        print(
            f"{event_type} device={device_id} slot={slot or '-'}; "
            f"matched={matched.get('id') if matched else 'none'}"
        )
    except DeviceApiError as exc:
        print(f"感測事件上傳失敗：{exc}")


def heartbeat_loop(device_id: str, user_name: str, interval: int, stop: threading.Event) -> None:
    while not stop.wait(max(15, interval)):
        post_event(device_id, user_name, None, "heartbeat", "raspberry_pi_gpio")


def main() -> int:
    parser = argparse.ArgumentParser(description="早／中／晚三格智慧藥盒 Raspberry Pi GPIO 感測器上報")
    parser.add_argument("--device-id", default=os.getenv("SMARTPILL_DEVICE_ID", "pillbox-01"))
    parser.add_argument("--user-name", default=os.getenv("SMARTPILL_USER_NAME", ""))
    parser.add_argument("--pins", default=os.getenv("SLOT_PINS", "1:5,2:6,3:13"))
    parser.add_argument("--heartbeat", type=int, default=60)
    parser.add_argument(
        "--active-high",
        action="store_true",
        help="感測器輸出高電位時代表觸發；預設為 active-low（使用內建 pull-up，接地觸發）。",
    )
    parser.add_argument("--simulate-slot", type=int, help="不讀 GPIO，只送出一次明確標示為 manual_test 的 opened 事件")
    args = parser.parse_args()

    if args.simulate_slot:
        if not 1 <= args.simulate_slot <= 3:
            parser.error("--simulate-slot 必須是 1 到 3（早、中、晚）")
        post_event(args.device_id, args.user_name, args.simulate_slot, "opened", "manual_test")
        return 0

    pin_map = parse_pin_map(args.pins)
    sensors: list[Button] = []
    for slot, pin in pin_map.items():
        sensor = Button(pin, pull_up=not args.active_high, bounce_time=0.12)
        sensor.when_pressed = partial(
            post_event,
            args.device_id,
            args.user_name,
            slot,
            "opened",
            "raspberry_pi_gpio",
        )
        sensor.when_released = partial(
            post_event,
            args.device_id,
            args.user_name,
            slot,
            "closed",
            "raspberry_pi_gpio",
        )
        sensors.append(sensor)
        print(f"格 {slot} → BCM GPIO {pin}")

    stop = threading.Event()
    heartbeat = threading.Thread(
        target=heartbeat_loop,
        args=(args.device_id, args.user_name, args.heartbeat, stop),
        daemon=True,
    )
    heartbeat.start()

    def shutdown(*_):
        stop.set()
        for sensor in sensors:
            sensor.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print("感測器監聽中；Ctrl+C 結束。")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
