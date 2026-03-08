from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_category_customer_expense_product_sale_saleitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="category",
            field=models.CharField(
                choices=[
                    ("Transport", "Transport"),
                    ("Rent", "Rent"),
                    ("Electricity", "Electricity"),
                    ("Salaries", "Salaries"),
                    ("Supplies", "Supplies"),
                    ("Maintenance", "Maintenance"),
                    ("Marketing", "Marketing"),
                    ("Other", "Other"),
                ],
                default="Other",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="expense",
            name="date",
            field=models.DateField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
