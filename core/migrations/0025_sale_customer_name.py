from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_sale_payment_status_amount_paid"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="customer_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
