from django.contrib import admin

from .slots import slot_label
from .models import (
    AgentDecision,
    AgentIntervention,
    DatasetSyncRun,
    Drug,
    DrugKnowledgeDocument,
    Elder,
    MedicationLog,
    MedicationSchedule,
    PillBoxDevice,
    QAConversation,
    Reminder,
    SensorEvent,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "android_name")
    search_fields = ("user__username", "android_name")


@admin.register(Elder)
class ElderAdmin(admin.ModelAdmin):
    list_display = ("name", "age", "owner")
    search_fields = ("name", "owner__username")


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ("name_zh", "generic_name", "fda_product_ndc")
    search_fields = ("name_zh", "generic_name", "fda_product_ndc")


@admin.register(MedicationSchedule)
class MedicationScheduleAdmin(admin.ModelAdmin):
    list_display = ("elder", "drug", "slot_name", "scheduled_time", "weekdays", "device_id", "is_active")

    @admin.display(description="藥盒時段")
    def slot_name(self, obj):
        return slot_label(obj.slot)
    list_filter = ("is_active", "period", "device_id")
    search_fields = ("elder__name", "drug__name_zh", "drug__generic_name")


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("user_name", "medicine_name", "scheduled_datetime", "slot_name", "status", "agent_state", "source", "confirmation_source")

    @admin.display(description="藥盒時段")
    def slot_name(self, obj):
        return slot_label(obj.slot)
    list_filter = ("status", "agent_state", "source", "confirmation_source")
    search_fields = ("user_name", "medicine_name", "device_id")
    date_hierarchy = "created_at"


@admin.register(MedicationLog)
class MedicationLogAdmin(admin.ModelAdmin):
    list_display = ("schedule", "scheduled_dt", "status", "taken_at", "reminder_count")
    list_filter = ("status",)


@admin.register(PillBoxDevice)
class PillBoxDeviceAdmin(admin.ModelAdmin):
    list_display = ("device_id", "display_name", "elder", "owner", "last_seen_at", "is_active")
    search_fields = ("device_id", "display_name", "elder__name")


@admin.register(SensorEvent)
class SensorEventAdmin(admin.ModelAdmin):
    list_display = ("device_id", "slot_name", "event_type", "user_name", "detected_at", "matched_reminder")

    @admin.display(description="藥盒時段")
    def slot_name(self, obj):
        return slot_label(obj.slot)
    list_filter = ("event_type", "device_id")
    search_fields = ("device_id", "user_name")


@admin.register(AgentIntervention)
class AgentInterventionAdmin(admin.ModelAdmin):
    list_display = ("intervention_type", "reminder", "state", "channel", "created_at")
    list_filter = ("intervention_type", "state", "channel")
    search_fields = ("message", "reminder__user_name", "reminder__medicine_name")


@admin.register(AgentDecision)
class AgentDecisionAdmin(admin.ModelAdmin):
    list_display = ("reminder", "stage", "planner", "risk_level", "updated_at")
    list_filter = ("stage", "planner", "risk_level")
    search_fields = ("reminder__user_name", "reminder__medicine_name", "reasoning")


@admin.register(DrugKnowledgeDocument)
class DrugKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("source_type", "generic_name", "brand_name", "product_ndc", "manufacturer", "retrieved_at")
    list_filter = ("source_type", "retrieved_at")
    search_fields = ("generic_name", "brand_name", "product_ndc", "manufacturer")
    readonly_fields = ("raw_json", "retrieved_at")


@admin.register(DatasetSyncRun)
class DatasetSyncRunAdmin(admin.ModelAdmin):
    list_display = ("source", "query", "state", "records_added", "records_updated", "started_at", "finished_at")
    list_filter = ("source", "state")


@admin.register(QAConversation)
class QAConversationAdmin(admin.ModelAdmin):
    list_display = ("drug_query", "elder_name", "owner", "created_at")
    search_fields = ("drug_query", "question", "answer", "elder_name")
