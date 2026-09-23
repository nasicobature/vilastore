from django.core.management.base import BaseCommand
from django.db import transaction

from edu.models import EduMembership, Profile


class Command(BaseCommand):
    help = (
        "Phase 1 backfill: create an EduMembership row for every existing "
        "edu.Profile that has an institution set, without touching Profile or "
        "any other existing model. Safe to re-run -- profiles already backfilled "
        "are skipped. Defaults to a dry run; pass --confirm to actually create "
        "records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually create EduMembership rows. Without this flag, only a summary is printed.",
        )

    def handle(self, *args, **options):
        confirm = options["confirm"]

        already_member_pairs = set(
            EduMembership.objects.values_list("user_id", "institution_id")
        )
        profiles = Profile.objects.filter(institution__isnull=False)
        candidates = [
            profile
            for profile in profiles
            if (profile.user_id, profile.institution_id) not in already_member_pairs
        ]

        self.stdout.write(f"Profiles with an institution and no EduMembership yet: {len(candidates)}")

        if not confirm:
            self.stdout.write(self.style.WARNING("Dry run only -- no data was changed. Re-run with --confirm to apply."))
            return

        created = 0
        with transaction.atomic():
            for profile in candidates:
                EduMembership.objects.create(
                    user_id=profile.user_id,
                    institution_id=profile.institution_id,
                    role=profile.role,
                    faculty_id=profile.faculty_id,
                    department_id=profile.department_id,
                    is_approved=profile.is_approved,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} EduMembership row(s). No existing data was modified."))
