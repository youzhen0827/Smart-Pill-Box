package com.example.smartpillbox

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.concurrent.thread

internal object AgentSyncScheduler {
    private const val ACTION_SYNC = "com.example.smartpillbox.AGENT_SYNC"
    private const val REQUEST_CODE = 88001
    private const val INTERVAL_MS = 15 * 60_000L

    fun start(context: Context) {
        val pending = PendingIntent.getBroadcast(
            context,
            REQUEST_CODE,
            Intent(context, AgentSyncReceiver::class.java).setAction(ACTION_SYNC),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        context.getSystemService(AlarmManager::class.java).setInexactRepeating(
            AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + 5_000L,
            INTERVAL_MS,
            pending
        )
    }
}

class AgentSyncReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val appContext = context.applicationContext
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) AgentSyncScheduler.start(appContext)
        val pendingResult = goAsync()
        thread(name = "agent-background-sync") {
            try {
                sync(appContext)
            } finally {
                pendingResult.finish()
            }
        }
    }

    private fun sync(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val userName = prefs.getString(KEY_USER_NAME, "").orEmpty().trim()
        if (userName.isBlank()) return
        val api = ApiClient(
            prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL).orEmpty(),
            prefs.getString(KEY_API_TOKEN, DEFAULT_TOKEN).orEmpty()
        )
        runCatching {
            val response = api.reminders(userName, taipeiDate())
            val array = response.optJSONArray("results")
            val reminders = buildList {
                if (array != null) {
                    for (index in 0 until array.length()) {
                        array.optJSONObject(index)?.let { add(ReminderItem.fromJson(it)) }
                    }
                }
            }
            AgentReminderScheduler.scheduleAll(context, reminders)
            deliverCreatedInterventions(context, api, userName)
        }
    }

    private fun deliverCreatedInterventions(context: Context, api: ApiClient, userName: String) {
        val results = api.interventions(userName).optJSONArray("results") ?: return
        for (index in 0 until results.length()) {
            val item = results.optJSONObject(index) ?: continue
            val reminder = item.optJSONObject("reminder") ?: continue
            val reminderId = reminder.optInt("id")
            if (reminderId <= 0 || reminder.optString("status") != "已提醒") continue
            val type = item.optString("type")
            val notificationId = reminderId * 10 + stageCode(type)
            val shown = AgentReminderReceiver.showNotification(
                context,
                notificationId,
                AgentReminderReceiver.titleForType(type),
                item.optString("message")
            )
            if (shown) api.updateInterventionState(item.optInt("id"), "delivered")
        }
    }

    private fun stageCode(type: String): Int = when (type) {
        "initial_reminder" -> 1
        "missed_escalation" -> 3
        else -> 2
    }

    companion object {
        private const val PREFS_NAME = "smart_medicine_box_api"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_API_TOKEN = "api_token"
        private const val KEY_USER_NAME = "user_name"
        private const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/api/v1/"
        private const val DEFAULT_TOKEN = "smartpill-dev-token"

        private fun taipeiDate(): String = SimpleDateFormat("yyyy-MM-dd", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("Asia/Taipei")
        }.format(Date())
    }
}
