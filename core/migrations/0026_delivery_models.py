from decimal import Decimal
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_sale_customer_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryRider",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(blank=True, max_length=150)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("is_active", models.BooleanField(default=True)),
                ("is_available", models.BooleanField(default=True)),
                ("current_lat", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("current_lng", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="delivery_rider",
                        to="core.marketplacebuyer",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DeliveryRequest",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("pickup_address", models.CharField(max_length=255)),
                ("dropoff_address", models.CharField(max_length=255)),
                ("pickup_lat", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("pickup_lng", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("dropoff_lat", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("dropoff_lng", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("distance_km", models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ("price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("customer_name", models.CharField(blank=True, max_length=150)),
                ("customer_phone", models.CharField(blank=True, max_length=30)),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("rider_selected", "Rider Selected"),
                            ("accepted", "Accepted"),
                            ("picked_up", "Picked Up"),
                            ("delivered", "Delivered"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="requested",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="delivery_requests",
                        to="core.marketplacebuyer",
                    ),
                ),
                (
                    "rider",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="delivery_requests",
                        to="core.deliveryrider",
                    ),
                ),
            ],
        ),
    ]
