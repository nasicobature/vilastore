from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_feedback"),
    ]

    operations = [
        migrations.CreateModel(
            name="Agent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=150)),
                ("username", models.CharField(max_length=80, unique=True)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("password", models.CharField(max_length=255)),
                ("referral_code", models.CharField(blank=True, max_length=20, unique=True)),
                ("commission_rate", models.DecimalField(decimal_places=2, default=Decimal("0.15"), max_digits=5)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.AddField(
            model_name="user",
            name="referred_by_agent",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="referred_users", to="core.agent"),
        ),
    ]
