import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_houseinquiry_houseinquirymessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopBranch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("code", models.CharField(blank=True, max_length=24)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="branches", to="core.user")),
            ],
            options={
                "ordering": ["name", "id"],
            },
        ),
        migrations.CreateModel(
            name="BranchInventory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stock", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("selling_price", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("track_separately", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_items", to="core.shopbranch")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="branch_inventory", to="core.product")),
            ],
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="delivery_requests", to="core.shopbranch"),
        ),
        migrations.AddField(
            model_name="expense",
            name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="expenses", to="core.shopbranch"),
        ),
        migrations.AddField(
            model_name="marketplaceorder",
            name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_orders", to="core.shopbranch"),
        ),
        migrations.AddField(
            model_name="sale",
            name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sales", to="core.shopbranch"),
        ),
        migrations.AddField(
            model_name="shopboy",
            name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="staff_members", to="core.shopbranch"),
        ),
        migrations.AddField(
            model_name="shopboy",
            name="role",
            field=models.CharField(choices=[("owner", "Owner"), ("manager", "Manager"), ("staff", "Staff / Shopboy")], default="staff", max_length=20),
        ),
        migrations.AddConstraint(
            model_name="shopbranch",
            constraint=models.UniqueConstraint(fields=("user", "name"), name="unique_branch_name_per_user"),
        ),
        migrations.AddConstraint(
            model_name="branchinventory",
            constraint=models.UniqueConstraint(fields=("branch", "product"), name="unique_branch_product_inventory"),
        ),
    ]
