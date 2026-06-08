from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
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
    InstitutionDocumentVerification,
    Payment,
    Profile,
    Result,
    ResultSubmission,
    SalaryVoucher,
    Staff,
    Student,
    StudentClassHistory,
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

        self.assertContains(response, "Monthly Plan")
        self.assertContains(response, "NGN 250,000")
        self.assertContains(response, "Termly Plan")
        self.assertContains(response, "NGN 70,000")
        self.assertContains(response, "Standard 3-month cost: NGN 75,000")
        self.assertContains(response, "Termly discount: NGN 5,000")
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
            self.assertContains(response, "Subscription Plan")
            self.assertContains(response, "NGN 250,000")
            self.assertContains(response, "NGN 70,000")
            self.assertContains(response, "Submit & Pay")


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
            "cac_number": "RC123456",
            "tin_number": "TIN123456",
            "owner_id_number": "12345678901",
        }
        data.update(self._verification_files())

        response = self.client.post(reverse("edu:secondary_register"), data)

        institution = Institution.objects.get(name="Verified Pending Academy")
        self.assertRedirects(
            response,
            reverse("edu:secondary_registration_payment", kwargs={"school_code": institution.school_code}),
        )
        profile = Profile.objects.get(institution=institution, role="admin")
        self.assertEqual(institution.verification_status, "pending")
        self.assertEqual(institution.registration_payment_status, "pending")
        self.assertEqual(institution.subscription_billing_cycle, "termly")
        self.assertEqual(institution.registration_payment_amount, Decimal("70000.00"))
        self.assertEqual(profile.user.email, "admin@example.com")
        self.assertFalse(profile.is_approved)
        self.assertTrue(institution.cac_certificate)
        self.assertTrue(institution.owner_valid_id)
        documents = InstitutionDocumentVerification.objects.filter(institution=institution)
        self.assertEqual(documents.count(), 8)
        self.assertEqual(
            documents.get(document_type="cac_certificate").reference_value,
            "RC123456",
        )
        self.assertEqual(
            documents.get(document_type="tin_certificate").reference_value,
            "TIN123456",
        )
        self.assertEqual(
            documents.get(document_type="owner_valid_id").reference_value,
            "12345678901",
        )
        self.assertTrue(documents.filter(status="manual_review").exists())

    def test_secondary_registration_can_choose_monthly_subscription(self):
        data = {
            "institution_name": "Monthly Academy",
            "admin_full_name": "School Admin",
            "admin_password": "StrongPass123!",
            "admin_email": "monthly-admin@example.com",
            "admin_phone": "08000000002",
            "subscription_billing_cycle": "monthly",
        }
        data.update(self._verification_files())

        response = self.client.post(reverse("edu:secondary_register"), data)

        institution = Institution.objects.get(name="Monthly Academy")
        self.assertRedirects(
            response,
            reverse("edu:secondary_registration_payment", kwargs={"school_code": institution.school_code}),
        )
        self.assertEqual(institution.subscription_billing_cycle, "monthly")
        self.assertEqual(institution.registration_payment_amount, Decimal("250000.00"))

        payment_page = self.client.get(
            reverse("edu:secondary_registration_payment", kwargs={"school_code": institution.school_code})
        )
        self.assertContains(payment_page, "Monthly Plan")
        self.assertContains(payment_page, "NGN 250,000")

    @override_settings(EDU_CAC_VERIFICATION_URL="https://verify.example.test/cac")
    @patch("edu.verification.requests.post")
    def test_configured_cac_api_marks_document_api_verified(self, mock_post):
        mock_post.return_value.ok = True
        mock_post.return_value.content = b'{"verified": true}'
        mock_post.return_value.json.return_value = {"verified": True}

        data = {
            "institution_name": "API Verified Academy",
            "admin_full_name": "School Admin",
            "admin_password": "StrongPass123!",
            "admin_email": "api-admin@example.com",
            "admin_phone": "08000000001",
            "cac_number": "RC654321",
        }
        data.update(self._verification_files())

        response = self.client.post(reverse("edu:secondary_register"), data)

        institution = Institution.objects.get(name="API Verified Academy")
        self.assertRedirects(
            response,
            reverse("edu:secondary_registration_payment", kwargs={"school_code": institution.school_code}),
        )
        document = InstitutionDocumentVerification.objects.get(
            institution=institution,
            document_type="cac_certificate",
        )
        self.assertEqual(document.status, "api_verified")
        mock_post.assert_called()

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
        self.assertContains(response, "EduPortal subscription payment is required")
        self.assertFalse("_auth_user_id" in self.client.session)

        email_response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "admin@example.com",
            "password": "StrongPass123!",
        })
        self.assertEqual(email_response.status_code, 200)
        self.assertContains(email_response, "EduPortal subscription payment is required")

        phone_response = self.client.post(reverse("edu:secondary_login"), {
            "school_code": institution.school_code,
            "username": "08000000000",
            "password": "StrongPass123!",
        })
        self.assertEqual(phone_response.status_code, 200)
        self.assertContains(phone_response, "EduPortal subscription payment is required")

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
        profile.email_verified = True
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

    def test_accountant_creates_salary_voucher_for_admin_approval(self):
        staff = Staff.objects.create(
            institution=self.institution,
            full_name="Salary Teacher",
            staff_id="SAL/001",
            role="teacher",
        )

        response = self.client.post(reverse("edu:secondary_create_salary_voucher"), {
            "staff": str(staff.id),
            "bank_account_number": "0123456789",
            "bank_name": "Test Bank",
            "verified_account_name": "Salary Teacher",
            "salary_amount": "150000.00",
            "payment_date": timezone.localdate().isoformat(),
            "payment_frequency": "monthly",
            "payment_gateway": "flutterwave",
        })

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "accountant", "page": "salary-vouchers"}))
        voucher = SalaryVoucher.objects.get(institution=self.institution, staff=staff)
        self.assertEqual(voucher.status, "pending")
        self.assertEqual(voucher.account_verification_status, "manual_review")
        self.assertEqual(voucher.verified_account_name, "Salary Teacher")

    def test_admin_approves_salary_voucher(self):
        staff = Staff.objects.create(
            institution=self.institution,
            full_name="Approved Teacher",
            staff_id="SAL/002",
            role="teacher",
        )
        voucher = SalaryVoucher.objects.create(
            institution=self.institution,
            staff=staff,
            staff_name=staff.full_name,
            bank_account_number="0123456789",
            bank_name="Test Bank",
            verified_account_name=staff.full_name,
            salary_amount="120000.00",
            payment_date=timezone.localdate(),
            account_verification_status="manual_review",
            created_by=self.accountant,
        )
        admin = get_user_model().objects.create_user(
            username="salary-admin",
            password="StrongPass123!",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        admin.profile.institution = self.institution
        admin.profile.institution_type = "secondary"
        admin.profile.role = "admin"
        admin.profile.is_approved = True
        admin.profile.save()
        self.client.force_login(admin)

        response = self.client.post(reverse("edu:secondary_approve_salary_voucher", kwargs={"voucher_id": voucher.id}))

        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "admin", "page": "salary-vouchers"}))
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, "approved")
        self.assertEqual(voucher.approved_by, admin)

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
        self.assertEqual(submission.status, "submitted_to_examiner")

    def test_result_approval_workflow_publishes_student_report_card(self):
        session = AcademicSession.objects.create(institution=self.institution, name="2025/2026", is_current=True)
        term = AcademicTerm.objects.create(session=session, term="first", is_current=True)
        subject = Subject.objects.create(institution=self.institution, name="Mathematics", code="MTH")
        teacher_user = get_user_model().objects.create_user(username="math-teacher", password="StrongPass123!")
        teacher_user.profile.institution = self.institution
        teacher_user.profile.institution_type = "secondary"
        teacher_user.profile.role = "teacher"
        teacher_user.profile.is_approved = True
        teacher_user.profile.save()
        teacher = Staff.objects.create(institution=self.institution, user=teacher_user, full_name="Math Teacher", staff_id="MT/001", role="teacher")
        TeacherAssignment.objects.create(institution=self.institution, teacher=teacher, academic_class=self.academic_class)
        ClassSubject.objects.create(academic_class=self.academic_class, subject=subject)
        TeacherSubjectAssignment.objects.create(institution=self.institution, teacher=teacher, academic_class=self.academic_class, subject=subject)
        student_user = get_user_model().objects.create_user(username="workflow-student", password="StrongPass123!")
        student_user.profile.institution = self.institution
        student_user.profile.institution_type = "secondary"
        student_user.profile.role = "student"
        student_user.profile.is_approved = True
        student_user.profile.save()
        self.student.user = student_user
        self.student.save(update_fields=["user"])

        self.client.force_login(teacher_user)
        self.client.post(reverse("edu:secondary_save_scores"), {
            "academic_session": str(session.id),
            "academic_term": str(term.id),
            "academic_class": str(self.academic_class.id),
            "subject": str(subject.id),
            "students": [str(self.student.id)],
            f"test1_{self.student.id}": "10",
            f"test2_{self.student.id}": "10",
            f"assignment_{self.student.id}": "10",
            f"exam_{self.student.id}": "60",
        })
        submission = ResultSubmission.objects.get(submitted_by=teacher, subject=subject)
        self.assertEqual(submission.status, "draft")
        self.client.post(reverse("edu:secondary_submit_results"), {
            "academic_session": str(session.id),
            "academic_term": str(term.id),
            "academic_class": str(self.academic_class.id),
            "subject": str(subject.id),
            "teacher_comment": "Excellent work",
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, "submitted_to_examiner")

        self.client.force_login(student_user)
        response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": "results"}))
        self.assertContains(response, "Your result is not yet published.")
        self.assertNotContains(response, "90.00")

        examiner_user = get_user_model().objects.create_user(username="examiner", password="StrongPass123!")
        examiner_user.profile.institution = self.institution
        examiner_user.profile.institution_type = "secondary"
        examiner_user.profile.role = "examiner"
        examiner_user.profile.is_approved = True
        examiner_user.profile.save()
        self.client.force_login(examiner_user)
        review_page = self.client.get(
            reverse("edu:secondary_page", kwargs={"role": "examiner", "page": "review-results"})
            + f"?submission={submission.id}"
        )
        self.assertContains(review_page, "Review Results")
        self.assertContains(review_page, "Report Card Template Preview")
        self.assertContains(review_page, "Report Card Preview")
        self.assertContains(review_page, "Ada Student")
        self.assertContains(review_page, "90.00")
        self.client.post(reverse("edu:secondary_review_results"), {
            "submission_id": str(submission.id),
            "examiner_comment": "Checked",
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, "approved_by_examiner")

        admin_user = get_user_model().objects.create_user(username="result-admin", password="StrongPass123!")
        admin_user.profile.institution = self.institution
        admin_user.profile.institution_type = "secondary"
        admin_user.profile.role = "admin"
        admin_user.profile.is_approved = True
        admin_user.profile.save()
        self.client.force_login(admin_user)
        admin_review_page = self.client.get(
            reverse("edu:secondary_page", kwargs={"role": "admin", "page": "approve-results"})
            + f"?submission={submission.id}"
        )
        self.assertContains(admin_review_page, "Review Before Publishing")
        self.assertContains(admin_review_page, "Report Card Template Preview")
        self.assertContains(admin_review_page, "Report Card Preview")
        self.assertContains(admin_review_page, "Ada Student")
        self.assertContains(admin_review_page, "90.00")
        self.assertContains(admin_review_page, "Checked")
        self.client.post(reverse("edu:secondary_admin_result_approval"), {
            "submission_id": str(submission.id),
            "admin_comment": "Published",
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, "published")
        self.assertIsNotNone(submission.published_at)

        self.client.force_login(student_user)
        response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": "results"}))
        self.assertContains(response, "Student Report Card")
        self.assertContains(response, "90.00")
        self.assertContains(response, "Excellent work")

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
            "subjects-student": ["My Classes", "JSS1", "English Language"],
            "test-scores": ["My Test Scores", "English Language", "8.00"],
            "results": ["My Results", "Your result is not yet published."],
            "pay-fees": ["My School Fees", "First Term Fee", "Receipt", "Paid"],
            "profile": ["Ada Student", "Fees Academy", self.student.student_id],
        }
        for page, texts in expectations.items():
            response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": page}))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Coming Soon")
            for text in texts:
                self.assertContains(response, text)

        response = self.client.post(reverse("edu:secondary_student_profile_update"), {
            "email": "updated-student@example.com",
            "phone": "08012345678",
            "home_address": "12 Student Street",
            "next_of_kin_name": "Parent One",
            "next_of_kin_phone": "08087654321",
            "next_of_kin_relationship": "Mother",
        })
        self.assertRedirects(response, reverse("edu:secondary_page", kwargs={"role": "student", "page": "profile"}))
        student_user.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(student_user.email, "updated-student@example.com")
        self.assertEqual(student_user.phone, "08012345678")
        self.assertEqual(student_user.address, "12 Student Street")
        self.assertEqual(self.student.next_of_kin_name, "Parent One")
        self.assertEqual(self.student.student_id, "FA/2026/001")

    def test_student_my_classes_shows_previous_class_report_card(self):
        previous_class = AcademicClass.objects.create(institution=self.institution, name="Primary 6", level=6)
        previous_session = AcademicSession.objects.create(institution=self.institution, name="2024/2025")
        previous_term = AcademicTerm.objects.create(session=previous_session, term="third")
        current_session = AcademicSession.objects.create(institution=self.institution, name="2025/2026")
        current_term = AcademicTerm.objects.create(session=current_session, term="first")
        self.academic_class.academic_session = current_session
        self.academic_class.academic_term = current_term
        self.academic_class.save(update_fields=["academic_session", "academic_term"])
        student_user = get_user_model().objects.create_user(username="history-student", password="StrongPass123!")
        student_user.profile.institution = self.institution
        student_user.profile.institution_type = "secondary"
        student_user.profile.role = "student"
        student_user.profile.is_approved = True
        student_user.profile.save()
        self.student.user = student_user
        self.student.save(update_fields=["user"])
        StudentClassHistory.objects.create(
            student=self.student,
            academic_class=previous_class,
            academic_session=previous_session,
            academic_term=previous_term,
        )
        subject = Subject.objects.create(institution=self.institution, name="Basic Science", code="BSC")
        ClassSubject.objects.create(academic_class=previous_class, subject=subject)
        teacher = Staff.objects.create(institution=self.institution, full_name="Science Teacher", staff_id="SCI/001", role="teacher")
        Result.objects.create(
            institution=self.institution,
            student=self.student,
            academic_class=previous_class,
            subject=subject,
            teacher=teacher,
            academic_session=previous_session,
            academic_term=previous_term,
            session=previous_session.name,
            term=previous_term.get_term_display(),
            test1="10",
            test2="10",
            assignment="10",
            exam="60",
        )
        ResultSubmission.objects.create(
            institution=self.institution,
            academic_class=previous_class,
            subject=subject,
            submitted_by=teacher,
            academic_session=previous_session,
            academic_term=previous_term,
            session=previous_session.name,
            term=previous_term.get_term_display(),
            status="published",
            teacher_comment="Promoted",
            examiner_comment="Checked",
            admin_comment="Approved",
            published_at=timezone.now(),
        )
        self.client.force_login(student_user)

        class_key = f"{previous_class.id}-{previous_session.id}-{previous_term.id}"
        response = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": "subjects-student"}) + f"?class_key={class_key}")

        self.assertContains(response, "My Classes")
        self.assertContains(response, "Primary 6")
        self.assertContains(response, "Current Class")
        self.assertContains(response, "Basic Science")
        self.assertContains(response, "90.00")
        self.assertContains(response, "Promoted")

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

    @patch("edu.views.requests.get")
    def test_student_can_pay_assigned_fee_online_from_portal(self, mock_get):
        self.institution.payment_public_key = "FLWPUBK_TEST"
        self.institution.payment_secret_key = "FLWSECK_TEST"
        self.institution.allow_online_payment = True
        self.institution.save(update_fields=["payment_public_key", "payment_secret_key", "allow_online_payment"])
        student_user = get_user_model().objects.create_user(
            username="student-pay",
            password="StrongPass123!",
            email="student-pay@example.com",
        )
        student_user.profile.institution = self.institution
        student_user.profile.institution_type = "secondary"
        student_user.profile.role = "student"
        student_user.profile.is_approved = True
        student_user.profile.save()
        self.student.user = student_user
        self.student.save(update_fields=["user"])
        fee = Fee.objects.create(
            institution=self.institution,
            name="Second Term Fee",
            amount="15000",
            session="2026/2027",
            term="Second Term",
        )
        fee.classes.set([self.academic_class])
        mock_get.return_value.json.return_value = {
            "status": "success",
            "data": {
                "status": "successful",
                "amount": 15000,
                "currency": "NGN",
            },
        }
        self.client.force_login(student_user)

        page = self.client.get(reverse("edu:secondary_page", kwargs={"role": "student", "page": "pay-fees"}))
        self.assertContains(page, "Second Term Fee")
        self.assertContains(page, "Pay Now")

        response = self.client.post(reverse("edu:secondary_student_online_payment"), {
            "fee": str(fee.id),
            "amount": "15000",
            "payment_reference": "987654321",
        })

        payment = Payment.objects.get(institution=self.institution, fee=fee, student=self.student)
        self.assertEqual(payment.status, "Paid")
        self.assertEqual(payment.payment_method, "Flutterwave")
        self.assertEqual(payment.gateway_reference, "987654321")
        self.assertRedirects(response, reverse("edu:secondary_payment_receipt", kwargs={"reference": payment.reference}))
