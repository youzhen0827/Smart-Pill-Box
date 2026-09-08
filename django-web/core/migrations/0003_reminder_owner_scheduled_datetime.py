from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0002_reminder'),
    ]

    operations = [
        migrations.AddField(
            model_name='reminder',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='reminders',
                to=settings.AUTH_USER_MODEL,
                verbose_name='建立者帳號',
            ),
        ),
        migrations.AddField(
            model_name='reminder',
            name='scheduled_datetime',
            field=models.DateTimeField(blank=True, null=True, verbose_name='服藥日期時間'),
        ),
    ]
