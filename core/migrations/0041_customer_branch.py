from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0040_aiassistantmessage_aireceiptscan"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="customers",
                to="core.shopbranch",
            ),
        ),
    ]
