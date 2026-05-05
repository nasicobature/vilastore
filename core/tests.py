from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


class MobileOwnerLoginTests(TestCase):
    def setUp(self):
        self.password = "TestPass123!"
        self.shared_email = "owner@example.com"
        future_date = timezone.localdate() + timedelta(days=30)

        self.shop_owner = User.objects.create_user(
            username="shop-owner",
            email=self.shared_email,
            password=self.password,
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Shop Owner",
            business_type="Retail",
            state="Lagos",
            phone="08000000001",
            address="1 Market Road",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )
        self.housing_owner = User.objects.create_user(
            username="housing-owner",
            email=self.shared_email,
            password=self.password,
            account_type=User.ACCOUNT_TYPE_HOUSING,
            business_name="Housing Owner",
            business_type="Real Estate",
            state="Abuja",
            phone="08000000002",
            address="2 Estate Avenue",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )

    def test_mobile_owner_login_requires_account_type_when_credentials_match_multiple_accounts(self):
        response = self.client.post(
            reverse("api_mobile_auth_login"),
            data={
                "role": "owner",
                "identifier": self.shared_email,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["code"], "account_type_required")
        self.assertEqual(
            {option["value"] for option in data["account_type_options"]},
            {User.ACCOUNT_TYPE_SHOP, User.ACCOUNT_TYPE_HOUSING},
        )

    def test_mobile_owner_login_accepts_account_type_to_select_workspace(self):
        response = self.client.post(
            reverse("api_mobile_auth_login"),
            data={
                "role": "owner",
                "identifier": self.shared_email,
                "password": self.password,
                "account_type": User.ACCOUNT_TYPE_HOUSING,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["profile"]["id"], self.housing_owner.id)
        self.assertEqual(data["profile"]["account_type"], User.ACCOUNT_TYPE_HOUSING)


class WebLoginPortalSelectionTests(TestCase):
    def setUp(self):
        self.password = "TestPass123!"
        self.shared_email = "shared-owner@example.com"
        future_date = timezone.localdate() + timedelta(days=30)

        self.shop_owner = User.objects.create_user(
            username="web-shop-owner",
            email=self.shared_email,
            password=self.password,
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Shop Owner",
            business_type="Retail",
            state="Lagos",
            phone="08000000101",
            address="1 Market Road",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )
        self.housing_owner = User.objects.create_user(
            username="web-housing-owner",
            email=self.shared_email,
            password=self.password,
            account_type=User.ACCOUNT_TYPE_HOUSING,
            business_name="Housing Owner",
            business_type="Real Estate",
            state="Abuja",
            phone="08000000102",
            address="2 Estate Avenue",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )

    def test_web_login_requires_portal_choice_when_identifier_matches_multiple_portals(self):
        response = self.client.post(
            reverse("login"),
            data={
                "email": self.shared_email,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose the portal you want to enter before we sign you in.")
        self.assertContains(response, "Shop Portal")
        self.assertContains(response, "Housing Portal")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_web_login_honors_selected_portal(self):
        response = self.client.post(
            reverse("login"),
            data={
                "email": self.shared_email,
                "password": self.password,
                "account_type": User.ACCOUNT_TYPE_HOUSING,
            },
        )

        self.assertRedirects(response, reverse("housing_management"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.housing_owner.id)
