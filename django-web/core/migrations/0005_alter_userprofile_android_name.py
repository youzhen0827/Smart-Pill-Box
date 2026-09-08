from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_userprofile'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='android_name',
            field=models.TextField(blank=True, verbose_name='Android使用者姓名名單'),
        ),
    ]
