from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
from django.db.models import Q


def normalize_slots_again(apps, schema_editor):
    MedicationSchedule = apps.get_model("core", "MedicationSchedule")
    Reminder = apps.get_model("core", "Reminder")
    SensorEvent = apps.get_model("core", "SensorEvent")
    PillBoxDevice = apps.get_model("core", "PillBoxDevice")

    MedicationSchedule.objects.filter(slot__lt=1).update(slot=1)
    MedicationSchedule.objects.filter(slot__gt=3).update(slot=3)
    MedicationSchedule.objects.filter(slot=1).update(period="morning")
    MedicationSchedule.objects.filter(slot=2).update(period="noon")
    MedicationSchedule.objects.filter(slot=3).update(period="evening")

    Reminder.objects.filter(slot__lt=1).update(slot=1)
    Reminder.objects.filter(slot__gt=3).update(slot=3)
    SensorEvent.objects.filter(slot__lt=1).update(slot=1)
    SensorEvent.objects.filter(slot__gt=3).update(slot=3)

    PillBoxDevice.objects.exclude(display_name="早／中／晚三格智慧藥盒").update(
        display_name="早／中／晚三格智慧藥盒"
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0012_three_slot_display_labels")]

    operations = [
        migrations.RunPython(normalize_slots_again, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="medicationschedule",
            name="slot",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                default=1,
                validators=[MinValueValidator(1), MaxValueValidator(3)],
                verbose_name="藥盒時段",
            ),
        ),
        migrations.AlterField(
            model_name="reminder",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(3)],
                verbose_name="藥盒時段",
            ),
        ),
        migrations.AlterField(
            model_name="sensorevent",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(3)],
                verbose_name="藥盒時段",
            ),
        ),
        migrations.AddConstraint(
            model_name="reminder",
            constraint=models.CheckConstraint(
                condition=Q(slot__isnull=True) | Q(slot__gte=1, slot__lte=3),
                name="reminder_slot_null_or_1_to_3",
            ),
        ),
        migrations.AddConstraint(
            model_name="sensorevent",
            constraint=models.CheckConstraint(
                condition=Q(slot__isnull=True) | Q(slot__gte=1, slot__lte=3),
                name="sensor_event_slot_null_or_1_to_3",
            ),
        ),
    ]
