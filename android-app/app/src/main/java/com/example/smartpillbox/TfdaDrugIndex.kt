package com.example.smartpillbox

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.zip.GZIPInputStream

internal data class TfdaDrugRecord(
    val permitNumber: String,
    val chineseName: String,
    val englishName: String,
    val indications: String,
    val dosage: String,
    val ingredients: String
)

internal data class TfdaDrugMatch(
    val record: TfdaDrugRecord,
    val sectionField: String,
    val sectionText: String,
    val identityScore: Int
)

internal object TfdaDrugMatcher {
    private fun normalize(value: String): String = value
        .lowercase(Locale.ROOT)
        .replace(Regex("[^a-z0-9\u3400-\u9fff]"), "")

    fun identityScore(query: String, record: TfdaDrugRecord): Int {
        val normalizedQuery = normalize(query)
        if (normalizedQuery.length < 2) return 0
        val names = listOf(record.permitNumber, record.chineseName, record.englishName)
            .map(::normalize)
            .filter(String::isNotBlank)
        if (names.any { it == normalizedQuery }) return 100
        if (names.any { normalizedQuery.length >= 4 && (it.contains(normalizedQuery) || normalizedQuery.contains(it)) }) {
            return 90
        }
        val ingredient = normalize(record.ingredients)
        return if (normalizedQuery.length >= 4 && ingredient.contains(normalizedQuery)) 80 else 0
    }
}

internal class TfdaDrugIndex(private val context: Context) {
    fun find(query: String, kind: EducationQuestionKind): TfdaDrugMatch? {
        var best: TfdaDrugMatch? = null
        GZIPInputStream(context.assets.open("tfda_active_drugs.dat")).use { stream ->
            BufferedReader(InputStreamReader(stream, StandardCharsets.UTF_8)).useLines { lines ->
                lines.forEach { line ->
                    val values = line.split('\t', limit = 6)
                    if (values.size != 6) return@forEach
                    val record = TfdaDrugRecord(
                        permitNumber = values[0],
                        chineseName = values[1],
                        englishName = values[2],
                        indications = values[3],
                        dosage = values[4],
                        ingredients = values[5]
                    )
                    val section = when (kind) {
                        EducationQuestionKind.INDICATIONS, EducationQuestionKind.GENERAL ->
                            "indications_and_usage" to record.indications
                        EducationQuestionKind.DOSAGE, EducationQuestionKind.MISSED_DOSE ->
                            "dosage_and_administration" to record.dosage
                        else -> null
                    } ?: return@forEach
                    if (section.second.isBlank()) return@forEach
                    val score = TfdaDrugMatcher.identityScore(query, record)
                    if (score >= 70 && score > (best?.identityScore ?: -1)) {
                        best = TfdaDrugMatch(record, section.first, section.second, score)
                    }
                }
            }
        }
        return best
    }
}
