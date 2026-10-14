package com.example.smartpillbox

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import java.text.SimpleDateFormat
import java.util.Locale

internal object AgentReminderScheduler {
    private const val ACTION_REMIND = "com.example.smartpillbox.AGENT_REMIND"

    fun scheduleAll(context: Context, reminders: List<ReminderItem>) {
        reminders.forEach { reminder ->
            if (reminder.status == "已提醒") schedule(context, reminder) else cancel(context, reminder.id)
        }
    }

    fun schedule(context: Context, reminder: ReminderItem) {
        val dueAt = parseTimestamp(reminder.scheduledDatetime) ?: return
        val stages = listOf(
            AlarmStage(
                code = 1,
                name = "due",
                triggerAt = dueAt,
                title = "安全提醒：現在該吃藥了",
                message = "${reminder.userName}，請服用 ${reminder.medicineName} ${reminder.doseCount}。${reminder.reminderHint}"
            ),
            AlarmStage(
                code = 2,
                name = "followup",
                triggerAt = dueAt + reminder.graceMinutes * 60_000L,
                title = "安全提醒：請確認是否已吃藥",
                message = "已超過服藥時間 ${reminder.graceMinutes} 分鐘，尚未確認服藥，請查看藥盒。"
            ),
            AlarmStage(
                code = 3,
                name = "missed",
                triggerAt = dueAt + reminder.missedAfterMinutes * 60_000L,
                title = "安全提醒：需要照護者確認",
                message = "已超過服藥時間 ${reminder.missedAfterMinutes} 分鐘，請家人或照護者確認是否已服藥。"
            )
        )
        stages.forEach { stage -> scheduleStage(context, reminder, stage) }
    }

    fun cancel(context: Context, reminderId: Int) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        for (stageCode in 1..3) {
            val requestCode = requestCode(reminderId, stageCode)
            val pending = pendingIntent(context, reminderId, stageCode, Intent(), PendingIntent.FLAG_NO_CREATE)
            if (pending != null) {
                alarmManager.cancel(pending)
                pending.cancel()
            }
            NotificationManagerCompat.from(context).cancel(requestCode)
        }
    }

    private fun scheduleStage(context: Context, reminder: ReminderItem, stage: AlarmStage) {
        if (stage.triggerAt <= System.currentTimeMillis()) return
        val extras = Intent()
            .putExtra("reminder_id", reminder.id)
            .putExtra("user_name", reminder.userName)
            .putExtra("medicine_name", reminder.medicineName)
            .putExtra("dose_count", reminder.doseCount)
            .putExtra("scheduled_time", reminder.scheduledTime)
            .putExtra("reminder_hint", reminder.reminderHint)
            .putExtra("minutes_late", when (stage.name) {
                "followup" -> reminder.graceMinutes
                "missed" -> reminder.missedAfterMinutes
                else -> 0
            })
            .putExtra("stage", stage.name)
            .putExtra("title", stage.title)
            .putExtra("message", stage.message)
        val pending = pendingIntent(
            context,
            reminder.id,
            stage.code,
            extras,
            PendingIntent.FLAG_UPDATE_CURRENT
        ) ?: return
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarmManager.canScheduleExactAlarms()) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, stage.triggerAt, pending)
        } else {
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, stage.triggerAt, pending)
        }
    }

    private fun pendingIntent(
        context: Context,
        reminderId: Int,
        stageCode: Int,
        extras: Intent,
        flag: Int
    ): PendingIntent? {
        val intent = Intent(context, AgentReminderReceiver::class.java)
            .setAction(ACTION_REMIND)
            .putExtras(extras)
        return PendingIntent.getBroadcast(
            context,
            requestCode(reminderId, stageCode),
            intent,
            flag or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun requestCode(reminderId: Int, stageCode: Int): Int = reminderId * 10 + stageCode

    private fun parseTimestamp(value: String?): Long? {
        if (value.isNullOrBlank()) return null
        val normalized = value.replace(Regex("\\.\\d+([+-]\\d{2}:\\d{2}|Z)$"), "$1")
        return runCatching {
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).parse(normalized)?.time
        }.getOrNull()
    }

    private data class AlarmStage(
        val code: Int,
        val name: String,
        val triggerAt: Long,
        val title: String,
        val message: String
    )
}
