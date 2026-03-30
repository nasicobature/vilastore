import json
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    MarketplaceBuyer,
    MarketplaceBuyerToken,
    MarketplaceChatMessage,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceShopProfile,
    Product,
    User,
)
from .views import (
    _ensure_marketplace_profiles,
    _get_assigned_shopboy,
    _password_meets_rules,
    _send_marketplace_reset_code,
    _send_marketplace_verification_code,
)


TOKEN_TTL_DAYS = 30
OTP_EXPIRY_MINUTES = 10


def _json_error(message, status=400, **extra):
    payload = {"success": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _json_success(data=None, status=200):
    payload = {"success": True}
    if data:
        payload.update(data)
    return JsonResponse(payload, status=status)


def _parse_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _get_body_data(request):
    if request.content_type and "application/json" in request.content_type:
        return _parse_json(request)
    if request.method in ["POST", "PUT", "PATCH"]:
        return request.POST.dict()
    return request.GET.dict()


def _money(value):
    if value is None:
        return "0.00"
    return str(Decimal(value).quantize(Decimal("0.01")))


def _abs_media_url(request, field):
    if not field:
        return ""
    try:
        return request.build_absolute_uri(field.url)
    except Exception:
        return ""


def _is_video(path):
    lower = (path or "").lower()
    return lower.endswith((".mp4", ".webm", ".ogg"))


def _issue_token(buyer):
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(days=TOKEN_TTL_DAYS)
    return MarketplaceBuyerToken.objects.create(
        buyer=buyer,
        token=token,
        expires_at=expires_at,
    )


def _get_token_value(request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.GET.get("token") or request.POST.get("token") or ""


def _get_buyer_from_request(request):
    token_value = _get_token_value(request)
    if not token_value:
        return None, None

    token_obj = (
        MarketplaceBuyerToken.objects.select_related("buyer")
        .filter(token=token_value, is_revoked=False)
        .first()
    )
    if not token_obj:
        return None, None

    if token_obj.expires_at and token_obj.expires_at < timezone.now():
        token_obj.is_revoked = True
        token_obj.save(update_fields=["is_revoked"])
        return None, token_obj

    buyer = token_obj.buyer
    if not buyer.is_active or not buyer.is_email_verified:
        return None, token_obj

    token_obj.last_used_at = timezone.now()
    token_obj.save(update_fields=["last_used_at"])
    return buyer, token_obj


def _serialize_buyer(buyer):
    return {
        "id": buyer.id,
        "email": buyer.email,
        "is_email_verified": buyer.is_email_verified,
        "last_login": buyer.last_login.isoformat() if buyer.last_login else None,
        "created_at": buyer.created_at.isoformat() if buyer.created_at else None,
    }


def _serialize_product(request, product):
    image_url = _abs_media_url(request, product.image)
    return {
        "id": product.id,
        "name": product.name,
        "price": _money(product.selling_price),
        "stock": product.stock,
        "image_url": image_url,
        "is_video": _is_video(image_url),
    }


def _serialize_shop_profile(request, profile):
    user = profile.user
    logo_url = _abs_media_url(request, profile.logo) or _abs_media_url(request, user.profile_image)
    cover_url = _abs_media_url(request, profile.cover_image) or _abs_media_url(request, user.profile_image)
    sales_count = getattr(profile, "sales_count", None)
    products_preview = []
    for product in list(user.product_set.all()[:4]):
        products_preview.append({
            "id": product.id,
            "name": product.name,
            "image_url": _abs_media_url(request, product.image),
        })
    return {
        "username": user.username,
        "business_name": user.business_name or user.username,
        "description": profile.description or "",
        "category": profile.category,
        "location": profile.location,
        "is_verified": profile.is_verified,
        "rating": float(profile.rating) if profile.rating is not None else 0,
        "sales_count": float(sales_count or 0),
        "logo_url": logo_url,
        "cover_url": cover_url,
        "products_preview": products_preview,
    }


def _serialize_order_item(item):
    return {
        "product_id": item.product_id,
        "product_name": item.product.name,
        "quantity": item.quantity,
        "unit_price": _money(item.unit_price),
        "line_total": _money(item.unit_price * item.quantity),
    }


def _serialize_message(message):
    return {
        "sender_type": message.sender_type,
        "message": message.message,
        "created_at": message.created_at.isoformat(),
    }


def _serialize_order(request, order, include_access_token=False):
    status_labels = dict(MarketplaceOrder.STATUS_CHOICES)
    return {
        "public_id": str(order.public_id),
        "access_token": str(order.access_token) if include_access_token else "",
        "status": order.status,
        "status_label": status_labels.get(order.status, order.status),
        "buyer_name": order.buyer_name,
        "buyer_contact": order.buyer_contact,
        "buyer_address": order.buyer_address,
        "total_amount": _money(order.total_amount),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "shop": {
            "username": order.shop_owner.username,
            "business_name": order.shop_owner.business_name or order.shop_owner.username,
        },
    }


def _get_order_access(request, order, buyer):
    if buyer and order.buyer_id == buyer.id:
        return True, True
    access_token = request.GET.get("access_token") or request.POST.get("access_token") or ""
    if access_token and str(order.access_token) == access_token:
        return True, False
    return False, False


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_signup(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not email or not password or not confirm_password:
        return _json_error("Email and passwords are required.")

    if password != confirm_password:
        return _json_error("Passwords do not match.")

    if not _password_meets_rules(password):
        return _json_error("Password must include uppercase, number, and special character.")

    if MarketplaceBuyer.objects.filter(email__iexact=email).exists():
        return _json_error("Email already registered. Please sign in.", status=409)

    buyer = MarketplaceBuyer.objects.create(
        email=email,
        password=make_password(password),
    )

    try:
        _send_marketplace_verification_code(buyer)
    except Exception:
        return _json_error("Account created, but verification email failed. Try again.", status=500)

    return _json_success({
        "requires_verification": True,
        "email": buyer.email,
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_login(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return _json_error("Email and password are required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer or not check_password(password, buyer.password):
        return _json_error("Invalid email or password.", status=401)

    if not buyer.is_email_verified:
        try:
            _send_marketplace_verification_code(buyer)
        except Exception:
            return _json_error("Could not send verification email. Please try again.", status=500)
        return _json_success({
            "requires_verification": True,
            "email": buyer.email,
        })

    buyer.last_login = timezone.now()
    buyer.save(update_fields=["last_login"])

    token_obj = _issue_token(buyer)
    return _json_success({
        "token": token_obj.token,
        "buyer": _serialize_buyer(buyer),
        "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_verify(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not email or not code:
        return _json_error("Email and code are required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer:
        return _json_error("Account not found.", status=404)

    if buyer.is_email_verified:
        token_obj = _issue_token(buyer)
        return _json_success({
            "token": token_obj.token,
            "buyer": _serialize_buyer(buyer),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    if not buyer.email_verification_code or not buyer.email_code_sent_at:
        return _json_error("No OTP found. Send code first.")

    if timezone.now() - buyer.email_code_sent_at > timedelta(minutes=OTP_EXPIRY_MINUTES):
        return _json_error("OTP expired. Send a new code.")

    if code != buyer.email_verification_code:
        return _json_error("Invalid code.")

    buyer.is_email_verified = True
    buyer.email_verification_code = ""
    buyer.email_code_sent_at = None
    buyer.last_login = timezone.now()
    buyer.save(update_fields=["is_email_verified", "email_verification_code", "email_code_sent_at", "last_login"])

    token_obj = _issue_token(buyer)
    return _json_success({
        "token": token_obj.token,
        "buyer": _serialize_buyer(buyer),
        "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_resend_code(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    if not email:
        return _json_error("Email is required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer:
        return _json_success({"sent": True})

    if buyer.is_email_verified:
        return _json_error("Email already verified.")

    try:
        _send_marketplace_verification_code(buyer)
    except Exception:
        return _json_error("Failed to send verification email. Please try again.", status=500)

    return _json_success({"sent": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_forgot_password_request(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    if not email:
        return _json_error("Email is required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if buyer:
        try:
            _send_marketplace_reset_code(buyer)
        except Exception:
            return _json_error("Failed to send reset email. Please try again.", status=500)

    return _json_success({"sent": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_forgot_password_verify(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or not code:
        return _json_error("Email and code are required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer or not buyer.reset_code or not buyer.reset_sent_at:
        return _json_error("No reset code found. Send code first.")

    if timezone.now() - buyer.reset_sent_at > timedelta(minutes=OTP_EXPIRY_MINUTES):
        return _json_error("Reset code expired. Send a new code.")

    if code != buyer.reset_code:
        return _json_error("Invalid code.")

    return _json_success({"verified": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_forgot_password_reset(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not email or not code or not password or not confirm_password:
        return _json_error("Email, code, and passwords are required.")

    if password != confirm_password:
        return _json_error("Passwords do not match.")

    if not _password_meets_rules(password):
        return _json_error("Password must include uppercase, number, and special character.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer or not buyer.reset_code or not buyer.reset_sent_at:
        return _json_error("No reset code found. Send code first.")

    if timezone.now() - buyer.reset_sent_at > timedelta(minutes=OTP_EXPIRY_MINUTES):
        return _json_error("Reset code expired. Send a new code.")

    if code != buyer.reset_code:
        return _json_error("Invalid code.")

    buyer.password = make_password(password)
    buyer.reset_code = ""
    buyer.reset_sent_at = None
    buyer.save(update_fields=["password", "reset_code", "reset_sent_at"])

    return _json_success({"reset": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_logout(request):
    buyer, token_obj = _get_buyer_from_request(request)
    if token_obj:
        token_obj.is_revoked = True
        token_obj.save(update_fields=["is_revoked"])
    return _json_success({"logged_out": True})


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_me(request):
    buyer, _ = _get_buyer_from_request(request)
    if not buyer:
        return _json_error("Unauthorized.", status=401)
    return _json_success({"buyer": _serialize_buyer(buyer)})


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_shops(request):
    q = (request.GET.get("q") or "").strip()
    username_q = q[1:] if q.startswith("@") else q
    category = (request.GET.get("category") or "").strip()
    location = (request.GET.get("location") or "").strip()
    verified = request.GET.get("verified") == "1"
    sort = request.GET.get("sort") or "rating"

    _ensure_marketplace_profiles()

    profiles = (
        MarketplaceShopProfile.objects.select_related("user")
        .prefetch_related("user__product_set")
        .filter(user__is_active=True)
        .distinct()
    )

    if q:
        profiles = profiles.filter(
            Q(user__business_name__icontains=q) |
            Q(user__username__icontains=username_q) |
            Q(description__icontains=q) |
            Q(user__product__name__icontains=q)
        ).distinct()

    if category:
        profiles = profiles.filter(category__iexact=category)
    if location:
        profiles = profiles.filter(location__icontains=location)
    if verified:
        profiles = profiles.filter(is_verified=True)

    profiles = profiles.annotate(
        sales_count=Sum(
            "user__marketplace_orders__items__quantity",
            filter=Q(user__marketplace_orders__status__in=["paid", "shipped", "delivered"])
        )
    )

    if sort == "sales":
        profiles = profiles.order_by("-sales_count", "-created_at")
    elif sort == "newest":
        profiles = profiles.order_by("-created_at")
    else:
        profiles = profiles.order_by("-rating", "-created_at")

    categories = (
        MarketplaceShopProfile.objects.exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    locations = (
        MarketplaceShopProfile.objects.exclude(location="")
        .values_list("location", flat=True)
        .distinct()
        .order_by("location")
    )

    shops = [_serialize_shop_profile(request, profile) for profile in profiles]

    return _json_success({
        "shops": shops,
        "categories": list(categories),
        "locations": list(locations),
        "filters": {
            "q": q,
            "category": category,
            "location": location,
            "verified": verified,
            "sort": sort,
        },
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_shop_detail(request, username):
    shop_owner = get_object_or_404(User, username=username, is_active=True)
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=shop_owner)
    products = Product.objects.filter(user=shop_owner).order_by("name")

    return _json_success({
        "shop": _serialize_shop_profile(request, profile),
        "products": [_serialize_product(request, product) for product in products],
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_place_order(request, username):
    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    shop_owner = get_object_or_404(User, username=username, is_active=True)
    buyer, _ = _get_buyer_from_request(request)

    buyer_name = (data.get("buyer_name") or "").strip()
    buyer_contact = (data.get("buyer_contact") or "").strip()
    buyer_address = (data.get("buyer_address") or "").strip()

    if not buyer_name or not buyer_contact:
        return _json_error("Buyer name and contact are required.")

    items = data.get("items") or []
    if not isinstance(items, list):
        return _json_error("Items must be a list.")

    product_ids = []
    clean_items = []
    for row in items:
        try:
            product_id = int(row.get("product_id"))
            quantity = int(row.get("quantity"))
        except Exception:
            continue
        if quantity <= 0:
            continue
        product_ids.append(product_id)
        clean_items.append({"product_id": product_id, "quantity": quantity})

    if not clean_items:
        return _json_error("Select at least one product to place an order.")

    total_amount = Decimal("0.00")
    order_items = []

    with transaction.atomic():
        products = (
            Product.objects.select_for_update()
            .filter(user=shop_owner, id__in=product_ids)
        )
        product_map = {product.id: product for product in products}

        for row in clean_items:
            product = product_map.get(row["product_id"])
            if not product:
                return _json_error("A product in your cart is invalid.")
            if product.stock < row["quantity"]:
                return _json_error(f"Not enough stock for {product.name}. Available: {product.stock}.")

            line_total = product.selling_price * row["quantity"]
            total_amount += line_total
            order_items.append({
                "product": product,
                "quantity": row["quantity"],
                "unit_price": product.selling_price,
            })

        order = MarketplaceOrder.objects.create(
            shop_owner=shop_owner,
            buyer=buyer,
            assigned_shopboy=_get_assigned_shopboy(shop_owner),
            buyer_name=buyer_name,
            buyer_contact=buyer_contact,
            buyer_address=buyer_address,
            total_amount=total_amount.quantize(Decimal("0.01")),
        )

        for row in order_items:
            MarketplaceOrderItem.objects.create(
                order=order,
                product=row["product"],
                quantity=row["quantity"],
                unit_price=row["unit_price"].quantize(Decimal("0.01")),
            )

        MarketplaceChatMessage.objects.create(
            order=order,
            sender_type=MarketplaceChatMessage.SENDER_SYSTEM,
            message="Order created. Waiting for confirmation.",
        )

    order = MarketplaceOrder.objects.select_related("shop_owner").get(id=order.id)
    items = order.items.select_related("product").all()
    messages = order.messages.order_by("created_at")

    return _json_success({
        "order": _serialize_order(request, order, include_access_token=True),
        "items": [_serialize_order_item(item) for item in items],
        "messages": [_serialize_message(message) for message in messages],
    }, status=201)


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_orders(request):
    buyer, _ = _get_buyer_from_request(request)
    if not buyer:
        return _json_error("Unauthorized.", status=401)

    orders = (
        MarketplaceOrder.objects.filter(buyer=buyer)
        .select_related("shop_owner")
        .order_by("-created_at")
    )

    return _json_success({
        "orders": [_serialize_order(request, order) for order in orders],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_order_detail(request, public_id):
    order = get_object_or_404(
        MarketplaceOrder.objects.select_related("shop_owner").prefetch_related("items__product", "messages"),
        public_id=public_id,
    )

    buyer, _ = _get_buyer_from_request(request)
    allowed, _ = _get_order_access(request, order, buyer)
    if not allowed:
        return _json_error("Access denied.", status=403)

    items = order.items.select_related("product").all()
    messages = order.messages.order_by("created_at")

    return _json_success({
        "order": _serialize_order(request, order),
        "items": [_serialize_order_item(item) for item in items],
        "messages": [_serialize_message(message) for message in messages],
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_order_message(request, public_id):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    order = get_object_or_404(MarketplaceOrder, public_id=public_id)
    buyer, _ = _get_buyer_from_request(request)
    allowed, _ = _get_order_access(request, order, buyer)
    if not allowed:
        return _json_error("Access denied.", status=403)

    text = (data.get("message") or "").strip()
    if not text:
        return _json_error("Message cannot be empty.")

    msg = MarketplaceChatMessage.objects.create(
        order=order,
        sender_type=MarketplaceChatMessage.SENDER_BUYER,
        message=text,
    )

    return _json_success({
        "message": _serialize_message(msg),
    }, status=201)
