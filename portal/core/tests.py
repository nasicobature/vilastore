from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Institution


@override_settings(
    ALLOWED_HOSTS=[".vilastore.store"],
    SCHOOL_PORTAL_ROOT_DOMAINS=["vilastore.store"],
)
class SchoolSubdomainTests(TestCase):
    def test_school_subdomain_redirects_to_matching_login(self):
        Institution.objects.create(
            name="Demo Secondary School",
            school_code="DEMO",
            short_name="demo",
            institution_type="secondary",
        )

        response = self.client.get("/", HTTP_HOST="demo.vilastore.store")

        self.assertRedirects(
            response,
            reverse("secondary_login"),
            fetch_redirect_response=False,
        )

    def test_subdomain_login_uses_school_code_context(self):
        Institution.objects.create(
            name="Demo Secondary School",
            school_code="DEMO",
            short_name="demo",
            institution_type="secondary",
        )

        response = self.client.get(reverse("secondary_login"), HTTP_HOST="demo.vilastore.store")

        self.assertContains(response, "Demo Secondary School")
        self.assertContains(response, 'name="school_code" value="DEMO"')
        self.assertNotContains(response, 'placeholder="e.g. FGGC"')
