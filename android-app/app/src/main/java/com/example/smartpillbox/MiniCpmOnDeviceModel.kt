package com.example.smartpillbox

import android.content.Context
import android.net.ConnectivityManager
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
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URI
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
        if (modelFile.isFile && modelFile.length() >= MIN_MODEL_BYTES) return
        val connectivity = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (connectivity.isActiveNetworkMetered) {
            error("首次使用需下載約 1.55 GB 的 MiniCPM5-2B，請先連接 Wi-Fi 再試。")
        }

        val partial = File(modelDir, "$MODEL_FILE.part")
        val existing = partial.takeIf(File::isFile)?.length() ?: 0L
        val connection = URI(MODEL_URL).toURL().openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 20_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("User-Agent", "SmartMedicineBox-Android/2.1.8")
            if (existing > 0L) connection.setRequestProperty("Range", "bytes=$existing-")
            connection.connect()
            val append = existing > 0L && connection.responseCode == HttpURLConnection.HTTP_PARTIAL
            if (connection.responseCode !in 200..299) {
                error("MiniCPM5-2B 下載失敗（HTTP ${connection.responseCode}）。")
            }
            val start = if (append) existing else 0L
            val total = contentRangeTotal(connection).takeIf { it > 0L }
                ?: (start + connection.contentLengthLong).takeIf { it > 0L }
                ?: EXPECTED_MODEL_BYTES
            var written = start
            var lastPercent = -1
            connection.inputStream.buffered().use { input ->
                FileOutputStream(partial, append).buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE * 8)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        written += count
                        val percent = ((written * 100L) / total).toInt().coerceIn(0, 100)
                        if (percent >= lastPercent + 5) {
                            lastPercent = percent
                            mainHandler.post { onProgress("正在下載 MiniCPM5-2B：$percent%") }
                        }
                    }
                }
            }
            if (partial.length() < MIN_MODEL_BYTES) error("模型下載不完整，請重新連線後再試。")
            if (modelFile.exists()) modelFile.delete()
            if (!partial.renameTo(modelFile)) error("模型儲存失敗，請確認手機空間足夠。")
        } finally {
            connection.disconnect()
        }
    }

    private fun contentRangeTotal(connection: HttpURLConnection): Long {
        return connection.getHeaderField("Content-Range")
            ?.substringAfterLast('/')
            ?.toLongOrNull()
            ?: 0L
    }

    override fun close() {
        runCatching { engine?.close() }
        engine = null
        executor.shutdownNow()
    }

    private companion object {
        const val MODEL_FILE = "MiniCPM5-2B_int4.litertlm"
        const val MODEL_URL =
            "https://huggingface.co/litert-community/MiniCPM5-2B/resolve/main/MiniCPM5-2B_int4.litertlm?download=true"
        const val MIN_MODEL_BYTES = 1_400_000_000L
        const val EXPECTED_MODEL_BYTES = 1_550_000_000L
    }
}
