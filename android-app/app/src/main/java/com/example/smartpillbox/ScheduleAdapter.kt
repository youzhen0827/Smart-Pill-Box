package com.example.smartpillbox

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class ScheduleAdapter(
    private val onEdit: (ScheduleItem) -> Unit,
    private val onDelete: (ScheduleItem) -> Unit
) : RecyclerView.Adapter<ScheduleAdapter.ScheduleViewHolder>() {

    private val items = mutableListOf<ScheduleItem>()

    fun submitList(newItems: List<ScheduleItem>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    class ScheduleViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val time: TextView = itemView.findViewById(R.id.tvScheduleTime)
        val medicine: TextView = itemView.findViewById(R.id.tvScheduleMedicine)
        val meta: TextView = itemView.findViewById(R.id.tvScheduleMeta)
        val weekdays: TextView = itemView.findViewById(R.id.tvScheduleWeekdays)
        val editButton: Button = itemView.findViewById(R.id.btnScheduleItemEdit)
        val deleteButton: Button = itemView.findViewById(R.id.btnScheduleItemDelete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ScheduleViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_schedule, parent, false)
        return ScheduleViewHolder(view)
    }

    override fun onBindViewHolder(holder: ScheduleViewHolder, position: Int) {
        val item = items[position]
        holder.time.text = item.scheduledTime
        holder.medicine.text = item.medicineName
        holder.meta.text = "${SlotLabels.display(item.slot, item.slotLabel)} · ${item.doseCount} 顆/份 · ${item.deviceId.ifBlank { "pillbox-01" }}"
        holder.weekdays.text = "星期 ${weekdayLabel(item.weekdays)}"
        holder.editButton.setOnClickListener { onEdit(item) }
        holder.deleteButton.setOnClickListener { onDelete(item) }
    }

    override fun getItemCount(): Int = items.size

    private fun weekdayLabel(value: String): String =
        value.split(",")
            .mapNotNull { it.trim().toIntOrNull() }
            .filter { it in 1..7 }
            .joinToString("、")
            .ifBlank { "未設定" }
}
