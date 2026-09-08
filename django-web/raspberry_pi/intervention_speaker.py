#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time

from common import DeviceApiError, api_request, speak_text


def main() -> int:
    parser = argparse.ArgumentParser(description="輪詢 Django Agent 介入訊息並在藥盒本機朗讀")
    parser.add_argument("--device-id", default=os.getenv("SMARTPILL_DEVICE_ID", "pillbox-01"))
    parser.add_argument("--user-name", default=os.getenv("SMARTPILL_USER_NAME", ""))
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    spoken_in_session: set[int] = set()
    while True:
        try:
            payload = api_request(
                "GET",
                "agent/interventions/",
                params={
                    "device_id": args.device_id,
                    "user_name": args.user_name,
                    "state": "created",
                },
            )
            for item in payload.get("results", []):
                item_id = int(item["id"])
                if item_id in spoken_in_session:
                    continue
                message = str(item.get("message", "")).strip()
                if not message:
                    continue
                print(f"朗讀 Agent 介入 #{item_id}: {message}")
                speak_text(message)
                api_request(
                    "POST",
                    f"agent/interventions/{item_id}/state/",
                    json_body={"state": "delivered"},
                )
                spoken_in_session.add(item_id)
        except (DeviceApiError, RuntimeError, ValueError) as exc:
            print(f"介入輪詢錯誤：{exc}")

        if args.once:
            return 0
        time.sleep(max(2, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
