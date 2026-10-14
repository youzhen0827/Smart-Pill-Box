from django.core.management.base import BaseCommand

from core.services.agent_planner import agent_runtime_status


class Command(BaseCommand):
    help = "檢查第 8 版 Hybrid AI Agent 是否已準備好 MiniCPM5-2B 智慧藥盒訓練模型。"

    def handle(self, *args, **options):
        status = agent_runtime_status(probe=True, force=True)
        message = (
            f"模式：{status['mode']}\n"
            f"提供者：{status['provider']}\n"
            f"模型：{status['model'] or '未設定'}\n"
            f"狀態：{status['message']}"
        )
        if status["available"]:
            self.stdout.write(self.style.SUCCESS(message))
        else:
            self.stdout.write(self.style.WARNING(message))
