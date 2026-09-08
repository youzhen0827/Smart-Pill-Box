package com.example.smartpillbox

import org.json.JSONObject

data class ReminderItem(
    val id: Int,
    val userName: String,
    val userAge: String,
    val medicineName: String,
    val scheduledTime: String,
    val scheduledDatetime: String?,
    val doseCount: String,
    val reminderHint: String,
    val slot: Int?,
    val slotLabel: String,
    val deviceId: String,
    val status: String,
    val agentState: String,
    val reminderCount: Int,
    val takenAt: String?,
    val confirmationSource: String,
    val source: String
) {
    companion object {
        fun fromJson(obj: JSONObject): ReminderItem = ReminderItem(
            id = obj.optInt("id"),
            userName = obj.optString("user_name"),
            userAge = obj.optString("user_age"),
            medicineName = obj.optString("medicine_name"),
            scheduledTime = obj.optString("scheduled_time"),
            scheduledDatetime = obj.optString("scheduled_datetime").takeIf { it.isNotBlank() && it != "null" },
            doseCount = obj.optString("dose_count", "1"),
            reminderHint = obj.optString("reminder_hint"),
            slot = if (obj.isNull("slot")) null else obj.optInt("slot"),
            slotLabel = obj.optString("slot_label"),
            deviceId = obj.optString("device_id"),
            status = obj.optString("status", "已提醒"),
            agentState = obj.optString("agent_state", "pending"),
            reminderCount = obj.optInt("reminder_count"),
            takenAt = obj.optString("taken_at").takeIf { it.isNotBlank() && it != "null" },
            confirmationSource = obj.optString("confirmation_source"),
            source = obj.optString("source")
        )
    }
}
