from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuthToken, BranchInventory, Customer, CustomerScanCart, Product, Sale, SaleItem, ShopBranch, ShopBoy, User


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
