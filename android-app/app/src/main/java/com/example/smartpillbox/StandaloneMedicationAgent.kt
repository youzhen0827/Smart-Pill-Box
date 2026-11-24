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
    val sourceName: String,
    val sourceId: String,
    val sourceUrl: String,
    val fromCache: Boolean,
    val identityScore: Int
)

internal data class MedicationEducationAnswer(
    val answer: String,
    val evidence: String,
    val questionLabel: String,
    val usedDownloadedModel: Boolean,
    val fromCache: Boolean,
    val qualityPassed: Boolean,
    val qualityMessage: String,
    val qualityScore: Int,
    val qualityChecks: List<EducationValidationCheck>,
    val revisionCount: Int,
    val sourceName: String
)

internal class StandaloneMedicationAgent(context: Context) : Closeable {
    private val cache = context.getSharedPreferences("standalone_medication_education", Context.MODE_PRIVATE)
    private val tfdaIndex = TfdaDrugIndex(context.applicationContext)
    private val miniCpm = MiniCpmOnDeviceModel(context.applicationContext)
    private val translator: Translator = Translation.getClient(
        TranslatorOptions.Builder()
            .setSourceLanguage(TranslateLanguage.ENGLISH)
            .setTargetLanguage(TranslateLanguage.CHINESE)
            .build()
    )

    fun fetchDraft(drug: String, question: String): MedicationEducationDraft {
        val kind = MedicationEducationLogic.detectQuestion(question)
        runCatching { tfdaIndex.find(drug, kind) }.getOrNull()?.let { match ->
            val displayDrug = match.record.chineseName.ifBlank { match.record.englishName }
            return MedicationEducationDraft(
                drugQuery = drug,
                displayDrug = displayDrug,
                question = question,
                kind = kind,
                sectionField = match.sectionField,
                sourceText = plainExcerpt(match.sectionText, maxChars = 420),
                sourceName = "台灣食藥署未註銷藥品許可證",
                sourceId = match.record.permitNumber,
                sourceUrl = "https://data.gov.tw/dataset/9123",
                fromCache = false,
                identityScore = match.identityScore
            )
        }
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
        val identityScore = recordIdentityScore(record, drug)
        if (identityScore < 70) {
            throw MedicationEducationException("找到的資料和輸入藥名不完全相符，Agent 已停止回答。")
        }

        return MedicationEducationDraft(
            drugQuery = drug,
            displayDrug = displayDrug,
            question = question,
            kind = kind,
            sectionField = field,
            sourceText = sourceText,
            sourceName = "openFDA 美國 FDA 藥品標籤",
            sourceId = record.optString("id").ifBlank { record.optString("set_id") },
            sourceUrl = "https://open.fda.gov/apis/drug/label/",
            fromCache = fromCache,
            identityScore = identityScore
        )
    }

    fun answerInChinese(
        draft: MedicationEducationDraft,
        onPreparingModel: (String) -> Unit,
        onSuccess: (MedicationEducationAnswer) -> Unit,
        onFailure: (String) -> Unit
    ) {
        miniCpm.rewriteForSenior(
            draft = draft,
            onPreparing = {
                onPreparingModel("正在準備手機內 MiniCPM5-2B；第一次使用需連接 Wi-Fi 下載約 1.55 GB…")
            },
            onProgress = onPreparingModel,
            onSuccess = { generated ->
                onSuccess(composeAnswer(draft, generated, usedDownloadedModel = true))
            },
            onFailure = {
                fallbackAnswerInChinese(draft, onPreparingModel, onSuccess, onFailure)
            }
        )
    }

    private fun fallbackAnswerInChinese(
        draft: MedicationEducationDraft,
        onPreparingModel: (String) -> Unit,
        onSuccess: (MedicationEducationAnswer) -> Unit,
        onFailure: (String) -> Unit
    ) {
        if (draft.sourceName.startsWith("台灣食藥署")) {
            onSuccess(
                composeAnswer(
                    draft,
                    MedicationEducationLogic.simplifyChinese(draft.sourceText),
                    usedDownloadedModel = false
                )
            )
            return
        }
        MedicationEducationLogic.offlineTranslation(draft.sourceText)?.let { translated ->
            onSuccess(composeAnswer(draft, translated, usedDownloadedModel = false))
            return
        }

        onPreparingModel("MiniCPM5-2B 暫時無法使用，正在改用手機內中文翻譯模型…")
        translator.downloadModelIfNeeded(DownloadConditions.Builder().build())
            .addOnSuccessListener {
                translateChunks(
                    MedicationEducationLogic.translationChunks(draft.sourceText),
                    onSuccess = { translated ->
                        onSuccess(composeAnswer(draft, translated, usedDownloadedModel = false))
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
        var conciseText = MedicationEducationLogic.conciseAnswer(translatedText)
        var review = MedicationEducationLogic.reviewAnswer(
            draft.kind,
            draft.sectionField,
            draft.sourceText,
            conciseText,
            draft.identityScore
        )
        var revisionCount = 0
        if (!review.passed) {
            val revisedText = MedicationEducationLogic.conciseAnswer(
                translatedText,
                maxChars = 220,
                maxSentences = 1
            )
            val revisedReview = MedicationEducationLogic.reviewAnswer(
                draft.kind,
                draft.sectionField,
                draft.sourceText,
                revisedText,
                draft.identityScore
            )
            if (revisedReview.score > review.score) {
                conciseText = revisedText
                review = revisedReview
                revisionCount = 1
            }
        }
        val answer = if (review.passed) {
            buildString {
                append(conciseText)
                append("\n\n提醒你：")
                append(MedicationEducationLogic.nextStep(draft.kind).removePrefix("請注意：").trim())
            }
        } else {
            "這次找到的資料還不足以清楚回答你的問題。請換一個更明確的問法，或帶著藥袋詢問醫師、藥師。"
        }
        val evidence = buildString {
            append("資料證據（APP 直接取得）：\n")
            append("${draft.sourceName}\n")
            append("藥物：${draft.displayDrug}\n")
            append("內容：$sectionLabel\n")
            if (draft.sourceId.isNotBlank()) append("資料編號：${draft.sourceId}\n")
            append(draft.sourceUrl)
        }
        return MedicationEducationAnswer(
            answer = answer,
            evidence = evidence,
            questionLabel = questionLabel,
            usedDownloadedModel = usedDownloadedModel,
            fromCache = draft.fromCache,
            qualityPassed = review.passed,
            qualityMessage = review.message,
            qualityScore = review.score,
            qualityChecks = review.checks,
            revisionCount = revisionCount,
            sourceName = draft.sourceName
        )
    }

    private fun queryOpenFda(drug: String, kind: EducationQuestionKind): JSONObject {
        val term = URLEncoder.encode("\"${drug.replace("\"", "").trim()}\"", StandardCharsets.UTF_8.name())
        val searches = if (drug.matches(Regex("[0-9-]+"))) {
            listOf("openfda.product_ndc:$term")
        } else {
            listOf(
                "openfda.generic_name:$term",
                "openfda.brand_name:$term",
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
                    if (
                        recordIdentityScore(record, drug) >= 70 &&
                        MedicationEducationLogic.fieldCandidates(kind).any { jsonText(record, it).isNotBlank() }
                    ) {
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
            connection.setRequestProperty("User-Agent", "SmartMedicineBox-Android/2.1.8")
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

    private fun arrayTexts(record: JSONObject?, field: String): List<String> {
        val values = record?.optJSONArray(field) ?: return emptyList()
        return (0 until values.length()).mapNotNull {
            values.optString(it).takeIf(String::isNotBlank)
        }
    }

    private fun recordIdentityScore(record: JSONObject, drug: String): Int {
        val openFda = record.optJSONObject("openfda")
        val candidates = buildList {
            addAll(arrayTexts(openFda, "brand_name"))
            addAll(arrayTexts(openFda, "generic_name"))
            addAll(arrayTexts(openFda, "substance_name"))
            addAll(arrayTexts(openFda, "product_ndc"))
        }
        return MedicationEducationLogic.identityScore(drug, candidates)
    }

    private fun plainExcerpt(text: String, maxChars: Int = 900): String {
        val plain = HtmlCompat.fromHtml(text, HtmlCompat.FROM_HTML_MODE_LEGACY)
            .toString()
            .let(MedicationEducationLogic::cleanSourceText)
        if (plain.length <= maxChars) return plain
        val clipped = plain.take(maxChars)
        val stop = listOf(clipped.lastIndexOf(". "), clipped.lastIndexOf("; "))
            .maxOrNull()
            ?.takeIf { it >= maxChars / 2 }
        val shortened = if (stop != null) clipped.take(stop + 1) else clipped
        return shortened.trimEnd() + "…"
    }

    override fun close() {
        miniCpm.close()
        translator.close()
    }
}
