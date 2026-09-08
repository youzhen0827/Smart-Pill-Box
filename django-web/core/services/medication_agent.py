from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.slots import SLOT_COUNT, slot_label
from core.models import (
    AgentIntervention,
    MedicationLog,
    MedicationSchedule,
    Reminder,
    SensorEvent,
)


@dataclass
class AgentCycleResult:
    schedules_checked: int = 0
    reminders_created: int = 0
    reminders_checked: int = 0
    matched_sensor_events: int = 0
    interventions_created: int = 0
    missed_marked: int = 0

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
    """執行一次狀態追蹤 Agent 狀態機。"""
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
            _mark_taken_from_event(reminder, sensor_event)
            result.matched_sensor_events += 1
            continue

        due = reminder.scheduled_datetime
        if now < due:
            if reminder.agent_state != "pending":
                reminder.agent_state = "pending"
                reminder.save(update_fields=["agent_state", "updated_at"])
            continue

        schedule = reminder.schedule
        grace_minutes = schedule.grace_minutes if schedule else 10
        missed_after_minutes = schedule.missed_after_minutes if schedule else 60
        grace_at = due + timedelta(minutes=grace_minutes)
        missed_at = due + timedelta(minutes=missed_after_minutes)

        _, created = _create_intervention(
            reminder,
            "initial_reminder",
            f"{reminder.user_name}，現在是 {reminder.scheduled_time}，請服用 {reminder.medicine_name} {reminder.dose_count} 粒。",
        )
        if created:
            reminder.reminder_count += 1
            result.interventions_created += 1

        if now < grace_at:
            reminder.agent_state = "waiting_sensor"
            reminder.save(update_fields=["agent_state", "reminder_count", "updated_at"])
            continue

        if now < missed_at:
            _, created = _create_intervention(
                reminder,
                "sensor_missing",
                f"服藥時間已到 {grace_minutes} 分鐘，感測器仍未偵測到{slot_label(reminder.slot)}藥格開啟，Agent 已再次提醒。",
            )
            if created:
                reminder.reminder_count += 1
                result.interventions_created += 1
            reminder.agent_state = "intervened"
            reminder.save(update_fields=["agent_state", "reminder_count", "updated_at"])
            continue

        reminder.status = "漏服"
        reminder.agent_state = "missed"
        reminder.save(update_fields=["status", "agent_state", "reminder_count", "updated_at"])
        result.missed_marked += 1
        _, created = _create_intervention(
            reminder,
            "missed_escalation",
            f"{reminder.user_name} 的 {reminder.medicine_name} 已超過 {missed_after_minutes} 分鐘仍未偵測到開盒，系統判定為漏服，請照護者確認。",
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

    return result
