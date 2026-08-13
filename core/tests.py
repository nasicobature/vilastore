from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuthToken, BranchInventory, Category, Customer, CustomerScanCart, Product, Sale, SaleItem, ShopBranch, ShopBoy, User


@override_settings(FLUTTERWAVE_SECRET_KEY="FLWSECK_TEST-demo", FLUTTERWAVE_PUBLIC_KEY="FLWPUBK_TEST-demo")
class SubscriptionPaymentGatewayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="payment-owner",
            email="payment@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Payment Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000001000",
            address="10 Payment Road",
            country="Nigeria",
            plan="starter",
            is_paid=False,
            subscription_active_until=None,
        )
        session = self.client.session
        session["pending_payment_user_id"] = self.user.id
        session.save()

    def _flutterwave_success_response(self, amount="4000.00", email="payment@example.com"):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "status": "success",
            "data": {
                "status": "successful",
                "amount": amount,
                "currency": "NGN",
                "customer": {"email": email},
            },
        }
        return response

    @patch("core.views.requests.get")
    def test_subscription_payment_verifies_flutterwave_transaction_id(self, mock_get):
        mock_get.return_value = self._flutterwave_success_response()

        response = self.client.post(
            reverse("subscription_payment"),
            data={"payment_reference": "123456789"},
        )

        self.assertEqual(response.status_code, 302)
        mock_get.assert_called_once()
        self.assertIn("/transactions/123456789/verify", mock_get.call_args.args[0])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paid)
        self.assertIsNotNone(self.user.subscription_active_until)

    @patch("core.views.requests.get")
    def test_subscription_payment_verifies_flutterwave_tx_ref(self, mock_get):
        mock_get.return_value = self._flutterwave_success_response()

        response = self.client.post(
            reverse("subscription_payment"),
            data={"payment_reference": "VILASTORE-TEST-REF"},
        )

        self.assertEqual(response.status_code, 302)
        mock_get.assert_called_once()
        self.assertIn("/transactions/verify_by_reference", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["params"], {"tx_ref": "VILASTORE-TEST-REF"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paid)

    def test_subscription_upgrade_rejects_same_or_lower_plan(self):
        self.user.plan = "growth"
        self.user.is_paid = True
        self.user.subscription_active_until = timezone.localdate() + timedelta(days=14)
        self.user.save(update_fields=["plan", "is_paid", "subscription_active_until"])
        self.client.force_login(self.user)

        response = self.client.post(reverse("start_subscription_upgrade"), data={"plan": "starter"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("settings"))
        self.assertNotIn("subscription_upgrade_plan", self.client.session)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)

    @patch("core.views.requests.get")
    def test_subscription_upgrade_payment_updates_plan_and_unlocks_features(self, mock_get):
        self.user.is_paid = True
        self.user.subscription_active_until = timezone.localdate() + timedelta(days=14)
        self.user.save(update_fields=["is_paid", "subscription_active_until"])
        self.client.force_login(self.user)

        start_response = self.client.post(reverse("start_subscription_upgrade"), data={"plan": "business"})
        self.assertEqual(start_response.status_code, 302)
        self.assertEqual(start_response.url, reverse("subscription_payment"))
        self.assertEqual(self.client.session["subscription_upgrade_plan"], "business")
        payment_page = self.client.get(reverse("subscription_payment"))
        self.assertContains(payment_page, "Upgrade Subscription")

        mock_get.return_value = self._flutterwave_success_response(amount="15000.00")
        response = self.client.post(
            reverse("subscription_payment"),
            data={"payment_reference": "VILASTORE-UPGRADE-REF"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.plan, "business")
        self.assertEqual(self.user.monthly_fee, Decimal("15000.00"))
        self.assertTrue(self.user.is_paid)
        self.assertNotIn("subscription_upgrade_plan", self.client.session)


class BranchSelectionScopeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="branch-owner",
            email="branch@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Branch Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000002000",
            address="20 Branch Road",
            country="Nigeria",
            plan="business",
            is_paid=True,
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        self.branch_a = ShopBranch.objects.create(user=self.user, name="Main Branch", address="A", is_default=True)
        self.branch_b = ShopBranch.objects.create(user=self.user, name="Second Branch", address="B")
        self.sale_a = Sale.objects.create(
            user=self.user,
            branch=self.branch_a,
            total_amount=Decimal("1000.00"),
            total_profit=Decimal("200.00"),
        )
        self.sale_b = Sale.objects.create(
            user=self.user,
            branch=self.branch_b,
            total_amount=Decimal("2500.00"),
            total_profit=Decimal("500.00"),
        )
        self.customer_a = Customer.objects.create(
            user=self.user,
            branch=self.branch_a,
            first_name="Main",
            last_name="Customer",
            phone="08000002001",
        )
        self.customer_b = Customer.objects.create(
            user=self.user,
            branch=self.branch_b,
            first_name="Second",
            last_name="Customer",
            phone="08000002002",
        )
        self.category_a = Category.objects.create(user=self.user, branch=self.branch_a, name="Main Category")
        self.category_b = Category.objects.create(user=self.user, branch=self.branch_b, name="Second Category")
        self.overall_category = Category.objects.create(user=self.user, name="Overall Category")
        self.product_a = Product.objects.create(
            user=self.user,
            category=self.category_a,
            name="Main Branch Product",
            cost_price=Decimal("500.00"),
            selling_price=Decimal("700.00"),
            stock=Decimal("10.00"),
        )
        self.product_b = Product.objects.create(
            user=self.user,
            category=self.category_b,
            name="Second Branch Product",
            cost_price=Decimal("800.00"),
            selling_price=Decimal("1200.00"),
            stock=Decimal("5.00"),
        )
        self.unassigned_product = Product.objects.create(
            user=self.user,
            name="Unassigned Product",
            cost_price=Decimal("300.00"),
            selling_price=Decimal("450.00"),
            stock=Decimal("7.00"),
        )
        BranchInventory.objects.create(
            branch=self.branch_a,
            product=self.product_a,
            stock=Decimal("10.00"),
            selling_price=Decimal("700.00"),
        )
        BranchInventory.objects.create(
            branch=self.branch_b,
            product=self.product_b,
            stock=Decimal("5.00"),
            selling_price=Decimal("1200.00"),
        )
        self.client.force_login(self.user)

    def test_selected_branch_persists_to_sales_history(self):
        self.client.get(reverse("index"), data={"branch": str(self.branch_b.id)})

        response = self.client.get(reverse("sales-history"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertEqual(list(response.context["sales"]), [self.sale_b])

    def test_selected_branch_filters_customer_records(self):
        self.client.get(reverse("customer"), data={"branch": str(self.branch_b.id)})

        response = self.client.get(reverse("customer"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertContains(response, "Second Customer")
        self.assertNotContains(response, "Main Customer")

    def test_selected_branch_filters_inventory_products(self):
        self.client.get(reverse("inventory"), data={"branch": str(self.branch_b.id)})

        response = self.client.get(reverse("inventory"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertEqual(list(response.context["products"]), [self.product_b])
        self.assertContains(response, "Second Branch Product")
        self.assertNotContains(response, "Main Branch Product")
        self.assertNotContains(response, "Unassigned Product")
        self.assertEqual(list(response.context["categories"]), [self.category_b])
        self.assertContains(response, "Second Category")
        self.assertNotContains(response, "Main Category")
        self.assertNotContains(response, "Overall Category")

    def test_selected_branch_includes_products_assigned_by_branch_category(self):
        category_only_product = Product.objects.create(
            user=self.user,
            category=self.category_b,
            name="Second Branch Category Only Product",
            cost_price=Decimal("200.00"),
            selling_price=Decimal("350.00"),
            stock=Decimal("3.00"),
        )

        response = self.client.get(reverse("inventory"), data={"branch": str(self.branch_b.id)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertIn(category_only_product, list(response.context["products"]))
        self.assertContains(response, "Second Branch Category Only Product")

    def test_product_branch_switch_ignores_category_from_other_branch(self):
        response = self.client.get(
            reverse("product"),
            data={"branch": str(self.branch_b.id), "category": str(self.category_a.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertEqual(response.context["selected_category"], "")
        self.assertContains(response, "Second Branch Product")
        self.assertNotContains(response, "Main Branch Product")

    def test_product_page_has_all_branches_filter(self):
        response = self.client.get(reverse("product"), data={"branch": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_branch"])
        self.assertContains(response, '<option value="all" selected>All branches</option>', html=True)
        self.assertContains(response, "Main Branch Product")
        self.assertContains(response, "Second Branch Product")

    def test_checkout_completes_sale_for_selected_branch(self):
        self.client.get(reverse("product"), data={"branch": str(self.branch_b.id)})
        session = self.client.session
        session["cart"] = {
            str(self.product_b.id): {
                "name": self.product_b.name,
                "price": float(self.product_b.selling_price),
                "cost": float(self.product_b.cost_price),
                "quantity": "1",
            }
        }
        session["owner_cart_branch_id"] = str(self.branch_b.id)
        session.save()

        response = self.client.post(reverse("checkout"), data={"payment_status": Sale.PAYMENT_PAID})

        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.filter(user=self.user, branch=self.branch_b).latest("id")
        self.assertEqual(sale.total_amount, Decimal("1200.00"))
        self.assertEqual(sale.payment_status, Sale.PAYMENT_PAID)
        inventory = BranchInventory.objects.get(branch=self.branch_b, product=self.product_b)
        self.assertEqual(inventory.stock, Decimal("4.00"))
        self.assertEqual(self.client.session.get("cart"), {})

    def test_checkout_handles_high_value_sale_without_server_error(self):
        self.product_b.selling_price = Decimal("100000000.00")
        self.product_b.cost_price = Decimal("70000000.00")
        self.product_b.save(update_fields=["selling_price", "cost_price"])
        BranchInventory.objects.filter(branch=self.branch_b, product=self.product_b).update(
            stock=Decimal("5.00"),
            selling_price=Decimal("100000000.00"),
        )
        self.client.get(reverse("product"), data={"branch": str(self.branch_b.id)})
        session = self.client.session
        session["cart"] = {
            str(self.product_b.id): {
                "name": self.product_b.name,
                "price": "100000000.00",
                "cost": "70000000.00",
                "quantity": "2",
            }
        }
        session["owner_cart_branch_id"] = str(self.branch_b.id)
        session.save()

        response = self.client.post(reverse("checkout"), data={"payment_status": Sale.PAYMENT_PAID})

        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.filter(user=self.user, branch=self.branch_b).latest("id")
        self.assertEqual(sale.total_amount, Decimal("200000000.00"))
        self.assertEqual(sale.total_profit, Decimal("60000000.00"))

    def test_mobile_checkout_completes_sale_for_selected_branch(self):
        token = AuthToken.objects.create(
            token="branch-checkout-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.user,
            expires_at=timezone.now() + timedelta(days=30),
        )
        from .api import _get_owner_cart

        cart = _get_owner_cart(token)
        cart.data = {
            str(self.product_b.id): {
                "name": self.product_b.name,
                "price": str(self.product_b.selling_price),
                "cost": str(self.product_b.cost_price),
                "quantity": "1",
            }
        }
        cart.save(update_fields=["data", "updated_at"])

        response = self.client.post(
            reverse("api_owner_cart_checkout"),
            data={
                "payment_status": Sale.PAYMENT_PAID,
                "branch_id": str(self.branch_b.id),
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer branch-checkout-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        sale = Sale.objects.filter(user=self.user, branch=self.branch_b).latest("id")
        self.assertEqual(sale.total_amount, Decimal("1200.00"))
        inventory = BranchInventory.objects.get(branch=self.branch_b, product=self.product_b)
        self.assertEqual(inventory.stock, Decimal("4.00"))

    def test_mobile_checkout_accepts_all_branch_marker(self):
        token = AuthToken.objects.create(
            token="branch-checkout-all-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.user,
            expires_at=timezone.now() + timedelta(days=30),
        )
        from .api import _get_owner_cart

        cart = _get_owner_cart(token)
        cart.data = {
            str(self.unassigned_product.id): {
                "name": self.unassigned_product.name,
                "price": str(self.unassigned_product.selling_price),
                "cost": str(self.unassigned_product.cost_price),
                "quantity": "1",
            }
        }
        cart.save(update_fields=["data", "updated_at"])

        response = self.client.post(
            reverse("api_owner_cart_checkout"),
            data={"payment_status": Sale.PAYMENT_PAID, "branch_id": "all"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer branch-checkout-all-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        sale = Sale.objects.filter(user=self.user, branch__isnull=True).latest("id")
        self.assertEqual(sale.total_amount, Decimal("450.00"))

    def test_default_branch_does_not_show_unassigned_inventory(self):
        self.client.get(reverse("inventory"), data={"branch": str(self.branch_a.id)})

        response = self.client.get(reverse("inventory"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_a)
        self.assertEqual(list(response.context["products"]), [self.product_a])
        self.assertContains(response, "Main Branch Product")
        self.assertNotContains(response, "Unassigned Product")

    def test_overall_inventory_still_shows_all_products(self):
        response = self.client.get(reverse("inventory"), data={"branch": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_branch"])
        product_names = [product.name for product in response.context["products"]]
        self.assertEqual(
            product_names,
            ["Main Branch Product", "Second Branch Product", "Unassigned Product"],
        )

    def test_add_product_in_selected_branch_creates_branch_inventory(self):
        self.client.get(reverse("inventory"), data={"branch": str(self.branch_b.id)})

        response = self.client.post(
            reverse("add_product"),
            data={
                "name": "Branch B New Product",
                "category": str(self.category_b.id),
                "cost_price": "100.00",
                "selling_price": "150.00",
                "stock": "4",
                "low_stock_threshold": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(user=self.user, name="Branch B New Product")
        self.assertEqual(product.category, self.category_b)
        inventory = BranchInventory.objects.get(branch=self.branch_b, product=product)
        self.assertEqual(inventory.stock, Decimal("4.00"))

    def test_add_category_in_selected_branch_stays_in_that_branch(self):
        self.client.get(reverse("inventory"), data={"branch": str(self.branch_b.id)})

        response = self.client.post(reverse("add_category"), data={"name": "Branch B Only"})

        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(user=self.user, name="Branch B Only")
        self.assertEqual(category.branch, self.branch_b)

    def test_selected_branch_filters_dashboard_product_counts(self):
        self.client.get(reverse("index"), data={"branch": str(self.branch_b.id)})

        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_b)
        self.assertEqual(response.context["total_products"], 1)

    def test_mobile_inventory_respects_selected_branch(self):
        AuthToken.objects.create(
            token="branch-mobile-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.user,
            expires_at=timezone.now() + timedelta(days=30),
        )

        response = self.client.get(
            reverse("api_owner_inventory"),
            data={"branch_id": str(self.branch_b.id)},
            HTTP_AUTHORIZATION="Bearer branch-mobile-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        product_names = [product["name"] for product in data["products"]]
        self.assertEqual(product_names, ["Second Branch Product"])


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


class SubscriptionEntitlementTests(TestCase):
    def setUp(self):
        self.password = "TestPass123!"
        self.future_date = timezone.localdate() + timedelta(days=30)
        self.owner = User.objects.create_user(
            username="starter-owner",
            email="starter@example.com",
            password=self.password,
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Starter Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000002001",
            address="20 Market Road",
            country="Nigeria",
            plan="starter",
            subscription_active_until=self.future_date,
        )
        ShopBranch.objects.create(user=self.owner, name="Main Branch", address=self.owner.address, is_default=True)

    def test_starter_cannot_use_barcode_generation(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("generate_product_code"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])

    def test_business_can_use_barcode_generation(self):
        self.owner.plan = "business"
        self.owner.save(update_fields=["plan"])
        self.client.force_login(self.owner)
        response = self.client.get(reverse("generate_product_code"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(response.json()["code"])

    def test_starter_cannot_add_shopboy(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("add_shopboy"),
            data={"full_name": "Staff One", "username": "staffone", "password": "Pass123!"},
            follow=True,
        )

        self.assertEqual(ShopBoy.objects.filter(user=self.owner).count(), 0)
        self.assertContains(response, "staff")

    def test_growth_allows_customer_profile_details(self):
        self.owner.plan = "growth"
        self.owner.save(update_fields=["plan"])
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("add_customer"),
            data={
                "first_name": "Amina",
                "last_name": "Bello",
                "phone": "08030000000",
                "email": "amina@example.com",
                "religion": "muslim",
            },
        )

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(user=self.owner)
        self.assertEqual(customer.email, "amina@example.com")

    def test_growth_can_add_second_branch_but_not_third(self):
        self.owner.plan = "growth"
        self.owner.save(update_fields=["plan"])
        self.client.force_login(self.owner)

        second_response = self.client.post(
            reverse("add_branch"),
            data={"name": "Second Branch", "address": "22 Market Road"},
        )

        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(ShopBranch.objects.filter(user=self.owner, is_active=True).count(), 2)

        third_response = self.client.post(
            reverse("add_branch"),
            data={"name": "Third Branch", "address": "33 Market Road"},
            follow=True,
        )

        self.assertEqual(ShopBranch.objects.filter(user=self.owner, is_active=True).count(), 2)
        self.assertContains(third_response, "Growth plan has reached its branch limit")

    def test_starter_blocks_customer_profile_details(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("add_customer"),
            data={
                "first_name": "Amina",
                "last_name": "Bello",
                "phone": "08030000000",
                "email": "amina@example.com",
            },
            follow=True,
        )

        self.assertEqual(Customer.objects.filter(user=self.owner).count(), 0)
        self.assertContains(response, "Full customer management")

    def test_starter_cannot_use_mobile_ai_business_analysis(self):
        AuthToken.objects.create(
            token="starter-ai-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.owner,
            expires_at=timezone.now() + timedelta(days=30),
        )

        response = self.client.get(
            reverse("api_owner_ai_summary"),
            HTTP_AUTHORIZATION="Bearer starter-ai-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["upgrade_required"])
        self.assertEqual(response.json()["feature"], "ai_business_analysis")

    def test_business_can_use_mobile_ai_business_analysis(self):
        self.owner.plan = "business"
        self.owner.save(update_fields=["plan"])
        AuthToken.objects.create(
            token="business-ai-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.owner,
            expires_at=timezone.now() + timedelta(days=30),
        )

        response = self.client.get(
            reverse("api_owner_ai_summary"),
            HTTP_AUTHORIZATION="Bearer business-ai-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("ai", response.json())


class OwnerInventoryApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="inventory-owner",
            email="inventory@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Inventory Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000004001",
            address="40 Market Road",
            country="Nigeria",
            plan="business",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        self.token = AuthToken.objects.create(
            token="inventory-token",
            role=AuthToken.ROLE_OWNER,
            owner=self.owner,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.product = Product.objects.create(
            user=self.owner,
            name="Old Rice",
            cost_price=Decimal("100.00"),
            selling_price=Decimal("150.00"),
            stock=Decimal("2.00"),
            low_stock_threshold=5,
        )

    def test_mobile_product_update_changes_inventory_values(self):
        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "name": "Premium Rice",
                "stock": "12",
                "low_stock_threshold": "3",
                "cost_price": "120.00",
                "selling_price": "180.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Premium Rice")
        self.assertEqual(self.product.stock, Decimal("12.00"))
        self.assertEqual(self.product.low_stock_threshold, 3)
        self.assertEqual(self.product.cost_price, Decimal("120.00"))
        self.assertEqual(self.product.selling_price, Decimal("180.00"))

        inventory = self.client.get(
            reverse("api_owner_inventory"),
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )
        self.assertEqual(inventory.status_code, 200)
        item = inventory.json()["products"][0]
        self.assertEqual(item["name"], "Premium Rice")
        self.assertEqual(item["stock"], "12.00")
        self.assertEqual(item["selling_price"], "180.00")

    def test_starter_can_update_product_when_existing_code_is_unchanged(self):
        self.owner.plan = "starter"
        self.owner.save(update_fields=["plan"])
        self.product.code = "RICE001"
        self.product.save(update_fields=["code"])

        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "name": "Starter Rice",
                "code": "RICE001",
                "stock": "7",
                "low_stock_threshold": "2",
                "cost_price": "110.00",
                "selling_price": "170.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Starter Rice")
        self.assertEqual(self.product.code, "RICE001")
        self.assertEqual(self.product.stock, Decimal("7.00"))

    def test_starter_update_preserves_existing_code_when_code_is_blank(self):
        self.owner.plan = "starter"
        self.owner.save(update_fields=["plan"])
        self.product.code = "RICE001"
        self.product.save(update_fields=["code"])

        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "name": "Starter Rice Blank Code",
                "code": "",
                "stock": "8",
                "low_stock_threshold": "2",
                "cost_price": "111.00",
                "selling_price": "171.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Starter Rice Blank Code")
        self.assertEqual(self.product.code, "RICE001")
        self.assertEqual(self.product.stock, Decimal("8.00"))

    def test_starter_can_update_product_when_only_default_branch_id_is_sent(self):
        self.owner.plan = "starter"
        self.owner.save(update_fields=["plan"])
        branch = ShopBranch.objects.create(
            user=self.owner,
            name="Main Shop",
            address="40 Market Road",
            is_default=True,
        )

        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "branch_id": str(branch.id),
                "name": "Starter Default Branch Rice",
                "stock": "10",
                "low_stock_threshold": "2",
                "cost_price": "115.00",
                "selling_price": "175.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Starter Default Branch Rice")
        self.assertEqual(self.product.stock, Decimal("10.00"))
        self.assertFalse(BranchInventory.objects.filter(branch=branch, product=self.product).exists())

    def test_starter_cannot_change_product_code(self):
        self.owner.plan = "starter"
        self.owner.save(update_fields=["plan"])
        self.product.code = "RICE001"
        self.product.save(update_fields=["code"])

        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "name": "Old Rice",
                "code": "RICE002",
                "stock": "2",
                "low_stock_threshold": "5",
                "cost_price": "100.00",
                "selling_price": "150.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["feature"], "barcode")

    def test_branch_product_update_changes_branch_inventory_not_global_stock(self):
        branch = ShopBranch.objects.create(
            user=self.owner,
            name="Second Shop",
            address="22 Branch Road",
            city="Ikeja",
            state="Lagos",
        )
        BranchInventory.objects.create(
            branch=branch,
            product=self.product,
            stock=Decimal("4.00"),
            selling_price=Decimal("160.00"),
        )

        response = self.client.post(
            reverse("api_owner_product_detail", kwargs={"pk": self.product.id}),
            data={
                "branch_id": str(branch.id),
                "name": "Branch Rice",
                "stock": "9",
                "low_stock_threshold": "3",
                "cost_price": "105.00",
                "selling_price": "190.00",
            },
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        inventory = BranchInventory.objects.get(branch=branch, product=self.product)
        self.assertEqual(self.product.name, "Branch Rice")
        self.assertEqual(self.product.stock, Decimal("2.00"))
        self.assertEqual(inventory.stock, Decimal("9.00"))
        self.assertEqual(inventory.selling_price, Decimal("190.00"))
        self.assertEqual(response.json()["product"]["stock"], "9.00")
        self.assertEqual(response.json()["product"]["selling_price"], "190.00")

    def test_dashboard_returns_inventory_analysis(self):
        response = self.client.get(
            reverse("api_owner_dashboard"),
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        analysis = data["inventory_analysis"]
        self.assertEqual(analysis["stock_value"], "300.00")
        self.assertEqual(analysis["stock_cost"], "200.00")
        self.assertEqual(analysis["potential_profit"], "100.00")
        self.assertEqual(analysis["total_stock_units"], "2.00")
        self.assertEqual(analysis["low_stock_count"], 1)
        self.assertEqual(analysis["out_of_stock_count"], 0)
        self.assertEqual(analysis["low_stock_products"][0]["name"], "Old Rice")

    def test_mobile_reports_returns_web_business_analysis_fields(self):
        response = self.client.get(
            reverse("api_owner_reports"),
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        analysis = response.json()["business_analysis"]
        self.assertTrue(analysis["available"])
        self.assertIn("health_score", analysis)
        self.assertIn("action_recommendations", analysis)
        self.assertIn("business_insights", analysis)
        self.assertIn("top_product_rows", analysis)
        self.assertIn("restock_recommendations", analysis)
        self.assertIn("expense_rows", analysis)
        self.assertIn("customer_count", analysis)
        self.assertIn("stock_value", analysis)

    def test_ai_barcode_prefill_returns_known_product_details(self):
        response = self.client.post(
            reverse("api_owner_ai_barcode_prefill"),
            data={"barcode": "5449000000996"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        prefill = response.json()["prefill"]
        self.assertTrue(prefill["found"])
        self.assertEqual(prefill["name"], "Coca-Cola 50cl")
        self.assertEqual(prefill["category"], "Drinks")
        self.assertEqual(prefill["code"], "5449000000996")

    def test_ai_voice_returns_product_form_from_local_phrase(self):
        response = self.client.post(
            reverse("api_owner_ai_voice"),
            data={"transcript": "Add Indomie small carton 15 pieces 12000 naira"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        product_form = response.json()["parsed"]["product_form"]
        self.assertIn("Indomie", product_form["name"])
        self.assertEqual(product_form["category"], "Food")
        self.assertEqual(product_form["stock"], "15")
        self.assertEqual(product_form["selling_price"], "12000.00")

    def test_inventory_ai_assistant_parses_english_product(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={
                "mode": "product",
                "command": "Add product for me. Product name is iPhone 13, price is 450000, quantity is 5, category is phones.",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_save"])
        parsed = data["parsed"]
        self.assertEqual(parsed["action"], "create_product")
        self.assertEqual(parsed["product_name"], "iPhone 13")
        self.assertEqual(parsed["price"], "450000.00")
        self.assertEqual(parsed["quantity"], "5")
        self.assertEqual(parsed["name"], "iPhone 13")
        self.assertEqual(parsed["selling_price"], "450000.00")
        self.assertEqual(parsed["stock"], "5")
        self.assertEqual(parsed["category"], "Phones")

    def test_inventory_ai_assistant_parses_hausa_category(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={
                "mode": "category",
                "command": "Ka ƙirƙira min category, sunan shi iPhone.",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_save"])
        self.assertEqual(data["parsed"]["action"], "create_category")
        self.assertEqual(data["parsed"]["category_name"], "iPhone")
        self.assertEqual(data["parsed"]["name"], "iPhone")

    def test_inventory_ai_assistant_parses_hausa_product_with_cost_and_description(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={
                "mode": "product",
                "command": "Sunan kaya sugar 1kg, farashin saye 900, farashin saidawa 1100, adadi 20, rukuni food, bayani imported sugar.",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        parsed = response.json()["parsed"]
        self.assertEqual(parsed["action"], "create_product")
        self.assertEqual(parsed["product_name"], "Sugar 1kg")
        self.assertEqual(parsed["cost_price"], "900.00")
        self.assertEqual(parsed["selling_price"], "1100.00")
        self.assertEqual(parsed["quantity"], "20")
        self.assertEqual(parsed["category"], "Food")
        self.assertEqual(parsed["description"], "imported sugar")

    def test_inventory_ai_assistant_parses_unlabeled_local_product_phrase(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={
                "mode": "product",
                "command": "Add Indomie small carton 15 pieces 12000 naira",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        parsed = response.json()["parsed"]
        self.assertTrue(response.json()["can_save"])
        self.assertEqual(parsed["product_name"], "Indomie Small Carton")
        self.assertEqual(parsed["quantity"], "15")
        self.assertEqual(parsed["selling_price"], "12000.00")
        self.assertEqual(parsed["category"], "Food")

    def test_inventory_ai_assistant_keeps_cost_and_selling_price_separate(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={
                "mode": "product",
                "command": "Add product Golden morn 500g cost price 2200 selling price 2800 quantity 10 category cereals description family pack",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        parsed = response.json()["parsed"]
        self.assertEqual(parsed["product_name"], "Golden Morn 500g")
        self.assertEqual(parsed["cost_price"], "2200.00")
        self.assertEqual(parsed["selling_price"], "2800.00")
        self.assertEqual(parsed["quantity"], "10")
        self.assertEqual(parsed["category"], "Cereals")
        self.assertEqual(parsed["description"], "family pack")

    def test_inventory_ai_assistant_parses_bag_quantity_without_using_weight(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={"mode": "product", "command": "Add rice 50kg 3 bags 75000"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        parsed = response.json()["parsed"]
        self.assertEqual(parsed["product_name"], "Rice 50kg")
        self.assertEqual(parsed["quantity"], "3")
        self.assertEqual(parsed["selling_price"], "75000.00")

    def test_inventory_ai_assistant_returns_missing_fields_message(self):
        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={"mode": "product", "command": "Add product name Rice"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["can_save"])
        self.assertIn("selling price", data["missing"])
        self.assertIn("quantity", data["missing"])

    @patch.dict("os.environ", {"AI_INVENTORY_PROVIDER": "openai", "OPENAI_API_KEY": "test-key", "OPENAI_INVENTORY_MODEL": "gpt-5.2"})
    @patch("core.ai.requests.post")
    def test_inventory_ai_assistant_can_use_openai_provider(self, mock_post):
        api_response = Mock()
        api_response.raise_for_status.return_value = None
        api_response.json.return_value = {
            "output_text": (
                '{"action":"create_product","category_name":"","product_name":"Milo 500g",'
                '"price":3500,"quantity":4,"category":"Beverages","cost_price":3000,'
                '"selling_price":3500,"barcode":"MIL500","description":"tin pack",'
                '"missing":[],"message":"Product details extracted. Review before saving."}'
            )
        }
        mock_post.return_value = api_response

        response = self.client.post(
            reverse("api_owner_ai_inventory_assistant"),
            data={"mode": "product", "command": "Add Milo tin 500g price 3500 quantity 4"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer inventory-token",
        )

        self.assertEqual(response.status_code, 200)
        parsed = response.json()["parsed"]
        self.assertEqual(parsed["ai_provider"], "openai")
        self.assertEqual(parsed["product_name"], "Milo 500g")
        self.assertEqual(parsed["selling_price"], "3500.00")
        self.assertEqual(parsed["quantity"], "4")
        self.assertEqual(parsed["category"], "Beverages")
        mock_post.assert_called_once()


class WebInventoryUpdateTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="web-inventory-owner",
            email="web-inventory@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Web Inventory Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000004101",
            address="41 Market Road",
            country="Nigeria",
            plan="starter",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        self.product = Product.objects.create(
            user=self.owner,
            name="Web Rice",
            code="WEB001",
            cost_price=Decimal("100.00"),
            selling_price=Decimal("150.00"),
            stock=Decimal("2.00"),
            low_stock_threshold=5,
        )
        self.client.force_login(self.owner)

    def test_web_edit_product_allows_unchanged_existing_code(self):
        response = self.client.post(
            reverse("edit_product", kwargs={"pk": self.product.id}),
            data={
                "name": "Updated Web Rice",
                "code": "WEB001",
                "category": "",
                "stock": "11",
                "low_stock_threshold": "4",
                "cost_price": "120.00",
                "selling_price": "180.00",
                "vat_status": Product.VAT_STANDARD,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Updated Web Rice")
        self.assertEqual(self.product.code, "WEB001")
        self.assertEqual(self.product.stock, Decimal("11.00"))
        self.assertEqual(self.product.cost_price, Decimal("120.00"))
        self.assertEqual(self.product.selling_price, Decimal("180.00"))

    def test_web_edit_product_preserves_code_when_barcode_locked_and_blank(self):
        response = self.client.post(
            reverse("edit_product", kwargs={"pk": self.product.id}),
            data={
                "name": "Updated Web Rice Blank Code",
                "code": "",
                "category": "",
                "stock": "12",
                "low_stock_threshold": "4",
                "cost_price": "121.00",
                "selling_price": "181.00",
                "vat_status": Product.VAT_STANDARD,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Updated Web Rice Blank Code")
        self.assertEqual(self.product.code, "WEB001")
        self.assertEqual(self.product.stock, Decimal("12.00"))
        self.assertEqual(self.product.cost_price, Decimal("121.00"))
        self.assertEqual(self.product.selling_price, Decimal("181.00"))

    def test_web_starter_can_update_product_when_only_default_branch_id_is_sent(self):
        branch = ShopBranch.objects.create(
            user=self.owner,
            name="Main Shop",
            address="41 Market Road",
            is_default=True,
        )

        response = self.client.post(
            reverse("edit_product", kwargs={"pk": self.product.id}),
            data={
                "branch_id": str(branch.id),
                "name": "Updated Web Rice Default Branch",
                "code": "WEB001",
                "category": "",
                "stock": "13",
                "low_stock_threshold": "4",
                "cost_price": "122.00",
                "selling_price": "182.00",
                "vat_status": Product.VAT_STANDARD,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Updated Web Rice Default Branch")
        self.assertEqual(self.product.code, "WEB001")
        self.assertEqual(self.product.stock, Decimal("13.00"))
        self.assertFalse(BranchInventory.objects.filter(branch=branch, product=self.product).exists())

    def test_web_edit_product_blocks_code_change_without_barcode_plan(self):
        response = self.client.post(
            reverse("edit_product", kwargs={"pk": self.product.id}),
            data={
                "name": "Updated Web Rice",
                "code": "WEB002",
                "category": "",
                "stock": "11",
                "low_stock_threshold": "4",
                "cost_price": "120.00",
                "selling_price": "180.00",
                "vat_status": Product.VAT_STANDARD,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.code, "WEB001")
        self.assertEqual(self.product.stock, Decimal("2.00"))

    def test_web_inventory_ai_assistant_parses_product_command(self):
        response = self.client.post(
            reverse("ai_inventory_assistant"),
            data={
                "mode": "product",
                "command": "Add product for me. Product name is iPhone 13, price is 450000, quantity is 5, category is phones.",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["can_save"])
        self.assertEqual(data["parsed"]["action"], "create_product")
        self.assertEqual(data["parsed"]["product_name"], "iPhone 13")
        self.assertEqual(data["parsed"]["price"], "450000.00")
        self.assertEqual(data["parsed"]["name"], "iPhone 13")
        self.assertEqual(data["parsed"]["selling_price"], "450000.00")
        self.assertEqual(data["parsed"]["category"], "Phones")

    def test_web_add_product_can_create_ai_suggested_category(self):
        response = self.client.post(
            reverse("add_product"),
            data={
                "name": "AI Phone",
                "category": "",
                "new_category_name": "Phones",
                "stock": "5",
                "low_stock_threshold": "2",
                "cost_price": "300000.00",
                "selling_price": "450000.00",
                "vat_status": Product.VAT_STANDARD,
            },
        )

        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(user=self.owner, name="Phones")
        product = Product.objects.get(user=self.owner, name="AI Phone")
        self.assertEqual(product.category, category)


class WebDashboardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="dashboard-owner",
            email="dashboard@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Dashboard Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000004201",
            address="42 Market Road",
            country="Nigeria",
            plan="starter",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        self.product = Product.objects.create(
            user=self.owner,
            name="Dashboard Rice",
            cost_price=Decimal("100.00"),
            selling_price=Decimal("150.00"),
            stock=Decimal("5.00"),
            low_stock_threshold=2,
        )
        self.client.force_login(self.owner)

    def test_dashboard_defaults_to_all_sales_not_default_branch_only(self):
        sale = Sale.objects.create(
            user=self.owner,
            total_amount=Decimal("150.00"),
            total_profit=Decimal("50.00"),
            payment_status=Sale.PAYMENT_PAID,
        )
        SaleItem.objects.create(
            sale=sale,
            product=self.product,
            quantity=Decimal("1.00"),
            price=Decimal("150.00"),
            profit=Decimal("50.00"),
        )

        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_sales"], Decimal("150.00"))
        self.assertEqual(response.context["today_profit"], Decimal("50.00"))
        self.assertIsNone(response.context["selected_branch"])
        self.assertEqual(len(response.context["today_transactions"]), 1)


class ShopboyPortalDashboardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="shopboy-dashboard-owner",
            email="shopboy-dashboard@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Dashboard Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000003009",
            address="31 Market Road",
            country="Nigeria",
        )
        self.product = Product.objects.create(
            user=self.owner,
            name="Dashboard Soap",
            code="SOAP001",
            cost_price=Decimal("500.00"),
            selling_price=Decimal("750.00"),
            stock=Decimal("5.00"),
        )
        self.shopboy = ShopBoy.objects.create(
            user=self.owner,
            full_name="Dashboard Staff",
            username="dashboard-staff",
            password="pass123",
            is_active=True,
        )

    def _login_shopboy_session(self):
        session = self.client.session
        session["shopboy_id"] = self.shopboy.id
        session["shopboy_owner_id"] = self.owner.id
        session["shopboy_name"] = self.shopboy.full_name
        session.save()

    def test_dashboard_shows_disabled_complete_sale_when_cart_is_empty(self):
        self._login_shopboy_session()

        response = self.client.get(reverse("shopboy_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Complete Sale")
        self.assertContains(response, "Add products before completing a sale.")
        self.assertContains(response, "shopboy-complete-sale-btn")
        self.assertContains(response, "disabled")

    def test_dashboard_shows_visible_complete_sale_when_cart_has_items(self):
        self._login_shopboy_session()
        session = self.client.session
        session["shopboy_cart"] = {
            str(self.product.id): {
                "name": self.product.name,
                "price": 750.0,
                "cost": 500.0,
                "quantity": "1",
            }
        }
        session.save()

        response = self.client.get(reverse("shopboy_dashboard"))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shopboy-checkout-bar")
        self.assertContains(response, "data-complete-sale-button")
        self.assertGreaterEqual(html.count("Complete Sale"), 2)
        self.assertGreaterEqual(html.count(reverse("shopboy_checkout")), 2)


class CustomerScannerPaymentTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="scan-shop",
            email="scan@example.com",
            password="TestPass123!",
            account_type=User.ACCOUNT_TYPE_SHOP,
            business_name="Scan Shop",
            business_type="Retail",
            state="Lagos",
            phone="08000003001",
            address="30 Market Road",
            country="Nigeria",
            plan="business",
            shop_code="SCAN01",
            bank_name="Test Bank",
            bank_account_number="1234567890",
            bank_account_name="Scan Shop Ltd",
            subscription_active_until=timezone.localdate() + timedelta(days=30),
        )
        self.product = Product.objects.create(
            user=self.owner,
            name="Scanner Milk",
            code="MILK001",
            cost_price=Decimal("500.00"),
            selling_price=Decimal("750.00"),
            stock=Decimal("5.00"),
        )
        self.shopboy = ShopBoy.objects.create(
            user=self.owner,
            full_name="Staff One",
            username="staff",
            password="pass123",
            is_active=True,
        )

    def _shopboy_token(self):
        response = self.client.post(reverse("api_mobile_auth_login"), data={
            "role": "shopboy",
            "shop_code": "SCAN01",
            "username": "staff",
            "password": "pass123",
        })
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def test_customer_scans_checkout_and_shopboy_confirms_payment(self):
        start = self.client.post(reverse("api_customer_scan_cart_start"), data={
            "shop_username": self.owner.username,
            "customer_name": "Walk In",
        })
        self.assertEqual(start.status_code, 200)
        cart = start.json()["cart"]
        self.assertEqual(cart["bank"]["account_number"], "1234567890")

        scan = self.client.post(reverse("api_customer_scan_cart_add_by_code"), data={
            "cart_token": cart["cart_token"],
            "code": "MILK001",
        })
        self.assertEqual(scan.status_code, 200)
        self.assertEqual(scan.json()["cart"]["total"], "750.00")

        checkout = self.client.post(reverse("api_customer_scan_cart_checkout"), data={
            "cart_token": cart["cart_token"],
        })
        self.assertEqual(checkout.status_code, 200)
        sale = Sale.objects.get(user=self.owner, sales_channel=Sale.CHANNEL_CUSTOMER_SCAN)
        self.assertEqual(sale.payment_status, Sale.PAYMENT_LOAN)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("5.00"))
        self.assertTrue(CustomerScanCart.objects.get(cart_token=cart["cart_token"]).is_checked_out)

        token = self._shopboy_token()
        pending = self.client.get(reverse("api_shopboy_scanner_sales"), HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertContains(pending, "Scanner Milk")

        confirm = self.client.post(reverse("api_shopboy_scanner_sale_confirm", kwargs={"sale_id": sale.id}), HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(confirm.status_code, 200)
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(sale.payment_status, Sale.PAYMENT_PAID)
        self.assertEqual(sale.handled_by_shopboy, self.shopboy)
        self.assertEqual(self.product.stock, Decimal("4.00"))

    def test_delivery_api_is_removed_for_mvp(self):
        response = self.client.get("/api/marketplace/delivery/riders/")
        self.assertEqual(response.status_code, 404)
