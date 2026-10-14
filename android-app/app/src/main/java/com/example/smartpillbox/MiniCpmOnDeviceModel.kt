package com.example.smartpillbox

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.ai.edge.litertlm.ThinkingConfig
import java.io.Closeable
import java.io.File
import java.util.concurrent.Executors

internal class MiniCpmOnDeviceModel(context: Context) : Closeable {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private val modelDir = appContext.getExternalFilesDir("models")
        ?: File(appContext.filesDir, "models")
    private val modelFile = File(modelDir, MODEL_FILE)
    private var engine: Engine? = null

    fun rewriteForSenior(
        draft: MedicationEducationDraft,
        onPreparing: () -> Unit,
        onProgress: (String) -> Unit,
        onSuccess: (String) -> Unit,
        onFailure: (String) -> Unit
    ) {
        onPreparing()
        executor.execute {
            try {
                ensureModel(onProgress)
                val prompt = buildString {
                    append("藥名：${draft.displayDrug}\n")
                    append("問題：${draft.question}\n")
                    append("可使用的資料：${draft.sourceText}\n\n")
                    append("請直接回答使用者的問題，用台灣長輩聽得懂的二至四個自然短句。")
                    append("刪除章節號、條文編號與重複標題，不要說明資料處理、檢查分數或資料筆數。")
                    append("只能使用提供的資料，不得新增用途、疾病、劑量、交互作用、停藥或治療建議。")
                    append("禁止出現廣告、促銷、新聞、電信、購物、模型自述或任何與藥物無關的句子。")
                    append("正確例子：資料寫『用於控制高血壓』，回答『這顆藥常用來控制高血壓。』")
                }
                val response = localEngine().createConversation(
                    ConversationConfig(
                        systemInstruction = Contents.of(
                            "你是智慧藥盒裡耐心的台灣藥師助理。說話自然、溫和、清楚；忠實整理來源，不猜測，不提供醫療處置。"
                        ),
                        samplerConfig = SamplerConfig(
                            topK = 8,
                            topP = 0.8,
                            temperature = 0.05,
                            seed = 7
                        ),
                        maxOutputToken = 280,
                        thinkingConfig = ThinkingConfig(enableThinking = false)
                    )
                ).use { conversation ->
                    conversation.sendMessage(
                        prompt,
                        maxOutputToken = 280,
                        thinkingConfig = ThinkingConfig(enableThinking = false)
                    ).toString().trim()
                }
                if (response.isBlank()) error("MiniCPM5-2B 沒有產生回答。")
                val cleanedResponse = MedicationEducationLogic.simplifyChinese(response)
                if (!MedicationEducationLogic.isGeneratedAnswerSafe(
                        draft.kind,
                        draft.sourceText,
                        cleanedResponse
                    )
                ) error("AI 回答含有無來源內容，已改用安全回答。")

                val verdictPrompt = buildString {
                    append("問題：${draft.question}\n")
                    append("來源：${draft.sourceText}\n")
                    append("待檢查回答：$cleanedResponse\n\n")
                    append("若每一句都能由來源支持、沒有新增疾病或用藥建議，只輸出『通過』；否則只輸出『拒絕』。")
                }
                val verdict = localEngine().createConversation(
                    ConversationConfig(
                        systemInstruction = Contents.of("你是嚴格的藥物回答核對員，不推測、不補充。"),
                        samplerConfig = SamplerConfig(
                            topK = 4,
                            topP = 0.6,
                            temperature = 0.05,
                            seed = 11
                        ),
                        maxOutputToken = 16,
                        thinkingConfig = ThinkingConfig(enableThinking = false)
                    )
                ).use { conversation ->
                    conversation.sendMessage(
                        verdictPrompt,
                        maxOutputToken = 16,
                        thinkingConfig = ThinkingConfig(enableThinking = false)
                    ).toString().trim()
                }
                if (!verdict.startsWith("通過") || verdict.contains("拒絕") || verdict.contains("不通過")) {
                    error("AI 回答未通過來源核對，已改用安全回答。")
                }
                mainHandler.post { onSuccess(cleanedResponse) }
            } catch (error: Exception) {
                val message = error.message ?: "MiniCPM5-2B 暫時無法使用。"
                mainHandler.post { onFailure(message) }
            }
        }
    }

    /**
     * This is called from AgentReminderReceiver's background thread. It deliberately
     * stays synchronous so the notification is shown only after the final text has
     * passed the local safety checks.
     */
    fun generateMedicationReminder(
        userName: String,
        medicineName: String,
        doseCount: String,
        scheduledTime: String,
        reminderHint: String,
        stage: String,
        minutesLate: Int
    ): String {
        ensureModel { }
        val situation = when (stage) {
            "followup" -> "已超過原訂時間 $minutesLate 分鐘，仍未確認服藥"
            "missed" -> "已超過原訂時間 $minutesLate 分鐘，可能漏服，需要家人或照護者協助確認"
            else -> "現在已到原訂服藥時間 $scheduledTime"
        }
        val hint = reminderHint.trim().takeIf { it.isNotBlank() }
        val prompt = buildString {
            append("姓名：$userName\n")
            append("藥物：$medicineName\n")
            append("劑量：$doseCount\n")
            append("情況：$situation\n")
            if (hint != null) append("原有提醒：$hint\n")
            append("\n請只輸出通知正文，用一至兩句自然、溫和的繁體中文提醒。")
            append("內容必須提到姓名、藥物與劑量，依目前情況提醒本人或照護者確認。")
            append("不要加標題、條列、AI 自述、診斷，也不得建議停藥、補吃、加量、減量或改藥。")
        }
        val response = localEngine().createConversation(
            ConversationConfig(
                systemInstruction = Contents.of(
                    "你是智慧藥盒的台灣照護提醒助理。語氣自然、有禮且簡短，只根據提供的服藥任務提醒，不做醫療決定。"
                ),
                samplerConfig = SamplerConfig(
                    topK = 12,
                    topP = 0.85,
                    temperature = 0.35,
                    seed = reminderSeed(userName, medicineName, stage)
                ),
                maxOutputToken = 96,
                thinkingConfig = ThinkingConfig(enableThinking = false)
            )
        ).use { conversation ->
            conversation.sendMessage(
                prompt,
                maxOutputToken = 96,
                thinkingConfig = ThinkingConfig(enableThinking = false)
            ).toString()
        }
        val cleaned = response
            .replace(Regex("^(通知正文|提醒內容|回答)[:：]\\s*"), "")
            .replace(Regex("[\\r\\n]+"), " ")
            .replace(Regex("\\s{2,}"), " ")
            .trim(' ', '"', '\'', '「', '」')
        if (!isReminderSafe(cleaned, userName, medicineName, doseCount)) {
            error("訓練模型提醒未通過安全檢查，已改用安全提醒。")
        }
        return cleaned
    }

    @Synchronized
    private fun localEngine(): Engine {
        engine?.let { return it }
        val gpu = runCatching { createEngine(Backend.GPU()) }.getOrNull()
        if (gpu != null) {
            engine = gpu
            return gpu
        }
        return createEngine(Backend.CPU()).also { engine = it }
    }

    private fun createEngine(backend: Backend): Engine {
        val candidate = Engine(
            EngineConfig(
                modelPath = modelFile.absolutePath,
                backend = backend,
                maxNumTokens = 4096,
                cacheDir = File(modelDir, "cache").apply { mkdirs() }.absolutePath
            )
        )
        return try {
            candidate.initialize()
            candidate
        } catch (error: Exception) {
            candidate.close()
            throw error
        }
    }

    private fun ensureModel(onProgress: (String) -> Unit) {
        modelDir.mkdirs()
        if (modelFile.isFile && modelFile.length() == EXPECTED_MODEL_BYTES) {
            mainHandler.post { onProgress("已載入智慧藥盒訓練模型") }
            return
        }
        if (modelFile.exists()) modelFile.delete()
        error("找不到智慧藥盒訓練模型，請用 USB 執行 install_trained_model.ps1。")
    }

    private fun isReminderSafe(
        text: String,
        userName: String,
        medicineName: String,
        doseCount: String
    ): Boolean {
        if (text.isBlank() || text.length > 180) return false
        if (!text.contains(userName) || !text.contains(medicineName)) return false
        val doseToken = doseCount.trim().split(Regex("\\s+")).firstOrNull().orEmpty()
        if (doseToken.isNotBlank() && !text.contains(doseToken)) return false
        val prohibited = listOf(
            "自行停藥", "停藥", "加倍", "加量", "減量", "改藥", "補吃",
            "保證", "一定有效", "診斷為", "廣告", "促銷", "我是 AI", "作為 AI"
        )
        return prohibited.none(text::contains)
    }

    private fun reminderSeed(userName: String, medicineName: String, stage: String): Int {
        return ("$userName|$medicineName|$stage".hashCode() and Int.MAX_VALUE).coerceAtLeast(1)
    }

    override fun close() {
        runCatching { engine?.close() }
        engine = null
        executor.shutdownNow()
    }

    private companion object {
        const val MODEL_FILE = "MiniCPM5-2B_smartpill_trained_int8.litertlm"
        const val EXPECTED_MODEL_BYTES = 2_546_936_640L
    }
}
