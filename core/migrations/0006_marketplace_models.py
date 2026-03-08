from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_expense_category_and_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketplaceSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_shopboy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_assignments", to="core.shopboy")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_settings", to="core.user")),
            ],
        ),
        migrations.CreateModel(
            name="MarketplaceShopProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.TextField(blank=True)),
                ("category", models.CharField(blank=True, max_length=100)),
                ("location", models.CharField(blank=True, max_length=100)),
                ("is_verified", models.BooleanField(default=False)),
                ("rating", models.DecimalField(decimal_places=2, default=4.5, max_digits=3)),
                ("logo", models.ImageField(blank=True, null=True, upload_to="marketplace/logos/")),
                ("cover_image", models.ImageField(blank=True, null=True, upload_to="marketplace/covers/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_profile", to="core.user")),
            ],
        ),
        migrations.CreateModel(
            name="MarketplaceOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("access_token", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("buyer_name", models.CharField(max_length=255)),
                ("buyer_contact", models.CharField(max_length=255)),
                ("buyer_address", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("paid", "Paid"), ("shipped", "Shipped"), ("delivered", "Delivered"), ("cancelled", "Cancelled")], default="pending", max_length=20)),
                ("total_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_shopboy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_orders", to="core.shopboy")),
                ("sale", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_order", to="core.sale")),
                ("shop_owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marketplace_orders", to="core.user")),
            ],
        ),
        migrations.CreateModel(
            name="MarketplaceOrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="core.marketplaceorder")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.product")),
            ],
        ),
        migrations.CreateModel(
            name="MarketplaceChatMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sender_type", models.CharField(choices=[("buyer", "Buyer"), ("seller", "Seller"), ("system", "System")], default="buyer", max_length=20)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="core.marketplaceorder")),
            ],
        ),
    ]
