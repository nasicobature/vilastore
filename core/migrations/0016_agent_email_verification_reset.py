from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_agent_portal"),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="is_email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agent",
            name="email_verification_code",
            field=models.CharField(blank=True, max_length=6),
        ),
        migrations.AddField(
            model_name="agent",
            name="email_code_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agent",
            name="reset_code",
            field=models.CharField(blank=True, max_length=6),
        ),
        migrations.AddField(
            model_name="agent",
            name="reset_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
