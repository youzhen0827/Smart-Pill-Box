from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests
from django.conf import settings


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


@dataclass(frozen=True)
class AgentPlan:
    planner: str
    model_name: str
    tools: list[str]
    reasoning: str


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
    return "依服藥時間與感測結果執行必要的安全動作。"


def _model_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"


def _model_choice(observation: dict, optional_tools: list[str]) -> tuple[str, str]:
    prompt = {
        "task": "從允許工具中選一個下一步，協助照護者追蹤是否按時取藥。",
        "safety": [
            "不得更改藥品、劑量或服藥時間",
            "不得診斷疾病或建議停藥",
            "只能選擇 allowed_tools 中的一個工具",
            "理由使用簡短、易懂的繁體中文",
        ],
        "observation": observation,
        "allowed_tools": optional_tools,
        "response_format": {"tool": "工具代碼", "reason": "一至兩句理由"},
    }
    headers = {"Content-Type": "application/json"}
    if settings.AGENT_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.AGENT_LLM_API_KEY}"
    response = requests.post(
        _model_url(settings.AGENT_LLM_BASE_URL),
        headers=headers,
        json={
            "model": settings.AGENT_LLM_MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "你是智慧藥盒的安全決策模組。只輸出 JSON，不得加入其他文字。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        },
        timeout=settings.AGENT_LLM_TIMEOUT,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lstrip().startswith("json"):
            content = content.lstrip()[4:].lstrip()
    data = json.loads(content)
    selected = str(data.get("tool", ""))
    if selected not in optional_tools:
        raise ValueError("AI 模型選擇了未授權工具")
    reason = str(data.get("reason", "")).strip()
    if not reason:
        raise ValueError("AI 模型未提供決策理由")
    return selected, reason[:500]


def plan_agent_action(
    *,
    observation: dict,
    required_tools: list[str],
    optional_tools: list[str],
) -> AgentPlan:
    """規劃下一步；模型只能從白名單選工具，失敗時改用本機安全規劃器。"""
    fallback_tool = _safe_optional_tool(observation, optional_tools)
    fallback_tools = required_tools + ([fallback_tool] if fallback_tool else [])
    if not optional_tools or not settings.AGENT_LLM_BASE_URL or not settings.AGENT_LLM_MODEL:
        return AgentPlan(
            planner="safe_policy",
            model_name="",
            tools=fallback_tools,
            reasoning=_safe_reason(observation, fallback_tool),
        )

    try:
        selected, reason = _model_choice(observation, optional_tools)
        return AgentPlan(
            planner="llm",
            model_name=settings.AGENT_LLM_MODEL,
            tools=required_tools + [selected],
            reasoning=reason,
        )
    except (requests.RequestException, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Agent model unavailable; using safe planner: %s", exc)
        return AgentPlan(
            planner="llm_fallback",
            model_name=settings.AGENT_LLM_MODEL,
            tools=fallback_tools,
            reasoning=f"AI 模型暫時無法使用；{_safe_reason(observation, fallback_tool)}",
        )
