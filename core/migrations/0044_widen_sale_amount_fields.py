from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0043_backfill_branch_inventory"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sale",
            name="amount_paid",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AlterField(
            model_name="sale",
            name="total_amount",
            field=models.DecimalField(decimal_places=2, max_digits=14),
        ),
        migrations.AlterField(
            model_name="sale",
            name="total_profit",
            field=models.DecimalField(decimal_places=2, max_digits=14),
        ),
        migrations.AlterField(
            model_name="saleitem",
            name="price",
            field=models.DecimalField(decimal_places=2, max_digits=14),
        ),
        migrations.AlterField(
            model_name="saleitem",
            name="profit",
            field=models.DecimalField(decimal_places=2, max_digits=14),
        ),
    ]
