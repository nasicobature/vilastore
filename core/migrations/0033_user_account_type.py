from django.db import migrations, models


def set_existing_account_types(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.filter(business_type__iexact="housing").update(account_type="housing")
    User.objects.exclude(business_type__iexact="housing").update(account_type="shop")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_houselisting_listing_agent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="account_type",
            field=models.CharField(
                choices=[("shop", "Shop Owner"), ("housing", "Housing Owner")],
                default="shop",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_existing_account_types, migrations.RunPython.noop),
    ]
