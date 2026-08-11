from django.db import migrations, models
import decimal


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_user_tax_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="vat_status",
            field=models.CharField(choices=[("standard", "Standard (7.5%)"), ("zero", "Zero-rated (0%)"), ("exempt", "Exempt")], default="standard", max_length=10),
        ),
        migrations.AddField(
            model_name="sale",
            name="vat_total",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="vat_applicable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="vat_amount",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="vat_rate",
            field=models.DecimalField(decimal_places=4, default=decimal.Decimal("0.00"), max_digits=5),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="vat_status",
            field=models.CharField(choices=[("standard", "Standard (7.5%)"), ("zero", "Zero-rated (0%)"), ("exempt", "Exempt")], default="standard", max_length=10),
        ),
    ]
