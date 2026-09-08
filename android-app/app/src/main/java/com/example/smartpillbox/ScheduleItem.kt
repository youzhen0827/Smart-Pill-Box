package com.example.smartpillbox

import org.json.JSONObject

data class ScheduleItem(
    val id: Int,
    val elderName: String,
    val elderAge: Int,
    val medicineName: String,
    val scheduledTime: String,
    val doseCount: String,
    val reminderHint: String,
    val slot: Int,
    val slotLabel: String,
    val weekdays: String,
    val deviceId: String,
    val isActive: Boolean
) {
    companion object {
        fun fromJson(obj: JSONObject): ScheduleItem = ScheduleItem(
            id = obj.optInt("id"),
            elderName = obj.optString("elder_name"),
            elderAge = obj.optInt("elder_age"),
            medicineName = obj.optString("medicine_name"),
            scheduledTime = obj.optString("scheduled_time"),
            doseCount = obj.optString("dose_count", "1"),
            reminderHint = obj.optString("reminder_hint"),
            slot = obj.optInt("slot", 1),
            slotLabel = obj.optString("slot_label"),
            weekdays = obj.optString("weekdays", "1,2,3,4,5,6,7"),
            deviceId = obj.optString("device_id"),
            isActive = obj.optBoolean("is_active", true)
        )
    }
}
