from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0014_remove_reminder_reminder_slot_null_or_1_to_3")]

    operations = [
        migrations.AlterField(
            model_name="agentintervention",
            name="intervention_type",
            field=models.CharField(
                choices=[
                    ("initial_reminder", "到時提醒"),
                    ("sensor_missing", "感測器未偵測"),
                    ("device_check", "請確認藥盒連線"),
                    ("caregiver_escalation", "提早通知照護者"),
                    ("missed_escalation", "漏服升級通知"),
                    ("qa_education", "醫療衛教"),
                ],
                max_length=30,
                verbose_name="介入類型",
            ),
        ),
        migrations.CreateModel(
            name="AgentDecision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stage", models.CharField(choices=[("before_due", "尚未到時"), ("due_window", "到時等待"), ("follow_up_window", "逾時追蹤"), ("overdue", "疑似漏服"), ("sensor_confirmed", "感測確認")], max_length=30, verbose_name="決策階段")),
                ("planner", models.CharField(choices=[("safe_policy", "本機安全規劃器"), ("llm", "AI 模型規劃器"), ("llm_fallback", "AI 模型失敗後安全規劃器")], max_length=30, verbose_name="規劃方式")),
                ("model_name", models.CharField(blank=True, default="", max_length=120, verbose_name="模型名稱")),
                ("risk_score", models.PositiveSmallIntegerField(default=0, verbose_name="風險分數")),
                ("risk_level", models.CharField(choices=[("low", "低"), ("medium", "中"), ("high", "高")], max_length=10, verbose_name="風險等級")),
                ("observation", models.JSONField(default=dict, verbose_name="觀察資料")),
                ("available_tools", models.JSONField(default=list, verbose_name="可用工具")),
                ("planned_tools", models.JSONField(default=list, verbose_name="選用工具")),
                ("reasoning", models.TextField(verbose_name="決策理由")),
                ("execution_result", models.JSONField(default=dict, verbose_name="執行結果")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="首次決策時間")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="最後決策時間")),
                ("reminder", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="agent_decisions", to="core.reminder")),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.AddConstraint(
            model_name="agentdecision",
            constraint=models.UniqueConstraint(fields=("reminder", "stage"), name="uniq_agent_decision_per_stage"),
        ),
    ]
