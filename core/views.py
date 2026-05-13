from django.shortcuts import render,redirect
from django.urls import reverse
from django.conf import settings as django_settings
import requests
import os
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import timedelta
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from .models import (
    User,
    Sale,
    Product,
    SaleItem,
    Category,
    Expense,
    Customer,
    Investor,
    ShopBranch,
    BranchInventory,
    ShopBoy,
    MarketplaceShopProfile,
    MarketplaceSettings,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceChatMessage,
    HouseInquiry,
    HouseInquiryMessage,
    MarketplaceBuyer,
    MarketplaceBuyerToken,
    Feedback,
    HouseListing,
    HouseListingImage,
    Agent,
    RentalPayment,
    RentalRecord,
    TenantRecord,
)
from .subscription import subscription_is_active
from .utils.notifications import send_email, send_sms
import random
import string
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import json
from django.db.models import F, Sum, Q, Case, When, IntegerField
from django.db import transaction
from django.db import OperationalError, ProgrammingError
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.shortcuts import redirect, get_object_or_404
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from datetime import datetime
from django.contrib.auth.hashers import make_password
from django.contrib.auth.hashers import check_password
import re
import logging
import secrets



# Create your views here.

logger = logging.getLogger(__name__)

VAT_RATE = Decimal("0.075")
VAT_SMALL_TURNOVER_THRESHOLD = Decimal("50000000")
VAT_SMALL_FIXED_ASSETS_THRESHOLD = Decimal("250000000")
QUANTITY_STEP = Decimal("0.01")


def _normalize_decimal(value, *, max_decimal_places=2):
    qty = Decimal(str(value))
    if qty.as_tuple().exponent < -max_decimal_places:
        raise ValueError("Too many decimal places.")
    return qty.quantize(Decimal("0.01"))


def _parse_quantity(raw, default=None):
    if raw in (None, ""):
        if default is None:
            raise ValueError("Quantity is required.")
        raw = default
    qty = _normalize_decimal(raw)
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return qty


def _parse_quantity_allow_zero(raw):
    if raw in (None, ""):
        raise ValueError("Quantity is required.")
    return _normalize_decimal(raw)


def _parse_stock(raw, default=None):
    if raw in (None, ""):
        if default is None:
            raise ValueError("Stock is required.")
        raw = default
    qty = _normalize_decimal(raw)
    if qty < 0:
        raise ValueError("Stock cannot be negative.")
    return qty


def _format_quantity(qty):
    qty = _normalize_decimal(qty)
    text = format(qty.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _cart_quantity(item):
    try:
        return _normalize_decimal(item.get("quantity", "0"))
    except Exception:
        return Decimal("0.00")

def _generate_product_code(user, length=12):
    for _ in range(20):
        code = "".join(random.choice(string.digits) for _ in range(length))
        if not Product.objects.filter(user=user, code=code).exists():
            return code
    return ""

def _check_migrations():
    try:
        # Touch a new column to confirm migrations are applied
        list(Sale.objects.values_list("vat_total", flat=True)[:1])
        list(Sale.objects.values_list("amount_paid", flat=True)[:1])
        list(Sale.objects.values_list("customer_name", flat=True)[:1])
        list(User.objects.values_list("fixed_assets", flat=True)[:1])
        return ""
    except (OperationalError, ProgrammingError):
        return "Database migrations are missing. Please run: python manage.py migrate"


def _owner_branches(user):
    branches = list(ShopBranch.objects.filter(user=user, is_active=True).order_by("-is_default", "name", "id"))
    if user.is_shop_account and not branches:
        branches = [
            ShopBranch.objects.create(
                user=user,
                name=user.business_name or user.username or "Main Branch",
                address=user.address or "Main business address",
                phone=user.phone or "",
                city=user.country or "",
                state="",
                is_default=True,
            )
        ]
    return branches


def _default_branch_for_user(user):
    branches = _owner_branches(user)
    if not branches:
        return None
    return next((branch for branch in branches if branch.is_default), branches[0])


def _selected_branch_for_request(request, *, session_key="owner_selected_branch_id", query_key="branch", default_to_all=False):
    branches = _owner_branches(request.user)
    if not _plan_has_feature(request.user, "multi_branch"):
        if default_to_all:
            return branches, None, False
        default_branch = next((branch for branch in branches if branch.is_default), branches[0] if branches else None)
        if default_branch:
            request.session[session_key] = str(default_branch.id)
        return branches, default_branch, False
    branch_map = {str(branch.id): branch for branch in branches}
    branch_id = (request.GET.get(query_key) or request.POST.get(query_key) or "").strip()

    if branch_id == "all":
        request.session[session_key] = ""
        return branches, None, True

    if branch_id and branch_id in branch_map:
        previous_branch_id = str(request.session.get(session_key) or "")
        request.session[session_key] = branch_id
        return branches, branch_map[branch_id], previous_branch_id != branch_id

    if default_to_all and not branch_id:
        return branches, None, False

    stored_branch_id = str(request.session.get(session_key) or "")
    if stored_branch_id in branch_map:
        return branches, branch_map[stored_branch_id], False

    default_branch = next((branch for branch in branches if branch.is_default), None)
    if default_branch:
        request.session[session_key] = str(default_branch.id)
    return branches, default_branch, False


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


def _attach_branch_inventory(products, branch):
    if not branch:
        return list(products)
    products = list(products)
    inventory_map = {
        item.product_id: item
        for item in BranchInventory.objects.filter(branch=branch, product__in=products)
    }
    for product in products:
        product._branch_inventory = inventory_map.get(product.id)
    return products


def _sync_global_product_stock(product):
    branch_rows = BranchInventory.objects.filter(product=product, is_active=True)
    if not branch_rows.exists():
        return
    total_stock = branch_rows.aggregate(total=Sum("stock"))["total"] or Decimal("0.00")
    product.stock = total_stock.quantize(Decimal("0.01"))
    product.save(update_fields=["stock"])


def _is_vat_registered(user, turnover):
    if (user.country or "").strip().lower() != "nigeria":
        return False
    fixed_assets = user.fixed_assets
    is_professional_services = bool(user.is_professional_services)
    if fixed_assets is None:
        return True
    is_small = (
        turnover <= VAT_SMALL_TURNOVER_THRESHOLD and
        fixed_assets <= VAT_SMALL_FIXED_ASSETS_THRESHOLD and
        not is_professional_services
    )
    return not is_small


def _vat_registration_note(user, turnover):
    if (user.country or "").strip().lower() != "nigeria":
        return "VAT applies only to Nigerian businesses."
    if user.fixed_assets is None:
        return "Fixed assets not set; VAT registration assumed."
    if user.is_professional_services:
        return "Professional services do not qualify for small-business VAT exemption."
    if turnover <= VAT_SMALL_TURNOVER_THRESHOLD and user.fixed_assets <= VAT_SMALL_FIXED_ASSETS_THRESHOLD:
        return "Small business exemption applies (turnover and fixed assets within limits)."
    return ""


def _year_turnover(user, year):
    return Sale.objects.filter(user=user, created_at__year=year).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")


def _vat_registered_for_sale(user, sale_date, additional_turnover):
    year_total = _year_turnover(user, sale_date.year)
    return _is_vat_registered(user, year_total + additional_turnover)


def _calculate_item_vat(product, line_total, vat_registered):
    vat_status = getattr(product, "vat_status", "standard")
    tax_enabled = _plan_has_feature(product.user, "tax_tools") if getattr(product, "user_id", None) else True
    vat_applicable = bool(tax_enabled and vat_registered and vat_status == "standard")
    vat_rate = VAT_RATE if vat_applicable else Decimal("0.00")
    vat_amount = (line_total * vat_rate).quantize(Decimal("0.01"))
    return vat_status, vat_applicable, vat_rate, vat_amount


def _derive_payment_status(total_amount, amount_paid):
    if amount_paid >= total_amount:
        return Sale.PAYMENT_PAID
    if amount_paid > 0:
        return Sale.PAYMENT_PARTIAL
    return Sale.PAYMENT_LOAN


def _get_agent_by_code(raw_code):
    code = (raw_code or "").strip()
    if not code:
        return None
    return Agent.objects.filter(referral_code__iexact=code, is_active=True).first()


def _refresh_house_availability(house):
    active_rentals = house.rentals.filter(status=RentalRecord.STATUS_ACTIVE).count()
    if house.availability_status == HouseListing.STATUS_MAINTENANCE:
        return
    if active_rentals <= 0:
        new_status = HouseListing.STATUS_AVAILABLE
    elif house.spaces_available > 1:
        new_status = HouseListing.STATUS_PARTIAL
    else:
        new_status = HouseListing.STATUS_OCCUPIED
    if house.availability_status != new_status:
        house.availability_status = new_status
        house.save(update_fields=["availability_status", "updated_at"])


def _marketplace_house_queryset():
    return (
        HouseListing.objects.filter(
            is_active=True,
            listed_in_marketplace=True,
            is_approved=True,
        )
        .filter(
            Q(owner__is_active=True) |
            Q(owner__isnull=True, listing_agent__is_active=True)
        )
        .select_related(
            "owner",
            "owner__marketplace_profile",
            "managed_by_agent",
            "listing_agent",
        )
        .prefetch_related("images")
        .distinct()
    )


def _sync_rental_payment_state(rental):
    today = timezone.localdate()
    next_unpaid = (
        rental.payments.exclude(status=RentalPayment.STATUS_PAID)
        .order_by("due_date", "created_at")
        .first()
    )
    latest_paid = (
        rental.payments.filter(status=RentalPayment.STATUS_PAID, paid_on__isnull=False)
        .order_by("-paid_on", "-created_at")
        .first()
    )

    payment_status = rental.payment_status or RentalRecord.PAYMENT_CURRENT
    next_due_date = rental.next_due_date
    if next_unpaid:
        if next_unpaid.status == RentalPayment.STATUS_PARTIAL:
            payment_status = RentalRecord.PAYMENT_PARTIAL
        elif next_unpaid.status == RentalPayment.STATUS_OVERDUE or next_unpaid.due_date < today:
            payment_status = RentalRecord.PAYMENT_OVERDUE
        else:
            payment_status = RentalRecord.PAYMENT_DUE
        next_due_date = next_unpaid.due_date
    elif not rental.payments.exists():
        if next_due_date and next_due_date < today:
            payment_status = RentalRecord.PAYMENT_OVERDUE
        elif next_due_date:
            payment_status = RentalRecord.PAYMENT_DUE

    rental.payment_status = payment_status
    rental.next_due_date = next_due_date
    rental.last_payment_date = latest_paid.paid_on if latest_paid else rental.last_payment_date
    rental.save(update_fields=["payment_status", "next_due_date", "last_payment_date", "updated_at"])


def home(request):
    return render(request, 'home/home.html', {"plans": PLAN_CATALOG})


def healthz(request):
    return HttpResponse("ok")


def privacy_policy(request):
    return render(request, "legal/privacy-policy.html")


def account_deletion(request):
    return render(request, "legal/account-deletion.html")


def not_found(request, exception):
    return render(request, "errors/404.html", status=404)


@require_POST
def submit_feedback(request):
    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    category = (request.POST.get("category") or Feedback.CATEGORY_GENERAL).strip()
    message = (request.POST.get("message") or "").strip()

    if not name or not email or not message:
        messages.error(request, "Please fill in your name, email, and message.")
        return redirect("home")

    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Please enter a valid email address.")
        return redirect("home")

    valid_categories = {choice[0] for choice in Feedback.CATEGORY_CHOICES}
    if category not in valid_categories:
        category = Feedback.CATEGORY_GENERAL

    Feedback.objects.create(
        name=name,
        email=email,
        category=category,
        message=message,
    )
    messages.success(request, "Thank you! Your feedback has been sent.")
    return redirect("home")


# Dashborad

@login_required
def index(request):
    user = request.user
    branches, selected_branch, _ = _selected_branch_for_request(request, default_to_all=True)

    today = timezone.localdate()
    sales_qs = Sale.objects.filter(user=user)
    if selected_branch:
        sales_qs = sales_qs.filter(branch=selected_branch)

    expenses_qs = Expense.objects.filter(user=user)
    if selected_branch:
        expenses_qs = expenses_qs.filter(branch=selected_branch)

    products_qs = Product.objects.filter(user=user)
    products = _attach_branch_inventory(products_qs.order_by("-created_at"), selected_branch)
    for product in products:
        product.display_stock = _effective_product_stock(product, selected_branch)
        product.display_price = _effective_product_price(product, selected_branch)

    today_sales = sales_qs.filter(created_at__date=today).aggregate(total=Sum('total_amount'))['total'] or Decimal("0.00")
    today_profit = sales_qs.filter(created_at__date=today).aggregate(total=Sum('total_profit'))['total'] or Decimal("0.00")
    total_products = len(products) if selected_branch else products_qs.count()
    total_houses = HouseListing.objects.filter(owner=user, is_active=True).count()
    expiring_rentals = RentalRecord.objects.filter(
        house__owner=user,
        status=RentalRecord.STATUS_ACTIVE,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=60),
    ).count()

    if selected_branch:
        low_stock_count = sum(1 for product in products if product.display_stock <= product.low_stock_threshold and product.display_stock > 0)
    else:
        low_stock_count = Product.objects.filter(user=user, stock__lte=F('low_stock_threshold'), stock__gt=0).count()

    today_transactions = (
        sales_qs.filter(created_at__date=today)
        .annotate(items_count=Sum('items__quantity'))
        .order_by('-created_at')[:5]
    )

    top_products = (
        Product.objects.filter(user=user)
        .annotate(total_sold=Sum('saleitem__quantity', filter=Q(saleitem__sale__branch=selected_branch) if selected_branch else Q()))
        .order_by('-total_sold', '-created_at')[:6]
    )
    top_products = _attach_branch_inventory(top_products, selected_branch)
    for product in top_products:
        product.display_stock = _effective_product_stock(product, selected_branch)
        product.display_price = _effective_product_price(product, selected_branch)

    marketplace_orders_qs = MarketplaceOrder.objects.filter(shop_owner=user)
    if selected_branch:
        marketplace_orders_qs = marketplace_orders_qs.filter(branch=selected_branch)
    pending_orders = marketplace_orders_qs.exclude(status__in=[MarketplaceOrder.STATUS_DELIVERED, MarketplaceOrder.STATUS_CANCELLED]).count()
    recent_marketplace_orders = marketplace_orders_qs.select_related("assigned_shopboy", "branch").order_by("-created_at")[:5]

    context = {
        'today_date': today,
        'today_sales': today_sales,
        'today_profit': today_profit,
        'total_products': total_products,
        'total_houses': total_houses,
        'expiring_rentals': expiring_rentals,
        'low_stock_count': low_stock_count,
        'today_transactions': today_transactions,
        'top_products': top_products,
        'pending_orders': pending_orders,
        'recent_marketplace_orders': recent_marketplace_orders,
        'migration_warning': _check_migrations(),
        'branches': branches,
        'selected_branch': selected_branch,
        'entitlements': _feature_entitlements(request.user),
    }
    return render(request, 'home/index.html', context)


#   PRODUCT

@login_required
def product(request):
    category_id = (request.GET.get("category") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    branches, selected_branch, branch_changed = _selected_branch_for_request(request)
    cart = request.session.get('cart', {})
    cart_branch_id = str(request.session.get("owner_cart_branch_id") or "")
    selected_branch_id = str(selected_branch.id) if selected_branch else ""
    if branch_changed and cart and cart_branch_id != selected_branch_id:
        request.session['cart'] = {}
        cart = {}
        messages.info(request, "Cart was cleared so you can work with the selected branch stock.")
    request.session["owner_cart_branch_id"] = selected_branch_id

    products = Product.objects.filter(user=request.user)
    if category_id:
        products = products.filter(category_id=category_id)
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    products = _attach_branch_inventory(products.select_related("category").order_by("-created_at"), selected_branch)
    for item in products:
        item.display_stock = _effective_product_stock(item, selected_branch)
        item.display_price = _effective_product_price(item, selected_branch)

    categories = Category.objects.filter(user=request.user).order_by("name")
    last_sale = None
    last_sale_id = request.session.get('last_sale_id')
    if last_sale_id:
        last_sale = Sale.objects.filter(user=request.user, id=last_sale_id).first()
        if not last_sale:
            request.session.pop('last_sale_id', None)

    total = sum(
        (Decimal(str(item['price'])) * _cart_quantity(item) for item in cart.values()),
        Decimal("0.00"),
    )

    return render(request, 'home/product.html', {
        'products': products,
        'cart': cart,
        'cart_total': total.quantize(Decimal("0.01")),
        'categories': categories,
        'selected_category': category_id,
        'search_query': search_query,
        'last_sale': last_sale,
        'can_edit_price': _can_edit_cart_price(request.user),
        'branches': branches,
        'selected_branch': selected_branch,
    })


def _can_edit_cart_price(user):
    # Only allow price overrides for admin/owner users (not shopboy sessions).
    return user.is_authenticated


@login_required
@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, user=request.user)
    qty_raw = request.POST.get("quantity")
    selected_branch = _default_branch_for_user(request.user)
    selected_branch_id = str(request.session.get("owner_selected_branch_id") or "")
    if selected_branch_id:
        selected_branch = ShopBranch.objects.filter(user=request.user, id=selected_branch_id, is_active=True).first() or selected_branch

    cart = request.session.get('cart', {})
    product_key = str(product_id)
    available_stock = _effective_product_stock(product, selected_branch)
    price = _effective_product_price(product, selected_branch)

    if available_stock <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect('product')

    try:
        qty = _parse_quantity(qty_raw, default=Decimal("1"))
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
        return redirect('product')

    current_qty = _cart_quantity(cart.get(product_key, {}))
    desired_qty = current_qty + qty
    if desired_qty > available_stock:
        desired_qty = available_stock
        messages.warning(request, f"Only {available_stock} units available for {product.name}.")

    if product_key in cart:
        cart[product_key]['quantity'] = _format_quantity(desired_qty)
    else:
        cart[product_key] = {
            'name': product.name,
            'price': float(price),
            'cost': float(product.cost_price),
            'quantity': _format_quantity(desired_qty)
        }

    request.session['cart'] = cart
    request.session["owner_cart_branch_id"] = str(selected_branch.id) if selected_branch else ""
    return redirect('product')

@login_required
@require_POST
def add_to_cart_by_code(request):
    feature_redirect = _require_feature_or_redirect(request, "barcode", "product")
    if feature_redirect:
        return feature_redirect

    code = (request.POST.get("code") or "").strip()
    qty_raw = request.POST.get("quantity")

    if not code:
        messages.error(request, "Enter a product code.")
        return redirect('product')

    try:
        qty = _parse_quantity(qty_raw, default=Decimal("1"))
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
        return redirect('product')

    selected_branch = _default_branch_for_user(request.user)
    selected_branch_id = str(request.session.get("owner_selected_branch_id") or "")
    if selected_branch_id:
        selected_branch = ShopBranch.objects.filter(user=request.user, id=selected_branch_id, is_active=True).first() or selected_branch

    product = Product.objects.filter(user=request.user, code__iexact=code).first()
    if not product:
        messages.error(request, f"No product found for code {code}.")
        return redirect('product')

    available_stock = _effective_product_stock(product, selected_branch)
    price = _effective_product_price(product, selected_branch)
    if available_stock <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect('product')

    cart = request.session.get('cart', {})
    product_key = str(product.id)

    current_qty = _cart_quantity(cart.get(product_key, {}))
    desired_qty = current_qty + qty
    if desired_qty > available_stock:
        desired_qty = available_stock
        messages.warning(request, f"Only {available_stock} units available for {product.name}.")

    if product_key in cart:
        cart[product_key]['quantity'] = _format_quantity(desired_qty)
    else:
        cart[product_key] = {
            'name': product.name,
            'price': float(price),
            'cost': float(product.cost_price),
            'quantity': _format_quantity(desired_qty)
        }

    request.session['cart'] = cart
    request.session["owner_cart_branch_id"] = str(selected_branch.id) if selected_branch else ""
    return redirect('product')

def product_lookup_by_code(request):
    code = (request.GET.get("code") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    if not code:
        return JsonResponse({"success": False, "message": "Code is required."}, status=400)

    user = request.user if request.user.is_authenticated else None
    if not user:
        shopboy = _get_shopboy_session(request)
        if shopboy:
            user = shopboy.user
    if not user:
        return JsonResponse({"success": False, "message": "Unauthorized."}, status=403)
    if not _plan_has_feature(user, "barcode"):
        return JsonResponse({"success": False, "message": _feature_upgrade_message("barcode")}, status=403)

    product = Product.objects.filter(user=user, code__iexact=code).first()
    if not product:
        return JsonResponse({"success": False, "message": "Product not found."}, status=404)

    branch = None
    if branch_id:
        if not _plan_has_feature(user, "multi_branch"):
            return JsonResponse({"success": False, "message": _feature_upgrade_message("multi_branch")}, status=403)
        branch = ShopBranch.objects.filter(user=user, id=branch_id, is_active=True).first()
        if branch:
            product._branch_inventory = BranchInventory.objects.filter(branch=branch, product=product).first()

    return JsonResponse({
        "success": True,
        "name": product.name,
        "stock": _effective_product_stock(product, branch),
        "price": str(_effective_product_price(product, branch)),
    })

@login_required
def generate_product_code(request):
    if not _plan_has_feature(request.user, "barcode"):
        return JsonResponse({"success": False, "message": _feature_upgrade_message("barcode")}, status=403)
    code = _generate_product_code(request.user)
    if not code:
        return JsonResponse({"success": False, "message": "Unable to generate code."}, status=500)
    return JsonResponse({"success": True, "code": code})

@login_required
def product_labels(request):
    feature_redirect = _require_feature_or_redirect(request, "barcode", "inventory")
    if feature_redirect:
        return feature_redirect

    products = Product.objects.filter(user=request.user).order_by("name")
    updated = False
    for product in products:
        if not product.code:
            product.code = _generate_product_code(request.user)
            updated = True
    if updated:
        Product.objects.bulk_update(products, ["code"])

    return render(request, "home/product-labels.html", {
        "products": products,
    })

@login_required
@require_POST
def update_cart(request, product_id):
    cart = request.session.get('cart', {})
    product_id = str(product_id)
    action = request.POST.get('action') or ""
    quantity_raw = request.POST.get('quantity')
    price_raw = request.POST.get("price")
    selected_branch = _default_branch_for_user(request.user)
    selected_branch_id = str(request.session.get("owner_selected_branch_id") or "")
    if selected_branch_id:
        selected_branch = ShopBranch.objects.filter(user=request.user, id=selected_branch_id, is_active=True).first() or selected_branch

    if product_id in cart:
        product = get_object_or_404(Product, id=product_id, user=request.user)
        available_stock = _effective_product_stock(product, selected_branch)

        if action == "price":
            if not _can_edit_cart_price(request.user):
                messages.error(request, "You do not have permission to edit prices.")
            else:
                try:
                    price = Decimal(price_raw)
                except (TypeError, ValueError):
                    messages.error(request, "Please enter a valid price.")
                else:
                    if price < 0:
                        messages.error(request, "Price cannot be negative.")
                    else:
                        cart[product_id]["price"] = float(price.quantize(Decimal("0.01")))
                        messages.success(request, f"Updated price for {product.name}.")
        elif action == "increase":
            current_qty = _cart_quantity(cart[product_id])
            desired_qty = current_qty + Decimal("1")
            if desired_qty <= available_stock:
                cart[product_id]["quantity"] = _format_quantity(desired_qty)
            else:
                messages.warning(request, f"Cannot add more than available stock ({available_stock}).")
        elif action == "decrease":
            current_qty = _cart_quantity(cart[product_id])
            desired_qty = current_qty - Decimal("1")
            if desired_qty <= 0:
                del cart[product_id]
            else:
                cart[product_id]["quantity"] = _format_quantity(desired_qty)
        elif action == "set" or (action not in ("increase", "decrease") and quantity_raw not in (None, "")):
            try:
                quantity = _parse_quantity_allow_zero(quantity_raw)
            except (TypeError, ValueError):
                messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
            else:
                if quantity <= 0:
                    del cart[product_id]
                elif quantity > available_stock:
                    cart[product_id]["quantity"] = _format_quantity(available_stock)
                    messages.warning(request, f"Only {available_stock} units available for {product.name}.")
                else:
                    cart[product_id]["quantity"] = _format_quantity(quantity)

    request.session['cart'] = cart
    return redirect('product')

@login_required
@require_POST
def remove_from_cart(request, product_id):
    cart = request.session.get('cart', {})
    cart.pop(str(product_id), None)
    request.session['cart'] = cart
    return redirect('product')


@login_required
@require_POST
def checkout(request):
    cart = request.session.get('cart', {})
    if not cart:
        messages.warning(request, "Cart is empty.")
        return redirect('product')

    payment_status = (request.POST.get("payment_status") or Sale.PAYMENT_PAID).strip().lower()
    valid_statuses = {Sale.PAYMENT_PAID, Sale.PAYMENT_LOAN}
    if payment_status not in valid_statuses:
        payment_status = Sale.PAYMENT_PAID

    customer_name = (request.POST.get("customer_name") or "").strip()
    initial_payment_raw = request.POST.get("initial_payment") or "0"
    try:
        initial_payment = Decimal(initial_payment_raw)
        if initial_payment < 0:
            raise ValueError
    except Exception:
        messages.error(request, "Initial payment must be 0 or more.")
        return redirect('product')

    product_ids = [int(pid) for pid in cart.keys()]
    selected_branch = _default_branch_for_user(request.user)
    selected_branch_id = str(request.session.get("owner_cart_branch_id") or request.session.get("owner_selected_branch_id") or "")
    if selected_branch_id:
        selected_branch = ShopBranch.objects.filter(user=request.user, id=selected_branch_id, is_active=True).first() or selected_branch

    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(user=request.user, id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        inventory_map = {}
        if selected_branch:
            inventory_map = {
                item.product_id: item
                for item in BranchInventory.objects.select_for_update().filter(branch=selected_branch, product__in=products)
            }
            for product in products:
                product._branch_inventory = inventory_map.get(product.id)

        for pid, item in cart.items():
            product = product_map.get(pid)
            if not product:
                messages.error(request, "A cart item no longer exists.")
                return redirect('product')

            quantity = _cart_quantity(item)
            if quantity <= 0:
                continue

            available_stock = _effective_product_stock(product, selected_branch)
            if available_stock < quantity:
                messages.error(request, f"Not enough stock for {product.name}. Available: {available_stock}.")
                return redirect('product')

            price = Decimal(str(item['price']))
            cost = Decimal(str(item['cost']))
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
            messages.warning(request, "Cart is empty.")
            return redirect('product')

        vat_registered = _vat_registered_for_sale(request.user, timezone.now(), total_amount)
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
            user=request.user,
            branch=selected_branch,
            customer_name=customer_name,
            sales_channel=Sale.CHANNEL_OWNER_POS,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            vat_total=vat_total.quantize(Decimal("0.01")),
            amount_paid=(
                total_amount.quantize(Decimal("0.01"))
                if payment_status == Sale.PAYMENT_PAID
                else min(initial_payment, total_amount).quantize(Decimal("0.01"))
            ),
            payment_status=(
                Sale.PAYMENT_PAID
                if payment_status == Sale.PAYMENT_PAID
                else _derive_payment_status(total_amount, min(initial_payment, total_amount))
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
            branch_inventory = _branch_inventory_row(selected_branch, row["product"])
            if branch_inventory and branch_inventory.track_separately:
                branch_inventory.stock = max(Decimal("0.00"), branch_inventory.stock - row["quantity"])
                branch_inventory.save(update_fields=["stock"])
                _sync_global_product_stock(row["product"])
            else:
                row["product"].stock -= row["quantity"]
                row["product"].save(update_fields=["stock"])

    request.session['last_sale_id'] = sale.id
    request.session['cart'] = {}
    request.session['owner_cart_branch_id'] = str(selected_branch.id) if selected_branch else ""
    if payment_status == Sale.PAYMENT_LOAN:
        messages.success(request, "Sale recorded as loan.")
    else:
        messages.success(request, "Sale completed successfully.")
    return redirect('product')
    


#INVENTORY

@login_required
def inventory(request):
    search_query = (request.GET.get("q") or "").strip()
    branches, selected_branch, _ = _selected_branch_for_request(request)
    products = Product.objects.filter(user=request.user)
    categories = Category.objects.filter(user=request.user)
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    products = _attach_branch_inventory(products.select_related("category").order_by("name"), selected_branch)
    for product in products:
        product.display_stock = _effective_product_stock(product, selected_branch)
        product.display_price = _effective_product_price(product, selected_branch)
        product.branch_inventory_row = _branch_inventory_row(selected_branch, product)

    total_products = len(products)
    total_value = sum((product.display_price * product.display_stock for product in products), Decimal("0.00"))
    low_stock = sum(1 for product in products if product.display_stock <= product.low_stock_threshold and product.display_stock > 0)
    out_of_stock = sum(1 for product in products if product.display_stock <= 0)

    context = {
        'products': products,
        'categories': categories,
        'total_products': total_products,
        'total_value': total_value,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'search_query': search_query,
        'branches': branches,
        'selected_branch': selected_branch,
    }

    return render(request, 'home/inventory.html', context)

@login_required
@require_POST
def add_product(request):
    name = (request.POST.get('name') or '').strip()
    category_id = request.POST.get('category') or None
    branch_id = (request.POST.get("branch_id") or "").strip()
    code = (request.POST.get("code") or "").strip()
    vat_status = (request.POST.get("vat_status") or Product.VAT_STANDARD).strip()

    try:
        stock = _parse_stock(request.POST.get('stock', 0))
        low_stock_threshold = int(request.POST.get('low_stock_threshold', 5))
        cost_price = Decimal(request.POST.get('cost_price'))
        selling_price = Decimal(request.POST.get('selling_price'))
    except Exception:
        messages.error(request, "Invalid product values.")
        return redirect('inventory')

    if not name:
        messages.error(request, "Product name is required.")
        return redirect('inventory')

    plan = _plan_for_slug(request.user.plan)
    product_limit = _plan_limit(request.user, "product_limit")
    if product_limit is not None and Product.objects.filter(user=request.user).count() >= product_limit:
        messages.error(request, _plan_limit_message("product", plan["name"]))
        return redirect('inventory')

    if code and not _plan_has_feature(request.user, "barcode"):
        messages.error(request, _feature_upgrade_message("barcode"))
        return redirect('inventory')

    if code:
        existing_code = Product.objects.filter(user=request.user, code__iexact=code).exists()
        if existing_code:
            messages.error(request, f"A product with code {code} already exists.")
            return redirect('inventory')

    if stock < 0 or low_stock_threshold < 0:
        messages.error(request, "Stock values cannot be negative.")
        return redirect('inventory')

    if cost_price < 0 or selling_price < 0:
        messages.error(request, "Prices cannot be negative.")
        return redirect('inventory')

    if category_id:
        category_exists = Category.objects.filter(id=category_id, user=request.user).exists()
        if not category_exists:
            messages.error(request, "Selected category is invalid.")
            return redirect('inventory')

    branch = None
    if branch_id:
        feature_redirect = _require_feature_or_redirect(request, "multi_branch", "inventory")
        if feature_redirect:
            return feature_redirect
        branch = ShopBranch.objects.filter(user=request.user, id=branch_id, is_active=True).first()
        if not branch:
            messages.error(request, "Selected branch is invalid.")
            return redirect('inventory')

    valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
    if vat_status not in valid_vat_status:
        vat_status = Product.VAT_STANDARD
    if vat_status != Product.VAT_STANDARD and not _plan_has_feature(request.user, "tax_tools"):
        messages.error(request, _feature_upgrade_message("tax_tools"))
        return redirect('inventory')

    product = Product.objects.create(
        user=request.user,
        name=name,
        code=code,
        category_id=category_id,
        stock=stock,
        cost_price=cost_price,
        selling_price=selling_price,
        low_stock_threshold=low_stock_threshold,
        vat_status=vat_status,
        image=request.FILES.get('image')
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
    messages.success(request, "Product added successfully.")
    if branch:
        return redirect(f"{reverse('inventory')}?branch={branch.id}")
    return redirect('inventory')


@login_required
@require_POST
def add_category(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "Category name is required.")
        return redirect('inventory')

    if Category.objects.filter(user=request.user, name__iexact=name).exists():
        messages.warning(request, "Category already exists.")
        return redirect('inventory')

    Category.objects.create(
        user=request.user,
        name=name
    )
    messages.success(request, "Category added successfully.")
    return redirect('inventory')

@login_required
@require_POST
def adjust_stock(request, pk):
    product = get_object_or_404(Product, pk=pk, user=request.user)
    branch_id = (request.POST.get("branch") or "").strip()
    branch = None
    if branch_id:
        feature_redirect = _require_feature_or_redirect(request, "multi_branch", "inventory")
        if feature_redirect:
            return feature_redirect
        branch = ShopBranch.objects.filter(user=request.user, id=branch_id, is_active=True).first()

    adjustment = Decimal(str(request.POST.get('adjustment', 0)))
    if branch:
        inventory, _ = BranchInventory.objects.get_or_create(
            branch=branch,
            product=product,
            defaults={
                "stock": Decimal("0.00"),
                "selling_price": product.selling_price,
                "is_active": True,
                "track_separately": True,
            },
        )
        inventory.stock = max(Decimal("0.00"), inventory.stock + adjustment)
        inventory.save(update_fields=["stock"])
        _sync_global_product_stock(product)
        return redirect(f"{reverse('inventory')}?branch={branch.id}")

    product.stock = max(Decimal("0.00"), product.stock + adjustment)
    product.save(update_fields=['stock'])

    return redirect('inventory')

@login_required
@require_POST
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk, user=request.user)
    product.delete()
    messages.success(request, "Product deleted.")
    return redirect('inventory')

@login_required
@require_POST
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk, user=request.user)
    branch_id = (request.POST.get("branch_id") or "").strip()
    branch = None
    if branch_id:
        branch = ShopBranch.objects.filter(user=request.user, id=branch_id, is_active=True).first()
        if not branch:
            messages.error(request, "Selected branch is invalid.")
            return redirect('inventory')
        if not _plan_has_feature(request.user, "multi_branch"):
            active_branch_count = ShopBranch.objects.filter(user=request.user, is_active=True).count()
            if active_branch_count <= 1:
                branch = None
            else:
                feature_redirect = _require_feature_or_redirect(request, "multi_branch", "inventory")
                if feature_redirect:
                    return feature_redirect

    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "Product name is required.")
        return redirect('inventory')

    category_id = request.POST.get('category') or None
    if category_id and not Category.objects.filter(id=category_id, user=request.user).exists():
        messages.error(request, "Selected category is invalid.")
        return redirect('inventory')

    product.name = name
    product.category_id = category_id
    submitted_code = (request.POST.get("code") or "").strip()
    try:
        parsed_stock = _parse_stock(request.POST.get('stock'))
        product.cost_price = Decimal(request.POST.get('cost_price'))
        product.selling_price = Decimal(request.POST.get('selling_price'))
        product.low_stock_threshold = int(request.POST.get('low_stock_threshold') or 0)
    except Exception:
        messages.error(request, "Invalid product values.")
        return redirect('inventory')
    if parsed_stock < 0 or product.low_stock_threshold < 0:
        messages.error(request, "Stock values cannot be negative.")
        return redirect('inventory')
    if product.cost_price < 0 or product.selling_price < 0:
        messages.error(request, "Prices cannot be negative.")
        return redirect('inventory')
    vat_status = (request.POST.get("vat_status") or "").strip()
    if vat_status:
        vat_changed = vat_status != product.vat_status
        if vat_status != Product.VAT_STANDARD and vat_changed and not _plan_has_feature(request.user, "tax_tools"):
            messages.error(request, _feature_upgrade_message("tax_tools"))
            return redirect('inventory')
        valid_vat_status = {choice[0] for choice in Product.VAT_STATUS_CHOICES}
        if vat_status in valid_vat_status:
            product.vat_status = vat_status

    if request.FILES.get('image'):
        product.image = request.FILES.get('image')

    current_code = (product.code or "").strip()
    barcode_allowed = _plan_has_feature(request.user, "barcode")
    if not barcode_allowed:
        code_changed = bool(submitted_code) and submitted_code.lower() != current_code.lower()
        if code_changed:
            messages.error(request, _feature_upgrade_message("barcode"))
            return redirect('inventory')
        code = current_code
    else:
        code = submitted_code

    if code:
        existing_code = Product.objects.filter(user=request.user, code__iexact=code).exclude(id=product.id).exists()
        if existing_code:
            messages.error(request, f"A product with code {code} already exists.")
            return redirect('inventory')
    product.code = code
    save_fields = [
        "name",
        "category",
        "cost_price",
        "selling_price",
        "low_stock_threshold",
        "vat_status",
        "code",
    ]
    if request.FILES.get('image'):
        save_fields.append("image")
    if branch:
        inventory, _ = BranchInventory.objects.get_or_create(
            branch=branch,
            product=product,
            defaults={
                "stock": parsed_stock,
                "selling_price": product.selling_price,
                "is_active": True,
                "track_separately": True,
            },
        )
        inventory.stock = parsed_stock
        inventory.selling_price = product.selling_price
        inventory.is_active = True
        inventory.track_separately = True
        inventory.save(update_fields=["stock", "selling_price", "is_active", "track_separately"])
    else:
        product.stock = parsed_stock
        save_fields.append("stock")

    product.save(update_fields=save_fields)
    if branch:
        _sync_global_product_stock(product)
    messages.success(request, "Product updated.")

    if branch:
        return redirect(f"{reverse('inventory')}?branch={branch.id}")
    return redirect('inventory')





#SALES HISTORY

@login_required
def sales_history(request):
    branches, selected_branch, _ = _selected_branch_for_request(request, default_to_all=True)
    start_date = parse_date((request.GET.get("start_date") or "").strip()) if request.GET.get("start_date") else None
    end_date = parse_date((request.GET.get("end_date") or "").strip()) if request.GET.get("end_date") else None
    search_query = (request.GET.get("q") or "").strip()
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    sales = (
        Sale.objects.filter(user=request.user)
        .select_related("handled_by_shopboy", "customer")
        .prefetch_related('items__product')
        .order_by('-created_at')
    )
    if selected_branch:
        sales = sales.filter(branch=selected_branch)
    if start_date:
        sales = sales.filter(created_at__date__gte=start_date)
    if end_date:
        sales = sales.filter(created_at__date__lte=end_date)
    if search_query:
        search_filters = (
            Q(items__product__name__icontains=search_query) |
            Q(handled_by_shopboy__full_name__icontains=search_query) |
            Q(handled_by_shopboy__username__icontains=search_query) |
            Q(customer__first_name__icontains=search_query) |
            Q(customer__last_name__icontains=search_query) |
            Q(sales_channel__icontains=search_query)
        )

        if search_query.isdigit():
            search_filters = search_filters | Q(id=int(search_query))

        search_date = parse_date(search_query)
        if search_date:
            search_filters = search_filters | Q(created_at__date=search_date)

        sales = sales.filter(search_filters).distinct()

    total_sales = sales.aggregate(total=Sum('total_amount'))['total'] or Decimal("0.00")
    total_profit = sales.aggregate(total=Sum('total_profit'))['total'] or Decimal("0.00")
    total_transactions = sales.count()

    years = {sale.created_at.year for sale in sales}
    vat_registered_by_year = {
        year: _is_vat_registered(request.user, _year_turnover(request.user, year))
        for year in years
    }
    for sale in sales:
        vat_registered = vat_registered_by_year.get(sale.created_at.year, False)
        for item in sale.items.all():
            line_total = (item.price or Decimal("0.00")) * item.quantity
            use_existing = (item.vat_rate != Decimal("0.00") or item.vat_amount != Decimal("0.00") or item.vat_applicable)
            if use_existing:
                item.vat_display = f"₦{item.vat_amount:.2f}" if item.vat_applicable else "Not eligible"
                continue
            vat_status = getattr(item.product, "vat_status", "standard")
            vat_applicable = bool(vat_registered and vat_status == Product.VAT_STANDARD)
            if vat_applicable:
                item.vat_display = f"₦{(line_total * VAT_RATE).quantize(Decimal('0.01')):.2f}"
            else:
                item.vat_display = "Not eligible"

    context = {
        'sales': sales,
        'total_sales': total_sales,
        'total_profit': total_profit,
        'total_transactions': total_transactions,
        'start_date': start_date,
        'end_date': end_date,
        'search_query': search_query,
        'branches': branches,
        'selected_branch': selected_branch,
    }

    return render(request, 'home/sales-history.html', context)


@login_required
def loans(request):
    branches, selected_branch, _ = _selected_branch_for_request(request, default_to_all=True)
    loans_qs = (
        Sale.objects.filter(user=request.user)
        .select_related("customer", "handled_by_shopboy")
        .order_by("-created_at")
    ).filter(payment_status__in=[Sale.PAYMENT_LOAN, Sale.PAYMENT_PARTIAL])
    if selected_branch:
        loans_qs = loans_qs.filter(branch=selected_branch)

    return render(request, "home/loans.html", {
        "loans": loans_qs,
        "branches": branches,
        "selected_branch": selected_branch,
    })


@login_required
@require_POST
def update_loan_payment(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id, user=request.user)
    if sale.remaining_balance <= 0:
        messages.info(request, "This loan is already fully paid.")
        return redirect("loans")

    payment_raw = request.POST.get("payment_amount")
    try:
        payment_amount = Decimal(payment_raw)
        if payment_amount <= 0:
            raise ValueError
    except Exception:
        messages.error(request, "Enter a valid payment amount greater than 0.")
        return redirect("loans")

    new_amount_paid = (sale.amount_paid or Decimal("0.00")) + payment_amount
    if new_amount_paid > sale.total_amount:
        new_amount_paid = sale.total_amount

    sale.amount_paid = new_amount_paid.quantize(Decimal("0.01"))
    sale.payment_status = _derive_payment_status(sale.total_amount, sale.amount_paid)
    sale.save(update_fields=["amount_paid", "payment_status"])

    if sale.payment_status == Sale.PAYMENT_PAID:
        messages.success(request, "Loan fully paid and marked as Paid.")
    else:
        messages.success(request, "Partial payment recorded.")
    return redirect("loans")


@login_required
def sale_receipt(request, sale_id):
    sale = get_object_or_404(
        Sale.objects.filter(user=request.user)
        .select_related("customer", "handled_by_shopboy")
        .prefetch_related("items__product"),
        id=sale_id,
    )

    line_items = []
    for item in sale.items.all():
        line_total = (item.price or Decimal("0.00")) * item.quantity
        line_items.append({
            "name": item.product.name,
            "quantity": item.quantity,
            "price": item.price,
            "total": line_total,
        })

    return render(request, "home/sale-receipt.html", {
        "sale": sale,
        "line_items": line_items,
        "business": request.user,
    })


def shopboy_sale_receipt(request, sale_id):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    sale = get_object_or_404(
        Sale.objects.filter(user=shopboy.user, handled_by_shopboy=shopboy)
        .select_related("customer", "handled_by_shopboy"),
        id=sale_id,
    )

    line_items = []
    for item in sale.items.select_related("product").all():
        line_total = (item.price or Decimal("0.00")) * item.quantity
        line_items.append({
            "name": item.product.name,
            "quantity": item.quantity,
            "price": item.price,
            "total": line_total,
        })

    return render(request, "home/sale-receipt.html", {
        "sale": sale,
        "line_items": line_items,
        "business": shopboy.user,
    })




@login_required
def expenses(request):
    branches, selected_branch, _ = _selected_branch_for_request(request, default_to_all=True)
    if request.method == "POST":
        category = request.POST.get("category", "").strip()
        title = request.POST.get("title", "").strip()
        amount = request.POST.get("amount")
        expense_date = request.POST.get("date")
        branch_id = (request.POST.get("branch_id") or "").strip()

        valid_categories = {choice[0] for choice in Expense.CATEGORY_CHOICES}
        if category not in valid_categories:
            messages.error(request, "Please select a valid expense category.")
            return redirect("expenses")

        if not title:
            messages.error(request, "Expense title is required.")
            return redirect("expenses")

        try:
            amount_value = Decimal(amount)
            if amount_value <= 0:
                raise ValueError
        except Exception:
            messages.error(request, "Amount must be greater than 0.")
            return redirect("expenses")

        if not expense_date:
            messages.error(request, "Expense date is required.")
            return redirect("expenses")

        expense_branch = None
        if branch_id:
            expense_branch = ShopBranch.objects.filter(user=request.user, id=branch_id, is_active=True).first()
            if not expense_branch:
                messages.error(request, "Selected branch is invalid.")
                return redirect("expenses")
        elif selected_branch:
            expense_branch = selected_branch

        Expense.objects.create(
            user=request.user,
            branch=expense_branch,
            category=category,
            title=title,
            amount=amount_value,
            date=expense_date,
        )
        messages.success(request, "Expense added successfully.")
        if expense_branch:
            return redirect(f"{reverse('expenses')}?branch={expense_branch.id}")
        return redirect("expenses")

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    expenses_qs = Expense.objects.filter(user=request.user)
    if selected_branch:
        expenses_qs = expenses_qs.filter(branch=selected_branch)
    expenses_qs = expenses_qs.order_by("-date", "-created_at")

    today_expenses = expenses_qs.filter(date=today).aggregate(total=Sum("amount"))["total"] or 0
    week_expenses = expenses_qs.filter(date__gte=week_start, date__lte=today).aggregate(total=Sum("amount"))["total"] or 0
    month_expenses = expenses_qs.filter(date__gte=month_start, date__lte=today).aggregate(total=Sum("amount"))["total"] or 0

    context = {
        "expenses": expenses_qs,
        "today_expenses": today_expenses,
        "week_expenses": week_expenses,
        "month_expenses": month_expenses,
        "total_records": expenses_qs.count(),
        "branches": branches,
        "selected_branch": selected_branch,
    }
    return render(request, "home/expenses.html", context)





@login_required
def reports(request):

    now = timezone.now()
    has_tax_tools = _plan_has_feature(request.user, "tax_tools")
    period = request.GET.get("period", "month")
    branches, selected_branch, _ = _selected_branch_for_request(request, default_to_all=True)
    start_date = parse_date((request.GET.get("start_date") or "").strip()) if request.GET.get("start_date") else None
    end_date = parse_date((request.GET.get("end_date") or "").strip()) if request.GET.get("end_date") else None
    custom_range = bool(start_date or end_date)
    if period == "custom" and not custom_range:
        period = "month"
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    # =========================
    # PERIOD FILTER
    # =========================

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
        else:  # month
            start = now.replace(day=1)

    sales = Sale.objects.filter(user=request.user)
    expenses = Expense.objects.filter(user=request.user)
    if selected_branch:
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

    total_revenue = sales.aggregate(
        total=Sum("total_amount")
    )["total"] or 0

    total_profit = sales.aggregate(
        total=Sum("total_profit")
    )["total"] or 0

    total_expenses = expenses.aggregate(
        total=Sum("amount")
    )["total"] or 0

    net_profit = total_profit - total_expenses
    total_transactions = sales.count()
    avg_transaction = (total_revenue / total_transactions) if total_transactions else 0
    avg_profit_per_sale = (total_profit / total_transactions) if total_transactions else 0

    items_sold = SaleItem.objects.filter(
        sale__in=sales
    ).aggregate(total=Sum("quantity"))["total"] or 0

    # =========================
    # ===== CIT CALCULATION ===
    # =========================

    try:
        cit_year = int(request.GET.get("cit_year", now.year))
    except (TypeError, ValueError):
        cit_year = now.year

    year_sales = Sale.objects.filter(
        created_at__year=cit_year,
        user=request.user
    )

    year_expenses = Expense.objects.filter(
        created_at__year=cit_year,
        user=request.user
    )
    if selected_branch:
        year_sales = year_sales.filter(branch=selected_branch)
        year_expenses = year_expenses.filter(branch=selected_branch)

    cit_revenue = year_sales.aggregate(
        total=Sum("total_amount")
    )["total"] or 0

    cit_profit = year_sales.aggregate(
        total=Sum("total_profit")
    )["total"] or 0

    cit_cost = cit_revenue - cit_profit
    cit_gross_profit = cit_profit

    cit_operating_expenses = year_expenses.aggregate(
        total=Sum("amount")
    )["total"] or 0

    cit_assessable_profit = cit_gross_profit - cit_operating_expenses
    cit_taxable_profit = max(0, cit_assessable_profit)
    # Nigeria Tax Act 2025 (effective 2026): small company rate 0%, others 30%.
    # Small company requires: turnover <= NGN 50m, fixed assets <= NGN 250m, and not a professional services company.
    cit_small_turnover_threshold = Decimal("50000000")
    cit_small_fixed_assets_threshold = Decimal("250000000")
    cit_rate = Decimal("0.30")
    cit_rate_label = "Standard rate (30%)"
    cit_rate_note = ""
    fixed_assets_value = request.user.fixed_assets
    is_professional_services = bool(request.user.is_professional_services)
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

    # =========================
    # ===== VAT CALCULATION ===
    # =========================

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

    if vat_month == 12:
        month_end = datetime(vat_year + 1, 1, 1)
    else:
        month_end = datetime(vat_year, vat_month + 1, 1)

    vat_sales = Sale.objects.filter(
        created_at__range=(month_start, month_end),
        user=request.user
    )
    if selected_branch:
        vat_sales = vat_sales.filter(branch=selected_branch)

    vat_year_turnover = _year_turnover(request.user, vat_year)
    vat_registered = _is_vat_registered(request.user, vat_year_turnover)
    vat_registration_note = _vat_registration_note(request.user, vat_year_turnover)

    vat_taxable_sales = Decimal("0.00")
    vat_output_vat = Decimal("0.00")
    if vat_registered:
        vat_items = (
            SaleItem.objects.filter(sale__in=vat_sales)
            .select_related("product")
        )
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

    # =========================
    # CONTEXT
    # =========================

    context = {
        # Main report
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "total_transactions": total_transactions,
        "items_sold": items_sold,
        "avg_transaction": avg_transaction,
        "avg_profit_per_sale": avg_profit_per_sale,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,

        # CIT
        "cit_year": cit_year,
        "cit_revenue": cit_revenue,
        "cit_cost": cit_cost,
        "cit_gross_profit": cit_gross_profit,
        "cit_operating_expenses": cit_operating_expenses,
        "cit_assessable_profit": cit_assessable_profit,
        "cit_taxable_profit": cit_taxable_profit,
        "cit_tax_due": cit_tax_due,
        "cit_rate": cit_rate,
        "cit_rate_percent": cit_rate_percent,
        "cit_rate_label": cit_rate_label,
        "cit_rate_note": cit_rate_note,
        "cit_small_turnover_threshold": cit_small_turnover_threshold,
        "cit_small_fixed_assets_threshold": cit_small_fixed_assets_threshold,

        # VAT
        "vat_year": vat_year,
        "vat_month": vat_month,
        "vat_taxable_sales": vat_taxable_sales,
        "vat_output_vat": vat_output_vat,
        "vat_registered": vat_registered,
        "vat_registration_note": vat_registration_note,
        "is_nigeria": (request.user.country or "").strip().lower() == "nigeria",
        "has_tax_tools": has_tax_tools,
        "tax_upgrade_message": _feature_upgrade_message("tax_tools"),
        "entitlements": _feature_entitlements(request.user),
        "branches": branches,
        "selected_branch": selected_branch,
    }

    return render(request, "home/reports.html", context)








@login_required
def customer(request):
    q = (request.GET.get("q") or "").strip()
    customers = Customer.objects.filter(user=request.user)

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
    return render(request, 'home/customer.html', {
        "customers": customers,
        "q": q,
        "entitlements": _feature_entitlements(request.user),
    })


@login_required
@require_POST
def add_customer(request):
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    email = (request.POST.get("email") or "").strip() or None
    birthday = (request.POST.get("birthday") or "").strip() or None
    religion = (request.POST.get("religion") or "").strip()
    tribe = (request.POST.get("tribe") or "").strip()
    notes = (request.POST.get("notes") or "").strip()

    if not first_name or not last_name or not phone:
        messages.error(request, "First name, last name and phone are required.")
        return redirect("customer")

    has_full_customer_management = _plan_has_feature(request.user, "full_customer_management")
    advanced_values = [email, birthday, religion, tribe, notes]
    if any(advanced_values) and not has_full_customer_management:
        messages.error(request, _feature_upgrade_message("full_customer_management"))
        return redirect("customer")

    valid_religions = {choice[0] for choice in Customer.RELIGION_CHOICES}
    if religion not in valid_religions:
        religion = ""

    Customer.objects.create(
        user=request.user,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        birthday=birthday,
        religion=religion,
        tribe=tribe,
        notes=notes,
    )
    messages.success(request, "Customer added.")
    return redirect("customer")


@login_required
@require_POST
def edit_customer(request, pk):
    customer_obj = get_object_or_404(Customer, pk=pk, user=request.user)

    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    email = (request.POST.get("email") or "").strip() or None
    birthday = (request.POST.get("birthday") or "").strip() or None
    religion = (request.POST.get("religion") or "").strip()
    tribe = (request.POST.get("tribe") or "").strip()
    notes = (request.POST.get("notes") or "").strip()

    if not first_name or not last_name or not phone:
        messages.error(request, "First name, last name and phone are required.")
        return redirect("customer")

    has_full_customer_management = _plan_has_feature(request.user, "full_customer_management")
    advanced_values = [email, birthday, religion, tribe, notes]
    if any(advanced_values) and not has_full_customer_management:
        messages.error(request, _feature_upgrade_message("full_customer_management"))
        return redirect("customer")

    valid_religions = {choice[0] for choice in Customer.RELIGION_CHOICES}
    if religion not in valid_religions:
        religion = ""

    customer_obj.first_name = first_name
    customer_obj.last_name = last_name
    customer_obj.phone = phone
    customer_obj.email = email
    customer_obj.birthday = birthday
    customer_obj.religion = religion
    customer_obj.tribe = tribe
    customer_obj.notes = notes
    customer_obj.save()

    messages.success(request, "Customer updated.")
    return redirect("customer")


@login_required
@require_POST
def delete_customer(request, pk):
    customer_obj = get_object_or_404(Customer, pk=pk, user=request.user)
    customer_obj.delete()
    messages.success(request, "Customer deleted.")
    return redirect("customer")

@login_required
def settings(request):
    branches = list(ShopBranch.objects.filter(user=request.user).order_by("name", "id"))
    if request.user.is_shop_account and not branches:
        branches = [
            ShopBranch.objects.create(
                user=request.user,
                name=(request.user.business_name or request.user.username or "Main Shop").strip(),
                phone=request.user.phone or "",
                address=request.user.address or "Main address",
                city="",
                state=request.user.state or "",
                is_default=True,
            )
        ]
    shopboys = ShopBoy.objects.filter(user=request.user).select_related("branch").order_by("-id")
    marketplace_settings = _get_marketplace_settings(request.user)
    marketplace_profile, _ = MarketplaceShopProfile.objects.get_or_create(user=request.user)
    _ensure_shop_code(request.user)
    staff_limit = _plan_limit(request.user, "staff_limit")
    branch_summaries = []
    total_branch_revenue = Decimal("0.00")
    for branch in branches:
        sales_count = Sale.objects.filter(user=request.user, branch=branch).count()
        branch_revenue = Sale.objects.filter(user=request.user, branch=branch).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
        branch_summaries.append({
            "branch": branch,
            "sales_count": sales_count,
            "revenue": branch_revenue,
            "active_staff": ShopBoy.objects.filter(user=request.user, branch=branch, is_active=True).count(),
        })
        total_branch_revenue += branch_revenue
    best_branch = max(branch_summaries, key=lambda item: item["revenue"], default=None)
    return render(request, 'home/settings.html', {
        "shopboys": shopboys,
        "branches": branches,
        "branch_summaries": branch_summaries,
        "branch_count": len(branches),
        "total_branch_revenue": total_branch_revenue,
        "best_branch": best_branch,
        "marketplace_settings": marketplace_settings,
        "marketplace_profile": marketplace_profile,
        "active_shopboy_count": shopboys.filter(is_active=True).count(),
        "marketplace_ready_shopboy_count": shopboys.filter(is_active=True, can_use_marketplace=True).count(),
        "entitlements": _feature_entitlements(request.user),
        "current_plan": _plan_for_slug(request.user.plan),
        "staff_limit": staff_limit,
        "can_add_shopboy": staff_limit is None or shopboys.count() < staff_limit,
    })


@login_required
@require_POST
def update_profile(request):
    user = request.user
    user.business_name = (request.POST.get("business_name") or "").strip()
    user.country = (request.POST.get("country") or "").strip()
    user.address = (request.POST.get("address") or "").strip()
    user.phone = (request.POST.get("phone") or "").strip()
    user.bank_name = (request.POST.get("bank_name") or "").strip()
    user.bank_account_number = (request.POST.get("bank_account_number") or "").strip()
    user.bank_account_name = (request.POST.get("bank_account_name") or "").strip()
    profile_image = request.FILES.get("profile_image")
    if profile_image:
        user.profile_image = profile_image
    fixed_assets_raw = (request.POST.get("fixed_assets") or "").strip()
    tax_fields_posted = "fixed_assets" in request.POST or "is_professional_services" in request.POST
    save_fields = ["business_name", "country", "address", "phone", "profile_image", "bank_name", "bank_account_number", "bank_account_name"]
    if tax_fields_posted:
        if not _plan_has_feature(user, "tax_tools"):
            messages.error(request, _feature_upgrade_message("tax_tools"))
            return redirect("settings")

        if fixed_assets_raw:
            try:
                fixed_assets_value = Decimal(fixed_assets_raw)
                if fixed_assets_value < 0:
                    raise ValueError
                user.fixed_assets = fixed_assets_value
            except Exception:
                messages.error(request, "Fixed assets must be a valid non-negative amount.")
                return redirect("settings")
        else:
            user.fixed_assets = None

        user.is_professional_services = request.POST.get("is_professional_services") == "on"
        save_fields.extend(["fixed_assets", "is_professional_services"])

    user.save(update_fields=save_fields)
    marketplace_profile, _ = MarketplaceShopProfile.objects.get_or_create(user=user)
    marketplace_logo = request.FILES.get("marketplace_logo")
    if marketplace_logo:
        marketplace_profile.logo = marketplace_logo
    marketplace_cover_image = request.FILES.get("marketplace_cover_image")
    if marketplace_cover_image:
        marketplace_profile.cover_image = marketplace_cover_image
    if marketplace_logo or marketplace_cover_image:
        marketplace_profile.save(update_fields=["logo", "cover_image"])
    messages.success(request, "Profile updated.")
    return redirect("settings")


@login_required
@require_POST
def add_shopboy(request):
    full_name = (request.POST.get("full_name") or "").strip()
    username = (request.POST.get("username") or "").strip()
    password = (request.POST.get("password") or "").strip()
    role = (request.POST.get("role") or ShopBoy.ROLE_STAFF).strip().lower()
    branch_id = (request.POST.get("branch_id") or "").strip()
    can_use_marketplace = request.POST.get("can_use_marketplace") == "on"

    if not full_name or not username or not password:
        messages.error(request, "Full name, username, and password are required.")
        return redirect("settings")

    plan = _plan_for_slug(request.user.plan)
    staff_limit = _plan_limit(request.user, "staff_limit")
    if staff_limit is not None and ShopBoy.objects.filter(user=request.user).count() >= staff_limit:
        messages.error(request, _plan_limit_message("staff", plan["name"]))
        return redirect("settings")

    if ShopBoy.objects.filter(user=request.user, username__iexact=username).exists():
        messages.error(request, "Shop boy username already exists.")
        return redirect("settings")

    valid_roles = {choice[0] for choice in ShopBoy.ROLE_CHOICES}
    if role not in valid_roles:
        role = ShopBoy.ROLE_STAFF
    branch = None
    if branch_id:
        feature_redirect = _require_feature_or_redirect(request, "multi_branch", "settings")
        if feature_redirect:
            return feature_redirect
        branch = ShopBranch.objects.filter(user=request.user, id=branch_id, is_active=True).first()
        if not branch:
            messages.error(request, "Selected branch is not available.")
            return redirect("settings")

    ShopBoy.objects.create(
        user=request.user,
        branch=branch,
        full_name=full_name,
        username=username,
        password=make_password(password),
        role=role,
        can_use_marketplace=can_use_marketplace,
        is_active=True,
    )
    messages.success(request, "Shop boy added.")
    return redirect("settings")


@login_required
@require_POST
def add_branch(request):
    name = (request.POST.get("name") or "").strip()
    address = (request.POST.get("address") or "").strip()
    if not name or not address:
        messages.error(request, "Branch name and address are required.")
        return redirect("settings")

    plan = _plan_for_slug(request.user.plan)
    branch_limit = _plan_limit(request.user, "branch_limit")
    if not _plan_has_feature(request.user, "multi_branch") and ShopBranch.objects.filter(user=request.user, is_active=True).count() >= 1:
        messages.error(request, _feature_upgrade_message("multi_branch"))
        return redirect("settings")
    if branch_limit is not None and ShopBranch.objects.filter(user=request.user, is_active=True).count() >= branch_limit:
        messages.error(request, _plan_limit_message("branch", plan["name"]))
        return redirect("settings")

    ShopBranch.objects.create(
        user=request.user,
        name=name,
        phone=(request.POST.get("phone") or "").strip(),
        address=address,
        city=(request.POST.get("city") or "").strip(),
        state=(request.POST.get("state") or request.user.state or "").strip(),
        is_default=request.POST.get("is_default") == "on",
        is_active=True,
    )
    messages.success(request, "Branch added.")
    return redirect("settings")


@login_required
@require_POST
def set_default_branch(request, pk):
    feature_redirect = _require_feature_or_redirect(request, "multi_branch", "settings")
    if feature_redirect:
        return feature_redirect
    branch = get_object_or_404(ShopBranch, pk=pk, user=request.user)
    branch.is_default = True
    branch.save()
    messages.success(request, f"{branch.name} is now your default branch.")
    return redirect("settings")


@login_required
@require_POST
def delete_branch(request, pk):
    feature_redirect = _require_feature_or_redirect(request, "multi_branch", "settings")
    if feature_redirect:
        return feature_redirect
    branch = get_object_or_404(ShopBranch, pk=pk, user=request.user)
    remaining = ShopBranch.objects.filter(user=request.user).exclude(pk=pk).order_by("-is_default", "id")
    fallback = remaining.first()
    if not fallback:
        messages.error(request, "At least one branch must remain.")
        return redirect("settings")
    ShopBoy.objects.filter(user=request.user, branch=branch).update(branch=fallback)
    Sale.objects.filter(user=request.user, branch=branch).update(branch=fallback)
    Expense.objects.filter(user=request.user, branch=branch).update(branch=fallback)
    MarketplaceOrder.objects.filter(shop_owner=request.user, branch=branch).update(branch=fallback)
    branch.delete()
    if not ShopBranch.objects.filter(user=request.user, is_default=True).exists():
        fallback.is_default = True
        fallback.save(update_fields=["is_default"])
    messages.success(request, "Branch deleted.")
    return redirect("settings")


@login_required
@require_POST
def toggle_shopboy(request, pk):
    shopboy = get_object_or_404(ShopBoy, pk=pk, user=request.user)
    if not shopboy.is_active:
        plan = _plan_for_slug(request.user.plan)
        staff_limit = _plan_limit(request.user, "staff_limit")
        active_count = ShopBoy.objects.filter(user=request.user, is_active=True).exclude(pk=pk).count()
        if staff_limit is not None and active_count >= staff_limit:
            messages.error(request, _plan_limit_message("active staff", plan["name"]))
            return redirect("settings")
    shopboy.is_active = not shopboy.is_active
    shopboy.save(update_fields=["is_active"])
    messages.success(request, "Shop boy status updated.")
    return redirect("settings")


@login_required
@require_POST
def delete_shopboy(request, pk):
    shopboy = get_object_or_404(ShopBoy, pk=pk, user=request.user)
    shopboy.delete()
    messages.success(request, "Shop boy deleted.")
    return redirect("settings")


@login_required
def housing_management(request):
    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()
    active_section = (request.GET.get("section") or "overview").strip()
    valid_sections = {
        "overview",
        "add-listing",
        "inquiries",
        "rentals",
        "payments",
        "listings",
        "reminders",
    }
    if active_section not in valid_sections:
        active_section = "overview"

    houses = (
        HouseListing.objects.filter(owner=request.user)
        .prefetch_related("images", "inquiries")
        .select_related("managed_by_agent")
        .order_by("-created_at")
    )
    if q:
        houses = houses.filter(
            Q(title__icontains=q) |
            Q(location__icontains=q) |
            Q(description__icontains=q)
        )
    if status_filter:
        houses = houses.filter(availability_status=status_filter)

    tenants = TenantRecord.objects.filter(user=request.user).order_by("full_name")
    rentals = (
        RentalRecord.objects.filter(house__owner=request.user)
        .select_related("house", "tenant")
        .order_by("end_date", "-created_at")
    )
    payments = (
        RentalPayment.objects.filter(rental__house__owner=request.user)
        .select_related("rental", "rental__house")
        .order_by("-due_date", "-created_at")
    )
    today = timezone.localdate()
    upcoming_reminders = rentals.filter(
        status=RentalRecord.STATUS_ACTIVE,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=60),
    )
    due_payments = payments.filter(
        Q(status__in=[RentalPayment.STATUS_PENDING, RentalPayment.STATUS_PARTIAL, RentalPayment.STATUS_OVERDUE]) |
        Q(due_date__lt=today)
    )
    inquiries = (
        HouseInquiry.objects.filter(owner=request.user)
        .select_related("house", "buyer")
        .prefetch_related("messages")
        .order_by("-updated_at", "-created_at")
    )

    return render(request, "home/housing.html", {
        "active_section": active_section,
        "houses": houses,
        "inquiries": inquiries[:12],
        "tenants": tenants,
        "rentals": rentals[:12],
        "payments": payments[:12],
        "upcoming_reminders": upcoming_reminders[:8],
        "due_payments": due_payments[:8],
        "agents": Agent.objects.filter(is_active=True).order_by("full_name"),
        "house_status_choices": HouseListing.AVAILABILITY_STATUS_CHOICES,
        "property_type_choices": HouseListing.PROPERTY_TYPE_CHOICES,
        "listing_mode_choices": HouseListing.LISTING_MODE_CHOICES,
        "rental_status_choices": RentalRecord.STATUS_CHOICES,
        "rental_payment_choices": RentalRecord.PAYMENT_STATUS_CHOICES,
        "payment_entry_choices": RentalPayment.STATUS_CHOICES,
        "filters": {"q": q, "status": status_filter},
        "stats": {
            "houses": HouseListing.objects.filter(owner=request.user, is_active=True).count(),
            "available_houses": HouseListing.objects.filter(owner=request.user, availability_status=HouseListing.STATUS_AVAILABLE, is_active=True).count(),
            "occupied_houses": HouseListing.objects.filter(owner=request.user, availability_status=HouseListing.STATUS_OCCUPIED, is_active=True).count(),
            "expiring_rentals": upcoming_reminders.count(),
            "marketplace_inquiries": inquiries.filter(status=HouseInquiry.STATUS_OPEN).count(),
        },
    })


@login_required
@require_POST
def add_house_listing(request):
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
        messages.error(request, "House title and location are required.")
        return redirect("housing_management")

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
        messages.error(request, "Price, rooms, and spaces must be valid positive values.")
        return redirect("housing_management")

    house = HouseListing.objects.create(
        owner=request.user,
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
        listed_in_marketplace=request.POST.get("listed_in_marketplace") == "on",
    )

    for index, image in enumerate(request.FILES.getlist("images")):
        HouseListingImage.objects.create(
            house=house,
            image=image,
            is_primary=index == 0,
        )

    messages.success(request, "House listing added.")
    return redirect("housing_management")


@login_required
@require_POST
def update_house_listing(request, house_id):
    house = get_object_or_404(HouseListing, id=house_id, owner=request.user)
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
    house.listed_in_marketplace = request.POST.get("listed_in_marketplace") == "on"
    house.is_active = request.POST.get("is_active") == "on"
    house.save(update_fields=["availability_status", "listing_mode", "listed_in_marketplace", "is_active", "updated_at"])
    messages.success(request, f"{house.title} updated.")
    return redirect("housing_management")


@login_required
@require_POST
def add_rental_record(request):
    house = get_object_or_404(HouseListing, id=request.POST.get("house_id"), owner=request.user)
    tenant = None
    tenant_id = (request.POST.get("tenant_id") or "").strip()
    if tenant_id:
        tenant = TenantRecord.objects.filter(id=tenant_id, user=request.user).first()

    tenant_name = (request.POST.get("tenant_name") or (tenant.full_name if tenant else "")).strip()
    tenant_phone = (request.POST.get("tenant_phone") or (tenant.phone if tenant else "")).strip()
    tenant_email = (request.POST.get("tenant_email") or (tenant.email if tenant else "")).strip()
    notes = (request.POST.get("notes") or "").strip()

    if not tenant_name:
        messages.error(request, "Tenant name is required.")
        return redirect("housing_management")

    start_date = parse_date((request.POST.get("start_date") or "").strip())
    end_date = parse_date((request.POST.get("end_date") or "").strip())
    next_due_date = parse_date((request.POST.get("next_due_date") or "").strip()) if request.POST.get("next_due_date") else None
    if not start_date or not end_date or end_date <= start_date:
        messages.error(request, "Please provide a valid rental start and end date.")
        return redirect("housing_management")

    try:
        monthly_rent = Decimal(request.POST.get("monthly_rent") or house.price)
        if monthly_rent <= 0:
            raise ValueError
    except Exception:
        messages.error(request, "Monthly rent must be a valid positive amount.")
        return redirect("housing_management")

    if tenant is None:
        tenant = TenantRecord.objects.create(
            user=request.user,
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
        payment_status=(request.POST.get("payment_status") or RentalRecord.PAYMENT_CURRENT).strip(),
        status=(request.POST.get("status") or RentalRecord.STATUS_ACTIVE).strip(),
        notes=notes,
    )
    _refresh_house_availability(house)
    _sync_rental_payment_state(rental)
    messages.success(request, "Rental record saved.")
    return redirect("housing_management")


@login_required
@require_POST
def add_rental_payment(request):
    rental = get_object_or_404(
        RentalRecord.objects.select_related("house"),
        id=request.POST.get("rental_id"),
        house__owner=request.user,
    )
    due_date = parse_date((request.POST.get("due_date") or "").strip())
    paid_on = parse_date((request.POST.get("paid_on") or "").strip()) if request.POST.get("paid_on") else None
    status = (request.POST.get("status") or RentalPayment.STATUS_PENDING).strip()
    notes = (request.POST.get("notes") or "").strip()

    if not due_date:
        messages.error(request, "Payment due date is required.")
        return redirect("housing_management")

    valid_payment_statuses = {choice[0] for choice in RentalPayment.STATUS_CHOICES}
    if status not in valid_payment_statuses:
        status = RentalPayment.STATUS_PENDING

    try:
        amount = Decimal(request.POST.get("amount") or "0")
        if amount <= 0:
            raise ValueError
    except Exception:
        messages.error(request, "Payment amount must be a valid positive amount.")
        return redirect("housing_management")

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
    messages.success(request, "Rental payment record saved.")
    return redirect("housing_management")


@login_required
@require_POST
def send_rental_reminder(request, rental_id):
    rental = get_object_or_404(
        RentalRecord.objects.select_related("house", "house__owner"),
        id=rental_id,
        house__owner=request.user,
    )

    reminder_message = (
        f"Hello {rental.tenant_name}, your rent for {rental.house.title} at {rental.house.location} "
        f"is set to expire on {rental.end_date:%B %d, %Y}. Please plan your renewal early."
    )
    sent = False

    if rental.tenant_email:
        sent = send_email(
            rental.tenant_email,
            "VilaStore Rent Expiry Reminder",
            reminder_message,
        ) or sent
    if rental.tenant_phone:
        sent = send_sms(rental.tenant_phone, reminder_message) or sent

    if sent:
        rental.reminder_sent_at = timezone.now()
        rental.save(update_fields=["reminder_sent_at", "updated_at"])
        messages.success(request, f"Reminder sent to {rental.tenant_name}.")
    else:
        messages.warning(request, "Reminder could not be delivered. Add tenant email or phone first.")

    return redirect("housing_management")


# Authentication

def _password_meets_rules(password):
    if not password:
        return False
    has_upper = any(c.isupper() for c in password)
    has_number = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    return has_upper and has_number and has_special


def _username_is_valid(username):
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username or ""))


TRIAL_DAYS = 30
BASE_FEE = 7000
MONTHLY_SUBSCRIPTION_FEE = 1000

PLAN_CATALOG = {
    "starter": {
        "name": "Starter",
        "tagline": "Start your business",
        "audience": "For small shops and beginners",
        "registration_fee": BASE_FEE,
        "monthly_fee": Decimal("1000.00"),
        "product_limit": 1000,
        "staff_limit": 0,
        "branch_limit": 1,
        "is_custom": False,
        "features": [
            "Inventory management",
            "Daily sales tracking",
            "Basic sales history",
            "Up to 1,000 products",
            "Basic customer management: name and phone",
        ],
        "limits": [
            ("Products", "Up to 1,000 products"),
            ("Staff / Shopboy", "Not included"),
            ("Branches", "Single shop only"),
        ],
        "feature_groups": [
            ("Customer management", "Basic customer records: name and phone number only."),
            ("Automation features", "Not included."),
            ("Barcode access", "Not included."),
            ("Multi-branch access", "Not included."),
            ("Tax tools", "Not included."),
            ("Reports and analytics", "Daily sales tracking and basic sales history."),
        ],
        "unavailable": [
            "Shopboy/staff accounts",
            "Messages and automation",
            "Barcode system",
            "Multi-branch",
            "Tax tools",
        ],
    },
    "growth": {
        "name": "Growth",
        "tagline": "Grow your customers",
        "audience": "For growing businesses",
        "registration_fee": BASE_FEE,
        "monthly_fee": Decimal("5000.00"),
        "product_limit": 5000,
        "staff_limit": 3,
        "branch_limit": 1,
        "is_custom": False,
        "features": [
            "Everything in Starter",
            "Full customer management",
            "Automated Friday, Sunday, and birthday messages",
            "Shopboy/staff management: up to 3 staff",
            "Up to 5,000 products",
            "Basic sales summary reports",
        ],
        "limits": [
            ("Products", "Up to 5,000 products"),
            ("Staff / Shopboy", "Up to 3 staff accounts"),
            ("Branches", "Single shop only"),
        ],
        "feature_groups": [
            ("Customer management", "Full customer details for stronger relationship management."),
            ("Automation features", "Friday wishes, Sunday wishes, and birthday messages."),
            ("Barcode access", "Not included."),
            ("Multi-branch access", "Not included."),
            ("Tax tools", "Not included."),
            ("Reports and analytics", "Basic reports and sales summary."),
        ],
        "unavailable": [
            "Barcode system",
            "Multi-branch",
            "Tax tools",
        ],
    },
    "business": {
        "name": "Business",
        "tagline": "Manage operations",
        "audience": "For serious businesses",
        "registration_fee": BASE_FEE,
        "monthly_fee": Decimal("15000.00"),
        "product_limit": 20000,
        "staff_limit": 10,
        "branch_limit": 5,
        "is_custom": False,
        "features": [
            "Everything in Growth",
            "Barcode system",
            "Multi-branch management",
            "Advanced customer management",
            "Better reports and insights",
            "Shopboy/staff management: up to 10 staff",
            "Up to 20,000 products",
            "Basic tax calculation and tax-use sales summary",
        ],
        "limits": [
            ("Products", "Up to 20,000 products"),
            ("Staff / Shopboy", "Up to 10 staff accounts"),
            ("Branches", "Up to 5 branches"),
        ],
        "feature_groups": [
            ("Customer management", "Advanced customer management for repeat sales."),
            ("Automation features", "Customer wishes and message automation from Growth."),
            ("Barcode access", "Included for scanning and product management."),
            ("Multi-branch access", "Included for multiple shop locations."),
            ("Tax tools", "Basic tax calculation and sales summaries for tax use."),
            ("Reports and analytics", "Better reports, insights, and branch performance views."),
        ],
        "unavailable": [],
    },
    "pro": {
        "name": "Pro / Enterprise",
        "tagline": "Scale without limits",
        "audience": "For big businesses and companies",
        "registration_fee": BASE_FEE,
        "monthly_fee": Decimal("50000.00"),
        "product_limit": None,
        "staff_limit": None,
        "branch_limit": None,
        "is_custom": False,
        "features": [
            "Everything in Business",
            "Unlimited products",
            "Unlimited staff",
            "Unlimited branches",
            "Full tax reports and VAT calculations",
            "Advanced analytics dashboard",
            "Custom branding on messages",
            "Smart personalized automation",
            "Priority support",
            "Future integrations: bank, POS, and more",
        ],
        "limits": [
            ("Products", "Unlimited"),
            ("Staff / Shopboy", "Unlimited"),
            ("Branches", "Unlimited"),
        ],
        "feature_groups": [
            ("Customer management", "Advanced customer management with custom branding."),
            ("Automation features", "Smart personalized automation and branded messages."),
            ("Barcode access", "Included."),
            ("Multi-branch access", "Unlimited branches."),
            ("Tax tools", "Advanced tax reports, VAT calculations, and full tax support."),
            ("Reports and analytics", "Advanced analytics dashboard and priority reporting support."),
        ],
        "unavailable": [],
    },
}


def _plan_pricing():
    return {
        key: plan["monthly_fee"]
        for key, plan in PLAN_CATALOG.items()
        if plan["monthly_fee"] is not None
    }


def _plan_for_slug(slug):
    return PLAN_CATALOG.get(slug) or PLAN_CATALOG["starter"]


def _plan_registration_fee(slug):
    plan = _plan_for_slug(slug)
    return plan["registration_fee"] if plan["registration_fee"] is not None else BASE_FEE


def _plan_first_payment_total(slug):
    plan = _plan_for_slug(slug)
    monthly_fee = plan["monthly_fee"] or Decimal("0.00")
    return _plan_registration_fee(slug) + monthly_fee


def _plan_limit(user, key):
    plan = _plan_for_slug(getattr(user, "plan", "starter"))
    return plan.get(key)


def _plan_limit_message(limit_name, plan_name):
    return f"Your {plan_name} plan has reached its {limit_name} limit. Upgrade your plan to add more."


PLAN_FEATURE_RULES = {
    "barcode": {"minimum_plan": "business", "label": "Barcode system"},
    "multi_branch": {"minimum_plan": "business", "label": "Multi-branch management"},
    "customer_automation": {"minimum_plan": "growth", "label": "Automated customer messaging"},
    "full_customer_management": {"minimum_plan": "growth", "label": "Full customer management"},
    "tax_tools": {"minimum_plan": "business", "label": "Tax tools"},
    "advanced_tax_tools": {"minimum_plan": "pro", "label": "Advanced tax tools"},
    "advanced_reports": {"minimum_plan": "business", "label": "Advanced reports and analytics"},
}
PLAN_ORDER = ["starter", "growth", "business", "pro"]


def _plan_rank(slug):
    try:
        return PLAN_ORDER.index((slug or "starter").lower())
    except ValueError:
        return 0


def _plan_has_feature(user, feature):
    rule = PLAN_FEATURE_RULES.get(feature)
    if not rule:
        return True
    return _plan_rank(getattr(user, "plan", "starter")) >= _plan_rank(rule["minimum_plan"])


def _feature_upgrade_message(feature):
    rule = PLAN_FEATURE_RULES.get(feature, {})
    label = rule.get("label", "This feature")
    minimum = _plan_for_slug(rule.get("minimum_plan", "business"))["name"]
    return f"{label} is available on the {minimum} plan and above. Upgrade your plan to use it."


def _feature_entitlements(user):
    return {
        key: {
            "allowed": _plan_has_feature(user, key),
            "message": _feature_upgrade_message(key),
            "minimum_plan": PLAN_FEATURE_RULES[key]["minimum_plan"],
            "label": PLAN_FEATURE_RULES[key]["label"],
        }
        for key in PLAN_FEATURE_RULES
    }


def _require_feature_or_redirect(request, feature, redirect_name):
    if _plan_has_feature(request.user, feature):
        return None
    messages.error(request, _feature_upgrade_message(feature))
    return redirect(redirect_name)


def _flutterwave_public_key():
    return (
        getattr(django_settings, "FLUTTERWAVE_PUBLIC_KEY", "")
        or os.getenv("FLUTTERWAVE_PUBLIC_KEY", "")
        or "a2b97709-9d73-42ec-a850-766eda997e6b"
    ).strip()


def _flutterwave_secret_key():
    return (
        getattr(django_settings, "FLUTTERWAVE_SECRET_KEY", "")
        or os.getenv("FLUTTERWAVE_SECRET_KEY", "")
        or os.getenv("FLUTTERWAVE_CLIENT_SECRET", "")
    ).strip()


def _accounts_for_identifier(identifier):
    identity = (identifier or "").strip()
    if not identity:
        return []

    # Prefer exact match when possible to avoid case-insensitive ambiguity.
    exact_matches = list(
        User.objects.filter(Q(email=identity) | Q(username=identity))
        .order_by("-is_active", "-id")
    )
    if exact_matches:
        return exact_matches

    return list(
        User.objects.filter(Q(email__iexact=identity) | Q(username__iexact=identity))
        .order_by("-is_active", "-id")
    )


def _valid_accounts_for_credentials(request, identifier, password, account_type=None):
    identity = (identifier or "").strip()
    if not identity or not password:
        return []

    accounts = _accounts_for_identifier(identity)
    if account_type:
        accounts = [account for account in accounts if account.account_type == account_type]

    valid_accounts = []
    seen_ids = set()
    for account in accounts:
        authenticated = authenticate(request, username=account.username, password=password)
        if authenticated and authenticated.id not in seen_ids:
            valid_accounts.append(authenticated)
            seen_ids.add(authenticated.id)
    return valid_accounts


def _authenticate_with_identifier(request, identifier, password, account_type=None):
    valid_accounts = _valid_accounts_for_credentials(request, identifier, password, account_type=account_type)
    if len(valid_accounts) == 1:
        return valid_accounts[0]

    identity = (identifier or "").strip()
    if account_type or _accounts_for_identifier(identity):
        return None
    return authenticate(request, username=identity, password=password)


def _login_account_type_options(users):
    seen_types = set()
    options = []
    for user in users:
        account_type = getattr(user, "account_type", User.ACCOUNT_TYPE_SHOP)
        if account_type in seen_types:
            continue
        seen_types.add(account_type)
        label = "Housing Portal" if account_type == User.ACCOUNT_TYPE_HOUSING else "Shop Portal"
        description = (
            "Open your housing management workspace."
            if account_type == User.ACCOUNT_TYPE_HOUSING
            else "Open your shop dashboard and sales tools."
        )
        options.append({
            "value": account_type,
            "label": label,
            "description": description,
        })
    return options


def _get_signup_user(request):
    signup_user_id = request.session.get("signup_user_id")
    if not signup_user_id:
        return None
    return User.objects.filter(id=signup_user_id).first()


def _signup_account_type(request):
    if request.session.get("signup_flow") == "housing":
        return User.ACCOUNT_TYPE_HOUSING
    return User.ACCOUNT_TYPE_SHOP


def _signup_route_name(request):
    return "housing_signup" if request.session.get("signup_flow") == "housing" else "signup"


def _signup_step_redirect(request, step):
    return redirect(f"{reverse(_signup_route_name(request))}?step={step}")


def _post_login_redirect_name(user):
    if getattr(user, "account_type", User.ACCOUNT_TYPE_SHOP) == User.ACCOUNT_TYPE_HOUSING:
        return "housing_management"
    return "index"


def _send_signup_code(user):
    code = str(random.randint(100000, 999999))
    user.email_verification_code = code
    user.email_code_sent_at = timezone.now()
    user.save(update_fields=["email_verification_code", "email_code_sent_at"])

    send_email(
        user.email,
        "Your VilaStore verification code",
        f"Your verification code is {code}. It will expire in 10 minutes.",
        fail_silently=False,
    )


@require_POST
def signup_create_account(request):
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    username = (request.POST.get("username") or "").strip()
    email = (request.POST.get("email") or "").strip().lower()
    phone = (request.POST.get("phone") or "").strip()
    password = request.POST.get("password") or ""
    confirm_password = request.POST.get("confirm_password") or ""
    ref_code = (request.POST.get("ref_code") or request.session.get("agent_ref_code") or "").strip()
    ref_agent = _get_agent_by_code(ref_code)
    if ref_agent:
        request.session["agent_ref_code"] = ref_agent.referral_code

    if not first_name or not last_name or not username or not email or not password or not confirm_password or not phone:
        messages.error(request, "First name, last name, username, email, phone, and passwords are required.")
        return _signup_step_redirect(request, 1)

    if not _username_is_valid(username):
        messages.error(request, "Username must be 3-30 characters and use only letters, numbers, dot, dash, or underscore.")
        return _signup_step_redirect(request, 1)

    if password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return _signup_step_redirect(request, 1)

    if not _password_meets_rules(password):
        messages.error(request, "Password must include uppercase, number, and special character.")
        return _signup_step_redirect(request, 1)

    current_signup_user = _get_signup_user(request)
    current_signup_user_id = current_signup_user.id if current_signup_user else None
    account_type = _signup_account_type(request)

    existing_email_account = (
        User.objects.filter(email__iexact=email)
        .exclude(id=current_signup_user_id)
        .filter(account_type=account_type)
        .filter(Q(is_active=True) | Q(is_email_verified=True))
        .first()
    )
    if existing_email_account:
        messages.error(request, "Email already registered. Use another email or sign in.")
        return _signup_step_redirect(request, 1)

    username_qs = User.objects.filter(username__iexact=username, account_type=account_type)
    if current_signup_user_id:
        username_qs = username_qs.exclude(id=current_signup_user_id)
    if username_qs.exists():
        messages.error(request, "This username is already taken. Please choose another one.")
        return _signup_step_redirect(request, 1)

    phone_qs = User.objects.filter(phone=phone, account_type=account_type)
    if current_signup_user_id:
        phone_qs = phone_qs.exclude(id=current_signup_user_id)
    if phone_qs.filter(Q(is_active=True) | Q(is_email_verified=True)).exists():
        messages.error(request, "Phone number already in use. Please use another one.")
        return _signup_step_redirect(request, 1)

    signup_user = current_signup_user
    if not signup_user or signup_user.is_active or signup_user.is_email_verified:
        signup_user = (
            User.objects.filter(
                email__iexact=email,
                is_active=False,
                is_email_verified=False,
                account_type=account_type,
            )
            .order_by("-id")
            .first()
        )

    if signup_user:
        signup_user.first_name = first_name
        signup_user.last_name = last_name
        signup_user.username = username
        signup_user.email = email
        signup_user.phone = phone
        signup_user.set_password(password)
        signup_user.is_active = False
        signup_user.is_email_verified = False
        signup_user.email_verification_code = ""
        signup_user.email_code_sent_at = None
        signup_user.is_paid = False
        signup_user.account_type = account_type
        if not signup_user.business_name:
            signup_user.business_name = f"{first_name}'s Housing" if account_type == User.ACCOUNT_TYPE_HOUSING else f"{first_name}'s Shop"
        if not signup_user.business_type:
            signup_user.business_type = "housing" if account_type == User.ACCOUNT_TYPE_HOUSING else "other"
        if not signup_user.state:
            signup_user.state = "pending"
        if not signup_user.address:
            signup_user.address = "pending"
        if not signup_user.country:
            signup_user.country = "pending"
        if not signup_user.plan:
            signup_user.plan = "starter"
        if ref_agent and not signup_user.referred_by_agent_id:
            signup_user.referred_by_agent = ref_agent
        signup_user.save()
    else:
        signup_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            business_name=f"{first_name}'s Housing" if account_type == User.ACCOUNT_TYPE_HOUSING else f"{first_name}'s Shop",
            business_type="housing" if account_type == User.ACCOUNT_TYPE_HOUSING else "other",
            state="pending",
            address="pending",
            country="pending",
            plan="starter",
            account_type=account_type,
            is_paid=False,
            is_active=False,
            is_email_verified=False,
            referred_by_agent=ref_agent,
        )

    request.session["signup_user_id"] = signup_user.id
    request.session.pop("verified_signup_user_id", None)
    request.session.pop("verified_email", None)
    request.session.pop("otp_email", None)
    request.session.pop("otp_code", None)
    request.session.pop("otp_sent_at", None)

    try:
        _send_signup_code(signup_user)
        messages.success(request, f"Account created for @{signup_user.username}. Verification code sent to {signup_user.email}.")
    except Exception:
        logger.exception("Failed to send signup verification email", extra={"signup_user_id": signup_user.id, "signup_email": signup_user.email})
        messages.warning(request, "Account created. Could not send verification email now; use Send Code after checking email settings.")

    return _signup_step_redirect(request, 2)


def signup(request):
    if request.method != "POST":
        request.session["signup_flow"] = "owner"
    ref_param = request.GET.get("ref")
    if ref_param:
        ref_agent = _get_agent_by_code(ref_param)
        if ref_agent:
            request.session["agent_ref_code"] = ref_agent.referral_code

    if request.method == "POST":
        signup_user = _get_signup_user(request)
        verified_signup_user_id = request.session.get("verified_signup_user_id")

        if not signup_user:
            messages.error(request, "Start by creating your account first.")
            return _signup_step_redirect(request, 1)

        if verified_signup_user_id != signup_user.id or not signup_user.is_email_verified:
            messages.error(request, "Please verify your email before completing shop setup.")
            return _signup_step_redirect(request, 2)

        business_name = (request.POST.get("business_name") or "").strip()
        business_type = (request.POST.get("business_type") or "").strip()
        country = (request.POST.get("country") or "").strip()
        address = (request.POST.get("address") or "").strip()
        state = (request.POST.get("state") or "").strip()
        plan = (request.POST.get("plan") or "starter").strip() or "starter"
        shop_description = (request.POST.get("shop_description") or "").strip()
        shop_category = (request.POST.get("shop_category") or "").strip()
        shop_location = (request.POST.get("shop_location") or "").strip()
        phone = (request.POST.get("phone") or "").strip()

        if not business_name or not business_type or not country or not address or not state:
            messages.error(request, "Business name, business type, country, address, and state are required.")
            return _signup_step_redirect(request, 3)

        if phone:
            if User.objects.filter(phone=phone).exclude(id=signup_user.id).filter(Q(is_active=True) | Q(is_email_verified=True)).exists():
                messages.error(request, "Phone number already in use. Please use another one.")
                return _signup_step_redirect(request, 3)
            signup_user.phone = phone

        plan_prices = _plan_pricing()
        if plan not in plan_prices:
            plan = "starter"

        trial_end = timezone.now().date() + timedelta(days=TRIAL_DAYS)

        signup_user.business_name = business_name
        signup_user.business_type = business_type
        signup_user.account_type = User.ACCOUNT_TYPE_SHOP
        signup_user.country = country
        signup_user.address = address
        signup_user.state = state
        signup_user.plan = plan
        signup_user.is_paid = False
        signup_user.monthly_fee = plan_prices[plan]
        signup_user.is_active = True
        signup_user.subscription_active_until = trial_end

        profile_image = request.FILES.get("profile_image")
        if profile_image:
            signup_user.profile_image = profile_image
        signup_user.save()

        marketplace_profile, _ = MarketplaceShopProfile.objects.get_or_create(user=signup_user)
        marketplace_profile.description = shop_description
        marketplace_profile.category = shop_category
        marketplace_profile.location = shop_location

        marketplace_logo = request.FILES.get("marketplace_logo")
        if marketplace_logo:
            marketplace_profile.logo = marketplace_logo

        marketplace_cover_image = request.FILES.get("marketplace_cover_image")
        if marketplace_cover_image:
            marketplace_profile.cover_image = marketplace_cover_image

        marketplace_profile.save()

        _ensure_shop_code(signup_user)
        login(request, signup_user, backend="django.contrib.auth.backends.ModelBackend")

        request.session.pop("signup_user_id", None)
        request.session.pop("verified_signup_user_id", None)
        request.session.pop("verified_email", None)
        request.session.pop("otp_email", None)
        request.session.pop("otp_code", None)
        request.session.pop("otp_sent_at", None)
        request.session.pop("agent_ref_code", None)
        request.session.pop("signup_flow", None)

        trial_end_display = trial_end.strftime("%b %d, %Y")
        selected_plan = _plan_for_slug(signup_user.plan)
        registration_fee = _plan_registration_fee(signup_user.plan)
        monthly_fee = selected_plan["monthly_fee"] or Decimal(MONTHLY_SUBSCRIPTION_FEE)
        first_payment_total = registration_fee + monthly_fee
        messages.success(
            request,
            "Signup completed successfully. "
            f"Your free trial runs until {trial_end_display}. "
            f"First payment due after trial is NGN {first_payment_total:,} "
            f"(NGN {registration_fee:,} registration + NGN {monthly_fee:,} {selected_plan['name']} subscription), "
            f"then NGN {monthly_fee:,}/month.",
        )
        return redirect(_post_login_redirect_name(signup_user))

    signup_user = _get_signup_user(request)
    marketplace_profile = None
    if signup_user:
        marketplace_profile = MarketplaceShopProfile.objects.filter(user=signup_user).first()

    def _prefill(value):
        if not value:
            return ""
        if isinstance(value, str) and value.strip().lower() == "pending":
            return ""
        return value

    default_step = "1"
    if signup_user:
        default_step = "3" if signup_user.is_email_verified else "2"

    current_step = request.GET.get("step", default_step)
    if current_step not in {"1", "2", "3"}:
        current_step = default_step

    return render(request, "auth/signup.html", {
        "FLUTTERWAVE_PUBLIC_KEY": _flutterwave_public_key(),
        "current_step": current_step,
        "email_verified": bool(signup_user and signup_user.is_email_verified),
        "prefill_ref_code": (
            signup_user.referred_by_agent.referral_code
            if signup_user and signup_user.referred_by_agent
            else request.session.get("agent_ref_code", "")
        ),
        "prefill_first_name": signup_user.first_name if signup_user else "",
        "prefill_last_name": signup_user.last_name if signup_user else "",
        "prefill_username": signup_user.username if signup_user else "",
        "prefill_email": signup_user.email if signup_user else "",
        "prefill_phone": signup_user.phone if signup_user else "",
        "prefill_business_name": _prefill(signup_user.business_name) if signup_user else "",
        "prefill_business_type": _prefill(signup_user.business_type) if signup_user else "",
        "prefill_country": _prefill(signup_user.country) if signup_user else "",
        "prefill_address": _prefill(signup_user.address) if signup_user else "",
        "prefill_state": _prefill(signup_user.state) if signup_user else "",
        "prefill_plan": signup_user.plan if signup_user else "starter",
        "prefill_shop_description": marketplace_profile.description if marketplace_profile else "",
        "prefill_shop_category": marketplace_profile.category if marketplace_profile else "",
        "prefill_shop_location": marketplace_profile.location if marketplace_profile else "",
        "base_fee": BASE_FEE,
        "monthly_fee": MONTHLY_SUBSCRIPTION_FEE,
        "first_payment_total": BASE_FEE + MONTHLY_SUBSCRIPTION_FEE,
        "plans": PLAN_CATALOG,
        "signup_flow": "owner",
        "brand_title": "VilaStore",
        "brand_heading": "Launch With Confidence",
        "brand_description": "Create your owner account, verify your email, then set up your shop for marketplace visibility.",
        "account_heading": "Create Owner Account",
        "account_description": "First create your account details before email verification.",
        "verify_description": "Verify your email before adding shop information.",
        "setup_step_label": "Shop Setup",
        "setup_heading": "Set Up Your Shop",
        "setup_description": "Add your business and marketplace details. Start your 1-month free trial once you finish signup.",
        "business_name_label": "Business Name",
        "business_type_label": "Business Type",
        "shop_category_label": "Marketplace Category",
        "shop_location_label": "Marketplace Location",
        "shop_description_label": "Shop Description",
        "plan_heading": "Shop Owner Plan",
        "signup_finish_label": "Start Free Trial",
        "setup_form_url": reverse("signup"),
    })


def housing_signup(request):
    request.session["signup_flow"] = "housing"

    ref_param = request.GET.get("ref")
    if ref_param:
        ref_agent = _get_agent_by_code(ref_param)
        if ref_agent:
            request.session["agent_ref_code"] = ref_agent.referral_code

    if request.method == "POST":
        signup_user = _get_signup_user(request)
        verified_signup_user_id = request.session.get("verified_signup_user_id")

        if not signup_user:
            messages.error(request, "Start by creating your housing account first.")
            return _signup_step_redirect(request, 1)

        if verified_signup_user_id != signup_user.id or not signup_user.is_email_verified:
            messages.error(request, "Please verify your email before completing housing setup.")
            return _signup_step_redirect(request, 2)

        business_name = (request.POST.get("business_name") or "").strip()
        business_type = (request.POST.get("business_type") or "housing").strip() or "housing"
        country = (request.POST.get("country") or "").strip()
        address = (request.POST.get("address") or "").strip()
        state = (request.POST.get("state") or "").strip()
        plan = (request.POST.get("plan") or "starter").strip() or "starter"
        phone = (request.POST.get("phone") or "").strip()

        if not business_name or not business_type or not country or not address or not state:
            messages.error(request, "Business name, housing type, country, address, and state are required.")
            return _signup_step_redirect(request, 3)

        if phone:
            if User.objects.filter(phone=phone, account_type=User.ACCOUNT_TYPE_HOUSING).exclude(id=signup_user.id).filter(Q(is_active=True) | Q(is_email_verified=True)).exists():
                messages.error(request, "Phone number already in use for another housing account. Please use another one.")
                return _signup_step_redirect(request, 3)
            signup_user.phone = phone

        plan_prices = _plan_pricing()
        if plan not in plan_prices:
            plan = "starter"

        trial_end = timezone.now().date() + timedelta(days=TRIAL_DAYS)

        signup_user.business_name = business_name
        signup_user.business_type = business_type
        signup_user.account_type = User.ACCOUNT_TYPE_HOUSING
        signup_user.country = country
        signup_user.address = address
        signup_user.state = state
        signup_user.plan = plan
        signup_user.is_paid = False
        signup_user.monthly_fee = plan_prices[plan]
        signup_user.is_active = True
        signup_user.subscription_active_until = trial_end

        profile_image = request.FILES.get("profile_image")
        if profile_image:
            signup_user.profile_image = profile_image
        signup_user.save()

        login(request, signup_user, backend="django.contrib.auth.backends.ModelBackend")

        request.session.pop("signup_user_id", None)
        request.session.pop("verified_signup_user_id", None)
        request.session.pop("verified_email", None)
        request.session.pop("otp_email", None)
        request.session.pop("otp_code", None)
        request.session.pop("otp_sent_at", None)
        request.session.pop("agent_ref_code", None)
        request.session.pop("signup_flow", None)

        trial_end_display = trial_end.strftime("%b %d, %Y")
        selected_plan = _plan_for_slug(signup_user.plan)
        registration_fee = _plan_registration_fee(signup_user.plan)
        monthly_fee = selected_plan["monthly_fee"] or Decimal(MONTHLY_SUBSCRIPTION_FEE)
        first_payment_total = registration_fee + monthly_fee
        messages.success(
            request,
            "Housing signup completed successfully. "
            f"Your free trial runs until {trial_end_display}. "
            f"First payment due after trial is NGN {first_payment_total:,} "
            f"(NGN {registration_fee:,} registration + NGN {monthly_fee:,} {selected_plan['name']} subscription), "
            f"then NGN {monthly_fee:,}/month.",
        )
        return redirect("housing_management")

    signup_user = _get_signup_user(request)
    marketplace_profile = None
    if signup_user:
        marketplace_profile = MarketplaceShopProfile.objects.filter(user=signup_user).first()

    def _prefill(value):
        if not value:
            return ""
        if isinstance(value, str) and value.strip().lower() == "pending":
            return ""
        return value

    default_step = "1"
    if signup_user:
        default_step = "3" if signup_user.is_email_verified else "2"

    current_step = request.GET.get("step", default_step)
    if current_step not in {"1", "2", "3"}:
        current_step = default_step

    return render(request, "auth/signup.html", {
        "FLUTTERWAVE_PUBLIC_KEY": _flutterwave_public_key(),
        "current_step": current_step,
        "email_verified": bool(signup_user and signup_user.is_email_verified),
        "prefill_ref_code": (
            signup_user.referred_by_agent.referral_code
            if signup_user and signup_user.referred_by_agent
            else request.session.get("agent_ref_code", "")
        ),
        "prefill_first_name": signup_user.first_name if signup_user else "",
        "prefill_last_name": signup_user.last_name if signup_user else "",
        "prefill_username": signup_user.username if signup_user else "",
        "prefill_email": signup_user.email if signup_user else "",
        "prefill_phone": signup_user.phone if signup_user else "",
        "prefill_business_name": _prefill(signup_user.business_name) if signup_user else "",
        "prefill_business_type": _prefill(signup_user.business_type) if signup_user else "housing",
        "prefill_country": _prefill(signup_user.country) if signup_user else "",
        "prefill_address": _prefill(signup_user.address) if signup_user else "",
        "prefill_state": _prefill(signup_user.state) if signup_user else "",
        "prefill_plan": signup_user.plan if signup_user else "starter",
        "prefill_shop_description": marketplace_profile.description if marketplace_profile else "",
        "prefill_shop_category": marketplace_profile.category if marketplace_profile else "House Rentals",
        "prefill_shop_location": marketplace_profile.location if marketplace_profile else "",
        "base_fee": BASE_FEE,
        "monthly_fee": MONTHLY_SUBSCRIPTION_FEE,
        "first_payment_total": BASE_FEE + MONTHLY_SUBSCRIPTION_FEE,
        "plans": PLAN_CATALOG,
        "signup_flow": "housing",
        "brand_title": "VilaStore Housing",
        "brand_heading": "Register for Housing Management",
        "brand_description": "Create your housing owner or agent account, verify your email, then set up your rental business profile and start managing properties online.",
        "account_heading": "Create Housing Account",
        "account_description": "Start your housing management registration here before email verification.",
        "verify_description": "Verify your email before completing your housing account setup.",
        "setup_step_label": "Housing Setup",
        "setup_heading": "Set Up Your Housing Business",
        "setup_description": "Add your housing business details so you can manage listings, tenants, payments, and reminders from the web dashboard.",
        "business_name_label": "Business or Agency Name",
        "business_type_label": "Housing Type",
        "shop_category_label": "Housing Category",
        "shop_location_label": "Primary Service Location",
        "shop_description_label": "Housing Description",
        "plan_heading": "Housing Owner Plan",
        "signup_finish_label": "Create Housing Account",
        "setup_form_url": reverse("housing_signup"),
    })


def login_view(request):
    preferred_account_type = (request.GET.get("account_type") or "").strip()
    if preferred_account_type not in {
        User.ACCOUNT_TYPE_SHOP,
        User.ACCOUNT_TYPE_HOUSING,
    }:
        preferred_account_type = ""

    if request.user.is_authenticated:
        current_account_type = getattr(request.user, "account_type", User.ACCOUNT_TYPE_SHOP)
        if preferred_account_type and preferred_account_type != current_account_type:
            logout(request)
            messages.info(request, f"Signed out of your {current_account_type} account. Sign in to continue to the {preferred_account_type} portal.")
        else:
            return redirect(_post_login_redirect_name(request.user))

    login_context = {
        "prefill_email": "",
        "selected_account_type": preferred_account_type,
        "account_type_options": [],
    }

    if request.method == "POST":
        identifier = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        selected_account_type = (request.POST.get("account_type") or preferred_account_type).strip()
        login_context["prefill_email"] = identifier
        login_context["selected_account_type"] = selected_account_type
        matching_accounts = _accounts_for_identifier(identifier)
        account_type_options = _login_account_type_options(matching_accounts)
        has_multiple_portals = len(account_type_options) > 1

        valid_accounts = _valid_accounts_for_credentials(
            request,
            identifier,
            password,
            account_type=selected_account_type or None,
        )
        if has_multiple_portals and not selected_account_type:
            if valid_accounts:
                login_context["account_type_options"] = account_type_options
                messages.error(request, "Choose the portal you want to enter before we sign you in.")
            else:
                messages.error(request, "Invalid email/username or password")
            return render(request, "auth/login.html", login_context)

        user = valid_accounts[0] if len(valid_accounts) == 1 else None
        if user is not None:
            if not subscription_is_active(user):
                request.session["pending_payment_user_id"] = user.id
                messages.error(request, "Subscription payment required. Please make the payment to continue.")
                return redirect("subscription_payment")
            login(request, user)
            request.session.pop("pending_payment_user_id", None)
            return redirect(_post_login_redirect_name(user))

        if len(valid_accounts) > 1 and not selected_account_type:
            login_context["account_type_options"] = _login_account_type_options(valid_accounts)
            messages.error(request, "We found more than one account on these credentials. Choose the portal you want to enter.")
            return render(request, "auth/login.html", login_context)

        pending_user = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier),
            is_active=False,
        )
        if selected_account_type:
            pending_user = pending_user.filter(account_type=selected_account_type)
        pending_user = pending_user.first()
        if pending_user:
            messages.error(request, "Your account setup is not complete yet. Finish signup and verify your email.")
        else:
            messages.error(request, "Invalid email/username or password")

        if len(matching_accounts) > 1 and not login_context["account_type_options"]:
            login_context["account_type_options"] = _login_account_type_options(matching_accounts)

    return render(request, "auth/login.html", login_context)


def logout_view(request):
    logout(request)
    return redirect("login")


# =============================
# Investor Portal
# =============================

def _get_investor_session(request):
    investor_id = request.session.get("investor_id")
    if not investor_id:
        return None
    return Investor.objects.filter(id=investor_id, is_active=True).first()


def investor_login(request):
    if _get_investor_session(request):
        return redirect("investor_dashboard")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""

        investor = Investor.objects.filter(email__iexact=email, is_active=True).first()
        if not investor or not check_password(password, investor.password):
            messages.error(request, "Invalid email or password.")
            return render(request, "investor/investor-login.html")

        request.session["investor_id"] = investor.id
        investor.last_login = timezone.now()
        investor.save(update_fields=["last_login"])
        return redirect("investor_dashboard")

    return render(request, "investor/investor-login.html")


def investor_logout(request):
    request.session.pop("investor_id", None)
    return redirect("investor_login")


def investor_dashboard(request):
    investor = _get_investor_session(request)
    if not investor:
        return redirect("investor_login")

    today = timezone.localdate()
    active_qs = User.objects.filter(
        subscription_active_until__gte=today,
        is_paid=True,
        is_staff=False,
        is_superuser=False,
        account_type=User.ACCOUNT_TYPE_SHOP,
    )
    active_shops = active_qs.count()
    monthly_revenue = active_qs.aggregate(total=Sum("monthly_fee"))["total"] or Decimal("0.00")

    ownership_ratio = (investor.ownership_percent or Decimal("0")) / Decimal("100")
    monthly_return = (monthly_revenue * ownership_ratio).quantize(Decimal("0.01"))

    return render(request, "investor/investor-dashboard.html", {
        "investor": investor,
        "active_shops": active_shops,
        "monthly_revenue": monthly_revenue,
        "monthly_return": monthly_return,
    })


# =============================
# Agent Portal
# =============================

def _get_agent_session(request):
    agent_id = request.session.get("agent_id")
    if not agent_id:
        return None
    return Agent.objects.filter(id=agent_id, is_active=True).first()


def _get_pending_agent(request):
    agent_id = request.session.get("agent_pending_id")
    if not agent_id:
        return None
    return Agent.objects.filter(id=agent_id, is_active=True).first()


def _send_agent_verification_code(agent: Agent):
    code = str(random.randint(100000, 999999))
    agent.email_verification_code = code
    agent.email_code_sent_at = timezone.now()
    agent.save(update_fields=["email_verification_code", "email_code_sent_at"])
    send_email(
        agent.email,
        "Your VilaStore Agent verification code",
        f"Your verification code is {code}. It will expire in 10 minutes.",
    )


def _send_agent_reset_code(agent: Agent):
    code = str(random.randint(100000, 999999))
    agent.reset_code = code
    agent.reset_sent_at = timezone.now()
    agent.save(update_fields=["reset_code", "reset_sent_at"])
    send_email(
        agent.email,
        "VilaStore Agent password reset code",
        f"Your password reset code is {code}. It will expire in 10 minutes.",
    )


def agent_login(request):
    if _get_agent_session(request):
        return redirect("agent_dashboard")

    if request.method == "POST":
        identifier = (request.POST.get("identifier") or "").strip()
        password = request.POST.get("password") or ""

        agent = Agent.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier),
            is_active=True,
        ).first()
        if not agent or not check_password(password, agent.password):
            messages.error(request, "Invalid username/email or password.")
            return render(request, "agent/agent-login.html")

        if not agent.is_email_verified:
            request.session["agent_pending_id"] = agent.id
            should_send = not agent.email_verification_code or not agent.email_code_sent_at
            if agent.email_code_sent_at and timezone.now() - agent.email_code_sent_at > timedelta(minutes=10):
                should_send = True
            if should_send:
                try:
                    _send_agent_verification_code(agent)
                except Exception:
                    messages.error(request, "Failed to send verification email. Please try again.")
                    return redirect("agent_verify")
            messages.error(request, "Verify your email to continue. We sent you a code.")
            return redirect("agent_verify")

        request.session["agent_id"] = agent.id
        agent.last_login = timezone.now()
        agent.save(update_fields=["last_login"])
        return redirect("agent_dashboard")

    return render(request, "agent/agent-login.html")


def agent_signup(request):
    if _get_agent_session(request):
        return redirect("agent_dashboard")

    if request.method == "POST":
        full_name = (request.POST.get("full_name") or "").strip()
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        phone = (request.POST.get("phone") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""

        if not full_name or not username or not email or not password or not confirm_password:
            messages.error(request, "Full name, username, email, and passwords are required.")
            return render(request, "agent/agent-signup.html")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "agent/agent-signup.html")

        if Agent.objects.filter(username__iexact=username).exists():
            messages.error(request, "This username is already taken.")
            return render(request, "agent/agent-signup.html")

        if Agent.objects.filter(email__iexact=email).exists():
            messages.error(request, "This email is already registered.")
            return render(request, "agent/agent-signup.html")

        agent = Agent.objects.create(
            full_name=full_name,
            username=username,
            email=email,
            phone=phone,
            password=password,
            is_email_verified=False,
        )
        request.session["agent_pending_id"] = agent.id
        try:
            _send_agent_verification_code(agent)
            messages.success(request, f"Agent account created for {agent.full_name}. Verification code sent to {agent.email}.")
        except Exception:
            logger.exception("Failed to send agent verification email", extra={"agent_id": agent.id, "agent_email": agent.email})
            messages.warning(request, "Agent account created. Could not send verification email now; use Resend Code after checking email settings.")
        return redirect("agent_verify")

    return render(request, "agent/agent-signup.html")


def agent_verify(request):
    if _get_agent_session(request):
        return redirect("agent_dashboard")

    agent = _get_pending_agent(request)
    if not agent:
        messages.error(request, "No pending agent verification found. Please sign in.")
        return redirect("agent_login")

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if not code:
            messages.error(request, "Verification code is required.")
            return render(request, "agent/agent-verify.html", {"agent": agent})

        sent_at = agent.email_code_sent_at
        if not agent.email_verification_code or not sent_at:
            messages.error(request, "No OTP found. Send code first.")
            return render(request, "agent/agent-verify.html", {"agent": agent})

        if timezone.now() - sent_at > timedelta(minutes=10):
            messages.error(request, "OTP expired. Send a new code.")
            return render(request, "agent/agent-verify.html", {"agent": agent})

        if code != agent.email_verification_code:
            messages.error(request, "Invalid code.")
            return render(request, "agent/agent-verify.html", {"agent": agent})

        agent.is_email_verified = True
        agent.email_verification_code = ""
        agent.email_code_sent_at = None
        agent.last_login = timezone.now()
        agent.save(update_fields=["is_email_verified", "email_verification_code", "email_code_sent_at", "last_login"])

        request.session.pop("agent_pending_id", None)
        request.session["agent_id"] = agent.id
        messages.success(request, "Email verified successfully.")
        return redirect("agent_dashboard")

    return render(request, "agent/agent-verify.html", {"agent": agent})


@require_POST
def agent_send_verification_code(request):
    agent = _get_pending_agent(request)
    if not agent:
        messages.error(request, "No pending agent verification found.")
        return redirect("agent_login")

    try:
        _send_agent_verification_code(agent)
    except Exception:
        messages.error(request, "Failed to send verification email. Please try again.")
        return redirect("agent_verify")

    messages.success(request, f"Code sent to {agent.email}.")
    return redirect("agent_verify")


def agent_forgot_password(request):
    reset_step = request.session.get("agent_reset_step", "email")
    reset_email = request.session.get("agent_reset_email", "")
    return render(request, "agent/agent-forgot-password.html", {
        "reset_step": reset_step,
        "reset_email": reset_email,
    })


@require_POST
def agent_forgot_password_send_code(request):
    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "Email is required.")
        return redirect("agent_forgot_password")

    agent = Agent.objects.filter(email__iexact=email, is_active=True).first()
    if not agent:
        messages.success(request, "If this email exists, a code has been sent.")
        return redirect("agent_forgot_password")

    request.session["agent_reset_email"] = email
    request.session["agent_reset_step"] = "otp"
    request.session["agent_reset_verified"] = False
    request.session.modified = True

    try:
        _send_agent_reset_code(agent)
    except Exception:
        messages.error(request, "Failed to send reset email. Check email settings.")
        return redirect("agent_forgot_password")

    messages.success(request, "Verification code sent.")
    return redirect("agent_forgot_password")


@require_POST
def agent_forgot_password_verify_code(request):
    email = (request.POST.get("email") or "").strip().lower()
    code = (request.POST.get("code") or "").strip()

    session_email = request.session.get("agent_reset_email")
    if not session_email or email != session_email:
        messages.error(request, "No reset code found. Send code first.")
        return redirect("agent_forgot_password")

    agent = Agent.objects.filter(email__iexact=email, is_active=True).first()
    if not agent or not agent.reset_code or not agent.reset_sent_at:
        messages.error(request, "No reset code found. Send code first.")
        return redirect("agent_forgot_password")

    if timezone.now() - agent.reset_sent_at > timedelta(minutes=10):
        messages.error(request, "Reset code expired. Send a new code.")
        return redirect("agent_forgot_password")

    if code != agent.reset_code:
        messages.error(request, "Invalid code.")
        return redirect("agent_forgot_password")

    request.session["agent_reset_verified"] = True
    request.session["agent_reset_step"] = "reset"
    messages.success(request, "Code verified. Set your new password.")
    return redirect("agent_forgot_password")


@require_POST
def agent_forgot_password_reset(request):
    email = (request.POST.get("email") or "").strip().lower()
    password = request.POST.get("password") or ""
    confirm_password = request.POST.get("confirm_password") or ""

    if not email:
        messages.error(request, "Email is required.")
        return redirect("agent_forgot_password")

    if password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return redirect("agent_forgot_password")

    if not _password_meets_rules(password):
        messages.error(request, "Password must include uppercase, number, and special character.")
        return redirect("agent_forgot_password")

    if request.session.get("agent_reset_verified") is not True or request.session.get("agent_reset_email") != email:
        messages.error(request, "Reset not verified.")
        return redirect("agent_forgot_password")

    agent = Agent.objects.filter(email__iexact=email, is_active=True).first()
    if not agent:
        messages.error(request, "Account not found.")
        return redirect("agent_forgot_password")

    agent.password = make_password(password)
    agent.reset_code = ""
    agent.reset_sent_at = None
    agent.save(update_fields=["password", "reset_code", "reset_sent_at"])

    request.session.pop("agent_reset_email", None)
    request.session.pop("agent_reset_step", None)
    request.session.pop("agent_reset_verified", None)

    messages.success(request, "Password reset successful. Please sign in.")
    return redirect("agent_login")


def agent_logout(request):
    request.session.pop("agent_id", None)
    return redirect("agent_login")


def agent_dashboard(request):
    agent = _get_agent_session(request)
    if not agent:
        return redirect("agent_login")

    shops = User.objects.filter(referred_by_agent=agent).order_by("-date_joined")

    rate = agent.commission_rate or Decimal("0.15")
    monthly_total = Decimal("0.00")
    items = []

    for shop in shops:
        is_active = bool(shop.is_paid and subscription_is_active(shop))
        monthly_fee = shop.monthly_fee or Decimal("0.00")
        commission = (monthly_fee * rate).quantize(Decimal("0.01")) if is_active else Decimal("0.00")
        monthly_total += commission
        items.append({
            "shop": shop,
            "is_active": is_active,
            "monthly_fee": monthly_fee,
            "commission": commission,
        })

    active_count = sum(1 for item in items if item["is_active"])
    invite_link = request.build_absolute_uri(f"{reverse('signup')}?ref={agent.referral_code}")

    return render(request, "agent/agent-dashboard.html", {
        "agent": agent,
        "shops": items,
        "active_count": active_count,
        "inactive_count": len(items) - active_count,
        "monthly_total": monthly_total.quantize(Decimal("0.01")),
        "commission_rate_percent": (rate * Decimal("100")).quantize(Decimal("0.01")),
        "invite_link": invite_link,
        "property_count": HouseListing.objects.filter(listing_agent=agent, is_active=True).count(),
        "marketplace_property_count": HouseListing.objects.filter(
            listing_agent=agent,
            is_active=True,
            listed_in_marketplace=True,
            is_approved=True,
        ).count(),
    })


def agent_property_management(request):
    agent = _get_agent_session(request)
    if not agent:
        return redirect("agent_login")

    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    houses = (
        HouseListing.objects.filter(listing_agent=agent)
        .prefetch_related("images")
        .select_related("managed_by_agent")
        .order_by("-created_at")
    )
    if q:
        houses = houses.filter(
            Q(title__icontains=q) |
            Q(location__icontains=q) |
            Q(description__icontains=q)
        )
    if status_filter:
        houses = houses.filter(availability_status=status_filter)

    return render(request, "agent/agent-properties.html", {
        "agent": agent,
        "houses": houses,
        "filters": {"q": q, "status": status_filter},
        "house_status_choices": HouseListing.AVAILABILITY_STATUS_CHOICES,
        "property_type_choices": HouseListing.PROPERTY_TYPE_CHOICES,
        "listing_mode_choices": HouseListing.LISTING_MODE_CHOICES,
        "stats": {
            "houses": HouseListing.objects.filter(listing_agent=agent, is_active=True).count(),
            "available_houses": HouseListing.objects.filter(
                listing_agent=agent,
                availability_status=HouseListing.STATUS_AVAILABLE,
                is_active=True,
            ).count(),
            "marketplace_live": HouseListing.objects.filter(
                listing_agent=agent,
                listed_in_marketplace=True,
                is_active=True,
                is_approved=True,
            ).count(),
            "pending_approval": HouseListing.objects.filter(
                listing_agent=agent,
                is_active=True,
                is_approved=False,
            ).count(),
        },
    })


@require_POST
def agent_add_house_listing(request):
    agent = _get_agent_session(request)
    if not agent:
        return redirect("agent_login")

    title = (request.POST.get("title") or "").strip()
    listing_mode = (request.POST.get("listing_mode") or HouseListing.MODE_RENT).strip()
    property_type = (request.POST.get("property_type") or HouseListing.TYPE_APARTMENT).strip()
    location = (request.POST.get("location") or "").strip()
    description = (request.POST.get("description") or "").strip()
    availability_status = (request.POST.get("availability_status") or HouseListing.STATUS_AVAILABLE).strip()

    if not title or not location:
        messages.error(request, "House title and location are required.")
        return redirect("agent_property_management")

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
        messages.error(request, "Price, rooms, and spaces must be valid positive values.")
        return redirect("agent_property_management")

    house = HouseListing.objects.create(
        owner=None,
        listing_agent=agent,
        managed_by_agent=agent,
        title=title,
        listing_mode=listing_mode,
        property_type=property_type,
        price=price,
        location=location,
        rooms_count=rooms_count,
        spaces_available=spaces_available,
        description=description,
        availability_status=availability_status,
        listed_in_marketplace=request.POST.get("listed_in_marketplace") == "on",
        is_approved=agent.is_email_verified,
    )

    for index, image in enumerate(request.FILES.getlist("images")):
        HouseListingImage.objects.create(
            house=house,
            image=image,
            is_primary=index == 0,
        )

    messages.success(request, "Property listing added. Approved listings automatically appear in the marketplace.")
    return redirect("agent_property_management")


@require_POST
def agent_update_house_listing(request, house_id):
    agent = _get_agent_session(request)
    if not agent:
        return redirect("agent_login")

    house = get_object_or_404(HouseListing, id=house_id, listing_agent=agent)
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
    house.listed_in_marketplace = request.POST.get("listed_in_marketplace") == "on"
    house.is_active = request.POST.get("is_active") == "on"
    house.save(update_fields=["availability_status", "listing_mode", "listed_in_marketplace", "is_active", "updated_at"])
    messages.success(request, f"{house.title} updated.")
    return redirect("agent_property_management")


def subscription_payment(request):
    user = request.user if request.user.is_authenticated else None
    pending_user_id = request.session.get("pending_payment_user_id")
    if not user and pending_user_id:
        user = User.objects.filter(id=pending_user_id).first()
    if not user:
        messages.error(request, "Please log in to continue.")
        return redirect("login")
    today = timezone.localdate()

    if subscription_is_active(user):
        request.session.pop("pending_payment_user_id", None)
        if request.user.is_authenticated:
            messages.success(request, "Your subscription is already active.")
            return redirect("index")
        messages.success(request, "Your subscription is already active. Please log in.")
        return redirect("login")

    plan = _plan_for_slug(user.plan)
    monthly_fee = plan["monthly_fee"] or (user.monthly_fee or Decimal(MONTHLY_SUBSCRIPTION_FEE))
    registration_fee = _plan_registration_fee(user.plan)
    registration_due = not user.is_paid
    amount_due = registration_fee + monthly_fee if registration_due else monthly_fee

    if request.method == "POST":
        payment_reference = (request.POST.get("payment_reference") or "").strip()
        if not payment_reference:
            messages.error(request, "Payment reference is missing. Complete payment to continue.")
            return redirect("subscription_payment")

        flutterwave_secret = _flutterwave_secret_key()
        if not flutterwave_secret:
            messages.error(request, "Flutterwave secret key is not configured.")
            return redirect("subscription_payment")

        try:
            verify_response = requests.get(
                f"https://api.flutterwave.com/v3/transactions/{payment_reference}/verify",
                headers={"Authorization": f"Bearer {flutterwave_secret}"},
                timeout=15,
            )
            verify_payload = verify_response.json()
        except Exception:
            messages.error(request, "Could not verify payment right now. Please try again.")
            return redirect("subscription_payment")

        tx_data = verify_payload.get("data") or {}
        tx_status = (tx_data.get("status") or "").strip().lower()
        if (verify_payload.get("status") or "").strip().lower() != "success" or tx_status != "successful":
            messages.error(request, "Payment was not successful.")
            return redirect("subscription_payment")

        try:
            paid_amount = Decimal(str(tx_data.get("amount") or "0"))
        except Exception:
            paid_amount = Decimal("0.00")
        if paid_amount < amount_due:
            messages.error(request, "Paid amount does not match the required subscription fee.")
            return redirect("subscription_payment")

        currency = (tx_data.get("currency") or "").strip().upper()
        if currency and currency != "NGN":
            messages.error(request, "Payment currency does not match the required currency.")
            return redirect("subscription_payment")

        customer = tx_data.get("customer") or {}
        flutterwave_email = (customer.get("email") or "").strip().lower()
        if flutterwave_email and flutterwave_email != (user.email or "").strip().lower():
            messages.error(request, "Payment email does not match your account email.")
            return redirect("subscription_payment")

        start_date = today
        if user.subscription_active_until and user.subscription_active_until > today:
            start_date = user.subscription_active_until

        user.is_paid = True
        user.monthly_fee = monthly_fee
        user.subscription_active_until = start_date + timedelta(days=30)
        user.save(update_fields=["is_paid", "monthly_fee", "subscription_active_until"])

        if not request.user.is_authenticated:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.pop("pending_payment_user_id", None)

        active_until_display = user.subscription_active_until.strftime("%b %d, %Y")
        messages.success(request, f"Payment confirmed. Subscription active until {active_until_display}.")
        return redirect("index")

    context = {
        "FLUTTERWAVE_PUBLIC_KEY": _flutterwave_public_key(),
        "amount_due": amount_due,
        "registration_due": registration_due,
        "base_fee": registration_fee,
        "monthly_fee": monthly_fee,
        "first_payment_total": registration_fee + monthly_fee,
        "plan": plan,
        "subscription_active_until": user.subscription_active_until,
        "subscription_email": user.email,
        "subscription_customer_name": user.get_full_name() or user.username or "VilaStore customer",
        "subscription_phone": user.phone or "",
    }
    return render(request, "auth/subscription-payment.html", context)


@require_POST
def send_code(request):
    is_json = bool(request.content_type and "application/json" in request.content_type)
    signup_user = _get_signup_user(request)

    if not signup_user:
        if is_json:
            return JsonResponse({"success": False, "message": "Create your account first."}, status=400)
        messages.error(request, "Create your account first.")
        return _signup_step_redirect(request, 1)

    if signup_user.is_email_verified:
        request.session["verified_signup_user_id"] = signup_user.id
        request.session["verified_email"] = signup_user.email
        if is_json:
            return JsonResponse({"success": True, "message": "Email already verified"})
        messages.success(request, "Email already verified.")
        return _signup_step_redirect(request, 3)

    try:
        _send_signup_code(signup_user)
    except Exception as exc:
        logger.exception("Failed to resend signup verification email", extra={"signup_user_id": signup_user.id, "signup_email": signup_user.email})
        if is_json:
            return JsonResponse({
                "success": False,
                "message": "Failed to send OTP email. Configure email settings.",
                "error": str(exc),
            }, status=500)
        messages.error(request, "Failed to send OTP email. Configure email settings.")
        return _signup_step_redirect(request, 2)

    if is_json:
        return JsonResponse({"success": True, "message": f"Code sent to {signup_user.email}"})
    messages.success(request, f"Code sent to {signup_user.email}")
    return _signup_step_redirect(request, 2)


@require_POST
def verify_code(request):
    is_json = bool(request.content_type and "application/json" in request.content_type)
    if is_json:
        data = json.loads(request.body or "{}")
    else:
        data = request.POST

    code = (data.get("code") or "").strip()
    signup_user = _get_signup_user(request)

    if not signup_user:
        if is_json:
            return JsonResponse({"success": False, "message": "Create account first."}, status=400)
        messages.error(request, "Create account first.")
        return _signup_step_redirect(request, 1)

    if not code:
        if is_json:
            return JsonResponse({"success": False, "message": "Verification code is required."}, status=400)
        messages.error(request, "Verification code is required.")
        return _signup_step_redirect(request, 2)

    sent_at = signup_user.email_code_sent_at
    if not signup_user.email_verification_code or not sent_at:
        if is_json:
            return JsonResponse({"success": False, "message": "No OTP found. Send code first."}, status=400)
        messages.error(request, "No OTP found. Send code first.")
        return _signup_step_redirect(request, 2)

    if timezone.now() - sent_at > timedelta(minutes=10):
        if is_json:
            return JsonResponse({"success": False, "message": "OTP expired. Send a new code."}, status=400)
        messages.error(request, "OTP expired. Send a new code.")
        return _signup_step_redirect(request, 2)

    if code != signup_user.email_verification_code:
        if is_json:
            return JsonResponse({"success": False, "message": "Invalid code"}, status=400)
        messages.error(request, "Invalid code.")
        return _signup_step_redirect(request, 2)

    signup_user.is_email_verified = True
    signup_user.email_verification_code = ""
    signup_user.email_code_sent_at = None
    signup_user.save(update_fields=["is_email_verified", "email_verification_code", "email_code_sent_at"])

    request.session["verified_signup_user_id"] = signup_user.id
    request.session["verified_email"] = signup_user.email

    if is_json:
        return JsonResponse({"success": True, "message": "Email verified"})

    messages.success(request, "Email verified successfully.")
    return _signup_step_redirect(request, 3)


def forgot_password(request):
    reset_step = request.session.get("reset_step", "email")
    reset_email = request.session.get("reset_email", "")
    return render(request, "auth/forgot-password.html", {
        "reset_step": reset_step,
        "reset_email": reset_email,
    })


@require_POST
def forgot_password_send_code(request):
    is_json = request.content_type == "application/json"
    if is_json:
        data = json.loads(request.body or "{}")
    else:
        data = request.POST
    email = (data.get("email") or "").strip().lower()
    if not email:
        if is_json:
            return JsonResponse({"success": False, "message": "Email is required"}, status=400)
        messages.error(request, "Email is required.")
        return redirect("forgot_password")

    user = User.objects.filter(email=email).first()
    if not user:
        if is_json:
            return JsonResponse({"success": True, "message": "If this email exists, a code has been sent."})
        messages.success(request, "If this email exists, a code has been sent.")
        return redirect("forgot_password")

    code = str(random.randint(100000, 999999))
    request.session["reset_email"] = email
    request.session["reset_code"] = code
    request.session["reset_sent_at"] = timezone.now().isoformat()
    request.session["reset_verified"] = False
    request.session["reset_step"] = "otp"
    request.session.modified = True

    try:
        send_email(
            email,
            "Password Reset Code",
            f"Your password reset code is {code}",
            fail_silently=False,
        )
    except Exception as exc:
        if is_json:
            return JsonResponse({
                "success": False,
                "message": "Failed to send reset email. Check email settings.",
                "error": str(exc),
            }, status=500)
        messages.error(request, "Failed to send reset email. Check email settings.")
        return redirect("forgot_password")

    if is_json:
        return JsonResponse({"success": True, "message": "Verification code sent."})
    messages.success(request, "Verification code sent.")
    return redirect("forgot_password")


@require_POST
def forgot_password_verify_code(request):
    is_json = request.content_type == "application/json"
    if is_json:
        data = json.loads(request.body or "{}")
    else:
        data = request.POST
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    session_email = request.session.get("reset_email")
    session_code = request.session.get("reset_code")
    sent_at_raw = request.session.get("reset_sent_at")

    if not session_email or not session_code or not sent_at_raw:
        if is_json:
            return JsonResponse({"success": False, "message": "No reset code found. Send code first."}, status=400)
        messages.error(request, "No reset code found. Send code first.")
        return redirect("forgot_password")

    try:
        sent_at = datetime.fromisoformat(sent_at_raw)
    except ValueError:
        if is_json:
            return JsonResponse({"success": False, "message": "Invalid reset session. Send code again."}, status=400)
        messages.error(request, "Invalid reset session. Send code again.")
        return redirect("forgot_password")

    if timezone.now() - sent_at > timedelta(minutes=10):
        if is_json:
            return JsonResponse({"success": False, "message": "Reset code expired. Send a new code."}, status=400)
        messages.error(request, "Reset code expired. Send a new code.")
        return redirect("forgot_password")

    if email == session_email and code == session_code:
        request.session["reset_verified"] = True
        request.session["reset_step"] = "reset"
        if is_json:
            return JsonResponse({"success": True, "message": "Code verified"})
        messages.success(request, "Code verified. Set your new password.")
        return redirect("forgot_password")

    if is_json:
        return JsonResponse({"success": False, "message": "Invalid code"}, status=400)
    messages.error(request, "Invalid code.")
    return redirect("forgot_password")


@require_POST
def forgot_password_reset(request):
    is_json = request.content_type == "application/json"
    if is_json:
        data = json.loads(request.body or "{}")
    else:
        data = request.POST
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not email:
        if is_json:
            return JsonResponse({"success": False, "message": "Email is required"}, status=400)
        messages.error(request, "Email is required.")
        return redirect("forgot_password")

    if password != confirm_password:
        if is_json:
            return JsonResponse({"success": False, "message": "Passwords do not match"}, status=400)
        messages.error(request, "Passwords do not match.")
        return redirect("forgot_password")

    if not (any(c.isupper() for c in password) and any(c.isdigit() for c in password) and any(not c.isalnum() for c in password)):
        if is_json:
            return JsonResponse({"success": False, "message": "Password must include uppercase, number, and special character"}, status=400)
        messages.error(request, "Password must include uppercase, number, and special character.")
        return redirect("forgot_password")

    if request.session.get("reset_verified") is not True or request.session.get("reset_email") != email:
        if is_json:
            return JsonResponse({"success": False, "message": "Reset not verified"}, status=400)
        messages.error(request, "Reset not verified.")
        return redirect("forgot_password")

    user = User.objects.filter(email=email).first()
    if not user:
        if is_json:
            return JsonResponse({"success": False, "message": "User not found"}, status=404)
        messages.error(request, "User not found.")
        return redirect("forgot_password")

    user.set_password(password)
    user.save(update_fields=["password"])

    request.session.pop("reset_email", None)
    request.session.pop("reset_code", None)
    request.session.pop("reset_sent_at", None)
    request.session.pop("reset_verified", None)
    request.session.pop("reset_step", None)

    if is_json:
        return JsonResponse({"success": True, "message": "Password reset successful"})
    messages.success(request, "Password reset successful. Please login.")
    return redirect("login")


def shopboy_login(request):
    if request.session.get("shopboy_id"):
        return redirect("shopboy_dashboard")

    if request.method == "POST":
        shop_code = (request.POST.get("shop_code") or "").strip().upper()
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        if not shop_code:
            messages.error(request, "Shop code is required.")
            return render(request, "shopboy/shopboy-login.html")

        owner = User.objects.filter(shop_code__iexact=shop_code).first()
        if not owner:
            messages.error(request, "Invalid shop code.")
            return render(request, "shopboy/shopboy-login.html")

        shopboy = ShopBoy.objects.filter(
            username__iexact=username,
            is_active=True,
            user=owner,
        ).select_related("user").first()
        if not shopboy:
            messages.error(request, "Invalid username or password.")
            return render(request, "shopboy/shopboy-login.html")

        valid = check_password(password, shopboy.password) or (shopboy.password == password)
        if not valid:
            messages.error(request, "Invalid username or password.")
            return render(request, "shopboy/shopboy-login.html")

        request.session["shopboy_id"] = shopboy.id
        request.session["shopboy_owner_id"] = shopboy.user_id
        request.session["shopboy_name"] = shopboy.full_name
        return redirect("shopboy_dashboard")

    return render(request, "shopboy/shopboy-login.html")


def shopboy_logout(request):
    request.session.pop("shopboy_id", None)
    request.session.pop("shopboy_owner_id", None)
    request.session.pop("shopboy_name", None)
    return redirect("shopboy_login")


def shopboy_profile(request):
    shopboy_id = request.session.get("shopboy_id")
    if not shopboy_id:
        return redirect("shopboy_login")

    shopboy = get_object_or_404(ShopBoy.objects.select_related("user"), id=shopboy_id, is_active=True)
    context = {
        "shopboy": shopboy,
        "owner": shopboy.user,
    }
    return render(request, "shopboy/shop-profile.html", context)


def shopboy_dashboard(request):
    shopboy_id = request.session.get("shopboy_id")
    if not shopboy_id:
        return redirect("shopboy_login")

    shopboy = get_object_or_404(ShopBoy.objects.select_related("user"), id=shopboy_id, is_active=True)
    category_id = (request.GET.get("category") or "").strip()
    products = Product.objects.filter(user=shopboy.user).order_by("name")
    if category_id:
        products = products.filter(category_id=category_id)
    categories = Category.objects.filter(user=shopboy.user).order_by("name")
    cart = request.session.get("shopboy_cart", {})
    total = sum(
        (Decimal(str(item["price"])) * _cart_quantity(item) for item in cart.values()),
        Decimal("0.00"),
    )

    last_sale_id = request.session.get("shopboy_last_sale_id")
    last_sale = None
    if last_sale_id:
        last_sale = Sale.objects.filter(user=shopboy.user, handled_by_shopboy=shopboy, id=last_sale_id).first()
        if not last_sale:
            request.session.pop("shopboy_last_sale_id", None)

    return render(request, "shopboy/shopboy-dashboard.html", {
        "shopboy": shopboy,
        "owner": shopboy.user,
        "products": products,
        "categories": categories,
        "selected_category": category_id,
        "cart": cart,
        "cart_total": total.quantize(Decimal("0.01")),
        "last_sale": last_sale,
    })


@require_POST
def shopboy_add_to_cart(request, product_id):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    product = get_object_or_404(Product, id=product_id, user=shopboy.user)
    qty_raw = request.POST.get("quantity")
    cart = request.session.get("shopboy_cart", {})
    product_key = str(product_id)

    if product.stock <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect("shopboy_dashboard")

    try:
        qty = _parse_quantity(qty_raw, default=Decimal("1"))
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
        return redirect("shopboy_dashboard")

    current_qty = _cart_quantity(cart.get(product_key, {}))
    desired_qty = current_qty + qty
    if desired_qty > product.stock:
        desired_qty = product.stock
        messages.warning(request, f"Only {product.stock} units available for {product.name}.")

    if product_key in cart:
        cart[product_key]["quantity"] = _format_quantity(desired_qty)
    else:
        cart[product_key] = {
            "name": product.name,
            "price": float(product.selling_price),
            "cost": float(product.cost_price),
            "quantity": _format_quantity(desired_qty),
        }

    request.session["shopboy_cart"] = cart
    return redirect("shopboy_dashboard")

@require_POST
def shopboy_add_to_cart_by_code(request):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    code = (request.POST.get("code") or "").strip()
    qty_raw = request.POST.get("quantity")

    if not code:
        messages.error(request, "Enter a product code.")
        return redirect("shopboy_dashboard")

    try:
        qty = _parse_quantity(qty_raw, default=Decimal("1"))
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
        return redirect("shopboy_dashboard")

    product = Product.objects.filter(user=shopboy.user, code__iexact=code).first()
    if not product:
        messages.error(request, f"No product found for code {code}.")
        return redirect("shopboy_dashboard")

    if product.stock <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect("shopboy_dashboard")

    cart = request.session.get("shopboy_cart", {})
    product_key = str(product.id)

    current_qty = _cart_quantity(cart.get(product_key, {}))
    desired_qty = current_qty + qty
    if desired_qty > product.stock:
        desired_qty = product.stock
        messages.warning(request, f"Only {product.stock} units available for {product.name}.")

    if product_key in cart:
        cart[product_key]["quantity"] = _format_quantity(desired_qty)
    else:
        cart[product_key] = {
            "name": product.name,
            "price": float(product.selling_price),
            "cost": float(product.cost_price),
            "quantity": _format_quantity(desired_qty),
        }

    request.session["shopboy_cart"] = cart
    return redirect("shopboy_dashboard")


@require_POST
def shopboy_update_cart(request, product_id):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    cart = request.session.get("shopboy_cart", {})
    product_id = str(product_id)
    action = request.POST.get("action") or ""
    quantity_raw = request.POST.get("quantity")

    if product_id in cart:
        product = get_object_or_404(Product, id=product_id, user=shopboy.user)

        if action == "increase":
            current_qty = _cart_quantity(cart[product_id])
            desired_qty = current_qty + Decimal("1")
            if desired_qty <= product.stock:
                cart[product_id]["quantity"] = _format_quantity(desired_qty)
            else:
                messages.warning(request, f"Cannot add more than available stock ({product.stock}).")
        elif action == "decrease":
            current_qty = _cart_quantity(cart[product_id])
            desired_qty = current_qty - Decimal("1")
            if desired_qty <= 0:
                del cart[product_id]
            else:
                cart[product_id]["quantity"] = _format_quantity(desired_qty)
        elif action == "set" or (action not in ("increase", "decrease") and quantity_raw not in (None, "")):
            try:
                quantity = _parse_quantity_allow_zero(quantity_raw)
            except (TypeError, ValueError):
                messages.error(request, "Please enter a valid quantity (e.g., 1 or 1.5).")
            else:
                if quantity <= 0:
                    del cart[product_id]
                elif quantity > product.stock:
                    cart[product_id]["quantity"] = _format_quantity(product.stock)
                    messages.warning(request, f"Only {product.stock} units available for {product.name}.")
                else:
                    cart[product_id]["quantity"] = _format_quantity(quantity)

    request.session["shopboy_cart"] = cart
    return redirect("shopboy_dashboard")


@require_POST
def shopboy_remove_from_cart(request, product_id):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    cart = request.session.get("shopboy_cart", {})
    cart.pop(str(product_id), None)
    request.session["shopboy_cart"] = cart
    return redirect("shopboy_dashboard")


@require_POST
def shopboy_checkout(request):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")

    cart = request.session.get("shopboy_cart", {})
    if not cart:
        messages.warning(request, "Cart is empty.")
        return redirect("shopboy_dashboard")

    product_ids = [int(pid) for pid in cart.keys()]

    total_amount = Decimal("0.00")
    total_profit = Decimal("0.00")
    line_items = []

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(user=shopboy.user, id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        for pid, item in cart.items():
            product = product_map.get(pid)
            if not product:
                messages.error(request, "A cart item no longer exists.")
                return redirect("shopboy_dashboard")

            quantity = _cart_quantity(item)
            if quantity <= 0:
                continue

            if product.stock < quantity:
                messages.error(request, f"Not enough stock for {product.name}. Available: {product.stock}.")
                return redirect("shopboy_dashboard")

            price = Decimal(str(item["price"]))
            cost = Decimal(str(item["cost"]))
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
            messages.warning(request, "Cart is empty.")
            return redirect("shopboy_dashboard")

        sale = Sale.objects.create(
            user=shopboy.user,
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
            row["product"].stock -= row["quantity"]
            row["product"].save(update_fields=["stock"])

    request.session["shopboy_cart"] = {}
    request.session["shopboy_last_sale_id"] = sale.id
    messages.success(request, "Sale completed successfully.")
    return redirect("shopboy_dashboard")


@require_POST
def shopboy_sell_product(request, product_id):
    shopboy_id = request.session.get("shopboy_id")
    if not shopboy_id:
        return redirect("shopboy_login")

    shopboy = get_object_or_404(ShopBoy.objects.select_related("user"), id=shopboy_id, is_active=True)

    try:
        qty = _parse_quantity(request.POST.get("quantity", 1), default=Decimal("1"))
    except (TypeError, ValueError):
        messages.error(request, "Invalid quantity.")
        return redirect("shopboy_dashboard")

    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), id=product_id, user=shopboy.user)

        if product.stock < qty:
            messages.error(request, f"Not enough stock for {product.name}. Available: {product.stock}.")
            return redirect("shopboy_dashboard")

        total_amount = product.selling_price * qty
        total_profit = (product.selling_price - product.cost_price) * qty
        vat_registered = _vat_registered_for_sale(shopboy.user, timezone.now(), total_amount)
        vat_status, vat_applicable, vat_rate, vat_amount = _calculate_item_vat(
            product,
            total_amount,
            vat_registered,
        )

        sale = Sale.objects.create(
            user=shopboy.user,
            sales_channel=Sale.CHANNEL_SHOPBOY_PORTAL,
            handled_by_shopboy=shopboy,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_profit=total_profit.quantize(Decimal("0.01")),
            vat_total=vat_amount.quantize(Decimal("0.01")),
            amount_paid=total_amount.quantize(Decimal("0.01")),
            payment_status=Sale.PAYMENT_PAID,
        )

        SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=qty,
            price=product.selling_price.quantize(Decimal("0.01")),
            profit=total_profit.quantize(Decimal("0.01")),
            vat_status=vat_status,
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            vat_applicable=vat_applicable,
        )

        product.stock -= qty
        product.save(update_fields=["stock"])

    request.session["shopboy_last_sale_id"] = sale.id
    messages.success(request, f"Sold {_format_quantity(qty)} x {product.name}.")
    return redirect("shopboy_dashboard")




# =============================
# Admin Portal
# =============================

def _admin_portal_check(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def admin_portal_login(request):
    if request.user.is_authenticated and _admin_portal_check(request.user):
        return redirect("admin_portal")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""

        user = _authenticate_with_identifier(request, email, password)
        if not user:
            messages.error(request, "Invalid email/username or password")
            return render(request, "admin/admin-login.html")

        if not _admin_portal_check(user):
            messages.error(request, "You do not have access to the admin portal")
            return render(request, "admin/admin-login.html")

        login(request, user)
        return redirect("admin_portal")

    return render(request, "admin/admin-login.html")


def admin_portal_logout(request):
    logout(request)
    return redirect("admin_portal_login")


@user_passes_test(_admin_portal_check, login_url="admin_portal_login")
def admin_portal(request):
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_sales = Sale.objects.filter(created_at__gte=month_start)
    month_revenue = month_sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    month_profit = month_sales.aggregate(total=Sum("total_profit"))["total"] or Decimal("0.00")

    today = timezone.localdate()
    subscription_revenue = (
        User.objects.filter(
            subscription_active_until__gte=today,
            is_paid=True,
            is_staff=False,
            is_superuser=False,
            account_type=User.ACCOUNT_TYPE_SHOP,
        )
        .aggregate(total=Sum("monthly_fee"))["total"]
        or Decimal("0.00")
    )

    active_shops = User.objects.filter(is_active=True, is_paid=True, account_type=User.ACCOUNT_TYPE_SHOP).count()
    total_shops = User.objects.filter(account_type=User.ACCOUNT_TYPE_SHOP).count()
    total_products = Product.objects.count()
    total_orders = MarketplaceOrder.objects.count()

    recent_users = User.objects.filter(account_type=User.ACCOUNT_TYPE_SHOP).order_by("-date_joined")[:5]
    investors = Investor.objects.order_by("-created_at")
    feedbacks = Feedback.objects.order_by("-created_at")[:50]
    for investor in investors:
        ownership_ratio = (investor.ownership_percent or Decimal("0")) / Decimal("100")
        investor.monthly_return = (subscription_revenue * ownership_ratio).quantize(Decimal("0.01"))

    return render(request, "admin/admin.html", {
        "month_revenue": month_revenue,
        "month_profit": month_profit,
        "subscription_revenue": subscription_revenue,
        "active_shops": active_shops,
        "total_shops": total_shops,
        "total_products": total_products,
        "total_orders": total_orders,
        "recent_users": recent_users,
        "investors": investors,
        "feedbacks": feedbacks,
    })


@user_passes_test(_admin_portal_check, login_url="admin_portal_login")
@require_POST
def admin_portal_add_investor(request):
    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip().lower()
    password = request.POST.get("password") or ""
    investment_amount = request.POST.get("investment_amount") or "0"
    ownership_percent = request.POST.get("ownership_percent") or "0"
    is_active = bool(request.POST.get("is_active"))

    if not name or not email or not password:
        messages.error(request, "Name, email, and password are required.")
        return redirect("admin_portal")

    if Investor.objects.filter(email__iexact=email).exists():
        messages.error(request, "An investor with this email already exists.")
        return redirect("admin_portal")

    try:
        investment_amount = Decimal(investment_amount)
        ownership_percent = Decimal(ownership_percent)
    except Exception:
        messages.error(request, "Invalid investment or ownership value.")
        return redirect("admin_portal")

    if investment_amount < 0 or ownership_percent < 0 or ownership_percent > 100:
        messages.error(request, "Investment must be >= 0 and ownership must be between 0 and 100.")
        return redirect("admin_portal")

    Investor.objects.create(
        name=name,
        email=email,
        password=password,
        investment_amount=investment_amount,
        ownership_percent=ownership_percent,
        is_active=is_active,
    )
    messages.success(request, "Investor created.")
    return redirect("admin_portal")


@user_passes_test(_admin_portal_check, login_url="admin_portal_login")
@require_POST
def admin_portal_delete_investor(request, pk):
    investor = get_object_or_404(Investor, pk=pk)
    investor.delete()
    messages.success(request, "Investor deleted.")
    return redirect("admin_portal")


@user_passes_test(_admin_portal_check, login_url="admin_portal_login")
@require_POST
def admin_portal_toggle_investor(request, pk):
    investor = get_object_or_404(Investor, pk=pk)
    investor.is_active = not investor.is_active
    investor.save(update_fields=["is_active"])
    messages.success(request, "Investor status updated.")
    return redirect("admin_portal")

# =============================
# Marketplace Helpers
# =============================
def _generate_shop_code():
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "SHOP-" + "".join(random.choices(alphabet, k=6))
        if not User.objects.filter(shop_code=code).exists():
            return code
    return "SHOP-" + "".join(random.choices(alphabet, k=8))


def _ensure_shop_code(user):
    if not user.shop_code:
        user.shop_code = _generate_shop_code()
        user.save(update_fields=["shop_code"])
    return user.shop_code


def _get_shopboy_session(request):
    shopboy_id = request.session.get("shopboy_id")
    if not shopboy_id:
        return None
    return ShopBoy.objects.filter(id=shopboy_id, is_active=True).select_related("user").first()


def _get_marketplace_settings(user):
    settings_obj, _ = MarketplaceSettings.objects.get_or_create(user=user)
    return settings_obj


def _ensure_marketplace_profiles():
    shop_owner_ids = list(
        User.objects.filter(is_active=True, account_type=User.ACCOUNT_TYPE_SHOP)
        .values_list("id", flat=True)
        .distinct()
    )
    if not shop_owner_ids:
        return

    existing_ids = set(
        MarketplaceShopProfile.objects.filter(user_id__in=shop_owner_ids)
        .values_list("user_id", flat=True)
    )
    missing_profiles = [
        MarketplaceShopProfile(user_id=user_id)
        for user_id in shop_owner_ids
        if user_id not in existing_ids
    ]
    if missing_profiles:
        MarketplaceShopProfile.objects.bulk_create(missing_profiles)


def _get_assigned_shopboy(user):
    settings_obj = _get_marketplace_settings(user)
    assigned = settings_obj.assigned_shopboy
    if assigned and assigned.is_active and assigned.can_use_marketplace and assigned.user_id == user.id:
        return assigned
    fallback = ShopBoy.objects.filter(user=user, is_active=True, can_use_marketplace=True).order_by("id").first()
    return fallback


def _get_marketplace_buyer(request):
    buyer_id = request.session.get("marketplace_buyer_id")
    if not buyer_id:
        return None
    buyer = MarketplaceBuyer.objects.filter(id=buyer_id, is_active=True).first()
    if not _marketplace_buyer_is_fully_verified(buyer):
        return None
    return buyer


def _get_pending_marketplace_buyer(request):
    buyer_id = request.session.get("marketplace_pending_buyer_id")
    if not buyer_id:
        return None
    return MarketplaceBuyer.objects.filter(id=buyer_id).first()


def _get_marketplace_next_url(request):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url.startswith("/"):
        return next_url
    return ""


def _login_marketplace_buyer(request, buyer):
    request.session["marketplace_buyer_id"] = buyer.id
    request.session["marketplace_buyer_email"] = buyer.email


def _logout_marketplace_buyer(request):
    request.session.pop("marketplace_buyer_id", None)
    request.session.pop("marketplace_buyer_email", None)
    request.session.pop("marketplace_pending_buyer_id", None)


def _get_marketplace_web_token(buyer):
    now = timezone.now()
    token_obj = (
        MarketplaceBuyerToken.objects.filter(
            buyer=buyer,
            is_revoked=False,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("-created_at")
        .first()
    )
    if token_obj:
        token_obj.last_used_at = now
        token_obj.save(update_fields=["last_used_at"])
        return token_obj

    return MarketplaceBuyerToken.objects.create(
        buyer=buyer,
        token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(days=30),
        last_used_at=now,
    )


def _marketplace_buyer_needs_phone_verification(buyer):
    return False


def _marketplace_buyer_is_fully_verified(buyer):
    if not buyer or not buyer.is_email_verified:
        return False
    if _marketplace_buyer_needs_phone_verification(buyer) and not buyer.is_phone_verified:
        return False
    return True


def _marketplace_default_dashboard_name(buyer):
    return "marketplace_home"


def _marketplace_dashboard_redirect(request, buyer, next_url=""):
    destination = next_url or request.session.pop("marketplace_next_url", "")
    if destination:
        return redirect(destination)
    return redirect(_marketplace_default_dashboard_name(buyer))


def _redirect_to_marketplace_login(request, fallback_next_name=None):
    next_url = _get_marketplace_next_url(request)
    if not next_url:
        next_url = request.get_full_path()
    if (not next_url or not next_url.startswith("/")) and fallback_next_name:
        next_url = reverse(fallback_next_name)
    login_url = reverse("marketplace_login")
    if next_url and next_url.startswith("/"):
        return redirect(f"{login_url}?next={next_url}")
    return redirect("marketplace_login")


def _send_marketplace_verification_code(buyer):
    code = str(random.randint(100000, 999999))
    buyer.email_verification_code = code
    buyer.email_code_sent_at = timezone.now()
    buyer.save(update_fields=["email_verification_code", "email_code_sent_at"])

    send_email(
        buyer.email,
        "Your Marketplace verification code",
        f"Your verification code is {code}. It will expire in 10 minutes.",
        fail_silently=False,
    )


def _send_marketplace_pending_verification_codes(buyer):
    if not buyer.is_email_verified:
        _send_marketplace_verification_code(buyer)


def _send_marketplace_reset_code(buyer):
    code = str(random.randint(100000, 999999))
    buyer.reset_code = code
    buyer.reset_sent_at = timezone.now()
    buyer.save(update_fields=["reset_code", "reset_sent_at"])

    send_email(
        buyer.email,
        "Marketplace password reset code",
        f"Your password reset code is {code}. It will expire in 10 minutes.",
        fail_silently=False,
    )


def _order_access_context(request, order):
    shopboy = _get_shopboy_session(request)
    is_seller = False
    if shopboy and shopboy.user_id == order.shop_owner_id and shopboy.can_use_marketplace:
        is_seller = True
    if request.user.is_authenticated and request.user.id == order.shop_owner_id:
        is_seller = True

    buyer = _get_marketplace_buyer(request)
    is_buyer = bool(buyer and order.buyer_id == buyer.id)
    access_token = request.GET.get("access") or request.POST.get("access") or ""
    if not is_buyer:
        is_buyer = str(order.access_token) == access_token
    return is_seller, is_buyer


def _house_inquiry_access_context(request, inquiry):
    is_seller = False
    if request.user.is_authenticated and inquiry.owner_id and request.user.id == inquiry.owner_id:
        is_seller = True

    agent = _get_agent_session(request)
    if agent and inquiry.house_id:
        if inquiry.house.listing_agent_id == agent.id or inquiry.house.managed_by_agent_id == agent.id:
            is_seller = True

    buyer = _get_marketplace_buyer(request)
    is_buyer = bool(buyer and inquiry.buyer_id == buyer.id)
    access_token = request.GET.get("access") or request.POST.get("access") or ""
    if not is_buyer:
        is_buyer = str(inquiry.access_token) == access_token
    return is_seller, is_buyer


# =============================
# Marketplace Views
# =============================
def marketplace_login(request):
    buyer = _get_marketplace_buyer(request)
    if buyer:
        next_url = _get_marketplace_next_url(request)
        return _marketplace_dashboard_redirect(request, buyer, next_url)

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        next_url = _get_marketplace_next_url(request)

        if not email or not password:
            messages.error(request, "Email and password are required.")
            return render(request, "shopboy/marketplace-login.html", {"next_url": next_url})

        buyer = MarketplaceBuyer.objects.filter(email__iexact=email).first()
        if not buyer or not check_password(password, buyer.password):
            messages.error(request, "Invalid email or password.")
            return render(request, "shopboy/marketplace-login.html", {"next_url": next_url})

        if not buyer.is_active and _marketplace_buyer_is_fully_verified(buyer):
            messages.error(request, "This marketplace account is inactive.")
            return render(request, "shopboy/marketplace-login.html", {"next_url": next_url})

        if not _marketplace_buyer_is_fully_verified(buyer):
            request.session["marketplace_pending_buyer_id"] = buyer.id
            if next_url:
                request.session["marketplace_next_url"] = next_url
            try:
                _send_marketplace_pending_verification_codes(buyer)
            except Exception:
                messages.error(request, "Could not send verification codes. Please try again.")
                return render(request, "shopboy/marketplace-login.html", {"next_url": next_url})
            messages.success(request, "Verify your email to continue. We sent you a code.")
            return redirect("marketplace_verify")

        buyer.last_login = timezone.now()
        buyer.save(update_fields=["last_login"])
        _login_marketplace_buyer(request, buyer)
        return _marketplace_dashboard_redirect(request, buyer, next_url)

    return render(request, "shopboy/marketplace-login.html", {
        "next_url": _get_marketplace_next_url(request),
    })


def marketplace_signup(request):
    buyer = _get_marketplace_buyer(request)
    if buyer:
        next_url = _get_marketplace_next_url(request)
        return _marketplace_dashboard_redirect(request, buyer, next_url)

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        next_url = _get_marketplace_next_url(request)

        if not email or not password or not confirm_password:
            messages.error(request, "Email and passwords are required.")
            return render(request, "shopboy/marketplace-signup.html", {"next_url": next_url})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "shopboy/marketplace-signup.html", {"next_url": next_url})

        if not _password_meets_rules(password):
            messages.error(request, "Password must include uppercase, number, and special character.")
            return render(request, "shopboy/marketplace-signup.html", {"next_url": next_url})

        if MarketplaceBuyer.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email already registered. Please sign in.")
            return render(request, "shopboy/marketplace-signup.html", {"next_url": next_url})

        buyer = MarketplaceBuyer.objects.create(
            email=email,
            password=make_password(password),
        )
        request.session["marketplace_pending_buyer_id"] = buyer.id
        if next_url:
            request.session["marketplace_next_url"] = next_url
        try:
            _send_marketplace_verification_code(buyer)
        except Exception:
            messages.error(request, "Account created, but we could not send verification email. Try again.")
            return render(request, "shopboy/marketplace-signup.html", {"next_url": next_url})
        messages.success(request, "Account created. Verify your email to continue.")
        return redirect("marketplace_verify")

    return render(request, "shopboy/marketplace-signup.html", {
        "next_url": _get_marketplace_next_url(request),
    })


def marketplace_logout(request):
    _logout_marketplace_buyer(request)
    return redirect("marketplace")


def marketplace_verify(request):
    buyer = _get_pending_marketplace_buyer(request)
    if not buyer:
        return redirect("marketplace_login")

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if not code:
            messages.error(request, "Verification code is required.")
            return render(request, "shopboy/marketplace-verify.html", {"buyer": buyer})

        sent_at = buyer.email_code_sent_at
        if not buyer.email_verification_code or not sent_at:
            messages.error(request, "No OTP found. Send code first.")
            return render(request, "shopboy/marketplace-verify.html", {"buyer": buyer})

        if timezone.now() - sent_at > timedelta(minutes=10):
            messages.error(request, "OTP expired. Send a new code.")
            return render(request, "shopboy/marketplace-verify.html", {"buyer": buyer})

        if code != buyer.email_verification_code:
            messages.error(request, "Invalid code.")
            return render(request, "shopboy/marketplace-verify.html", {"buyer": buyer})

        buyer.is_email_verified = True
        buyer.email_verification_code = ""
        buyer.email_code_sent_at = None
        buyer.last_login = timezone.now()
        buyer.save(update_fields=["is_email_verified", "email_verification_code", "email_code_sent_at", "last_login"])

        request.session.pop("marketplace_pending_buyer_id", None)
        _login_marketplace_buyer(request, buyer)
        messages.success(request, "Email verified successfully.")
        return _marketplace_dashboard_redirect(request, buyer)

    return render(request, "shopboy/marketplace-verify.html", {"buyer": buyer})


@require_POST
def marketplace_send_verification_code(request):
    buyer = _get_pending_marketplace_buyer(request)
    if not buyer:
        return redirect("marketplace_login")

    try:
        _send_marketplace_pending_verification_codes(buyer)
    except Exception:
        messages.error(request, "Failed to send verification codes. Please try again.")
        return redirect("marketplace_verify")

    messages.success(request, f"Code sent to {buyer.email}.")
    return redirect("marketplace_verify")


def marketplace_forgot_password(request):
    reset_step = request.session.get("marketplace_reset_step", "email")
    reset_email = request.session.get("marketplace_reset_email", "")
    return render(request, "shopboy/marketplace-forgot-password.html", {
        "reset_step": reset_step,
        "reset_email": reset_email,
    })


@require_POST
def marketplace_forgot_password_send_code(request):
    email = (request.POST.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "Email is required.")
        return redirect("marketplace_forgot_password")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer:
        messages.success(request, "If this email exists, a code has been sent.")
        return redirect("marketplace_forgot_password")

    request.session["marketplace_reset_email"] = email
    request.session["marketplace_reset_step"] = "otp"
    request.session["marketplace_reset_verified"] = False
    request.session.modified = True

    try:
        _send_marketplace_reset_code(buyer)
    except Exception:
        messages.error(request, "Failed to send reset email. Check email settings.")
        return redirect("marketplace_forgot_password")

    messages.success(request, "Verification code sent.")
    return redirect("marketplace_forgot_password")


@require_POST
def marketplace_forgot_password_verify_code(request):
    email = (request.POST.get("email") or "").strip().lower()
    code = (request.POST.get("code") or "").strip()

    session_email = request.session.get("marketplace_reset_email")
    if not session_email or email != session_email:
        messages.error(request, "No reset code found. Send code first.")
        return redirect("marketplace_forgot_password")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer or not buyer.reset_code or not buyer.reset_sent_at:
        messages.error(request, "No reset code found. Send code first.")
        return redirect("marketplace_forgot_password")

    if timezone.now() - buyer.reset_sent_at > timedelta(minutes=10):
        messages.error(request, "Reset code expired. Send a new code.")
        return redirect("marketplace_forgot_password")

    if code != buyer.reset_code:
        messages.error(request, "Invalid code.")
        return redirect("marketplace_forgot_password")

    request.session["marketplace_reset_verified"] = True
    request.session["marketplace_reset_step"] = "reset"
    messages.success(request, "Code verified. Set your new password.")
    return redirect("marketplace_forgot_password")


@require_POST
def marketplace_forgot_password_reset(request):
    email = (request.POST.get("email") or "").strip().lower()
    password = request.POST.get("password") or ""
    confirm_password = request.POST.get("confirm_password") or ""

    if not email:
        messages.error(request, "Email is required.")
        return redirect("marketplace_forgot_password")

    if password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return redirect("marketplace_forgot_password")

    if not _password_meets_rules(password):
        messages.error(request, "Password must include uppercase, number, and special character.")
        return redirect("marketplace_forgot_password")

    if request.session.get("marketplace_reset_verified") is not True or request.session.get("marketplace_reset_email") != email:
        messages.error(request, "Reset not verified.")
        return redirect("marketplace_forgot_password")

    buyer = MarketplaceBuyer.objects.filter(email__iexact=email, is_active=True).first()
    if not buyer:
        messages.error(request, "Account not found.")
        return redirect("marketplace_forgot_password")

    buyer.password = make_password(password)
    buyer.reset_code = ""
    buyer.reset_sent_at = None
    buyer.save(update_fields=["password", "reset_code", "reset_sent_at"])

    request.session.pop("marketplace_reset_email", None)
    request.session.pop("marketplace_reset_step", None)
    request.session.pop("marketplace_reset_verified", None)

    messages.success(request, "Password reset successful. Please sign in.")
    return redirect("marketplace_login")


def marketplace_account(request):
    buyer = _get_marketplace_buyer(request)
    if not buyer:
        pending = _get_pending_marketplace_buyer(request)
        if pending and not pending.is_email_verified:
            return redirect("marketplace_verify")
        return _redirect_to_marketplace_login(request, "marketplace_account")

    orders = (
        MarketplaceOrder.objects.filter(buyer=buyer)
        .select_related("shop_owner")
        .order_by("-created_at")
    )
    house_inquiries = (
        HouseInquiry.objects.filter(buyer=buyer)
        .select_related("house", "owner")
        .order_by("-updated_at", "-created_at")
    )

    return render(request, "shopboy/marketplace-account.html", {
        "buyer": buyer,
        "orders": orders,
        "house_inquiries": house_inquiries,
        "marketplace_portal_role": "customer",
        "marketplace_active_tab": "marketplace",
    })


def marketplace_home(request):
    buyer = _get_marketplace_buyer(request)
    if not buyer:
        pending = _get_pending_marketplace_buyer(request)
        if pending and not pending.is_email_verified:
            return redirect("marketplace_verify")
        return _redirect_to_marketplace_login(request, "marketplace_home")

    buyer_token = _get_marketplace_web_token(buyer)
    orders = (
        MarketplaceOrder.objects.filter(buyer=buyer)
        .select_related("shop_owner")
        .order_by("-created_at")
    )
    house_inquiries = (
        HouseInquiry.objects.filter(buyer=buyer)
        .select_related("house", "owner")
        .order_by("-updated_at", "-created_at")
    )
    return render(request, "shopboy/marketplace-home.html", {
        "buyer": buyer,
        "buyer_api_token": buyer_token.token,
        "marketplace_portal_role": "customer",
        "recent_orders": orders[:5],
        "recent_house_inquiries": house_inquiries[:5],
        "stats": {
            "orders_count": orders.count(),
            "house_inquiries": house_inquiries.count(),
        },
        "marketplace_active_tab": "home",
    })


def marketplace_settings(request):
    return redirect("marketplace_home")


def marketplace(request):
    buyer = _get_marketplace_buyer(request)
    active_tab = (request.GET.get("tab") or "houses").strip().lower()
    if active_tab not in {"houses", "shops"}:
        active_tab = "houses"
    q = (request.GET.get("q") or "").strip()
    username_q = q[1:] if q.startswith("@") else q
    category = (request.GET.get("category") or "").strip()
    location = (request.GET.get("location") or "").strip()
    property_type = (request.GET.get("property_type") or "").strip()
    listing_mode = (request.GET.get("listing_mode") or "").strip()
    rooms_min = (request.GET.get("rooms_min") or "").strip()
    min_price = (request.GET.get("min_price") or "").strip()
    max_price = (request.GET.get("max_price") or "").strip()
    available_only = request.GET.get("available") == "1"
    verified = request.GET.get("verified") == "1"
    sort = request.GET.get("sort") or "rating"

    valid_property_types = {choice[0]: choice[1] for choice in HouseListing.PROPERTY_TYPE_CHOICES}
    valid_listing_modes = {choice[0]: choice[1] for choice in HouseListing.LISTING_MODE_CHOICES}
    if property_type and property_type not in valid_property_types:
        property_type = ""
    if listing_mode and listing_mode not in valid_listing_modes:
        listing_mode = ""

    _ensure_marketplace_profiles()

    profiles = (
        MarketplaceShopProfile.objects.select_related("user")
        .prefetch_related("user__product_set")
        .filter(user__is_active=True, user__account_type=User.ACCOUNT_TYPE_SHOP)
        .distinct()
    )
    if q:
        profiles = profiles.filter(
            Q(user__business_name__icontains=q) |
            Q(user__username__icontains=username_q) |
            Q(description__icontains=q) |
            Q(user__product_set__name__icontains=q)
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
    houses = _marketplace_house_queryset()
    if q:
        houses = houses.filter(
            Q(title__icontains=q) |
            Q(location__icontains=q) |
            Q(description__icontains=q) |
            Q(owner__business_name__icontains=q) |
            Q(owner__username__icontains=username_q) |
            Q(listing_agent__full_name__icontains=q) |
            Q(listing_agent__username__icontains=username_q)
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
            Q(owner__marketplace_profile__is_verified=True) |
            Q(owner__isnull=True, listing_agent__is_email_verified=True)
        )

    min_price_value = None
    max_price_value = None
    rooms_min_value = None
    if rooms_min:
        try:
            rooms_min_value = int(rooms_min)
            if rooms_min_value > 0:
                houses = houses.filter(rooms_count__gte=rooms_min_value)
            else:
                rooms_min = ""
        except Exception:
            rooms_min = ""
    if min_price:
        try:
            min_price_value = Decimal(min_price)
            if min_price_value < 0:
                min_price = ""
                min_price_value = None
        except (InvalidOperation, ValueError):
            min_price = ""
            min_price_value = None
    if max_price:
        try:
            max_price_value = Decimal(max_price)
            if max_price_value < 0:
                max_price = ""
                max_price_value = None
        except (InvalidOperation, ValueError):
            max_price = ""
            max_price_value = None

    if min_price_value is not None and max_price_value is not None and min_price_value > max_price_value:
        min_price_value, max_price_value = max_price_value, min_price_value
        min_price = format(min_price_value, "f")
        max_price = format(max_price_value, "f")

    if min_price_value is not None:
        houses = houses.filter(price__gte=min_price_value)
    if max_price_value is not None:
        houses = houses.filter(price__lte=max_price_value)

    if sort == "newest":
        houses = houses.order_by("-created_at")
    elif sort == "price_low":
        houses = houses.order_by("price", "-created_at")
    elif sort == "price_high":
        houses = houses.order_by("-price", "-created_at")
    else:
        houses = houses.order_by(
            Case(
                When(availability_status=HouseListing.STATUS_AVAILABLE, then=0),
                When(availability_status=HouseListing.STATUS_PARTIAL, then=1),
                default=2,
                output_field=IntegerField(),
            ),
            "-created_at",
        )

    house_locations = (
        _marketplace_house_queryset()
        .exclude(location="")
        .values_list("location", flat=True)
        .distinct()
    )
    all_locations = sorted({*locations, *house_locations})
    house_types = [choice for choice in HouseListing.PROPERTY_TYPE_CHOICES]
    listing_modes = [choice for choice in HouseListing.LISTING_MODE_CHOICES]

    return render(request, "shopboy/marketplace.html", {
        "buyer": buyer,
        "active_tab": active_tab,
        "active_result_count": houses.count() if active_tab == "houses" else profiles.count(),
        "marketplace_portal_role": "customer",
        "profiles": profiles,
        "houses": houses,
        "categories": categories,
        "locations": all_locations,
        "house_types": house_types,
        "listing_modes": listing_modes,
        "filters": {
            "q": q,
            "category": category,
            "location": location,
            "property_type": property_type,
            "property_type_label": valid_property_types.get(property_type, ""),
            "listing_mode": listing_mode,
            "listing_mode_label": valid_listing_modes.get(listing_mode, ""),
            "rooms_min": rooms_min,
            "min_price": min_price,
            "max_price": max_price,
            "available": available_only,
            "verified": verified,
            "sort": sort,
        },
        "marketplace_active_tab": "marketplace",
    })


def marketplace_house_detail(request, house_id):
    house = get_object_or_404(
        _marketplace_house_queryset().prefetch_related("rentals"),
        id=house_id,
    )
    profile = None
    if house.owner:
        profile, _ = MarketplaceShopProfile.objects.get_or_create(user=house.owner)
    active_rental = house.rentals.filter(status=RentalRecord.STATUS_ACTIVE).order_by("end_date").first()

    return render(request, "shopboy/marketplace-house.html", {
        "buyer": _get_marketplace_buyer(request),
        "house": house,
        "profile": profile,
        "shop_owner": house.owner,
        "house_agent": house.listing_agent,
        "active_rental": active_rental,
        "marketplace_active_tab": "marketplace",
    })


def _render_marketplace_housing_profile(
    request,
    *,
    houses,
    profile_title,
    profile_subtitle,
    profile_description,
    profile_location,
    cover_image_url="",
    avatar_image_url="",
    verification_label="",
    profile_username="",
):
    buyer = _get_marketplace_buyer(request)
    houses = houses.prefetch_related("images", "rentals")
    available_count = sum(1 for house in houses if house.is_available)

    return render(request, "shopboy/marketplace-housing-profile.html", {
        "buyer": buyer,
        "profile_title": profile_title,
        "profile_subtitle": profile_subtitle,
        "profile_description": profile_description,
        "profile_location": profile_location,
        "cover_image_url": cover_image_url,
        "avatar_image_url": avatar_image_url,
        "verification_label": verification_label,
        "profile_username": profile_username,
        "houses": houses,
        "available_count": available_count,
        "marketplace_active_tab": "marketplace",
    })


def marketplace_housing_profile(request, username):
    owner = get_object_or_404(
        User,
        username=username,
        is_active=True,
        account_type=User.ACCOUNT_TYPE_HOUSING,
    )
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=owner)
    houses = _marketplace_house_queryset().filter(owner=owner).order_by(
        Case(
            When(availability_status=HouseListing.STATUS_AVAILABLE, then=0),
            When(availability_status=HouseListing.STATUS_PARTIAL, then=1),
            default=2,
            output_field=IntegerField(),
        ),
        "-created_at",
    )

    return _render_marketplace_housing_profile(
        request,
        houses=houses,
        profile_title=owner.business_name or owner.username,
        profile_subtitle=f"@{owner.username}",
        profile_description=profile.description or "Browse every live house under this housing profile.",
        profile_location=profile.location or owner.state or owner.country or "Location on request",
        cover_image_url=profile.cover_image.url if profile.cover_image else "",
        avatar_image_url=owner.profile_image.url if owner.profile_image else "",
        verification_label="Verified housing profile" if profile.is_verified else "",
        profile_username=owner.username,
    )


def marketplace_housing_agent_profile(request, username):
    agent = get_object_or_404(Agent, username=username, is_active=True)
    houses = _marketplace_house_queryset().filter(
        Q(listing_agent=agent) | Q(managed_by_agent=agent)
    ).distinct().order_by(
        Case(
            When(availability_status=HouseListing.STATUS_AVAILABLE, then=0),
            When(availability_status=HouseListing.STATUS_PARTIAL, then=1),
            default=2,
            output_field=IntegerField(),
        ),
        "-created_at",
    )

    return _render_marketplace_housing_profile(
        request,
        houses=houses,
        profile_title=agent.full_name,
        profile_subtitle=f"@{agent.username}",
        profile_description="Browse every live house currently listed or managed by this housing agent.",
        profile_location=houses[0].area_label if houses else "Location on request",
        verification_label="Verified housing agent" if agent.is_email_verified else "",
        profile_username=agent.username,
    )


@require_POST
def marketplace_create_house_inquiry(request, house_id):
    house = get_object_or_404(_marketplace_house_queryset(), id=house_id)
    buyer = _get_marketplace_buyer(request)
    if not buyer:
        messages.error(request, "Please sign in to contact the house owner.")
        return redirect(f"{reverse('marketplace_login')}?next={reverse('marketplace_house_detail', kwargs={'house_id': house.id})}")

    buyer_name = (request.POST.get("buyer_name") or "").strip()
    buyer_contact = (request.POST.get("buyer_contact") or "").strip()
    inquiry_message = (request.POST.get("message") or "").strip()

    if not buyer_name or not buyer_contact:
        messages.error(request, "Your name and contact are required before you can start a chat.")
        return redirect("marketplace_house_detail", house_id=house.id)

    if not house.owner_id:
        messages.error(request, "This house does not have an owner chat account yet.")
        return redirect("marketplace_house_detail", house_id=house.id)

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
    if inquiry_message:
        HouseInquiryMessage.objects.create(
            inquiry=inquiry,
            sender_type=HouseInquiryMessage.SENDER_BUYER,
            message=inquiry_message,
        )

    url = reverse("marketplace_house_inquiry_chat", kwargs={"public_id": inquiry.public_id})
    return redirect(f"{url}?access={inquiry.access_token}")


def marketplace_shop(request, username):
    shop_owner = get_object_or_404(User, username=username)
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=shop_owner)
    products = Product.objects.filter(user=shop_owner).order_by("name")

    return render(request, "shopboy/marketplace-shop.html", {
        "buyer": _get_marketplace_buyer(request),
        "shop_owner": shop_owner,
        "profile": profile,
        "products": products,
        "marketplace_active_tab": "marketplace",
    })


@require_POST
def marketplace_place_order(request, username):
    shop_owner = get_object_or_404(User, username=username)
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=shop_owner)
    buyer = _get_marketplace_buyer(request)
    if not buyer:
        messages.error(request, "Please sign in to place an order.")
        return redirect(f"{reverse('marketplace_login')}?next={reverse('marketplace_shop', kwargs={'username': shop_owner.username})}")

    buyer_name = (request.POST.get("buyer_name") or "").strip()
    buyer_contact = (request.POST.get("buyer_contact") or "").strip()
    buyer_address = (request.POST.get("buyer_address") or "").strip()

    if not buyer_name or not buyer_contact:
        messages.error(request, "Buyer name and contact are required.")
        return redirect("marketplace_shop", username=shop_owner.username)

    products = Product.objects.filter(user=shop_owner).order_by("name")
    item_rows = []
    total_amount = Decimal("0.00")

    with transaction.atomic():
        for product in products.select_for_update():
            qty_raw = request.POST.get(f"qty_{product.id}") or "0"
            try:
                qty = int(qty_raw)
            except ValueError:
                qty = 0
            if qty <= 0:
                continue
            if product.stock < qty:
                messages.error(request, f"Not enough stock for {product.name}. Available: {product.stock}.")
                return redirect("marketplace_shop", username=shop_owner.username)

            line_total = product.selling_price * qty
            total_amount += line_total
            item_rows.append({
                "product": product,
                "quantity": qty,
                "unit_price": product.selling_price,
            })

        if not item_rows:
            messages.error(request, "Select at least one product to place an order.")
            return redirect("marketplace_shop", username=shop_owner.username)

        order = MarketplaceOrder.objects.create(
            shop_owner=shop_owner,
            buyer=buyer,
            assigned_shopboy=_get_assigned_shopboy(shop_owner),
            buyer_name=buyer_name,
            buyer_contact=buyer_contact,
            buyer_address=buyer_address,
            total_amount=total_amount.quantize(Decimal("0.01")),
        )

        for row in item_rows:
            MarketplaceOrderItem.objects.create(
                order=order,
                product=row["product"],
                quantity=row["quantity"],
                unit_price=row["unit_price"].quantize(Decimal("0.01")),
            )

        MarketplaceChatMessage.objects.create(
            order=order,
            sender_type=MarketplaceChatMessage.SENDER_SYSTEM,
            message="Order created. Waiting for confirmation."
        )

    url = reverse("marketplace_order_chat", kwargs={"public_id": order.public_id})
    return redirect(f"{url}?access={order.access_token}")


@ensure_csrf_cookie
def marketplace_order_chat(request, public_id):
    order = get_object_or_404(
        MarketplaceOrder.objects.select_related("shop_owner", "assigned_shopboy").prefetch_related("items__product", "messages"),
        public_id=public_id
    )
    is_seller, is_buyer = _order_access_context(request, order)
    if not (is_seller or is_buyer):
        return HttpResponseForbidden("You do not have access to this order.")

    messages_qs = order.messages.all().order_by("created_at")
    profile, _ = MarketplaceShopProfile.objects.get_or_create(user=order.shop_owner)

    next_map = {
        MarketplaceOrder.STATUS_PENDING: MarketplaceOrder.STATUS_CONFIRMED,
        MarketplaceOrder.STATUS_CONFIRMED: MarketplaceOrder.STATUS_PAID,
        MarketplaceOrder.STATUS_PAID: MarketplaceOrder.STATUS_SHIPPED,
        MarketplaceOrder.STATUS_SHIPPED: MarketplaceOrder.STATUS_DELIVERED,
    }
    next_status = next_map.get(order.status)

    return render(request, "shopboy/order-chat.html", {
        "order": order,
        "profile": profile,
        "items": order.items.all(),
        "chat_messages": messages_qs,
        "is_seller": is_seller,
        "access_token": str(order.access_token) if is_buyer else "",
        "status_choices": MarketplaceOrder.STATUS_CHOICES,
        "next_status": next_status,
    })


@require_POST
def marketplace_add_message(request, public_id):
    order = get_object_or_404(MarketplaceOrder, public_id=public_id)
    is_seller, is_buyer = _order_access_context(request, order)
    if not (is_seller or is_buyer):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)

    text = (request.POST.get("message") or "").strip()
    if not text:
        return JsonResponse({"success": False, "error": "Message cannot be empty"}, status=400)

    sender_type = MarketplaceChatMessage.SENDER_SELLER if is_seller else MarketplaceChatMessage.SENDER_BUYER
    msg = MarketplaceChatMessage.objects.create(
        order=order,
        sender_type=sender_type,
        message=text,
    )

    return JsonResponse({
        "success": True,
        "message": {
            "sender_type": msg.sender_type,
            "message": msg.message,
            "created_at": msg.created_at.isoformat(),
        }
    })


@ensure_csrf_cookie
def marketplace_house_inquiry_chat(request, public_id):
    inquiry = get_object_or_404(
        HouseInquiry.objects.select_related("house", "owner", "buyer", "house__listing_agent", "house__managed_by_agent")
        .prefetch_related("messages", "house__images"),
        public_id=public_id,
    )
    is_seller, is_buyer = _house_inquiry_access_context(request, inquiry)
    if not (is_seller or is_buyer):
        return HttpResponseForbidden("You do not have access to this inquiry.")

    return render(request, "shopboy/house-inquiry-chat.html", {
        "inquiry": inquiry,
        "chat_messages": inquiry.messages.all(),
        "is_seller": is_seller,
        "access_token": str(inquiry.access_token) if is_buyer else "",
        "seller_label": inquiry.house.display_owner_name,
        "seller_phone": inquiry.house.display_owner_phone,
    })


@require_POST
def marketplace_add_house_inquiry_message(request, public_id):
    inquiry = get_object_or_404(HouseInquiry.objects.select_related("house"), public_id=public_id)
    is_seller, is_buyer = _house_inquiry_access_context(request, inquiry)
    if not (is_seller or is_buyer):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)

    text = (request.POST.get("message") or "").strip()
    if not text:
        return JsonResponse({"success": False, "error": "Message cannot be empty"}, status=400)

    sender_type = HouseInquiryMessage.SENDER_SELLER if is_seller else HouseInquiryMessage.SENDER_BUYER
    msg = HouseInquiryMessage.objects.create(
        inquiry=inquiry,
        sender_type=sender_type,
        message=text,
    )
    inquiry.save(update_fields=["updated_at"])

    return JsonResponse({
        "success": True,
        "message": {
            "sender_type": msg.sender_type,
            "message": msg.message,
            "created_at": msg.created_at.isoformat(),
        }
    })


@csrf_exempt
@require_POST
def marketplace_update_status(request, public_id):
    order = get_object_or_404(MarketplaceOrder, public_id=public_id)
    is_seller, _ = _order_access_context(request, order)
    if not is_seller:
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)

    acting_shopboy = _get_shopboy_session(request)
    if acting_shopboy and not (
        acting_shopboy.can_use_marketplace and
        acting_shopboy.is_active and
        acting_shopboy.user_id == order.shop_owner_id
    ):
        acting_shopboy = None

    status = (request.POST.get("status") or "").strip()
    valid_statuses = {choice[0] for choice in MarketplaceOrder.STATUS_CHOICES}
    if status not in valid_statuses:
        return JsonResponse({"success": False, "error": "Invalid status"}, status=400)

    if order.status in [MarketplaceOrder.STATUS_DELIVERED, MarketplaceOrder.STATUS_CANCELLED]:
        return JsonResponse({"success": False, "error": "Order is closed"}, status=400)

    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.select_for_update().select_related("assigned_shopboy").get(id=order.id)
            if acting_shopboy and order.assigned_shopboy_id != acting_shopboy.id:
                order.assigned_shopboy = acting_shopboy

            if status in [MarketplaceOrder.STATUS_CONFIRMED, MarketplaceOrder.STATUS_PAID] and order.sale_id is None:
                items = list(order.items.select_related("product").select_for_update())
                total_amount = Decimal("0.00")
                total_profit = Decimal("0.00")
                vat_total = Decimal("0.00")

                for item in items:
                    product = item.product
                    if product.stock < item.quantity:
                        return JsonResponse({"success": False, "error": f"Not enough stock for {product.name}."}, status=400)
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
            if acting_shopboy:
                fields_to_update.append("assigned_shopboy")
            order.save(update_fields=fields_to_update)

            MarketplaceChatMessage.objects.create(
                order=order,
                sender_type=MarketplaceChatMessage.SENDER_SYSTEM,
                message=f"Order status updated to \"{dict(MarketplaceOrder.STATUS_CHOICES).get(status, status)}\"."
            )

        return JsonResponse({
            "success": True,
            "status": order.status,
        })
    except (OperationalError, ProgrammingError) as exc:
        logger.exception("Marketplace status update failed due to DB/migration issue")
        return JsonResponse({
            "success": False,
            "error": "Server needs database migration. Please run migrate and retry."
        }, status=500)
    except Exception:
        logger.exception("Marketplace status update failed")
        return JsonResponse({
            "success": False,
            "error": "Server error while updating status. Please try again."
        }, status=500)


def shopboy_marketplace_orders(request):
    shopboy = _get_shopboy_session(request)
    if not shopboy:
        return redirect("shopboy_login")
    if not shopboy.can_use_marketplace:
        messages.error(request, "You are not allowed to handle marketplace orders.")
        return redirect("shopboy_dashboard")

    orders = MarketplaceOrder.objects.filter(
        shop_owner=shopboy.user,
    ).filter(
        Q(assigned_shopboy=shopboy) | Q(assigned_shopboy__isnull=True)
    ).select_related("assigned_shopboy").order_by("-created_at")

    return render(request, "shopboy/marketplace-orders.html", {
        "shopboy": shopboy,
        "owner": shopboy.user,
        "orders": orders,
    })


@login_required
@require_POST
def update_marketplace_assignment(request):
    settings_obj = _get_marketplace_settings(request.user)
    shopboy_id = request.POST.get("assigned_shopboy") or None
    assigned = None
    is_enabled_raw = request.POST.get("marketplace_enabled")
    settings_obj.is_enabled = is_enabled_raw == "on"
    if shopboy_id:
        assigned = ShopBoy.objects.filter(id=shopboy_id, user=request.user, is_active=True, can_use_marketplace=True).first()
        if not assigned:
            messages.error(request, "Invalid shop boy selection.")
            return redirect("settings")

    settings_obj.assigned_shopboy = assigned
    settings_obj.save(update_fields=["assigned_shopboy", "is_enabled", "updated_at"])
    messages.success(request, "Marketplace settings updated.")
    return redirect("settings")
