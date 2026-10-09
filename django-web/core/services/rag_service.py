from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from django.db.models import Q

from core.models import Drug, DrugKnowledgeDocument


@dataclass
class RetrievedEvidence:
    document: DrugKnowledgeDocument
    score: float
    section_name: str
    section_text: str


CATEGORY_KEYWORDS = {
    "missed_dose": ["忘記吃", "忘了吃", "漏吃", "少吃", "missed dose", "forgot to take"],
    "dosage": ["怎麼吃", "如何服用", "吃幾顆", "吃幾次", "劑量", "用量", "飯前", "飯後", "dose", "dosage", "how to take"],
    "adverse_reactions": ["副作用", "不良反應", "不舒服", "adverse", "side effect", "reaction"],
    "drug_interactions": [
        "交互作用",
        "其他藥",
        "一起吃",
        "一起服用",
        "一起使用",
        "併用",
        "interaction",
        "interact",
    ],
    "warnings": ["警告", "注意", "不能吃", "禁忌", "warning", "caution", "avoid"],
    "indications": ["為什麼", "做什麼", "幹嘛", "藥效", "功效", "用途", "治療", "indication", "use", "purpose", "what for"],
}

SECTION_LABELS = {
    "purpose": "用途",
    "indications": "適應症與功效",
    "adverse_reactions": "副作用／不良反應",
    "warnings": "警告與注意事項",
    "drug_interactions": "藥物交互作用",
    "dosage": "服用方法與劑量",
}

QUESTION_LABELS = {
    "missed_dose": "忘記服藥怎麼處理",
    "dosage": "服用方法與劑量",
    "adverse_reactions": "可能的副作用",
    "drug_interactions": "能否與其他藥一起使用",
    "warnings": "警告與注意事項",
    "indications": "藥物用途",
    "general": "藥物基本資訊",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text)
    english = set(re.findall(r"[a-z0-9][a-z0-9\-]{1,}", normalized))
    chinese_chunks = re.findall(r"[\u3400-\u9fff]+", normalized)
    chinese: set[str] = set()
    for chunk in chinese_chunks:
        chinese.add(chunk)
        if len(chunk) >= 2:
            chinese.update(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return english | chinese


def resolve_drug_query(drug_query: str) -> str:
    """將網站中文顯示名稱轉成 FDA 可檢索的學名。"""
    cleaned = (drug_query or "").strip()
    if not cleaned:
        return ""
    drug = Drug.objects.filter(
        Q(name_zh__iexact=cleaned)
        | Q(generic_name__iexact=cleaned)
        | Q(fda_product_ndc__iexact=cleaned)
    ).first()
    if drug:
        return drug.generic_name or drug.fda_product_ndc or drug.name_zh
    return cleaned


def infer_question_types(question: str) -> list[str]:
    q = _normalize(question)
    selected: list[str] = []
    for question_type, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in q for keyword in keywords):
            selected.append(question_type)
    if "drug_interactions" in selected and "dosage" in selected:
        dosage_details = ("劑量", "用量", "吃幾", "幾次", "飯前", "飯後", "dose", "dosage")
        if not any(keyword in q for keyword in dosage_details):
            selected.remove("dosage")
    return selected or ["general"]


def infer_sections(question: str) -> list[str]:
    selected: list[str] = []
    for question_type in infer_question_types(question):
        if question_type in {"missed_dose", "dosage"}:
            selected.append("dosage")
        elif question_type != "general":
            selected.append(question_type)
    if not selected:
        return ["purpose", "indications"]
    if "indications" in selected:
        selected.insert(0, "purpose")
    return list(dict.fromkeys(selected))


def question_label(question: str) -> str:
    return "、".join(QUESTION_LABELS[item] for item in infer_question_types(question))


def _raw_value(value) -> str:
    if isinstance(value, list):
        return " ".join(_raw_value(item) for item in value if item is not None).strip()
    if isinstance(value, dict):
        return " ".join(_raw_value(item) for item in value.values() if item is not None).strip()
    return str(value or "").strip()


def _section_text(document: DrugKnowledgeDocument, section_name: str) -> str:
    if section_name != "dosage":
        return getattr(document, section_name, "") or ""
    raw = document.raw_json or {}
    sources = [raw]
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        sources.append(raw["data"])
    keys = (
        "dosage_and_administration",
        "dosage",
        "dose",
        "directions",
        "instructions_for_use",
        "patient_information",
        "用法用量",
    )
    values: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = _raw_value(source.get(key))
            if value:
                values.append(value)
    return "\n".join(dict.fromkeys(values))


def _document_candidates(drug_query: str):
    resolved = resolve_drug_query(drug_query)
    if not resolved:
        return DrugKnowledgeDocument.objects.none(), resolved
    candidates = DrugKnowledgeDocument.objects.filter(
        Q(generic_name__icontains=resolved)
        | Q(brand_name__icontains=resolved)
        | Q(product_ndc__icontains=resolved)
        | Q(source_id__iexact=resolved)
    )
    if not candidates.exists():
        pieces = [piece for piece in re.split(r"[,/()]", resolved) if len(piece.strip()) >= 3]
        query = Q()
        for piece in pieces[:4]:
            value = piece.strip()
            query |= Q(generic_name__icontains=value) | Q(brand_name__icontains=value)
        candidates = DrugKnowledgeDocument.objects.filter(query) if query else candidates
    return candidates[:500], resolved


def retrieve(drug_query: str, question: str, *, limit: int = 4) -> list[RetrievedEvidence]:
    candidates, resolved = _document_candidates(drug_query)
    query_tokens = _tokens(f"{resolved} {question}")
    name_tokens = _tokens(resolved)
    requested_sections = infer_sections(question)
    evidence: list[RetrievedEvidence] = []

    for doc in candidates:
        doc_name_tokens = _tokens(f"{doc.generic_name} {doc.brand_name} {doc.product_ndc}")
        exact_bonus = 0.0
        resolved_norm = _normalize(resolved)
        if resolved_norm and resolved_norm in _normalize(f"{doc.generic_name} {doc.brand_name} {doc.product_ndc}"):
            exact_bonus = 12.0
        name_overlap = len(name_tokens & doc_name_tokens) * 4.0

        for section_name in requested_sections:
            section_text = _section_text(doc, section_name)
            if not section_text.strip():
                continue
            section_tokens = _tokens(section_text)
            overlap = len(query_tokens & section_tokens)
            length_penalty = math.log10(max(len(section_text), 10)) * 0.15
            source_bonus = {
                "tfda_license": 4.0,
                "openfda_label": 3.0,
                "openfda_ndc": 2.0,
                "kaggle_csv": 1.0,
            }.get(doc.source_type, 0.0)
            score = exact_bonus + name_overlap + overlap * 1.6 + source_bonus - length_penalty
            evidence.append(
                RetrievedEvidence(
                    document=doc,
                    score=score,
                    section_name=section_name,
                    section_text=section_text,
                )
            )

    evidence.sort(key=lambda item: (item.score, item.document.retrieved_at), reverse=True)
    selected: list[RetrievedEvidence] = []
    seen: set[tuple[int, str]] = set()
    for item in evidence:
        key = (item.document.id, item.section_name)
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def section_label(section_name: str) -> str:
    return SECTION_LABELS.get(section_name, section_name)


def concise_source_text(text: str, *, max_chars: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    last_stop = max(cut.rfind(". "), cut.rfind("。"), cut.rfind("; "))
    if last_stop > max_chars * 0.55:
        cut = cut[: last_stop + 1]
    return cut.rstrip() + "…"
