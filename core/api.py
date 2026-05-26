import json
import random
import re
import secrets
from datetime import timedelta, datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import Q, Sum, F, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    Agent,
    AuthToken,
    Category,
    Expense,
    MarketplaceBuyer,
    MarketplaceBuyerToken,
    MarketplaceChatMessage,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceShopProfile,
    BranchInventory,
    HouseInquiry,
    HouseInquiryMessage,
    HouseListing,
    HouseListingImage,
    Product,
    RentalPayment,
    RentalRecord,
    Sale,
    SaleItem,
    ShopBranch,
    ShopBoy,
    ShopboyCart,
    TenantRecord,
    OwnerCart,
    User,
    Customer,
    CustomerScanCart,
    AIReceiptScan,
    AIAssistantMessage,
)
from . import ai as ai_engine

PLAN_LIMITS = {
    "starter": {"name": "Starter", "product_limit": 1000, "staff_limit": 0, "branch_limit": 1},
    "growth": {"name": "Growth", "product_limit": 5000, "staff_limit": 3, "branch_limit": 2},
    "business": {"name": "Business", "product_limit": 20000, "staff_limit": 10, "branch_limit": 5},
    "pro": {"name": "Pro / Enterprise", "product_limit": None, "staff_limit": None, "branch_limit": None},
}


def _plan_limit(owner, key):
    plan = PLAN_LIMITS.get(getattr(owner, "plan", "starter")) or PLAN_LIMITS["starter"]
    return plan, plan.get(key)


def _plan_limit_error(limit_name, plan_name):
    return f"Your {plan_name} plan has reached its {limit_name} limit. Upgrade your plan to add more."


def _json_feature_required(owner, feature):
    if _plan_has_feature(owner, feature):
        return None
    return _json_error(_feature_upgrade_message(feature), status=403, feature=feature, upgrade_required=True)


def _normalize_branch_id(value):
    branch_id = str(value or "").strip()
    return "" if branch_id.lower() in {"", "all", "none", "null"} else branch_id


def _branch_scoped_products(owner, branch, queryset=None):
    queryset = queryset if queryset is not None else Product.objects.filter(user=owner)
    if not branch:
        return queryset
    return queryset.filter(
        Q(branch_inventory__branch=branch, branch_inventory__is_active=True) |
        Q(category__branch=branch)
    ).distinct()


def _branch_scoped_categories(owner, branch, queryset=None):
    queryset = queryset if queryset is not None else Category.objects.filter(user=owner)
    if not branch:
        return queryset
    return queryset.filter(
        Q(branch=branch) |
        Q(product__branch_inventory__branch=branch, product__branch_inventory__is_active=True)
    ).distinct()


def _branch_inventory_for_product(product, branch):
    if not branch:
        return None
    inventory = BranchInventory.objects.filter(branch=branch, product=product, is_active=True).first()
    if inventory:
        product._branch_inventory = inventory
    return inventory


from .views import (
    _authenticate_with_identifier,
    _calculate_item_vat,
    _parse_stock,
    _ensure_marketplace_profiles,
    _get_assigned_shopboy,
    _login_account_type_options,
    _get_marketplace_settings,
    _password_meets_rules,
    _ensure_shop_code,
    _valid_accounts_for_credentials,
    _vat_registered_for_sale,
    _year_turnover,
    _is_vat_registered,
    _vat_registration_note,
    _generate_product_code,
    _sync_global_product_stock,
    _plan_has_feature,
    _feature_upgrade_message,
    _feature_entitlements,
    _subscription_upgrade_options,
    _marketplace_house_queryset,
    VAT_RATE,
    _send_marketplace_reset_code,
    _send_marketplace_verification_code,
    _send_signup_code,
    _plan_for_slug,
    TRIAL_DAYS,
    _refresh_house_availability,
    _sync_rental_payment_state,
)
from .subscription import subscription_is_active
from .utils.notifications import send_email, send_sms


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


USER_BANK_FIELDS = ("bank_name", "bank_account_number", "bank_account_name")


def _defer_user_bank_fields(queryset, prefix=""):
    return queryset.defer(*(f"{prefix}{field}" for field in USER_BANK_FIELDS))


@require_http_methods(["GET"])
def api_health(request):
    return _json_success({
        "status": "ok",
        "time": timezone.now().isoformat(),
    })


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


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


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


def _marketplace_buyer_needs_phone_verification(buyer):
    return False


def _marketplace_buyer_is_fully_verified(buyer):
    if not buyer or not buyer.is_email_verified:
        return False
    if _marketplace_buyer_needs_phone_verification(buyer) and not buyer.is_phone_verified:
        return False
    return True


def _send_marketplace_pending_verification_codes(buyer):
    if not buyer.is_email_verified:
        _send_marketplace_verification_code(buyer)


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


def _require_housing_owner(request):
    owner = _require_owner(request)
    if not owner or owner.account_type != User.ACCOUNT_TYPE_HOUSING:
        return None
    return owner


def _serialize_owner(owner):
    return {
        "id": owner.id,
        "username": owner.username,
        "email": owner.email,
        "business_name": owner.business_name,
        "account_type": owner.account_type,
        "account_type_label": owner.get_account_type_display(),
        "phone": owner.phone,
        "bank": {
            "bank_name": owner.bank_name or "",
            "account_number": owner.bank_account_number or "",
            "account_name": owner.bank_account_name or "",
        },
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
        "role": shopboy.role,
        "role_label": shopboy.get_role_display(),
        "can_use_marketplace": shopboy.can_use_marketplace,
        "is_active": shopboy.is_active,
        "branch": _serialize_branch(shopboy.branch) if getattr(shopboy, "branch_id", None) else None,
        "owner": {
            "id": shopboy.user_id,
            "business_name": shopboy.user.business_name,
            "bank": {
                "bank_name": shopboy.user.bank_name or "",
                "account_number": shopboy.user.bank_account_number or "",
                "account_name": shopboy.user.bank_account_name or "",
            },
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


def _serialize_branch(branch):
    if not branch:
        return None
    return {
        "id": branch.id,
        "name": branch.name,
        "code": branch.code or "",
        "phone": branch.phone or "",
        "address": branch.address or "",
        "city": branch.city or "",
        "state": branch.state or "",
        "latitude": str(branch.latitude) if branch.latitude is not None else "",
        "longitude": str(branch.longitude) if branch.longitude is not None else "",
        "is_active": branch.is_active,
        "is_default": branch.is_default,
    }


def _branch_inventory_row(branch, product):
    if not branch:
        return None
    if hasattr(product, "_branch_inventory"):
        return product._branch_inventory
    return BranchInventory.objects.filter(branch=branch, product=product).first()


def _effective_product_stock(product, branch=None):
    inventory = _branch_inventory_row(branch, product)
    if inventory and inventory.track_separately:
        return inventory.stock
    return product.stock


def _effective_product_price(product, branch=None):
    inventory = _branch_inventory_row(branch, product)
    if inventory and inventory.selling_price is not None:
        return inventory.selling_price
    return product.selling_price


def _serialize_owner_product(request, product, branch=None):
    inventory = _branch_inventory_row(branch, product)
    effective_stock = _effective_product_stock(product, branch)
    effective_price = _effective_product_price(product, branch)
    payload = {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "stock": str(effective_stock),
        "global_stock": str(product.stock),
        "low_stock_threshold": product.low_stock_threshold,
        "cost_price": _money(product.cost_price),
        "selling_price": _money(effective_price),
        "global_selling_price": _money(product.selling_price),
        "vat_status": product.vat_status,
        "category": _serialize_category(product.category) if product.category_id else None,
        "image_url": _abs_media_url(request, product.image),
        "branch_inventory": {
            "track_separately": inventory.track_separately if inventory else False,
            "is_active": inventory.is_active if inventory else True,
            "stock": str(inventory.stock) if inventory else "",
            "selling_price": _money(inventory.selling_price) if inventory and inventory.selling_price is not None else "",
        } if branch else None,
    }
    return payload


def _serialize_sale(sale):
    try:
        remaining = Decimal(sale.total_amount or "0.00") - Decimal(sale.amount_paid or "0.00")
    except Exception:
        remaining = Decimal("0.00")
    if remaining < 0:
        remaining = Decimal("0.00")
    return {
        "id": sale.id,
        "branch": _serialize_branch(sale.branch) if getattr(sale, "branch_id", None) else None,
        "total_amount": _money(sale.total_amount),
        "total_profit": _money(sale.total_profit),
        "vat_total": _money(sale.vat_total),
        "amount_paid": _money(getattr(sale, "amount_paid", Decimal("0.00"))),
        "payment_status": getattr(sale, "payment_status", "paid"),
        "remaining_balance": _money(remaining),
        "customer_name": getattr(sale, "customer_name", ""),
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


def _scanner_order_reference(sale):
    return f"VS-{sale.id:06d}"


def _serialize_scanner_pending_sale(sale):
    return {
        "id": sale.id,
        "reference": _scanner_order_reference(sale),
        "customer_name": sale.display_customer_name or "Scanner Customer",
        "total_amount": _money(sale.total_amount),
        "payment_status": sale.payment_status,
        "created_at": sale.created_at.isoformat(),
        "branch": _serialize_branch(sale.branch) if getattr(sale, "branch_id", None) else None,
        "items": [_serialize_sale_item(item) for item in sale.items.all()],
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


def _cart_money_value(value, default=Decimal("0.00")):
    try:
        amount = Decimal(str(value if value not in (None, "") else default))
    except Exception:
        amount = Decimal(str(default or "0.00"))
    if amount < 0:
        amount = Decimal("0.00")
    return amount.quantize(Decimal("0.01"))


def _derive_payment_status(total_amount, amount_paid):
    if amount_paid >= total_amount:
        return Sale.PAYMENT_PAID
    if amount_paid > 0:
        return Sale.PAYMENT_PARTIAL
    return Sale.PAYMENT_LOAN


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


OWNER_CART_BRANCHES_KEY = "branch_carts"


def _cart_key_for_branch(branch):
    return str(branch.id) if branch else "all"


def _owner_cart_branches(cart):
    if not isinstance(cart.data, dict):
        cart.data = {}
    branch_carts = cart.data.get(OWNER_CART_BRANCHES_KEY)
    if not isinstance(branch_carts, dict):
        legacy_rows = {
            key: value
            for key, value in cart.data.items()
            if str(key).isdigit() and isinstance(value, dict)
        }
        branch_carts = {}
        if legacy_rows:
            branch_carts["all"] = legacy_rows
        cart.data = {OWNER_CART_BRANCHES_KEY: branch_carts}
    return branch_carts


def _owner_cart_data(cart, branch):
    branch_carts = _owner_cart_branches(cart)
    key = _cart_key_for_branch(branch)
    rows = branch_carts.get(key)
    if rows is None and key != "all" and branch_carts.get("all"):
        rows = branch_carts.pop("all")
        branch_carts[key] = rows
        cart.data = {OWNER_CART_BRANCHES_KEY: branch_carts}
    return dict(rows or {})


def _set_owner_cart_data(cart, branch, rows):
    branch_carts = _owner_cart_branches(cart)
    key = _cart_key_for_branch(branch)
    if rows:
        branch_carts[key] = rows
    else:
        branch_carts.pop(key, None)
    cart.data = {OWNER_CART_BRANCHES_KEY: branch_carts}


def _serialize_owner_cart(request, cart, owner, branch=None):
    items = []
    total = Decimal("0.00")
    cart_rows = _owner_cart_data(cart, branch)
    product_ids = [int(pid) for pid in cart_rows.keys() if str(pid).isdigit()]
    products = _branch_scoped_products(owner, branch, Product.objects.filter(user=owner, id__in=product_ids))
    products = list(products)
    if branch:
        inventory_map = {
            item.product_id: item
            for item in BranchInventory.objects.filter(branch=branch, product__in=products)
        }
        for product in products:
            product._branch_inventory = inventory_map.get(product.id)
    product_map = {str(p.id): p for p in products}

    for pid, row in cart_rows.items():
        product = product_map.get(str(pid))
        if not product:
            continue
        qty = _cart_quantity_value(row.get("quantity"))
        if qty <= 0:
            continue
        price = _cart_money_value(row.get("price"), product.selling_price)
        line_total = price * qty
        total += line_total
        items.append({
            "product_id": product.id,
            "name": product.name,
            "price": _money(price),
            "quantity": _format_quantity(qty),
            "stock": str(_effective_product_stock(product, branch)),
        })

    return {
        "items": items,
        "total": _money(total),
        "branch_id": str(branch.id) if branch else "",
    }


def _serialize_shopboy_cart(request, cart, shopboy):
    items = []
    total = Decimal("0.00")
    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    products = _branch_scoped_products(shopboy.user, shopboy.branch, Product.objects.filter(user=shopboy.user, id__in=product_ids))
    products = list(products)
    if shopboy.branch:
        inventory_map = {
            item.product_id: item
            for item in BranchInventory.objects.filter(branch=shopboy.branch, product__in=products)
        }
        for product in products:
            product._branch_inventory = inventory_map.get(product.id)
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
            "stock": str(_effective_product_stock(product, shopboy.branch)),
        })

    return {
        "items": items,
        "total": _money(total),
    }


def _shop_bank_payload(owner):
    return {
        "bank_name": owner.bank_name or "",
        "account_number": owner.bank_account_number or "",
        "account_name": owner.bank_account_name or owner.business_name or owner.username,
        "payment_note": "Pay to this account, then show payment proof to shop staff for confirmation.",
    }


def _serialize_customer_scan_cart(request, cart):
    items = []
    total = Decimal("0.00")
    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    products = Product.objects.filter(user=cart.shop_owner, id__in=product_ids)
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
            "code": product.code,
            "name": product.name,
            "price": _money(price),
            "quantity": _format_quantity(qty),
            "line_total": _money(line_total),
            "image_url": _abs_media_url(request, product.image),
        })
    return {
        "cart_token": cart.cart_token,
        "shop": {
            "id": cart.shop_owner_id,
            "username": cart.shop_owner.username,
            "business_name": cart.shop_owner.business_name or cart.shop_owner.username,
        },
        "items": items,
        "total": _money(total),
        "bank": _shop_bank_payload(cart.shop_owner),
        "is_checked_out": cart.is_checked_out,
        "pending_sale_id": cart.pending_sale_id,
    }


def _marketplace_buyer_from_request(request):
    token_value = _get_token_value(request)
    if not token_value:
        return None
    token = MarketplaceBuyerToken.objects.select_related("buyer").filter(token=token_value, is_revoked=False).first()
    if not token:
        return None
    return token.buyer


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
    if not buyer.is_active or not _marketplace_buyer_is_fully_verified(buyer):
        return None, token_obj

    token_obj.last_used_at = timezone.now()
    token_obj.save(update_fields=["last_used_at"])
    return buyer, token_obj


def _serialize_buyer(buyer):
    return {
        "id": buyer.id,
        "email": buyer.email,
        "phone": buyer.phone,
        "registration_role": buyer.registration_role,
        "is_email_verified": buyer.is_email_verified,
        "is_phone_verified": buyer.is_phone_verified,
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
        "is_verified": bool(profile.is_verified or user.is_email_verified),
        "rating": float(profile.rating) if profile.rating is not None else 0,
        "sales_count": float(sales_count or 0),
        "logo_url": logo_url,
        "cover_url": cover_url,
        "products_preview": products_preview,
    }


def _serialize_house_image(request, image):
    return {
        "id": image.id,
        "image_url": _abs_media_url(request, image.image),
        "caption": image.caption or "",
        "is_primary": image.is_primary,
    }


def _serialize_house_listing(request, house, include_images=False):
    marketplace_agent = house.marketplace_agent
    data = {
        "id": house.id,
        "title": house.title,
        "description": house.description or "",
        "listing_mode": house.listing_mode,
        "listing_mode_label": house.get_listing_mode_display(),
        "property_type": house.property_type,
        "property_type_label": house.get_property_type_display(),
        "profile_type_label": house.profile_type_label,
        "price": _money(house.price),
        "location": house.location or "",
        "location_label": house.area_label,
        "rooms_count": house.rooms_count,
        "spaces_available": house.spaces_available,
        "units_summary": house.units_summary,
        "availability_status": house.availability_status,
        "availability_status_label": house.get_availability_status_display(),
        "is_available": house.is_available,
        "listed_in_marketplace": house.listed_in_marketplace,
        "is_active": house.is_active,
        "owner_name": house.display_owner_name,
        "owner_username": house.owner.username if house.owner_id else "",
        "owner_phone": house.display_owner_phone or "",
        "owner_address": house.display_owner_address or "",
        "agent_name": marketplace_agent.full_name if marketplace_agent else "",
        "agent_username": marketplace_agent.username if marketplace_agent else "",
        "agent_phone": marketplace_agent.phone if marketplace_agent else "",
        "agent_email": marketplace_agent.email if marketplace_agent else "",
        "agent_role": "Property Manager" if house.managed_by_agent_id else ("Listing Agent" if house.listing_agent_id else ""),
        "privacy_note": "Exact address is shared privately after contact is established.",
        "primary_image_url": _abs_media_url(request, house.primary_image.image) if house.primary_image else "",
        "images_count": house.images.count() if hasattr(house, "images") else 0,
        "inquiries_count": house.inquiries.count() if hasattr(house, "inquiries") else 0,
    }
    if include_images:
        data["images"] = [_serialize_house_image(request, image) for image in house.images.all()]
    return data


def _serialize_owner_house_inquiry(request, inquiry):
    status_labels = dict(HouseInquiry.STATUS_CHOICES)
    return {
        "public_id": str(inquiry.public_id),
        "status": inquiry.status,
        "status_label": status_labels.get(inquiry.status, inquiry.status),
        "buyer_name": inquiry.buyer_name,
        "buyer_contact": inquiry.buyer_contact,
        "created_at": inquiry.created_at.isoformat(),
        "updated_at": inquiry.updated_at.isoformat(),
        "house": _serialize_house_listing(request, inquiry.house),
    }


def _serialize_tenant_record(tenant):
    return {
        "id": tenant.id,
        "full_name": tenant.full_name,
        "phone": tenant.phone or "",
        "email": tenant.email or "",
    }


def _serialize_rental_record(rental):
    return {
        "id": rental.id,
        "tenant_name": rental.tenant_name,
        "tenant_phone": rental.tenant_phone or "",
        "tenant_email": rental.tenant_email or "",
        "start_date": rental.start_date.isoformat() if rental.start_date else "",
        "end_date": rental.end_date.isoformat() if rental.end_date else "",
        "monthly_rent": _money(rental.monthly_rent),
        "next_due_date": rental.next_due_date.isoformat() if rental.next_due_date else "",
        "last_payment_date": rental.last_payment_date.isoformat() if rental.last_payment_date else "",
        "payment_status": rental.payment_status,
        "payment_status_label": rental.get_payment_status_display(),
        "status": rental.status,
        "status_label": rental.get_status_display(),
        "notes": rental.notes or "",
        "created_at": rental.created_at.isoformat(),
        "updated_at": rental.updated_at.isoformat(),
        "days_until_expiry": rental.days_until_expiry,
        "needs_expiry_reminder": rental.needs_expiry_reminder,
        "reminder_sent_at": rental.reminder_sent_at.isoformat() if rental.reminder_sent_at else "",
        "tenant": _serialize_tenant_record(rental.tenant) if rental.tenant_id else None,
        "house": {
            "id": rental.house_id,
            "title": rental.house.title,
            "location": rental.house.location,
        },
    }


def _serialize_rental_payment(payment):
    return {
        "id": payment.id,
        "amount": _money(payment.amount),
        "status": payment.status,
        "status_label": payment.get_status_display(),
        "due_date": payment.due_date.isoformat() if payment.due_date else "",
        "paid_on": payment.paid_on.isoformat() if payment.paid_on else "",
        "notes": payment.notes or "",
        "created_at": payment.created_at.isoformat(),
        "rental": {
            "id": payment.rental_id,
            "tenant_name": payment.rental.tenant_name,
            "house_title": payment.rental.house.title,
        },
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


def _serialize_house_inquiry_message(message):
    return {
        "sender_type": message.sender_type,
        "message": message.message,
        "created_at": message.created_at.isoformat(),
    }


def _serialize_house_inquiry(request, inquiry, include_access_token=False):
    status_labels = dict(HouseInquiry.STATUS_CHOICES)
    return {
        "public_id": str(inquiry.public_id),
        "access_token": str(inquiry.access_token) if include_access_token else "",
        "status": inquiry.status,
        "status_label": status_labels.get(inquiry.status, inquiry.status),
        "buyer_name": inquiry.buyer_name,
        "buyer_contact": inquiry.buyer_contact,
        "created_at": inquiry.created_at.isoformat(),
        "updated_at": inquiry.updated_at.isoformat(),
        "house": _serialize_house_listing(request, inquiry.house),
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
        "branch": _serialize_branch(order.branch) if getattr(order, "branch_id", None) else None,
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
    registration_role = MarketplaceBuyer.ROLE_CUSTOMER
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
        registration_role=registration_role,
        is_active=True,
    )

    try:
        _send_marketplace_pending_verification_codes(buyer)
    except Exception:
        return _json_error("Account created, but verification codes could not be sent. Try again.", status=500)

    return _json_success({
        "requires_verification": True,
        "email": buyer.email,
        "registration_role": buyer.registration_role,
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

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email).first()
    if not buyer or not check_password(password, buyer.password):
        return _json_error("Invalid email or password.", status=401)

    if not buyer.is_active and _marketplace_buyer_is_fully_verified(buyer):
        return _json_error("This marketplace account is inactive.", status=403)

    if not _marketplace_buyer_is_fully_verified(buyer):
        try:
            _send_marketplace_pending_verification_codes(buyer)
        except Exception:
            return _json_error("Could not send verification codes. Please try again.", status=500)
        return _json_success({
            "requires_verification": True,
            "email": buyer.email,
        "registration_role": buyer.registration_role,
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
    email_code = (data.get("email_code") or data.get("code") or "").strip()
    if not email or not email_code:
        return _json_error("Email and verification code are required.")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email).first()
    if not buyer:
        return _json_error("Account not found.", status=404)

    if _marketplace_buyer_is_fully_verified(buyer):
        token_obj = _issue_token(buyer)
        return _json_success({
            "token": token_obj.token,
            "buyer": _serialize_buyer(buyer),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    update_fields = ["last_login"]

    if not buyer.is_email_verified:
        if not buyer.email_verification_code or not buyer.email_code_sent_at:
            return _json_error("No email verification code found. Send code first.")
        if timezone.now() - buyer.email_code_sent_at > timedelta(minutes=OTP_EXPIRY_MINUTES):
            return _json_error("Email verification code expired. Send a new code.")
        if email_code != buyer.email_verification_code:
            return _json_error("Invalid email verification code.")
        buyer.is_email_verified = True
        buyer.email_verification_code = ""
        buyer.email_code_sent_at = None
        update_fields.extend(["is_email_verified", "email_verification_code", "email_code_sent_at"])

    buyer.last_login = timezone.now()
    buyer.save(update_fields=update_fields)

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

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email).first()
    if not buyer:
        return _json_success({"sent": True})

    if _marketplace_buyer_is_fully_verified(buyer):
        return _json_error("Account already verified.")

    try:
        _send_marketplace_pending_verification_codes(buyer)
    except Exception:
        return _json_error("Failed to send verification codes. Please try again.", status=500)

    return _json_success({"sent": True, "email": buyer.email, "phone": buyer.phone})


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
        _defer_user_bank_fields(MarketplaceShopProfile.objects.select_related("user"), "user__")
        .prefetch_related("user__product_set")
        .filter(user__is_active=True, user__account_type=User.ACCOUNT_TYPE_SHOP)
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
        profiles = profiles.filter(Q(is_verified=True) | Q(user__is_email_verified=True))

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
        MarketplaceShopProfile.objects.filter(user__is_active=True, user__account_type=User.ACCOUNT_TYPE_SHOP).exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    locations = (
        MarketplaceShopProfile.objects.filter(user__is_active=True, user__account_type=User.ACCOUNT_TYPE_SHOP).exclude(location="")
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
def api_marketplace_houses(request):
    q = (request.GET.get("q") or "").strip()
    username_q = q[1:] if q.startswith("@") else q
    location = (request.GET.get("location") or "").strip()
    property_type = (request.GET.get("property_type") or "").strip()
    listing_mode = (request.GET.get("listing_mode") or "").strip()
    rooms_min = (request.GET.get("rooms_min") or "").strip()
    min_price = (request.GET.get("min_price") or "").strip()
    max_price = (request.GET.get("max_price") or "").strip()
    owner_username = (request.GET.get("owner_username") or "").strip()
    agent_username = (request.GET.get("agent_username") or "").strip()
    available_only = request.GET.get("available") == "1"
    verified = request.GET.get("verified") == "1"
    sort = request.GET.get("sort") or "rating"

    houses = _marketplace_house_queryset()
    if q:
        houses = houses.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(owner__business_name__icontains=q)
            | Q(owner__username__icontains=username_q)
            | Q(listing_agent__full_name__icontains=q)
            | Q(listing_agent__username__icontains=username_q)
        )
    if owner_username:
        houses = houses.filter(owner__username__iexact=owner_username)
    if agent_username:
        houses = houses.filter(
            Q(listing_agent__username__iexact=agent_username)
            | Q(managed_by_agent__username__iexact=agent_username)
        )
    if location:
        houses = houses.filter(location__icontains=location)
    if property_type:
        houses = houses.filter(property_type=property_type)
    if listing_mode:
        houses = houses.filter(listing_mode=listing_mode)
    if available_only:
        houses = houses.filter(
            availability_status__in=[HouseListing.STATUS_AVAILABLE, HouseListing.STATUS_PARTIAL]
        )
    if verified:
        houses = houses.filter(
            Q(owner__marketplace_profile__is_verified=True)
            | Q(owner__isnull=True, listing_agent__is_email_verified=True)
        )
    if rooms_min:
        try:
            houses = houses.filter(rooms_count__gte=int(rooms_min))
        except Exception:
            rooms_min = ""
    if min_price:
        try:
            houses = houses.filter(price__gte=Decimal(min_price))
        except Exception:
            min_price = ""
    if max_price:
        try:
            houses = houses.filter(price__lte=Decimal(max_price))
        except Exception:
            max_price = ""

    if sort == "newest":
        houses = houses.order_by("-created_at")
    elif sort == "price_low":
        houses = houses.order_by("price", "-created_at")
    elif sort == "price_high":
        houses = houses.order_by("-price", "-created_at")
    else:
        houses = houses.order_by("-created_at")

    house_locations = (
        _marketplace_house_queryset()
        .exclude(location="")
        .values_list("location", flat=True)
        .distinct()
    )

    return _json_success({
        "houses": [_serialize_house_listing(request, house) for house in houses],
        "locations": sorted(house_locations),
        "house_types": [{"value": key, "label": label} for key, label in HouseListing.PROPERTY_TYPE_CHOICES],
        "listing_modes": [{"value": key, "label": label} for key, label in HouseListing.LISTING_MODE_CHOICES],
        "filters": {
            "q": q,
            "location": location,
            "property_type": property_type,
            "listing_mode": listing_mode,
            "rooms_min": rooms_min,
            "min_price": min_price,
            "max_price": max_price,
            "available": available_only,
            "verified": verified,
            "sort": sort,
        },
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_house_detail(request, house_id):
    house = get_object_or_404(_marketplace_house_queryset(), id=house_id)
    return _json_success({
        "house": _serialize_house_listing(request, house, include_images=True),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_shop_detail(request, username):
    shop_owner = get_object_or_404(_defer_user_bank_fields(User.objects.all()), username=username, is_active=True)
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=shop_owner)
    products = Product.objects.filter(user=shop_owner).order_by("name")
    branches = _serialize_business_branch_analytics(shop_owner)["branches"] if shop_owner.account_type == User.ACCOUNT_TYPE_SHOP else []
    default_branch = _default_branch_for_owner(shop_owner)

    return _json_success({
        "shop": _serialize_shop_profile(request, profile),
        "products": [_serialize_product(request, product) for product in products],
        "branches": branches,
        "default_branch": _serialize_branch(default_branch),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_place_order(request, username):
    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    shop_owner = get_object_or_404(_defer_user_bank_fields(User.objects.all()), username=username, is_active=True)
    buyer, _ = _get_buyer_from_request(request)

    buyer_name = (data.get("buyer_name") or "").strip()
    buyer_contact = (data.get("buyer_contact") or "").strip()
    buyer_address = (data.get("buyer_address") or "").strip()
    branch_id = _normalize_branch_id(data.get("branch_id"))

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
    branch = None
    if branch_id:
        branch = ShopBranch.objects.filter(user=shop_owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Selected branch is not available.")
    else:
        branch = _default_branch_for_owner(shop_owner)

    with transaction.atomic():
        products = (
            Product.objects.select_for_update()
            .filter(user=shop_owner, id__in=product_ids)
        )
        product_map = {product.id: product for product in products}
        inventory_map = {}
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=branch, product__in=products)
            }
            for product in products:
                product._branch_inventory = inventory_map.get(product.id)

        for row in clean_items:
            product = product_map.get(row["product_id"])
            if not product:
                return _json_error("A product in your cart is invalid.")
            available_stock = _effective_product_stock(product, branch)
            if available_stock < row["quantity"]:
                return _json_error(f"Not enough stock for {product.name}. Available: {available_stock}.")

            line_total = _effective_product_price(product, branch) * row["quantity"]
            total_amount += line_total
            order_items.append({
                "product": product,
                "quantity": row["quantity"],
                "unit_price": _effective_product_price(product, branch),
            })

        order = MarketplaceOrder.objects.create(
            shop_owner=shop_owner,
            branch=branch,
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
def api_marketplace_house_inquiries(request):
    buyer, _ = _get_buyer_from_request(request)
    if not buyer:
        return _json_error("Unauthorized.", status=401)

    inquiries = (
        HouseInquiry.objects.filter(buyer=buyer)
        .select_related("house")
        .prefetch_related("house__images")
        .order_by("-updated_at", "-created_at")
    )
    return _json_success({
        "inquiries": [_serialize_house_inquiry(request, inquiry) for inquiry in inquiries],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_marketplace_house_inquiry_detail(request, public_id):
    buyer, _ = _get_buyer_from_request(request)
    inquiry = get_object_or_404(
        HouseInquiry.objects.select_related("house", "buyer").prefetch_related("house__images", "messages"),
        public_id=public_id,
    )
    if not buyer or inquiry.buyer_id != buyer.id:
        return _json_error("Access denied.", status=403)

    return _json_success({
        "inquiry": _serialize_house_inquiry(request, inquiry),
        "messages": [_serialize_house_inquiry_message(message) for message in inquiry.messages.all()],
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


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_house_inquiry_create(request, house_id):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    buyer, _ = _get_buyer_from_request(request)
    if not buyer:
        return _json_error("Unauthorized.", status=401)

    house = get_object_or_404(_marketplace_house_queryset(), id=house_id)
    if not house.owner_id:
        return _json_error("This house does not have an owner chat account yet.")

    buyer_name = (data.get("buyer_name") or "").strip()
    buyer_contact = (data.get("buyer_contact") or "").strip()
    message_text = (data.get("message") or "").strip()

    if not buyer_name or not buyer_contact:
        return _json_error("Buyer name and contact are required.")

    inquiry = HouseInquiry.objects.create(
        house=house,
        buyer=buyer,
        owner=house.owner,
        buyer_name=buyer_name,
        buyer_contact=buyer_contact,
    )
    HouseInquiryMessage.objects.create(
        inquiry=inquiry,
        sender_type=HouseInquiryMessage.SENDER_SYSTEM,
        message="Inquiry created. Continue chatting here to discuss the house details.",
    )
    if message_text:
        HouseInquiryMessage.objects.create(
            inquiry=inquiry,
            sender_type=HouseInquiryMessage.SENDER_BUYER,
            message=message_text,
        )

    return _json_success({
        "inquiry": _serialize_house_inquiry(request, inquiry, include_access_token=True),
        "messages": [_serialize_house_inquiry_message(message) for message in inquiry.messages.all()],
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_marketplace_house_inquiry_message(request, public_id):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    buyer, _ = _get_buyer_from_request(request)
    inquiry = get_object_or_404(HouseInquiry, public_id=public_id)
    if not buyer or inquiry.buyer_id != buyer.id:
        return _json_error("Access denied.", status=403)

    text = (data.get("message") or "").strip()
    if not text:
        return _json_error("Message cannot be empty.")

    message = HouseInquiryMessage.objects.create(
        inquiry=inquiry,
        sender_type=HouseInquiryMessage.SENDER_BUYER,
        message=text,
    )
    inquiry.save(update_fields=["updated_at"])
    return _json_success({
        "message": _serialize_house_inquiry_message(message),
    }, status=201)


# =============================
# Mobile Unified Auth + Owner APIs
# =============================

SHOP_SIGNUP_ALLOWED_PLANS = {"starter", "growth", "business", "pro"}


def _mobile_username_is_valid(username):
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username or ""))


def _mobile_signup_owner_by_email(email):
    return User.objects.filter(
        email__iexact=email,
        account_type=User.ACCOUNT_TYPE_SHOP,
    ).order_by("-date_joined").first()


def _mobile_shop_signup_profile(user):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "business_name": user.business_name,
        "is_email_verified": user.is_email_verified,
    }


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_shop_signup(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""
    business_name = (data.get("business_name") or "").strip()
    business_type = (data.get("business_type") or "retail").strip()
    country = (data.get("country") or "Nigeria").strip()
    state = (data.get("state") or "").strip()
    address = (data.get("address") or "").strip()
    plan_slug = (data.get("plan") or "starter").strip().lower()

    if plan_slug not in SHOP_SIGNUP_ALLOWED_PLANS:
        return _json_error("Choose a valid plan.")
    if not all([first_name, last_name, username, email, phone, password, confirm_password, business_name, state, address]):
        return _json_error("Fill all required shop registration fields.")
    if not _mobile_username_is_valid(username):
        return _json_error("Username must be 3-30 characters and use only letters, numbers, dot, dash, or underscore.")
    if password != confirm_password:
        return _json_error("Passwords do not match.")
    if not _password_meets_rules(password):
        return _json_error("Password must include uppercase, number, and special character.")

    existing_email = User.objects.filter(
        email__iexact=email,
        account_type=User.ACCOUNT_TYPE_SHOP,
        is_email_verified=True,
    ).first()
    if existing_email:
        return _json_error("Email already registered. Please sign in.", status=409)

    existing_username_qs = User.objects.filter(username__iexact=username)
    pending = _mobile_signup_owner_by_email(email)
    if pending:
        existing_username_qs = existing_username_qs.exclude(id=pending.id)
    if existing_username_qs.exists():
        return _json_error("Username already taken. Choose another username.", status=409)

    existing_phone_qs = User.objects.filter(
        phone=phone,
        account_type=User.ACCOUNT_TYPE_SHOP,
        is_email_verified=True,
    )
    if pending:
        existing_phone_qs = existing_phone_qs.exclude(id=pending.id)
    if existing_phone_qs.exists():
        return _json_error("Phone number already registered. Please sign in.", status=409)

    plan = _plan_for_slug(plan_slug)
    monthly_fee = plan["monthly_fee"] or Decimal("0.00")

    with transaction.atomic():
        if pending and not pending.is_email_verified:
            user = pending
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            user.email = email
            user.phone = phone
            user.set_password(password)
        else:
            user = User(
                first_name=first_name,
                last_name=last_name,
                username=username,
                email=email,
                phone=phone,
            )
            user.set_password(password)

        user.business_name = business_name
        user.business_type = business_type or "retail"
        user.account_type = User.ACCOUNT_TYPE_SHOP
        user.country = country or "Nigeria"
        user.state = state
        user.address = address
        user.plan = plan_slug
        user.monthly_fee = monthly_fee
        user.is_paid = False
        user.is_active = False
        user.is_email_verified = False
        user.subscription_active_until = None
        user.email_verification_code = ""
        user.email_code_sent_at = None
        user.save()

        MarketplaceShopProfile.objects.get_or_create(user=user)

    try:
        _send_signup_code(user)
    except Exception:
        return _json_error("Account was created, but the verification email could not be sent. Please try resend code.", status=502)

    return _json_success({
        "message": f"Verification code sent to {user.email}.",
        "email": user.email,
        "profile": _mobile_shop_signup_profile(user),
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_shop_signup_resend(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    user = _mobile_signup_owner_by_email(email)
    if not user:
        return _json_error("No pending shop registration found.", status=404)
    if user.is_email_verified:
        return _json_success({"message": "Email is already verified.", "email": user.email})

    try:
        _send_signup_code(user)
    except Exception:
        return _json_error("Verification email could not be sent. Please try again.", status=502)
    return _json_success({"message": f"Verification code sent to {user.email}.", "email": user.email})


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_shop_signup_verify(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or not code:
        return _json_error("Email and verification code are required.")

    user = _mobile_signup_owner_by_email(email)
    if not user:
        return _json_error("No shop registration found.", status=404)
    if user.is_email_verified and user.is_active:
        token_obj = _issue_auth_token(AuthToken.ROLE_OWNER, owner=user)
        return _json_success({
            "token": token_obj.token,
            "role": token_obj.role,
            "profile": _serialize_owner(user),
            "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        })

    sent_at = user.email_code_sent_at
    if not user.email_verification_code or not sent_at:
        return _json_error("No active verification code. Please resend code.")
    if sent_at < timezone.now() - timedelta(minutes=OTP_EXPIRY_MINUTES):
        return _json_error("Verification code has expired. Please resend code.")
    if code != user.email_verification_code:
        return _json_error("Invalid verification code.")

    user.is_email_verified = True
    user.is_active = True
    user.email_verification_code = ""
    user.email_code_sent_at = None
    user.subscription_active_until = timezone.localdate() + timedelta(days=TRIAL_DAYS)
    user.is_paid = False
    plan = _plan_for_slug(user.plan)
    user.monthly_fee = plan["monthly_fee"] or Decimal("0.00")
    user.save(update_fields=[
        "is_email_verified",
        "is_active",
        "email_verification_code",
        "email_code_sent_at",
        "subscription_active_until",
        "is_paid",
        "monthly_fee",
    ])
    _ensure_shop_code(user)
    _ensure_marketplace_profiles()

    token_obj = _issue_auth_token(AuthToken.ROLE_OWNER, owner=user)
    return _json_success({
        "message": "Shop registration completed. Your 1-week free trial has started.",
        "token": token_obj.token,
        "role": token_obj.role,
        "profile": _serialize_owner(user),
        "trial_days": TRIAL_DAYS,
        "expires_at": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_auth_login(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    role = (data.get("role") or "").strip().lower()
    account_type = (data.get("account_type") or "").strip().lower()
    if role in ("shopowner", "shop_owner", "owner"):
        role = AuthToken.ROLE_OWNER
    if role in ("shopboy", "shop_boy"):
        role = AuthToken.ROLE_SHOPBOY
    if role in ("agent",):
        role = AuthToken.ROLE_AGENT
    if account_type in ("shop_owner", "shopowner"):
        account_type = User.ACCOUNT_TYPE_SHOP
    elif account_type in ("house", "housing_owner"):
        account_type = User.ACCOUNT_TYPE_HOUSING
    elif account_type not in ("", User.ACCOUNT_TYPE_SHOP, User.ACCOUNT_TYPE_HOUSING):
        return _json_error("Invalid account type. Use shop or housing.")

    if role == AuthToken.ROLE_OWNER:
        identifier = (data.get("identifier") or "").strip()
        password = data.get("password") or ""
        if not identifier or not password:
            return _json_error("Email/username and password are required.")

        valid_accounts = _valid_accounts_for_credentials(
            request,
            identifier,
            password,
            account_type=account_type or None,
        )
        if len(valid_accounts) > 1 and not account_type:
            return _json_error(
                "Choose which workspace you want to open.",
                status=409,
                code="account_type_required",
                account_type_options=_login_account_type_options(valid_accounts),
            )

        owner = valid_accounts[0] if len(valid_accounts) == 1 else None
        if not owner:
            owner = _authenticate_with_identifier(
                request,
                identifier,
                password,
                account_type=account_type or None,
            )
        if not owner:
            return _json_error("Invalid email/username or password.", status=401)

        token_obj = _issue_auth_token(AuthToken.ROLE_OWNER, owner=owner)
        return _json_success({
            "token": token_obj.token,
            "role": token_obj.role,
            "profile": _serialize_owner(owner),
            "subscription_required": not subscription_is_active(owner),
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

    data = _get_body_data(request) if request.method == "POST" else None
    branch_id = _normalize_branch_id(request.GET.get("branch_id") if request.method == "GET" else data.get("branch_id") if data else "")
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    if request.method == "GET":
        categories = _branch_scoped_categories(owner, branch).order_by("name")
        return _json_success({
            "categories": [_serialize_category(cat) for cat in categories],
        })

    if data is None:
        return _json_error("Invalid JSON payload.")

    name = (data.get("name") or "").strip()
    if not name:
        return _json_error("Category name is required.")

    if _branch_scoped_categories(owner, branch).filter(name__iexact=name).exists():
        return _json_error("Category already exists.", status=409)

    category = Category.objects.create(user=owner, branch=branch, name=name)
    return _json_success({"category": _serialize_category(category)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_products(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        branch_id = _normalize_branch_id(request.GET.get("branch_id"))
        branch = None
        if branch_id:
            feature_error = _json_feature_required(owner, "multi_branch")
            if feature_error:
                return feature_error
            branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
            if not branch:
                return _json_error("Branch not found.", status=404)
        products = _branch_scoped_products(owner, branch)
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
    branch_id = _normalize_branch_id(data.get("branch_id"))
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

    plan, product_limit = _plan_limit(owner, "product_limit")
    if product_limit is not None and Product.objects.filter(user=owner).count() >= product_limit:
        return _json_error(_plan_limit_error("product", plan["name"]), status=403)

    if code:
        feature_error = _json_feature_required(owner, "barcode")
        if feature_error:
            return feature_error

    if code:
        existing_code = Product.objects.filter(user=owner, code__iexact=code).exists()
        if existing_code:
            return _json_error(f"A product with code {code} already exists.", status=409)

    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    if category_id:
        category_exists = _branch_scoped_categories(owner, branch).filter(id=category_id).exists() if branch else Category.objects.filter(id=category_id, user=owner).exists()
        if not category_exists:
            return _json_error("Selected category is invalid.")

    valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
    if vat_status not in valid_vat_status:
        vat_status = Product.VAT_STANDARD
    if vat_status != Product.VAT_STANDARD:
        feature_error = _json_feature_required(owner, "tax_tools")
        if feature_error:
            return feature_error

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
    if branch:
        BranchInventory.objects.update_or_create(
            branch=branch,
            product=product,
            defaults={
                "stock": stock,
                "selling_price": selling_price,
                "is_active": True,
                "track_separately": True,
            },
        )
        _sync_global_product_stock(product)
        product._branch_inventory = BranchInventory.objects.filter(branch=branch, product=product).first()
    return _json_success({"product": _serialize_owner_product(request, product, branch=branch)}, status=201)


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

    branch_id = (data.get("branch_id") or "").strip()
    branch = None
    branch_inventory = None
    if branch_id:
        branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
        if not branch:
            return _json_error("Branch not found.", status=404)
        if not _plan_has_feature(owner, "multi_branch"):
            active_branch_count = ShopBranch.objects.filter(user=owner, is_active=True).count()
            if active_branch_count <= 1:
                branch = None
            else:
                feature_error = _json_feature_required(owner, "multi_branch")
                if feature_error:
                    return feature_error
        if branch:
            branch_inventory, _ = BranchInventory.objects.get_or_create(
                branch=branch,
                product=product,
                defaults={"stock": product.stock, "selling_price": product.selling_price},
            )

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return _json_error("Product name is required.")
        product.name = name
    if "category_id" in data:
        category_id = data.get("category_id") or None
        if category_id:
            category_exists = _branch_scoped_categories(owner, branch).filter(id=category_id).exists() if branch else Category.objects.filter(id=category_id, user=owner).exists()
            if not category_exists:
                return _json_error("Selected category is invalid.")
        product.category_id = category_id
    if "code" in data:
        code = (data.get("code") or "").strip()
        code_changed = code.lower() != (product.code or "").strip().lower()
        barcode_allowed = _plan_has_feature(owner, "barcode")
        if not barcode_allowed:
            if code and code_changed:
                feature_error = _json_feature_required(owner, "barcode")
                if feature_error:
                    return feature_error
            elif not code:
                code = product.code or ""
        if code and code_changed and barcode_allowed:
            feature_error = _json_feature_required(owner, "barcode")
            if feature_error:
                return feature_error
            existing_code = Product.objects.filter(user=owner, code__iexact=code).exclude(id=product.id).exists()
            if existing_code:
                return _json_error(f"A product with code {code} already exists.", status=409)
        product.code = code

    for field in ["stock", "low_stock_threshold", "cost_price", "selling_price"]:
        if field in data:
            try:
                if field == "stock":
                    if branch_inventory:
                        branch_inventory.stock = _parse_stock(data.get("stock"))
                        branch_inventory.track_separately = True
                    else:
                        product.stock = _parse_stock(data.get("stock"))
                elif field == "low_stock_threshold":
                    product.low_stock_threshold = int(data.get("low_stock_threshold") or 0)
                elif field == "cost_price":
                    product.cost_price = Decimal(data.get("cost_price"))
                elif field == "selling_price":
                    if branch_inventory:
                        branch_inventory.selling_price = Decimal(data.get("selling_price"))
                    else:
                        product.selling_price = Decimal(data.get("selling_price"))
            except Exception:
                return _json_error("Invalid product values.")

    vat_status = (data.get("vat_status") or "").strip()
    if vat_status:
        vat_changed = vat_status != product.vat_status
        if vat_status != Product.VAT_STANDARD and vat_changed:
            feature_error = _json_feature_required(owner, "tax_tools")
            if feature_error:
                return feature_error
        valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
        if vat_status in valid_vat_status:
            product.vat_status = vat_status

    if request.FILES.get("image"):
        product.image = request.FILES.get("image")

    product.save()
    if branch_inventory:
        branch_inventory.save()
        product._branch_inventory = branch_inventory
    return _json_success({"product": _serialize_owner_product(request, product, branch=branch)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_adjust_stock(request, pk):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    product = get_object_or_404(Product, pk=pk, user=owner)
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        adjustment = _parse_stock(data.get("adjustment", 0))
    except Exception:
        return _json_error("Invalid adjustment amount.")
    branch_id = _normalize_branch_id(data.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    if branch:
        inventory, _ = BranchInventory.objects.get_or_create(
            branch=branch,
            product=product,
            defaults={"stock": Decimal("0.00"), "selling_price": product.selling_price},
        )
        inventory.stock = max(Decimal("0.00"), inventory.stock + adjustment)
        inventory.save(update_fields=["stock", "updated_at"])
        product._branch_inventory = inventory
    else:
        product.stock = max(Decimal("0.00"), product.stock + adjustment)
        product.save(update_fields=["stock"])
    return _json_success({ "product": _serialize_owner_product(request, product, branch=branch) })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_dashboard(request):
    try:
        owner = _require_owner(request)
        if not owner:
            return _json_error("Unauthorized.", status=401)

        branch_id = (request.GET.get("branch_id") or "").strip()
        selected_branch = None
        if branch_id:
            feature_error = _json_feature_required(owner, "multi_branch")
            if feature_error:
                return feature_error
            selected_branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
            if not selected_branch:
                return _json_error("Branch not found.", status=404)

        today = timezone.localdate()
        sales_qs = Sale.objects.filter(user=owner)
        if selected_branch:
            sales_qs = sales_qs.filter(branch=selected_branch)

        products_qs = _branch_scoped_products(owner, selected_branch)
        products_for_counts = list(products_qs)
        if selected_branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.filter(branch=selected_branch, product__in=products_for_counts)
            }
            for product in products_for_counts:
                product._branch_inventory = inventory_map.get(product.id)

        total_stock_units = Decimal("0.00")
        total_stock_value = Decimal("0.00")
        total_stock_cost = Decimal("0.00")
        out_of_stock_count = 0
        low_stock_products = []
        for product in products_for_counts:
            stock = Decimal(_effective_product_stock(product, selected_branch) or "0.00")
            selling_price = Decimal(_effective_product_price(product, selected_branch) or "0.00")
            cost_price = Decimal(product.cost_price or "0.00")
            total_stock_units += stock
            total_stock_value += stock * selling_price
            total_stock_cost += stock * cost_price
            if stock <= 0:
                out_of_stock_count += 1
            elif stock <= product.low_stock_threshold:
                low_stock_products.append(product)

        today_sales = sales_qs.filter(created_at__date=today).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        today_profit = sales_qs.filter(created_at__date=today).aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
        total_products = len(products_for_counts)
        low_stock_count = len(low_stock_products)

        today_transactions = (
            sales_qs.filter(created_at__date=today)
            .annotate(items_count=Sum("items__quantity"))
            .order_by("-created_at")[:5]
        )

        top_products = (
            products_qs
            .annotate(total_sold=Sum("saleitem__quantity", filter=Q(saleitem__sale__branch=selected_branch) if selected_branch else Q()))
            .order_by("-total_sold", "-created_at")[:6]
        )
        top_products = list(top_products)
        if selected_branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.filter(branch=selected_branch, product__in=top_products)
            }
            for product in top_products:
                product._branch_inventory = inventory_map.get(product.id)
        branch_analytics = _serialize_business_branch_analytics(owner)

        return _json_success({
            "today_date": today.isoformat(),
            "today_sales": _money(today_sales),
            "today_profit": _money(today_profit),
            "total_products": total_products,
            "low_stock_count": low_stock_count,
            "inventory_analysis": {
                "total_stock_units": str(total_stock_units),
                "stock_value": _money(total_stock_value),
                "stock_cost": _money(total_stock_cost),
                "potential_profit": _money(total_stock_value - total_stock_cost),
                "out_of_stock_count": out_of_stock_count,
                "low_stock_count": low_stock_count,
                "low_stock_products": [
                    {
                        "id": product.id,
                        "name": product.name,
                        "stock": str(_effective_product_stock(product, selected_branch)),
                        "low_stock_threshold": product.low_stock_threshold,
                    }
                    for product in low_stock_products[:5]
                ],
            },
            "branch": _serialize_branch(selected_branch) if selected_branch else None,
            "branch_analytics": branch_analytics,
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
                    "selling_price": _money(_effective_product_price(product, selected_branch)),
                    "stock": str(_effective_product_stock(product, selected_branch)),
                    "total_sold": float(product.total_sold or 0),
                    "image_url": _abs_media_url(request, product.image),
                }
                for product in top_products
            ],
        })
    except Exception as exc:
        return _json_error(f"Dashboard failed: {exc}", status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_housing_dashboard(request):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    today = timezone.localdate()
    houses = (
        HouseListing.objects.filter(owner=owner, is_active=True)
        .prefetch_related("images", "inquiries")
        .select_related("managed_by_agent")
        .order_by("-created_at")
    )
    inquiries = (
        HouseInquiry.objects.filter(owner=owner)
        .select_related("house", "buyer")
        .prefetch_related("house__images")
        .order_by("-updated_at", "-created_at")
    )
    rentals = RentalRecord.objects.filter(house__owner=owner)
    payments = RentalPayment.objects.filter(rental__house__owner=owner)

    upcoming_reminders = rentals.filter(
        status=RentalRecord.STATUS_ACTIVE,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=60),
    )
    due_payments = payments.filter(
        Q(status__in=[RentalPayment.STATUS_PENDING, RentalPayment.STATUS_PARTIAL, RentalPayment.STATUS_OVERDUE])
        | Q(due_date__lt=today)
    )
    agents = Agent.objects.filter(is_active=True).order_by("full_name")
    tenants = TenantRecord.objects.filter(user=owner).order_by("full_name")

    return _json_success({
        "profile": _serialize_owner(owner),
        "stats": {
            "houses": houses.count(),
            "available_houses": houses.filter(availability_status=HouseListing.STATUS_AVAILABLE).count(),
            "occupied_houses": houses.filter(availability_status=HouseListing.STATUS_OCCUPIED).count(),
            "open_inquiries": inquiries.filter(status=HouseInquiry.STATUS_OPEN).count(),
            "expiring_rentals": upcoming_reminders.count(),
            "due_payments": due_payments.count(),
        },
        "houses": [_serialize_house_listing(request, house) for house in houses],
        "inquiries": [_serialize_owner_house_inquiry(request, inquiry) for inquiry in inquiries[:12]],
        "rentals": [_serialize_rental_record(rental) for rental in rentals.select_related("house", "tenant")[:12]],
        "payments": [_serialize_rental_payment(payment) for payment in payments.select_related("rental", "rental__house")[:12]],
        "upcoming_reminders": [_serialize_rental_record(rental) for rental in upcoming_reminders.select_related("house", "tenant")[:8]],
        "due_payments": [_serialize_rental_payment(payment) for payment in due_payments.select_related("rental", "rental__house")[:8]],
        "tenants": [_serialize_tenant_record(tenant) for tenant in tenants],
        "agents": [_serialize_agent(agent) for agent in agents],
        "choices": {
            "house_statuses": [{"value": value, "label": label} for value, label in HouseListing.AVAILABILITY_STATUS_CHOICES],
            "property_types": [{"value": value, "label": label} for value, label in HouseListing.PROPERTY_TYPE_CHOICES],
            "listing_modes": [{"value": value, "label": label} for value, label in HouseListing.LISTING_MODE_CHOICES],
            "rental_statuses": [{"value": value, "label": label} for value, label in RentalRecord.STATUS_CHOICES],
            "rental_payment_statuses": [{"value": value, "label": label} for value, label in RentalRecord.PAYMENT_STATUS_CHOICES],
            "payment_statuses": [{"value": value, "label": label} for value, label in RentalPayment.STATUS_CHOICES],
        },
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_listing_create(request):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    title = (request.POST.get("title") or "").strip()
    listing_mode = (request.POST.get("listing_mode") or HouseListing.MODE_RENT).strip()
    property_type = (request.POST.get("property_type") or HouseListing.TYPE_APARTMENT).strip()
    location = (request.POST.get("location") or "").strip()
    description = (request.POST.get("description") or "").strip()
    availability_status = (request.POST.get("availability_status") or HouseListing.STATUS_AVAILABLE).strip()
    managed_by_agent = None
    managed_by_agent_id = (request.POST.get("managed_by_agent") or "").strip()
    if managed_by_agent_id:
        managed_by_agent = Agent.objects.filter(id=managed_by_agent_id, is_active=True).first()

    if not title or not location:
        return _json_error("House title and location are required.")

    valid_property_types = {choice[0] for choice in HouseListing.PROPERTY_TYPE_CHOICES}
    if property_type not in valid_property_types:
        property_type = HouseListing.TYPE_OTHER
    valid_listing_modes = {choice[0] for choice in HouseListing.LISTING_MODE_CHOICES}
    if listing_mode not in valid_listing_modes:
        listing_mode = HouseListing.MODE_RENT
    valid_availability = {choice[0] for choice in HouseListing.AVAILABILITY_STATUS_CHOICES}
    if availability_status not in valid_availability:
        availability_status = HouseListing.STATUS_AVAILABLE

    try:
        price = Decimal(request.POST.get("price") or "0")
        rooms_count = int(request.POST.get("rooms_count") or "1")
        spaces_available = int(request.POST.get("spaces_available") or "1")
        if price <= 0 or rooms_count <= 0 or spaces_available <= 0:
            raise ValueError
    except Exception:
        return _json_error("Price, rooms, and spaces must be valid positive values.")

    house = HouseListing.objects.create(
        owner=owner,
        managed_by_agent=managed_by_agent,
        title=title,
        listing_mode=listing_mode,
        property_type=property_type,
        price=price,
        location=location,
        rooms_count=rooms_count,
        spaces_available=spaces_available,
        description=description,
        availability_status=availability_status,
        listed_in_marketplace=request.POST.get("listed_in_marketplace") in {"true", "1", "on"},
    )

    for index, image in enumerate(request.FILES.getlist("images")):
        HouseListingImage.objects.create(house=house, image=image, is_primary=index == 0)

    return _json_success({
        "message": "House listing added.",
        "house": _serialize_house_listing(request, house, include_images=True),
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_listing_update(request, house_id):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    house = get_object_or_404(HouseListing, id=house_id, owner=owner)
    availability_status = (request.POST.get("availability_status") or house.availability_status).strip()
    listing_mode = (request.POST.get("listing_mode") or house.listing_mode).strip()

    valid_availability = {choice[0] for choice in HouseListing.AVAILABILITY_STATUS_CHOICES}
    if availability_status not in valid_availability:
        availability_status = house.availability_status
    valid_listing_modes = {choice[0] for choice in HouseListing.LISTING_MODE_CHOICES}
    if listing_mode not in valid_listing_modes:
        listing_mode = house.listing_mode

    house.availability_status = availability_status
    house.listing_mode = listing_mode
    house.listed_in_marketplace = request.POST.get("listed_in_marketplace") in {"true", "1", "on"}
    house.is_active = request.POST.get("is_active") in {"true", "1", "on"}
    house.save(update_fields=["availability_status", "listing_mode", "listed_in_marketplace", "is_active", "updated_at"])

    return _json_success({
        "message": f"{house.title} updated.",
        "house": _serialize_house_listing(request, house, include_images=True),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_rental_create(request):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    house = get_object_or_404(HouseListing, id=request.POST.get("house_id"), owner=owner)
    tenant = None
    tenant_id = (request.POST.get("tenant_id") or "").strip()
    if tenant_id:
        tenant = TenantRecord.objects.filter(id=tenant_id, user=owner).first()

    tenant_name = (request.POST.get("tenant_name") or (tenant.full_name if tenant else "")).strip()
    tenant_phone = (request.POST.get("tenant_phone") or (tenant.phone if tenant else "")).strip()
    tenant_email = (request.POST.get("tenant_email") or (tenant.email if tenant else "")).strip()
    notes = (request.POST.get("notes") or "").strip()

    if not tenant_name:
        return _json_error("Tenant name is required.")

    start_date = parse_date((request.POST.get("start_date") or "").strip())
    end_date = parse_date((request.POST.get("end_date") or "").strip())
    next_due_date = parse_date((request.POST.get("next_due_date") or "").strip()) if request.POST.get("next_due_date") else None
    if not start_date or not end_date or end_date <= start_date:
        return _json_error("Please provide a valid rental start and end date.")

    try:
        monthly_rent = Decimal(request.POST.get("monthly_rent") or house.price)
        if monthly_rent <= 0:
            raise ValueError
    except Exception:
        return _json_error("Monthly rent must be a valid positive amount.")

    valid_payment_statuses = {choice[0] for choice in RentalRecord.PAYMENT_STATUS_CHOICES}
    payment_status = (request.POST.get("payment_status") or RentalRecord.PAYMENT_CURRENT).strip()
    if payment_status not in valid_payment_statuses:
        payment_status = RentalRecord.PAYMENT_CURRENT
    valid_rental_statuses = {choice[0] for choice in RentalRecord.STATUS_CHOICES}
    rental_status = (request.POST.get("status") or RentalRecord.STATUS_ACTIVE).strip()
    if rental_status not in valid_rental_statuses:
        rental_status = RentalRecord.STATUS_ACTIVE

    if tenant is None:
        tenant = TenantRecord.objects.create(
            user=owner,
            full_name=tenant_name,
            phone=tenant_phone,
            email=tenant_email,
        )

    rental = RentalRecord.objects.create(
        house=house,
        tenant=tenant,
        tenant_name=tenant_name,
        tenant_phone=tenant_phone,
        tenant_email=tenant_email,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=monthly_rent,
        next_due_date=next_due_date,
        payment_status=payment_status,
        status=rental_status,
        notes=notes,
    )
    _refresh_house_availability(house)
    _sync_rental_payment_state(rental)

    return _json_success({
        "message": "Rental record saved.",
        "rental": _serialize_rental_record(rental),
        "tenant": _serialize_tenant_record(tenant),
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_payment_create(request):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    rental = get_object_or_404(
        RentalRecord.objects.select_related("house"),
        id=request.POST.get("rental_id"),
        house__owner=owner,
    )
    due_date = parse_date((request.POST.get("due_date") or "").strip())
    paid_on = parse_date((request.POST.get("paid_on") or "").strip()) if request.POST.get("paid_on") else None
    status = (request.POST.get("status") or RentalPayment.STATUS_PENDING).strip()
    notes = (request.POST.get("notes") or "").strip()

    if not due_date:
        return _json_error("Payment due date is required.")

    valid_payment_statuses = {choice[0] for choice in RentalPayment.STATUS_CHOICES}
    if status not in valid_payment_statuses:
        status = RentalPayment.STATUS_PENDING

    try:
        amount = Decimal(request.POST.get("amount") or "0")
        if amount <= 0:
            raise ValueError
    except Exception:
        return _json_error("Payment amount must be a valid positive amount.")

    payment = RentalPayment.objects.create(
        rental=rental,
        amount=amount,
        due_date=due_date,
        paid_on=paid_on,
        status=status,
        notes=notes,
    )
    if payment.status == RentalPayment.STATUS_PAID and payment.paid_on:
        rental.last_payment_date = payment.paid_on
        rental.save(update_fields=["last_payment_date", "updated_at"])
    _sync_rental_payment_state(rental)

    return _json_success({
        "message": "Rental payment record saved.",
        "payment": _serialize_rental_payment(payment),
    }, status=201)


@csrf_exempt
@require_http_methods(["GET"])
def api_housing_inquiry_detail(request, public_id):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    inquiry = get_object_or_404(
        HouseInquiry.objects.select_related("house", "buyer").prefetch_related("house__images", "messages"),
        public_id=public_id,
        owner=owner,
    )
    return _json_success({
        "inquiry": _serialize_house_inquiry(request, inquiry),
        "messages": [_serialize_house_inquiry_message(message) for message in inquiry.messages.all()],
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_inquiry_message(request, public_id):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    inquiry = get_object_or_404(HouseInquiry.objects.select_related("house"), public_id=public_id, owner=owner)
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid request payload.")

    message_text = (data.get("message") or "").strip()
    if not message_text:
        return _json_error("Message cannot be empty.")

    message = HouseInquiryMessage.objects.create(
        inquiry=inquiry,
        sender_type=HouseInquiryMessage.SENDER_SELLER,
        message=message_text,
    )
    if inquiry.status != HouseInquiry.STATUS_OPEN:
        inquiry.status = HouseInquiry.STATUS_OPEN
        inquiry.save(update_fields=["status", "updated_at"])

    return _json_success({
        "message": _serialize_house_inquiry_message(message),
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_housing_rental_reminder(request, rental_id):
    owner = _require_housing_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    rental = get_object_or_404(
        RentalRecord.objects.select_related("house", "house__owner"),
        id=rental_id,
        house__owner=owner,
    )

    reminder_message = (
        f"Hello {rental.tenant_name}, your rent for {rental.house.title} at {rental.house.location} "
        f"is set to expire on {rental.end_date:%B %d, %Y}. Please plan your renewal early."
    )
    sent = False
    if rental.tenant_email:
        sent = send_email(rental.tenant_email, "VilaStore Rent Expiry Reminder", reminder_message) or sent
    if rental.tenant_phone:
        sent = send_sms(rental.tenant_phone, reminder_message) or sent

    if not sent:
        return _json_error("Reminder could not be delivered. Add tenant email or phone first.")

    rental.reminder_sent_at = timezone.now()
    rental.save(update_fields=["reminder_sent_at", "updated_at"])
    return _json_success({
        "message": f"Reminder sent to {rental.tenant_name}.",
        "rental": _serialize_rental_record(rental),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_pos(request):
    try:
        token_obj, _ = _get_auth_from_request(request)
        owner = _require_owner(request)
        if not owner or not token_obj:
            return _json_error("Unauthorized.", status=401)

        category_id = (request.GET.get("category") or "").strip()
        q = (request.GET.get("q") or "").strip()
        branch_id = _normalize_branch_id(request.GET.get("branch_id"))
        branch = None
        if branch_id:
            feature_error = _json_feature_required(owner, "multi_branch")
            if feature_error:
                return feature_error
            branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
            if not branch:
                return _json_error("Branch not found.", status=404)

        products = _branch_scoped_products(owner, branch)
        if category_id:
            products = products.filter(category_id=category_id)
        if q:
            products = products.filter(
                Q(name__icontains=q) |
                Q(code__icontains=q) |
                Q(category__name__icontains=q)
            )

        categories = _branch_scoped_categories(owner, branch).order_by("name")
        cart = _get_owner_cart(token_obj)
        cart_payload = _serialize_owner_cart(request, cart, owner, branch=branch)

        last_sale = None
        if cart.last_sale_id:
            sale_qs = Sale.objects.filter(user=owner, id=cart.last_sale_id)
            if branch:
                sale_qs = sale_qs.filter(branch=branch)
            sale = sale_qs.first()
            if sale:
                last_sale = {
                    "id": sale.id,
                    "total_amount": _money(sale.total_amount),
                    "created_at": sale.created_at.isoformat(),
                }

        product_rows = list(products.select_related("category").order_by("name"))
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.filter(branch=branch, product__in=product_rows)
            }
            for product in product_rows:
                product._branch_inventory = inventory_map.get(product.id)
        branches = _serialize_business_branch_analytics(owner)["branches"]

        return _json_success({
            "products": [_serialize_owner_product(request, product, branch=branch) for product in product_rows],
            "categories": [_serialize_category(cat) for cat in categories],
            "cart": cart_payload,
            "last_sale": last_sale,
            "branch": _serialize_branch(branch) if branch else None,
            "branches": branches,
            "can_edit_price": True,
        })
    except Exception as exc:
        return _json_error(f"POS failed: {exc}", status=500)


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

    branch_id = _normalize_branch_id(data.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    product = get_object_or_404(_branch_scoped_products(owner, branch), id=product_id)
    _branch_inventory_for_product(product, branch)
    available_stock = _effective_product_stock(product, branch)
    price = _effective_product_price(product, branch)
    if available_stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_owner_cart(token_obj)
    cart_rows = _owner_cart_data(cart, branch)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart_rows.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > available_stock:
        desired_qty = available_stock

    cart_rows[product_key] = {
        "name": product.name,
        "price": float(price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    _set_owner_cart_data(cart, branch, cart_rows)
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_owner_cart(request, cart, owner, branch=branch)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_add_by_code(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "barcode")
    if feature_error:
        return feature_error

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

    branch_id = _normalize_branch_id(data.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    product = _branch_scoped_products(owner, branch).filter(code__iexact=code).first()
    if not product:
        return _json_error(f"No product found for code {code}.", status=404)
    _branch_inventory_for_product(product, branch)
    available_stock = _effective_product_stock(product, branch)
    price = _effective_product_price(product, branch)
    if available_stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_owner_cart(token_obj)
    cart_rows = _owner_cart_data(cart, branch)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart_rows.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > available_stock:
        desired_qty = available_stock

    cart_rows[product_key] = {
        "name": product.name,
        "price": float(price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    _set_owner_cart_data(cart, branch, cart_rows)
    cart.save(update_fields=["data", "updated_at"])

    return _json_success({"cart": _serialize_owner_cart(request, cart, owner, branch=branch)})


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
    branch_id = _normalize_branch_id(data.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    cart = _get_owner_cart(token_obj)
    cart_rows = _owner_cart_data(cart, branch)
    product_key = str(product_id)
    if product_key not in cart_rows:
        return _json_error("Item not in cart.", status=404)

    product = get_object_or_404(_branch_scoped_products(owner, branch), id=product_id)
    _branch_inventory_for_product(product, branch)
    available_stock = _effective_product_stock(product, branch)
    current_qty = _cart_quantity_value(cart_rows.get(product_key, {}).get("quantity"))

    if action == "price":
        try:
            price = Decimal(str(price_raw))
        except Exception:
            return _json_error("Invalid price.")
        if price < 0:
            return _json_error("Price cannot be negative.")
        cart_rows[product_key]["price"] = float(price.quantize(Decimal("0.01")))
    elif action == "increase":
        desired_qty = current_qty + Decimal("1")
        if desired_qty > available_stock:
            desired_qty = available_stock
        cart_rows[product_key]["quantity"] = _format_quantity(desired_qty)
    elif action == "decrease":
        desired_qty = current_qty - Decimal("1")
        if desired_qty <= 0:
            cart_rows.pop(product_key, None)
        else:
            cart_rows[product_key]["quantity"] = _format_quantity(desired_qty)
    else:
        quantity = _cart_quantity_value(quantity_raw)
        if quantity <= 0:
            cart_rows.pop(product_key, None)
        elif quantity > available_stock:
            cart_rows[product_key]["quantity"] = _format_quantity(available_stock)
        else:
            cart_rows[product_key]["quantity"] = _format_quantity(quantity)

    _set_owner_cart_data(cart, branch, cart_rows)
    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_owner_cart(request, cart, owner, branch=branch)})


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

    branch_id = _normalize_branch_id(data.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    cart = _get_owner_cart(token_obj)
    cart_rows = _owner_cart_data(cart, branch)
    cart_rows.pop(str(product_id), None)
    _set_owner_cart_data(cart, branch, cart_rows)
    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_owner_cart(request, cart, owner, branch=branch)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_cart_checkout(request):
    token_obj, _ = _get_auth_from_request(request)
    owner = _require_owner(request)
    if not owner or not token_obj:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request) or {}
    payment_status = (data.get("payment_status") or Sale.PAYMENT_PAID).strip().lower()
    valid_statuses = {Sale.PAYMENT_PAID, Sale.PAYMENT_LOAN}
    if payment_status not in valid_statuses:
        payment_status = Sale.PAYMENT_PAID

    customer_name = (data.get("customer_name") or "").strip()
    branch_id = _normalize_branch_id(data.get("branch_id"))
    try:
        initial_payment = Decimal(str(data.get("initial_payment") or "0"))
        if initial_payment < 0:
            raise ValueError
    except Exception:
        return _json_error("Initial payment must be 0 or more.")

    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    cart = _get_owner_cart(token_obj)
    cart_rows = _owner_cart_data(cart, branch)
    if not cart_rows:
        return _json_error("Cart is empty.", status=400)

    sanitized_cart = {
        str(pid): item
        for pid, item in cart_rows.items()
        if str(pid).isdigit() and isinstance(item, dict)
    }
    if sanitized_cart != cart_rows:
        _set_owner_cart_data(cart, branch, sanitized_cart)
        cart.save(update_fields=["data", "updated_at"])
        return _json_error("Old cart data was cleaned. Please review the cart and complete the sale again.", status=409)

    product_ids = [int(pid) for pid in cart_rows.keys()]
    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = _branch_scoped_products(
            owner,
            branch,
            Product.objects.select_for_update().filter(user=owner, id__in=product_ids),
        )
        product_map = {str(p.id): p for p in products}
        inventory_map = {}
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=branch, product__in=products)
            }
            for product in products:
                product._branch_inventory = inventory_map.get(product.id)

        for pid, item in cart_rows.items():
            product = product_map.get(str(pid))
            if not product:
                return _json_error("A cart item no longer exists.", status=409)

            quantity = _cart_quantity_value(item.get("quantity"))
            if quantity <= 0:
                continue

            available_stock = _effective_product_stock(product, branch)
            if available_stock < quantity:
                return _json_error(f"Not enough stock for {product.name}. Available: {available_stock}.", status=409)

            price = _cart_money_value(item.get("price"), _effective_product_price(product, branch))
            cost = _cart_money_value(item.get("cost"), product.cost_price)
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

        amount_paid = (
            total_amount.quantize(Decimal("0.01"))
            if payment_status == Sale.PAYMENT_PAID
            else min(initial_payment, total_amount).quantize(Decimal("0.01"))
        )

        sale = Sale.objects.create(
            user=owner,
            branch=branch,
            sales_channel=Sale.CHANNEL_OWNER_POS,
            customer_name=customer_name,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            vat_total=vat_total.quantize(Decimal("0.01")),
            amount_paid=amount_paid,
            payment_status=(
                Sale.PAYMENT_PAID
                if payment_status == Sale.PAYMENT_PAID
                else _derive_payment_status(total_amount, amount_paid)
            ),
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
            inventory = inventory_map.get(row["product"].id) if branch else None
            if inventory and inventory.track_separately:
                inventory.stock = max(Decimal("0.00"), inventory.stock - row["quantity"])
                inventory.save(update_fields=["stock", "updated_at"])
                _sync_global_product_stock(row["product"])
            else:
                row["product"].stock -= row["quantity"]
                row["product"].save(update_fields=["stock"])

    _set_owner_cart_data(cart, branch, {})
    cart.last_sale_id = sale.id
    cart.save(update_fields=["data", "last_sale_id", "updated_at"])

    return _json_success({
        "sale": {
            "id": sale.id,
            "total_amount": _money(sale.total_amount),
            "created_at": sale.created_at.isoformat(),
        },
        "cart": _serialize_owner_cart(request, cart, owner, branch=branch),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_inventory(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    q = (request.GET.get("q") or "").strip()
    branch_id = _normalize_branch_id(request.GET.get("branch_id"))
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
        if not branch:
            return _json_error("Branch not found.", status=404)
    products = _branch_scoped_products(owner, branch)
    if q:
        products = products.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(category__name__icontains=q)
        )

    products = products.select_related("category").order_by("name")
    product_rows = list(products)
    if branch:
        inventory_map = {
            item.product_id: item
            for item in BranchInventory.objects.filter(branch=branch, product__in=product_rows)
        }
        for product in product_rows:
            product._branch_inventory = inventory_map.get(product.id)

    total_products = len(product_rows)
    total_value = sum((_effective_product_price(p, branch) * _effective_product_stock(p, branch) for p in product_rows), Decimal("0.00"))
    low_stock = sum(1 for p in product_rows if Decimal(_effective_product_stock(p, branch)) <= p.low_stock_threshold and Decimal(_effective_product_stock(p, branch)) > 0)
    out_of_stock = sum(1 for p in product_rows if Decimal(_effective_product_stock(p, branch)) <= 0)

    return _json_success({
        "summary": {
            "total_products": total_products,
            "total_value": _money(total_value),
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
        },
        "branch": _serialize_branch(branch) if branch else None,
        "products": [_serialize_owner_product(request, product, branch=branch) for product in product_rows],
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_generate_product_code(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "barcode")
    if feature_error:
        return feature_error

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
    feature_error = _json_feature_required(owner, "barcode")
    if feature_error:
        return feature_error

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
    branch_id = (request.GET.get("branch_id") or "").strip()
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    sales = (
        Sale.objects.filter(user=owner)
        .select_related("handled_by_shopboy", "branch")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    if branch_id:
        sales = sales.filter(branch_id=branch_id)
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

    years = {sale.created_at.year for sale in sales}
    vat_registered_by_year = {
        year: _is_vat_registered(owner, _year_turnover(owner, year))
        for year in years
    }

    sales_payload = []
    for sale in sales:
        vat_registered = vat_registered_by_year.get(sale.created_at.year, False)
        items_payload = []
        for item in sale.items.all():
            line_total = (item.price or Decimal("0.00")) * item.quantity
            use_existing = (
                item.vat_rate != Decimal("0.00")
                or item.vat_amount != Decimal("0.00")
                or item.vat_applicable
            )
            if use_existing:
                vat_display = f"₦{item.vat_amount:.2f}" if item.vat_applicable else "Not eligible"
            else:
                vat_status = getattr(item.product, "vat_status", "standard")
                vat_applicable = bool(vat_registered and vat_status == Product.VAT_STANDARD)
                if vat_applicable:
                    vat_display = f"₦{(line_total * VAT_RATE).quantize(Decimal('0.01')):.2f}"
                else:
                    vat_display = "Not eligible"

            items_payload.append({
                "product_name": item.product.name,
                "quantity": _format_quantity(item.quantity),
                "vat_display": vat_display,
            })

        sales_payload.append({
            "id": sale.id,
            "items_count": float(sale.items.aggregate(total=Sum("quantity"))["total"] or 0),
            "total_amount": _money(sale.total_amount),
            "total_profit": _money(sale.total_profit),
            "amount_paid": _money(getattr(sale, "amount_paid", Decimal("0.00"))),
            "remaining_balance": _money(sale.remaining_balance),
            "payment_status": getattr(sale, "payment_status", Sale.PAYMENT_PAID),
            "branch_name": sale.branch.name if sale.branch_id else "",
            "customer_name": sale.display_customer_name if hasattr(sale, "display_customer_name") else "",
            "created_at": sale.created_at.isoformat(),
            "sales_channel": sale.sales_channel,
            "sales_channel_display": sale.get_sales_channel_display(),
            "handled_by": {
                "name": sale.handled_by_shopboy.full_name if sale.handled_by_shopboy else "Shop Owner",
                "username": sale.handled_by_shopboy.username if sale.handled_by_shopboy else "",
            },
            "items": items_payload,
            "receipt_url": f"/sales/{sale.id}/receipt/",
        })

    return _json_success({
        "summary": {
            "total_sales": _money(total_sales),
            "total_profit": _money(total_profit),
            "total_transactions": total_transactions,
        },
        "sales": sales_payload,
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


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_loans(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    loans = (
        Sale.objects.filter(user=owner, payment_status__in=[Sale.PAYMENT_LOAN, Sale.PAYMENT_PARTIAL])
        .select_related("customer")
        .order_by("-created_at")
    )

    payload = []
    for sale in loans:
        payload.append({
            "id": sale.id,
            "customer_name": sale.display_customer_name,
            "total_amount": _money(sale.total_amount),
            "amount_paid": _money(sale.amount_paid),
            "remaining_balance": _money(sale.remaining_balance),
            "payment_status": sale.payment_status,
            "created_at": sale.created_at.isoformat(),
        })

    return _json_success({ "loans": payload })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_loan_update(request, sale_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    try:
        payment_amount = Decimal(str(data.get("payment_amount")))
        if payment_amount <= 0:
            raise ValueError
    except Exception:
        return _json_error("Payment amount must be greater than 0.")

    sale = get_object_or_404(Sale, id=sale_id, user=owner)
    new_amount_paid = (sale.amount_paid or Decimal("0.00")) + payment_amount
    if new_amount_paid > sale.total_amount:
        new_amount_paid = sale.total_amount

    sale.amount_paid = new_amount_paid.quantize(Decimal("0.01"))
    sale.payment_status = _derive_payment_status(sale.total_amount, sale.amount_paid)
    sale.save(update_fields=["amount_paid", "payment_status"])

    return _json_success({
        "sale": {
            "id": sale.id,
            "amount_paid": _money(sale.amount_paid),
            "remaining_balance": _money(sale.remaining_balance),
            "payment_status": sale.payment_status,
        }
    })


def _serialize_expense(expense):
    return {
        "id": expense.id,
        "branch": _serialize_branch(expense.branch) if getattr(expense, "branch_id", None) else None,
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
        branch_id = (request.GET.get("branch_id") or "").strip()
        expenses = Expense.objects.filter(user=owner).order_by("-date", "-created_at")
        selected_branch = None
        if branch_id:
            feature_error = _json_feature_required(owner, "multi_branch")
            if feature_error:
                return feature_error
            selected_branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
            if not selected_branch:
                return _json_error("Branch not found.", status=404)
            expenses = expenses.filter(branch=selected_branch)
        if q:
            expenses = expenses.filter(
                Q(title__icontains=q) |
                Q(category__icontains=q)
            )

        total_amount = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return _json_success({
            "total_amount": _money(total_amount),
            "branch": _serialize_branch(selected_branch) if selected_branch else None,
            "branches": [_serialize_branch(branch) for branch in _owner_branch_queryset(owner)],
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
    branch_id = (data.get("branch_id") or "").strip()

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

    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    expense = Expense.objects.create(
        user=owner,
        branch=branch,
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
def api_owner_reports(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    now = timezone.now()
    period = request.GET.get("period", "month")
    branch_id = (request.GET.get("branch_id") or "").strip()
    start_date = parse_date((request.GET.get("start_date") or "").strip()) if request.GET.get("start_date") else None
    end_date = parse_date((request.GET.get("end_date") or "").strip()) if request.GET.get("end_date") else None
    custom_range = bool(start_date or end_date)
    if period == "custom" and not custom_range:
        period = "month"
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    if custom_range:
        period = "custom"
        start = None
    else:
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "year":
            start = now.replace(month=1, day=1)
        elif period == "all":
            start = None
        else:
            start = now.replace(day=1)

    sales = Sale.objects.filter(user=owner)
    expenses = Expense.objects.filter(user=owner)
    selected_branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        selected_branch = ShopBranch.objects.filter(user=owner, id=branch_id).first()
        if not selected_branch:
            return _json_error("Branch not found.", status=404)
        sales = sales.filter(branch=selected_branch)
        expenses = expenses.filter(branch=selected_branch)

    if start is not None:
        sales = sales.filter(created_at__gte=start)
        expenses = expenses.filter(date__gte=start.date())
    if start_date:
        sales = sales.filter(created_at__date__gte=start_date)
        expenses = expenses.filter(date__gte=start_date)
    if end_date:
        sales = sales.filter(created_at__date__lte=end_date)
        expenses = expenses.filter(date__lte=end_date)

    total_revenue = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    total_profit = sales.aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
    total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    net_profit = total_profit - total_expenses
    total_transactions = sales.count()
    avg_transaction = (total_revenue / total_transactions) if total_transactions else Decimal("0.00")
    avg_profit_per_sale = (total_profit / total_transactions) if total_transactions else Decimal("0.00")
    items_sold = SaleItem.objects.filter(sale__in=sales).aggregate(total=Sum("quantity"))["total"] or Decimal("0.00")

    profit_margin = Decimal("0.00")
    if total_revenue:
        profit_margin = (total_profit / total_revenue * Decimal("100")).quantize(Decimal("0.01"))

    total_cost = total_revenue - total_profit
    net_margin_percent = ((net_profit / total_revenue) * Decimal("100")).quantize(Decimal("0.01")) if total_revenue else Decimal("0.00")
    expense_ratio_percent = ((total_expenses / total_revenue) * Decimal("100")).quantize(Decimal("0.01")) if total_revenue else Decimal("0.00")

    sold_product_ids = set(
        SaleItem.objects.filter(sale__in=sales)
        .values_list("product_id", flat=True)
        .distinct()
    )
    products_qs = Product.objects.filter(user=owner)
    if selected_branch:
        branch_inventory = BranchInventory.objects.filter(branch=selected_branch, product__user=owner)
        product_stock_rows = [
            {
                "product": row.product,
                "stock": row.stock if row.track_separately else row.product.stock,
                "selling_price": row.selling_price if row.selling_price is not None else row.product.selling_price,
                "cost_price": row.product.cost_price,
            }
            for row in branch_inventory.select_related("product")
        ]
    else:
        product_stock_rows = [
            {
                "product": product,
                "stock": product.stock,
                "selling_price": product.selling_price,
                "cost_price": product.cost_price,
            }
            for product in products_qs
        ]

    stock_value = Decimal("0.00")
    stock_cost = Decimal("0.00")
    stock_by_product = {}
    low_stock_products = []
    out_of_stock_count = 0
    slow_moving_products = []
    for row in product_stock_rows:
        product = row["product"]
        stock = row["stock"] or Decimal("0.00")
        selling_price = row["selling_price"] or Decimal("0.00")
        cost_price = row["cost_price"] or Decimal("0.00")
        stock_by_product[product.id] = stock
        stock_value += selling_price * stock
        stock_cost += cost_price * stock
        if stock <= 0:
            out_of_stock_count += 1
        elif stock <= product.low_stock_threshold:
            low_stock_products.append({"name": product.name, "stock": stock})
        if stock > 0 and product.id not in sold_product_ids:
            slow_moving_products.append({"name": product.name, "stock": stock})

    inventory_profit_potential = stock_value - stock_cost

    top_product_rows = []
    top_product_data = (
        SaleItem.objects.filter(sale__in=sales)
        .values("product_id", "product__name")
        .annotate(quantity=Sum("quantity"), profit=Sum("profit"))
        .order_by("-quantity")[:5]
    )
    for row in top_product_data:
        product_items = SaleItem.objects.filter(sale__in=sales, product_id=row["product_id"])
        revenue = Decimal("0.00")
        for item in product_items:
            revenue += (item.price or Decimal("0.00")) * item.quantity
        top_product_rows.append({
            "product_id": row["product_id"],
            "name": row["product__name"] or "Product",
            "quantity": row["quantity"] or Decimal("0.00"),
            "revenue": revenue,
            "profit": row["profit"] or Decimal("0.00"),
        })

    best_profit_products = sorted(top_product_rows, key=lambda item: item["profit"], reverse=True)[:5]
    low_margin_products = []
    for row in top_product_rows:
        margin = ((row["profit"] / row["revenue"]) * Decimal("100")).quantize(Decimal("0.01")) if row["revenue"] else Decimal("0.00")
        if row["revenue"] and margin < Decimal("15.00"):
            low_margin_products.append({**row, "margin": margin})
    low_margin_products = sorted(low_margin_products, key=lambda item: item["margin"])[:5]

    restock_recommendations = []
    for row in top_product_rows:
        current_stock = stock_by_product.get(row["product_id"], Decimal("0.00"))
        sold_qty = row["quantity"] or Decimal("0.00")
        if sold_qty > 0 and current_stock <= max(Decimal("3.00"), sold_qty * Decimal("0.35")):
            restock_recommendations.append({
                "name": row["name"],
                "sold": sold_qty,
                "stock": current_stock,
                "suggested": max(Decimal("5.00"), sold_qty - current_stock),
            })
    if not restock_recommendations:
        for product in low_stock_products[:5]:
            restock_recommendations.append({
                "name": product["name"],
                "sold": Decimal("0.00"),
                "stock": product["stock"],
                "suggested": Decimal("5.00"),
            })

    top_products = (
        SaleItem.objects.filter(sale__in=sales)
        .values("product__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:5]
    )

    expense_breakdown = (
        expenses.values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    expense_rows = []
    for row in expense_breakdown[:5]:
        amount = row["total"] or Decimal("0.00")
        expense_rows.append({
            "category": row["category"] or "Other",
            "amount": amount,
            "percent": ((amount / total_expenses) * Decimal("100")).quantize(Decimal("0.01")) if total_expenses else Decimal("0.00"),
        })
    highest_expense = expense_breakdown[0] if expense_breakdown else None
    branch_breakdown = (
        Sale.objects.filter(user=owner)
        .values("branch__id", "branch__name")
        .annotate(total=Sum("total_amount"), transactions=Count("id"))
        .order_by("-total")
    )
    branch_rows = list(branch_breakdown)

    branch_comparison = []
    if not selected_branch:
        branches = ShopBranch.objects.filter(user=owner, is_active=True).order_by("name")
        for branch in branches:
            branch_sales = sales.filter(branch=branch)
            branch_expenses = expenses.filter(branch=branch)
            branch_revenue = branch_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
            branch_profit = branch_sales.aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
            branch_expense_total = branch_expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            branch_comparison.append({
                "name": branch.name,
                "sales": branch_revenue,
                "profit": branch_profit,
                "expenses": branch_expense_total,
                "net": branch_profit - branch_expense_total,
                "transactions": branch_sales.count(),
            })
        branch_comparison = sorted(branch_comparison, key=lambda row: row["net"], reverse=True)

    credit_sales = sales.filter(payment_status__in=[Sale.PAYMENT_LOAN, Sale.PAYMENT_PARTIAL])
    credit_total = Decimal("0.00")
    credit_customers = {}
    for sale in credit_sales:
        balance = sale.remaining_balance
        credit_total += balance
        name = sale.display_customer_name or "Walk-in customer"
        credit_customers[name] = credit_customers.get(name, Decimal("0.00")) + balance
    top_credit_customers = [
        {"name": name, "balance": balance}
        for name, balance in sorted(credit_customers.items(), key=lambda item: item[1], reverse=True)[:5]
        if balance > 0
    ]

    customer_sales = {}
    for sale in sales:
        name = sale.display_customer_name or "Walk-in customer"
        if name == "Walk-in customer":
            continue
        row = customer_sales.setdefault(name, {"name": name, "sales": Decimal("0.00"), "visits": 0})
        row["sales"] += sale.total_amount or Decimal("0.00")
        row["visits"] += 1
    top_customers = sorted(customer_sales.values(), key=lambda item: item["sales"], reverse=True)[:5]
    repeat_customer_count = len([row for row in customer_sales.values() if row["visits"] > 1])
    customer_count_qs = Customer.objects.filter(user=owner)
    if selected_branch:
        customer_count_qs = customer_count_qs.filter(Q(branch=selected_branch) | Q(sale__branch=selected_branch)).distinct()
    customer_count = customer_count_qs.count()

    expense_warnings = []
    if expense_rows and expense_rows[0]["percent"] > Decimal("45.00"):
        expense_warnings.append({
            "title": f"{expense_rows[0]['category']} is dominating expenses",
            "message": f"{expense_rows[0]['category']} takes {expense_rows[0]['percent']}% of expenses in this period.",
        })

    health_score = Decimal("50.00")
    if total_transactions:
        health_score += Decimal("10.00")
    if total_revenue and profit_margin >= Decimal("25.00"):
        health_score += Decimal("15.00")
    elif total_revenue and profit_margin < Decimal("15.00"):
        health_score -= Decimal("10.00")
    if net_profit > 0:
        health_score += Decimal("15.00")
    else:
        health_score -= Decimal("15.00")
    if total_revenue and expense_ratio_percent <= Decimal("30.00"):
        health_score += Decimal("10.00")
    elif total_revenue and expense_ratio_percent > Decimal("50.00"):
        health_score -= Decimal("10.00")
    low_stock_count = len(low_stock_products)
    if low_stock_count:
        health_score -= min(Decimal("10.00"), Decimal(low_stock_count * 2))
    if credit_total > 0 and total_revenue and credit_total > total_revenue * Decimal("0.25"):
        health_score -= Decimal("10.00")
    health_score = max(Decimal("0.00"), min(Decimal("100.00"), health_score)).quantize(Decimal("1"))

    analysis_allowed = _plan_has_feature(owner, "advanced_reports")
    business_recommendations = []
    business_warnings = []
    if analysis_allowed:
        if total_transactions == 0:
            business_recommendations.append("No sales were recorded in this period. Start by recording every sale so VilaStore can calculate useful trends.")
        elif profit_margin < Decimal("10.00"):
            business_warnings.append("Profit margin is low for this period.")
            business_recommendations.append("Review selling prices, supplier cost, discounts, and slow-moving stock.")
        else:
            business_recommendations.append("Profit margin looks healthy for this period. Keep tracking expenses so the net profit stays accurate.")

        if total_expenses > total_profit and total_expenses > 0:
            business_warnings.append("Expenses are higher than profit in this period.")
            business_recommendations.append("Reduce non-essential expenses or increase high-margin product sales.")

        if highest_expense:
            business_recommendations.append(
                f"Your biggest expense category is {highest_expense['category'] or 'Uncategorized'} at NGN {_money(highest_expense['total'] or Decimal('0.00'))}."
            )

        if branch_rows and branch_rows[0]["branch__id"]:
            business_recommendations.append(f"{branch_rows[0]['branch__name']} is your strongest branch in this view.")

    action_recommendations = []
    if restock_recommendations:
        action_recommendations.append(f"Restock {restock_recommendations[0]['name']} first; it is selling faster than current stock.")
    if low_margin_products:
        action_recommendations.append(f"Review pricing or supplier cost for {low_margin_products[0]['name']} because its margin is low.")
    if expense_warnings:
        action_recommendations.append("Check your largest expense category and reduce non-essential spending this week.")
    if top_credit_customers:
        action_recommendations.append(f"Follow up with {top_credit_customers[0]['name']} about outstanding credit.")
    if slow_moving_products:
        action_recommendations.append(f"Promote or discount {slow_moving_products[0]['name']} because it has stock but no sales in this period.")
    if branch_comparison:
        action_recommendations.append(f"Use {branch_comparison[0]['name']} as the branch benchmark because it currently has the best net result.")
    if not action_recommendations:
        action_recommendations.append("Keep recording sales, expenses, and customers daily so VilaStore can keep improving recommendations.")

    business_insights = []
    if total_transactions == 0:
        business_insights.append({
            "tone": "warning",
            "title": "No sales in this period",
            "message": "Record sales consistently so VilaStore can show useful trends and product performance.",
        })
    if total_revenue and profit_margin < Decimal("20.00"):
        business_insights.append({
            "tone": "warning",
            "title": "Profit margin is low",
            "message": "Review selling prices, supplier costs, and discounts. A stronger margin gives the business more breathing room.",
        })
    if net_profit < 0:
        business_insights.append({
            "tone": "danger",
            "title": "Expenses are eating profit",
            "message": "Your net profit is negative for this period. Check the biggest expenses and reduce non-essential spending.",
        })
    elif total_revenue and expense_ratio_percent > Decimal("40.00"):
        business_insights.append({
            "tone": "warning",
            "title": "Expense ratio is high",
            "message": "Expenses are taking a large share of revenue. Compare rent, salaries, transport, and supplies.",
        })
    if top_product_rows:
        business_insights.append({
            "tone": "success",
            "title": "Best-selling product found",
            "message": f"{top_product_rows[0]['name']} sold the most in this period. Keep it in stock and consider promoting related items.",
        })
    if low_stock_products:
        business_insights.append({
            "tone": "warning",
            "title": "Low stock needs attention",
            "message": f"{len(low_stock_products)} product(s) are close to running out. Restock fast-moving items before sales are lost.",
        })
    if slow_moving_products:
        business_insights.append({
            "tone": "neutral",
            "title": "Some stock is not moving",
            "message": "Products with stock but no sales in this period may need discounts, better display, or supplier review.",
        })
    if not business_insights:
        business_insights.append({
            "tone": "success",
            "title": "Business looks healthy",
            "message": "Sales, profit, and expenses look balanced for this period. Keep tracking daily to spot changes early.",
        })

    try:
        cit_year = int(request.GET.get("cit_year", now.year))
    except (TypeError, ValueError):
        cit_year = now.year

    year_sales = Sale.objects.filter(created_at__year=cit_year, user=owner)
    year_expenses = Expense.objects.filter(created_at__year=cit_year, user=owner)

    cit_revenue = year_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    cit_profit = year_sales.aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")
    cit_cost = cit_revenue - cit_profit
    cit_gross_profit = cit_profit
    cit_operating_expenses = year_expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    cit_assessable_profit = cit_gross_profit - cit_operating_expenses
    cit_taxable_profit = max(Decimal("0.00"), cit_assessable_profit)
    cit_small_turnover_threshold = Decimal("50000000")
    cit_small_fixed_assets_threshold = Decimal("250000000")
    cit_rate = Decimal("0.30")
    cit_rate_label = "Standard rate (30%)"
    cit_rate_note = ""
    fixed_assets_value = owner.fixed_assets
    is_professional_services = bool(owner.is_professional_services)
    missing_assets = fixed_assets_value is None
    qualifies_small_by_assets = (fixed_assets_value is not None and fixed_assets_value <= cit_small_fixed_assets_threshold)

    if cit_revenue <= cit_small_turnover_threshold and qualifies_small_by_assets and not is_professional_services:
        cit_rate = Decimal("0.00")
        cit_rate_label = "Small company rate (0%)"
    elif cit_revenue <= cit_small_turnover_threshold and missing_assets:
        cit_rate_note = "Fixed assets are missing; small-company test cannot be fully applied."
    elif is_professional_services and cit_revenue <= cit_small_turnover_threshold:
        cit_rate_note = "Professional services companies do not qualify for small-company CIT relief."

    cit_tax_due = (cit_taxable_profit * cit_rate)
    cit_rate_percent = (cit_rate * Decimal("100")).quantize(Decimal("0.01"))

    try:
        vat_month = int(request.GET.get("vat_month", now.month))
    except (TypeError, ValueError):
        vat_month = now.month
    try:
        vat_year = int(request.GET.get("vat_year", now.year))
    except (TypeError, ValueError):
        vat_year = now.year
    if vat_month < 1 or vat_month > 12:
        vat_month = now.month

    month_start = datetime(vat_year, vat_month, 1)
    month_end = datetime(vat_year + 1, 1, 1) if vat_month == 12 else datetime(vat_year, vat_month + 1, 1)

    vat_sales = Sale.objects.filter(created_at__range=(month_start, month_end), user=owner)
    vat_year_turnover = _year_turnover(owner, vat_year)
    vat_registered = _is_vat_registered(owner, vat_year_turnover)
    vat_registration_note = _vat_registration_note(owner, vat_year_turnover)

    vat_taxable_sales = Decimal("0.00")
    vat_output_vat = Decimal("0.00")
    if vat_registered:
        vat_items = SaleItem.objects.filter(sale__in=vat_sales).select_related("product")
        for item in vat_items:
            line_total = (item.price or Decimal("0.00")) * item.quantity
            use_existing = (item.vat_rate != Decimal("0.00") or item.vat_amount != Decimal("0.00") or item.vat_applicable)
            if use_existing:
                if item.vat_applicable:
                    vat_taxable_sales += line_total
                    vat_output_vat += item.vat_amount
                continue
            vat_status = getattr(item.product, "vat_status", "standard")
            if vat_status == Product.VAT_STANDARD:
                vat_taxable_sales += line_total
                vat_output_vat += (line_total * VAT_RATE).quantize(Decimal("0.01"))

    return _json_success({
        "period": period,
        "branch": _serialize_branch(selected_branch) if selected_branch else None,
        "branches": [_serialize_branch(branch) for branch in _owner_branch_queryset(owner)],
        "start_date": start_date.isoformat() if start_date else "",
        "end_date": end_date.isoformat() if end_date else "",
        "totals": {
            "total_revenue": _money(total_revenue),
            "total_profit": _money(total_profit),
            "total_expenses": _money(total_expenses),
            "net_profit": _money(net_profit),
            "total_transactions": total_transactions,
        },
        "summary": {
            "avg_transaction": _money(avg_transaction),
            "items_sold": str(items_sold),
            "avg_profit_per_sale": _money(avg_profit_per_sale),
            "total_cost": _money(total_cost),
            "profit_margin": str(profit_margin),
        },
        "top_products": [
            { "name": row["product__name"], "total": float(row["total"] or 0) }
            for row in top_products
        ],
        "branch_performance": [
            {
                "id": row["branch__id"],
                "name": row["branch__name"] or "Unassigned",
                "total_revenue": _money(row["total"] or Decimal("0.00")),
                "transactions": row["transactions"] or 0,
            }
            for row in branch_rows
        ],
        "expense_breakdown": [
            { "category": row["category"], "total": _money(row["total"]) }
            for row in expense_breakdown
        ],
        "business_analysis": {
            "available": analysis_allowed,
            "upgrade_message": "" if analysis_allowed else _feature_upgrade_message("advanced_reports"),
            "summary": (
                "Advanced business analysis is ready for this period."
                if analysis_allowed else
                "Upgrade to unlock mobile business analysis, warnings, and recommendations."
            ),
            "recommendations": business_recommendations if analysis_allowed else [],
            "warnings": business_warnings if analysis_allowed else [],
            "profit_margin": str(profit_margin),
            "net_profit": _money(net_profit),
            "expense_ratio": str((total_expenses / total_profit * Decimal("100")).quantize(Decimal("0.01")) if total_profit else Decimal("0.00")),
            "health_score": str(health_score),
            "gross_margin_percent": str(profit_margin),
            "net_margin_percent": str(net_margin_percent),
            "expense_ratio_percent": str(expense_ratio_percent),
            "customer_count": customer_count,
            "credit_total": _money(credit_total),
            "credit_sales_count": credit_sales.count(),
            "stock_value": _money(stock_value),
            "stock_cost": _money(stock_cost),
            "inventory_profit_potential": _money(inventory_profit_potential),
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "repeat_customer_count": repeat_customer_count,
            "action_recommendations": action_recommendations if analysis_allowed else [],
            "business_insights": business_insights if analysis_allowed else [],
            "top_product_rows": [
                {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "quantity": str(row["quantity"]),
                    "revenue": _money(row["revenue"]),
                    "profit": _money(row["profit"]),
                }
                for row in top_product_rows
            ] if analysis_allowed else [],
            "best_profit_products": [
                {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "quantity": str(row["quantity"]),
                    "profit": _money(row["profit"]),
                }
                for row in best_profit_products
            ] if analysis_allowed else [],
            "low_margin_products": [
                {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "margin": str(row["margin"]),
                    "profit": _money(row["profit"]),
                }
                for row in low_margin_products
            ] if analysis_allowed else [],
            "restock_recommendations": [
                {
                    "name": row["name"],
                    "sold": str(row["sold"]),
                    "stock": str(row["stock"]),
                    "suggested": str(row["suggested"]),
                }
                for row in restock_recommendations
            ] if analysis_allowed else [],
            "expense_rows": [
                {
                    "category": row["category"],
                    "amount": _money(row["amount"]),
                    "percent": str(row["percent"]),
                }
                for row in expense_rows
            ] if analysis_allowed else [],
            "expense_warnings": expense_warnings if analysis_allowed else [],
            "low_stock_products": [
                {"name": row["name"], "stock": str(row["stock"])}
                for row in low_stock_products[:5]
            ] if analysis_allowed else [],
            "slow_moving_products": [
                {"name": row["name"], "stock": str(row["stock"])}
                for row in slow_moving_products[:5]
            ] if analysis_allowed else [],
            "top_customers": [
                {"name": row["name"], "sales": _money(row["sales"]), "visits": row["visits"]}
                for row in top_customers
            ] if analysis_allowed else [],
            "top_credit_customers": [
                {"name": row["name"], "balance": _money(row["balance"])}
                for row in top_credit_customers
            ] if analysis_allowed else [],
            "branch_comparison": [
                {
                    "name": row["name"],
                    "sales": _money(row["sales"]),
                    "profit": _money(row["profit"]),
                    "expenses": _money(row["expenses"]),
                    "net": _money(row["net"]),
                    "transactions": row["transactions"],
                }
                for row in branch_comparison
            ] if analysis_allowed else [],
        },
        "cit": {
            "available": _plan_has_feature(owner, "tax_tools"),
            "upgrade_message": "" if _plan_has_feature(owner, "tax_tools") else _feature_upgrade_message("tax_tools"),
            "cit_year": cit_year,
            "cit_revenue": _money(cit_revenue),
            "cit_cost": _money(cit_cost),
            "cit_gross_profit": _money(cit_gross_profit),
            "cit_operating_expenses": _money(cit_operating_expenses),
            "cit_assessable_profit": _money(cit_assessable_profit),
            "cit_taxable_profit": _money(cit_taxable_profit),
            "cit_tax_due": _money(cit_tax_due),
            "cit_rate_percent": str(cit_rate_percent),
            "cit_rate_label": cit_rate_label,
            "cit_rate_note": cit_rate_note,
            "cit_small_turnover_threshold": _money(cit_small_turnover_threshold),
            "cit_small_fixed_assets_threshold": _money(cit_small_fixed_assets_threshold),
            "fixed_assets": _money(owner.fixed_assets) if owner.fixed_assets is not None else "",
            "is_professional_services": bool(owner.is_professional_services),
        },
        "vat": {
            "available": _plan_has_feature(owner, "tax_tools"),
            "upgrade_message": "" if _plan_has_feature(owner, "tax_tools") else _feature_upgrade_message("tax_tools"),
            "vat_year": vat_year,
            "vat_month": vat_month,
            "vat_taxable_sales": _money(vat_taxable_sales),
            "vat_output_vat": _money(vat_output_vat),
            "vat_registered": vat_registered,
            "vat_registration_note": vat_registration_note,
        },
        "is_nigeria": (owner.country or "").strip().lower() == "nigeria",
        "entitlements": _feature_entitlements(owner),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_ai_summary(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    return _json_success({"ai": ai_engine.ai_summary(owner)})


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_ai_product_search(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    query = request.GET.get("q", "")
    return _json_success({"query": query, "results": ai_engine.smart_product_search(owner, query)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_ai_voice(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    data = _get_body_data(request) or {}
    transcript = (data.get("transcript") or "").strip()
    parsed = ai_engine.parse_voice_command(owner, transcript)
    parsed["product_form"] = ai_engine.parse_product_voice_form(transcript)
    return _json_success({"parsed": parsed})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_ai_inventory_assistant(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request) or {}
    command = (data.get("command") or data.get("transcript") or "").strip()
    mode = (data.get("mode") or "product").strip().lower()
    if not command:
        return _json_error("Type or speak a command first.")

    parsed = ai_engine.parse_inventory_command(command, mode=mode)
    resolved_mode = "category" if parsed.get("action") == "create_category" else "product"
    return _json_success({
        "mode": resolved_mode,
        "parsed": parsed,
        "missing": parsed.get("missing", []),
        "can_save": not parsed.get("missing"),
        "message": parsed.get("message"),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_ai_barcode_prefill(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    data = _get_body_data(request) or {}
    barcode = data.get("barcode") or data.get("code") or ""
    return _json_success({"prefill": ai_engine.product_prefill_from_barcode(owner, barcode)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_ai_receipt_scan(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    data = _get_body_data(request) or {}
    raw_text = (data.get("receipt_text") or "").strip()
    parsed_items = ai_engine.parse_receipt_text(owner, raw_text)
    apply_inventory = str(data.get("apply_inventory") or "").lower() in {"1", "true", "yes", "on"}
    inventory = {"updated": [], "skipped": parsed_items}
    status = AIReceiptScan.STATUS_PARSED if parsed_items else AIReceiptScan.STATUS_NEEDS_REVIEW
    if apply_inventory and parsed_items:
        inventory = ai_engine.apply_receipt_inventory(owner, parsed_items)
        status = AIReceiptScan.STATUS_APPLIED if inventory["updated"] else AIReceiptScan.STATUS_NEEDS_REVIEW
    scan = AIReceiptScan.objects.create(user=owner, raw_text=raw_text, parsed_items=parsed_items, status=status)
    return _json_success({"scan_id": scan.id, "parsed_items": parsed_items, "inventory": inventory})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_ai_chat(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "ai_business_analysis")
    if feature_error:
        return feature_error
    data = _get_body_data(request) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return _json_error("Ask a question first.")
    answer = ai_engine.assistant_answer(owner, question)
    AIAssistantMessage.objects.create(user=owner, question=question, answer=answer)
    return _json_success({"answer": answer})


def _serialize_customer(customer):
    return {
        "id": customer.id,
        "branch": _serialize_branch(customer.branch) if getattr(customer, "branch_id", None) else None,
        "first_name": customer.first_name,
        "last_name": customer.last_name,
        "phone": customer.phone,
        "email": customer.email or "",
        "birthday": customer.birthday.isoformat() if customer.birthday else "",
        "religion": customer.religion or "",
        "tribe": customer.tribe or "",
        "notes": customer.notes or "",
        "created_at": customer.created_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_customers(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        branch_id = (request.GET.get("branch_id") or "").strip()
        customers = Customer.objects.filter(user=owner)
        selected_branch = None
        if branch_id:
            feature_error = _json_feature_required(owner, "multi_branch")
            if feature_error:
                return feature_error
            selected_branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
            if not selected_branch:
                return _json_error("Branch not found.", status=404)
            customers = customers.filter(Q(branch=selected_branch) | Q(sale__branch=selected_branch)).distinct()
        if q:
            customers = customers.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(phone__icontains=q) |
                Q(email__icontains=q) |
                Q(religion__icontains=q) |
                Q(tribe__icontains=q)
            )
        customers = customers.order_by("first_name", "last_name")
        return _json_success({
            "customers": [_serialize_customer(c) for c in customers],
            "branch": _serialize_branch(selected_branch) if selected_branch else None,
            "branches": [_serialize_branch(branch) for branch in _owner_branch_queryset(owner)],
            "religions": [choice[0] for choice in Customer.RELIGION_CHOICES],
            "entitlements": _feature_entitlements(owner),
        })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip() or None
    birthday = (data.get("birthday") or "").strip() or None
    religion = (data.get("religion") or "").strip()
    tribe = (data.get("tribe") or "").strip()
    notes = (data.get("notes") or "").strip()
    branch_id = (data.get("branch_id") or "").strip()

    if not first_name or not last_name or not phone:
        return _json_error("First name, last name, and phone are required.")

    advanced_values = [email, birthday, religion, tribe, notes]
    if any(advanced_values):
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error

    valid_religions = {choice[0] for choice in Customer.RELIGION_CHOICES}
    if religion not in valid_religions:
        religion = ""
    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    customer = Customer.objects.create(
        user=owner,
        branch=branch,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        birthday=birthday or None,
        religion=religion,
        tribe=tribe,
        notes=notes,
    )
    return _json_success({ "customer": _serialize_customer(customer) }, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_owner_customer_detail(request, customer_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    customer = get_object_or_404(Customer, id=customer_id, user=owner)

    if request.method == "GET":
        return _json_success({ "customer": _serialize_customer(customer) })

    if request.method == "DELETE":
        customer.delete()
        return _json_success({ "deleted": True })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    if "first_name" in data:
        customer.first_name = (data.get("first_name") or "").strip()
    if "last_name" in data:
        customer.last_name = (data.get("last_name") or "").strip()
    if "phone" in data:
        customer.phone = (data.get("phone") or "").strip()
    if "email" in data:
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error
        email = (data.get("email") or "").strip()
        customer.email = email or None
    if "birthday" in data:
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error
        birthday = (data.get("birthday") or "").strip()
        customer.birthday = birthday or None
    if "religion" in data:
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error
        religion = (data.get("religion") or "").strip()
        valid_religions = {choice[0] for choice in Customer.RELIGION_CHOICES}
        customer.religion = religion if religion in valid_religions else ""
    if "tribe" in data:
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error
        customer.tribe = (data.get("tribe") or "").strip()
    if "notes" in data:
        feature_error = _json_feature_required(owner, "full_customer_management")
        if feature_error:
            return feature_error
        customer.notes = (data.get("notes") or "").strip()

    if not customer.first_name or not customer.last_name or not customer.phone:
        return _json_error("First name, last name, and phone are required.")

    customer.save()
    return _json_success({ "customer": _serialize_customer(customer) })


def _serialize_shopboy_settings(shopboy):
    return {
        "id": shopboy.id,
        "full_name": shopboy.full_name,
        "username": shopboy.username,
        "role": shopboy.role,
        "role_label": shopboy.get_role_display(),
        "branch_id": shopboy.branch_id,
        "branch_name": shopboy.branch.name if shopboy.branch_id else "",
        "can_use_marketplace": shopboy.can_use_marketplace,
        "is_active": shopboy.is_active,
    }


def _owner_branch_queryset(owner):
    return ShopBranch.objects.filter(user=owner).order_by("name", "id")


def _default_branch_for_owner(owner):
    branch = _owner_branch_queryset(owner).filter(is_default=True).first() or _owner_branches_qs_first(owner)
    if branch:
        return branch
    if owner.account_type != User.ACCOUNT_TYPE_SHOP:
        return None
    return ShopBranch.objects.create(
        user=owner,
        name=(owner.business_name or owner.username or "Main Shop").strip(),
        phone=owner.phone or "",
        address=owner.address or "Main address",
        city="",
        state=owner.state or "",
        is_default=True,
    )


def _owner_branches_qs_first(owner):
    return _owner_branch_queryset(owner).first()


def _serialize_branch_summary(owner, branch):
    sales = Sale.objects.filter(user=owner, branch=branch)
    orders = MarketplaceOrder.objects.filter(shop_owner=owner, branch=branch)
    revenue = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    product_count = BranchInventory.objects.filter(branch=branch, is_active=True).count()
    active_staff = ShopBoy.objects.filter(user=owner, branch=branch, is_active=True).count()
    return {
        **_serialize_branch(branch),
        "stats": {
            "sales_count": sales.count(),
            "orders_count": orders.count(),
            "revenue": _money(revenue),
            "product_count": product_count,
            "active_staff": active_staff,
        },
    }


def _serialize_business_branch_analytics(owner):
    branches = list(_owner_branch_queryset(owner))
    summaries = [_serialize_branch_summary(owner, branch) for branch in branches]
    best_branch = None
    if summaries:
        best_branch = max(summaries, key=lambda item: Decimal(item["stats"]["revenue"]))
    total_revenue = Sale.objects.filter(user=owner).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    return {
        "branches": summaries,
        "summary": {
            "branch_count": len(branches),
            "active_branch_count": sum(1 for branch in branches if branch.is_active),
            "total_revenue": _money(total_revenue),
            "best_performing_branch": {
                "id": best_branch["id"],
                "name": best_branch["name"],
                "revenue": best_branch["stats"]["revenue"],
            } if best_branch else None,
        },
    }


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_settings(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    _ensure_shop_code(owner)
    marketplace_settings = _get_marketplace_settings(owner)
    marketplace_profile, _ = MarketplaceShopProfile.objects.get_or_create(user=owner)
    branches = list(_owner_branch_queryset(owner))
    if not branches:
        default_branch = ShopBranch.objects.create(
            user=owner,
            name=(owner.business_name or owner.username or "Main Shop").strip(),
            phone=owner.phone or "",
            address=owner.address or "Main address",
            city="",
            state=owner.state or "",
            is_default=True,
        )
        branches = [default_branch]
    shopboys = ShopBoy.objects.filter(user=owner).select_related("branch").order_by("-id")

    return _json_success({
        "shop_code": owner.shop_code or "",
        "profile": {
            "username": owner.username or "",
            "email": owner.email or "",
            "business_name": owner.business_name or "",
            "country": owner.country or "",
            "address": owner.address or "",
            "phone": owner.phone or "",
            "bank_name": owner.bank_name or "",
            "bank_account_number": owner.bank_account_number or "",
            "bank_account_name": owner.bank_account_name or "",
            "fixed_assets": _money(owner.fixed_assets) if owner.fixed_assets is not None else "",
            "is_professional_services": bool(owner.is_professional_services),
            "profile_image_url": _abs_media_url(request, owner.profile_image),
        },
        "marketplace_profile": {
            "logo_url": _abs_media_url(request, marketplace_profile.logo),
            "cover_url": _abs_media_url(request, marketplace_profile.cover_image),
        },
        "branches": [_serialize_branch_summary(owner, branch) for branch in branches],
        "branch_analytics": _serialize_business_branch_analytics(owner)["summary"],
        "shopboys": [_serialize_shopboy_settings(sb) for sb in shopboys],
        "marketplace_assignment": {
            "assigned_shopboy_id": marketplace_settings.assigned_shopboy_id,
        },
        "entitlements": _feature_entitlements(owner),
        "plan": PLAN_LIMITS.get(getattr(owner, "plan", "starter")) or PLAN_LIMITS["starter"],
        "subscription": {
            "plan_slug": getattr(owner, "plan", "starter") or "starter",
            "is_paid": bool(owner.is_paid),
            "active_until": owner.subscription_active_until.isoformat() if owner.subscription_active_until else "",
        },
        "upgrade_options": _subscription_upgrade_options(owner),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_subscription_upgrade_start(request):
    token_obj, _ = _get_auth_from_request(request)
    if not token_obj or token_obj.role != AuthToken.ROLE_OWNER or not token_obj.owner:
        return _json_error("Unauthorized.", status=401)

    owner = token_obj.owner
    data = _get_body_data(request) or {}
    target_plan_slug = (data.get("plan") or "").strip().lower()
    available_plan_slugs = {option["slug"] for option in _subscription_upgrade_options(owner)}
    if target_plan_slug not in available_plan_slugs:
        return _json_error("Choose a valid higher plan to upgrade.", status=400)

    query = urlencode({"token": token_obj.token, "plan": target_plan_slug})
    checkout_url = request.build_absolute_uri(f"{reverse('mobile_subscription_upgrade_checkout')}?{query}")
    target_plan = _plan_for_slug(target_plan_slug)
    return _json_success({
        "checkout_url": checkout_url,
        "plan": {
            "slug": target_plan_slug,
            "name": target_plan["name"],
            "monthly_fee": _money(target_plan["monthly_fee"]),
        },
        "message": f"Complete payment to upgrade to {target_plan['name']}.",
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_profile(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request) or {}
    business_name = (data.get("business_name") or "").strip()
    country = (data.get("country") or "").strip()
    address = (data.get("address") or "").strip()
    phone = (data.get("phone") or "").strip()
    bank_name = (data.get("bank_name") or "").strip()
    bank_account_number = (data.get("bank_account_number") or "").strip()
    bank_account_name = (data.get("bank_account_name") or "").strip()
    fixed_assets_raw = (data.get("fixed_assets") or "").strip()
    is_professional_services_raw = (data.get("is_professional_services") or "").strip().lower()
    is_professional_services = is_professional_services_raw in {"true", "1", "on", "yes"}

    if not business_name or not country or not address or not phone:
        return _json_error("Business name, country, address, and phone are required.")

    tax_update_requested = bool(fixed_assets_raw or is_professional_services)
    save_fields = [
        "business_name",
        "country",
        "address",
        "phone",
        "profile_image",
        "bank_name",
        "bank_account_number",
        "bank_account_name",
    ]
    if tax_update_requested and not _plan_has_feature(owner, "tax_tools"):
        feature_error = _json_feature_required(owner, "tax_tools")
        if feature_error:
            return feature_error

    if _plan_has_feature(owner, "tax_tools"):
        if fixed_assets_raw:
            try:
                fixed_assets_value = Decimal(fixed_assets_raw)
                if fixed_assets_value < 0:
                    raise ValueError
                owner.fixed_assets = fixed_assets_value
            except Exception:
                return _json_error("Fixed assets must be a valid non-negative amount.")
        else:
            owner.fixed_assets = None
        owner.is_professional_services = is_professional_services
        save_fields.extend(["fixed_assets", "is_professional_services"])

    owner.business_name = business_name
    owner.country = country
    owner.address = address
    owner.phone = phone
    owner.bank_name = bank_name
    owner.bank_account_number = bank_account_number
    owner.bank_account_name = bank_account_name

    profile_image = request.FILES.get("profile_image")
    if profile_image:
        owner.profile_image = profile_image

    owner.save(update_fields=save_fields)

    marketplace_profile, _ = MarketplaceShopProfile.objects.get_or_create(user=owner)
    marketplace_logo = request.FILES.get("marketplace_logo")
    if marketplace_logo:
        marketplace_profile.logo = marketplace_logo
    marketplace_cover = request.FILES.get("marketplace_cover_image")
    if marketplace_cover:
        marketplace_profile.cover_image = marketplace_cover
    if marketplace_logo or marketplace_cover:
        marketplace_profile.save(update_fields=["logo", "cover_image"])

    return _json_success({
        "profile": {
            "business_name": owner.business_name or "",
            "country": owner.country or "",
            "address": owner.address or "",
            "phone": owner.phone or "",
            "bank_name": owner.bank_name or "",
            "bank_account_number": owner.bank_account_number or "",
            "bank_account_name": owner.bank_account_name or "",
            "fixed_assets": _money(owner.fixed_assets) if owner.fixed_assets is not None else "",
            "is_professional_services": bool(owner.is_professional_services),
            "profile_image_url": _abs_media_url(request, owner.profile_image),
        },
        "marketplace_profile": {
            "logo_url": _abs_media_url(request, marketplace_profile.logo),
            "cover_url": _abs_media_url(request, marketplace_profile.cover_image),
        },
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_settings_shopboys(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        shopboys = ShopBoy.objects.filter(user=owner).select_related("branch").order_by("-id")
        return _json_success({ "shopboys": [_serialize_shopboy_settings(sb) for sb in shopboys] })

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    full_name = (data.get("full_name") or "").strip()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or ShopBoy.ROLE_STAFF).strip().lower()
    branch_id = data.get("branch_id") or None
    can_use_marketplace_raw = data.get("can_use_marketplace")
    if isinstance(can_use_marketplace_raw, str):
        can_use_marketplace = can_use_marketplace_raw.strip().lower() in {"true", "1", "yes", "on"}
    else:
        can_use_marketplace = bool(can_use_marketplace_raw)

    if not full_name or not username or not password:
        return _json_error("Full name, username, and password are required.")

    plan, staff_limit = _plan_limit(owner, "staff_limit")
    if staff_limit is not None and ShopBoy.objects.filter(user=owner).count() >= staff_limit:
        return _json_error(_plan_limit_error("staff", plan["name"]), status=403)

    valid_roles = {choice[0] for choice in ShopBoy.ROLE_CHOICES}
    if role not in valid_roles:
        role = ShopBoy.ROLE_STAFF

    if ShopBoy.objects.filter(user=owner, username__iexact=username).exists():
        return _json_error("Shop boy username already exists.")

    branch = None
    if branch_id:
        feature_error = _json_feature_required(owner, "multi_branch")
        if feature_error:
            return feature_error
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Invalid branch selection.")

    shopboy = ShopBoy.objects.create(
        user=owner,
        branch=branch,
        full_name=full_name,
        username=username,
        password=make_password(password),
        role=role,
        can_use_marketplace=can_use_marketplace,
        is_active=True,
    )
    return _json_success({ "shopboy": _serialize_shopboy_settings(shopboy) }, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_owner_settings_branches(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    if request.method == "GET":
        return _json_success(_serialize_business_branch_analytics(owner))

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip()
    if not name or not address:
        return _json_error("Branch name and address are required.")

    plan, branch_limit = _plan_limit(owner, "branch_limit")
    if not _plan_has_feature(owner, "multi_branch") and ShopBranch.objects.filter(user=owner, is_active=True).count() >= 1:
        return _json_error(_feature_upgrade_message("multi_branch"), status=403, feature="multi_branch", upgrade_required=True)
    if branch_limit is not None and ShopBranch.objects.filter(user=owner, is_active=True).count() >= branch_limit:
        return _json_error(_plan_limit_error("branch", plan["name"]), status=403)

    branch = ShopBranch.objects.create(
        user=owner,
        name=name,
        phone=(data.get("phone") or "").strip(),
        address=address,
        city=(data.get("city") or "").strip(),
        state=(data.get("state") or owner.state or "").strip(),
        latitude=_to_decimal(data.get("latitude")),
        longitude=_to_decimal(data.get("longitude")),
        is_active=str(data.get("is_active", "true")).strip().lower() in {"true", "1", "yes", "on"},
        is_default=str(data.get("is_default", "")).strip().lower() in {"true", "1", "yes", "on"},
    )
    return _json_success({"branch": _serialize_branch_summary(owner, branch)}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_branch_update(request, branch_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "multi_branch")
    if feature_error:
        return feature_error

    branch = get_object_or_404(ShopBranch, user=owner, id=branch_id)
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    if "name" in data:
        branch.name = (data.get("name") or "").strip() or branch.name
    if "phone" in data:
        branch.phone = (data.get("phone") or "").strip()
    if "address" in data:
        branch.address = (data.get("address") or "").strip() or branch.address
    if "city" in data:
        branch.city = (data.get("city") or "").strip()
    if "state" in data:
        branch.state = (data.get("state") or "").strip()
    if "latitude" in data:
        branch.latitude = _to_decimal(data.get("latitude"))
    if "longitude" in data:
        branch.longitude = _to_decimal(data.get("longitude"))
    if "is_active" in data:
        branch.is_active = str(data.get("is_active")).strip().lower() in {"true", "1", "yes", "on"}
    if "is_default" in data:
        branch.is_default = str(data.get("is_default")).strip().lower() in {"true", "1", "yes", "on"}
    branch.save()
    return _json_success({"branch": _serialize_branch_summary(owner, branch)})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_branch_delete(request, branch_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)
    feature_error = _json_feature_required(owner, "multi_branch")
    if feature_error:
        return feature_error

    branch = get_object_or_404(ShopBranch, user=owner, id=branch_id)
    if ShopBranch.objects.filter(user=owner).count() <= 1:
        return _json_error("At least one branch must remain.")

    fallback = ShopBranch.objects.filter(user=owner).exclude(id=branch.id).order_by("-is_default", "id").first()
    ShopBoy.objects.filter(user=owner, branch=branch).update(branch=fallback)
    Sale.objects.filter(user=owner, branch=branch).update(branch=fallback)
    Expense.objects.filter(user=owner, branch=branch).update(branch=fallback)
    MarketplaceOrder.objects.filter(shop_owner=owner, branch=branch).update(branch=fallback)
    branch.delete()
    if fallback and not ShopBranch.objects.filter(user=owner, is_default=True).exists():
        fallback.is_default = True
        fallback.save(update_fields=["is_default"])
    return _json_success({"deleted": True, "fallback_branch_id": fallback.id if fallback else None})


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_shopboy_toggle(request, shopboy_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    shopboy = get_object_or_404(ShopBoy, id=shopboy_id, user=owner)
    shopboy.is_active = not shopboy.is_active
    shopboy.save(update_fields=["is_active"])
    return _json_success({ "shopboy": _serialize_shopboy_settings(shopboy) })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_shopboy_delete(request, shopboy_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    shopboy = get_object_or_404(ShopBoy, id=shopboy_id, user=owner)
    shopboy.delete()
    return _json_success({ "deleted": True })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_settings_marketplace_assign(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    shopboy_id = data.get("assigned_shopboy") or None
    assigned = None
    if shopboy_id:
        assigned = ShopBoy.objects.filter(
            id=shopboy_id,
            user=owner,
            is_active=True,
            can_use_marketplace=True,
        ).first()
        if not assigned:
            return _json_error("Invalid shop boy selection.")

    settings_obj = _get_marketplace_settings(owner)
    settings_obj.assigned_shopboy = assigned
    settings_obj.save(update_fields=["assigned_shopboy", "updated_at"])
    return _json_success({
        "assigned_shopboy_id": settings_obj.assigned_shopboy_id,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_customer_scan_cart_start(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    shop_identifier = (data.get("shop_username") or data.get("shop_code") or "").strip()
    if not shop_identifier:
        return _json_error("Shop username or shop code is required.")

    owner = User.objects.filter(
        Q(username__iexact=shop_identifier) | Q(shop_code__iexact=shop_identifier),
        account_type=User.ACCOUNT_TYPE_SHOP,
        is_active=True,
    ).first()
    if not owner:
        return _json_error("Shop not found.", status=404)

    branch = None
    branch_id = data.get("branch_id")
    if branch_id:
        branch = ShopBranch.objects.filter(user=owner, id=branch_id, is_active=True).first()
        if not branch:
            return _json_error("Branch not found.", status=404)

    cart = CustomerScanCart.objects.create(
        shop_owner=owner,
        buyer=_marketplace_buyer_from_request(request),
        branch=branch,
        customer_name=(data.get("customer_name") or "").strip(),
        customer_phone=(data.get("customer_phone") or "").strip(),
    )
    return _json_success({"cart": _serialize_customer_scan_cart(request, cart)})


@csrf_exempt
@require_http_methods(["POST"])
def api_customer_scan_cart_add_by_code(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    cart_token = (data.get("cart_token") or "").strip()
    code = (data.get("code") or "").strip()
    if not cart_token or not code:
        return _json_error("Cart token and product code are required.")

    cart = CustomerScanCart.objects.select_related("shop_owner", "branch").filter(cart_token=cart_token, is_checked_out=False).first()
    if not cart:
        return _json_error("Active cart not found.", status=404)

    try:
        quantity = _parse_stock(data.get("quantity", 1))
    except Exception:
        return _json_error("Invalid quantity.")

    product = Product.objects.filter(user=cart.shop_owner, code__iexact=code).first()
    if not product:
        return _json_error(f"No product found for code {code}.", status=404)
    available_stock = _effective_product_stock(product, cart.branch)
    if available_stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = min(current_qty + quantity, available_stock)
    cart.data[product_key] = {
        "name": product.name,
        "price": float(product.selling_price),
        "cost": float(product.cost_price),
        "quantity": _format_quantity(desired_qty),
    }
    cart.save(update_fields=["data", "updated_at"])
    return _json_success({"cart": _serialize_customer_scan_cart(request, cart)})


@csrf_exempt
@require_http_methods(["POST"])
def api_customer_scan_cart_checkout(request):
    data = _get_body_data(request)
    if data is None:
        return _json_error("Invalid JSON payload.")

    cart_token = (data.get("cart_token") or "").strip()
    cart = CustomerScanCart.objects.select_related("shop_owner", "branch").filter(cart_token=cart_token, is_checked_out=False).first()
    if not cart:
        return _json_error("Active cart not found.", status=404)
    if not cart.data:
        return _json_error("Cart is empty.", status=400)

    product_ids = [int(pid) for pid in cart.data.keys() if str(pid).isdigit()]
    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(user=cart.shop_owner, id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        inventory_map = {}
        if cart.branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=cart.branch, product__in=products)
            }
            for product in products:
                product._branch_inventory = inventory_map.get(product.id)

        for pid, item in cart.data.items():
            product = product_map.get(str(pid))
            if not product:
                return _json_error("A cart item no longer exists.", status=409)
            quantity = _cart_quantity_value(item.get("quantity"))
            if quantity <= 0:
                continue
            available_stock = _effective_product_stock(product, cart.branch)
            if available_stock < quantity:
                return _json_error(f"Not enough stock for {product.name}. Available: {available_stock}.", status=409)
            price = Decimal(str(item.get("price", product.selling_price)))
            cost = Decimal(str(item.get("cost", product.cost_price)))
            total_amount += price * quantity
            total_profit += (price - cost) * quantity
            line_items.append({"product": product, "quantity": quantity, "price": price, "profit": (price - cost) * quantity})

        if not line_items:
            return _json_error("Cart is empty.", status=400)

        sale = Sale.objects.create(
            user=cart.shop_owner,
            branch=cart.branch,
            sales_channel=Sale.CHANNEL_CUSTOMER_SCAN,
            customer_name=cart.customer_name or "Scanner Customer",
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            amount_paid=Decimal("0.00"),
            payment_status=Sale.PAYMENT_LOAN,
        )
        for row in line_items:
            SaleItem.objects.create(
                sale=sale,
                product=row["product"],
                quantity=row["quantity"],
                price=row["price"].quantize(Decimal("0.01")),
                profit=row["profit"].quantize(Decimal("0.01")),
            )

        cart.pending_sale = sale
        cart.is_checked_out = True
        cart.save(update_fields=["pending_sale", "is_checked_out", "updated_at"])

    return _json_success({
        "sale": {
            "id": sale.id,
            "reference": _scanner_order_reference(sale),
            "status": "awaiting_payment_confirmation",
            "total_amount": _money(sale.total_amount),
        },
        "cart": _serialize_customer_scan_cart(request, cart),
        "bank": _shop_bank_payload(cart.shop_owner),
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_owner_scanner_sales(request):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    sales = Sale.objects.filter(
        user=owner,
        sales_channel=Sale.CHANNEL_CUSTOMER_SCAN,
        payment_status__in=[Sale.PAYMENT_LOAN, Sale.PAYMENT_PARTIAL],
    ).select_related("branch").prefetch_related("items__product").order_by("-created_at")
    return _json_success({
        "pending_sales": [_serialize_scanner_pending_sale(sale) for sale in sales],
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_owner_scanner_sale_confirm(request, sale_id):
    owner = _require_owner(request)
    if not owner:
        return _json_error("Unauthorized.", status=401)

    with transaction.atomic():
        sale = get_object_or_404(
            Sale.objects.select_for_update().prefetch_related("items__product"),
            id=sale_id,
            user=owner,
            sales_channel=Sale.CHANNEL_CUSTOMER_SCAN,
        )
        if sale.payment_status == Sale.PAYMENT_PAID:
            return _json_success({"sale": _serialize_sale(sale), "message": "Sale was already paid."})

        branch = sale.branch
        inventory_map = {}
        products = [item.product for item in sale.items.all()]
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=branch, product__in=products)
            }
        for item in sale.items.all():
            inventory = inventory_map.get(item.product_id) if branch else None
            if inventory and inventory.track_separately:
                if inventory.stock < item.quantity:
                    return _json_error(f"Not enough stock for {item.product.name}.", status=409)
                inventory.stock = max(Decimal("0.00"), inventory.stock - item.quantity)
                inventory.save(update_fields=["stock", "updated_at"])
            else:
                if item.product.stock < item.quantity:
                    return _json_error(f"Not enough stock for {item.product.name}.", status=409)
                item.product.stock -= item.quantity
                item.product.save(update_fields=["stock"])

        sale.amount_paid = sale.total_amount
        sale.payment_status = Sale.PAYMENT_PAID
        sale.save(update_fields=["amount_paid", "payment_status"])

    return _json_success({"sale": _serialize_sale(sale), "message": "Payment verified. Sale completed."})


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_dashboard(request):
    shopboy, token_obj = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    q = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("category") or "").strip()

    branch = shopboy.branch
    products = _branch_scoped_products(shopboy.user, branch)
    if category_id:
        products = products.filter(category_id=category_id)
    if q:
        products = products.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(category__name__icontains=q)
        )

    categories = _branch_scoped_categories(shopboy.user, branch).order_by("name")
    product_rows = list(products.select_related("category").order_by("name"))
    if branch:
        inventory_map = {
            item.product_id: item
            for item in BranchInventory.objects.filter(branch=branch, product__in=product_rows)
        }
        for product in product_rows:
            product._branch_inventory = inventory_map.get(product.id)
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
        "branch": _serialize_branch(branch) if branch else None,
        "products": [_serialize_owner_product(request, product, branch=branch) for product in product_rows],
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

    product = get_object_or_404(_branch_scoped_products(shopboy.user, shopboy.branch), id=product_id)
    _branch_inventory_for_product(product, shopboy.branch)
    available_stock = _effective_product_stock(product, shopboy.branch)
    if available_stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_shopboy_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > available_stock:
        desired_qty = available_stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(_effective_product_price(product, shopboy.branch)),
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
    feature_error = _json_feature_required(shopboy.user, "barcode")
    if feature_error:
        return feature_error

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

    product = _branch_scoped_products(shopboy.user, shopboy.branch).filter(code__iexact=code).first()
    if not product:
        return _json_error(f"No product found for code {code}.", status=404)
    _branch_inventory_for_product(product, shopboy.branch)
    available_stock = _effective_product_stock(product, shopboy.branch)
    if available_stock <= 0:
        return _json_error(f"{product.name} is out of stock.", status=409)

    cart = _get_shopboy_cart(token_obj)
    product_key = str(product.id)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))
    desired_qty = current_qty + quantity
    if desired_qty > available_stock:
        desired_qty = available_stock

    cart.data[product_key] = {
        "name": product.name,
        "price": float(_effective_product_price(product, shopboy.branch)),
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

    product = get_object_or_404(_branch_scoped_products(shopboy.user, shopboy.branch), id=product_id)
    _branch_inventory_for_product(product, shopboy.branch)
    available_stock = _effective_product_stock(product, shopboy.branch)
    current_qty = _cart_quantity_value(cart.data.get(product_key, {}).get("quantity"))

    if action == "increase":
        desired_qty = current_qty + Decimal("1")
        if desired_qty > available_stock:
            desired_qty = available_stock
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
        elif quantity > available_stock:
            cart.data[product_key]["quantity"] = _format_quantity(available_stock)
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
        branch = shopboy.branch
        products = _branch_scoped_products(
            shopboy.user,
            branch,
            Product.objects.select_for_update().filter(user=shopboy.user, id__in=product_ids),
        )
        product_map = {str(p.id): p for p in products}
        inventory_map = {}
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=branch, product__in=products)
            }
            for product in products:
                product._branch_inventory = inventory_map.get(product.id)

        for pid, item in cart.data.items():
            product = product_map.get(str(pid))
            if not product:
                return _json_error("A cart item no longer exists.", status=409)

            quantity = _cart_quantity_value(item.get("quantity"))
            if quantity <= 0:
                continue

            available_stock = _effective_product_stock(product, branch)
            if available_stock < quantity:
                return _json_error(f"Not enough stock for {product.name}. Available: {available_stock}.", status=409)

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
            branch=branch,
            sales_channel=Sale.CHANNEL_SHOPBOY_PORTAL,
            handled_by_shopboy=shopboy,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            amount_paid=total_amount.quantize(Decimal("0.01")),
            payment_status=Sale.PAYMENT_PAID,
        )

        for row in line_items:
            SaleItem.objects.create(
                sale=sale,
                product=row["product"],
                quantity=row["quantity"],
                price=row["price"].quantize(Decimal("0.01")),
                profit=row["profit"].quantize(Decimal("0.01")),
            )
            inventory = inventory_map.get(row["product"].id) if branch else None
            if inventory and inventory.track_separately:
                inventory.stock = max(Decimal("0.00"), inventory.stock - row["quantity"])
                inventory.save(update_fields=["stock", "updated_at"])
            else:
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
            "bank": _shop_bank_payload(owner),
        },
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_shopboy_scanner_sales(request):
    shopboy, _ = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    sales = Sale.objects.filter(
        user=shopboy.user,
        sales_channel=Sale.CHANNEL_CUSTOMER_SCAN,
        payment_status__in=[Sale.PAYMENT_LOAN, Sale.PAYMENT_PARTIAL],
    ).select_related("branch").prefetch_related("items__product").order_by("-created_at")
    if shopboy.branch_id:
        sales = sales.filter(Q(branch=shopboy.branch) | Q(branch__isnull=True))

    return _json_success({
        "pending_sales": [
            {
                **_serialize_scanner_pending_sale(sale),
            }
            for sale in sales
        ]
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_shopboy_scanner_sale_confirm(request, sale_id):
    shopboy, _ = _get_shopboy_from_request(request)
    if not shopboy:
        return _json_error("Unauthorized.", status=401)

    with transaction.atomic():
        sale = get_object_or_404(
            Sale.objects.select_for_update().prefetch_related("items__product"),
            id=sale_id,
            user=shopboy.user,
            sales_channel=Sale.CHANNEL_CUSTOMER_SCAN,
        )
        if shopboy.branch_id and sale.branch_id not in (None, shopboy.branch_id):
            return _json_error("This sale belongs to another branch.", status=403)
        if sale.payment_status == Sale.PAYMENT_PAID:
            return _json_success({"sale": _serialize_sale(sale), "message": "Sale was already paid."})

        branch = sale.branch
        inventory_map = {}
        products = [item.product for item in sale.items.all()]
        if branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=branch, product__in=products)
            }
        for item in sale.items.all():
            inventory = inventory_map.get(item.product_id) if branch else None
            if inventory and inventory.track_separately:
                if inventory.stock < item.quantity:
                    return _json_error(f"Not enough stock for {item.product.name}.", status=409)
                inventory.stock = max(Decimal("0.00"), inventory.stock - item.quantity)
                inventory.save(update_fields=["stock", "updated_at"])
            else:
                if item.product.stock < item.quantity:
                    return _json_error(f"Not enough stock for {item.product.name}.", status=409)
                item.product.stock -= item.quantity
                item.product.save(update_fields=["stock"])

        sale.handled_by_shopboy = shopboy
        sale.amount_paid = sale.total_amount
        sale.payment_status = Sale.PAYMENT_PAID
        sale.save(update_fields=["handled_by_shopboy", "amount_paid", "payment_status"])

    return _json_success({"sale": _serialize_sale(sale), "message": "Payment confirmed. Sale completed."})


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
                    amount_paid=total_amount.quantize(Decimal("0.01")),
                    payment_status=Sale.PAYMENT_PAID,
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
