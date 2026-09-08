from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests


class DeviceApiError(RuntimeError):
    pass


def api_base_url() -> str:
    return os.getenv("SMARTPILL_API_URL", "http://127.0.0.1:8000/api/v1/").rstrip("/") + "/"


def api_token() -> str:
    return os.getenv("SMARTPILL_DEVICE_TOKEN", "smartpill-dev-token").strip()


def api_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    url = api_base_url() + path.lstrip("/")
    headers = {
        "X-Device-Token": api_token(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DeviceApiError(f"無法連線 Django API：{exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    if not response.ok:
        raise DeviceApiError(f"API {response.status_code}: {json.dumps(payload, ensure_ascii=False)}")
    if not isinstance(payload, dict):
        raise DeviceApiError("API 回傳格式不是 JSON object。")
    return payload


def record_wav(output_path: Path, *, seconds: int = 6, device: str = "default") -> None:
    """用 Raspberry Pi 的 ALSA arecord 收音；音檔固定為 Whisper 適用的 16 kHz mono PCM。"""

    command = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        "16000",
        "-c",
        "1",
        "-d",
        str(max(1, seconds)),
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("找不到 arecord；請先安裝 sudo apt install alsa-utils。") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"錄音失敗，請檢查麥克風與 ALSA 裝置：{exc}") from exc


def speak_text(text: str) -> None:
    """完全本機 TTS：優先 Piper 模型，否則使用 eSpeak NG。"""

    cleaned = (text or "").strip()
    if not cleaned:
        return
    cleaned = cleaned[:6_000]

    piper_model = os.getenv("PIPER_MODEL", "").strip()
    if piper_model:
        model_path = Path(piper_model).expanduser()
        if not model_path.exists():
            raise RuntimeError(f"PIPER_MODEL 不存在：{model_path}")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                ["piper", "--model", str(model_path), "--output_file", str(wav_path)],
                input=cleaned.encode("utf-8"),
                check=True,
            )
            del proc
            subprocess.run(["aplay", str(wav_path)], check=True)
            return
        except FileNotFoundError as exc:
            raise RuntimeError("設定了 PIPER_MODEL，但找不到 piper 或 aplay。") from exc
        finally:
            wav_path.unlink(missing_ok=True)

    voice = os.getenv("ESPEAK_VOICE", "zh")
    speed = os.getenv("ESPEAK_SPEED", "145")
    try:
        subprocess.run(["espeak-ng", "-v", voice, "-s", speed, cleaned], check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("找不到本機 TTS；請安裝 espeak-ng，或設定 PIPER_MODEL。") from exc
