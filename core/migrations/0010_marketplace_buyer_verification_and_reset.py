from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_marketplace_buyer_and_order_buyer"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketplacebuyer",
            name="email_verification_code",
            field=models.CharField(blank=True, max_length=6),
        ),
        migrations.AddField(
            model_name="marketplacebuyer",
            name="email_code_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="marketplacebuyer",
            name="is_email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="marketplacebuyer",
            name="reset_code",
            field=models.CharField(blank=True, max_length=6),
        ),
        migrations.AddField(
            model_name="marketplacebuyer",
            name="reset_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
