from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_alter_deliverycompany_id_alter_deliveryrequest_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="houselisting",
            name="owner",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="house_listings", to="core.user"),
        ),
        migrations.AddField(
            model_name="houselisting",
            name="is_approved",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="houselisting",
            name="listing_agent",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="property_listings", to="core.agent"),
        ),
        migrations.AddField(
            model_name="houselisting",
            name="listing_mode",
            field=models.CharField(choices=[("rent", "For Rent"), ("sale", "For Sale")], default="rent", max_length=10),
        ),
    ]
