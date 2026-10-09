from __future__ import annotations

import re
from dataclasses import dataclass

from core.services.rag_service import infer_sections


@dataclass(frozen=True)
class AnswerClaim:
    section: str
    display_text: str
    source_text: str
    evidence_id: int
    brand_name: str = ""
    generic_name: str = ""
    product_ndc: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class ValidationCheck:
    code: str
    label: str
    passed: bool
    critical: bool

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "passed": self.passed,
            "critical": self.critical,
        }


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    score: int
    summary: str
    checks: tuple[ValidationCheck, ...]


def _identity_text(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9\u3400-\u9fff]+", (value or "").casefold()))


def identity_match_score(
    drug_query: str,
    resolved_name: str,
    *,
    brand_name: str = "",
    generic_name: str = "",
    product_ndc: str = "",
    source_id: str = "",
) -> float:
    """Return a conservative identity score so similarly named drugs are not mixed."""

    queries = {_identity_text(drug_query), _identity_text(resolved_name)} - {""}
    candidates = {
        _identity_text(brand_name),
        _identity_text(generic_name),
        _identity_text(product_ndc),
        _identity_text(source_id),
    } - {""}
    if not queries or not candidates:
        return 0.0
    if queries & candidates:
        return 1.0
    for query in queries:
        for candidate in candidates:
            shorter = min(len(query), len(candidate))
            if shorter >= 4 and (query in candidate or candidate in query):
                return 0.9
    query_tokens = set(re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]{2,}", f"{drug_query} {resolved_name}".casefold()))
    candidate_tokens = set(
        re.findall(
            r"[a-z0-9]{3,}|[\u3400-\u9fff]{2,}",
            f"{brand_name} {generic_name} {product_ndc} {source_id}".casefold(),
        )
    )
    overlap = query_tokens & candidate_tokens
    return 0.7 if overlap else 0.0


def _expected_sections(question: str) -> set[str]:
    return set(infer_sections(question))


def _remaining_english(text: str, removable_terms: list[str]) -> bool:
    cleaned = text or ""
    for term in sorted((item for item in removable_terms if item), key=len, reverse=True):
        cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:FDA|USP|NDC|API|HIV|AIDS|COVID|COPD|mg|mcg|ml|mL)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return bool(re.search(r"\b[A-Za-z]{3,}\b", cleaned))


def validate_answer(
    *,
    drug_query: str,
    resolved_name: str,
    question: str,
    language: str,
    claims: list[AnswerClaim],
) -> ValidationReport:
    evidence_ok = bool(claims) and all(claim.evidence_id and claim.source_text.strip() for claim in claims)
    identity_ok = bool(claims) and all(
        identity_match_score(
            drug_query,
            resolved_name,
            brand_name=claim.brand_name,
            generic_name=claim.generic_name,
            product_ndc=claim.product_ndc,
            source_id=claim.source_id,
        )
        >= 0.7
        for claim in claims
    )
    expected = _expected_sections(question)
    relevance_ok = bool(claims) and all(claim.section in expected for claim in claims)
    combined = " ".join(claim.display_text for claim in claims).strip()
    if language.lower().startswith("zh"):
        removable = [drug_query, resolved_name]
        for claim in claims:
            removable.extend([claim.brand_name, claim.generic_name])
        language_ok = (
            bool(re.search(r"[\u3400-\u9fff]", combined))
            and not _remaining_english(combined, removable)
            and "目前無法自動翻成中文" not in combined
        )
    else:
        language_ok = bool(combined)
    concise_ok = len(combined) <= max(360, 320 * max(1, len(claims)))
    unsafe = re.search(r"(?:請|可以)?自行(?:停藥|加量|減量|改藥)|一次吃兩倍|取代醫師", combined)
    safety_ok = unsafe is None

    checks = (
        ValidationCheck("evidence", "每個重點都有資料來源", evidence_ok, True),
        ValidationCheck("identity", "資料與查詢藥物相符", identity_ok, True),
        ValidationCheck("relevance", "內容只回答目前問題", relevance_ok, True),
        ValidationCheck("language", "中文完整且適合閱讀", language_ok, True),
        ValidationCheck("concise", "回答保持精簡", concise_ok, False),
        ValidationCheck("safety", "沒有自行停藥或改量建議", safety_ok, True),
    )
    weights = {
        "evidence": 20,
        "identity": 20,
        "relevance": 20,
        "language": 20,
        "concise": 10,
        "safety": 10,
    }
    score = sum(weights[item.code] for item in checks if item.passed)
    passed = score >= 80 and all(item.passed for item in checks if item.critical)
    failed_labels = [item.label for item in checks if not item.passed]
    summary = (
        "已核對藥名、問題、資料來源、中文與用藥安全。"
        if passed
        else f"未通過：{'、'.join(failed_labels)}。"
    )
    return ValidationReport(passed=passed, score=score, summary=summary, checks=checks)
