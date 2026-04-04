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
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    Agent,
    AuthToken,
    Category,
    MarketplaceBuyer,
    MarketplaceBuyerToken,
    MarketplaceChatMessage,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceShopProfile,
    Product,
    Sale,
    SaleItem,
    ShopBoy,
    ShopboyCart,
    OwnerCart,
    User,
)
from .views import (
    _authenticate_with_identifier,
    _calculate_item_vat,
    _parse_stock,
    _ensure_marketplace_profiles,
    _get_assigned_shopboy,
    _password_meets_rules,
    _vat_registered_for_sale,
    _send_marketplace_reset_code,
    _send_marketplace_verification_code,
)
from .subscription import subscription_is_active


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


def _issue_auth_token(role, *, owner=None, shopboy=None, agent=None):
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(days=TOKEN_TTL_DAYS)
    return AuthToken.objects.create(
        token=token,
        role=role,
        owner=owner,
        shopboy=shopboy,
        agent=agent,
        expires_at=expires_at,
    )


def _get_auth_token_value(request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.GET.get("token") or request.POST.get("token") or ""


def _get_auth_from_request(request):
    token_value = _get_auth_token_value(request)
    if not token_value:
        return None, None

    token_obj = AuthToken.objects.select_related("owner", "shopboy", "agent").filter(
        token=token_value,
        is_revoked=False,
    ).first()
    if not token_obj:
        return None, None

    if token_obj.expires_at and token_obj.expires_at < timezone.now():
        token_obj.is_revoked = True
        token_obj.save(update_fields=["is_revoked"])
        return None, token_obj

    token_obj.last_used_at = timezone.now()
    token_obj.save(update_fields=["last_used_at"])
    return token_obj, token_obj


def _require_owner(request):
    token_obj, _ = _get_auth_from_request(request)
    if not token_obj or token_obj.role != AuthToken.ROLE_OWNER or not token_obj.owner:
        return None
    return token_obj.owner


def _serialize_owner(owner):
    return {
        "id": owner.id,
        "username": owner.username,
        "email": owner.email,
        "business_name": owner.business_name,
        "phone": owner.phone,
        "is_paid": owner.is_paid,
        "subscription_active_until": (
            owner.subscription_active_until.isoformat()
            if owner.subscription_active_until
            else None
        ),
    }


def _serialize_shopboy(shopboy):
    return {
        "id": shopboy.id,
        "username": shopboy.username,
        "full_name": shopboy.full_name,
        "can_use_marketplace": shopboy.can_use_marketplace,
        "owner": {
            "id": shopboy.user_id,
            "business_name": shopboy.user.business_name,
        },
    }


def _serialize_agent(agent):
    return {
        "id": agent.id,
        "username": agent.username,
        "full_name": agent.full_name,
        "email": agent.email,
        "commission_rate": str(agent.commission_rate),
    }


def _serialize_category(category):
    return {
        "id": category.id,
        "name": category.name,
    }


def _serialize_owner_product(request, product):
    return {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "stock": str(product.stock),
        "low_stock_threshold": product.low_stock_threshold,
        "cost_price": _money(product.cost_price),
        "selling_price": _money(product.selling_price),
        "vat_status": product.vat_status,
        "category": _serialize_category(product.category) if product.category_id else None,
        "image_url": _abs_media_url(request, product.image),
    }


def _serialize_sale(sale):
    return {
        "id": sale.id,
        "total_amount": _money(sale.total_amount),
        "total_profit": _money(sale.total_profit),
        "vat_total": _money(sale.vat_total),
        "created_at": sale.created_at.isoformat(),
        "sales_channel": sale.sales_channel,
    }


def _serialize_sale_item(item):
    return {
        "product_name": item.product.name,
        "quantity": str(item.quantity),
        "price": _money(item.price),
        "profit": _money(item.profit),
        "vat_status": item.vat_status,
        "vat_rate": str(item.vat_rate),
        "vat_amount": _money(item.vat_amount),
        "vat_applicable": item.vat_applicable,
    }


def _cart_quantity_value(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0.00")


def _format_quantity(qty):
    qty = Decimal(str(qty))
    text = format(qty.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _get_shopboy_from_request(request):
    token_obj, _ = _get_auth_from_request(request)
    if not token_obj or token_obj.role != AuthToken.ROLE_SHOPBOY or not token_obj.shopboy:
        return None, None
    return token_obj.shopboy, token_obj


def _get_shopboy_cart(token_obj):
    cart, _ = ShopboyCart.objects.get_or_create(token=token_obj)
    if not isinstance(cart.data, dict):
        cart.data = {}
    return cart


def _get_owner_cart(token_obj):
    cart, _ = OwnerCart.objects.get_or_create(token=token_obj)
    if not isinstance(cart.data, dict):
        cart.data = {}
    return cart


def _serialize_owner_cart(request, cart, owner):
    items = []
    total = Decimal("0.00")
    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    products = Product.objects.filter(user=owner, id__in=product_ids)
    product_map = {str(p.id): p for p in products}

    for pid, row in cart.data.items():
        product = product_map.get(str(pid))
        if not product:
            continue
        qty = _cart_quantity_value(row.get("quantity"))
        if qty <= 0:
            continue
        price = Decimal(str(row.get("price", product.selling_price)))
        line_total = price * qty
        total += line_total
        items.append({
            "product_id": product.id,
            "name": product.name,
            "price": _money(price),
            "quantity": _format_quantity(qty),
            "stock": str(product.stock),
        })

    return {
        "items": items,
        "total": _money(total),
    }


def _serialize_shopboy_cart(request, cart, shopboy):
    items = []
    total = Decimal("0.00")
    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    products = Product.objects.filter(user=shopboy.user, id__in=product_ids)
    product_map = {str(p.id): p for p in products}

    for pid, row in cart.data.items():
        product = product_map.get(str(pid))
        if not product:
            continue
        qty = _cart_quantity_value(row.get("quantity"))
        if qty <= 0:
            continue
        price = Decimal(str(row.get("price", product.selling_price)))
        line_total = price * qty
        total += line_total
        items.append({
            "product_id": product.id,
            "name": product.name,
            "price": _money(price),
            "quantity": _format_quantity(qty),
            "stock": str(product.stock),
        })

    return {
        "items": items,
        "total": _money(total),
    }


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


# =============================
# Mobile Unified Auth + Owner APIs
# =============================


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_auth_login(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    role = (data.get("role") or "").strip().lower()
    if role in ("shopowner", "shop_owner", "owner"):
        role = AuthToken.ROLE_OWNER
    if role in ("shopboy", "shop_boy"):
        role = AuthToken.ROLE_SHOPBOY
    if role in ("agent",):
        role = AuthToken.ROLE_AGENT

    if role == AuthToken.ROLE_OWNER:
        identifier = (data.get("identifier") or "").strip()
        password = data.get("password") or ""
        if not identifier or not password:
            return _json_error("Email/username and password are required.")

        owner = _authenticate_with_identifier(request, identifier, password)
        if not owner:
            return _json_error("Invalid email/username or password.", status=401)

        if not subscription_is_active(owner):
            return _json_error("Subscription payment required.", status=402, code="subscription_required")

        token_obj = _issue_auth_token(AuthToken.ROLE_OWNER, owner=owner)
        return _json_success({
            "token": token_obj.token,
            "role": token_obj.role,
            "profile": _serialize_owner(owner),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    if role == AuthToken.ROLE_SHOPBOY:
        shop_code = (data.get("shop_code") or "").strip().upper()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""

        if not shop_code or not username or not password:
            return _json_error("Shop code, username, and password are required.")

        owner = User.objects.filter(shop_code__iexact=shop_code).first()
        if not owner:
            return _json_error("Invalid shop code.", status=401)

        shopboy = ShopBoy.objects.filter(
            username__iexact=username,
            is_active=True,
            user=owner,
        ).select_related("user").first()
        if not shopboy:
            return _json_error("Invalid username or password.", status=401)

        valid = check_password(password, shopboy.password) or (shopboy.password == password)
        if not valid:
            return _json_error("Invalid username or password.", status=401)

        token_obj = _issue_auth_token(AuthToken.ROLE_SHOPBOY, shopboy=shopboy)
        return _json_success({
            "token": token_obj.token,
            "role": token_obj.role,
            "profile": _serialize_shopboy(shopboy),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    if role == AuthToken.ROLE_AGENT:
        identifier = (data.get("identifier") or "").strip()
        password = data.get("password") or ""
        if not identifier or not password:
            return _json_error("Username/email and password are required.")

        agent = Agent.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier),
            is_active=True,
        ).first()
        if not agent or not check_password(password, agent.password):
            return _json_error("Invalid username/email or password.", status=401)

        if not agent.is_email_verified:
            return _json_error("Email not verified.", status=403, code="email_not_verified")

        token_obj = _issue_auth_token(AuthToken.ROLE_AGENT, agent=agent)
        return _json_success({
            "token": token_obj.token,
            "role": token_obj.role,
            "profile": _serialize_agent(agent),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    return _json_error("Invalid role. Use owner, shopboy, or agent.")


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_auth_logout(request):
    token_value = _get_auth_token_value(request)
    if token_value:
        AuthToken.objects.filter(token=token_value).update(is_revoked=True)
    return _json_success({"logged_out": True})


@csrf_exempt
@require_http_methods(["GET"])
def api_mobile_auth_me(request):
    token_obj, _ = _get_auth_from_request(request)
    if not token_obj:
        return _json_error("Unauthorized.", status=401)

    profile = None
    if token_obj.role == AuthToken.ROLE_OWNER and token_obj.owner:
        profile = _serialize_owner(token_obj.owner)
    elif token_obj.role == AuthToken.ROLE_SHOPBOY and token_obj.shopboy:
        profile = _serialize_shopboy(token_obj.shopboy)
    elif token_obj.role == AuthToken.ROLE_AGENT and token_obj.agent:
        profile = _serialize_agent(token_obj.agent)

    return _json_success({
        "role": token_obj.role,
        "profile": profile,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_categories(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        categories = Category.objects.filter(user=owner).order_by("name")
        return _json_success({
            "categories": [_serialize_category(cat) for cat in categories],
        })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    name = (data.get("name") or "").strip()
    if not name:
        return _json_error("Category name is required.")

    if Category.objects.filter(user=owner, name__iexact=name).exists():
        return _json_error("Category already exists.", status=409)

    category = Category.objects.create(user=owner, name=name)
    return _json_success({"category": _serialize_category(category)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_products(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        products = Product.objects.filter(user=owner)
        if q:
            products = products.filter(
                Q(name__icontains=q) |
                Q(code__icontains=q) |
                Q(category__name__icontains=q)
            )
        products = products.select_related("category").order_by("name")
        return _json_success({
            "products": [_serialize_owner_product(request, product) for product in products],
        })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    name = (data.get("name") or "").strip()
    category_id = data.get("category_id") or None
    code = (data.get("code") or "").strip()
    vat_status = (data.get("vat_status") or Product.VAT_STANDARD).strip()

    try:
        stock = _parse_stock(data.get("stock", 0))
        low_stock_threshold = int(data.get("low_stock_threshold", 5))
        cost_price = Decimal(data.get("cost_price"))
        selling_price = Decimal(data.get("selling_price"))
    except Exception:
        return _json_error("Invalid product values.")

    if not name:
        return _json_error("Product name is required.")

    if code:
        existing_code = Product.objects.filter(user=owner, code__iexact=code).exists()
        if existing_code:
            return _json_error(f"A product with code {code} already exists.", status=409)

    if category_id:
        category_exists = Category.objects.filter(id=category_id, user=owner).exists()
        if not category_exists:
            return _json_error("Selected category is invalid.")

    valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
    if vat_status not in valid_vat_status:
        vat_status = Product.VAT_STANDARD

    product = Product.objects.create(
        user=owner,
        name=name,
        code=code,
        category_id=category_id,
        stock=stock,
        cost_price=cost_price,
        selling_price=selling_price,
        low_stock_threshold=low_stock_threshold,
        vat_status=vat_status,
        image=request.FILES.get("image"),
    )
    return _json_success({"product": _serialize_owner_product(request, product)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_owner_product_detail(request, pk):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    product = get_object_or_404(Product.objects.select_related("category"), pk=pk, user=owner)

    if request.method == "GET":
        return _json_success({"product": _serialize_owner_product(request, product)})

    if request.method == "DELETE":
        product.delete()
        return _json_success({"deleted": True})

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    if "name" in data:
        product.name = (data.get("name") or "").strip()
    if "category_id" in data:
        category_id = data.get("category_id") or None
        if category_id:
            category_exists = Category.objects.filter(id=category_id, user=owner).exists()
            if not category_exists:
                return _json_error("Selected category is invalid.")
        product.category_id = category_id
    if "code" in data:
        code = (data.get("code") or "").strip()
        if code:
            existing_code = Product.objects.filter(user=owner, code__iexact=code).exclude(id=product.id).exists()
            if existing_code:
                return _json_error(f"A product with code {code} already exists.", status=409)
        product.code = code

    for field in ["stock", "low_stock_threshold", "cost_price", "selling_price"]:
        if field in data:
            try:
                if field == "stock":
                    product.stock = _parse_stock(data.get("stock"))
                elif field == "low_stock_threshold":
                    product.low_stock_threshold = int(data.get("low_stock_threshold") or 0)
                elif field == "cost_price":
                    product.cost_price = Decimal(data.get("cost_price"))
                elif field == "selling_price":
                    product.selling_price = Decimal(data.get("selling_price"))
            except Exception:
                return _json_error("Invalid product values.")

    vat_status = (data.get("vat_status") or "").strip()
    if vat_status:
        valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
        if vat_status in valid_vat_status:
            product.vat_status = vat_status

    if request.FILES.get("image"):
        product.image = request.FILES.get("image")

    product.save()
    return _json_success({"product": _serialize_owner_product(request, product)})


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_dashboard(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    today = timezone.localdate()
    today_sales = Sale.objects.filter(user=owner, created_at__date=today).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    today_profit = Sale.objects.filter(user=owner, created_at__date=today).aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
    total_products = Product.objects.filter(user=owner).count()
    low_stock_count = Product.objects.filter(user=owner, stock__lte=F("low_stock_threshold"), stock__gt=0).count()

    today_transactions = (
        Sale.objects.filter(user=owner, created_at__date=today)
        .annotate(items_count=Sum("items__quantity"))
        .order_by("-created_at")[:5]
    )

    top_products = (
        Product.objects.filter(user=owner)
        .annotate(total_sold=Sum("saleitem__quantity"))
        .order_by("-total_sold", "-created_at")[:6]
    )

    return _json_success({
        "today_date": today.isoformat(),
        "today_sales": _money(today_sales),
        "today_profit": _money(today_profit),
        "total_products": total_products,
        "low_stock_count": low_stock_count,
        "today_transactions": [
            {
                "id": sale.id,
                "items_count": float(sale.items_count or 0),
                "total_amount": _money(sale.total_amount),
                "total_profit": _money(sale.total_profit),
                "created_at": sale.created_at.isoformat(),
            }
            for sale in today_transactions
        ],
        "top_products": [
            {
                "id": product.id,
                "name": product.name,
                "selling_price": _money(product.selling_price),
                "stock": str(product.stock),
                "total_sold": float(product.total_sold or 0),
                "image_url": _abs_media_url(request, product.image),
            }
            for product in top_products
        ],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_pos(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    category_id = (request.GET.get("category") or "").strip()
    q = (request.GET.get("q") or "").strip()

    products = Product.objects.filter(user=owner)
    if category_id:
        products = products.filter(category_id=category_id)
    if q:
        products = products.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(category__name__icontains=q)
        )

    categories = Category.objects.filter(user=owner).order_by("name")
    cart = _get_owner_cart(token_obj)
    cart_payload = _serialize_owner_cart(request, cart, owner)

    last_sale = None
    if cart.last_sale_id:
        sale = Sale.objects.filter(user=owner, id=cart.last_sale_id).first()
        if sale:
            last_sale = {
                "id": sale.id,
                "total_amount": _money(sale.total_amount),
                "created_at": sale.created_at.isoformat(),
            }

    return _json_success({
        "products": [_serialize_owner_product(request, product) for product in products.select_related("category")],
        "categories": [_serialize_category(cat) for cat in categories],
        "cart": cart_payload,
        "last_sale": last_sale,
        "can_edit_price": True,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_add(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
        quantity = _parse_stock(data.get("quantity", 1))
    except Exception:
        return _json_error("Invalid product or quantity.")

    product = get_object_or_404(Product, id=product_id, user=owner)
    if product.stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_owner_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > product.stock:
        desired_qty = product.stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(product.selling_price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_owner_cart(request, cart, owner)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_add_by_code(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    code = (data.get("code") or "").strip()
    if not code:
        return _json_error("Product code is required.")

    try:
        quantity = _parse_stock(data.get("quantity", 1))
    except Exception:
        return _json_error("Invalid quantity.")

    product = Product.objects.filter(user=owner, code__iexact=code).first()
    if not product:
        return _json_error(f"No product found for code {code}.", status=404)
    if product.stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_owner_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > product.stock:
        desired_qty = product.stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(product.selling_price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_owner_cart(request, cart, owner)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_update(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
    except Exception:
        return _json_error("Invalid product.")

    action = (data.get("action") or "").strip()
    quantity_raw = data.get("quantity")
    price_raw = data.get("price")

    cart = _get_owner_cart(token_obj)
    product_key = str(product_id)
    if product_key not in cart.data:
        return _json_error("Item not in cart.", status=404)

    product = get_object_or_404(Product, id=product_id, user=owner)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))

    if action == "price":
        try:
            price = Decimal(str(price_raw))
        except Exception:
            return _json_error("Invalid price.")
        if price < 0:
            return _json_error("Price cannot be negative.")
        cart.data[product_key]["price"] = float(price.quantize(Decimal("0.01")))
    elif action == "increase":
        desired_qty = current_qty + Decimal("1")
        if desired_qty > product.stock:
            desired_qty = product.stock
        cart.data[product_key]["quantity"] = _format_quantity(desired_qty)
    elif action == "decrease":
        desired_qty = current_qty - Decimal("1")
        if desired_qty <= 0:
            cart.data.pop(product_key, None)
        else:
            cart.data[product_key]["quantity"] = _format_quantity(desired_qty)
    else:
        quantity = _cart_quantity_value(quantity_raw)
        if quantity <= 0:
            cart.data.pop(product_key, None)
        elif quantity > product.stock:
            cart.data[product_key]["quantity"] = _format_quantity(product.stock)
        else:
            cart.data[product_key]["quantity"] = _format_quantity(quantity)

    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_owner_cart(request, cart, owner)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_remove(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
    except Exception:
        return _json_error("Invalid product.")

    cart = _get_owner_cart(token_obj)
    cart.data.pop(str(product_id), None)
    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_owner_cart(request, cart, owner)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_checkout(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    cart = _get_owner_cart(token_obj)
    if not cart.data:
        return _json_error("Cart is empty.", status=400)

    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(user=owner, id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        for pid, item in cart.data.items():
            product = product_map.get(str(pid))
            if not product:
                return _json_error("A cart item no longer exists.", status=409)

            quantity = _cart_quantity_value(item.get("quantity"))
            if quantity <= 0:
                continue

            if product.stock < quantity:
                return _json_error(f"Not enough stock for {product.name}. Available: {product.stock}.", status=409)

            price = Decimal(str(item.get("price", product.selling_price)))
            cost = Decimal(str(item.get("cost", product.cost_price)))
            line_total = price * quantity
            line_profit = (price - cost) * quantity
            total_amount += line_total
            total_profit += line_profit

            line_items.append({
                "product": product,
                "quantity": quantity,
                "price": price,
                "profit": line_profit,
                "line_total": line_total,
            })

        if not line_items:
            return _json_error("Cart is empty.", status=400)

        vat_registered = _vat_registered_for_sale(owner, timezone.now(), total_amount)
        vat_total = Decimal("0.00")
        for row in line_items:
            vat_status, vat_applicable, vat_rate, vat_amount = _calculate_item_vat(
                row["product"],
                row["line_total"],
                vat_registered,
            )
            row["vat_status"] = vat_status
            row["vat_applicable"] = vat_applicable
            row["vat_rate"] = vat_rate
            row["vat_amount"] = vat_amount
            vat_total += vat_amount

        sale = Sale.objects.create(
            user=owner,
            sales_channel=Sale.CHANNEL_OWNER_POS,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            vat_total=vat_total.quantize(Decimal("0.01")),
        )

        for row in line_items:
            SaleItem.objects.create(
                sale=sale,
                product=row["product"],
                quantity=row["quantity"],
                price=row["price"].quantize(Decimal("0.01")),
                profit=row["profit"].quantize(Decimal("0.01")),
                vat_status=row["vat_status"],
                vat_rate=row["vat_rate"],
                vat_amount=row["vat_amount"],
                vat_applicable=row["vat_applicable"],
            )
            row["product"].stock -= row["quantity"]
            row["product"].save(update_fields=["stock"])

    cart.data = {}
    cart.last_sale_id = sale.id
    cart.save(update_fields=["data", "last_sale_id", "updated_at"])

    return _json_success({
        "sale": {
            "id": sale.id,
            "total_amount": _money(sale.total_amount),
            "created_at": sale.created_at.isoformat(),
        },
        "cart": _serialize_owner_cart(request, cart, owner),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_inventory(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    q = (request.GET.get("q") or "").strip()
    products = Product.objects.filter(user=owner)
    if q:
        products = products.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(category__name__icontains=q)
        )

    products = products.select_related("category")

    total_products = products.count()
    total_value = sum((p.selling_price * p.stock for p in products), Decimal("0.00"))
    low_stock = products.filter(stock__lte=F("low_stock_threshold"), stock__gt=0).count()
    out_of_stock = products.filter(stock=0).count()

    return _json_success({
        "summary": {
            "total_products": total_products,
            "total_value": _money(total_value),
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
        },
        "products": [_serialize_owner_product(request, product) for product in products.order_by("name")],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_generate_product_code(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    code = _generate_product_code(owner)
    if not code:
        return _json_error("Unable to generate code.", status=500)
    return _json_success({ "code": code })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_product_labels(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    products = Product.objects.filter(user=owner).order_by("name")
    updated = False
    for product in products:
        if not product.code:
            product.code = _generate_product_code(owner)
            updated = True
    if updated:
        Product.objects.bulk_update(products, ["code"])

    return _json_success({
        "products": [
            {
                "id": product.id,
                "name": product.name,
                "code": product.code,
            }
            for product in products
        ],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_sales_history(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    start_date = parse_date((request.GET.get("start_date") or "").strip()) if request.GET.get("start_date") else None
    end_date = parse_date((request.GET.get("end_date") or "").strip()) if request.GET.get("end_date") else None
    q = (request.GET.get("q") or "").strip()
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    sales = (
        Sale.objects.filter(user=owner)
        .select_related("handled_by_shopboy")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    if start_date:
        sales = sales.filter(created_at__date__gte=start_date)
    if end_date:
        sales = sales.filter(created_at__date__lte=end_date)
    if q:
        sales = sales.filter(
            Q(items__product__name__icontains=q) |
            Q(handled_by_shopboy__full_name__icontains=q) |
            Q(handled_by_shopboy__username__icontains=q) |
            Q(sales_channel__icontains=q) |
            Q(id__iexact=q)
        ).distinct()

    total_sales = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    total_profit = sales.aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
    total_transactions = sales.count()

    return _json_success({
        "summary": {
            "total_sales": _money(total_sales),
            "total_profit": _money(total_profit),
            "total_transactions": total_transactions,
        },
        "sales": [
            {
                "id": sale.id,
                "items_count": float(sale.items.aggregate(total=Sum("quantity"))["total"] or 0),
                "total_amount": _money(sale.total_amount),
                "total_profit": _money(sale.total_profit),
                "created_at": sale.created_at.isoformat(),
                "sales_channel": sale.sales_channel,
                "handled_by": sale.handled_by_shopboy.full_name if sale.handled_by_shopboy else "",
            }
            for sale in sales
        ],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_sale_detail(request, sale_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    sale = get_object_or_404(
        Sale.objects.select_related("handled_by_shopboy").prefetch_related("items__product"),
        id=sale_id,
        user=owner,
    )

    return _json_success({
        "sale": _serialize_sale(sale),
        "items": [_serialize_sale_item(item) for item in sale.items.all()],
    })


def _serialize_expense(expense):
    return {
        "id": expense.id,
        "category": expense.category,
        "title": expense.title,
        "amount": _money(expense.amount),
        "date": expense.date.isoformat(),
        "created_at": expense.created_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_expenses(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        expenses = Expense.objects.filter(user=owner).order_by("-date", "-created_at")
        if q:
            expenses = expenses.filter(
                Q(title__icontains=q) |
                Q(category__icontains=q)
            )

        total_amount = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return _json_success({
            "total_amount": _money(total_amount),
            "expenses": [_serialize_expense(exp) for exp in expenses],
            "categories": [choice[0] for choice in Expense.CATEGORY_CHOICES],
        })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    category = (data.get("category") or "").strip()
    title = (data.get("title") or "").strip()
    amount_raw = data.get("amount")
    date_raw = (data.get("date") or "").strip()

    valid_categories = {choice[0] for choice in Expense.CATEGORY_CHOICES}
    if category not in valid_categories:
        category = "Other"

    if not title:
        return _json_error("Title is required.")

    try:
        amount = Decimal(str(amount_raw))
        if amount < 0:
            raise ValueError
    except Exception:
        return _json_error("Amount must be a valid non-negative number.")

    date = parse_date(date_raw)
    if not date:
        return _json_error("Date is required.")

    expense = Expense.objects.create(
        user=owner,
        category=category,
        title=title,
        amount=amount,
        date=date,
    )
    return _json_success({"expense": _serialize_expense(expense)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_owner_expense_detail(request, expense_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    expense = get_object_or_404(Expense, id=expense_id, user=owner)

    if request.method == "GET":
        return _json_success({"expense": _serialize_expense(expense)})

    if request.method == "DELETE":
        expense.delete()
        return _json_success({"deleted": True})

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    if "category" in data:
        category = (data.get("category") or "").strip()
        valid_categories = {choice[0] for choice in Expense.CATEGORY_CHOICES}
        if category in valid_categories:
            expense.category = category

    if "title" in data:
        title = (data.get("title") or "").strip()
        if title:
            expense.title = title

    if "amount" in data:
        try:
            amount = Decimal(str(data.get("amount")))
            if amount < 0:
                raise ValueError
            expense.amount = amount
        except Exception:
            return _json_error("Amount must be a valid non-negative number.")

    if "date" in data:
        date = parse_date((data.get("date") or "").strip())
        if date:
            expense.date = date

    expense.save()
    return _json_success({"expense": _serialize_expense(expense)})


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_dashboard(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    q = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("category") or "").strip()

    products = Product.objects.filter(user=shopboy.user)
    if category_id:
        products = products.filter(category_id=category_id)
    if q:
        products = products.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(category__name__icontains=q)
        )

    categories = Category.objects.filter(user=shopboy.user).order_by("name")
    cart = _get_shopboy_cart(token_obj)
    cart_payload = _serialize_shopboy_cart(request, cart, shopboy)

    last_sale = None
    if cart.last_sale_id:
        sale = Sale.objects.filter(id=cart.last_sale_id, handled_by_shopboy=shopboy).first()
        if sale:
            last_sale = {
                "id": sale.id,
                "total_amount": _money(sale.total_amount),
                "created_at": sale.created_at.isoformat(),
            }

    return _json_success({
        "shopboy": _serialize_shopboy(shopboy),
        "products": [_serialize_owner_product(request, product) for product in products.select_related("category")],
        "categories": [_serialize_category(cat) for cat in categories],
        "cart": cart_payload,
        "last_sale": last_sale,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_cart_add(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
        quantity = _parse_stock(data.get("quantity", 1))
    except Exception:
        return _json_error("Invalid product or quantity.")

    product = get_object_or_404(Product, id=product_id, user=shopboy.user)
    if product.stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_shopboy_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > product.stock:
        desired_qty = product.stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(product.selling_price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_shopboy_cart(request, cart, shopboy)})


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_cart_add_by_code(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    code = (data.get("code") or "").strip()
    if not code:
        return _json_error("Product code is required.")

    try:
        quantity = _parse_stock(data.get("quantity", 1))
    except Exception:
        return _json_error("Invalid quantity.")

    product = Product.objects.filter(user=shopboy.user, code__iexact=code).first()
    if not product:
        return _json_error(f"No product found for code {code}.", status=404)
    if product.stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_shopboy_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > product.stock:
        desired_qty = product.stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(product.selling_price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_shopboy_cart(request, cart, shopboy)})


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_cart_update(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
    except Exception:
        return _json_error("Invalid product.")

    action = (data.get("action") or "").strip()
    quantity_raw = data.get("quantity")

    cart = _get_shopboy_cart(token_obj)
    product_key = str(product_id)
    if product_key not in cart.data:
        return _json_error("Item not in cart.", status=404)

    product = get_object_or_404(Product, id=product_id, user=shopboy.user)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))

    if action == "increase":
        desired_qty = current_qty + Decimal("1")
        if desired_qty > product.stock:
            desired_qty = product.stock
        cart.data[product_key]["quantity"] = _format_quantity(desired_qty)
    elif action == "decrease":
        desired_qty = current_qty - Decimal("1")
        if desired_qty <= 0:
            cart.data.pop(product_key, None)
        else:
            cart.data[product_key]["quantity"] = _format_quantity(desired_qty)
    else:
        try:
            quantity = _cart_quantity_value(quantity_raw)
        except Exception:
            return _json_error("Invalid quantity.")
        if quantity <= 0:
            cart.data.pop(product_key, None)
        elif quantity > product.stock:
            cart.data[product_key]["quantity"] = _format_quantity(product.stock)
        else:
            cart.data[product_key]["quantity"] = _format_quantity(quantity)

    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_shopboy_cart(request, cart, shopboy)})


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_cart_remove(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        product_id = int(data.get("product_id"))
    except Exception:
        return _json_error("Invalid product.")

    cart = _get_shopboy_cart(token_obj)
    cart.data.pop(str(product_id), None)
    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_shopboy_cart(request, cart, shopboy)})


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_cart_checkout(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    cart = _get_shopboy_cart(token_obj)
    if not cart.data:
        return _json_error("Cart is empty.", status=400)

    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(user=shopboy.user, id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        for pid, item in cart.data.items():
            product = product_map.get(str(pid))
            if not product:
                return _json_error("A cart item no longer exists.", status=409)

            quantity = _cart_quantity_value(item.get("quantity"))
            if quantity <= 0:
                continue

            if product.stock < quantity:
                return _json_error(f"Not enough stock for {product.name}. Available: {product.stock}.", status=409)

            price = Decimal(str(item.get("price", product.selling_price)))
            cost = Decimal(str(item.get("cost", product.cost_price)))
            line_total = price * quantity
            line_profit = (price - cost) * quantity
            total_amount += line_total
            total_profit += line_profit

            line_items.append({
                "product": product,
                "quantity": quantity,
                "price": price,
                "profit": line_profit,
            })

        if not line_items:
            return _json_error("Cart is empty.", status=400)

        sale = Sale.objects.create(
            user=shopboy.user,
            sales_channel=Sale.CHANNEL_SHOPBOY_PORTAL,
            handled_by_shopboy=shopboy,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
        )

        for row in line_items:
            SaleItem.objects.create(
                sale=sale,
                product=row["product"],
                quantity=row["quantity"],
                price=row["price"].quantize(Decimal("0.01")),
                profit=row["profit"].quantize(Decimal("0.01")),
            )
            row["product"].stock -= row["quantity"]
            row["product"].save(update_fields=["stock"])

    cart.data = {}
    cart.last_sale_id = sale.id
    cart.save(update_fields=["data", "last_sale_id", "updated_at"])

    return _json_success({
        "sale": {
            "id": sale.id,
            "total_amount": _money(sale.total_amount),
            "created_at": sale.created_at.isoformat(),
        },
        "cart": _serialize_shopboy_cart(request, cart, shopboy),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_profile(request):
    shopboy, _ = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    owner = shopboy.user
    return _json_success({
        "shopboy": _serialize_shopboy(shopboy),
        "owner": {
            "id": owner.id,
            "business_name": owner.business_name,
            "username": owner.username,
            "phone": owner.phone,
        },
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_sales(request):
    shopboy, _ = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    start_date = parse_date((request.GET.get("start_date") or "").strip()) if request.GET.get("start_date") else None
    end_date = parse_date((request.GET.get("end_date") or "").strip()) if request.GET.get("end_date") else None
    q = (request.GET.get("q") or "").strip()
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    sales = Sale.objects.filter(handled_by_shopboy=shopboy).order_by("-created_at")
    if start_date:
        sales = sales.filter(created_at__date__gte=start_date)
    if end_date:
        sales = sales.filter(created_at__date__lte=end_date)
    if q:
        sales = sales.filter(
            Q(items__product__name__icontains=q) |
            Q(id__iexact=q)
        ).distinct()

    return _json_success({
        "sales": [_serialize_sale(sale) for sale in sales],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_sale_detail(request, sale_id):
    shopboy, _ = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    sale = get_object_or_404(
        Sale.objects.select_related("handled_by_shopboy").prefetch_related("items__product"),
        id=sale_id,
        handled_by_shopboy=shopboy,
    )

    return _json_success({
        "sale": _serialize_sale(sale),
        "items": [_serialize_sale_item(item) for item in sale.items.all()],
    })


def _require_shopboy_marketplace(shopboy):
    return bool(shopboy and shopboy.can_use_marketplace and shopboy.is_active)


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_marketplace_orders(request):
    shopboy, _ = _get_shopboy_from_request(request)
    if not _require_shopboy_marketplace(shopboy):
        return _json_error("You are not allowed to handle marketplace orders.", status=403)

    orders = MarketplaceOrder.objects.filter(
        shop_owner=shopboy.user,
    ).filter(
        Q(assigned_shopboy=shopboy) | Q(assigned_shopboy__isnull=True)
    ).select_related("assigned_shopboy", "shop_owner").order_by("-created_at")

    return _json_success({
        "orders": [_serialize_order(request, order) for order in orders],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_marketplace_order_detail(request, public_id):
    shopboy, _ = _get_shopboy_from_request(request)
    if not _require_shopboy_marketplace(shopboy):
        return _json_error("You are not allowed to handle marketplace orders.", status=403)

    order = get_object_or_404(
        MarketplaceOrder.objects.select_related("shop_owner", "assigned_shopboy").prefetch_related("items__product", "messages"),
        public_id=public_id,
    )
    if order.shop_owner_id != shopboy.user_id:
        return _json_error("Access denied.", status=403)
    if order.assigned_shopboy_id not in (None, shopboy.id):
        return _json_error("Access denied.", status=403)

    messages = order.messages.order_by("created_at")
    next_map = {
        MarketplaceOrder.STATUS_PENDING: MarketplaceOrder.STATUS_CONFIRMED,
        MarketplaceOrder.STATUS_CONFIRMED: MarketplaceOrder.STATUS_PAID,
        MarketplaceOrder.STATUS_PAID: MarketplaceOrder.STATUS_SHIPPED,
        MarketplaceOrder.STATUS_SHIPPED: MarketplaceOrder.STATUS_DELIVERED,
    }
    next_status = next_map.get(order.status)

    return _json_success({
        "order": _serialize_order(request, order),
        "items": [_serialize_order_item(item) for item in order.items.all()],
        "messages": [_serialize_message(msg) for msg in messages],
        "next_status": next_status,
        "status_choices": MarketplaceOrder.STATUS_CHOICES,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_marketplace_order_message(request, public_id):
    shopboy, _ = _get_shopboy_from_request(request)
    if not _require_shopboy_marketplace(shopboy):
        return _json_error("You are not allowed to handle marketplace orders.", status=403)

    order = get_object_or_404(MarketplaceOrder, public_id=public_id)
    if order.shop_owner_id != shopboy.user_id:
        return _json_error("Access denied.", status=403)
    if order.assigned_shopboy_id not in (None, shopboy.id):
        return _json_error("Access denied.", status=403)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")
    text = (data.get("message") or "").strip()
    if not text:
        return _json_error("Message cannot be empty.")

    msg = MarketplaceChatMessage.objects.create(
        order=order,
        sender_type=MarketplaceChatMessage.SENDER_SELLER,
        message=text,
    )
    return _json_success({
        "message": _serialize_message(msg),
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_marketplace_order_status(request, public_id):
    shopboy, _ = _get_shopboy_from_request(request)
    if not _require_shopboy_marketplace(shopboy):
        return _json_error("You are not allowed to handle marketplace orders.", status=403)

    order = get_object_or_404(MarketplaceOrder, public_id=public_id)
    if order.shop_owner_id != shopboy.user_id:
        return _json_error("Access denied.", status=403)
    if order.assigned_shopboy_id not in (None, shopboy.id):
        return _json_error("Access denied.", status=403)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")
    status = (data.get("status") or "").strip()
    valid_statuses = {choice[0] for choice in MarketplaceOrder.STATUS_CHOICES}
    if status not in valid_statuses:
        return _json_error("Invalid status.")

    if order.status in [MarketplaceOrder.STATUS_DELIVERED, MarketplaceOrder.STATUS_CANCELLED]:
        return _json_error("Order is closed.", status=400)

    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.select_for_update().select_related("assigned_shopboy").get(id=order.id)
            if order.assigned_shopboy_id is None:
                order.assigned_shopboy = shopboy

            if status in [MarketplaceOrder.STATUS_CONFIRMED, MarketplaceOrder.STATUS_PAID] and order.sale_id is None:
                items = list(order.items.select_related("product").select_for_update())
                total_amount = Decimal("0.00")
                total_profit = Decimal("0.00")
                vat_total = Decimal("0.00")

                for item in items:
                    product = item.product
                    if product.stock < item.quantity:
                        return _json_error(f"Not enough stock for {product.name}.", status=400)
                    line_total = item.unit_price * item.quantity
                    line_profit = (item.unit_price - product.cost_price) * item.quantity
                    total_amount += line_total
                    total_profit += line_profit

                vat_registered = _vat_registered_for_sale(order.shop_owner, timezone.now(), total_amount)

                sale = Sale.objects.create(
                    user=order.shop_owner,
                    sales_channel=Sale.CHANNEL_MARKETPLACE,
                    handled_by_shopboy=order.assigned_shopboy,
                    total_amount=total_amount.quantize(Decimal("0.01")),
                    total_profit=total_profit.quantize(Decimal("0.01")),
                    vat_total=Decimal("0.00"),
                )
                for item in items:
                    product = item.product
                    line_total = item.unit_price * item.quantity
                    line_profit = (item.unit_price - product.cost_price) * item.quantity
                    vat_status, vat_applicable, vat_rate, vat_amount = _calculate_item_vat(
                        product,
                        line_total,
                        vat_registered,
                    )
                    vat_total += vat_amount
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        quantity=item.quantity,
                        price=item.unit_price.quantize(Decimal("0.01")),
                        profit=line_profit.quantize(Decimal("0.01")),
                        vat_status=vat_status,
                        vat_rate=vat_rate,
                        vat_amount=vat_amount,
                        vat_applicable=vat_applicable,
                    )
                    product.stock -= item.quantity
                    product.save(update_fields=["stock"])

                if vat_total:
                    sale.vat_total = vat_total.quantize(Decimal("0.01"))
                    sale.save(update_fields=["vat_total"])

                order.sale = sale
                order.total_amount = total_amount.quantize(Decimal("0.01"))

            order.status = status
            fields_to_update = ["status", "updated_at"]
            if order.sale_id is not None:
                fields_to_update.extend(["total_amount", "sale"])
            if order.assigned_shopboy_id is None:
                fields_to_update.append("assigned_shopboy")
            order.save(update_fields=fields_to_update)

            MarketplaceChatMessage.objects.create(
                order=order,
                sender_type=MarketplaceChatMessage.SENDER_SYSTEM,
                message=f"Order status updated to \"{dict(MarketplaceOrder.STATUS_CHOICES).get(status, status)}\"."
            )

        return _json_success({ "status": order.status })
    except Exception:
        return _json_error("Server error while updating status. Please try again.", status=500)
