from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_delivery_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliveryrider",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="home_address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="id_type",
            field=models.CharField(blank=True, choices=[("nin", "National ID (NIN)"), ("voter", "Voter's Card"), ("driver", "Driver's License")], max_length=20),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="id_number",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="id_document",
            field=models.ImageField(blank=True, null=True, upload_to="delivery/ids/"),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="vehicle_type",
            field=models.CharField(blank=True, choices=[("bike", "Bike"), ("car", "Car"), ("tricycle", "Tricycle")], max_length=20),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="plate_number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="vehicle_color",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="vehicle_model",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="profile_photo",
            field=models.ImageField(blank=True, null=True, upload_to="delivery/profile/"),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="vehicle_photo",
            field=models.ImageField(blank=True, null=True, upload_to="delivery/vehicle/"),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="plate_photo",
            field=models.ImageField(blank=True, null=True, upload_to="delivery/plate/"),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="city",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="operating_areas",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="bank_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="account_number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="account_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="allow_direct_call",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="deliveryrider",
            name="terms_accepted",
            field=models.BooleanField(default=False),
        ),
    ]
