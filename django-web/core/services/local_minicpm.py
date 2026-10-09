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


def model_path() -> Path:
    return Path(settings.AGENT_MODEL_PATH).expanduser().resolve()


def runtime_available() -> bool:
    return importlib.util.find_spec("litert_lm") is not None


def model_ready() -> bool:
    path = model_path()
    return runtime_available() and path.is_file() and path.stat().st_size > 1_000_000_000


def model_status() -> dict[str, Any]:
    path = model_path()
    dependency = runtime_available()
    exists = path.is_file() and path.stat().st_size > 1_000_000_000
    return {
        "dependency": dependency,
        "model_exists": exists,
        "path": str(path),
        "available": dependency and exists,
    }


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
                backend=litert_lm.Backend.CPU(),
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
