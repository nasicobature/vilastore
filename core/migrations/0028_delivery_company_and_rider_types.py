from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_delivery_rider_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliveryrider",
            name="rider_type",
            field=models.CharField(choices=[("personal", "Personal Rider"), ("company", "Company Rider")], default="personal", max_length=20),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="is_approved",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="DeliveryCompany",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company_name", models.CharField(max_length=200)),
                ("phone", models.CharField(max_length=30)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(max_length=80)),
                ("operating_areas", models.TextField(blank=True)),
                ("bank_name", models.CharField(max_length=100)),
                ("account_number", models.CharField(max_length=30)),
                ("account_name", models.CharField(max_length=120)),
                ("terms_accepted", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="delivery_company",
                        to="core.marketplacebuyer",
                    ),
                ),
            ],
        ),
    ]
