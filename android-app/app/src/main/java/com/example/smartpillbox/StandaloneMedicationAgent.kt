package com.example.smartpillbox

import android.content.Context
import androidx.core.text.HtmlCompat
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.Closeable
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.Locale

internal class MedicationEducationException(message: String) : Exception(message)

internal data class MedicationEducationDraft(
    val drugQuery: String,
    val displayDrug: String,
    val question: String,
    val kind: EducationQuestionKind,
    val sectionField: String,
    val sourceText: String,
    val sourceUrl: String,
    val fromCache: Boolean
)

internal data class MedicationEducationAnswer(
    val answer: String,
    val evidence: String,
    val questionLabel: String,
    val usedDownloadedModel: Boolean,
    val fromCache: Boolean
)

internal class StandaloneMedicationAgent(context: Context) : Closeable {
    private val cache = context.getSharedPreferences("standalone_medication_education", Context.MODE_PRIVATE)
    private val translator: Translator = Translation.getClient(
        TranslatorOptions.Builder()
            .setSourceLanguage(TranslateLanguage.ENGLISH)
            .setTargetLanguage(TranslateLanguage.CHINESE)
            .build()
    )

    fun fetchDraft(drug: String, question: String): MedicationEducationDraft {
        val kind = MedicationEducationLogic.detectQuestion(question)
        val cacheKey = "label_${drug.lowercase(Locale.ROOT).replace(Regex("[^a-z0-9-]"), "_")}".take(120)
        var fromCache = false
        val record = try {
            val online = queryOpenFda(drug, kind)
            cache.edit().putString(cacheKey, online.toString()).apply()
            online
        } catch (error: Exception) {
            val saved = cache.getString(cacheKey, null)
            if (saved.isNullOrBlank()) {
                throw MedicationEducationException(
                    error.message ?: "APP 無法取得 FDA 藥品資料，請確認手機網路後再試。"
                )
            }
            fromCache = true
            JSONObject(saved)
        }

        val field = MedicationEducationLogic.fieldCandidates(kind)
            .firstOrNull { jsonText(record, it).isNotBlank() }
            ?: throw MedicationEducationException(
                "FDA 找到這個藥，但沒有「${MedicationEducationLogic.label(kind)}」的資料。請改問其他問題，或詢問醫師、藥師。"
            )
        val sourceText = plainExcerpt(jsonText(record, field), maxChars = 420)
        val openFda = record.optJSONObject("openfda")
        val displayDrug = firstArrayText(openFda, "brand_name")
            .ifBlank { firstArrayText(openFda, "generic_name") }
            .ifBlank { drug }

        return MedicationEducationDraft(
            drugQuery = drug,
            displayDrug = displayDrug,
            question = question,
            kind = kind,
            sectionField = field,
            sourceText = sourceText,
            sourceUrl = "https://open.fda.gov/apis/drug/label/",
            fromCache = fromCache
        )
    }

    fun answerInChinese(
        draft: MedicationEducationDraft,
        onPreparingModel: () -> Unit,
        onSuccess: (MedicationEducationAnswer) -> Unit,
        onFailure: (String) -> Unit
    ) {
        MedicationEducationLogic.offlineTranslation(draft.sourceText)?.let { translated ->
            onSuccess(composeAnswer(draft, translated, usedDownloadedModel = false))
            return
        }

        onPreparingModel()
        translator.downloadModelIfNeeded(DownloadConditions.Builder().build())
            .addOnSuccessListener {
                translateChunks(
                    MedicationEducationLogic.translationChunks(draft.sourceText),
                    onSuccess = { translated ->
                        onSuccess(composeAnswer(draft, translated, usedDownloadedModel = true))
                    },
                    onFailure = {
                        onFailure("手機內翻譯失敗，請確認儲存空間足夠後再試。")
                    }
                )
            }
            .addOnFailureListener {
                onFailure("首次使用需下載中文翻譯模型，請開啟手機網路後再試。下載完成後，翻譯不需連接網頁。")
            }
    }

    private fun translateChunks(
        chunks: List<String>,
        index: Int = 0,
        translated: MutableList<String> = mutableListOf(),
        onSuccess: (String) -> Unit,
        onFailure: (Exception) -> Unit
    ) {
        if (index >= chunks.size) {
            onSuccess(MedicationEducationLogic.simplifyChinese(translated.joinToString(" ")))
            return
        }
        translator.translate(chunks[index])
            .addOnSuccessListener { result ->
                translated += result
                translateChunks(chunks, index + 1, translated, onSuccess, onFailure)
            }
            .addOnFailureListener(onFailure)
    }

    private fun composeAnswer(
        draft: MedicationEducationDraft,
        translatedText: String,
        usedDownloadedModel: Boolean
    ): MedicationEducationAnswer {
        val questionLabel = MedicationEducationLogic.label(draft.kind)
        val sectionLabel = MedicationEducationLogic.sectionLabel(draft.sectionField)
        val conciseText = MedicationEducationLogic.conciseAnswer(translatedText)
        val answer = buildString {
            append("藥物：${draft.displayDrug}\n\n")
            append("【$sectionLabel】\n")
            append(MedicationEducationLogic.prefix(draft.kind))
            append(conciseText)
            append("\n\n【請注意】\n")
            append(MedicationEducationLogic.nextStep(draft.kind))
        }
        val evidence = buildString {
            append("資料證據（APP 直接取得）：\n")
            append("openFDA 美國 FDA 藥品標籤\n")
            append("藥物：${draft.displayDrug}\n")
            append("內容：$sectionLabel\n")
            append(draft.sourceUrl)
        }
        return MedicationEducationAnswer(
            answer = answer,
            evidence = evidence,
            questionLabel = questionLabel,
            usedDownloadedModel = usedDownloadedModel,
            fromCache = draft.fromCache
        )
    }

    private fun queryOpenFda(drug: String, kind: EducationQuestionKind): JSONObject {
        val term = URLEncoder.encode("\"${drug.replace("\"", "").trim()}\"", StandardCharsets.UTF_8.name())
        val searches = if (drug.matches(Regex("[0-9-]+"))) {
            listOf("openfda.product_ndc:$term")
        } else {
            listOf(
                "openfda.generic_name:$term+openfda.brand_name:$term",
                "openfda.substance_name:$term"
            )
        }
        var lastMessage = "FDA 找不到此藥。請輸入藥袋上的英文學名、品牌名或 Product NDC。"
        for (search in searches) {
            val url = "https://api.fda.gov/drug/label.json?search=$search&limit=5"
            try {
                val results = requestResults(url) ?: continue
                for (index in 0 until results.length()) {
                    val record = results.optJSONObject(index) ?: continue
                    if (MedicationEducationLogic.fieldCandidates(kind).any { jsonText(record, it).isNotBlank() }) {
                        return record
                    }
                }
                lastMessage = "FDA 找到藥品，但沒有「${MedicationEducationLogic.label(kind)}」資料。"
            } catch (error: MedicationEducationException) {
                lastMessage = error.message ?: lastMessage
            }
        }
        throw MedicationEducationException(lastMessage)
    }

    private fun requestResults(url: String): JSONArray? {
        var connection: HttpURLConnection? = null
        try {
            connection = URI(url).toURL().openConnection() as HttpURLConnection
            connection.requestMethod = "GET"
            connection.connectTimeout = 12_000
            connection.readTimeout = 25_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", "SmartMedicineBox-Android/2.1.6")
            val status = connection.responseCode
            if (status == 404) return null
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.let {
                BufferedReader(InputStreamReader(it, StandardCharsets.UTF_8)).use { reader ->
                    reader.readText()
                }
            }.orEmpty()
            if (status !in 200..299) {
                val message = if (status == 429) {
                    "FDA 查詢次數暫時過多，請稍後再試。"
                } else {
                    "APP 無法取得 FDA 資料（HTTP $status）。"
                }
                throw MedicationEducationException(message)
            }
            return JSONObject(body).optJSONArray("results")
        } catch (error: MedicationEducationException) {
            throw error
        } catch (error: Exception) {
            throw MedicationEducationException("APP 無法連到 FDA，請確認手機網路後再試。")
        } finally {
            connection?.disconnect()
        }
    }

    private fun jsonText(record: JSONObject, field: String): String {
        val value = record.opt(field)
        return when (value) {
            is JSONArray -> (0 until value.length())
                .mapNotNull { value.optString(it).takeIf(String::isNotBlank) }
                .joinToString("\n")
            is String -> value
            else -> ""
        }
    }

    private fun firstArrayText(record: JSONObject?, field: String): String {
        return record?.optJSONArray(field)?.optString(0).orEmpty()
    }

    private fun plainExcerpt(text: String, maxChars: Int = 900): String {
        val plain = HtmlCompat.fromHtml(text, HtmlCompat.FROM_HTML_MODE_LEGACY)
            .toString()
            .replace(Regex("\\s+"), " ")
            .trim()
        if (plain.length <= maxChars) return plain
        val clipped = plain.take(maxChars)
        val stop = listOf(clipped.lastIndexOf(". "), clipped.lastIndexOf("; "))
            .maxOrNull()
            ?.takeIf { it >= maxChars / 2 }
        val shortened = if (stop != null) clipped.take(stop + 1) else clipped
        return shortened.trimEnd() + "…"
    }

    override fun close() {
        translator.close()
    }
}
