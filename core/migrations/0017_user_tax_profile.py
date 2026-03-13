from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_agent_email_verification_reset"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="fixed_assets",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="is_professional_services",
            field=models.BooleanField(default=False),
        ),
    ]
