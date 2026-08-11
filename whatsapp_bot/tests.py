import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import DataPlan, Payment, Transaction, Wallet, WhatsAppUser
from .services.bot import handle_message
from .services.vtu import VTUResult


class WhatsAppBotFlowTests(TestCase):
    def setUp(self):
        self.plan = DataPlan.objects.create(
            network=DataPlan.NETWORK_MTN,
            plan_name="MTN 1GB",
            size="1GB",
            validity="30 days",
            vtu_plan_code="MTN1GB",
            cost_price=Decimal("250.00"),
            normal_price=Decimal("350.00"),
            reseller_price=Decimal("300.00"),
        )

    def test_hi_registers_user_and_returns_menu(self):
        reply = handle_message("08012345678", "Hi", display_name="Ada")

        self.assertIn("Buy Data", reply)
        user = WhatsAppUser.objects.get(phone_number="2348012345678")
        self.assertEqual(user.display_name, "Ada")
        self.assertTrue(hasattr(user, "wallet"))

    @patch("whatsapp_bot.services.bot.VTUClient.purchase_data")
    def test_buy_data_deducts_wallet_and_saves_success_transaction(self, mock_purchase):
        mock_purchase.return_value = VTUResult(True, "sent", provider_reference="VTU123", raw={"status": "success"})
        user = WhatsAppUser.objects.create(phone_number="2348012345678")
        Wallet.objects.create(user=user, balance=Decimal("1000.00"))

        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "08099999999")
        reply = handle_message(user.phone_number, "YES")

        self.assertIn("Success", reply)
        user.wallet.refresh_from_db()
        self.assertEqual(user.wallet.balance, Decimal("650.00"))
        tx = Transaction.objects.get(user=user)
        self.assertEqual(tx.status, Transaction.STATUS_SUCCESS)
        self.assertEqual(tx.recipient_phone, "2348099999999")

    @patch("whatsapp_bot.services.bot.VTUClient.purchase_data")
    def test_failed_vtu_purchase_refunds_wallet(self, mock_purchase):
        mock_purchase.return_value = VTUResult(False, "provider down", raw={"status": "failed"})
        user = WhatsAppUser.objects.create(phone_number="2348012345678")
        Wallet.objects.create(user=user, balance=Decimal("1000.00"))

        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "1")
        handle_message(user.phone_number, "08099999999")
        reply = handle_message(user.phone_number, "YES")

        self.assertIn("refunded", reply.lower())
        user.wallet.refresh_from_db()
        self.assertEqual(user.wallet.balance, Decimal("1000.00"))
        self.assertEqual(Transaction.objects.get(user=user).status, Transaction.STATUS_FAILED)


@override_settings(PAYMENT_WEBHOOK_SECRET="secret")
class PaymentWebhookTests(TestCase):
    def test_successful_payment_updates_wallet_once(self):
        user = WhatsAppUser.objects.create(phone_number="2348012345678")
        Wallet.objects.create(user=user, balance=Decimal("100.00"))
        payment = Payment.objects.create(user=user, amount=Decimal("500.00"), reference="PAY123")
        body = json.dumps({"status": "success", "reference": payment.reference, "amount": "500.00"}).encode("utf-8")
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

        url = reverse("whatsapp_bot:payment_webhook")
        first = self.client.post(url, data=body, content_type="application/json", HTTP_X_SIGNATURE=signature)
        second = self.client.post(url, data=body, content_type="application/json", HTTP_X_SIGNATURE=signature)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        user.wallet.refresh_from_db()
        self.assertEqual(user.wallet.balance, Decimal("600.00"))
        self.assertTrue(second.json()["duplicate"])

    def test_invalid_payment_signature_is_rejected(self):
        body = json.dumps({"status": "success", "reference": "PAY123", "amount": "500.00"}).encode("utf-8")
        response = self.client.post(
            reverse("whatsapp_bot:payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE="bad",
        )

        self.assertEqual(response.status_code, 403)
