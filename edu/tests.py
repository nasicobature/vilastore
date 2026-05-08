from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .models import (
    AcademicClass,
    AcademicSession,
    AcademicTerm,
    ClassSubject,
    Fee,
    Institution,
    Payment,
    Profile,
    Result,
    ResultSubmission,
    Staff,
    Student,
    Subject,
    TeacherAssignment,
    TeacherSubjectAssignment,
)


class EduPortalRoutingTests(TestCase):
    def test_index_links_use_edu_prefixed_routes(self):
        response = self.client.get(reverse("edu:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/edu/secondary/login/"')
        self.assertContains(response, 'href="/edu/tertiary/login/"')
        self.assertNotContains(response, 'href="/secondary/login/"')
        self.assertNotContains(response, 'href="/tertiary/login/"')

    def test_index_shows_launch_pricing_and_coming_soon_modules(self):
        response = self.client.get(reverse("edu:index"))

        self.assertContains(response, "Starter School")
        self.assertContains(response, "₦50,000")
        self.assertContains(response, "Up to 250 students")
        self.assertContains(response, "Growth School")
        self.assertContains(response, "Up to 700 students")
        self.assertContains(response, "Professional School")
        self.assertContains(response, "Up to 1,500 students")
        self.assertContains(response, "Enterprise / Tertiary")
        self.assertContains(response, "Coming Soon Modules")

    def test_edu_login_pages_exist(self):
        secondary = self.client.get(reverse("edu:secondary_login"))
        tertiary = self.client.get(reverse("edu:tertiary_login"))

        self.assertEqual(secondary.status_code, 200)
        self.assertEqual(tertiary.status_code, 200)

    def test_registration_pages_render_verification_wizard(self):
        secondary = self.client.get(reverse("edu:secondary_register"))
        tertiary = self.client.get(reverse("edu:tertiary_register"))

        for response in (secondary, tertiary):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'class="wizard-form"')
            self.assertContains(response, "Verification Documents")
            self.assertContains(response, "Submit for Verification")


class EduPortalVerificationRegistrationTests(TestCase):
    def _file(self, name):
        return SimpleUploadedFile(name, b"test document", content_type="application/pdf")

    def _verification_files(self):
        return {
            "cac_certificate": self._file("cac-certificate.pdf"),
            "cac_status_report": self._file("cac-status-report.pdf"),
            "ministry_approval": self._file("ministry-approval.pdf"),
            "tin_certificate": self._file("tin-certificate.pdf"),
            "school_letterhead": self._file("letterhead.pdf"),
            "school_stamp": self._file("school-stamp.pdf"),
            "owner_valid_id": self._file("owner-id.pdf"),
            "utility_bill": self._file("utility-bill.pdf"),
        }

    def test_secondary_registration_requires_verification_documents(self):
        response = self.client.post(reverse("edu:secondary_register"), {
            "institution_name": "Missing Docs Academy",
            "admin_full_name": "School Admin",
            "admin_password": "StrongPass123!",
            "admin_email": "admin@example.com",
            "admin_phone": "08000000000",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please complete verification requirements")
        self.assertFalse(Institution.objects.filter(name="Missing Docs Academy").exists())

    def test_secondary_registration_creates_pending_verification_school(self):
        data = {
            "institution_name": "Verified Pending Academy",
            "admin_full_name": "School Admin",
            "admin_password": "StrongPass123!",
            "admin_email": "admin@example.com",
            "admin_phone": "08000000000",
        }
        data.update(self._verification_files())

        response = self.client.post(reverse("edu:secondary_register"), data)

        self.assertRedirects(response, reverse("edu:secondary_login"))
        institution = Institution.objects.get(name="Verified Pending Academy")
        profile = Profile.objects.get(institution=institution, role="admin")
        self.assertEqual(institution.verification_status, "pending")
        self.assertEqual(profile.user.email, "admin@example.com")
        self.assertFalse(profile.is_approved)
        self.assertTrue(institution.cac_certificate)
        self.assertTrue(institution.owner_valid_id)

    def test_pending_school_admin_login_shows_verification_message(self):
        data = {
            "institution_name": "Pending Login Academy",
            "admin_full_name": "School Admin",
            "admin_password": "StrongPass123!",
            "admin_email": "admin@example.com",
            "admin_phone": "08000000000",
        }
        data.update(self._verification_files())
        self.client.post(reverse("edu:secondary_register"), data)
        institution = Institution.objects.get(name="Pending Login Academy")
        profile = Profile.objects.get(institution=institution, role="admin")

        response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": profile.user.username,
            "password": "StrongPass123!",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "School verification is still pending")
        self.assertFalse("_auth_user_id" in self.client.session)

        email_response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "admin@example.com",
            "password": "StrongPass123!",
        })
        self.assertEqual(email_response.status_code, 200)
        self.assertContains(email_response, "School verification is still pending")

        phone_response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "08000000000",
            "password": "StrongPass123!",
        })
        self.assertEqual(phone_response.status_code, 200)
        self.assertContains(phone_response, "School verification is still pending")

    def test_login_repairs_missing_profile_from_staff_record(self):
        institution = Institution.objects.create(
            name="Approved Repair Academy",
            institution_type="secondary",
            verification_status="approved",
        )
        user = get_user_model().objects.create_user(
            username="repair-admin",
            password="StrongPass123!",
            email="repair@example.com",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        Profile.objects.filter(user=user).delete()
        Staff.objects.create(
            institution=institution,
            user=user,
            full_name="Repair Admin",
            staff_id="REP/001",
            role="admin",
        )

        response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "repair-admin",
            "password": "StrongPass123!",
        })

        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.institution, institution)
        self.assertEqual(profile.role, "admin")
        self.assertTrue(profile.is_approved)
        self.assertRedirects(response, reverse("edu:secondary_dashboard", kwargs={"role": "admin"}))

    def test_approved_school_admin_login_is_not_sent_to_shop_subscription_payment(self):
        institution = Institution.objects.create(
            name="Approved No Shop Sub Academy",
            institution_type="secondary",
            verification_status="approved",
        )
        user = get_user_model().objects.create_user(
            username="approved-admin",
            password="StrongPass123!",
            email="approved@example.com",
        )
        profile = user.profile
        profile.institution = institution
        profile.institution_type = "secondary"
        profile.role = "admin"
        profile.is_approved = True
        profile.save()

        response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "approved-admin",
            "password": "StrongPass123!",
        })

        self.assertRedirects(response, reverse("edu:secondary_dashboard", kwargs={"role": "admin"}))

class EduPortalFeesTests(TestCase):
    def setUp(self):
        self.institution = Institution.objects.create(
            name="Fees Academy",
            institution_type="secondary",
            verification_status="approved",
        )
        self.accountant = get_user_model().objects.create_user(
            username="acct",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        profile = self.accountant.profile
        profile.institution = self.institution
        profile.institution_type = "secondary"
        profile.role = "accountant"
        profile.is_approved = True
        profile.save()
        self.client.force_login(self.accountant)
        self.academic_class = AcademicClass.objects.create(
            institution=self.institution,
            name="JSS1",
            level=1,
        )
        self.student = Student.objects.create(
            institution=self.institution,
            full_name="Ada Student",
            student_id="FA/2026/001",
            academic_class=self.academic_class,
        )

    def test_school_can_add_current_session_and_term(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        admin.profile.institution = self.institution
        admin.profile.institution_type = "secondary"
        admin.profile.role = "admin"
        admin.profile.is_approved = True
        admin.profile.save()
        self.client.force_login(admin)

        response = self.client.post(reverse("edu:secondary_add_session_term"), {
            "session_name": "2026/2027",
            "term": "first",
            "is_current": "on",
        })

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "admin", "page": "sessions"}))
        session = AcademicSession.objects.get(institution=self.institution, name="2026/2027")
        term = AcademicTerm.objects.get(session=session, term="first")
        self.assertTrue(session.is_current)
        self.assertTrue(term.is_current)

    def test_registry_assigns_session_and_term_to_class(self):
        registry = get_user_model().objects.create_user(
            username="registry",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        registry.profile.institution = self.institution
        registry.profile.institution_type = "secondary"
        registry.profile.role = "registry"
        registry.profile.is_approved = True
        registry.profile.save()
        self.client.force_login(registry)
        session = AcademicSession.objects.create(institution=self.institution, name="2025/2026")
        term = AcademicTerm.objects.create(session=session, term="first")

        response = self.client.post(reverse("edu:secondary_assign_class_session_term"), {
            "academic_class": str(self.academic_class.id),
            "academic_session": str(session.id),
            "academic_term": str(term.id),
        })

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "registry", "page": "sessions"}))
        self.academic_class.refresh_from_db()
        self.assertEqual(self.academic_class.academic_session, session)
        self.assertEqual(self.academic_class.academic_term, term)

    def test_teacher_scores_use_registry_session_term_and_save_metadata(self):
        session = AcademicSession.objects.create(institution=self.institution, name="2025/2026")
        term = AcademicTerm.objects.create(session=session, term="first")
        subject = Subject.objects.create(institution=self.institution, name="Mathematics", code="MTH")
        teacher_user = get_user_model().objects.create_user(
            username="teacher",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        teacher_user.profile.institution = self.institution
        teacher_user.profile.institution_type = "secondary"
        teacher_user.profile.role = "teacher"
        teacher_user.profile.is_approved = True
        teacher_user.profile.save()
        teacher = Staff.objects.create(
            institution=self.institution,
            user=teacher_user,
            full_name="Teacher One",
            staff_id="TCH/001",
            role="teacher",
        )
        TeacherAssignment.objects.create(institution=self.institution, teacher=teacher, academic_class=self.academic_class)
        ClassSubject.objects.create(academic_class=self.academic_class, subject=subject)
        TeacherSubjectAssignment.objects.create(
            institution=self.institution,
            teacher=teacher,
            academic_class=self.academic_class,
            subject=subject,
        )
        self.client.force_login(teacher_user)

        response = self.client.post(reverse("edu:secondary_save_scores"), {
            "academic_session": str(session.id),
            "academic_term": str(term.id),
            "academic_class": str(self.academic_class.id),
            "subject": str(subject.id),
            "students": [str(self.student.id)],
            f"test1_{self.student.id}": "10",
            f"test2_{self.student.id}": "9",
            f"assignment_{self.student.id}": "8",
            f"exam_{self.student.id}": "60",
        })
        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "teacher", "page": "enter-scores"}))
        result = Result.objects.get(student=self.student, subject=subject)
        self.assertEqual(result.academic_class, self.academic_class)
        self.assertEqual(result.teacher, teacher)
        self.assertEqual(result.academic_session, session)
        self.assertEqual(result.academic_term, term)
        self.assertEqual(result.session, "2025/2026")
        self.assertEqual(result.term, "First Term")

        response = self.client.post(reverse("edu:secondary_submit_results"), {
            "academic_session": str(session.id),
            "academic_term": str(term.id),
            "academic_class": str(self.academic_class.id),
            "subject": str(subject.id),
        })
        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "teacher", "page": "submit-results"}))
        submission = ResultSubmission.objects.get(submitted_by=teacher, subject=subject)
        self.assertEqual(submission.academic_session, session)
        self.assertEqual(submission.academic_term, term)

    def test_registry_student_id_cards_page_is_active(self):
        admin = get_user_model().objects.create_user(
            username="id-admin",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        admin.profile.institution = self.institution
        admin.profile.institution_type = "secondary"
        admin.profile.role = "registry"
        admin.profile.is_approved = True
        admin.profile.save()
        self.client.force_login(admin)

        response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "registry", "page": "student-ids"}))

        self.assertContains(response, "Student ID Cards")
        self.assertContains(response, "Ada Student")
        self.assertContains(response, self.student.student_id)
        self.assertNotContains(response, "Coming soon")

    def test_student_portal_sections_are_active(self):
        student_user = get_user_model().objects.create_user(
            username="student-user",
            password="StrongPass123!",
            email="student@example.com",
        )
        student_user.profile.institution = self.institution
        student_user.profile.institution_type = "secondary"
        student_user.profile.role = "student"
        student_user.profile.is_approved = True
        student_user.profile.save()
        self.student.user = student_user
        self.student.save(update_fields=["user"])
        session = AcademicSession.objects.create(institution=self.institution, name="2025/2026", is_current=True)
        term = AcademicTerm.objects.create(session=session, term="first", is_current=True)
        self.academic_class.academic_session = session
        self.academic_class.academic_term = term
        self.academic_class.save(update_fields=["academic_session", "academic_term"])
        subject = Subject.objects.create(institution=self.institution, name="English Language", code="ENG")
        ClassSubject.objects.create(academic_class=self.academic_class, subject=subject)
        teacher = Staff.objects.create(
            institution=self.institution,
            full_name="Teacher Two",
            staff_id="TCH/002",
            role="teacher",
        )
        Result.objects.create(
            institution=self.institution,
            student=self.student,
            academic_class=self.academic_class,
            subject=subject,
            teacher=teacher,
            academic_session=session,
            academic_term=term,
            session=session.name,
            term=term.get_term_display(),
            test1="8",
            test2="9",
            assignment="10",
            exam="55",
        )
        fee = Fee.objects.create(
            institution=self.institution,
            name="First Term Fee",
            amount="12000",
            session=session.name,
            term=term.get_term_display(),
        )
        fee.classes.set([self.academic_class])
        payment = Payment.objects.create(
            institution=self.institution,
            fee=fee,
            student=self.student,
            amount="2000",
            status="Paid",
            payment_method="Manual",
        )
        self.client.force_login(student_user)

        expectations = {
            "subjects-student": ["My Subjects", "English Language"],
            "test-scores": ["My Test Scores", "English Language", "8.00"],
            "results": ["My Results", "82.00", "A"],
            "pay-fees": ["My School Fees", "First Term Fee", "Receipt"],
            "profile": ["Ada Student", "Fees Academy", self.student.student_id],
        }
        for page, texts in expectations.items():
            response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": page}))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Coming Soon")
            for text in texts:
                self.assertContains(response, text)

    def test_accountant_can_create_class_fee_and_record_payment(self):
        response = self.client.post(reverse("edu:secondary_create_fee"), {
            "name": "First Term Tuition",
            "fee_type": "Tuition",
            "amount": "15000",
            "session": "2026/2027",
            "term": "First Term",
            "classes": [str(self.academic_class.id)],
        })

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "accountant", "page": "fees"}))
        fee = Fee.objects.get(institution=self.institution, name="First Term Tuition")
        self.assertEqual(fee.classes.count(), 1)

        response = self.client.post(reverse("edu:secondary_record_payment"), {
            "fee": str(fee.id),
            "student": str(self.student.id),
            "amount": "10000",
            "status": "Paid",
        })

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "accountant", "page": "fees"}))
        payment = Payment.objects.get(institution=self.institution, fee=fee, student=self.student)
        self.assertEqual(str(payment.amount), "10000.00")
        self.assertEqual(payment.status, "Paid")
        self.assertEqual(payment.payment_method, "Manual")
        self.assertTrue(payment.reference)

        page = self.client.get(reverse("edu:secondary_page", kwargs={"role": "accountant", "page": "fees"}))
        self.assertContains(page, "₦10000.00")
        self.assertContains(page, "₦5000.00")
        self.assertContains(page, f"/edu/secondary/payments/{payment.reference}/receipt/")

        receipt = self.client.get(reverse("edu:secondary_payment_receipt", kwargs={"reference": payment.reference}))
        self.assertContains(receipt, payment.reference)
        self.assertContains(receipt, "Ada Student")
        self.assertContains(receipt, "First Term Tuition")

    @patch("edu.views.requests.get")
    def test_online_payment_verification_records_receipt(self, mock_get):
        self.institution.payment_public_key = "FLWPUBK_TEST"
        self.institution.payment_secret_key = "FLWSECK_TEST"
        self.institution.allow_online_payment = True
        self.institution.save(update_fields=["payment_public_key", "payment_secret_key", "allow_online_payment"])
        fee = Fee.objects.create(
            institution=self.institution,
            name="Exam Fee",
            amount="5000",
            session="2026/2027",
            term="First Term",
        )
        fee.classes.set([self.academic_class])

        mock_get.return_value.json.return_value = {
            "status": "success",
            "data": {
                "status": "successful",
                "amount": 5000,
                "currency": "NGN",
            },
        }

        response = self.client.post(reverse("edu:secondary_online_payment"), {
            "fee": str(fee.id),
            "student": str(self.student.id),
            "amount": "5000",
            "payment_reference": "123456789",
        })

        payment = Payment.objects.get(institution=self.institution, fee=fee, student=self.student)
        self.assertEqual(payment.payment_method, "Flutterwave")
        self.assertEqual(payment.gateway_reference, "123456789")
        self.assertRedirects(response, reverse("edu:secondary_payment_receipt", kwargs={"reference": payment.reference}))
