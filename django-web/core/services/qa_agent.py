from __future__ import annotations

import ctypes
import html
import logging
import os
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache

import requests
from django.conf import settings
from django.utils import timezone

try:
    from opencc import OpenCC
except ImportError:
    OpenCC = None

from core.services.dataset_service import DatasetServiceError, sync_openfda
from core.services.answer_validator import AnswerClaim, validate_answer
from core.services.local_minicpm import (
    LocalModelError,
    model_ready,
    naturalize_medication_answer,
    translate_medical_text,
)
from core.services.rag_service import (
    concise_source_text,
    infer_question_types,
    question_label,
    resolve_drug_query,
    retrieve,
    section_label,
)

logger = logging.getLogger(__name__)

try:
    TRADITIONAL_CHINESE_CONVERTER = OpenCC("s2twp") if OpenCC else None
except Exception:
    TRADITIONAL_CHINESE_CONVERTER = None


@dataclass
class QAResult:
    answer: str
    evidence: list[dict]
    question_type: str = "general"
    question_label: str = "藥物基本資訊"
    translated: bool = False
    auto_synced: bool = False
    sync_message: str = ""
    quality_status: str = "passed"
    quality_message: str = "Agent 已核對問題、資料來源與回答內容。"
    quality_score: int = 100
    quality_checks: list[dict] = field(default_factory=list)
    revision_count: int = 0
    resolved_drug_name: str = ""
    agent_summary: str = "已辨識問題、查找資料並完成回答檢查。"


PLAIN_PREFIX = {
    "purpose": "這顆藥的用途：",
    "indications": "為什麼要吃／可能用來治療：",
    "adverse_reactions": "可能出現的副作用：",
    "warnings": "需要特別注意：",
    "drug_interactions": "和其他藥一起使用時：",
    "dosage": "資料來源中的服用方法：",
}

NEXT_STEPS = {
    "indications": "這是藥物常見用途，不一定等於你本人服藥的原因。請以藥袋或醫師說明為準。",
    "adverse_reactions": "若出現不舒服，請記下症狀與時間並詢問醫師或藥師；若呼吸困難或臉、喉嚨腫脹，請立即就醫。",
    "warnings": "若你符合警告中提到的情況，先詢問醫師或藥師，不要自行停藥。",
    "drug_interactions": "要和其他藥一起吃前，請將西藥、中藥與保健食品清單交給藥師確認。",
    "dosage": "實際吃法以藥袋與處方為準，不要自行增減劑量。",
    "missed_dose": "先查看藥袋的漏服說明或詢問藥師，不要自行補吃兩次的份量。",
    "general": "請先確認藥袋上的藥名與查詢名稱相同，再閱讀以下資料。",
}


ENGLISH_WORD = re.compile(r"\b[A-Za-z]{3,}\b")
CHINESE_TEXT = re.compile(r"[\u3400-\u9fff]")
OFFLINE_MEDICAL_PHRASES = (
    (r"\bTreatment of Type 2 diabetes mellitus\b", "用於治療第 2 型糖尿病"),
    (r"\bTreatment of Type 1 diabetes mellitus\b", "用於治療第 1 型糖尿病"),
    (r"\bType 2 diabetes mellitus\b", "第 2 型糖尿病"),
    (r"\bType 1 diabetes mellitus\b", "第 1 型糖尿病"),
    (r"\bhigh blood pressure\b", "高血壓"),
    (r"\bhypertension\b", "高血壓"),
    (r"\bheart failure\b", "心臟衰竭"),
    (r"\bacterial infections?\b", "細菌感染"),
    (r"\ballergic rhinitis\b", "過敏性鼻炎"),
    (r"\bnausea and vomiting\b", "噁心和嘔吐"),
    (r"\bTreatment of\b", "用於治療"),
    (r"\bUsed to treat\b", "用於治療"),
    (r"\bPrevention of\b", "用於預防"),
    (r"\bRelief of\b", "用於緩解"),
)
OFFLINE_MEDICAL_TERMS = {
    "Gastroesophageal reflux disease (Acid reflux)": "胃食道逆流（胃酸逆流）",
    "Sneezing and runny nose due to allergies": "過敏引起的打噴嚏和流鼻水",
    "Skin conditions with inflammation & itching": "皮膚發炎和發癢",
    "Dementia in Parkinson's disease": "巴金森氏症引起的失智症",
    "Chronic obstructive pulmonary disease (COPD)": "慢性阻塞性肺病",
    "Angina (heart-related chest pain)": "心絞痛（心臟引起的胸痛）",
    "Systemic lupus erythematosus (SLE)": "全身性紅斑性狼瘡",
    "Nausea and vomiting in pregnancy": "懷孕期間的噁心和嘔吐",
    "Treatment and prevention of": "用於治療及預防",
    "Type 2 diabetes mellitus": "第 2 型糖尿病",
    "Type 1 diabetes mellitus": "第 1 型糖尿病",
    "Pain due to muscle spasm": "肌肉痙攣引起的疼痛",
    "Post menopausal osteoporosis": "停經後骨質疏鬆症",
    "Resistance Tuberculosis (TB)": "抗藥性結核病",
    "Resistant Tuberculosis (TB)": "抗藥性結核病",
    "Benign prostatic hyperplasia": "良性攝護腺肥大",
    "Primary biliary cirrhosis": "原發性膽汁性肝硬化",
    "Hormone replacement therapy": "荷爾蒙補充治療",
    "Age related memory loss": "年齡增加造成的記憶力下降",
    "Bacterial & parasitic infections": "細菌和寄生蟲感染",
    "Prevention of heart attack and stroke": "預防心臟病發作和中風",
    "Moderate to severe pain": "中度到重度疼痛",
    "Nausea and vomiting": "噁心和嘔吐",
    "Peptic ulcer disease": "消化性潰瘍",
    "Functional dyspepsia": "功能性消化不良",
    "Irritable bowel syndrome": "腸躁症",
    "Severe bacterial infections": "嚴重細菌感染",
    "Respiratory tract infection": "呼吸道感染",
    "Bacterial eye infections": "眼睛細菌感染",
    "Bacterial skin infections": "皮膚細菌感染",
    "Fungal skin infections": "皮膚黴菌感染",
    "Bacterial infections": "細菌感染",
    "Fungal infections": "黴菌感染",
    "Parasitic infections": "寄生蟲感染",
    "Worm infections": "寄生蟲感染",
    "Allergic skin conditions": "過敏性皮膚問題",
    "Allergic conditions": "過敏症狀",
    "Inflammatory conditions": "發炎疾病",
    "Autoimmune conditions": "自體免疫疾病",
    "Nutritional deficiencies": "營養不足",
    "Diabetic nerve pain": "糖尿病神經痛",
    "Neuropathic pain": "神經痛",
    "Rheumatic disorder": "風濕性疾病",
    "Allergic rhinitis": "過敏性鼻炎",
    "Female infertility": "女性不孕症",
    "Erectile dysfunction": "勃起功能障礙",
    "Gallbladder stones": "膽結石",
    "Meniere's disease": "梅尼爾氏症",
    "Epilepsy/Seizures": "癲癇／抽搐",
    "Bipolar disorder": "雙相情緒障礙症",
    "Anxiety disorder": "焦慮症",
    "Panic disorder": "恐慌症",
    "Alzheimer's disease": "阿茲海默症",
    "Common cold": "一般感冒",
    "High cholesterol": "高膽固醇",
    "Vitamin B12 deficiency": "維生素 B12 缺乏",
    "Cough with mucus": "有痰的咳嗽",
    "Abdominal cramp": "腹部絞痛",
    "Abdominal pain": "腹痛",
    "Menstrual pain": "經痛",
    "Muscular pain": "肌肉疼痛",
    "Pain relief": "緩解疼痛",
    "Dry cough": "乾咳",
    "Short term anxiety": "短期焦慮",
    "Blood clots": "血栓",
    "organ rejection in transplant patients": "移植病人的器官排斥",
    "heart attack": "心臟病發作",
    "Heart failure": "心臟衰竭",
    "Hypertension": "高血壓",
    "Arrhythmia": "心律不整",
    "Migraine": "偏頭痛",
    "Schizophrenia": "思覺失調症",
    "Depression": "憂鬱症",
    "Anxiety": "焦慮",
    "Insomnia": "失眠",
    "Fibromyalgia": "纖維肌痛症",
    "Osteoarthritis": "退化性關節炎",
    "Acidity": "胃酸過多",
    "Heartburn": "胃灼熱",
    "Stomach ulcers": "胃潰瘍",
    "Intestinal ulcers": "腸道潰瘍",
    "Constipation": "便祕",
    "Diarrhea": "腹瀉",
    "Dysentery": "痢疾",
    "Bloating": "腹脹",
    "Vomiting": "嘔吐",
    "Nausea": "噁心",
    "Cough": "咳嗽",
    "Fever": "發燒",
    "Malaria": "瘧疾",
    "Scabies": "疥瘡",
    "Gout": "痛風",
    "Acne": "青春痘",
    "Cancer": "癌症",
    "Stroke": "中風",
    "Head injury": "頭部受傷",
    "Edema": "水腫",
    "Swelling": "腫脹",
    "Bleeding": "出血",
    "Skin infections": "皮膚感染",
    "Skin disorders": "皮膚疾病",
    "Eye disorders": "眼睛疾病",
    "Muscle relaxation": "放鬆肌肉",
    "Appetite stimulant": "幫助增加食慾",
    "Hay fever": "花粉症",
}
TRANSLATION_UNAVAILABLE_TEXT = (
    "這段藥物資料目前無法自動翻成中文。為避免翻錯，系統沒有顯示英文原文；"
    "請稍後再試，或請家人、醫師或藥師協助查看下方資料來源。"
)

UNRELATED_CONTENT = re.compile(
    r"(?:大哥大|廣告|促銷|優惠|訂閱|按讚|分享|購物|客服專線|手機門號|電信方案|"
    r"點擊(?:此處|連結)|這是(?:幾句|一段).{0,16}(?:簡述|摘要)|我是(?:一個)?AI|作為AI)",
    re.IGNORECASE,
)


def _clean_medical_source(text: str) -> str:
    """移除標記、控制字元及明顯與藥物無關的廣告內容。"""

    cleaned = html.unescape(text or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", cleaned)
    parts = re.split(r"(?<=[。！？!?;；])\s*|\n+", cleaned)
    kept = [part.strip() for part in parts if part.strip() and not UNRELATED_CONTENT.search(part)]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def _chinese_bigrams(text: str) -> set[str]:
    chars = "".join(re.findall(r"[\u3400-\u9fff]", text or ""))
    return {chars[index : index + 2] for index in range(max(0, len(chars) - 1))}


def _generated_answer_is_grounded(candidate: str, trusted_text: str) -> bool:
    """逐句檢查改寫內容；任何無來源句子都讓系統使用安全回退答案。"""

    cleaned = _simplify_chinese(candidate)
    if (
        not cleaned
        or len(cleaned) > 700
        or UNRELATED_CONTENT.search(cleaned)
        or re.search(r"自行(?:停藥|加量|減量|換藥)|改變劑量|一次吃兩倍", cleaned)
    ):
        return False
    trusted_bigrams = _chinese_bigrams(trusted_text)
    if not trusted_bigrams:
        return False
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?;；])\s*|\n+", cleaned)
        if part.strip()
    ]
    if not sentences:
        return False
    for sentence in sentences:
        chars = "".join(re.findall(r"[\u3400-\u9fff]", sentence))
        if len(chars) < 4:
            continue
        overlap = _chinese_bigrams(sentence) & trusted_bigrams
        required = 1 if len(chars) < 8 else 2
        if len(overlap) < required:
            return False
    return True


def _has_english_words(text: str) -> bool:
    return bool(ENGLISH_WORD.search(text or ""))


def _simplify_chinese(text: str) -> str:
    """轉為台灣繁體並整理機器翻譯用語，讓句子較適合長輩閱讀。"""

    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if TRADITIONAL_CHINESE_CONVERTER and cleaned:
        cleaned = TRADITIONAL_CHINESE_CONVERTER.convert(cleaned)
    elif os.name == "nt" and cleaned:
        try:
            mapper = ctypes.windll.kernel32.LCMapStringEx
            mapper.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_ssize_t,
            ]
            mapper.restype = ctypes.c_int
            output = ctypes.create_unicode_buffer(len(cleaned) + 1)
            if mapper(
                "zh-TW",
                0x04000000,
                cleaned,
                len(cleaned),
                output,
                len(output),
                None,
                None,
                0,
            ):
                cleaned = output.value
        except (AttributeError, OSError):
            pass

    replacements = {
        "不良反應": "副作用",
        "不良反应": "副作用",
        "患者": "病人",
        "給藥": "用藥",
        "给药": "用藥",
        "服用本品": "吃這個藥",
        "本品": "這個藥",
        "治療": "治療",
        "治疗": "治療",
        "藥物": "藥物",
        "药物": "藥物",
        "劑量": "劑量",
        "剂量": "劑量",
        "醫師": "醫師",
        "医师": "醫師",
        "處方": "處方",
        "处方": "處方",
        "嚴重": "嚴重",
        "严重": "嚴重",
        "過敏": "過敏",
        "过敏": "過敏",
        "與": "與",
        "与": "與",
        "鹽": "鹽",
        "釋放": "釋放",
        "飲食": "飲食",
        "輔料": "輔助",
        "鍛煉": "運動",
        "鍛鍊": "運動",
        "延伸釋放片": "緩釋錠",
        "延長釋放片": "緩釋錠",
        "被指為": "用於",
        "飲食的輔助和運動": "搭配飲食控制和運動",
        "甘油控制": "血糖控制",
        "2型糖尿病": "第 2 型糖尿病",
    }
    cleaned = re.sub(
        r"\bINDICATIONS?\s*&\s*USAGE\b[:：]?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", cleaned)
    return cleaned


def _offline_medical_translation(text: str) -> str:
    translated = text
    for pattern, replacement in OFFLINE_MEDICAL_PHRASES:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    for phrase in sorted(OFFLINE_MEDICAL_TERMS, key=len, reverse=True):
        translated = re.sub(
            re.escape(phrase),
            OFFLINE_MEDICAL_TERMS[phrase],
            translated,
            flags=re.IGNORECASE,
        )
    return _simplify_chinese(translated)


def _usable_translation(original: str, translated: str) -> bool:
    return bool(
        translated.strip()
        and translated.strip() != original.strip()
        and CHINESE_TEXT.search(translated)
    )


def _translate_with_libre(text: str, base_url: str, api_key: str) -> str:
    payload = {"q": text, "source": "en", "target": "zh", "format": "text"}
    if api_key:
        payload["api_key"] = api_key
    response = requests.post(f"{base_url}/translate", json=payload, timeout=30)
    response.raise_for_status()
    return response.json().get("translatedText", "").strip()


def _translation_chunks(text: str, max_chars: int = 450) -> list[str]:
    sentences = re.split(r"(?<=[.!?;])\s+|\n+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            split_at = sentence.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            head, sentence = sentence[:split_at].strip(), sentence[split_at:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _translate_service_chunk(text: str, service_url: str) -> str:
    if "mymemory.translated.net" in service_url.lower():
        params = {"q": text, "langpair": "en|zh-TW"}
    else:
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-TW",
            "dt": "t",
            "q": text,
        }
    response = requests.get(
        service_url,
        params=params,
        timeout=getattr(settings, "AUTOMATIC_TRANSLATE_TIMEOUT", 15),
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        translated = str(payload.get("responseData", {}).get("translatedText", "")).strip()
        if payload.get("responseStatus") not in (None, 200, "200"):
            return ""
        if "MYMEMORY WARNING" in translated.upper():
            return ""
        return translated
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        return "".join(
            segment[0]
            for segment in payload[0]
            if isinstance(segment, list) and segment and isinstance(segment[0], str)
        ).strip()
    return ""


def _translate_with_automatic_service(text: str, service_url: str) -> str:
    translated_chunks = []
    for chunk in _translation_chunks(text):
        translated = _translate_service_chunk(chunk, service_url)
        if not _usable_translation(chunk, translated):
            return ""
        translated_chunks.append(translated)
    return " ".join(translated_chunks)


@lru_cache(maxsize=512)
def _translate_cached(text: str, base_url: str, api_key: str, service_url: str) -> tuple[str, bool]:
    offline_text = _offline_medical_translation(text)
    if not _has_english_words(offline_text):
        return offline_text, offline_text != text

    if model_ready():
        try:
            translated = translate_medical_text(text)
            if _usable_translation(text, translated):
                return _simplify_chinese(translated), True
        except LocalModelError as exc:
            logger.warning("MiniCPM5-2B translation unavailable: %s", exc)

    if base_url:
        try:
            translated = _translate_with_libre(text, base_url, api_key)
            if _usable_translation(text, translated):
                return _simplify_chinese(translated), True
        except Exception as exc:
            logger.warning("LibreTranslate unavailable: %s", exc)

    if service_url:
        try:
            translated = _translate_with_automatic_service(text, service_url)
            if _usable_translation(text, translated):
                return _simplify_chinese(translated), True
        except Exception as exc:
            logger.warning("Automatic translation unavailable: %s", exc)

    return TRANSLATION_UNAVAILABLE_TEXT, False


def _translate_to_zh(text: str) -> tuple[str, bool]:
    """自動將英文證據翻成易懂中文，不把失敗的整段英文直接顯示給長輩。"""

    base_url = getattr(settings, "LIBRETRANSLATE_URL", "").strip().rstrip("/")
    if not text.strip() or not _has_english_words(text):
        return text, False
    api_key = getattr(settings, "LIBRETRANSLATE_API_KEY", "").strip()
    service_url = getattr(settings, "AUTOMATIC_TRANSLATE_URL", "").strip()
    return _translate_cached(text, base_url, api_key, service_url)


def _plain_excerpt(text: str, *, max_chars: int = 700) -> str:
    """只截取來源內容，不補寫醫療事實；讓朗讀長度適合長輩。"""

    cleaned = _clean_medical_source(text)
    if len(cleaned) <= max_chars:
        return cleaned

    # 優先在句點、分號或中文句號切斷，避免 TTS 朗讀超長段落。
    clipped = cleaned[:max_chars]
    stops = [clipped.rfind(mark) for mark in ("。", ". ", "; ", "；")]
    cut = max(stops)
    if cut >= int(max_chars * 0.55):
        clipped = clipped[: cut + 1]
    return clipped.rstrip() + "…"


def _focused_excerpt(text: str, *, max_chars: int = 320, max_sentences: int = 2) -> str:
    """只保留最前面的重點句，避免朗讀整段 FDA 標籤。"""

    cleaned = re.sub(r"\s+", " ", text or "").strip()
    cleaned = re.sub(
        r"^(?:DRUG INTERACTIONS|ADVERSE REACTIONS|DOSAGE AND ADMINISTRATION|"
        r"藥物交互作用|副作用(?:／不良反應)?|服用方法與劑量)\s*[:：-]*\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?;；])\s*|(?<=\.)\s+", cleaned)
        if part.strip()
    ]
    selected: list[str] = []
    for sentence in sentences:
        if selected and len(" ".join(selected + [sentence])) > max_chars:
            break
        selected.append(sentence)
        if len(selected) >= max_sentences or len(" ".join(selected)) >= max_chars:
            break
    focused = " ".join(selected) or cleaned
    if len(focused) > max_chars:
        focused = focused[:max_chars].rstrip()
    if len(focused) < len(cleaned) and not focused.endswith("…"):
        focused += "…"
    return focused


def _can_auto_sync(query: str) -> bool:
    resolved = resolve_drug_query(query)
    # openFDA 主要以英文字段或 Product NDC 查詢；純中文且沒有 Drug 對照時不盲查。
    return bool(re.search(r"[A-Za-z]", resolved) or re.fullmatch(r"[0-9\-]+", resolved))


def _review_answer(
    *,
    question_types: list[str],
    used_sections: set[str],
    content_text: str,
    evidence_count: int,
    language: str,
) -> tuple[str, str]:
    """用可重現規則檢查回答是否相關、有依據、精簡且適合中文閱讀。"""
    if evidence_count == 0:
        return "insufficient_evidence", "資料不足，Agent 已停止推測並改為請使用者詢問醫師或藥師。"

    expected = set()
    for question_type in question_types:
        if question_type in {"missed_dose", "dosage"}:
            expected.add("dosage")
        elif question_type == "indications":
            expected.update({"purpose", "indications"})
        elif question_type != "general":
            expected.add(question_type)
    relevant = not expected or bool(expected & used_sections)
    concise = len(content_text) <= max(420, 360 * max(1, len(used_sections)))
    review_text = re.sub(r"\b(?:FDA|USP|NDC|API)\b", "", content_text)
    if language.lower().startswith("zh"):
        readable = (
            TRANSLATION_UNAVAILABLE_TEXT not in content_text
            and bool(CHINESE_TEXT.search(review_text))
            and not _has_english_words(review_text)
        )
    else:
        readable = bool(review_text.strip())
    if relevant and concise and readable:
        return "passed", "問題類型、回答區段、資料來源、長度與中文內容均已核對。"
    failed = []
    if not relevant:
        failed.append("回答沒有對到問題類型")
    if not concise:
        failed.append("回答過長")
    if not readable:
        failed.append("中文內容仍不完整")
    return "blocked", "、".join(failed) + "；Agent 已停止顯示可能不合理的內容。"


def answer_medication_question(
    drug_query: str,
    question: str,
    *,
    language: str = "zh-TW",
    auto_sync: bool = False,
) -> QAResult:
    drug_query = (drug_query or "").strip()
    question = (question or "").strip()
    if not drug_query or not question:
        raise ValueError("藥物名稱與問題不得為空。")

    question_types = infer_question_types(question)
    answer_type = "+".join(question_types)
    answer_label = question_label(question)
    resolved = resolve_drug_query(drug_query)

    evidences = retrieve(drug_query, question, limit=5)
    auto_synced = False
    sync_message = ""

    if not evidences and auto_sync:
        if _can_auto_sync(resolved):
            try:
                sync_result = sync_openfda(resolved, limit=8)
                auto_synced = True
                sync_message = (
                    f"已從 openFDA 即時同步 NDC {sync_result.ndc_results} 筆、"
                    f"Drug Label {sync_result.label_results} 筆。"
                )
                evidences = retrieve(drug_query, question, limit=5)
            except DatasetServiceError as exc:
                sync_message = f"openFDA 自動同步失敗：{exc}"
        else:
            sync_message = "純中文藥名尚未對應到英文學名；請先在藥物資料中填入 FDA 英文學名或 Product NDC。"

    if not evidences:
        detail = f"\n{sync_message}" if sync_message else ""
        return QAResult(
            answer=(
                f"目前沒有足夠內容回答「{question}」，所以我不會隨便猜。\n\n"
                "請先查看藥袋，或直接詢問醫師、藥師，會比較安全。"
                f"{detail}"
            ),
            evidence=[],
            question_type=answer_type,
            question_label=answer_label,
            auto_synced=auto_synced,
            sync_message=sync_message,
            quality_status="insufficient_evidence",
            quality_message="資料不足，Agent 已停止推測並改為請使用者詢問醫師或藥師。",
            quality_score=0,
            quality_checks=[
                {
                    "code": "evidence",
                    "label": "每個重點都有資料來源",
                    "passed": False,
                    "critical": True,
                }
            ],
            resolved_drug_name=resolved,
            agent_summary="已辨識問題，但沒有找到足夠且可核對的資料，因此不自行推測。",
        )

    claims: list[AnswerClaim] = []
    evidence_payload: list[dict] = []
    translated_any = False
    seen_sections: set[str] = set()

    for item in evidences:
        if item.section_name in seen_sections:
            continue
        seen_sections.add(item.section_name)

        source_text = _plain_excerpt(
            concise_source_text(item.section_text, max_chars=520), max_chars=420
        )
        display_text = source_text
        translated = False
        if language.lower().startswith("zh"):
            display_text, translated = _translate_to_zh(source_text)
            translated_any = translated_any or translated
            display_text = _focused_excerpt(display_text)
        else:
            display_text = _focused_excerpt(display_text)

        doc = item.document
        claims.append(
            AnswerClaim(
                section=item.section_name,
                display_text=display_text,
                source_text=source_text,
                evidence_id=doc.id,
                brand_name=doc.brand_name,
                generic_name=doc.generic_name,
                product_ndc=doc.product_ndc,
                source_id=doc.source_id,
            )
        )
        evidence_payload.append(
            {
                "id": doc.id,
                "source_type": doc.source_type,
                "source_label": doc.get_source_type_display(),
                "source_id": doc.source_id,
                "brand_name": doc.brand_name,
                "generic_name": doc.generic_name,
                "product_ndc": doc.product_ndc,
                "section": item.section_name,
                "section_label": section_label(item.section_name),
                "source_url": doc.source_url,
                "retrieved_at": timezone.localtime(doc.retrieved_at).isoformat(),
            }
        )

    report = validate_answer(
        drug_query=drug_query,
        resolved_name=resolved,
        question=question,
        language=language,
        claims=claims,
    )
    revision_count = 0
    if not report.passed and claims:
        revised_claims = [
            replace(
                claim,
                display_text=_focused_excerpt(
                    claim.display_text,
                    max_chars=220,
                    max_sentences=1,
                ),
            )
            for claim in claims
        ]
        revised_report = validate_answer(
            drug_query=drug_query,
            resolved_name=resolved,
            question=question,
            language=language,
            claims=revised_claims,
        )
        if revised_report.score > report.score:
            claims = revised_claims
            report = revised_report
            revision_count = 1

    blocks = [claim.display_text.strip() for claim in claims if claim.display_text.strip()]

    next_steps = []
    for item in question_types:
        guidance = NEXT_STEPS.get(item, NEXT_STEPS["general"])
        if guidance not in next_steps:
            next_steps.append(guidance)
    guidance_text = "\n".join(next_steps)
    answer = "\n\n".join(blocks) + f"\n\n提醒你：{guidance_text}"
    if report.passed and language.lower().startswith("zh") and model_ready():
        try:
            natural_answer = naturalize_medication_answer(
                drug_name=drug_query,
                question=question,
                facts=" ".join(blocks),
                safety_note=guidance_text,
            )
            natural_answer = _simplify_chinese(natural_answer)
            if _generated_answer_is_grounded(
                natural_answer,
                trusted_text=" ".join(blocks + [guidance_text]),
            ):
                answer = natural_answer
            else:
                revision_count += 1
                logger.warning("MiniCPM5-2B rewrite rejected by grounding guardrail")
        except LocalModelError as exc:
            logger.warning("MiniCPM5-2B answer rewrite unavailable: %s", exc)
    quality_status = "passed" if report.passed else "blocked"
    if not report.passed:
        answer = (
            "這次找到的內容和你的問題不夠吻合，我先不顯示，避免讓你誤會。\n\n"
            "請換一個更明確的問法，或帶著藥袋詢問醫師、藥師。"
        )
    return QAResult(
        answer=answer,
        evidence=evidence_payload,
        question_type=answer_type,
        question_label=answer_label,
        translated=translated_any,
        auto_synced=auto_synced,
        sync_message=sync_message,
        quality_status=quality_status,
        quality_message=report.summary,
        quality_score=report.score,
        quality_checks=[item.as_dict() for item in report.checks],
        revision_count=revision_count,
        resolved_drug_name=resolved,
        agent_summary=(
            f"我已找出和「{answer_label}」最相關的內容，並完成來源與安全檢查。"
        ),
    )
