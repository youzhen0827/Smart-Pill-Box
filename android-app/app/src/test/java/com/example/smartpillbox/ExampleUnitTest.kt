package com.example.smartpillbox

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExampleUnitTest {
    @Test
    fun defaultApiUrlIsNormalizedForVersionSevenBackend() {
        assertEquals(
            "http://10.0.2.2:8000/api/v1/",
            ApiClient.normalizeApiBase("10.0.2.2:8000/api/v1")
        )
        assertEquals(
            "http://10.0.2.2:8000/",
            ApiClient("10.0.2.2:8000/api/v1", "").webRoot()
        )
    }

    @Test
    fun pillboxKeepsExactlyThreeReadableSlots() {
        assertEquals(listOf("早", "中", "晚"), (1..SlotLabels.SLOT_COUNT).map(SlotLabels::label))
    }

    @Test
    fun voiceEducationRoutesQuestionsWithoutDjango() {
        assertEquals(
            EducationQuestionKind.INDICATIONS,
            MedicationEducationLogic.detectQuestion("為什麼要吃這顆藥？")
        )
        assertEquals(
            EducationQuestionKind.ADVERSE_REACTIONS,
            MedicationEducationLogic.detectQuestion("可能有哪些副作用？")
        )
        assertEquals(
            EducationQuestionKind.DOSAGE,
            MedicationEducationLogic.detectQuestion("這顆藥要怎麼吃？")
        )
    }

    @Test
    fun commonFdaPurposeCanBeTranslatedOnDeviceWithoutServer() {
        val translated = MedicationEducationLogic.offlineTranslation(
            "Treatment of Type 2 diabetes mellitus"
        ).orEmpty()
        assertEquals("用於治療第 2 型糖尿病", translated)
        assertFalse(translated.contains("Treatment"))
    }

    @Test
    fun machineTranslationIsNormalizedForTaiwanReaders() {
        val translated = MedicationEducationLogic.simplifyChinese(
            "INDICATIONS & USAGE Metformin 盐酸延伸释放片,USP" +
                "被指为饮食的辅料和锻炼,以改善2型糖尿病病人的甘油控制."
        )
        assertFalse(translated.contains("盐酸"))
        assertFalse(translated.contains("INDICATIONS"))
        assertFalse(translated.contains("甘油控制"))
        assertTrue(translated.contains("鹽酸緩釋錠"))
        assertTrue(translated.contains("第 2 型糖尿病"))
        assertTrue(translated.contains("血糖控制"))
    }

    @Test
    fun voiceEducationKeepsOnlyTwoShortSentences() {
        val answer = MedicationEducationLogic.conciseAnswer(
            "第一句重點。第二句重點。第三句不應顯示。"
        )
        assertTrue(answer.contains("第一句重點"))
        assertTrue(answer.contains("第二句重點"))
        assertFalse(answer.contains("第三句不應顯示"))
    }

    @Test
    fun agentChecksThatAnswerMatchesQuestionAndIsChinese() {
        val passed = MedicationEducationLogic.reviewAnswer(
            EducationQuestionKind.INDICATIONS,
            "indications_and_usage",
            "Treatment of Type 2 diabetes mellitus",
            "用於治療第 2 型糖尿病"
        )
        assertTrue(passed.passed)
        assertEquals(100, passed.score)

        val blocked = MedicationEducationLogic.reviewAnswer(
            EducationQuestionKind.INTERACTIONS,
            "adverse_reactions",
            "Nausea",
            "Nausea"
        )
        assertFalse(blocked.passed)
    }

    @Test
    fun tfdaIdentityMatcherRejectsAnotherDrug() {
        val record = TfdaDrugRecord(
            permitNumber = "衛部藥製字第000001號",
            chineseName = "安心降壓錠",
            englishName = "SAFEPRESS TABLETS",
            indications = "高血壓。",
            dosage = "依醫師指示使用。",
            ingredients = "AMLODIPINE"
        )
        assertEquals(100, TfdaDrugMatcher.identityScore("安心降壓錠", record))
        assertEquals(80, TfdaDrugMatcher.identityScore("amlodipine", record))
        assertEquals(0, TfdaDrugMatcher.identityScore("metformin", record))
    }

    @Test
    fun agentScoreDropsWhenDrugIdentityDoesNotMatch() {
        val review = MedicationEducationLogic.reviewAnswer(
            EducationQuestionKind.INDICATIONS,
            "indications_and_usage",
            "Treatment of high blood pressure",
            "用於治療高血壓",
            identityScore = 0
        )
        assertFalse(review.passed)
        assertTrue(review.score < 100)
    }

    @Test
    fun generatedAnswerRejectsAdvertisingHallucination() {
        val source = "這顆藥用來幫助控制血糖。"
        val hallucinated = "這是幾句大哥大廣告的簡述。這顆藥用來幫助控制血糖。"
        assertFalse(
            MedicationEducationLogic.isGeneratedAnswerSafe(
                EducationQuestionKind.INDICATIONS,
                source,
                hallucinated
            )
        )
        assertTrue(
            MedicationEducationLogic.isGeneratedAnswerSafe(
                EducationQuestionKind.INDICATIONS,
                source,
                "這顆藥用來幫助控制血糖。"
            )
        )
    }

    @Test
    fun sourceCleanerRemovesAdvertisingSentence() {
        val cleaned = MedicationEducationLogic.cleanSourceText(
            "這顆藥用於控制血糖。大哥大廣告限時優惠。"
        )
        assertTrue(cleaned.contains("控制血糖"))
        assertFalse(cleaned.contains("廣告"))
    }

}

