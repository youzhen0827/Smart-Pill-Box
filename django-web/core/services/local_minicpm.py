from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from typing import Any

from django.conf import settings


class LocalModelError(RuntimeError):
    pass


_ENGINE = None
_ENGINE_LOCK = threading.RLock()
_MIN_TRAINED_MODEL_BYTES = 2_400_000_000


def model_path() -> Path:
    return Path(settings.AGENT_MODEL_PATH).expanduser().resolve()


def runtime_available() -> bool:
    return importlib.util.find_spec("litert_lm") is not None


def model_ready() -> bool:
    path = model_path()
    return (
        runtime_available()
        and path.is_file()
        and path.stat().st_size >= _MIN_TRAINED_MODEL_BYTES
    )


def model_status() -> dict[str, Any]:
    path = model_path()
    dependency = runtime_available()
    exists = path.is_file() and path.stat().st_size >= _MIN_TRAINED_MODEL_BYTES
    return {
        "dependency": dependency,
        "model_exists": exists,
        "path": str(path),
        "backend": settings.AGENT_LITERT_BACKEND,
        "available": dependency and exists,
    }


def _configured_backend(litert_lm):
    backend = settings.AGENT_LITERT_BACKEND
    factories = {
        "cpu": litert_lm.Backend.CPU,
        "gpu": litert_lm.Backend.GPU,
        "npu": litert_lm.Backend.NPU,
    }
    factory = factories.get(backend)
    if factory is None:
        raise LocalModelError(
            f"不支援的 AGENT_LITERT_BACKEND：{backend}，請使用 cpu、gpu 或 npu"
        )
    return factory()


def _engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        status = model_status()
        if not status["dependency"]:
            raise LocalModelError("尚未安裝 litert-lm，請先執行 pip install -r requirements.txt")
        if not status["model_exists"]:
            raise LocalModelError(f"找不到 MiniCPM5-2B 模型：{status['path']}")

        import litert_lm

        cache_dir = Path(settings.AGENT_MODEL_CACHE_DIR).expanduser().resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            try:
                litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            except (AttributeError, TypeError):
                pass
            _ENGINE = litert_lm.Engine(
                str(model_path()),
                backend=_configured_backend(litert_lm),
                max_num_tokens=4096,
                cache_dir=str(cache_dir),
            )
        except Exception as exc:
            raise LocalModelError(f"MiniCPM5-2B 載入失敗：{exc}") from exc
        return _ENGINE


def _response_text(response: Any) -> str:
    if isinstance(response, dict):
        content = response.get("content", [])
        if isinstance(content, list):
            return "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip()
    return str(response or "").strip()


def generate_text(
    *,
    system_message: str,
    user_message: str,
    max_output_tokens: int = 384,
    response_schema: dict | None = None,
) -> str:
    import litert_lm

    with _ENGINE_LOCK:
        try:
            conversation_options = {
                "system_message": system_message,
                "sampler_config": litert_lm.SamplerConfig(
                    top_k=8,
                    top_p=0.8,
                    temperature=0.05,
                    seed=7,
                ),
                "thinking_config": litert_lm.ThinkingConfig(enable_thinking=False),
                "max_output_tokens": max_output_tokens,
            }
            if response_schema:
                conversation_options["constrained_decoding_config"] = (
                    litert_lm.ConstrainedDecodingConfig(
                        enable=True,
                        provider=litert_lm.LiteRtLmConstraintProviderType.LL_GUIDANCE,
                    )
                )
            with _engine().create_conversation(
                **conversation_options,
            ) as conversation:
                kwargs = {
                    "max_output_tokens": max_output_tokens,
                    "thinking_config": litert_lm.ThinkingConfig(enable_thinking=False),
                }
                if response_schema:
                    kwargs["response_format"] = litert_lm.ResponseFormat.json(response_schema)
                response = conversation.send_message(user_message, **kwargs)
        except LocalModelError:
            raise
        except Exception as exc:
            raise LocalModelError(f"MiniCPM5-2B 推論失敗：{exc}") from exc

    text = _response_text(response)
    if not text:
        raise LocalModelError("MiniCPM5-2B 沒有回傳內容")
    return text


def generate_json(*, system_message: str, payload: dict, schema: dict) -> dict:
    text = generate_text(
        system_message=system_message,
        user_message=json.dumps(payload, ensure_ascii=False),
        max_output_tokens=320,
        response_schema=schema,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end >= start:
            return json.loads(text[start : end + 1])
        raise LocalModelError("MiniCPM5-2B 回傳內容不是有效 JSON") from exc


def generate_medication_reminder(
    *,
    tool: str,
    user_name: str,
    medicine_name: str,
    dose_count: str,
    scheduled_time: str,
    slot_name: str,
    reminder_hint: str,
    observation: dict,
) -> str:
    context = {
        "提醒目的": tool,
        "稱呼": user_name,
        "藥物": medicine_name,
        "原排程劑量": dose_count,
        "原排程時間": scheduled_time,
        "藥格": slot_name,
        "服藥備註": reminder_hint,
        "逾時分鐘": observation.get("minutes_late", 0),
        "提醒次數": observation.get("reminder_count", 0),
        "近30日漏服次數": observation.get("prior_missed_30d", 0),
        "藥盒連線": observation.get("device_health", "unknown"),
        "藥盒狀態說明": observation.get("device_note", ""),
        "風險等級": observation.get("risk_level", "low"),
        "再次提醒門檻": observation.get("grace_minutes", 10),
        "漏服判定門檻": observation.get("missed_after_minutes", 30),
    }
    return generate_text(
        system_message=(
            "你是經過智慧藥盒提醒情境訓練的台灣繁體中文照護助理。"
            "請依提供的真實狀態，寫出要直接顯示在手機通知上的一至兩個自然短句。"
            "語氣要像熟悉長輩的照護者，溫和、清楚、不責備；逾時或高風險時可以更明確，"
            "但不得恐嚇。只能使用輸入中的姓名、藥物、劑量、時間、裝置與紀錄，"
            "不得新增疾病、療效、醫囑或數字，不得改藥、改量、改時間、要求停藥或補吃。"
            "除非是『請勿自行改藥或改量』這類安全警語，否則不要提及改藥、停藥或加減量。"
            "必須提到稱呼與藥物；到時提醒也必須保留原排程劑量。"
            "不要輸出標題、引號、JSON、條列、模型說明、檢查分數或『根據資料』。"
        ),
        user_message=(
            f"提醒情境：{json.dumps(context, ensure_ascii=False)}\n"
            "請直接輸出這次通知文字。"
        ),
        max_output_tokens=128,
    )


def translate_medical_text(text: str) -> str:
    return generate_text(
        system_message=(
            "你是耐心的台灣藥師助理。只能整理來源文字，不得補充來源沒有的療效、"
            "劑量或治療建議。請用台灣繁體中文與長輩聽得懂的日常短句回答，刪除章節號、"
            "條文編號與重複標題，保留必要的藥名、數字及單位。不要提到翻譯或資料處理，"
            "直接說明重點。"
        ),
        user_message=f"請把下列藥物資料自然地說給長輩聽，使用二至三句話：\n{text}",
        max_output_tokens=512,
    )


def naturalize_medication_answer(
    *,
    drug_name: str,
    question: str,
    facts: str,
    safety_note: str,
) -> str:
    return generate_text(
        system_message=(
            "你是智慧藥盒裡耐心、可信賴的台灣藥師助理。只能使用提供的資料重點回答，"
            "不得新增療效、疾病、劑量、交互作用或停藥建議。用台灣繁體中文，像面對長輩"
            "說話一樣自然、溫和、清楚。直接回答問題，不要使用【標題】、章節號、檢查分數、"
            "資料筆數或『根據資料』等系統文字。禁止出現廣告、促銷、新聞、電信、購物、"
            "模型自述或與藥物無關的句子。每一句都必須能在提供的資料或安全提醒中找到依據。"
            "控制在二至四個短句。"
        ),
        user_message=(
            "正確示例：資料寫『用於控制高血壓』，回答『這顆藥常用來控制高血壓。』\n"
            "錯誤示例：加入廣告、未提供的疾病或自行改藥建議。這些內容一律不可輸出。\n\n"
            f"藥物：{drug_name}\n"
            f"使用者問題：{question}\n"
            f"可使用的資料重點：{facts}\n"
            f"最後必須自然提醒：{safety_note}"
        ),
        max_output_tokens=420,
    )
