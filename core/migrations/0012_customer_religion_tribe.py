from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_marketplace_buyer_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="religion",
            field=models.CharField(blank=True, choices=[("", "Not specified"), ("muslim", "Muslim"), ("christian", "Christian"), ("other", "Other")], default="", max_length=20),
        ),
        migrations.AddField(
            model_name="customer",
            name="tribe",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
