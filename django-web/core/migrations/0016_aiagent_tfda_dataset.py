from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0015_agentdecision")]

    operations = [
        migrations.AlterField(
            model_name="drugknowledgedocument",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("openfda_ndc", "FDA NDC Directory"),
                    ("openfda_label", "FDA Drug Label"),
                    ("kaggle_csv", "Kaggle Drug Interactions / Side Effects CSV"),
                    ("tfda_license", "台灣食藥署未註銷藥品許可證"),
                ],
                max_length=30,
                verbose_name="資料來源",
            ),
        ),
        migrations.AlterField(
            model_name="datasetsyncrun",
            name="source",
            field=models.CharField(
                choices=[
                    ("openfda", "openFDA"),
                    ("kaggle_csv", "Kaggle CSV"),
                    ("tfda", "台灣食藥署"),
                ],
                max_length=30,
                verbose_name="來源",
            ),
        ),
    ]
