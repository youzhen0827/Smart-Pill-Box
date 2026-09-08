from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .slots import SLOT_CHOICES, SLOT_COUNT, period_for_slot, slot_label


class UserProfile(models.Model):
    """Django 帳號與 Android 長輩姓名的綁定。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Django 登入帳號",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    android_name = models.TextField("Android 使用者姓名名單", blank=True)

    def __str__(self) -> str:
        return f"{self.user.username} — {self.android_name or '尚未設定'}"


class Elder(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="照護帳號",
        on_delete=models.CASCADE,
        related_name="elders",
        null=True,
        blank=True,
    )
    name = models.CharField("姓名", max_length=50)
    age = models.PositiveSmallIntegerField("年齡", default=70)
    notes = models.TextField("照護備註", blank=True, default="")

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_elder_owner_name")
        ]

    def __str__(self) -> str:
        return self.name


class Drug(models.Model):
    name_zh = models.CharField("顯示名稱", max_length=100)
    generic_name = models.CharField("FDA 學名／通用名", max_length=180, blank=True, default="")
    side_effects = models.TextField("人工補充副作用", blank=True)
    dosage_note = models.TextField("人工補充用藥說明", blank=True)
    fda_product_ndc = models.CharField("FDA Product NDC", max_length=50, blank=True, default="")

    class Meta:
        ordering = ["name_zh", "id"]

    def __str__(self) -> str:
        suffix = f" / {self.generic_name}" if self.generic_name else ""
        return f"{self.name_zh}{suffix}"


class MedicationSchedule(models.Model):
    PERIOD = [
        ("morning", "早"),
        ("noon", "中"),
        ("evening", "晚"),
    ]

    elder = models.ForeignKey(Elder, on_delete=models.CASCADE, related_name="schedules")
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name="schedules")
    slot = models.PositiveSmallIntegerField(
        "藥盒時段", choices=SLOT_CHOICES, default=1,
        validators=[MinValueValidator(1), MaxValueValidator(SLOT_COUNT)],
    )
    period = models.CharField("時段", max_length=10, choices=PERIOD, default="morning")
    scheduled_time = models.TimeField("服藥時間")
    dose_count = models.CharField("數量", max_length=20, default="1")
    reminder_hint = models.CharField("提醒文字", max_length=200, default="記得吃藥喔！")
    weekdays = models.CharField(
        "執行星期",
        max_length=30,
        default="1,2,3,4,5,6,7",
        help_text="1=週一，7=週日；用逗號分隔。",
    )
    grace_minutes = models.PositiveIntegerField("感測器等待分鐘", default=10)
    missed_after_minutes = models.PositiveIntegerField("漏服判定分鐘", default=60)
    device_id = models.CharField("藥盒裝置 ID", max_length=80, default="pillbox-01")
    is_active = models.BooleanField("啟用", default=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["scheduled_time", "slot", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(slot__gte=1, slot__lte=SLOT_COUNT), name="schedule_slot_1_to_3"),
        ]

    def __str__(self) -> str:
        return f"{self.elder} — {self.drug} [{slot_label(self.slot)}]"

    def save(self, *args, **kwargs):
        # Physical compartment is the source of truth: 1=早, 2=中, 3=晚.
        self.period = period_for_slot(self.slot)
        super().save(*args, **kwargs)

    def runs_on(self, target_date) -> bool:
        days = {
            int(value.strip())
            for value in (self.weekdays or "").split(",")
            if value.strip().isdigit()
        }
        return target_date.isoweekday() in days


class Reminder(models.Model):
    """Android、網頁、排程 Agent 共用的一次性服藥任務。"""

    STATUS_CHOICES = [("已提醒", "已提醒"), ("已服藥", "已服藥"), ("漏服", "漏服")]
    SOURCE_CHOICES = [
        ("android", "Android App"),
        ("web", "Django 網頁"),
        ("schedule", "排程 Agent"),
        ("sensor", "感測器"),
    ]
    AGENT_STATE_CHOICES = [
        ("pending", "尚未到時"),
        ("waiting_sensor", "等待藥盒開啟"),
        ("intervened", "Agent 已介入"),
        ("taken", "已完成"),
        ("missed", "已判定漏服"),
    ]
    CONFIRMATION_SOURCE_CHOICES = [
        ("", "尚未確認"),
        ("android", "Android App"),
        ("web", "Django 網頁"),
        ("sensor", "藥盒感測器"),
        ("raspberry_pi", "Raspberry Pi"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="建立者帳號",
        on_delete=models.CASCADE,
        related_name="reminders",
        null=True,
        blank=True,
    )
    schedule = models.ForeignKey(
        MedicationSchedule,
        verbose_name="來源排程",
        on_delete=models.SET_NULL,
        related_name="reminders",
        null=True,
        blank=True,
    )
    user_name = models.CharField("Android 輸入名稱", max_length=50)
    user_age = models.CharField("年齡", max_length=10, blank=True)
    medicine_name = models.CharField("藥品名稱", max_length=100)
    scheduled_time = models.CharField("服藥時間", max_length=20)
    scheduled_datetime = models.DateTimeField("服藥日期時間", null=True, blank=True)
    dose_count = models.CharField("數量", max_length=20, default="1")
    reminder_hint = models.CharField("提醒文字", max_length=200, default="記得吃藥喔！")
    slot = models.PositiveSmallIntegerField(
        "藥盒時段", choices=SLOT_CHOICES, null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(SLOT_COUNT)],
    )
    device_id = models.CharField("藥盒裝置 ID", max_length=80, blank=True, default="")
    source = models.CharField("建立來源", max_length=20, choices=SOURCE_CHOICES, default="android")
    status = models.CharField("狀態", max_length=15, choices=STATUS_CHOICES, default="已提醒")
    agent_state = models.CharField(
        "Agent 狀態", max_length=30, choices=AGENT_STATE_CHOICES, default="pending"
    )
    reminder_count = models.IntegerField("提醒次數", default=0)
    taken_at = models.DateTimeField("實際服藥時間", null=True, blank=True)
    confirmation_source = models.CharField(
        "確認來源",
        max_length=30,
        choices=CONFIRMATION_SOURCE_CHOICES,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["-scheduled_datetime", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slot__isnull=True) | models.Q(slot__gte=1, slot__lte=SLOT_COUNT),
                name="reminder_slot_null_or_1_to_3",
            ),
        ]
        indexes = [
            models.Index(fields=["user_name", "scheduled_datetime"]),
            models.Index(fields=["status", "agent_state"]),
            models.Index(fields=["device_id", "slot"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scheduled_datetime"],
                condition=models.Q(schedule__isnull=False, scheduled_datetime__isnull=False),
                name="uniq_schedule_occurrence",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_name} — {self.medicine_name} [{self.status}]"

    def mark_taken(self, *, at=None, source="sensor") -> None:
        self.status = "已服藥"
        self.agent_state = "taken"
        self.taken_at = at or timezone.now()
        if source in dict(self.CONFIRMATION_SOURCE_CHOICES):
            self.confirmation_source = source
        self.save(
            update_fields=[
                "status",
                "agent_state",
                "taken_at",
                "confirmation_source",
                "updated_at",
            ]
        )


class MedicationLog(models.Model):
    STATUS = [("taken", "已服藥"), ("missed", "漏服"), ("reminded", "已提醒")]

    schedule = models.ForeignKey(MedicationSchedule, on_delete=models.CASCADE, related_name="logs")
    reminder = models.OneToOneField(
        Reminder,
        on_delete=models.SET_NULL,
        related_name="medication_log",
        null=True,
        blank=True,
    )
    status = models.CharField("狀態", max_length=15, choices=STATUS, default="reminded")
    scheduled_dt = models.DateTimeField("預定時間")
    taken_at = models.DateTimeField("實際取藥", null=True, blank=True)
    reminder_count = models.IntegerField("提醒次數", default=0)

    class Meta:
        ordering = ["-scheduled_dt"]
        indexes = [models.Index(fields=["schedule", "scheduled_dt"])]

    def __str__(self) -> str:
        return f"{self.schedule.elder} [{self.status}]"


class PillBoxDevice(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pillbox_devices",
        null=True,
        blank=True,
    )
    elder = models.ForeignKey(
        Elder,
        on_delete=models.SET_NULL,
        related_name="devices",
        null=True,
        blank=True,
    )
    device_id = models.CharField("裝置 ID", max_length=80, unique=True)
    display_name = models.CharField("裝置名稱", max_length=100, default="早／中／晚三格智慧藥盒")
    last_seen_at = models.DateTimeField("最後連線", null=True, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        ordering = ["device_id"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.device_id})"


class SensorEvent(models.Model):
    EVENT_TYPES = [("opened", "藥盒開啟"), ("closed", "藥盒關閉"), ("heartbeat", "裝置心跳")]

    device_record = models.ForeignKey(
        PillBoxDevice,
        on_delete=models.SET_NULL,
        related_name="events",
        null=True,
        blank=True,
    )
    device_id = models.CharField("裝置 ID", max_length=80)
    user_name = models.CharField("長輩姓名", max_length=50, blank=True)
    slot = models.PositiveSmallIntegerField(
        "藥盒時段", choices=SLOT_CHOICES, null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(SLOT_COUNT)],
    )
    event_type = models.CharField("事件", max_length=20, choices=EVENT_TYPES, default="opened")
    detected_at = models.DateTimeField("偵測時間", default=timezone.now)
    matched_reminder = models.ForeignKey(
        Reminder,
        on_delete=models.SET_NULL,
        related_name="sensor_events",
        null=True,
        blank=True,
    )
    raw_payload = models.JSONField("原始資料", default=dict, blank=True)
    created_at = models.DateTimeField("寫入時間", auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slot__isnull=True) | models.Q(slot__gte=1, slot__lte=SLOT_COUNT),
                name="sensor_event_slot_null_or_1_to_3",
            ),
        ]
        indexes = [
            models.Index(fields=["device_id", "slot", "detected_at"]),
            models.Index(fields=["user_name", "detected_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device_id} {slot_label(self.slot)} {self.get_event_type_display()}"


class AgentIntervention(models.Model):
    TYPES = [
        ("initial_reminder", "到時提醒"),
        ("sensor_missing", "感測器未偵測"),
        ("device_check", "請確認藥盒連線"),
        ("caregiver_escalation", "提早通知照護者"),
        ("missed_escalation", "漏服升級通知"),
        ("qa_education", "醫療衛教"),
    ]
    STATES = [
        ("created", "已建立"),
        ("delivered", "已送達"),
        ("acknowledged", "已確認"),
        ("closed", "已結案"),
    ]

    reminder = models.ForeignKey(
        Reminder,
        on_delete=models.CASCADE,
        related_name="interventions",
        null=True,
        blank=True,
    )
    intervention_type = models.CharField("介入類型", max_length=30, choices=TYPES)
    state = models.CharField("處理狀態", max_length=20, choices=STATES, default="created")
    channel = models.CharField("通知管道", max_length=30, default="dashboard")
    message = models.TextField("Agent 訊息")
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    delivered_at = models.DateTimeField("送達時間", null=True, blank=True)
    acknowledged_at = models.DateTimeField("確認時間", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reminder", "intervention_type"],
                condition=models.Q(reminder__isnull=False),
                name="uniq_intervention_per_reminder_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_intervention_type_display()} — {self.state}"


class AgentDecision(models.Model):
    """Agent 每次觀察、規劃、使用工具及結果的可稽核記憶。"""

    STAGES = [
        ("before_due", "尚未到時"),
        ("due_window", "到時等待"),
        ("follow_up_window", "逾時追蹤"),
        ("overdue", "疑似漏服"),
        ("sensor_confirmed", "感測確認"),
    ]
    PLANNERS = [
        ("safe_policy", "本機安全規劃器"),
        ("llm", "AI 模型規劃器"),
        ("llm_fallback", "AI 模型失敗後安全規劃器"),
    ]
    RISK_LEVELS = [("low", "低"), ("medium", "中"), ("high", "高")]

    reminder = models.ForeignKey(
        Reminder, on_delete=models.CASCADE, related_name="agent_decisions"
    )
    stage = models.CharField("決策階段", max_length=30, choices=STAGES)
    planner = models.CharField("規劃方式", max_length=30, choices=PLANNERS)
    model_name = models.CharField("模型名稱", max_length=120, blank=True, default="")
    risk_score = models.PositiveSmallIntegerField("風險分數", default=0)
    risk_level = models.CharField("風險等級", max_length=10, choices=RISK_LEVELS)
    observation = models.JSONField("觀察資料", default=dict)
    available_tools = models.JSONField("可用工具", default=list)
    planned_tools = models.JSONField("選用工具", default=list)
    reasoning = models.TextField("決策理由")
    execution_result = models.JSONField("執行結果", default=dict)
    created_at = models.DateTimeField("首次決策時間", auto_now_add=True)
    updated_at = models.DateTimeField("最後決策時間", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reminder", "stage"], name="uniq_agent_decision_per_stage"
            )
        ]

    def __str__(self) -> str:
        return f"{self.reminder} — {self.get_stage_display()}"


class DrugKnowledgeDocument(models.Model):
    """只保存真實外部資料集匯入的藥物文件，不建立示範假資料。"""

    SOURCE_TYPES = [
        ("openfda_ndc", "FDA NDC Directory"),
        ("openfda_label", "FDA Drug Label"),
        ("kaggle_csv", "Kaggle Drug Interactions / Side Effects CSV"),
    ]

    source_type = models.CharField("資料來源", max_length=30, choices=SOURCE_TYPES)
    source_id = models.CharField("來源唯一 ID", max_length=180)
    product_ndc = models.CharField("Product NDC", max_length=80, blank=True)
    brand_name = models.CharField("品牌名", max_length=250, blank=True)
    generic_name = models.CharField("學名", max_length=250, blank=True)
    manufacturer = models.CharField("製造商", max_length=250, blank=True)
    route = models.TextField("給藥途徑", blank=True)
    dosage_form = models.CharField("劑型", max_length=180, blank=True)
    purpose = models.TextField("用途／Purpose", blank=True)
    indications = models.TextField("適應症與功效", blank=True)
    adverse_reactions = models.TextField("副作用／不良反應", blank=True)
    warnings = models.TextField("警告", blank=True)
    drug_interactions = models.TextField("藥物交互作用", blank=True)
    raw_json = models.JSONField("原始資料", default=dict)
    source_url = models.URLField("來源 API", max_length=500)
    retrieved_at = models.DateTimeField("同步時間", default=timezone.now)

    class Meta:
        ordering = ["generic_name", "brand_name", "source_type", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source_type", "source_id"], name="uniq_dataset_source_id")
        ]
        indexes = [
            models.Index(fields=["source_type", "generic_name"]),
            models.Index(fields=["product_ndc"]),
        ]

    def __str__(self) -> str:
        return self.brand_name or self.generic_name or self.source_id

    @property
    def searchable_text(self) -> str:
        return "\n".join(
            filter(
                None,
                [
                    self.brand_name,
                    self.generic_name,
                    self.manufacturer,
                    self.purpose,
                    self.indications,
                    self.adverse_reactions,
                    self.warnings,
                    self.drug_interactions,
                ],
            )
        )


class DatasetSyncRun(models.Model):
    SOURCES = [("openfda", "openFDA"), ("kaggle_csv", "Kaggle CSV")]
    STATES = [("running", "執行中"), ("success", "成功"), ("failed", "失敗")]

    source = models.CharField("來源", max_length=30, choices=SOURCES)
    query = models.CharField("查詢條件", max_length=250, blank=True)
    state = models.CharField("狀態", max_length=20, choices=STATES, default="running")
    records_added = models.PositiveIntegerField("新增筆數", default=0)
    records_updated = models.PositiveIntegerField("更新筆數", default=0)
    message = models.TextField("執行訊息", blank=True)
    started_at = models.DateTimeField("開始時間", auto_now_add=True)
    finished_at = models.DateTimeField("完成時間", null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.source} {self.query} [{self.state}]"


class QAConversation(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="qa_conversations",
        null=True,
        blank=True,
    )
    elder_name = models.CharField("長輩姓名", max_length=50, blank=True)
    drug_query = models.CharField("藥物查詢", max_length=180)
    question = models.TextField("問題")
    answer = models.TextField("回答")
    evidence_ids = models.JSONField("資料證據 ID", default=list, blank=True)
    language = models.CharField("輸出語言", max_length=20, default="zh-TW")
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.drug_query}: {self.question[:30]}"
