from django.db import migrations


def backfill_branch_inventory(apps, schema_editor):
    User = apps.get_model("core", "User")
    ShopBranch = apps.get_model("core", "ShopBranch")
    Product = apps.get_model("core", "Product")
    BranchInventory = apps.get_model("core", "BranchInventory")

    for owner in User.objects.filter(account_type="shop"):
        branch = (
            ShopBranch.objects.filter(user=owner, is_active=True, is_default=True).first()
            or ShopBranch.objects.filter(user=owner, is_active=True).order_by("id").first()
        )
        if not branch:
            continue

        products = Product.objects.filter(user=owner).exclude(branch_inventory__is_active=True)
        for product in products.iterator():
            BranchInventory.objects.get_or_create(
                branch=branch,
                product=product,
                defaults={
                    "stock": product.stock,
                    "selling_price": product.selling_price,
                    "is_active": True,
                    "track_separately": True,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0042_category_branch"),
    ]

    operations = [
        migrations.RunPython(backfill_branch_inventory, migrations.RunPython.noop),
    ]
