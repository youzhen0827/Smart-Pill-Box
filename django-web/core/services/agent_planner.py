from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import requests
from django.conf import settings

from core.services.local_minicpm import (
    LocalModelError,
    generate_json,
    model_status,
)
from core.services.qa_agent import _simplify_chinese


logger = logging.getLogger(__name__)

TOOL_LABELS = {
    "wait_until_due": "等待服藥時間",
    "send_initial_reminder": "送出到時提醒",
    "wait_for_sensor": "等待藥盒感測",
    "send_followup_reminder": "再次提醒本人",
    "request_device_check": "請照護者確認藥盒連線",
    "escalate_caregiver": "提早通知照護者",
    "mark_probable_missed": "標記疑似漏服並通知照護者",
    "confirm_sensor_event": "依感測事件完成追蹤",
}

EVIDENCE_LABELS = {
    "stage": "目前追蹤階段",
    "minutes_late": "逾時分鐘",
    "grace_minutes": "再次提醒分鐘",
    "missed_after_minutes": "漏服判定分鐘",
    "reminder_count": "提醒次數",
    "prior_taken_30d": "近 30 日已服藥紀錄",
    "prior_missed_30d": "近 30 日漏服紀錄",
    "device_health": "藥盒連線狀態",
    "device_note": "藥盒回報說明",
    "sensor_confirmed": "藥盒開啟證據",
    "risk_score": "風險分數",
    "risk_level": "風險等級",
}

_BLOCKED_REASON_PATTERN = re.compile(
    r"停藥|加量|減量|換藥|改藥|修改劑量|修改服藥時間|診斷為|治療建議"
)
_STATUS_CACHE: tuple[float, dict] = (0.0, {})


@dataclass(frozen=True)
class AgentPlan:
    planner: str
    model_name: str
    tools: list[str]
    reasoning: str
    confidence: float
    evidence_fields: list[str]
    validation_summary: str


def _safe_optional_tool(observation: dict, optional_tools: list[str]) -> str | None:
    preferred = "send_followup_reminder"
    if observation.get("risk_level") == "high":
        preferred = "escalate_caregiver"
    elif observation.get("device_health") == "offline":
        preferred = "request_device_check"
    if preferred in optional_tools:
        return preferred
    return optional_tools[0] if optional_tools else None


def _safe_reason(observation: dict, selected: str | None) -> str:
    minutes_late = observation.get("minutes_late", 0)
    if selected == "escalate_caregiver":
        return "近期有漏服紀錄且本次已逾時，提早請照護者確認較安全。"
    if selected == "request_device_check":
        return "藥盒近期沒有回報，先請照護者確認裝置與實際服藥情況。"
    if selected == "send_followup_reminder":
        return f"已超過預定時間 {minutes_late} 分鐘且尚無開盒證據，先再次提醒本人。"
    if selected == "send_initial_reminder":
        return "服藥時間已到，主動提醒本人依原排程服藥。"
    if selected == "mark_probable_missed":
        return "已超過原本設定的漏服判定時間，通知照護者確認。"
    return "依服藥時間與感測結果執行必要的安全動作。"


def _safe_evidence_fields(selected: str | None) -> list[str]:
    if selected == "escalate_caregiver":
        return ["minutes_late", "prior_missed_30d", "risk_level"]
    if selected == "request_device_check":
        return ["device_health", "device_note"]
    if selected == "send_followup_reminder":
        return ["minutes_late", "sensor_confirmed"]
    if selected == "send_initial_reminder":
        return ["stage", "minutes_late"]
    if selected == "mark_probable_missed":
        return ["minutes_late", "missed_after_minutes", "sensor_confirmed"]
    return ["stage", "risk_level"]


def _model_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"


def _models_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        clean = clean[: -len("/chat/completions")]
    if clean.endswith("/v1"):
        return f"{clean}/models"
    return f"{clean}/v1/models"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.AGENT_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.AGENT_LLM_API_KEY}"
    return headers


def _provider_label(base_url: str) -> str:
    if getattr(settings, "AGENT_LLM_BACKEND", "") == "litert_lm":
        return "MiniCPM5-2B 智慧藥盒訓練模型"
    local_markers = ("127.0.0.1:11434", "localhost:11434", "host.docker.internal:11434")
    return "Ollama 本機模型" if any(item in base_url for item in local_markers) else "OpenAI 相容模型"


def agent_runtime_status(*, probe: bool = False, force: bool = False) -> dict:
    """回報 Hybrid Agent 設定；探測失敗不影響固定安全規則。"""
    global _STATUS_CACHE

    backend = getattr(settings, "AGENT_LLM_BACKEND", "openai").strip()
    base_url = settings.AGENT_LLM_BASE_URL.strip()
    model = settings.AGENT_LLM_MODEL.strip()
    local_status = model_status() if backend == "litert_lm" else None
    configured = bool(model and (local_status is not None or base_url))
    status = {
        "mode": "hybrid",
        "provider": _provider_label(base_url),
        "configured": configured,
        "available": False,
        "model": model,
        "planner": "llm" if configured else "safe_policy",
        "message": "已設定本機模型；無法使用時會自動改用安全規則。" if configured else "尚未設定模型，目前使用安全規則。",
    }
    if backend == "litert_lm":
        status["available"] = bool(local_status and local_status["available"])
        status["planner"] = "llm" if status["available"] else "safe_policy"
        if status["available"]:
            status["message"] = f"{model} 已在程式內準備完成，特殊狀況會交由模型判斷。"
        elif local_status and not local_status["dependency"]:
            status["message"] = "尚未安裝 LiteRT-LM，目前使用安全規則。"
        else:
            status["message"] = f"尚未找到 {model} 模型檔，目前使用安全規則。"
        return status

    if not probe or not configured:
        return status

    now = time.monotonic()
    cached_at, cached_status = _STATUS_CACHE
    if not force and cached_status and now - cached_at < 15:
        return cached_status.copy()

    try:
        response = requests.get(
            _models_url(base_url),
            headers=_headers(),
            timeout=min(float(settings.AGENT_LLM_TIMEOUT), 2.5),
        )
        response.raise_for_status()
        model_ids = {
            str(item.get("id", ""))
            for item in response.json().get("data", [])
            if isinstance(item, dict)
        }
        status["available"] = model in model_ids
        status["planner"] = "llm" if status["available"] else "safe_policy"
        status["message"] = (
            f"{model} 已連線，特殊狀況會交由模型判斷。"
            if status["available"]
            else f"Ollama 已啟動，但尚未找到 {model}；目前使用安全規則。"
        )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        status["planner"] = "safe_policy"
        status["message"] = "Ollama 尚未連線，目前使用安全規則，提醒功能仍可運作。"
    _STATUS_CACHE = (now, status.copy())
    return status


def _tool_schemas(optional_tools: list[str], observation: dict) -> list[dict]:
    evidence_fields = [key for key in EVIDENCE_LABELS if key in observation]
    return [
        {
            "type": "function",
            "function": {
                "name": tool,
                "description": f"{TOOL_LABELS[tool]}。只能用於目前的服藥追蹤，不得更改藥品、劑量或排程。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "一至兩句容易理解的繁體中文理由",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "根據觀察資料判斷此動作合理的信心值",
                        },
                        "evidence_fields": {
                            "type": "array",
                            "items": {"type": "string", "enum": evidence_fields},
                            "minItems": 1,
                            "description": "本次判斷實際使用的 observation 欄位",
                        },
                    },
                    "required": ["reason", "confidence", "evidence_fields"],
                    "additionalProperties": False,
                },
            },
        }
        for tool in optional_tools
    ]


def _parse_arguments(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    raise ValueError("AI 模型回傳的工具參數格式錯誤")


def _validate_model_choice(
    selected: str,
    arguments: dict,
    observation: dict,
    optional_tools: list[str],
) -> tuple[str, str, float, list[str]]:
    if selected not in optional_tools:
        raise ValueError("AI 模型選擇了未授權工具")

    reason = _simplify_chinese(str(arguments.get("reason", "")))
    if not 8 <= len(reason) <= 240 or not re.search(r"[\u4e00-\u9fff]", reason):
        raise ValueError("AI 模型未提供清楚的繁體中文理由")
    if _BLOCKED_REASON_PATTERN.search(reason):
        raise ValueError("AI 模型理由包含不允許的醫療處置")

    confidence = float(arguments.get("confidence", 0))
    if not 0 <= confidence <= 1 or confidence < settings.AGENT_LLM_MIN_CONFIDENCE:
        raise ValueError("AI 模型信心不足")

    raw_evidence = arguments.get("evidence_fields", [])
    evidence_fields = list(dict.fromkeys(str(item) for item in raw_evidence))
    if not evidence_fields or any(item not in EVIDENCE_LABELS or item not in observation for item in evidence_fields):
        raise ValueError("AI 模型沒有提供可核對的觀察依據")
    return selected, reason, confidence, evidence_fields


def _model_choice(observation: dict, optional_tools: list[str]) -> tuple[str, str, float, list[str]]:
    prompt = {
        "task": "根據觀察資料選擇一個安全的下一步，協助照護者追蹤是否按時取藥。",
        "safety": [
            "不得更改藥品、劑量或服藥時間",
            "不得診斷疾病、建議停藥或提供治療處置",
            "只能呼叫提供的其中一個工具",
            "理由必須是簡短、易懂的繁體中文",
            "evidence_fields 只能填入本次確實使用的觀察欄位",
        ],
        "observation": observation,
    }
    if getattr(settings, "AGENT_LLM_BACKEND", "openai") == "litert_lm":
        evidence_fields = [key for key in EVIDENCE_LABELS if key in observation]
        arguments = generate_json(
            system_message=(
                "你是智慧藥盒的安全決策模組。只能依觀察資料選擇白名單中的一個工具，"
                "不得回答醫療知識、改藥、改量或改時間。"
            ),
            payload={**prompt, "allowed_tools": optional_tools},
            schema={
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": optional_tools},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_fields": {
                        "type": "array",
                        "items": {"type": "string", "enum": evidence_fields},
                        "minItems": 1,
                    },
                },
                "required": ["tool", "reason", "confidence", "evidence_fields"],
                "additionalProperties": False,
            },
        )
        selected = str(arguments.pop("tool", ""))
        return _validate_model_choice(selected, arguments, observation, optional_tools)

    response = requests.post(
        _model_url(settings.AGENT_LLM_BASE_URL),
        headers=_headers(),
        json={
            "model": settings.AGENT_LLM_MODEL,
            "temperature": 0,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": "你是智慧藥盒的安全決策模組。請選擇一個工具，不得回答醫療知識。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "tools": _tool_schemas(optional_tools, observation),
            "tool_choice": "required",
        },
        timeout=settings.AGENT_LLM_TIMEOUT,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        function = tool_calls[0].get("function", {})
        selected = str(function.get("name", ""))
        arguments = _parse_arguments(function.get("arguments", {}))
    else:
        content = str(message.get("content", "")).strip()
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < start:
            raise ValueError("AI 模型沒有選擇工具")
        arguments = json.loads(content[start : end + 1])
        selected = str(arguments.pop("tool", ""))
    return _validate_model_choice(selected, arguments, observation, optional_tools)


def plan_agent_action(
    *,
    observation: dict,
    required_tools: list[str],
    optional_tools: list[str],
) -> AgentPlan:
    """只讓模型在特殊狀況選擇白名單工具，任何異常都回退安全規則。"""
    fallback_tool = _safe_optional_tool(observation, optional_tools)
    fallback_tools = required_tools + ([fallback_tool] if fallback_tool else [])
    fallback_evidence = _safe_evidence_fields(fallback_tool)
    backend = getattr(settings, "AGENT_LLM_BACKEND", "openai")
    configured = bool(settings.AGENT_LLM_MODEL) and (
        backend == "litert_lm" or bool(settings.AGENT_LLM_BASE_URL)
    )
    if not optional_tools or not configured:
        return AgentPlan(
            planner="safe_policy",
            model_name="",
            tools=fallback_tools,
            reasoning=_safe_reason(observation, fallback_tool),
            confidence=1.0,
            evidence_fields=fallback_evidence,
            validation_summary="固定安全規則已通過",
        )

    try:
        selected, reason, confidence, evidence_fields = _model_choice(observation, optional_tools)
        return AgentPlan(
            planner="llm",
            model_name=settings.AGENT_LLM_MODEL,
            tools=required_tools + [selected],
            reasoning=reason,
            confidence=confidence,
            evidence_fields=evidence_fields,
            validation_summary="工具白名單、理由、信心與觀察依據均已通過",
        )
    except (
        LocalModelError,
        requests.RequestException,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("Agent model unavailable; using safe planner: %s", exc)
        return AgentPlan(
            planner="llm_fallback",
            model_name=settings.AGENT_LLM_MODEL,
            tools=fallback_tools,
            reasoning=f"AI 模型暫時無法使用；{_safe_reason(observation, fallback_tool)}",
            confidence=1.0,
            evidence_fields=fallback_evidence,
            validation_summary="模型輸出未通過或無法連線，已改用固定安全規則",
        )
