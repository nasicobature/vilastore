from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_customer_religion_tribe"),
    ]

    operations = [
        migrations.CreateModel(
            name="Investor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("password", models.CharField(max_length=255)),
                ("investment_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("ownership_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
