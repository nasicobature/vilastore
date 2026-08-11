from django.db import migrations, models
from django.db.models import F


def set_paid_for_existing(apps, schema_editor):
    Sale = apps.get_model("core", "Sale")
    Sale.objects.all().update(amount_paid=F("total_amount"), payment_status="paid")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_ownercart"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="amount_paid",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="sale",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("paid", "Paid"),
                    ("loan", "Loan (Unpaid)"),
                    ("partial", "Partially Paid"),
                ],
                default="paid",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_paid_for_existing, migrations.RunPython.noop),
    ]
