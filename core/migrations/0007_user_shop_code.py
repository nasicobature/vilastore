from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_marketplace_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="shop_code",
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
    ]
