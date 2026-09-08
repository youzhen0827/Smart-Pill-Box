from __future__ import annotations

import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from core.services.medication_agent import run_agent_cycle


class Command(BaseCommand):
    help = "持續執行智慧藥盒狀態追蹤 Agent。"

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=settings.AGENT_POLL_SECONDS)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        interval = max(3, options["interval"])
        running = True

        def stop_handler(*_):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, stop_handler)
        signal.signal(signal.SIGTERM, stop_handler)

        while running:
            try:
                result = run_agent_cycle()
                self.stdout.write(self.style.SUCCESS(f"Agent cycle: {result.as_dict()}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Agent cycle failed: {exc}"))
            if options["once"]:
                break
            time.sleep(interval)
