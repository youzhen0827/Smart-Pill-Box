package com.example.smartpillbox

import android.os.Build

internal enum class EducationQuestionKind {
    INDICATIONS,
    ADVERSE_REACTIONS,
    DOSAGE,
    INTERACTIONS,
    WARNINGS,
    MISSED_DOSE,
    GENERAL
}

internal object MedicationEducationLogic {
    private val englishWord = Regex("\\b[A-Za-z]{3,}\\b")

    private val offlineTerms = linkedMapOf(
        "Treatment of Type 2 diabetes mellitus" to "用於治療第 2 型糖尿病",
        "Treatment of Type 1 diabetes mellitus" to "用於治療第 1 型糖尿病",
        "Type 2 diabetes mellitus" to "第 2 型糖尿病",
        "Type 1 diabetes mellitus" to "第 1 型糖尿病",
        "Gastroesophageal reflux disease" to "胃食道逆流",
        "high blood pressure" to "高血壓",
        "hypertension" to "高血壓",
        "heart failure" to "心臟衰竭",
        "bacterial infections" to "細菌感染",
        "fungal infections" to "黴菌感染",
        "allergic rhinitis" to "過敏性鼻炎",
        "nausea and vomiting" to "噁心和嘔吐",
        "adverse reactions" to "副作用",
        "stomach pain" to "胃痛",
        "abdominal pain" to "腹痛",
        "loss of appetite" to "食慾下降",
        "allergic reaction" to "過敏反應",
        "dryness in mouth" to "口乾",
        "blurred vision" to "視力模糊",
        "joint pain" to "關節痛",
        "muscle pain" to "肌肉痛",
        "skin rash" to "皮疹",
        "pain relief" to "緩解疼痛",
        "indigestion" to "消化不良",
        "constipation" to "便祕",
        "diarrhea" to "腹瀉",
        "vomiting" to "嘔吐",
        "nausea" to "噁心",
        "dizziness" to "頭暈",
        "headache" to "頭痛",
        "sleepiness" to "想睡",
        "drowsiness" to "嗜睡",
        "tiredness" to "疲倦",
        "fatigue" to "疲倦",
        "weakness" to "無力",
        "flatulence" to "脹氣",
        "heartburn" to "胃灼熱",
        "itching" to "發癢",
        "rash" to "皮疹",
        "cough" to "咳嗽",
        "fever" to "發燒",
        "Treatment of" to "用於治療",
        "Used to treat" to "用於治療",
        "Prevention of" to "用於預防",
        "Relief of" to "用於緩解"
    )

    fun detectQuestion(question: String): EducationQuestionKind {
        val value = question.lowercase()
        return when {
            listOf("忘記", "漏吃", "漏服", "missed").any(value::contains) -> EducationQuestionKind.MISSED_DOSE
            listOf("一起吃", "其他藥", "交互", "相互作用", "interaction").any(value::contains) -> EducationQuestionKind.INTERACTIONS
            listOf("副作用", "不舒服", "不良反應", "adverse", "side effect").any(value::contains) -> EducationQuestionKind.ADVERSE_REACTIONS
            listOf("怎麼吃", "如何吃", "劑量", "服用", "飯前", "飯後", "dosage", "dose").any(value::contains) -> EducationQuestionKind.DOSAGE
            listOf("注意", "警告", "不能吃", "禁忌", "危險", "warning").any(value::contains) -> EducationQuestionKind.WARNINGS
            listOf("為什麼", "做什麼", "用途", "功效", "治療", "indication", "used for").any(value::contains) -> EducationQuestionKind.INDICATIONS
            else -> EducationQuestionKind.GENERAL
        }
    }

    fun label(kind: EducationQuestionKind): String = when (kind) {
        EducationQuestionKind.INDICATIONS -> "藥物用途"
        EducationQuestionKind.ADVERSE_REACTIONS -> "可能的副作用"
        EducationQuestionKind.DOSAGE -> "服用方法與劑量"
        EducationQuestionKind.INTERACTIONS -> "和其他藥一起使用"
        EducationQuestionKind.WARNINGS -> "注意事項與警告"
        EducationQuestionKind.MISSED_DOSE -> "忘記服藥"
        EducationQuestionKind.GENERAL -> "藥物基本資訊"
    }

    fun fieldCandidates(kind: EducationQuestionKind): List<String> = when (kind) {
        EducationQuestionKind.INDICATIONS -> listOf("indications_and_usage", "purpose")
        EducationQuestionKind.ADVERSE_REACTIONS -> listOf("adverse_reactions")
        EducationQuestionKind.DOSAGE -> listOf("dosage_and_administration")
        EducationQuestionKind.INTERACTIONS -> listOf("drug_interactions")
        EducationQuestionKind.WARNINGS -> listOf("warnings_and_cautions", "warnings", "boxed_warning", "do_not_use")
        EducationQuestionKind.MISSED_DOSE -> listOf("dosage_and_administration", "information_for_patients")
        EducationQuestionKind.GENERAL -> listOf("indications_and_usage", "purpose", "description")
    }

    fun sectionLabel(field: String): String = when (field) {
        "indications_and_usage", "purpose" -> "適應症與功效"
        "adverse_reactions" -> "可能的副作用"
        "dosage_and_administration" -> "服用方法與劑量"
        "drug_interactions" -> "藥物交互作用"
        "warnings_and_cautions", "warnings", "boxed_warning", "do_not_use" -> "注意事項與警告"
        "information_for_patients" -> "病人用藥資訊"
        else -> "藥物基本資訊"
    }

    fun prefix(kind: EducationQuestionKind): String = when (kind) {
        EducationQuestionKind.INDICATIONS -> "為什麼要吃／可能用來治療："
        EducationQuestionKind.ADVERSE_REACTIONS -> "標籤列出的副作用重點（非完整清單）："
        EducationQuestionKind.DOSAGE -> "FDA 建議用法重點："
        EducationQuestionKind.INTERACTIONS -> "已知藥物交互作用重點："
        EducationQuestionKind.WARNINGS -> "需要特別注意："
        EducationQuestionKind.MISSED_DOSE -> "FDA 標籤中的服藥說明："
        EducationQuestionKind.GENERAL -> "藥物資料："
    }

    fun nextStep(kind: EducationQuestionKind): String = when (kind) {
        EducationQuestionKind.INDICATIONS -> "這是常見用途，不一定是你本人吃藥的原因。請以藥袋或醫師說明為準。"
        EducationQuestionKind.ADVERSE_REACTIONS -> "若出現不舒服，請記下症狀與時間並詢問醫師或藥師；若呼吸困難或臉、喉嚨腫脹，請立即就醫。"
        EducationQuestionKind.DOSAGE -> "實際吃法以藥袋與處方為準，不要自行增減劑量。"
        EducationQuestionKind.INTERACTIONS -> "要和其他藥一起吃前，請將西藥、中藥與保健食品清單交給藥師確認。"
        EducationQuestionKind.WARNINGS -> "若你符合警告中的情況，先詢問醫師或藥師，不要自行停藥。"
        EducationQuestionKind.MISSED_DOSE -> "請查看藥袋或詢問藥師，不要自行補吃兩次的份量。"
        EducationQuestionKind.GENERAL -> "請先確認藥袋上的藥名和查詢名稱相同。"
    }

    fun offlineTranslation(text: String): String? {
        var result = text
        offlineTerms.entries.sortedByDescending { it.key.length }.forEach { (source, target) ->
            result = result.replace(source, target, ignoreCase = true)
        }
        result = simplifyChinese(result)
        return result.takeIf { !englishWord.containsMatchIn(it) }
    }

    fun simplifyChinese(text: String): String {
        var result = text.replace(Regex("\\s+"), " ").trim()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            result = runCatching {
                android.icu.text.Transliterator
                    .getInstance("Simplified-Traditional")
                    .transliterate(result)
            }.getOrDefault(result)
        }
        result = result.replace(
            Regex("\\bINDICATIONS?\\s*&\\s*USAGE\\b[:：]?\\s*", RegexOption.IGNORE_CASE),
            ""
        )
        val replacements = linkedMapOf(
            "饮食的辅料和锻炼" to "搭配飲食控制和運動",
            "飲食的輔料和鍛鍊" to "搭配飲食控制和運動",
            "飲食的輔料和鍛煉" to "搭配飲食控制和運動",
            "盐酸" to "鹽酸",
            "延伸释放片" to "緩釋錠",
            "延伸釋放片" to "緩釋錠",
            "延长释放片" to "緩釋錠",
            "延長釋放片" to "緩釋錠",
            "被指为" to "用於",
            "被指為" to "用於",
            "甘油控制" to "血糖控制",
            "2型糖尿病" to "第 2 型糖尿病",
            "不良反應" to "副作用",
            "不良反应" to "副作用",
            "患者" to "病人",
            "服用本品" to "吃這個藥",
            "本品" to "這個藥",
            "给药" to "用藥",
            "药物" to "藥物",
            "治疗" to "治療",
            "剂量" to "劑量",
            "医师" to "醫師",
            "处方" to "處方",
            "严重" to "嚴重",
            "过敏" to "過敏",
            "与" to "與",
            "发生" to "發生",
            "出现" to "出現",
            "这种" to "這種",
            "导致" to "造成",
            "以及" to "和"
        )
        replacements.forEach { (source, target) -> result = result.replace(source, target) }
        return result
    }

    fun translationChunks(text: String, maxChars: Int = 420): List<String> {
        val sentences = text.split(Regex("(?<=[.!?;])\\s+|\\n+"))
        val chunks = mutableListOf<String>()
        var current = ""
        sentences.filter { it.isNotBlank() }.forEach { original ->
            var sentence = original.trim()
            while (sentence.length > maxChars) {
                val candidate = sentence.lastIndexOf(' ', maxChars).takeIf { it >= maxChars / 2 } ?: maxChars
                if (current.isNotBlank()) {
                    chunks += current
                    current = ""
                }
                chunks += sentence.substring(0, candidate).trim()
                sentence = sentence.substring(candidate).trim()
            }
            val combined = "$current $sentence".trim()
            if (current.isNotBlank() && combined.length > maxChars) {
                chunks += current
                current = sentence
            } else {
                current = combined
            }
        }
        if (current.isNotBlank()) chunks += current
        return chunks
    }

    fun conciseAnswer(text: String, maxChars: Int = 320, maxSentences: Int = 2): String {
        val cleaned = simplifyChinese(text).replace(
            Regex(
                "^(?:DRUG INTERACTIONS|ADVERSE REACTIONS|DOSAGE AND ADMINISTRATION|" +
                    "藥物交互作用|副作用(?:／不良反應)?|服用方法與劑量)\\s*[:：-]*\\s*",
                RegexOption.IGNORE_CASE
            ),
            ""
        )
        val sentences = cleaned
            .split(Regex("(?<=[。！？!?;；])\\s*|(?<=\\.)\\s+"))
            .map(String::trim)
            .filter(String::isNotBlank)
        val selected = mutableListOf<String>()
        for (sentence in sentences) {
            val candidate = (selected + sentence).joinToString(" ")
            if (selected.isNotEmpty() && candidate.length > maxChars) break
            selected += sentence
            if (selected.size >= maxSentences || candidate.length >= maxChars) break
        }
        var focused = selected.joinToString(" ").ifBlank { cleaned }
        if (focused.length > maxChars) focused = focused.take(maxChars).trimEnd()
        if (focused.length < cleaned.length && !focused.endsWith("…")) focused += "…"
        return focused
    }
}
