from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_change_missed_threshold_to_30"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sensorevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("opened", "藥盒開啟"),
                    ("closed", "藥盒關閉"),
                    ("heartbeat", "裝置心跳"),
                    ("presence_detected", "PIR 偵測到有人"),
                    ("presence_cleared", "PIR 未偵測到人"),
                ],
                default="opened",
                max_length=20,
                verbose_name="事件",
            ),
        ),
    ]
