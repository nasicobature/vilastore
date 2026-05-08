from django.test import TestCase
from django.urls import reverse


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
