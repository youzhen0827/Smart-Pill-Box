from django.db import migrations, models


def change_existing_sixty_minute_thresholds(apps, schema_editor):
    schedule = apps.get_model("core", "MedicationSchedule")
    schedule.objects.filter(missed_after_minutes=60).update(missed_after_minutes=30)


class Migration(migrations.Migration):
    dependencies = [("core", "0016_aiagent_tfda_dataset")]

    operations = [
        migrations.AlterField(
            model_name="medicationschedule",
            name="missed_after_minutes",
            field=models.PositiveIntegerField(default=30, verbose_name="漏服判定分鐘"),
        ),
        migrations.RunPython(
            change_existing_sixty_minute_thresholds,
            migrations.RunPython.noop,
        ),
    ]
