from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.slots import SLOT_COUNT, slot_label
from core.models import (
    AgentDecision,
    AgentIntervention,
    MedicationLog,
    MedicationSchedule,
    PillBoxDevice,
    Reminder,
    SensorEvent,
)
from core.services.agent_planner import TOOL_LABELS, plan_agent_action


@dataclass
class AgentCycleResult:
    schedules_checked: int = 0
    reminders_created: int = 0
    reminders_checked: int = 0
    matched_sensor_events: int = 0
    interventions_created: int = 0
    missed_marked: int = 0
    decisions_created: int = 0
    tools_executed: int = 0
    unchanged_events_skipped: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _aware_for_date(target_date, target_time):
    value = datetime.combine(target_date, target_time)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _create_intervention(reminder: Reminder, intervention_type: str, message: str):
    obj, created = AgentIntervention.objects.get_or_create(
        reminder=reminder,
        intervention_type=intervention_type,
        defaults={
            "message": message,
            "state": "created",
            "channel": "dashboard+device",
        },
    )
    return obj, created


def ensure_daily_reminders(now=None) -> int:
    now = now or timezone.now()
    local_date = timezone.localdate(now)
    created_count = 0

    schedules = MedicationSchedule.objects.filter(
        is_active=True, slot__range=(1, SLOT_COUNT)
    ).select_related(
        "elder", "drug", "elder__owner"
    )
    for schedule in schedules:
        if not schedule.runs_on(local_date):
            continue
        scheduled_dt = _aware_for_date(local_date, schedule.scheduled_time)
        reminder, created = Reminder.objects.get_or_create(
            schedule=schedule,
            scheduled_datetime=scheduled_dt,
            defaults={
                "owner": schedule.elder.owner,
                "user_name": schedule.elder.name,
                "user_age": str(schedule.elder.age),
                "medicine_name": schedule.drug.name_zh,
                "scheduled_time": timezone.localtime(scheduled_dt).strftime("%I:%M %p"),
                "dose_count": schedule.dose_count,
                "reminder_hint": schedule.reminder_hint,
                "slot": schedule.slot,
                "device_id": schedule.device_id,
                "source": "schedule",
                "status": "已提醒",
                "agent_state": "pending",
                "reminder_count": 0,
            },
        )
        if created:
            created_count += 1
        MedicationLog.objects.get_or_create(
            reminder=reminder,
            defaults={
                "schedule": schedule,
                "status": "reminded",
                "scheduled_dt": scheduled_dt,
                "reminder_count": reminder.reminder_count,
            },
        )
    return created_count


def _sensor_match_for_reminder(reminder: Reminder, now) -> SensorEvent | None:
    if not reminder.scheduled_datetime:
        return None
    start = reminder.scheduled_datetime - timedelta(minutes=5)
    query = SensorEvent.objects.filter(
        event_type="opened",
        slot__range=(1, SLOT_COUNT),
        detected_at__gte=start,
        detected_at__lte=now,
    ).filter(Q(matched_reminder__isnull=True) | Q(matched_reminder=reminder))
    if reminder.device_id:
        query = query.filter(device_id=reminder.device_id)
    if reminder.slot:
        query = query.filter(slot=reminder.slot)
    if reminder.user_name:
        query = query.filter(Q(user_name="") | Q(user_name__iexact=reminder.user_name))
    return query.order_by("detected_at").first()


def mark_reminder_taken(
    reminder: Reminder,
    *,
    at=None,
    source: str = "web",
    sensor_event: SensorEvent | None = None,
) -> Reminder:
    """以 Android、網頁或感測器完成任務，並同步 Log 與 Agent 介入狀態。"""

    taken_at = at or timezone.now()
    reminder.mark_taken(at=taken_at, source=source)

    if sensor_event and sensor_event.matched_reminder_id != reminder.id:
        sensor_event.matched_reminder = reminder
        sensor_event.save(update_fields=["matched_reminder"])

    AgentIntervention.objects.filter(reminder=reminder).exclude(state="closed").update(
        state="closed",
        acknowledged_at=taken_at,
    )

    if reminder.schedule_id and reminder.scheduled_datetime:
        MedicationLog.objects.update_or_create(
            reminder=reminder,
            defaults={
                "schedule": reminder.schedule,
                "status": "taken",
                "scheduled_dt": reminder.scheduled_datetime,
                "taken_at": taken_at,
                "reminder_count": reminder.reminder_count,
            },
        )
    return reminder


def _mark_taken_from_event(reminder: Reminder, event: SensorEvent) -> None:
    mark_reminder_taken(
        reminder,
        at=event.detected_at,
        source="sensor",
        sensor_event=event,
    )


def _device_health(reminder: Reminder, now) -> tuple[str, str, str]:
    if not reminder.device_id:
        return "not_configured", "未指定裝置", "not_configured"
    device = PillBoxDevice.objects.filter(device_id=reminder.device_id).first()
    event_seen = (
        SensorEvent.objects.filter(device_id=reminder.device_id)
        .order_by("-detected_at")
        .values_list("detected_at", flat=True)
        .first()
    )
    seen_times = [value for value in (device.last_seen_at if device else None, event_seen) if value]
    last_seen = max(seen_times) if seen_times else None
    if last_seen is None:
        return "unknown", "尚無裝置回報", "never_seen"
    age_minutes = max(0, int((now - last_seen).total_seconds() // 60))
    if age_minutes > 15:
        if age_minutes > 7 * 24 * 60:
            return "offline", "超過 7 天沒有回報", "over_week"
        if age_minutes >= 24 * 60:
            return "offline", f"約 {age_minutes // (24 * 60)} 天沒有回報", "days"
        if age_minutes >= 60:
            return "offline", f"約 {age_minutes // 60} 小時沒有回報", "hours"
        return "offline", f"已 {age_minutes} 分鐘沒有回報", "minutes"
    return "online", f"{age_minutes} 分鐘前有回報", "recent"


def _observe(reminder: Reminder, now, stage: str) -> dict:
    minutes_late = max(0, int((now - reminder.scheduled_datetime).total_seconds() // 60))
    schedule = reminder.schedule
    history = MedicationLog.objects.none()
    if schedule:
        history = MedicationLog.objects.filter(
            schedule__elder=schedule.elder,
            scheduled_dt__gte=now - timedelta(days=30),
        ).exclude(reminder=reminder)
    prior_missed = history.filter(status="missed").count()
    prior_taken = history.filter(status="taken").count()
    device_health, device_note, device_age_bucket = _device_health(reminder, now)
    risk_score = min(35, minutes_late // 2) + min(40, prior_missed * 15)
    risk_score += min(15, reminder.reminder_count * 5)
    if device_health == "offline":
        risk_score += 10
    risk_score = min(100, risk_score)
    risk_level = "high" if risk_score >= 60 else "medium" if risk_score >= 30 else "low"
    observation = {
        "stage": stage,
        "minutes_late": minutes_late,
        "grace_minutes": schedule.grace_minutes if schedule else 10,
        "missed_after_minutes": schedule.missed_after_minutes if schedule else 30,
        "reminder_count": reminder.reminder_count,
        "prior_taken_30d": prior_taken,
        "prior_missed_30d": prior_missed,
        "device_health": device_health,
        "device_note": device_note,
        "device_age_bucket": device_age_bucket,
        "sensor_confirmed": stage == "sensor_confirmed",
        "risk_score": risk_score,
        "risk_level": risk_level,
    }
    observation["event_key"] = "|".join(
        str(observation[item])
        for item in (
            "stage",
            "risk_level",
            "device_health",
            "device_age_bucket",
            "prior_missed_30d",
        )
    )
    return observation


def _tool_options(stage: str) -> tuple[list[str], list[str]]:
    if stage == "before_due":
        return ["wait_until_due"], []
    if stage == "sensor_confirmed":
        return ["confirm_sensor_event"], []
    if stage == "due_window":
        return ["wait_for_sensor"], ["send_initial_reminder"]
    if stage == "follow_up_window":
        return ["send_initial_reminder"], [
            "send_followup_reminder",
            "request_device_check",
            "escalate_caregiver",
        ]
    return ["send_initial_reminder"], ["mark_probable_missed"]


def _contextual_reminder_message(tool: str, reminder: Reminder, observation: dict) -> str:
    name = reminder.user_name or "您好"
    medicine = reminder.medicine_name
    dose = reminder.dose_count
    minutes_late = observation["minutes_late"]
    prior_missed = observation["prior_missed_30d"]
    device_offline = observation["device_health"] == "offline"
    local_time = timezone.localtime(reminder.scheduled_datetime).strftime("%H:%M")

    if tool == "send_initial_reminder":
        if device_offline:
            return (
                f"{name}，現在 {local_time} 該服用 {medicine} {dose}。"
                "藥盒目前沒有回報，服藥後請在手機按「已服用」。"
            )
        if prior_missed >= 2:
            return (
                f"{name}，現在 {local_time} 該服用 {medicine} {dose}。"
                f"最近 30 天有 {prior_missed} 次沒有按時確認，這次服藥後記得開啟藥盒。"
            )
        return f"{name}，現在 {local_time} 該服用 {medicine} {dose}。{reminder.reminder_hint}"

    if tool == "send_followup_reminder":
        if device_offline:
            return (
                f"已超過服藥時間 {minutes_late} 分鐘，但藥盒目前沒有回報。"
                f"請確認 {name} 是否已服用 {medicine}，並在手機留下結果。"
            )
        if prior_missed >= 2 or observation["risk_level"] == "high":
            return (
                f"{name}，{medicine} 已晚了 {minutes_late} 分鐘，仍未偵測到開盒。"
                f"最近 30 天另有 {prior_missed} 次漏服紀錄，請現在確認。"
            )
        return (
            f"{name}，{medicine} 已超過預定時間 {minutes_late} 分鐘，"
            f"仍未偵測到{slot_label(reminder.slot)}藥格開啟。請確認是否已服用。"
        )

    if tool == "request_device_check":
        return (
            f"{reminder.device_id or '藥盒'}目前沒有回報，AI 無法用開盒資料確認是否服藥。"
            f"請照護者聯絡 {name}，並檢查藥盒電源或網路。"
        )

    if tool == "escalate_caregiver":
        history = f"最近 30 天已有 {prior_missed} 次漏服紀錄，" if prior_missed else ""
        return (
            f"{history}{name} 這次服用 {medicine} 已晚了 {minutes_late} 分鐘，"
            "仍沒有開盒或人工確認。請照護者協助確認。"
        )

    return (
        f"{name} 的 {medicine} 已超過原定時間 {observation['missed_after_minutes']} 分鐘，"
        "仍沒有服藥證據，AI 已標記為疑似漏服，請照護者確認。"
    )


def _execute_agent_tool(
    tool: str,
    reminder: Reminder,
    observation: dict,
    result: AgentCycleResult,
    *,
    sensor_event: SensorEvent | None = None,
) -> dict:
    result.tools_executed += 1
    if tool in {"wait_until_due", "wait_for_sensor"}:
        return {"state": "waiting", "message": TOOL_LABELS[tool]}
    if tool == "confirm_sensor_event" and sensor_event:
        _mark_taken_from_event(reminder, sensor_event)
        result.matched_sensor_events += 1
        return {"state": "completed", "event_id": sensor_event.id}
    if tool == "send_initial_reminder":
        _, created = _create_intervention(
            reminder,
            "initial_reminder",
            _contextual_reminder_message(tool, reminder, observation),
        )
        if created:
            reminder.reminder_count += 1
            result.interventions_created += 1
        return {"state": "created" if created else "already_exists"}
    if tool == "send_followup_reminder":
        _, created = _create_intervention(
            reminder,
            "sensor_missing",
            _contextual_reminder_message(tool, reminder, observation),
        )
        if created:
            reminder.reminder_count += 1
            result.interventions_created += 1
        return {"state": "created" if created else "already_exists"}
    if tool == "request_device_check":
        _, created = _create_intervention(
            reminder,
            "device_check",
            _contextual_reminder_message(tool, reminder, observation),
        )
        if created:
            result.interventions_created += 1
        return {"state": "created" if created else "already_exists"}
    if tool == "escalate_caregiver":
        _, created = _create_intervention(
            reminder,
            "caregiver_escalation",
            _contextual_reminder_message(tool, reminder, observation),
        )
        if created:
            result.interventions_created += 1
        return {"state": "created" if created else "already_exists"}
    if tool == "mark_probable_missed":
        newly_missed = reminder.status != "漏服"
        reminder.status = "漏服"
        reminder.agent_state = "missed"
        if newly_missed:
            result.missed_marked += 1
        _, created = _create_intervention(
            reminder,
            "missed_escalation",
            _contextual_reminder_message(tool, reminder, observation),
        )
        if created:
            result.interventions_created += 1
        if reminder.schedule_id:
            MedicationLog.objects.update_or_create(
                reminder=reminder,
                defaults={
                    "schedule": reminder.schedule,
                    "status": "missed",
                    "scheduled_dt": reminder.scheduled_datetime,
                    "taken_at": None,
                    "reminder_count": reminder.reminder_count,
                },
            )
        return {"state": "marked", "notification_created": created}
    return {"state": "rejected", "message": "工具不在允許清單"}


def _remember_decision(reminder, stage, observation, available_tools, plan, outcomes):
    decision, created = AgentDecision.objects.update_or_create(
        reminder=reminder,
        stage=stage,
        defaults={
            "planner": plan.planner,
            "model_name": plan.model_name,
            "risk_score": observation["risk_score"],
            "risk_level": observation["risk_level"],
            "observation": observation,
            "available_tools": available_tools,
            "planned_tools": plan.tools,
            "reasoning": plan.reasoning,
            "execution_result": {
                **outcomes,
                "_agent_validation": {
                    "passed": True,
                    "confidence": round(plan.confidence, 2),
                    "evidence_fields": plan.evidence_fields,
                    "summary": plan.validation_summary,
                },
            },
        },
    )
    return decision, created


@transaction.atomic
def match_sensor_event(event: SensorEvent) -> Reminder | None:
    """把真實藥盒開啟事件配對至最接近的未完成服藥任務。"""
    if event.event_type != "opened":
        return None

    earliest = event.detected_at - timedelta(hours=4)
    latest = event.detected_at + timedelta(minutes=15)
    query = Reminder.objects.filter(
        Q(slot__isnull=True) | Q(slot__range=(1, SLOT_COUNT)),
        status="已提醒",
        scheduled_datetime__gte=earliest,
        scheduled_datetime__lte=latest,
    )
    if event.device_id:
        query = query.filter(Q(device_id=event.device_id) | Q(device_id=""))
    if event.slot:
        query = query.filter(Q(slot=event.slot) | Q(slot__isnull=True))
    if event.user_name:
        query = query.filter(user_name__iexact=event.user_name)

    candidates = list(query.select_related("schedule").order_by("scheduled_datetime")[:30])
    if not candidates:
        return None
    reminder = min(
        candidates,
        key=lambda candidate: abs((candidate.scheduled_datetime - event.detected_at).total_seconds()),
    )
    _mark_taken_from_event(reminder, event)
    return reminder


@transaction.atomic
def run_agent_cycle(now=None) -> AgentCycleResult:
    """執行一次「觀察 → 評估 → 規劃 → 使用工具 → 記憶」Agent 循環。"""
    now = now or timezone.now()
    result = AgentCycleResult()
    result.schedules_checked = MedicationSchedule.objects.filter(
        is_active=True, slot__range=(1, SLOT_COUNT)
    ).count()
    result.reminders_created = ensure_daily_reminders(now)

    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    reminders = Reminder.objects.filter(
        Q(slot__isnull=True) | Q(slot__range=(1, SLOT_COUNT)),
        status="已提醒",
        scheduled_datetime__isnull=False,
        scheduled_datetime__gte=start,
        scheduled_datetime__lte=end,
    ).select_related("schedule", "schedule__elder", "schedule__drug")

    for reminder in reminders:
        result.reminders_checked += 1
        sensor_event = _sensor_match_for_reminder(reminder, now)
        if sensor_event:
            stage = "sensor_confirmed"
        else:
            due = reminder.scheduled_datetime
            schedule = reminder.schedule
            grace_minutes = schedule.grace_minutes if schedule else 10
            missed_after_minutes = schedule.missed_after_minutes if schedule else 30
            if now < due:
                stage = "before_due"
            elif now < due + timedelta(minutes=grace_minutes):
                stage = "due_window"
            elif now < due + timedelta(minutes=missed_after_minutes):
                stage = "follow_up_window"
            else:
                stage = "overdue"

        observation = _observe(reminder, now, stage)
        previous_decision = AgentDecision.objects.filter(
            reminder=reminder, stage=stage
        ).first()
        if (
            previous_decision
            and previous_decision.observation.get("event_key") == observation["event_key"]
        ):
            result.unchanged_events_skipped += 1
            continue

        required_tools, optional_tools = _tool_options(stage)
        available_tools = required_tools + optional_tools
        plan = plan_agent_action(
            observation=observation,
            required_tools=required_tools,
            optional_tools=optional_tools,
        )
        outcomes = {
            tool: _execute_agent_tool(
                tool, reminder, observation, result, sensor_event=sensor_event
            )
            for tool in plan.tools
        }

        if stage == "before_due":
            reminder.agent_state = "pending"
        elif stage == "due_window":
            reminder.agent_state = "waiting_sensor"
        elif stage == "follow_up_window":
            reminder.agent_state = "intervened"
        if stage != "sensor_confirmed":
            reminder.save(
                update_fields=["status", "agent_state", "reminder_count", "updated_at"]
            )
        _, created = _remember_decision(
            reminder, stage, observation, available_tools, plan, outcomes
        )
        if created:
            result.decisions_created += 1

    return result
