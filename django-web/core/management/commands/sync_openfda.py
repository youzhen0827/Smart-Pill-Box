from django.core.management.base import BaseCommand, CommandError

from core.services.dataset_service import DatasetServiceError, sync_openfda


class Command(BaseCommand):
    help = "從 FDA 官方 openFDA NDC 與 Drug Label API 同步真實資料。"

    def add_arguments(self, parser):
        parser.add_argument("--drug", action="append", required=True, help="英文學名、品牌名或 Product NDC；可重複使用。")
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        for term in options["drug"]:
            try:
                result = sync_openfda(term, limit=options["limit"])
            except DatasetServiceError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"{term}: added={result.added}, updated={result.updated}, "
                    f"ndc={result.ndc_results}, label={result.label_results}"
                )
            )
