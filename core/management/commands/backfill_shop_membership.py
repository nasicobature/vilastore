from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Shop, ShopMembership

# Reverse relation names on the User model that indicate real shop
# activity. account_type defaults to "shop" for every user (including
# EduPortal-only accounts), so it can't reliably tell shop owners apart
# from everyone else -- actual data ownership can.
SHOP_FOOTPRINT_RELATIONS = [
    "branches",
    "product",
    "customer",
    "sale",
    "expense",
    "ai_receipt_scans",
    "ai_assistant_messages",
    "shopboy",
    "marketplace_profile",
    "marketplace_settings",
    "house_listings",
    "tenant_records",
    "customer_scan_carts",
    "marketplace_orders",
    "house_inquiries",
    "category",
]


def has_shop_footprint(user):
    for relation_name in SHOP_FOOTPRINT_RELATIONS:
        related = getattr(user, relation_name, None)
        if related is None:
            continue
        try:
            if related.exists():
                return True
        except AttributeError:
            return True
    return False


class Command(BaseCommand):
    help = (
        "Phase 1 backfill: create a Shop + ShopMembership(role=owner) for every "
        "existing user with real Shop Management data, without touching any "
        "existing model or foreign key. Safe to re-run -- users that already "
        "have a ShopMembership are skipped. Defaults to a dry run; pass "
        "--confirm to actually create records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually create Shop/ShopMembership rows. Without this flag, only a summary is printed.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        confirm = options["confirm"]

        already_member_ids = set(ShopMembership.objects.values_list("user_id", flat=True))
        candidates = [
            user
            for user in User.objects.exclude(id__in=already_member_ids)
            if has_shop_footprint(user)
        ]

        self.stdout.write(f"Users with shop data and no ShopMembership yet: {len(candidates)}")

        if not confirm:
            self.stdout.write(self.style.WARNING("Dry run only -- no data was changed. Re-run with --confirm to apply."))
            return

        created = 0
        with transaction.atomic():
            for user in candidates:
                shop = Shop.objects.create(
                    business_name=user.business_name,
                    shop_code=user.shop_code or None,
                )
                ShopMembership.objects.create(user=user, shop=shop, role=ShopMembership.ROLE_OWNER)
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} Shop + ShopMembership pair(s). No existing data was modified."))
