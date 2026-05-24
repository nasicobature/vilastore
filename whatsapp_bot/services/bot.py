from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import DataPlan, Payment, ResellerProfile, Transaction, Wallet, WhatsAppUser
from .phone import is_valid_phone, normalize_phone
from .vtu import VTUClient


MAIN_MENU = (
    "Welcome to VilaStore Data Bot.\n\n"
    "Reply with a number:\n"
    "1. Buy Data\n"
    "2. Buy Airtime\n"
    "3. Fund Wallet\n"
    "4. Check Balance\n"
    "5. Become Reseller\n"
    "6. Transaction History"
)

NETWORKS = {
    "1": DataPlan.NETWORK_MTN,
    "2": DataPlan.NETWORK_AIRTEL,
    "3": DataPlan.NETWORK_GLO,
    "4": DataPlan.NETWORK_9MOBILE,
}


class BotState:
    MENU = "menu"
    SELECT_NETWORK = "select_network"
    SELECT_PLAN = "select_plan"
    ENTER_RECIPIENT = "enter_recipient"
    CONFIRM_DATA = "confirm_data"
    FUND_AMOUNT = "fund_amount"


def get_or_create_user(phone_number, display_name=""):
    phone = normalize_phone(phone_number)
    user, _ = WhatsAppUser.objects.get_or_create(
        phone_number=phone,
        defaults={"display_name": display_name or ""},
    )
    if display_name and not user.display_name:
        user.display_name = display_name
    user.last_seen_at = timezone.now()
    user.save(update_fields=["display_name", "last_seen_at"] if display_name else ["last_seen_at"])
    Wallet.objects.get_or_create(user=user)
    return user


def reset_to_menu(user):
    user.bot_state = BotState.MENU
    user.session_data = {}
    user.save(update_fields=["bot_state", "session_data"])
    return MAIN_MENU


def wallet_price_for(user, plan):
    reseller = getattr(user, "reseller_profile", None)
    if reseller and reseller.is_approved:
        return plan.reseller_price
    return plan.normal_price


def network_menu():
    return "Select network:\n1. MTN\n2. Airtel\n3. Glo\n4. 9mobile\n\nReply 0 to go back."


def plan_menu(user, network):
    plans = list(DataPlan.objects.filter(network=network, is_active=True).order_by("normal_price", "id")[:20])
    if not plans:
        return "No active data plans for this network yet. Reply 0 for main menu."
    lines = ["Select data plan:"]
    for idx, plan in enumerate(plans, start=1):
        lines.append(f"{idx}. {plan.size} / {plan.validity} - ₦{wallet_price_for(user, plan):,.2f}")
    lines.append("\nReply 0 to go back.")
    user.session_data["plan_ids"] = [plan.id for plan in plans]
    user.save(update_fields=["session_data"])
    return "\n".join(lines)


def create_fund_payment(user, amount):
    payment = Payment.objects.create(user=user, amount=amount)
    checkout_url = settings.PAYMENT_CHECKOUT_URL
    if checkout_url:
        separator = "&" if "?" in checkout_url else "?"
        pay_link = f"{checkout_url}{separator}reference={payment.reference}&amount={amount}&phone={user.phone_number}"
    else:
        pay_link = "Payment link is not configured yet. Contact admin to complete funding."
    return payment, pay_link


def transaction_history(user):
    rows = Transaction.objects.filter(user=user).select_related("data_plan")[:5]
    if not rows:
        return "No transactions yet."
    lines = ["Last transactions:"]
    for tx in rows:
        plan = tx.data_plan.size if tx.data_plan else tx.transaction_type
        lines.append(f"{tx.reference}: {plan} to {tx.recipient_phone} - ₦{tx.amount:,.2f} - {tx.get_status_display()}")
    return "\n".join(lines)


def process_data_purchase(user):
    plan = DataPlan.objects.get(id=user.session_data["plan_id"], is_active=True)
    recipient = normalize_phone(user.session_data["recipient_phone"])
    amount = wallet_price_for(user, plan)

    with db_transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(user=user)
        if wallet.balance < amount:
            return f"Insufficient wallet balance. Balance: ₦{wallet.balance:,.2f}, needed: ₦{amount:,.2f}.\nReply 3 to fund wallet."

        wallet.balance -= amount
        wallet.save(update_fields=["balance", "updated_at"])
        tx = Transaction.objects.create(
            user=user,
            transaction_type=Transaction.TYPE_DATA,
            data_plan=plan,
            recipient_phone=recipient,
            amount=amount,
            status=Transaction.STATUS_PENDING,
        )

    result = VTUClient().purchase_data(
        network=plan.network,
        plan_code=plan.vtu_plan_code,
        recipient_phone=recipient,
        reference=tx.reference,
        amount=amount,
    )

    with db_transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)
        tx.provider_response = result.raw or {}
        tx.provider_reference = result.provider_reference
        if result.success:
            tx.status = Transaction.STATUS_SUCCESS
            tx.failure_reason = ""
            message = f"Success! {plan.size} {plan.get_network_display()} data sent to {recipient}.\nReference: {tx.reference}"
        else:
            tx.status = Transaction.STATUS_FAILED
            tx.failure_reason = result.message
            wallet = Wallet.objects.select_for_update().get(user=user)
            wallet.balance += amount
            wallet.save(update_fields=["balance", "updated_at"])
            message = f"Data purchase failed and your wallet was refunded.\nReason: {result.message}\nReference: {tx.reference}"
        tx.save(update_fields=["provider_response", "provider_reference", "status", "failure_reason", "updated_at"])

    user.bot_state = BotState.MENU
    user.session_data = {}
    user.save(update_fields=["bot_state", "session_data"])
    return message + "\n\n" + MAIN_MENU


def handle_message(phone_number, text, display_name=""):
    user = get_or_create_user(phone_number, display_name=display_name)
    body = (text or "").strip()
    lowered = body.lower()

    if lowered in {"hi", "hello", "menu", "start", "0"}:
        return reset_to_menu(user)

    if user.bot_state in {"", BotState.MENU}:
        if body == "1":
            user.bot_state = BotState.SELECT_NETWORK
            user.session_data = {}
            user.save(update_fields=["bot_state", "session_data"])
            return network_menu()
        if body == "2":
            return "Airtime purchase is coming next. Reply 1 to buy data or 0 for menu."
        if body == "3":
            user.bot_state = BotState.FUND_AMOUNT
            user.save(update_fields=["bot_state"])
            return "Enter amount to fund your wallet, e.g. 5000.\nReply 0 to cancel."
        if body == "4":
            wallet = Wallet.objects.get(user=user)
            return f"Your wallet balance is ₦{wallet.balance:,.2f}.\n\n{MAIN_MENU}"
        if body == "5":
            profile, created = ResellerProfile.objects.get_or_create(user=user)
            if profile.status == ResellerProfile.STATUS_APPROVED:
                return "You are already an approved reseller.\n\n" + MAIN_MENU
            return ("Your reseller application has been submitted." if created else "Your reseller application is still pending.") + "\nAdmin will review it.\n\n" + MAIN_MENU
        if body == "6":
            return transaction_history(user) + "\n\n" + MAIN_MENU
        return MAIN_MENU

    if user.bot_state == BotState.FUND_AMOUNT:
        try:
            amount = Decimal(body.replace(",", ""))
            if amount <= 0:
                raise ValueError
        except Exception:
            return "Enter a valid amount, e.g. 5000. Reply 0 to cancel."
        payment, pay_link = create_fund_payment(user, amount)
        user.bot_state = BotState.MENU
        user.save(update_fields=["bot_state"])
        return f"Wallet funding created.\nAmount: ₦{amount:,.2f}\nReference: {payment.reference}\nPay here: {pay_link}"

    if user.bot_state == BotState.SELECT_NETWORK:
        network = NETWORKS.get(body)
        if not network:
            return network_menu()
        user.session_data = {"network": network}
        user.bot_state = BotState.SELECT_PLAN
        user.save(update_fields=["session_data", "bot_state"])
        return plan_menu(user, network)

    if user.bot_state == BotState.SELECT_PLAN:
        plan_ids = user.session_data.get("plan_ids", [])
        try:
            plan_id = plan_ids[int(body) - 1]
            plan = DataPlan.objects.get(id=plan_id, is_active=True)
        except Exception:
            return plan_menu(user, user.session_data.get("network"))
        user.session_data["plan_id"] = plan.id
        user.bot_state = BotState.ENTER_RECIPIENT
        user.save(update_fields=["session_data", "bot_state"])
        return f"Enter recipient phone number for {plan.size} {plan.get_network_display()} data."

    if user.bot_state == BotState.ENTER_RECIPIENT:
        if not is_valid_phone(body):
            return "Invalid phone number. Enter a valid recipient phone number."
        plan = DataPlan.objects.get(id=user.session_data["plan_id"])
        recipient = normalize_phone(body)
        price = wallet_price_for(user, plan)
        user.session_data["recipient_phone"] = recipient
        user.bot_state = BotState.CONFIRM_DATA
        user.save(update_fields=["session_data", "bot_state"])
        return (
            "Confirm purchase:\n"
            f"Network: {plan.get_network_display()}\n"
            f"Plan: {plan.size} / {plan.validity}\n"
            f"Recipient: {recipient}\n"
            f"Amount: ₦{price:,.2f}\n\n"
            "Reply YES to confirm or 0 to cancel."
        )

    if user.bot_state == BotState.CONFIRM_DATA:
        if lowered in {"yes", "y", "confirm"}:
            return process_data_purchase(user)
        return "Purchase cancelled.\n\n" + reset_to_menu(user)

    return reset_to_menu(user)
