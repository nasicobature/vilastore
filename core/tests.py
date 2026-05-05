from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Product, Sale, SaleItem, ShopBranch, User


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


class ShopOwnerDashboardTests(TestCase):
    def test_login_creates_default_branch_for_shop_owner_without_branch(self):
        password = "TestPass123!"
        future_date = timezone.localdate() + timedelta(days=30)
        owner = User.objects.create_user(
            username="branchless-owner",
            email="branchless@example.com",
            password=password,
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Branchless Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000000901",
            address="9 Market Road",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )

        response = self.client.post(
            reverse("login"),
            data={
                "email": owner.email,
                "password": password,
            },
        )

        self.assertRedirects(response, reverse("index"))
        dashboard_response = self.client.get(reverse("index"))
        self.assertEqual(dashboard_response.status_code, 200)
        branch = ShopBranch.objects.get(user=owner)
        self.assertEqual(branch.address, owner.address)

    def test_sales_history_defaults_to_all_branches_so_old_unassigned_sales_show(self):
        password = "TestPass123!"
        future_date = timezone.localdate() + timedelta(days=30)
        owner = User.objects.create_user(
            username="history-owner",
            email="history@example.com",
            password=password,
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="History Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000000902",
            address="10 Market Road",
            country="Nigeria",
            plan="basic",
            subscription_active_until=future_date,
        )
        branch = ShopBranch.objects.create(
            user=owner,
            name="Main Branch",
            address=owner.address,
            is_default=True,
        )
        product = Product.objects.create(
            user=owner,
            name="Old Sale Product",
            cost_price=Decimal("50.00"),
            selling_price=Decimal("100.00"),
            stock=Decimal("5.00"),
        )
        sale = Sale.objects.create(
            user=owner,
            total_amount=Decimal("100.00"),
            total_profit=Decimal("50.00"),
            amount_paid=Decimal("100.00"),
            branch=None,
        )
        SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=Decimal("1.00"),
            price=Decimal("100.00"),
            profit=Decimal("50.00"),
        )

        self.client.force_login(owner)
        session = self.client.session
        session["owner_selected_branch_id"] = str(branch.id)
        session.save()

        response = self.client.get(reverse("sales-history"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_transactions"], 1)
        self.assertIsNone(response.context["selected_branch"])
        self.assertContains(response, "Old Sale Product")
