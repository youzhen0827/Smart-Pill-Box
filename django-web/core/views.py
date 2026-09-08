from __future__ import annotations

import json
import re
from datetime import datetime
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    AccountRegistrationForm,
    DrugForm,
    ElderForm,
    KaggleImportForm,
    MedicationScheduleForm,
    OpenFDASyncForm,
    QAForm,
    ReminderForm,
    SensorDemoForm,
    UserProfileForm,
)
from .models import (
    AgentIntervention,
    DatasetSyncRun,
    Drug,
    DrugKnowledgeDocument,
    Elder,
    MedicationSchedule,
    PillBoxDevice,
    QAConversation,
    Reminder,
    SensorEvent,
    UserProfile,
)
from .services.dataset_service import DatasetServiceError, import_kaggle_csv, sync_openfda
from .services.medication_agent import mark_reminder_taken, match_sensor_event, run_agent_cycle
from .slots import SLOT_COUNT, is_valid_slot, period_for_slot, slot_label, slot_payload
from .services.qa_agent import answer_medication_question


def home(request):
    return render(request, "core/home.html")


def split_android_names(names_text):
    if not names_text:
        return []
    normalized = (
        names_text.replace("，", ",")
        .replace("、", ",")
        .replace(";", ",")
        .replace("；", ",")
        .replace("\n", ",")
    )
    return [name.strip() for name in normalized.split(",") if name.strip()]


def get_user_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def find_owner_by_android_name(android_name):
    android_name = (android_name or "").strip()
    if not android_name:
        return None
    for profile in UserProfile.objects.select_related("user"):
        if any(name.casefold() == android_name.casefold() for name in split_android_names(profile.android_name)):
            return profile.user
    return None


def user_reminder_queryset(user):
    profile = get_user_profile(user)
    android_names = split_android_names(profile.android_name)
    query = Q(owner=user)
    if android_names:
        query |= Q(owner__isnull=True, user_name__in=android_names)
    return Reminder.objects.filter(query).filter(
        Q(slot__isnull=True) | Q(slot__range=(1, SLOT_COUNT))
    )


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AccountRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            login(request, user)
            messages.success(request, "帳號建立完成。請設定 Android 使用者姓名。")
            return redirect("android_name_settings")
    else:
        form = AccountRegistrationForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    today = timezone.localdate()
    reminders_query = user_reminder_queryset(request.user).filter(
        Q(scheduled_datetime__date=today)
        | Q(scheduled_datetime__isnull=True, created_at__date=today)
    ).order_by("scheduled_datetime", "created_at")
    stats = {
        "total": reminders_query.count(),
        "pending": reminders_query.filter(agent_state="pending").count(),
        "tracking": reminders_query.filter(agent_state__in=["waiting_sensor", "intervened"]).count(),
        "completed": reminders_query.filter(agent_state="taken").count(),
        "attention": reminders_query.filter(agent_state="missed").count(),
    }
    reminders = list(reminders_query)
    schedule_queryset = MedicationSchedule.objects.filter(elder__owner=request.user, is_active=True)
    schedules = schedule_queryset.count()
    profile_names = split_android_names(get_user_profile(request.user).android_name)
    event_queryset = SensorEvent.objects.filter(
        Q(device_record__owner=request.user) | Q(user_name__in=profile_names)
    )
    selected_device_id = request.GET.get("device_id", "").strip()
    if not selected_device_id:
        selected_device_id = (
            schedule_queryset.exclude(device_id="").values_list("device_id", flat=True).first()
            or PillBoxDevice.objects.filter(owner=request.user).values_list("device_id", flat=True).first()
            or ""
        )
    device_events = event_queryset
    if selected_device_id:
        device_events = device_events.filter(device_id=selected_device_id)
    valid_device_events = device_events.filter(slot__in=range(1, SLOT_COUNT + 1))
    recent_events = valid_device_events.select_related("matched_reminder")[:8]

    latest_by_slot = {}
    for event in valid_device_events.order_by("-detected_at")[:200]:
        if event.slot not in latest_by_slot:
            latest_by_slot[event.slot] = event
    slot_states = [
        {
            "slot": item["slot"],
            "slot_label": item["label"],
            "event": latest_by_slot.get(item["slot"]),
            "state": latest_by_slot[item["slot"]].event_type if item["slot"] in latest_by_slot else "unknown",
        }
        for item in slot_payload()
    ]

    interventions = AgentIntervention.objects.filter(
        Q(reminder__owner=request.user) | Q(reminder__user_name__in=split_android_names(get_user_profile(request.user).android_name))
    ).select_related("reminder")[:8]
    return render(
        request,
        "core/dashboard.html",
        {
            "current_user": request.user,
            "reminders": reminders,
            "stats": stats,
            "today": today,
            "schedule_count": schedules,
            "dataset_count": DrugKnowledgeDocument.objects.count(),
            "recent_events": recent_events,
            "interventions": interventions,
            "selected_device_id": selected_device_id,
            "slot_states": slot_states,
            "slot_count": SLOT_COUNT,
            "three_slot_revision": "v4",
        },
    )


@login_required
def android_name_settings(request):
    profile = get_user_profile(request.user)
    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save()
            names = split_android_names(profile.android_name)
            if names:
                Reminder.objects.filter(owner__isnull=True, user_name__in=names).update(owner=request.user)
            messages.success(request, "Android 使用者姓名名單已更新。")
            return redirect("dashboard")
    else:
        form = UserProfileForm(instance=profile)
    return render(request, "core/android_name_form.html", {"form": form, "profile": profile})


@login_required
def reminder_create(request):
    if request.method == "POST":
        form = ReminderForm(request.POST, user=request.user)
        if form.is_valid():
            reminder = form.save(commit=False)
            elder = form.cleaned_data["elder"]
            reminder.owner = request.user
            reminder.user_name = elder.name
            reminder.user_age = str(elder.age)
            reminder.source = "web"
            reminder.status = "已提醒"
            reminder.agent_state = "pending"
            reminder.scheduled_time = timezone.localtime(reminder.scheduled_datetime).strftime("%I:%M %p")
            if not reminder.device_id:
                reminder.device_id = elder.devices.filter(is_active=True).values_list("device_id", flat=True).first() or ""
            reminder.save()
            messages.success(request, "臨時服藥已新增，服藥結果將由後續確認更新。")
            return redirect("dashboard")
    else:
        form = ReminderForm(user=request.user)
    return render(request, "core/reminder_form.html", {"form": form, "title": "新增臨時服藥", "button_text": "新增臨時服藥"})


@login_required
def reminder_edit(request, record_id):
    reminder = get_object_or_404(user_reminder_queryset(request.user), pk=record_id)
    if request.method == "POST":
        form = ReminderForm(request.POST, instance=reminder, user=request.user)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.owner = request.user
            elder = form.cleaned_data.get("elder")
            if elder:
                reminder.user_name = elder.name
                reminder.user_age = str(elder.age)
                if not reminder.device_id:
                    reminder.device_id = elder.devices.filter(is_active=True).values_list("device_id", flat=True).first() or ""
            reminder.scheduled_time = timezone.localtime(reminder.scheduled_datetime).strftime("%I:%M %p")
            reminder.save()
            messages.success(request, "服藥任務已更新。")
            return redirect("dashboard")
    else:
        form = ReminderForm(instance=reminder, user=request.user)
    return render(request, "core/reminder_form.html", {"form": form, "title": "編輯服藥任務", "button_text": "儲存修改"})


@login_required
@require_POST
def reminder_taken(request, record_id):
    reminder = get_object_or_404(
        user_reminder_queryset(request.user).select_related("schedule"),
        pk=record_id,
    )
    mark_reminder_taken(reminder, source="web")
    messages.success(request, "已確認服藥，相關 Agent 介入已結案。")
    return redirect("dashboard")


@login_required
def reminder_delete(request, record_id):
    reminder = get_object_or_404(user_reminder_queryset(request.user), pk=record_id)
    if request.method == "POST":
        reminder.delete()
        messages.success(request, "服藥任務已刪除。")
        return redirect("dashboard")
    return render(request, "core/reminder_confirm_delete.html", {"reminder": reminder})


@login_required
def schedules(request):
    schedule_list = MedicationSchedule.objects.filter(elder__owner=request.user).select_related("elder", "drug")
    elders = Elder.objects.filter(owner=request.user)
    return render(request, "core/schedules.html", {"schedules": schedule_list, "elders": elders, "drug_count": Drug.objects.count()})


@login_required
def schedule_create(request):
    if request.method == "POST":
        form = MedicationScheduleForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "週期服藥排程已建立，Agent 會依星期與時間產生任務。")
            return redirect("schedules")
    else:
        form = MedicationScheduleForm(user=request.user)
    return render(request, "core/schedule_form.html", {"form": form, "title": "新增週期服藥排程"})


@login_required
def schedule_edit(request, schedule_id):
    schedule = get_object_or_404(MedicationSchedule, pk=schedule_id, elder__owner=request.user)
    if request.method == "POST":
        form = MedicationScheduleForm(request.POST, instance=schedule, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "排程已更新。")
            return redirect("schedules")
    else:
        form = MedicationScheduleForm(instance=schedule, user=request.user)
    return render(request, "core/schedule_form.html", {"form": form, "title": "編輯週期服藥排程"})


@login_required
@require_POST
def schedule_delete(request, schedule_id):
    schedule = get_object_or_404(MedicationSchedule, pk=schedule_id, elder__owner=request.user)
    schedule.delete()
    messages.success(request, "排程已刪除。")
    return redirect("schedules")


@login_required
def elder_create(request):
    if request.method == "POST":
        form = ElderForm(request.POST)
        if form.is_valid():
            elder, created = Elder.objects.get_or_create(
                owner=request.user,
                name=form.cleaned_data["name"].strip(),
                defaults={
                    "age": form.cleaned_data["age"],
                    "notes": form.cleaned_data.get("notes", ""),
                },
            )
            if created:
                messages.success(request, "長輩資料已新增。")
            else:
                elder.age = form.cleaned_data["age"]
                elder.notes = form.cleaned_data.get("notes", "")
                elder.save(update_fields=["age", "notes"])
                messages.info(request, "此長輩姓名已存在，已更新原本資料。")
            return redirect("schedules")
    else:
        form = ElderForm()
    return render(request, "core/simple_form.html", {"form": form, "title": "新增長輩資料", "button_text": "新增"})


@login_required
def drug_create(request):
    if request.method == "POST":
        form = DrugForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "藥物對照資料已新增。")
            return redirect("schedules")
    else:
        form = DrugForm()
    return render(request, "core/simple_form.html", {"form": form, "title": "新增藥物對照", "button_text": "新增"})


@login_required
def drug_search_options(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 1:
        return JsonResponse({"results": []})
    drugs = Drug.objects.filter(
        Q(name_zh__icontains=query) | Q(generic_name__icontains=query) | Q(fda_product_ndc__icontains=query)
    )[:12]
    return JsonResponse(
        {
            "results": [
                {
                    "label": f"{drug.name_zh or drug.generic_name}"
                    + (f" / {drug.generic_name}" if drug.generic_name and drug.generic_name != drug.name_zh else ""),
                    "value": drug.name_zh or drug.generic_name or drug.fda_product_ndc,
                }
                for drug in drugs
            ]
        }
    )


@login_required
def dataset_center(request):
    sync_form = OpenFDASyncForm(prefix="fda")
    kaggle_form = KaggleImportForm(prefix="kaggle")
    if request.method == "POST" and "sync_openfda" in request.POST:
        sync_form = OpenFDASyncForm(request.POST, prefix="fda")
        if sync_form.is_valid():
            try:
                result = sync_openfda(sync_form.cleaned_data["query"], limit=sync_form.cleaned_data["limit"])
                messages.success(request, f"openFDA 同步完成：新增 {result.added}、更新 {result.updated} 筆真實資料。")
                return redirect("dataset_center")
            except DatasetServiceError as exc:
                messages.error(request, str(exc))
    elif request.method == "POST" and "import_kaggle" in request.POST:
        kaggle_form = KaggleImportForm(request.POST, request.FILES, prefix="kaggle")
        if kaggle_form.is_valid():
            uploaded = kaggle_form.cleaned_data["csv_file"]
            try:
                result = import_kaggle_csv(
                    uploaded,
                    original_name=uploaded.name,
                    dataset_url=kaggle_form.cleaned_data["dataset_url"],
                )
                messages.success(request, f"Kaggle CSV 匯入完成：新增 {result.added}、更新 {result.updated} 筆。")
                return redirect("dataset_center")
            except DatasetServiceError as exc:
                messages.error(request, str(exc))

    query = request.GET.get("q", "").strip()
    documents = DrugKnowledgeDocument.objects.all()
    if query:
        documents = documents.filter(
            Q(generic_name__icontains=query)
            | Q(brand_name__icontains=query)
            | Q(product_ndc__icontains=query)
            | Q(manufacturer__icontains=query)
        )
    counts = {
        "total": DrugKnowledgeDocument.objects.count(),
        "ndc": DrugKnowledgeDocument.objects.filter(source_type="openfda_ndc").count(),
        "label": DrugKnowledgeDocument.objects.filter(source_type="openfda_label").count(),
        "kaggle": DrugKnowledgeDocument.objects.filter(source_type="kaggle_csv").count(),
    }
    return render(
        request,
        "core/dataset_center.html",
        {
            "sync_form": sync_form,
            "kaggle_form": kaggle_form,
            "documents": documents[:100],
            "counts": counts,
            "query": query,
            "sync_runs": DatasetSyncRun.objects.all()[:8],
        },
    )


@login_required
def dataset_document(request, document_id):
    document = get_object_or_404(DrugKnowledgeDocument, pk=document_id)
    return render(request, "core/dataset_document.html", {"document": document})


@login_required
def qa_center(request):
    result = None
    evidence_docs = []
    if request.method == "POST":
        form = QAForm(request.POST)
        if form.is_valid():
            result = answer_medication_question(
                form.cleaned_data["drug_name"],
                form.cleaned_data["question"],
                language=form.cleaned_data["language"],
                auto_sync=form.cleaned_data["auto_sync"],
            )
            QAConversation.objects.create(
                owner=request.user,
                elder_name=form.cleaned_data["elder_name"],
                drug_query=form.cleaned_data["drug_name"],
                question=form.cleaned_data["question"],
                answer=result.answer,
                evidence_ids=[item["id"] for item in result.evidence],
                language=form.cleaned_data["language"],
            )
            if result.evidence:
                evidence_docs = DrugKnowledgeDocument.objects.filter(id__in=[item["id"] for item in result.evidence])
    else:
        form = QAForm()
    history = QAConversation.objects.filter(owner=request.user)[:10]
    return render(request, "core/qa_center.html", {"form": form, "result": result, "evidence_docs": evidence_docs, "history": history})


@login_required
def agent_center(request):
    profile_names = split_android_names(get_user_profile(request.user).android_name)
    schedules_qs = MedicationSchedule.objects.filter(
        elder__owner=request.user, slot__range=(1, SLOT_COUNT)
    ).select_related("elder", "drug")
    selected_date = parse_date(request.GET.get("date", "")) or timezone.localdate()
    selected_elder = request.GET.get("elder", "").strip()
    reminder_query = user_reminder_queryset(request.user).filter(
        Q(scheduled_datetime__date=selected_date)
        | Q(scheduled_datetime__isnull=True, created_at__date=selected_date)
    )
    if selected_elder:
        reminder_query = reminder_query.filter(user_name=selected_elder)
    agent_stats = {
        "pending": reminder_query.filter(agent_state="pending").count(),
        "waiting": reminder_query.filter(agent_state="waiting_sensor").count(),
        "intervened": reminder_query.filter(agent_state="intervened").count(),
        "taken": reminder_query.filter(agent_state="taken").count(),
        "missed": reminder_query.filter(agent_state="missed").count(),
    }
    reminders = reminder_query.filter(
        agent_state__in=["waiting_sensor", "intervened", "missed"]
    ).select_related("schedule")[:30]
    interventions = AgentIntervention.objects.filter(
        Q(reminder__owner=request.user) | Q(reminder__user_name__in=profile_names)
    ).select_related("reminder")[:30]
    events = SensorEvent.objects.filter(
        Q(device_record__owner=request.user) | Q(user_name__in=profile_names),
        slot__range=(1, SLOT_COUNT),
    )[:30]
    return render(
        request,
        "core/agent_center.html",
        {
            "schedules": schedules_qs,
            "reminders": reminders,
            "interventions": interventions,
            "events": events,
            "sensor_form": SensorDemoForm(),
            "agent_stats": agent_stats,
            "selected_date": selected_date,
            "selected_elder": selected_elder,
            "elders": Elder.objects.filter(owner=request.user),
        },
    )


@login_required
@require_POST
def run_agent_now(request):
    if not request.user.is_staff:
        messages.error(request, "只有管理員可手動執行全系統 Agent。")
        return redirect("agent_center")
    result = run_agent_cycle()
    messages.success(request, f"Agent 執行完成：{result.as_dict()}")
    return redirect("agent_center")


@login_required
@require_POST
def simulate_sensor_event(request):
    if not request.user.is_staff:
        messages.error(request, "只有管理員可使用感測器測試工具。")
        return redirect("agent_center")
    form = SensorDemoForm(request.POST)
    if form.is_valid():
        device, _ = PillBoxDevice.objects.get_or_create(
            device_id=form.cleaned_data["device_id"], defaults={"owner": request.user}
        )
        if device.display_name != "早／中／晚三格智慧藥盒":
            device.display_name = "早／中／晚三格智慧藥盒"
            device.save(update_fields=["display_name"])
        event = SensorEvent.objects.create(
            device_record=device,
            device_id=device.device_id,
            user_name=form.cleaned_data["user_name"],
            slot=form.cleaned_data["slot"],
            event_type="opened",
            raw_payload={"source": "web_test_button"},
        )
        matched = match_sensor_event(event)
        messages.success(request, f"已寫入開盒事件；配對任務：{matched.id if matched else '無'}。")
    else:
        messages.error(request, "測試事件欄位不正確。")
    return redirect("agent_center")


# ---------------------------------------------------------------------------
# JSON API


def _json_body(request: HttpRequest) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 格式錯誤。") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON 最外層必須是物件。")
    return payload


def _token_from_request(request):
    token = request.headers.get("X-Device-Token", "").strip()
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token


def require_device_token(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        expected = getattr(settings, "DEVICE_API_TOKEN", "").strip()
        if expected and _token_from_request(request) != expected:
            return JsonResponse({"error": "invalid_device_token"}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapped


def _parse_dt(value, fallback_time=""):
    if value:
        parsed = parse_datetime(str(value))
        if parsed:
            return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed
    if fallback_time:
        for pattern in ("%I:%M %p", "%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(fallback_time.strip(), pattern).time()
                return timezone.make_aware(datetime.combine(timezone.localdate(), parsed_time), timezone.get_current_timezone())
            except ValueError:
                continue
    return None


def _parse_bool(value, *, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_slot(value):
    if value in (None, ""):
        return None
    try:
        slot = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("slot 必須是早=1、中=2、晚=3 的整數。") from exc
    if not 1 <= slot <= SLOT_COUNT:
        raise ValueError("slot 必須只能是早=1、中=2、晚=3。")
    return slot


def _parse_schedule_time(value):
    value = str(value or "").strip()
    for pattern in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return datetime.strptime(value, pattern).time()
        except ValueError:
            continue
    raise ValueError("scheduled_time 請使用 HH:mm，例如 08:00。")


def _period_for_time(value):
    if value.hour < 11:
        return "morning"
    if value.hour < 15:
        return "noon"
    return "evening"


def _parse_weekdays_1_to_7(value):
    raw = str(value or "1,2,3,4,5,6,7")
    pieces = [piece.strip() for piece in raw.replace("，", ",").split(",") if piece.strip()]
    if not pieces:
        pieces = ["1", "2", "3", "4", "5", "6", "7"]
    days = []
    for piece in pieces:
        if not piece.isdigit() or not 1 <= int(piece) <= 7:
            raise ValueError("weekdays 只能使用 1 到 7，週一=1、週日=7。")
        days.append(str(int(piece)))
    return ",".join(sorted(set(days), key=int))


def _find_or_create_drug(name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("medicine_name 必填。")
    drug = Drug.objects.filter(
        Q(name_zh__iexact=name) | Q(generic_name__iexact=name) | Q(fda_product_ndc__iexact=name)
    ).first()
    if drug:
        return drug
    drug = Drug.objects.filter(Q(name_zh__icontains=name) | Q(generic_name__icontains=name)).first()
    if drug:
        return drug
    return Drug.objects.create(name_zh=name[:100], generic_name=name[:180] if name.isascii() else "")


def _get_or_create_elder(user_name, user_age=""):
    user_name = str(user_name or "").strip()
    if not user_name:
        raise ValueError("user_name 必填。")
    owner = find_owner_by_android_name(user_name)
    age = 70
    try:
        if str(user_age).strip():
            age = max(1, min(120, int(user_age)))
    except (TypeError, ValueError):
        age = 70
    elder, created = Elder.objects.get_or_create(
        owner=owner,
        name=user_name[:50],
        defaults={"age": age},
    )
    if not created and user_age and elder.age != age:
        elder.age = age
        elder.save(update_fields=["age"])
    return elder


def _serialize_reminder(reminder):
    return {
        "id": reminder.id,
        "user_name": reminder.user_name,
        "user_age": reminder.user_age,
        "medicine_name": reminder.medicine_name,
        "scheduled_time": reminder.scheduled_time,
        "scheduled_datetime": reminder.scheduled_datetime.isoformat() if reminder.scheduled_datetime else None,
        "dose_count": reminder.dose_count,
        "reminder_hint": reminder.reminder_hint,
        "slot": reminder.slot,
        "slot_label": slot_label(reminder.slot),
        "device_id": reminder.device_id,
        "status": reminder.status,
        "agent_state": reminder.agent_state,
        "reminder_count": reminder.reminder_count,
        "taken_at": reminder.taken_at.isoformat() if reminder.taken_at else None,
        "confirmation_source": reminder.confirmation_source,
        "source": reminder.source,
    }


def _serialize_schedule(schedule):
    return {
        "id": schedule.id,
        "elder_name": schedule.elder.name,
        "elder_age": schedule.elder.age,
        "medicine_name": schedule.drug.name_zh or schedule.drug.generic_name,
        "generic_name": schedule.drug.generic_name,
        "scheduled_time": schedule.scheduled_time.strftime("%H:%M"),
        "dose_count": schedule.dose_count,
        "reminder_hint": schedule.reminder_hint,
        "slot": schedule.slot,
        "slot_label": slot_label(schedule.slot),
        "period": period_for_slot(schedule.slot),
        "period_label": slot_label(schedule.slot),
        "weekdays": schedule.weekdays,
        "device_id": schedule.device_id,
        "is_active": schedule.is_active,
    }


def _serialize_intervention(item):
    reminder = item.reminder
    return {
        "id": item.id,
        "type": item.intervention_type,
        "type_label": item.get_intervention_type_display(),
        "state": item.state,
        "channel": item.channel,
        "message": item.message,
        "created_at": item.created_at.isoformat(),
        "delivered_at": item.delivered_at.isoformat() if item.delivered_at else None,
        "acknowledged_at": item.acknowledged_at.isoformat() if item.acknowledged_at else None,
        "reminder": _serialize_reminder(reminder) if reminder else None,
    }


@require_http_methods(["GET"])
def api_health(request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "smart-medicine-box",
            "time": timezone.now().isoformat(),
            "dataset_documents": DrugKnowledgeDocument.objects.count(),
            "slot_count": SLOT_COUNT,
            "slots": slot_payload(),
            "pillbox_layout": "early-noon-evening-3-slot",
            "ui_revision": 6,
        }
    )


@csrf_exempt
@require_device_token
@require_http_methods(["GET", "POST"])
def api_reminders(request):
    if request.method == "GET":
        user_name = request.GET.get("user_name", "").strip()
        date_value = parse_date(request.GET.get("date", "")) or timezone.localdate()
        query = Reminder.objects.filter(Q(slot__isnull=True) | Q(slot__range=(1, SLOT_COUNT)))
        if user_name:
            query = query.filter(user_name__iexact=user_name)
        query = query.filter(
            Q(scheduled_datetime__date=date_value)
            | Q(scheduled_datetime__isnull=True, created_at__date=date_value)
        ).order_by("scheduled_datetime", "created_at")
        return JsonResponse({"results": [_serialize_reminder(item) for item in query[:200]]})

    try:
        data = _json_body(request)
        user_name = str(data.get("user_name", "")).strip()
        medicine_name = str(data.get("medicine_name", "")).strip()
        if not user_name or not medicine_name:
            return JsonResponse({"error": "user_name 與 medicine_name 為必填。"}, status=400)
        scheduled_time = str(data.get("scheduled_time", "")).strip()
        scheduled_dt = _parse_dt(data.get("scheduled_datetime"), scheduled_time)
        if not scheduled_dt:
            return JsonResponse({"error": "scheduled_datetime 或 scheduled_time 為必填。"}, status=400)
        if not scheduled_time:
            scheduled_time = timezone.localtime(scheduled_dt).strftime("%I:%M %p")
        status = str(data.get("status", "已提醒"))
        if status not in dict(Reminder.STATUS_CHOICES):
            status = "已提醒"
        agent_state = "missed" if status == "漏服" else "pending"
        reminder = Reminder.objects.create(
            owner=find_owner_by_android_name(user_name),
            user_name=user_name[:50],
            user_age=str(data.get("user_age") or "")[:10],
            medicine_name=medicine_name[:100],
            scheduled_time=scheduled_time[:20],
            scheduled_datetime=scheduled_dt,
            dose_count=str(data.get("dose_count") or "1")[:20],
            reminder_hint=str(data.get("reminder_hint") or "記得吃藥喔！")[:200],
            slot=_parse_slot(data.get("slot")),
            device_id=str(data.get("device_id") or "pillbox-01")[:80],
            source="android",
            status="已提醒" if status == "已服藥" else status,
            agent_state=agent_state,
            reminder_count=max(0, int(data.get("reminder_count") or 0)),
        )
        if status == "已服藥":
            mark_reminder_taken(reminder, source="android")
        return JsonResponse(_serialize_reminder(reminder), status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
@require_device_token
@require_http_methods(["GET", "POST"])
def api_schedules(request):
    if request.method == "GET":
        user_name = request.GET.get("user_name", "").strip()
        query = MedicationSchedule.objects.select_related("elder", "drug").filter(slot__range=(1, SLOT_COUNT))
        if user_name:
            query = query.filter(elder__name__iexact=user_name)
        return JsonResponse({"results": [_serialize_schedule(item) for item in query[:200]]})

    try:
        data = _json_body(request)
        elder = _get_or_create_elder(data.get("user_name"), data.get("user_age"))
        drug = _find_or_create_drug(data.get("medicine_name"))
        scheduled_time = _parse_schedule_time(data.get("scheduled_time"))
        parsed_slot = _parse_slot(data.get("slot")) or 1
        schedule = MedicationSchedule.objects.create(
            elder=elder,
            drug=drug,
            slot=parsed_slot,
            period=period_for_slot(parsed_slot),
            scheduled_time=scheduled_time,
            dose_count=str(data.get("dose_count") or "1")[:20],
            reminder_hint=str(data.get("reminder_hint") or "飯後服用")[:200],
            weekdays=_parse_weekdays_1_to_7(data.get("weekdays")),
            grace_minutes=max(1, int(data.get("grace_minutes") or 10)),
            missed_after_minutes=max(2, int(data.get("missed_after_minutes") or 60)),
            device_id=str(data.get("device_id") or "pillbox-01")[:80],
            is_active=_parse_bool(data.get("is_active"), default=True),
        )
        return JsonResponse(_serialize_schedule(schedule), status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
@require_device_token
@require_http_methods(["GET", "POST"])
def api_schedule_detail(request, schedule_id):
    schedule = get_object_or_404(MedicationSchedule.objects.select_related("elder", "drug"), pk=schedule_id)
    if request.method == "GET":
        return JsonResponse(_serialize_schedule(schedule))
    try:
        data = _json_body(request)
        if data.get("user_name"):
            schedule.elder = _get_or_create_elder(data.get("user_name"), data.get("user_age"))
        if data.get("medicine_name"):
            schedule.drug = _find_or_create_drug(data.get("medicine_name"))
        if data.get("slot") not in (None, ""):
            schedule.slot = _parse_slot(data.get("slot")) or 1
        if data.get("scheduled_time"):
            schedule.scheduled_time = _parse_schedule_time(data.get("scheduled_time"))
        schedule.period = period_for_slot(schedule.slot)
        if data.get("dose_count") is not None:
            schedule.dose_count = str(data.get("dose_count") or "1")[:20]
        if data.get("reminder_hint") is not None:
            schedule.reminder_hint = str(data.get("reminder_hint") or "飯後服用")[:200]
        if data.get("weekdays") is not None:
            schedule.weekdays = _parse_weekdays_1_to_7(data.get("weekdays"))
        if data.get("device_id") is not None:
            schedule.device_id = str(data.get("device_id") or "pillbox-01")[:80]
        if data.get("is_active") is not None:
            schedule.is_active = _parse_bool(data.get("is_active"), default=True)
        schedule.save()
        return JsonResponse(_serialize_schedule(schedule))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
@require_device_token
@require_http_methods(["DELETE", "POST"])
def api_schedule_delete(request, schedule_id):
    schedule = get_object_or_404(MedicationSchedule, pk=schedule_id)
    schedule.delete()
    return JsonResponse({"deleted": schedule_id})


@csrf_exempt
@require_device_token
@require_POST
def api_reminder_taken(request, record_id):
    reminder = get_object_or_404(Reminder.objects.select_related("schedule"), pk=record_id)
    mark_reminder_taken(reminder, source="android")
    return JsonResponse(_serialize_reminder(reminder))


@csrf_exempt
@require_device_token
@require_http_methods(["DELETE", "POST"])
def api_reminder_delete(request, record_id):
    reminder = get_object_or_404(Reminder, pk=record_id)
    reminder.delete()
    return JsonResponse({"deleted": record_id})


@csrf_exempt
@require_device_token
@require_POST
def api_sensor_event(request):
    try:
        data = _json_body(request)
        device_id = str(data.get("device_id", "")).strip()
        if not device_id:
            return JsonResponse({"error": "device_id 為必填。"}, status=400)
        event_type = str(data.get("event_type", "opened"))
        if event_type not in dict(SensorEvent.EVENT_TYPES):
            return JsonResponse({"error": "event_type 必須是 opened、closed 或 heartbeat。"}, status=400)
        detected_at = _parse_dt(data.get("detected_at")) or timezone.now()
        user_name = str(data.get("user_name", "")).strip()
        owner = find_owner_by_android_name(user_name)
        device, _ = PillBoxDevice.objects.get_or_create(
            device_id=device_id,
            defaults={"owner": owner, "display_name": str(data.get("device_name", "早／中／晚三格智慧藥盒"))[:100]},
        )
        device.last_seen_at = detected_at
        update_fields = ["last_seen_at"]
        if owner and not device.owner_id:
            device.owner = owner
            update_fields.append("owner")
        if device.display_name != "早／中／晚三格智慧藥盒":
            device.display_name = "早／中／晚三格智慧藥盒"
            update_fields.append("display_name")
        device.save(update_fields=sorted(set(update_fields)))
        slot = _parse_slot(data.get("slot"))
        event = SensorEvent.objects.create(
            device_record=device,
            device_id=device_id,
            user_name=user_name[:50],
            slot=slot,
            event_type=event_type,
            detected_at=detected_at,
            raw_payload=data,
        )
        matched = match_sensor_event(event)
        return JsonResponse(
            {
                "event_id": event.id,
                "device_id": event.device_id,
                "slot": event.slot,
                "slot_label": slot_label(event.slot),
                "event_type": event.event_type,
                "matched_reminder": _serialize_reminder(matched) if matched else None,
            },
            status=201,
        )
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
@require_device_token
@require_POST
def api_qa_ask(request):
    try:
        data = _json_body(request)
        drug_name = str(data.get("drug_name", "")).strip()
        question = str(data.get("question", "")).strip()
        if not drug_name or not question:
            return JsonResponse({"error": "drug_name 與 question 為必填。"}, status=400)
        language = str(data.get("language", "zh-TW"))[:20]
        elder_name = str(data.get("user_name", ""))[:50]
        result = answer_medication_question(
            drug_name,
            question,
            language=language,
            auto_sync=_parse_bool(data.get("auto_sync"), default=True),
        )
        conversation = QAConversation.objects.create(
            owner=find_owner_by_android_name(elder_name),
            elder_name=elder_name,
            drug_query=drug_name,
            question=question,
            answer=result.answer,
            evidence_ids=[item["id"] for item in result.evidence],
            language=language,
        )
        AgentIntervention.objects.create(
            reminder=None,
            intervention_type="qa_education",
            state="delivered",
            channel="voice_or_android",
            message=f"Q: {question}\nA: {result.answer[:1500]}",
            delivered_at=timezone.now(),
        )
        return JsonResponse(
            {
                "conversation_id": conversation.id,
                "answer": result.answer,
                "question_type": result.question_type,
                "question_label": result.question_label,
                "evidence": result.evidence,
                "translated": result.translated,
                "auto_synced": result.auto_synced,
                "sync_message": result.sync_message,
            }
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_device_token
@require_http_methods(["GET"])
def api_interventions(request):
    """供 Raspberry Pi／Android 輪詢尚未播放的 Agent 語音訊息。"""

    device_id = request.GET.get("device_id", "").strip()
    user_name = request.GET.get("user_name", "").strip()
    state = request.GET.get("state", "created").strip()
    if state not in dict(AgentIntervention.STATES):
        return JsonResponse({"error": "state 不正確。"}, status=400)

    query = AgentIntervention.objects.filter(state=state, reminder__isnull=False).select_related("reminder")
    if device_id:
        query = query.filter(reminder__device_id=device_id)
    if user_name:
        query = query.filter(reminder__user_name__iexact=user_name)
    return JsonResponse({"results": [_serialize_intervention(item) for item in query[:50]]})


@csrf_exempt
@require_device_token
@require_POST
def api_intervention_state(request, intervention_id):
    try:
        data = _json_body(request)
        state = str(data.get("state", "delivered")).strip()
        if state not in dict(AgentIntervention.STATES):
            return JsonResponse({"error": "state 必須是 created、delivered、acknowledged 或 closed。"}, status=400)
        item = get_object_or_404(AgentIntervention.objects.select_related("reminder"), pk=intervention_id)
        item.state = state
        update_fields = ["state"]
        now = timezone.now()
        if state == "delivered" and not item.delivered_at:
            item.delivered_at = now
            update_fields.append("delivered_at")
        if state in {"acknowledged", "closed"} and not item.acknowledged_at:
            item.acknowledged_at = now
            update_fields.append("acknowledged_at")
        item.save(update_fields=update_fields)
        return JsonResponse(_serialize_intervention(item))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_device_token
@require_http_methods(["GET"])
def api_drug_search(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    docs = DrugKnowledgeDocument.objects.filter(
        Q(generic_name__icontains=query) | Q(brand_name__icontains=query) | Q(product_ndc__icontains=query)
    )[:30]
    return JsonResponse(
        {
            "results": [
                {
                    "id": doc.id,
                    "source": doc.source_type,
                    "generic_name": doc.generic_name,
                    "brand_name": doc.brand_name,
                    "product_ndc": doc.product_ndc,
                }
                for doc in docs
            ]
        }
    )


# 舊版 Android 相容網址
@csrf_exempt
@require_device_token
@require_POST
def upload_reminder(request):
    return api_reminders(request)


@csrf_exempt
@require_device_token
@require_POST
def confirm_taken(request, record_id):
    return api_reminder_taken(request, record_id)
