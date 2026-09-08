package com.example.smartpillbox

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView

class ReminderAdapter(
    private val onTaken: (ReminderItem) -> Unit,
    private val onDelete: (ReminderItem) -> Unit
) : RecyclerView.Adapter<ReminderAdapter.ReminderViewHolder>() {

    private val items = mutableListOf<ReminderItem>()

    fun submitList(newItems: List<ReminderItem>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    class ReminderViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val time: TextView = itemView.findViewById(R.id.tvItemTime)
        val medicine: TextView = itemView.findViewById(R.id.tvItemMedicineName)
        val dose: TextView = itemView.findViewById(R.id.tvItemDose)
        val hint: TextView = itemView.findViewById(R.id.tvItemHint)
        val status: TextView = itemView.findViewById(R.id.tvItemStatus)
        val meta: TextView = itemView.findViewById(R.id.tvItemMeta)
        val agent: TextView = itemView.findViewById(R.id.tvItemAgent)
        val takenButton: Button = itemView.findViewById(R.id.btnItemTaken)
        val deleteButton: Button = itemView.findViewById(R.id.btnItemDelete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ReminderViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_reminder_timeline, parent, false)
        return ReminderViewHolder(view)
    }

    override fun onBindViewHolder(holder: ReminderViewHolder, position: Int) {
        val item = items[position]
        holder.time.text = item.scheduledTime.ifBlank { "未設定" }
        holder.medicine.text = item.medicineName
        holder.dose.text = "${item.doseCount} 顆／份"
        holder.hint.text = item.reminderHint.ifBlank { "無額外提醒" }
        holder.status.text = resultLabel(item)
        val slotText = SlotLabels.display(item.slot, item.slotLabel)
        holder.meta.text = "$slotText · ${item.deviceId.ifBlank { "未指定裝置" }}"
        holder.agent.text = buildString {
            append("追蹤進度：${agentStateLabel(item.agentState)}")
            append("\n確認依據：${confirmationLabel(item.confirmationSource)}")
            append(" · 來源：${sourceLabel(item.source)}")
            append(" · 提醒 ${item.reminderCount} 次")
        }

        when (item.status) {
            "已服藥" -> {
                holder.status.setBackgroundResource(R.drawable.chip_status_taken)
                holder.status.setTextColor(ContextCompat.getColor(holder.itemView.context, R.color.ok_green))
            }
            "漏服" -> {
                holder.status.setBackgroundResource(R.drawable.chip_status_missed)
                holder.status.setTextColor(ContextCompat.getColor(holder.itemView.context, R.color.danger_red))
            }
            else -> {
                holder.status.setBackgroundResource(R.drawable.chip_status_pending)
                holder.status.setTextColor(ContextCompat.getColor(holder.itemView.context, R.color.warn_orange))
            }
        }

        holder.takenButton.visibility = if (item.status == "已服藥") View.GONE else View.VISIBLE
        holder.takenButton.text = if (item.status == "漏服") "更正為已服藥" else "確認已服藥"
        holder.takenButton.setOnClickListener { onTaken(item) }
        holder.deleteButton.setOnClickListener { onDelete(item) }
    }

    override fun getItemCount(): Int = items.size

    private fun agentStateLabel(value: String): String = when (value) {
        "pending" -> "尚未到時"
        "waiting_sensor" -> "等待開盒"
        "intervened" -> "已再次提醒"
        "taken" -> "追蹤完成"
        "missed" -> "需要照護者確認"
        else -> value.ifBlank { "未知" }
    }

    private fun resultLabel(item: ReminderItem): String = when (item.status) {
        "已服藥" -> if (item.confirmationSource == "sensor") "推定已取藥" else "已確認服藥"
        "漏服" -> "疑似漏服"
        else -> if (item.agentState == "pending") "待執行" else "待確認"
    }

    private fun confirmationLabel(value: String): String = when (value) {
        "sensor" -> "藥盒已開啟"
        "android" -> "Android 使用者確認"
        "web" -> "照護者網頁確認"
        "raspberry_pi" -> "Raspberry Pi 回報"
        else -> "尚無證據"
    }

    private fun sourceLabel(value: String): String = when (value) {
        "schedule" -> "固定排程"
        "web" -> "網頁臨時新增"
        "android" -> "Android 臨時新增"
        "sensor" -> "感測器"
        else -> "未知"
    }
}
