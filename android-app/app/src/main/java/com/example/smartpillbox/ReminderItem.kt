package com.example.smartpillbox

import org.json.JSONObject

data class AgentDecisionItem(
    val stageLabel: String,
    val plannerLabel: String,
    val riskScore: Int,
    val riskLabel: String,
    val toolLabels: List<String>,
    val reasoning: String,
    val confidencePercent: Int,
    val evidenceLabels: List<String>,
    val validationSummary: String,
    val situationSummary: String,
    val nextStepSummary: String,
    val notificationMessage: String
)

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
    val graceMinutes: Int,
    val missedAfterMinutes: Int,
    val takenAt: String?,
    val confirmationSource: String,
    val source: String,
    val agentDecision: AgentDecisionItem?
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
            graceMinutes = obj.optInt("grace_minutes", 10).coerceAtLeast(1),
            missedAfterMinutes = obj.optInt("missed_after_minutes", 30).coerceAtLeast(2),
            takenAt = obj.optString("taken_at").takeIf { it.isNotBlank() && it != "null" },
            confirmationSource = obj.optString("confirmation_source"),
            source = obj.optString("source"),
            agentDecision = obj.optJSONObject("agent_decision")?.let { decision ->
                val labels = decision.optJSONArray("planned_tool_labels")
                AgentDecisionItem(
                    stageLabel = decision.optString("stage_label"),
                    plannerLabel = decision.optString("planner_label"),
                    riskScore = decision.optInt("risk_score"),
                    riskLabel = decision.optString("risk_label"),
                    toolLabels = buildList {
                        if (labels != null) {
                            for (index in 0 until labels.length()) {
                                val label = labels.optString(index)
                                if (label.isNotBlank()) add(label)
                            }
                        }
                    },
                    reasoning = decision.optString("reasoning"),
                    confidencePercent = decision.optInt("confidence_percent"),
                    evidenceLabels = buildList {
                        val evidence = decision.optJSONArray("evidence_labels")
                        if (evidence != null) {
                            for (index in 0 until evidence.length()) {
                                evidence.optString(index).takeIf { it.isNotBlank() }?.let(::add)
                            }
                        }
                    },
                    validationSummary = decision.optString("validation_summary"),
                    situationSummary = decision.optString("situation_summary"),
                    nextStepSummary = decision.optString("next_step_summary"),
                    notificationMessage = decision.optString("notification_message")
                )
            }
        )
    }
}
