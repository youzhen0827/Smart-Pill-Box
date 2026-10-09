from django.core.management.base import BaseCommand, CommandError

from core.services.dataset_service import DatasetServiceError, sync_tfda_active_licenses


class Command(BaseCommand):
    help = "同步台灣食藥署未註銷藥品許可證資料集"

    def add_arguments(self, parser):
        parser.add_argument("--archive", help="選用：已下載的官方 ZIP 或 JSON 檔")

    def handle(self, *args, **options):
        try:
            archive_path = options.get("archive")
            archive_bytes = None
            if archive_path:
                with open(archive_path, "rb") as source:
                    archive_bytes = source.read()
            result = sync_tfda_active_licenses(archive_bytes=archive_bytes)
        except DatasetServiceError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"TFDA 同步完成：新增 {result.added}、更新 {result.updated}、"
                f"略過 {result.skipped} 筆。"
            )
        )
