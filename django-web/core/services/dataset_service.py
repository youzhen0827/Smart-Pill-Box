from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import DatasetSyncRun, Drug, DrugKnowledgeDocument

logger = logging.getLogger(__name__)

# FDA 官方 openFDA 端點。網站只保存從這些端點取回的原始 JSON 與欄位映射，
# 不會自動建立合成或示範藥物資料。
OPENFDA_NDC_URL = "https://api.fda.gov/drug/ndc.json"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"


class DatasetServiceError(RuntimeError):
    """資料集同步或匯入失敗。"""


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    ndc_results: int = 0
    label_results: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.added + self.updated


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _first(value: Any) -> str:
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    return _text(value)


def _safe_term(term: str) -> str:
    # 移除 openFDA 查詢字串中可能破壞語法的字元；保留英數、空格與 NDC 連字號。
    cleaned = re.sub(r"[\"'\\]", " ", (term or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) < 2:
        raise DatasetServiceError("查詢字至少需要 2 個字元。")
    return cleaned[:120]


def _openfda_get(url: str, *, search: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": search,
        "limit": max(1, min(int(limit), 100)),
    }
    api_key = getattr(settings, "OPENFDA_API_KEY", "").strip()
    if api_key:
        # openFDA 可不帶 API key 使用；有 key 時僅提高官方配額。
        params["api_key"] = api_key

    try:
        response = requests.get(
            url,
            params=params,
            timeout=getattr(settings, "OPENFDA_TIMEOUT", 20),
            headers={
                "User-Agent": "SmartMedicineBoxResearch/1.1 (+Django openFDA dataset sync)",
                "Accept": "application/json",
            },
        )
    except requests.RequestException as exc:
        raise DatasetServiceError(f"無法連線 openFDA：{exc}") from exc

    if response.status_code == 404:
        return []
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            detail = response.text[:300]
        raise DatasetServiceError(f"openFDA 回傳 {response.status_code}：{detail}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise DatasetServiceError("openFDA 回傳的資料不是有效 JSON。") from exc

    results = payload.get("results", [])
    if not isinstance(results, list):
        raise DatasetServiceError("openFDA JSON 缺少 results 陣列。")
    return [item for item in results if isinstance(item, dict)]


def _query_endpoint(url: str, term: str, limit: int) -> list[dict[str, Any]]:
    # 可接受 Product NDC（有無連字號）、英文學名或品牌名。
    is_ndc = bool(re.fullmatch(r"\d{4,5}-?\d{3,4}(?:-?\d{1,2})?", term))
    if url == OPENFDA_NDC_URL:
        fields = ["product_ndc"] if is_ndc else ["generic_name", "brand_name"]
    else:
        fields = ["openfda.product_ndc"] if is_ndc else ["openfda.generic_name", "openfda.brand_name"]

    merged: dict[str, dict[str, Any]] = {}
    for field in fields:
        results = _openfda_get(url, search=f'{field}:"{term}"', limit=limit)
        for item in results:
            item_id = _text(item.get("id") or item.get("product_id") or item.get("set_id"))
            if not item_id:
                item_id = hashlib.sha256(
                    json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
            merged[item_id] = item
        if len(merged) >= limit:
            break
    return list(merged.values())[:limit]


def _ensure_drug(document: dict[str, Any]) -> None:
    """讓排程表可選擇已匯入的真實藥物，不覆寫使用者的中文顯示名稱。"""

    generic_name = _text(document.get("generic_name"))[:180]
    brand_name = _text(document.get("brand_name"))[:100]
    product_ndc = _text(document.get("product_ndc"))[:50]
    display_name = brand_name or generic_name
    if not display_name:
        return

    if product_ndc:
        existing = Drug.objects.filter(fda_product_ndc=product_ndc).first()
    elif generic_name:
        existing = Drug.objects.filter(generic_name__iexact=generic_name).first()
    else:
        existing = Drug.objects.filter(name_zh__iexact=display_name).first()

    if existing:
        changed_fields: list[str] = []
        if not existing.generic_name and generic_name:
            existing.generic_name = generic_name
            changed_fields.append("generic_name")
        if not existing.fda_product_ndc and product_ndc:
            existing.fda_product_ndc = product_ndc
            changed_fields.append("fda_product_ndc")
        if changed_fields:
            existing.save(update_fields=changed_fields)
        return

    Drug.objects.create(
        name_zh=display_name,
        generic_name=generic_name,
        fda_product_ndc=product_ndc,
    )


def _upsert_ndc(record: dict[str, Any]) -> bool:
    product_ndc = _text(record.get("product_ndc"))
    source_id = _text(record.get("product_id")) or product_ndc
    if not source_id:
        source_id = hashlib.sha256(
            json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    defaults = {
        "product_ndc": product_ndc,
        "brand_name": _text(record.get("brand_name")),
        "generic_name": _text(record.get("generic_name")),
        "manufacturer": _text(record.get("labeler_name")),
        "route": _text(record.get("route")),
        "dosage_form": _text(record.get("dosage_form")),
        "purpose": "",
        "indications": "",
        "adverse_reactions": "",
        "warnings": "",
        "drug_interactions": "",
        "raw_json": record,
        "source_url": OPENFDA_NDC_URL,
        "retrieved_at": timezone.now(),
    }
    _, created = DrugKnowledgeDocument.objects.update_or_create(
        source_type="openfda_ndc", source_id=source_id[:180], defaults=defaults
    )
    _ensure_drug(defaults)
    return created


def _upsert_label(record: dict[str, Any]) -> bool:
    openfda = record.get("openfda") or {}
    source_id = _text(record.get("id") or record.get("set_id"))
    if record.get("effective_time"):
        source_id = f"{source_id}:{record['effective_time']}"
    if not source_id.strip(":"):
        source_id = hashlib.sha256(
            json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    warning_sections = [
        _text(record.get("boxed_warning")),
        _text(record.get("warnings")),
        _text(record.get("warnings_and_cautions")),
        _text(record.get("do_not_use")),
        _text(record.get("ask_doctor")),
    ]
    defaults = {
        "product_ndc": _first(openfda.get("product_ndc")),
        "brand_name": _first(openfda.get("brand_name")),
        "generic_name": _first(openfda.get("generic_name")),
        "manufacturer": _first(openfda.get("manufacturer_name")),
        "route": _text(openfda.get("route")),
        "dosage_form": _first(openfda.get("dosage_form")),
        "purpose": _text(record.get("purpose")),
        "indications": _text(record.get("indications_and_usage")),
        "adverse_reactions": _text(record.get("adverse_reactions")),
        "warnings": "\n\n".join(section for section in warning_sections if section),
        "drug_interactions": _text(record.get("drug_interactions")),
        "raw_json": record,
        "source_url": OPENFDA_LABEL_URL,
        "retrieved_at": timezone.now(),
    }
    _, created = DrugKnowledgeDocument.objects.update_or_create(
        source_type="openfda_label", source_id=source_id[:180], defaults=defaults
    )
    _ensure_drug(defaults)
    return created


def _finish_run(run: DatasetSyncRun, *, state: str, result: SyncResult, message: str) -> None:
    run.state = state
    run.records_added = result.added
    run.records_updated = result.updated
    run.message = message[:1000]
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "state",
            "records_added",
            "records_updated",
            "message",
            "finished_at",
        ]
    )


def sync_openfda(term: str, *, limit: int = 10) -> SyncResult:
    """從 FDA 官方 openFDA API 同步 NDC Directory 與 Drug Label 真實資料。"""

    cleaned = _safe_term(term)
    run = DatasetSyncRun.objects.create(source="openfda", query=cleaned)
    result = SyncResult()
    try:
        # 外部 HTTP 不放在 DB transaction 內，避免慢連線長時間鎖住資料庫。
        ndc_records = _query_endpoint(OPENFDA_NDC_URL, cleaned, limit)
        label_records = _query_endpoint(OPENFDA_LABEL_URL, cleaned, limit)
        result.ndc_results = len(ndc_records)
        result.label_results = len(label_records)

        if not (ndc_records or label_records):
            raise DatasetServiceError(f"openFDA 找不到「{cleaned}」的 NDC 或藥品標示資料。")

        with transaction.atomic():
            for record in ndc_records:
                if _upsert_ndc(record):
                    result.added += 1
                else:
                    result.updated += 1
            for record in label_records:
                if _upsert_label(record):
                    result.added += 1
                else:
                    result.updated += 1

        _finish_run(
            run,
            state="success",
            result=result,
            message=f"NDC {result.ndc_results} 筆；Drug Label {result.label_results} 筆",
        )
        return result
    except DatasetServiceError as exc:
        _finish_run(run, state="failed", result=result, message=str(exc))
        raise
    except Exception as exc:
        logger.exception("Unexpected openFDA sync error")
        _finish_run(run, state="failed", result=result, message=str(exc))
        raise DatasetServiceError(f"同步 openFDA 時發生錯誤：{exc}") from exc


def _column_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").strip().lower())


def _find_column(fieldnames: Iterable[str], aliases: Iterable[str]) -> str | None:
    normalized = {_column_key(name): name for name in fieldnames if name}
    for alias in aliases:
        found = normalized.get(_column_key(alias))
        if found:
            return found
    return None


def _find_columns(
    fieldnames: Iterable[str],
    aliases: Iterable[str],
    patterns: Iterable[str] = (),
) -> list[str]:
    """找出單欄與 numbered columns（例如 sideEffect0..sideEffect40）。"""

    ordered = [name for name in fieldnames if name]
    normalized = {name: _column_key(name) for name in ordered}
    exact = {_column_key(alias) for alias in aliases}
    regexes = [re.compile(pattern) for pattern in patterns]
    result: list[str] = []
    for name in ordered:
        key = normalized[name]
        if key in exact or any(regex.fullmatch(key) for regex in regexes):
            result.append(name)
    return result


def _joined_row_values(row: dict[str, Any], columns: Iterable[str]) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for column in columns:
        value = _text(row.get(column))
        normalized = value.casefold()
        if value and normalized not in seen:
            seen.add(normalized)
            values.append(value)
    return "\n".join(values)


def _validate_kaggle_url(dataset_url: str) -> str:
    value = (dataset_url or "").strip()
    if not value:
        return "local_csv_upload"
    if value.startswith(("recommended:", "local:", "file:")):
        return value[:500]
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return f"local:{value[:494]}"
    return value[:500]


def import_kaggle_csv(
    uploaded_file,
    *,
    original_name: str = "",
    dataset_url: str,
    max_rows: int = 100_000,
) -> SyncResult:
    """匯入使用者從 Kaggle 下載的真實 CSV；不產生任何合成資料。"""

    source_url = _validate_kaggle_url(dataset_url)
    if source_url == "local_csv_upload" and original_name:
        source_url = f"local:{original_name}"[:500]
    run = DatasetSyncRun.objects.create(source="kaggle_csv", query=source_url[:250])
    result = SyncResult()
    try:
        raw = uploaded_file.read()
        if not raw:
            raise DatasetServiceError("CSV 是空檔案。")
        if len(raw) > 25 * 1024 * 1024:
            raise DatasetServiceError("CSV 超過 25 MB，請先切分後再匯入。")

        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise DatasetServiceError("CSV 沒有欄位名稱。")

        generic_col = _find_column(
            reader.fieldnames,
            ["generic_name", "generic name", "drug_name", "drug name", "drug", "name", "medicine_name"],
        )
        brand_col = _find_column(
            reader.fieldnames,
            ["brand_name", "brand name", "brand_names", "brand names"],
        )
        # 常見 DDI 資料集會分成 Drug 1 / Drug 2，而不是單一 drug_name。
        drug1_col = _find_column(reader.fieldnames, ["drug1", "drug 1", "drug_a", "drug a", "drug_one"])
        drug2_col = _find_column(reader.fieldnames, ["drug2", "drug 2", "drug_b", "drug b", "drug_two"])

        side_cols = _find_columns(
            reader.fieldnames,
            ["side_effects", "side effects", "side effect", "side_effect", "adverse_reactions"],
            [r"sideeffects?\d*", r"adversereactions?\d*"],
        )
        interaction_cols = _find_columns(
            reader.fieldnames,
            ["drug_interactions", "drug interactions", "interactions", "interaction", "description"],
            [r"(?:drug)?interactions?\d*", r"interactiondescription\d*"],
        )
        indication_cols = _find_columns(
            reader.fieldnames,
            ["medical_condition", "medical condition", "condition", "indication", "indications", "uses", "purpose"],
            [r"uses?\d*", r"medicalconditions?\d*", r"indications?\d*", r"purpose\d*"],
        )
        warning_cols = _find_columns(
            reader.fieldnames,
            ["warnings", "warning", "contraindications", "contraindication"],
            [r"warnings?\d*", r"contraindications?\d*"],
        )
        manufacturer_col = _find_column(
            reader.fieldnames,
            ["manufacturer", "manufacturer_name", "company"],
        )

        if not (generic_col or brand_col or drug1_col) or not (
            side_cols or interaction_cols or indication_cols or warning_cols
        ):
            raise DatasetServiceError(
                "找不到必要欄位。至少需要藥名欄（或 Drug 1／Drug 2），以及副作用／交互作用／適應症／警告其中一欄。"
            )

        parsed_rows: list[tuple[int, dict[str, Any], dict[str, str]]] = []
        for row_number, row in enumerate(reader, start=2):
            if row_number - 1 > max_rows:
                raise DatasetServiceError(f"CSV 超過 {max_rows:,} 筆上限，請先切分後再匯入。")

            generic_name = _text(row.get(generic_col)) if generic_col else ""
            brand_name = _text(row.get(brand_col)) if brand_col else ""
            drug1 = _text(row.get(drug1_col)) if drug1_col else ""
            drug2 = _text(row.get(drug2_col)) if drug2_col else ""
            if not (generic_name or brand_name) and drug1:
                generic_name = f"{drug1} + {drug2}" if drug2 else drug1
            drug_name = generic_name or brand_name
            if not drug_name:
                result.skipped += 1
                continue

            side_effects = _joined_row_values(row, side_cols)
            interactions = _joined_row_values(row, interaction_cols)
            indications = _joined_row_values(row, indication_cols)
            warnings = _joined_row_values(row, warning_cols)
            if drug1 and drug2 and interactions:
                interactions = f"Drug pair: {drug1} + {drug2}\n{interactions}"
            if not (side_effects or interactions or indications or warnings):
                result.skipped += 1
                continue

            normalized = {
                "generic_name": generic_name[:250],
                "brand_name": brand_name[:250],
                "manufacturer": (_text(row.get(manufacturer_col)) if manufacturer_col else "")[:250],
                "indications": indications,
                "adverse_reactions": side_effects,
                "warnings": warnings,
                "drug_interactions": interactions,
            }
            parsed_rows.append((row_number, row, normalized))

        if not parsed_rows:
            raise DatasetServiceError("CSV 中沒有可匯入的有效資料列。")

        with transaction.atomic():
            for row_number, row, normalized in parsed_rows:
                row_hash = hashlib.sha256(
                    json.dumps(
                        {"dataset_url": source_url, "row": row},
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
                defaults = {
                    "product_ndc": "",
                    "brand_name": normalized["brand_name"],
                    "generic_name": normalized["generic_name"],
                    "manufacturer": normalized["manufacturer"],
                    "route": "",
                    "dosage_form": "",
                    "purpose": "",
                    "indications": normalized["indications"],
                    "adverse_reactions": normalized["adverse_reactions"],
                    "warnings": normalized["warnings"],
                    "drug_interactions": normalized["drug_interactions"],
                    "raw_json": {
                        "dataset_url": source_url,
                        "file": original_name,
                        "row": row_number,
                        "data": row,
                    },
                    "source_url": source_url,
                    "retrieved_at": timezone.now(),
                }
                _, created = DrugKnowledgeDocument.objects.update_or_create(
                    source_type="kaggle_csv", source_id=row_hash, defaults=defaults
                )
                if created:
                    result.added += 1
                else:
                    result.updated += 1
                _ensure_drug(defaults)

        _finish_run(
            run,
            state="success",
            result=result,
            message=f"由 {original_name or 'CSV'} 解析 {result.total} 筆；略過 {result.skipped} 筆",
        )
        return result
    except DatasetServiceError as exc:
        _finish_run(run, state="failed", result=result, message=str(exc))
        raise
    except Exception as exc:
        logger.exception("Unexpected Kaggle CSV import error")
        _finish_run(run, state="failed", result=result, message=str(exc))
        raise DatasetServiceError(f"匯入 Kaggle CSV 時發生錯誤：{exc}") from exc
