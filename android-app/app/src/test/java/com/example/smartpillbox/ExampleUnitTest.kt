package com.example.smartpillbox

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExampleUnitTest {
    @Test
    fun defaultApiUrlIsNormalizedForVersionSixBackend() {
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

        val blocked = MedicationEducationLogic.reviewAnswer(
            EducationQuestionKind.INTERACTIONS,
            "adverse_reactions",
            "Nausea",
            "Nausea"
        )
        assertFalse(blocked.passed)
    }
}

