#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from common import DeviceApiError, api_request, record_wav, speak_text


def transcribe(model: WhisperModel, wav_path: Path, language: str) -> str:
    segments, info = model.transcribe(
        str(wav_path),
        language=language or None,
        vad_filter=True,
        beam_size=5,
    )
    text = "".join(segment.text for segment in segments).strip()
    print(f"STT language={info.language}, probability={info.language_probability:.3f}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="智慧藥盒本機 STT → Django RAG → 本機 TTS")
    parser.add_argument("--drug", required=True, help="英文學名、品牌、NDC，或已在 Django 建立對照的中文名")
    parser.add_argument("--question", help="直接提供文字；省略時由麥克風錄音")
    parser.add_argument("--user-name", default=os.getenv("SMARTPILL_USER_NAME", ""))
    parser.add_argument("--model", default=os.getenv("WHISPER_MODEL", "small"), help="faster-whisper 模型名或本機路徑")
    parser.add_argument("--device", default=os.getenv("ALSA_DEVICE", "default"))
    parser.add_argument("--record-seconds", type=int, default=7)
    parser.add_argument("--stt-language", default="zh", help="Whisper 語言代碼；台語可先嘗試 zh 或自動偵測留空")
    parser.add_argument("--no-speak", action="store_true")
    args = parser.parse_args()

    question = (args.question or "").strip()
    if not question:
        print("載入本機 faster-whisper 模型…")
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            print(f"開始錄音 {args.record_seconds} 秒，請說出問題…")
            record_wav(wav_path, seconds=args.record_seconds, device=args.device)
            question = transcribe(model, wav_path, args.stt_language)
        finally:
            wav_path.unlink(missing_ok=True)

    if not question:
        print("沒有辨識到文字，未送出 QA。")
        return 2

    print(f"問題：{question}")
    try:
        result = api_request(
            "POST",
            "qa/ask/",
            json_body={
                "user_name": args.user_name,
                "drug_name": args.drug,
                "question": question,
                "language": "zh-TW",
                "auto_sync": True,
            },
            timeout=60,
        )
    except DeviceApiError as exc:
        print(exc)
        return 1

    answer = str(result.get("answer", ""))
    print("\n=== Agent 回答 ===\n" + answer)
    print("\n=== 證據 ===")
    for item in result.get("evidence", []):
        print(
            f"- {item.get('source_label')} / {item.get('generic_name') or item.get('brand_name')} "
            f"/ {item.get('section')} / id={item.get('id')}"
        )

    if not args.no_speak:
        speak_text(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
