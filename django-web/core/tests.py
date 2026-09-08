from __future__ import annotations

import io
import json
import re
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AgentIntervention,
    DatasetSyncRun,
    Drug,
    DrugKnowledgeDocument,
    Elder,
    MedicationLog,
    MedicationSchedule,
    Reminder,
    SensorEvent,
    UserProfile,
)
from core.services.dataset_service import import_kaggle_csv, sync_openfda
from core.services.medication_agent import run_agent_cycle
from core.services.qa_agent import (
    _focused_excerpt,
    _simplify_chinese,
    _translate_with_automatic_service,
    answer_medication_question,
)
from core.services.rag_service import infer_question_types


User = get_user_model()
TOKEN = "test-device-token"


class ApiTestMixin:
    def api_post(self, name: str, payload: dict, *args):
        return self.client.post(
            reverse(name, args=args),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_DEVICE_TOKEN=TOKEN,
        )


@override_settings(DEVICE_API_TOKEN=TOKEN)
class ReminderApiTests(ApiTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="caregiver", password="pass-12345")
        UserProfile.objects.create(user=self.user, android_name="王阿公、爸爸")

    def test_token_is_required(self):
        response = self.client.get(reverse("api_reminders"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_device_token")

    def test_android_create_list_take_and_delete(self):
        payload = {
            "user_name": "王阿公",
            "user_age": "72",
            "medicine_name": "metformin",
            "scheduled_datetime": "2026-07-10T18:30:00",
            "scheduled_time": "06:30 PM",
            "dose_count": "1",
            "reminder_hint": "飯後服用",
            "slot": 2,
            "device_id": "pillbox-01",
        }
        created = self.api_post("api_reminders", payload)
        self.assertEqual(created.status_code, 201)
        record_id = created.json()["id"]

        reminder = Reminder.objects.get(pk=record_id)
        self.assertEqual(reminder.owner, self.user)
        self.assertEqual(reminder.source, "android")
        self.assertEqual(reminder.slot, 2)

        listed = self.client.get(
            reverse("api_reminders"),
            {"user_name": "王阿公", "date": "2026-07-10"},
            HTTP_X_DEVICE_TOKEN=TOKEN,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["results"]), 1)
        self.assertEqual(listed.json()["results"][0]["slot_label"], "中")

        taken = self.api_post("api_reminder_taken", {}, record_id)
        self.assertEqual(taken.status_code, 200)
        self.assertEqual(taken.json()["status"], "已服藥")
        self.assertEqual(taken.json()["confirmation_source"], "android")

        deleted = self.api_post("api_reminder_delete", {}, record_id)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(Reminder.objects.filter(pk=record_id).exists())

    def test_invalid_slot_is_rejected(self):
        response = self.api_post(
            "api_reminders",
            {
                "user_name": "王阿公",
                "medicine_name": "metformin",
                "scheduled_datetime": "2026-07-10T18:30:00",
                "slot": 4,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("早=1、中=2、晚=3", response.json()["error"])

    def test_sensor_open_event_marks_nearest_task_taken(self):
        detected_at = timezone.make_aware(datetime(2026, 7, 10, 18, 31))
        reminder = Reminder.objects.create(
            owner=self.user,
            user_name="王阿公",
            medicine_name="metformin",
            scheduled_time="06:30 PM",
            scheduled_datetime=detected_at - timedelta(minutes=1),
            dose_count="1",
            slot=3,
            device_id="pillbox-01",
            status="已提醒",
        )
        response = self.api_post(
            "api_sensor_event",
            {
                "device_id": "pillbox-01",
                "user_name": "王阿公",
                "slot": 3,
                "event_type": "opened",
                "detected_at": detected_at.isoformat(),
                "source": "test_fixture_only",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["matched_reminder"]["id"], reminder.id)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "已服藥")
        self.assertEqual(reminder.confirmation_source, "sensor")
        event = SensorEvent.objects.get(pk=response.json()["event_id"])
        self.assertEqual(event.matched_reminder, reminder)


class MedicationAgentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="agent-owner", password="pass-12345")
        self.elder = Elder.objects.create(owner=self.user, name="王阿公", age=72)
        self.drug = Drug.objects.create(name_zh="測試排程藥物", generic_name="fixture-only")

    def make_schedule(self, *, scheduled_time: time, grace=10, missed=60):
        return MedicationSchedule.objects.create(
            elder=self.elder,
            drug=self.drug,
            slot=1,
            scheduled_time=scheduled_time,
            dose_count="1",
            grace_minutes=grace,
            missed_after_minutes=missed,
            device_id="pillbox-01",
        )

    def test_agent_intervenes_when_sensor_has_not_opened(self):
        now = timezone.make_aware(datetime(2026, 7, 10, 10, 20))
        schedule = self.make_schedule(scheduled_time=time(10, 0))

        result = run_agent_cycle(now)
        reminder = Reminder.objects.get(schedule=schedule)
        self.assertEqual(reminder.agent_state, "intervened")
        self.assertEqual(reminder.status, "已提醒")
        self.assertEqual(reminder.reminder_count, 2)
        self.assertEqual(result.interventions_created, 2)
        self.assertEqual(
            set(reminder.interventions.values_list("intervention_type", flat=True)),
            {"initial_reminder", "sensor_missing"},
        )

        # 狀態機重跑不能重複建立同類介入。
        second = run_agent_cycle(now + timedelta(seconds=30))
        reminder.refresh_from_db()
        self.assertEqual(second.interventions_created, 0)
        self.assertEqual(reminder.reminder_count, 2)

    def test_agent_marks_missed_after_threshold(self):
        now = timezone.make_aware(datetime(2026, 7, 10, 11, 10))
        schedule = self.make_schedule(scheduled_time=time(10, 0), grace=10, missed=60)

        result = run_agent_cycle(now)
        reminder = Reminder.objects.get(schedule=schedule)
        log = MedicationLog.objects.get(reminder=reminder)
        self.assertEqual(reminder.status, "漏服")
        self.assertEqual(reminder.agent_state, "missed")
        self.assertEqual(log.status, "missed")
        self.assertEqual(result.missed_marked, 1)
        self.assertTrue(
            AgentIntervention.objects.filter(
                reminder=reminder, intervention_type="missed_escalation"
            ).exists()
        )

    def test_real_sensor_event_wins_before_agent_escalation(self):
        now = timezone.make_aware(datetime(2026, 7, 10, 10, 20))
        schedule = self.make_schedule(scheduled_time=time(10, 0))
        run_agent_cycle(timezone.make_aware(datetime(2026, 7, 10, 9, 55)))
        reminder = Reminder.objects.get(schedule=schedule)
        SensorEvent.objects.create(
            device_id="pillbox-01",
            user_name="王阿公",
            slot=1,
            event_type="opened",
            detected_at=timezone.make_aware(datetime(2026, 7, 10, 10, 2)),
            raw_payload={"source": "test_fixture_only"},
        )

        result = run_agent_cycle(now)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "已服藥")
        self.assertEqual(reminder.confirmation_source, "sensor")
        self.assertEqual(result.matched_sensor_events, 1)


class DatasetImportTests(TestCase):
    def test_numbered_side_effect_and_use_columns_are_supported(self):
        # 這是欄位解析測試資料，不會被載入正式資料庫或作為醫療內容。
        csv_bytes = (
            "name,sideEffect0,sideEffect1,use0,manufacturer\n"
            "fixture-drug-not-for-use,fixture-effect-a,fixture-effect-b,fixture-use,fixture-company\n"
        ).encode("utf-8")
        uploaded = SimpleUploadedFile("fixture.csv", csv_bytes, content_type="text/csv")
        result = import_kaggle_csv(
            uploaded,
            original_name="fixture.csv",
            dataset_url=(
                "https://www.kaggle.com/datasets/"
                "shudhanshusingh/250k-medicines-usage-side-effects-and-substitutes"
            ),
        )
        self.assertEqual(result.added, 1)
        document = DrugKnowledgeDocument.objects.get(source_type="kaggle_csv")
        self.assertIn("fixture-effect-a", document.adverse_reactions)
        self.assertIn("fixture-effect-b", document.adverse_reactions)
        self.assertEqual(document.indications, "fixture-use")
        self.assertEqual(document.raw_json["file"], "fixture.csv")
        self.assertEqual(document.raw_json["row"], 2)
        self.assertTrue(document.source_url.startswith("https://www.kaggle.com/datasets/"))

    def test_drug_pair_interaction_columns_are_supported(self):
        csv_bytes = (
            "Drug 1,Drug 2,Interaction\n"
            "fixture-a,fixture-b,fixture-interaction-text\n"
        ).encode("utf-8")
        uploaded = SimpleUploadedFile("ddi-fixture.csv", csv_bytes, content_type="text/csv")
        result = import_kaggle_csv(
            uploaded,
            original_name="ddi-fixture.csv",
            dataset_url="https://www.kaggle.com/datasets/mghobashy/drug-drug-interactions",
        )
        self.assertEqual(result.added, 1)
        document = DrugKnowledgeDocument.objects.get(source_type="kaggle_csv")
        self.assertEqual(document.generic_name, "fixture-a + fixture-b")
        self.assertIn("fixture-interaction-text", document.drug_interactions)

    @patch("core.services.dataset_service._query_endpoint")
    def test_openfda_sync_persists_source_provenance(self, query_endpoint):
        # 模擬 HTTP 邊界；只驗證正式程式會保存 openFDA 的 source URL、ID 與 raw JSON。
        def side_effect(url, term, limit):
            if url.endswith("ndc.json"):
                return [
                    {
                        "product_id": "fixture-product-id",
                        "product_ndc": "00000-000",
                        "brand_name": "fixture-brand-not-for-use",
                        "generic_name": "fixture-generic-not-for-use",
                        "labeler_name": "fixture-company",
                        "dosage_form": "TABLET",
                        "route": ["ORAL"],
                    }
                ]
            return [
                {
                    "id": "fixture-label-id",
                    "effective_time": "20260101",
                    "openfda": {
                        "product_ndc": ["00000-000"],
                        "brand_name": ["fixture-brand-not-for-use"],
                        "generic_name": ["fixture-generic-not-for-use"],
                        "manufacturer_name": ["fixture-company"],
                    },
                    "indications_and_usage": ["TEST FIXTURE ONLY"],
                    "adverse_reactions": ["TEST FIXTURE ONLY"],
                }
            ]

        query_endpoint.side_effect = side_effect
        result = sync_openfda("fixture-generic-not-for-use", limit=5)
        self.assertEqual(result.added, 2)
        self.assertEqual(DrugKnowledgeDocument.objects.count(), 2)
        self.assertEqual(DatasetSyncRun.objects.get().state, "success")
        for document in DrugKnowledgeDocument.objects.all():
            self.assertTrue(document.source_url.startswith("https://api.fda.gov/"))
            self.assertTrue(document.source_id)
            self.assertIsInstance(document.raw_json, dict)


@override_settings(LIBRETRANSLATE_URL="")
class QaAgentTests(TestCase):
    def test_answer_contains_only_retrieved_evidence_and_provenance(self):
        document = DrugKnowledgeDocument.objects.create(
            source_type="openfda_label",
            source_id="fixture-label-for-test",
            generic_name="fixture-generic-not-for-use",
            indications="TEST FIXTURE INDICATION TEXT",
            adverse_reactions="TEST FIXTURE ADVERSE TEXT",
            raw_json={"fixture": True},
            source_url="https://api.fda.gov/drug/label.json",
        )
        result = answer_medication_question(
            "fixture-generic-not-for-use",
            "what is this used for and what are the side effects?",
            language="en",
        )
        self.assertIn("TEST FIXTURE INDICATION TEXT", result.answer)
        self.assertIn("TEST FIXTURE ADVERSE TEXT", result.answer)
        self.assertEqual(result.evidence[0]["id"], document.id)
        self.assertEqual(result.evidence[0]["source_url"], document.source_url)

    def test_no_document_means_no_invented_medical_answer(self):
        result = answer_medication_question(
            "definitely-not-present",
            "有什麼副作用？",
            auto_sync=False,
        )
        self.assertEqual(result.evidence, [])
        self.assertIn("沒有足夠內容回答", result.answer)

    def test_answer_changes_with_question_type(self):
        DrugKnowledgeDocument.objects.create(
            source_type="openfda_label",
            source_id="fixture-question-routing",
            generic_name="fixture-routing-drug",
            indications="PURPOSE-ONLY-TEXT",
            adverse_reactions="SIDE-EFFECT-ONLY-TEXT",
            raw_json={"dosage_and_administration": ["DOSAGE-ONLY-TEXT"]},
            source_url="https://api.fda.gov/drug/label.json",
        )
        purpose = answer_medication_question(
            "fixture-routing-drug", "這顆藥是做什麼的？", language="en"
        )
        side_effect = answer_medication_question(
            "fixture-routing-drug", "這顆藥有哪些副作用？", language="en"
        )
        dosage = answer_medication_question(
            "fixture-routing-drug", "這顆藥要怎麼吃？", language="en"
        )
        self.assertIn("PURPOSE-ONLY-TEXT", purpose.answer)
        self.assertNotIn("SIDE-EFFECT-ONLY-TEXT", purpose.answer)
        self.assertIn("SIDE-EFFECT-ONLY-TEXT", side_effect.answer)
        self.assertNotIn("PURPOSE-ONLY-TEXT", side_effect.answer)
        self.assertIn("DOSAGE-ONLY-TEXT", dosage.answer)
        self.assertEqual(purpose.question_label, "藥物用途")
        self.assertEqual(side_effect.question_label, "可能的副作用")
        self.assertEqual(dosage.question_label, "服用方法與劑量")
        self.assertEqual(len(side_effect.evidence), 1)
        self.assertEqual(len(dosage.evidence), 1)

    def test_interaction_question_does_not_add_unrequested_dosage_answer(self):
        self.assertEqual(
            infer_question_types("這顆藥可以和其他藥一起服用嗎？"),
            ["drug_interactions"],
        )

    def test_answer_excerpt_keeps_only_two_short_sentences(self):
        text = "第一句重點。第二句重點。第三句不應顯示。"
        focused = _focused_excerpt(text)
        self.assertIn("第一句重點", focused)
        self.assertIn("第二句重點", focused)
        self.assertNotIn("第三句不應顯示", focused)

    @override_settings(AUTOMATIC_TRANSLATE_URL="")
    def test_common_english_indication_is_automatically_translated(self):
        DrugKnowledgeDocument.objects.create(
            source_type="openfda_label",
            source_id="fixture-chinese-translation",
            generic_name="fixture-translation-drug",
            indications="Treatment of Type 2 diabetes mellitus",
            source_url="https://api.fda.gov/drug/label.json",
        )
        result = answer_medication_question(
            "fixture-translation-drug", "為什麼要吃這個藥？", language="zh-TW"
        )
        self.assertIn("用於治療第 2 型糖尿病", result.answer)
        self.assertNotIn("Treatment of Type 2 diabetes mellitus", result.answer)
        self.assertTrue(result.translated)

    def test_machine_translation_is_normalized_to_taiwan_traditional_chinese(self):
        translated = _simplify_chinese(
            "INDICATIONS & USAGE Metformin 盐酸延伸释放片,USP"
            "被指为饮食的辅料和锻炼,以改善2型糖尿病病人的甘油控制."
        )
        self.assertNotIn("盐酸", translated)
        self.assertNotIn("甘油控制", translated)
        self.assertNotIn("INDICATIONS", translated)
        self.assertIn("鹽酸緩釋錠", translated)
        self.assertIn("第 2 型糖尿病", translated)
        self.assertIn("血糖控制", translated)

    @patch("core.services.qa_agent.requests.get")
    def test_automatic_translation_service_supports_mymemory(self, get):
        response = get.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "responseStatus": 200,
            "responseData": {"translatedText": "這個藥可能會引起頭暈和噁心。"},
        }
        translated = _translate_with_automatic_service(
            "This medicine may cause dizziness and nausea.",
            "https://api.mymemory.translated.net/get",
        )
        self.assertEqual(translated, "這個藥可能會引起頭暈和噁心。")
        self.assertEqual(get.call_args.kwargs["params"]["langpair"], "en|zh-TW")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reset-user",
            email="reset@example.com",
            password="Old-password-4826",
        )

    def test_password_can_be_reset_from_email_link(self):
        response = self.client.post(
            reverse("password_reset"), {"email": "reset@example.com"}
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        match = re.search(r"http://testserver(?P<path>/accounts/reset/\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        confirm = self.client.get(match.group("path"))
        self.assertEqual(confirm.status_code, 302)
        response = self.client.post(
            confirm.url,
            {
                "new_password1": "New-password-5937",
                "new_password2": "New-password-5937",
            },
        )
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-password-5937"))

    def test_registration_saves_reset_email(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new-caregiver",
                "email": "caregiver@example.com",
                "password1": "Medicine-safe-4826",
                "password2": "Medicine-safe-4826",
            },
        )
        self.assertRedirects(response, reverse("android_name_settings"))
        self.assertEqual(
            User.objects.get(username="new-caregiver").email,
            "caregiver@example.com",
        )

class WebPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="web-user", password="pass-12345")
        self.client.force_login(self.user)

    def test_main_authenticated_pages_render(self):
        for name in (
            "dashboard",
            "schedules",
            "agent_center",
            "dataset_center",
            "qa_center",
            "android_name_settings",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_dataset_page_lists_real_source_workflow(self):
        response = self.client.get(reverse("dataset_center"))
        self.assertContains(response, "openFDA")
        self.assertContains(response, "Kaggle")
        self.assertContains(response, "資料集匯入")

    def test_navigation_keeps_seven_main_pages(self):
        response = self.client.get(reverse("dashboard"))
        for label in (
            "首頁",
            "監控中心",
            "服藥排程",
            "AI Agent 追蹤",
            "語音衛教",
            "資料集匯入",
            "Android 名字",
        ):
            self.assertContains(response, label)

    def test_temporary_medication_uses_selected_elder(self):
        elder = Elder.objects.create(owner=self.user, name="王奶奶", age=78)
        scheduled_at = timezone.localtime() + timedelta(days=1)
        response = self.client.post(
            reverse("reminder_create"),
            {
                "elder": elder.pk,
                "medicine_name": "測試臨時藥物",
                "scheduled_datetime": scheduled_at.strftime("%Y-%m-%dT%H:%M"),
                "dose_count": "1",
                "reminder_hint": "飯後服用",
                "slot": "1",
                "device_id": "",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        reminder = Reminder.objects.get(medicine_name="測試臨時藥物")
        self.assertEqual(reminder.user_name, "王奶奶")
        self.assertEqual(reminder.user_age, "78")
        self.assertEqual(reminder.status, "已提醒")
        self.assertEqual(reminder.agent_state, "pending")


@override_settings(DEVICE_API_TOKEN=TOKEN)
class StrictThreeSlotLayoutTests(ApiTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="three-slot-owner", password="pass-12345")
        UserProfile.objects.create(user=self.user, android_name="三格測試長輩")
        self.elder = Elder.objects.create(owner=self.user, name="三格測試長輩", age=75)
        self.drug = Drug.objects.create(name_zh="三格測試藥")

    def test_health_contract_is_exactly_early_noon_evening(self):
        response = self.client.get(reverse("api_health"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["slot_count"], 3)
        self.assertEqual([item["label"] for item in body["slots"]], ["早", "中", "晚"])
        self.assertEqual([item["slot"] for item in body["slots"]], [1, 2, 3])
        self.assertEqual(body["pillbox_layout"], "early-noon-evening-3-slot")
        self.assertEqual(body["ui_revision"], 6)

    def test_dashboard_renders_only_three_slot_cards(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        html = response.content.decode("utf-8")
        self.assertContains(response, "早／中／晚三格藥盒感測狀態")
        self.assertContains(response, 'data-slot-count="3"')
        self.assertEqual(html.count('class="text-xs font-bold">早</div>'), 1)
        self.assertEqual(html.count('class="text-xs font-bold">中</div>'), 1)
        self.assertEqual(html.count('class="text-xs font-bold">晚</div>'), 1)
        self.assertNotIn("格 4", html)
        self.assertNotIn("格 5", html)
        self.assertNotIn("格 6", html)
        self.assertNotIn("格 7", html)

    def test_schedule_period_is_derived_from_slot(self):
        schedule = MedicationSchedule.objects.create(
            elder=self.elder,
            drug=self.drug,
            slot=2,
            period="morning",
            scheduled_time=time(12, 0),
        )
        self.assertEqual(schedule.period, "noon")
        schedule.slot = 3
        schedule.save()
        self.assertEqual(schedule.period, "evening")

    def test_sensor_slot_four_is_rejected(self):
        response = self.api_post(
            "api_sensor_event",
            {"device_id": "pillbox-01", "user_name": "三格測試長輩", "slot": 4, "event_type": "opened"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("早=1、中=2、晚=3", response.json()["error"])
