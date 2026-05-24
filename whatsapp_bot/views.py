import json
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import DataPlan, Payment, Wallet, WhatsAppUser
from .services.bot import handle_message
from .services.payments import parse_payment_payload, verify_payment_signature
from .services.phone import normalize_phone
from .services.whatsapp import WhatsAppCloudClient

logger = logging.getLogger(__name__)


def _json_error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge or "")
        return HttpResponse("Invalid verification token", status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return _json_error("Invalid JSON payload.")

    client = WhatsAppCloudClient()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            contacts = {item.get("wa_id"): item.get("profile", {}).get("name", "") for item in value.get("contacts", [])}
            for message in value.get("messages", []):
                from_phone = normalize_phone(message.get("from", ""))
                text = (message.get("text") or {}).get("body", "")
                if not from_phone or not text:
                    continue
                try:
                    reply = handle_message(from_phone, text, display_name=contacts.get(message.get("from"), ""))
                    client.send_text(from_phone, reply)
                except Exception:
                    logger.exception("WhatsApp bot message processing failed.", extra={"from_phone": from_phone})
                    client.send_text(from_phone, "Sorry, something went wrong. Please try again.")

    return JsonResponse({"success": True})


@csrf_exempt
@require_http_methods(["POST"])
def payment_webhook(request):
    signature = request.headers.get("X-Signature") or request.headers.get("Verif-Hash") or request.headers.get("X-Paystack-Signature")
    if not verify_payment_signature(request.body, signature):
        return _json_error("Invalid payment signature.", status=403)

    try:
        parsed = parse_payment_payload(request.body)
    except Exception:
        logger.exception("Payment webhook payload could not be parsed.")
        return _json_error("Invalid payment payload.")

    reference = parsed["reference"]
    if not reference:
        return _json_error("Payment reference is required.")

    try:
        paid_amount = Decimal(str(parsed["amount"]))
    except Exception:
        return _json_error("Payment amount is invalid.")

    success_statuses = {"success", "successful", "completed", "paid"}
    with db_transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if not payment:
            return _json_error("Payment reference was not found.", status=404)
        if payment.status == Payment.STATUS_SUCCESS:
            return JsonResponse({"success": True, "duplicate": True})
        if paid_amount < payment.amount:
            payment.status = Payment.STATUS_FAILED
            payment.raw_payload = parsed["payload"]
            payment.gateway_reference = parsed["gateway_reference"]
            payment.save(update_fields=["status", "raw_payload", "gateway_reference"])
            return _json_error("Paid amount is lower than expected.", status=400)

        payment.raw_payload = parsed["payload"]
        payment.gateway_reference = parsed["gateway_reference"]
        if parsed["status"] in success_statuses:
            wallet = Wallet.objects.select_for_update().get(user=payment.user)
            wallet.balance += payment.amount
            wallet.save(update_fields=["balance", "updated_at"])
            payment.status = Payment.STATUS_SUCCESS
            payment.processed_at = timezone.now()
        else:
            payment.status = Payment.STATUS_FAILED
        payment.save(update_fields=["raw_payload", "gateway_reference", "status", "processed_at"])

    return JsonResponse({"success": True, "status": payment.status})


@require_http_methods(["GET"])
def data_plans_api(request):
    network = (request.GET.get("network") or "").strip().lower()
    plans = DataPlan.objects.filter(is_active=True)
    if network:
        plans = plans.filter(network=network)
    return JsonResponse({
        "success": True,
        "plans": [
            {
                "id": plan.id,
                "network": plan.network,
                "network_display": plan.get_network_display(),
                "plan_name": plan.plan_name,
                "size": plan.size,
                "validity": plan.validity,
                "normal_price": str(plan.normal_price),
                "reseller_price": str(plan.reseller_price),
            }
            for plan in plans
        ],
    })


@require_http_methods(["GET"])
def transaction_history_api(request):
    phone = normalize_phone(request.GET.get("phone", ""))
    user = WhatsAppUser.objects.filter(phone_number=phone).first()
    if not user:
        return _json_error("User not found.", status=404)
    return JsonResponse({
        "success": True,
        "transactions": [
            {
                "reference": tx.reference,
                "type": tx.transaction_type,
                "recipient_phone": tx.recipient_phone,
                "amount": str(tx.amount),
                "status": tx.status,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in user.transactions.all()[:20]
        ],
    })
