from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_delivery_company_and_rider_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliveryrider",
            name="company",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="riders", to="core.deliverycompany"),
        ),
    ]
