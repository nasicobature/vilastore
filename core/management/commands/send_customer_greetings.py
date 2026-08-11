from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Customer
from core.utils.notifications import send_email, send_sms
from core.views import _plan_has_feature


class Command(BaseCommand):
    help = "Send weekly (Friday/Sunday) and birthday greetings to customers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print messages without sending.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        weekday = today.weekday()  # Monday=0
        is_friday = weekday == 4
        is_sunday = weekday == 6
        dry_run = options.get("dry_run", False)

        total_sent = 0

        customers = Customer.objects.select_related("user")
        for customer in customers:
            if not _plan_has_feature(customer.user, "customer_automation"):
                continue
            shop_name = (customer.user.business_name or customer.user.username or "VilaStore").strip()
            outbound_messages = []

            if customer.religion == Customer.RELIGION_MUSLIM and is_friday:
                outbound_messages.append(f"Jummah Mubarak from {shop_name}. Have a blessed Friday.")
            elif customer.religion == Customer.RELIGION_CHRISTIAN and is_sunday:
                outbound_messages.append(f"Happy Sunday from {shop_name}. Have a blessed day.")

            if customer.birthday and customer.birthday.month == today.month and customer.birthday.day == today.day:
                outbound_messages.append(
                    f"Happy Birthday {customer.first_name}! {shop_name} wishes you a joyful day."
                )

            for message in outbound_messages:
                if dry_run:
                    self.stdout.write(f"[DRY RUN] {customer.phone} / {customer.email}: {message}")
                    total_sent += 1
                    continue

                if customer.phone:
                    send_sms(customer.phone, message)

                if customer.email:
                    subject = f"{shop_name} - A message for you"
                    send_email(customer.email, subject, message)

                total_sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {total_sent} message(s)."))
