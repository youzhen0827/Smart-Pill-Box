# Generated for display labels after early/noon/evening three-slot conversion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_three_slot_pillbox"),
    ]

    operations = [
        migrations.AlterField(
            model_name="medicationschedule",
            name="slot",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                default=1,
                verbose_name="服藥時段",
            ),
        ),
        migrations.AlterField(
            model_name="reminder",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                verbose_name="服藥時段",
            ),
        ),
        migrations.AlterField(
            model_name="sensorevent",
            name="slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "早"), (2, "中"), (3, "晚")],
                null=True,
                verbose_name="服藥時段",
            ),
        ),
    ]
