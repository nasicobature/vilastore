from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_marketplace_buyer_verification_and_reset"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketplaceBuyerToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=80, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_revoked", models.BooleanField(default=False)),
                ("buyer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tokens", to="core.marketplacebuyer")),
            ],
        ),
    ]
