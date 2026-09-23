from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from edu.models import Institution, Profile

# Reverse relation names on the User model that indicate the account is
# also used on the Shop Management side. Any such user is kept (its edu
# Profile is reset instead of deleting the account) so this command never
# touches Shop Management data.
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
            # OneToOne reverse accessor: existence of the attribute is enough.
            return True
    return False


class Command(BaseCommand):
    help = (
        "Wipe all EduPortal data (institutions, students, staff, results, "
        "fees, etc.) so onboarding can start fresh. Shop Management data is "
        "never touched. Defaults to a dry run; pass --confirm to actually delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually perform the deletion. Without this flag, only a summary is printed.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        confirm = options["confirm"]

        institution_qs = Institution.objects.all()
        institution_count = institution_qs.count()

        edu_user_ids = list(
            Profile.objects.filter(institution__isnull=False)
            .values_list("user_id", flat=True)
            .distinct()
        )
        edu_users = list(User.objects.filter(id__in=edu_user_ids))

        users_to_delete = []
        users_to_keep = []
        for user in edu_users:
            if user.is_superuser or has_shop_footprint(user):
                users_to_keep.append(user)
            else:
                users_to_delete.append(user)

        self.stdout.write(f"Institutions to delete (cascades students, staff, results, fees, etc.): {institution_count}")
        self.stdout.write(f"EduPortal-only user accounts to delete: {len(users_to_delete)}")
        self.stdout.write(f"Accounts kept (also used in Shop Management or superuser) whose EduPortal profile will be cleared: {len(users_to_keep)}")

        if not confirm:
            self.stdout.write(self.style.WARNING("Dry run only -- no data was changed. Re-run with --confirm to apply."))
            return

        with transaction.atomic():
            institution_qs.delete()

            for user in users_to_delete:
                user.delete()

            for user in users_to_keep:
                profile = getattr(user, "profile", None)
                if not profile:
                    continue
                profile.institution = None
                profile.institution_type = "secondary"
                profile.role = "student"
                profile.faculty = None
                profile.department = None
                profile.is_approved = False
                profile.created_by = None
                profile.created_via = ""
                profile.approved_by = None
                profile.approved_at = None
                profile.email_verified = False
                profile.email_verification_token = ""
                profile.email_verification_sent_at = None
                profile.email_verification_expires_at = None
                profile.password_reset_token = ""
                profile.password_reset_sent_at = None
                profile.password_reset_expires_at = None
                profile.save()

        self.stdout.write(self.style.SUCCESS("EduPortal data reset complete. Shop Management data was not touched."))
