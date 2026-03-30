from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_product_code_product_unique_product_code_per_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="stock",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name="saleitem",
            name="quantity",
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
    ]
