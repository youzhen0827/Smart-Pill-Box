package com.example.smartpillbox

import org.json.JSONArray

object SlotLabels {
    const val SLOT_COUNT = 3

    private val names = listOf("早", "中", "晚")
    private val periods = listOf("morning", "noon", "evening")

    fun isValid(slot: Int?): Boolean = slot != null && slot in 1..SLOT_COUNT

    fun label(slot: Int): String = names.getOrNull(slot - 1) ?: "未指定"

    fun label(slot: Int?): String = slot?.let { label(it) } ?: "未指定"

    fun period(slot: Int): String = periods.getOrNull(slot - 1) ?: "morning"

    fun display(slot: Int?, apiLabel: String = ""): String {
        val normalized = apiLabel.trim()
        return if (normalized in names && isValid(slot)) normalized else label(slot)
    }

    fun optionLabels(): List<String> = names

    fun withStatus(slot: Int, status: String): String = "${label(slot)}\n$status"

    fun healthContractIsThreeSlot(slotCount: Int, slots: JSONArray?): Boolean {
        if (slotCount != SLOT_COUNT || slots == null || slots.length() != SLOT_COUNT) return false
        for (index in 0 until SLOT_COUNT) {
            val item = slots.optJSONObject(index) ?: return false
            if (item.optInt("slot") != index + 1) return false
            if (item.optString("label") != names[index]) return false
        }
        return true
    }
}
