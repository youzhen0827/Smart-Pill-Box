# Generated for early/noon/evening three-slot pillbox
from django.db import migrations, models
from django.db.models import Q


def normalize_existing_slot_data(apps, schema_editor):
    MedicationSchedule = apps.get_model("core", "MedicationSchedule")
    Reminder = apps.get_model("core", "Reminder")
    SensorEvent = apps.get_model("core", "SensorEvent")
    PillBoxDevice = apps.get_model("core", "PillBoxDevice")

    MedicationSchedule.objects.filter(slot__gt=3).update(slot=3)
    MedicationSchedule.objects.filter(period="bedtime").update(period="evening")
    Reminder.objects.filter(slot__gt=3).update(slot=3)
    SensorEvent.objects.filter(slot__gt=3).update(slot=3)
    PillBoxDevice.objects.filter(display_name="七格智慧藥盒").update(display_name="早／中／晚三格智慧藥盒")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_weekdays_one_to_seven"),
    ]

    operations = [
        migrations.RunPython(normalize_existing_slot_data, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="medicationschedule",
            name="period",
            field=models.CharField(
                choices=[("morning", "早"), ("noon", "中"), ("evening", "晚")],
                default="morning",
                max_length=10,
                verbose_name="時段",
            ),
        ),
        migrations.AlterField(
            model_name="medicationschedule",
            name="slot",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                default=1,
                verbose_name="格子編號",
            ),
        ),
        migrations.AlterField(
            model_name="reminder",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                verbose_name="藥盒格位",
            ),
        ),
        migrations.AlterField(
            model_name="sensorevent",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                verbose_name="格位",
            ),
        ),
        migrations.AlterField(
            model_name="pillboxdevice",
            name="display_name",
            field=models.CharField(default="早／中／晚三格智慧藥盒", max_length=100, verbose_name="裝置名稱"),
        ),
        migrations.RemoveConstraint(
            model_name="medicationschedule",
            name="schedule_slot_1_to_7",
        ),
        migrations.AddConstraint(
            model_name="medicationschedule",
            constraint=models.CheckConstraint(condition=Q(slot__gte=1, slot__lte=3), name="schedule_slot_1_to_3"),
        ),
    ]
