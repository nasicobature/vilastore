from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import Institution, Profile


class EduPortalRoutingTests(TestCase):
    def test_index_links_use_edu_prefixed_routes(self):
        response = self.client.get(reverse("edu:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/edu/secondary/login/"')
        self.assertContains(response, 'href="/edu/tertiary/login/"')
        self.assertNotContains(response, 'href="/secondary/login/"')
        self.assertNotContains(response, 'href="/tertiary/login/"')

    def test_edu_login_pages_exist(self):
        secondary = self.client.get(reverse("edu:secondary_login"))
        tertiary = self.client.get(reverse("edu:tertiary_login"))

        self.assertEqual(secondary.status_code, 200)
        self.assertEqual(tertiary.status_code, 200)


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
        self.assertFalse(profile.is_approved)
        self.assertTrue(institution.cac_certificate)
        self.assertTrue(institution.owner_valid_id)
