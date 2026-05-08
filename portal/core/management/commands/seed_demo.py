from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Institution, Faculty, Department, AcademicClass, Subject, Student, Staff, Fee, Payment, Result


class Command(BaseCommand):
    help = "Seed demo data for EduPortal"

    def handle(self, *args, **options):
        User = get_user_model()

        secondary, _ = Institution.objects.get_or_create(
            name="Federal Government College, Lagos",
            defaults={"institution_type": "secondary", "city": "Lagos", "country": "Nigeria", "school_code": "FGGC", "short_name": "FGGC"},
        )
        tertiary, _ = Institution.objects.get_or_create(
            name="Coastal State University",
            defaults={"institution_type": "tertiary", "city": "Port Harcourt", "country": "Nigeria", "school_code": "CSU", "short_name": "CSU"},
        )

        def next_id(inst):
            inst.user_sequence += 1
            inst.save(update_fields=['user_sequence'])
            return f\"{(inst.short_name or 'SCH').upper()}/{timezone.now().year}/{inst.user_sequence:03d}\"

        def create_user(password="EduPortal123", role="student", institution=secondary):
            username = next_id(institution)
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True})
            if created:
                user.set_password(password)
                user.save()
            profile = getattr(user, "profile", None)
            if profile:
                profile.role = role
                profile.institution = institution
                profile.institution_type = institution.institution_type
                profile.is_approved = True
                profile.save()
            user.is_active = True
            user.save()
            return user

        create_user(role="admin", institution=secondary)
        create_user(role="registry", institution=secondary)
        create_user(role="accountant", institution=secondary)
        create_user(role="teacher", institution=secondary)
        create_user(role="student", institution=secondary)

        create_user(role="vc", institution=tertiary)
        create_user(role="provost", institution=tertiary)
        create_user(role="ict-admin", institution=tertiary)
        create_user(role="accountant", institution=tertiary)
        create_user(role="faculty-admin", institution=tertiary)
        create_user(role="department-admin", institution=tertiary)
        create_user(role="lecturer", institution=tertiary)
        create_user(role="examiner", institution=tertiary)
        create_user(role="student", institution=tertiary)

        sci, _ = Faculty.objects.get_or_create(institution=tertiary, name="Faculty of Science", defaults={"code": "SCI"})
        eng, _ = Faculty.objects.get_or_create(institution=tertiary, name="Faculty of Engineering", defaults={"code": "ENG"})
        Department.objects.get_or_create(faculty=sci, name="Computer Science", defaults={"code": "CSC"})
        Department.objects.get_or_create(faculty=eng, name="Mechanical Engineering", defaults={"code": "MEC"})

        classes = []
        for idx, name in enumerate(["JSS1", "JSS2", "JSS3", "SS1", "SS2", "SS3"], start=1):
            cls, _ = AcademicClass.objects.get_or_create(institution=secondary, name=name, defaults={"level": idx})
            classes.append(cls)

        subjects = []
        for name in ["Mathematics", "English Language", "Physics", "Biology", "Chemistry"]:
            subject, _ = Subject.objects.get_or_create(institution=secondary, name=name)
            subjects.append(subject)

        for i in range(1, 8):
            student, _ = Student.objects.get_or_create(
                institution=secondary,
                student_id=f"STU-{i:03d}",
                defaults={
                    "full_name": f"Student {i}",
                    "academic_class": classes[i % len(classes)],
                    "status": "Active",
                },
            )
            Payment.objects.get_or_create(
                institution=secondary,
                student=student,
                amount=45000,
                defaults={"status": "Paid", "paid_at": timezone.now()},
            )

        for i in range(1, 5):
            Staff.objects.get_or_create(
                institution=secondary,
                staff_id=f"STF-{i:03d}",
                defaults={
                    "full_name": f"Teacher {i}",
                    "role": "teacher",
                    "department": "Science",
                },
            )

        Fee.objects.get_or_create(
            institution=secondary,
            name="Tuition",
            defaults={"amount": 65000, "term": "First Term", "session": "2024/2025"},
        )

        for i, student in enumerate(Student.objects.filter(institution=secondary)[:5], start=1):
            Result.objects.get_or_create(
                institution=secondary,
                student=student,
                subject=subjects[i % len(subjects)],
                defaults={"test1": 12, "test2": 14, "assignment": 8, "exam": 55, "term": "First Term", "session": "2024/2025"},
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded. Use password: EduPortal123"))
