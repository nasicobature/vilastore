from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_user_shop_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="handled_by_shopboy",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="handled_sales",
                to="core.shopboy",
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="sales_channel",
            field=models.CharField(
                choices=[
                    ("owner_pos", "Owner POS"),
                    ("marketplace", "Marketplace"),
                    ("shopboy_portal", "Shop Boy Portal"),
                ],
                default="owner_pos",
                max_length=30,
            ),
        ),
    ]
