from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.staticfiles import finders


class Command(BaseCommand):
    help = "Fail if required static assets are missing."

    def handle(self, *args, **options):
        required = [
            "css/styles.css",
        ]

        missing = []
        for asset in required:
            if finders.find(asset) is None:
                missing.append(asset)

        if missing:
            missing_list = ", ".join(missing)
            raise SystemExit(f"Missing static assets: {missing_list}")

        self.stdout.write("Static assets check passed.")
