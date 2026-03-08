from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_investor"),
    ]

    operations = [
        migrations.CreateModel(
            name="Feedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254)),
                ("category", models.CharField(choices=[("general", "General Feedback"), ("bug", "Bug Report"), ("feature", "Feature Request"), ("support", "Support")], default="general", max_length=20)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
