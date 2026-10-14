package com.example.smartpillbox

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.concurrent.thread

class AgentReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pendingResult = goAsync()
        thread(name = "agent-reminder") {
            try {
                deliver(context.applicationContext, intent)
            } finally {
                pendingResult.finish()
            }
        }
    }

    private fun deliver(context: Context, intent: Intent) {
        val reminderId = intent.getIntExtra("reminder_id", 0)
        val userName = intent.getStringExtra("user_name").orEmpty()
        val medicineName = intent.getStringExtra("medicine_name").orEmpty()
        val doseCount = intent.getStringExtra("dose_count").orEmpty()
        val scheduledTime = intent.getStringExtra("scheduled_time").orEmpty()
        val reminderHint = intent.getStringExtra("reminder_hint").orEmpty()
        val minutesLate = intent.getIntExtra("minutes_late", 0)
        val stage = intent.getStringExtra("stage").orEmpty()
        var title = intent.getStringExtra("title").orEmpty().ifBlank { "AI Agent 服藥提醒" }
        var message = intent.getStringExtra("message").orEmpty()
        var trainedModelOutput = false
        var deliveredInterventionId = 0
        var apiClient: ApiClient? = null

        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val baseUrl = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL).orEmpty()
        val token = prefs.getString(KEY_API_TOKEN, DEFAULT_TOKEN).orEmpty()
        if (reminderId > 0 && userName.isNotBlank()) {
            runCatching {
                val api = ApiClient(baseUrl, token)
                apiClient = api
                val current = findReminder(api.reminders(userName, taipeiDate()), reminderId)
                if (current != null && current.optString("status") != "已提醒") {
                    AgentReminderScheduler.cancel(context, reminderId)
                    return
                }
                val intervention = findIntervention(api.interventions(userName), reminderId, stage)
                if (intervention != null) {
                    trainedModelOutput = intervention.optString("channel").contains("trained_minicpm")
                    title = titleForType(
                        intervention.optString("type"),
                        trainedModelOutput
                    )
                    message = intervention.optString("message", message)
                    deliveredInterventionId = intervention.optInt("id")
                }
            }
        }
        if (!trainedModelOutput && userName.isNotBlank() && medicineName.isNotBlank()) {
            runCatching {
                MiniCpmOnDeviceModel(context).use { model ->
                    message = model.generateMedicationReminder(
                        userName = userName,
                        medicineName = medicineName,
                        doseCount = doseCount.ifBlank { "1 粒" },
                        scheduledTime = scheduledTime,
                        reminderHint = reminderHint,
                        stage = stage,
                        minutesLate = minutesLate
                    )
                }
                title = titleForType(typeForStage(stage), trainedModel = true)
                trainedModelOutput = true
                deliveredInterventionId = 0
            }
        }
        if (message.isNotBlank()) {
            val shown = showNotification(context, reminderId * 10 + stageCode(stage), title, message)
            if (shown && deliveredInterventionId > 0) {
                runCatching { apiClient?.updateInterventionState(deliveredInterventionId, "delivered") }
            }
        }
    }

    private fun findReminder(response: JSONObject, reminderId: Int): JSONObject? {
        val results = response.optJSONArray("results") ?: return null
        for (index in 0 until results.length()) {
            val item = results.optJSONObject(index) ?: continue
            if (item.optInt("id") == reminderId) return item
        }
        return null
    }

    private fun findIntervention(
        response: JSONObject,
        reminderId: Int,
        stage: String
    ): JSONObject? {
        val allowed = when (stage) {
            "due" -> setOf("initial_reminder")
            "followup" -> setOf("sensor_missing", "device_check", "caregiver_escalation")
            "missed" -> setOf("missed_escalation")
            else -> emptySet()
        }
        val results = response.optJSONArray("results") ?: return null
        for (index in 0 until results.length()) {
            val item = results.optJSONObject(index) ?: continue
            val itemReminder = item.optJSONObject("reminder")
            if (itemReminder?.optInt("id") == reminderId && item.optString("type") in allowed) return item
        }
        return null
    }

    companion object {
        private const val CHANNEL_ID = "ai_agent_medication_reminders"
        private const val PREFS_NAME = "smart_medicine_box_api"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_API_TOKEN = "api_token"
        private const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/api/v1/"
        private const val DEFAULT_TOKEN = "smartpill-dev-token"

        internal fun showNotification(context: Context, id: Int, title: String, message: String): Boolean {
            if (
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) return false

            val manager = context.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                manager.createNotificationChannel(
                    NotificationChannel(
                        CHANNEL_ID,
                        "AI Agent 服藥提醒",
                        NotificationManager.IMPORTANCE_HIGH
                    ).apply {
                        description = "依照原本服藥時間、再次提醒與漏服標準主動通知"
                        enableVibration(true)
                    }
                )
            }
            val openApp = PendingIntent.getActivity(
                context,
                id,
                Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .setAutoCancel(true)
                .setContentIntent(openApp)
                .build()
            NotificationManagerCompat.from(context).notify(id, notification)
            return true
        }

        internal fun titleForType(type: String, trainedModel: Boolean = false): String {
            val prefix = if (trainedModel) "訓練 AI" else "安全提醒"
            return when (type) {
                "initial_reminder" -> "$prefix：現在該吃藥了"
                "sensor_missing" -> "$prefix：還沒偵測到開盒"
                "device_check" -> "$prefix：藥盒暫時沒有回報"
                "caregiver_escalation" -> "$prefix：請照護者協助確認"
                "missed_escalation" -> "$prefix：可能漏服，請確認"
                else -> "$prefix：服藥提醒"
            }
        }

        private fun stageCode(stage: String): Int = when (stage) {
            "due" -> 1
            "followup" -> 2
            else -> 3
        }

        private fun typeForStage(stage: String): String = when (stage) {
            "due" -> "initial_reminder"
            "followup" -> "sensor_missing"
            "missed" -> "missed_escalation"
            else -> ""
        }

        private fun taipeiDate(): String = SimpleDateFormat("yyyy-MM-dd", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("Asia/Taipei")
        }.format(Date())
    }
}
