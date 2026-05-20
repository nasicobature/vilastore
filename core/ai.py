from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from difflib import SequenceMatcher
import json
import os
import re

import requests
from django.db.models import Count, Sum
from django.utils import timezone

from .models import BranchInventory, Customer, Expense, Product, Sale, SaleItem
from .ai_inventory_training import CATEGORY_ACTION_WORDS, CREATE_WORDS, INVENTORY_COMMAND_EXAMPLES, PRODUCT_ACTION_WORDS


SOFT_DRINK_WORDS = {"coke", "coka", "cola", "soft drink", "softdrink", "soda", "minerals"}

BARCODE_PRODUCT_HINTS = {
    "5449000000996": {
        "name": "Coca-Cola 50cl",
        "category": "Drinks",
        "brand": "Coca-Cola",
        "suggested_price": "500.00",
        "image_url": "https://placehold.co/640x640/f40009/ffffff?text=Coca-Cola",
    },
    "5449000131805": {
        "name": "Fanta Orange 50cl",
        "category": "Drinks",
        "brand": "Fanta",
        "suggested_price": "500.00",
        "image_url": "https://placehold.co/640x640/f47b20/ffffff?text=Fanta",
    },
    "6156000128083": {
        "name": "Indomie Instant Noodles",
        "category": "Food",
        "brand": "Indomie",
        "suggested_price": "350.00",
        "image_url": "https://placehold.co/640x640/f7b500/111111?text=Indomie",
    },
}

PRODUCT_KEYWORDS = [
    ("coca-cola", "Coca-Cola", "Drinks", "Coca-Cola", "500.00"),
    ("coke", "Coca-Cola", "Drinks", "Coca-Cola", "500.00"),
    ("fanta", "Fanta Orange", "Drinks", "Fanta", "500.00"),
    ("sprite", "Sprite", "Drinks", "Sprite", "500.00"),
    ("pepsi", "Pepsi", "Drinks", "Pepsi", "500.00"),
    ("indomie", "Indomie Instant Noodles", "Food", "Indomie", "350.00"),
    ("rice", "Rice", "Food", "Generic", "0.00"),
    ("sugar", "Sugar", "Food", "Generic", "0.00"),
    ("milk", "Peak Milk", "Food", "Peak", "0.00"),
]


def money(value):
    try:
        return Decimal(value or 0).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def serialize_money(value):
    return str(money(value))


def _date_ranges():
    today = timezone.localdate()
    return {
        "today": today,
        "week_start": today - timedelta(days=6),
        "prev_week_start": today - timedelta(days=13),
        "prev_week_end": today - timedelta(days=7),
        "month_start": today - timedelta(days=29),
        "prev_month_start": today - timedelta(days=59),
        "prev_month_end": today - timedelta(days=30),
    }


def _sale_totals(owner, start, end=None):
    qs = Sale.objects.filter(user=owner, created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return {
        "sales": money(qs.aggregate(total=Sum("total_amount"))["total"]),
        "profit": money(qs.aggregate(total=Sum("total_profit"))["total"]),
        "count": qs.count(),
    }


def _expense_total(owner, start, end=None):
    qs = Expense.objects.filter(user=owner, date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    return money(qs.aggregate(total=Sum("amount"))["total"])


def _change_text(current, previous, label):
    current = money(current)
    previous = money(previous)
    if previous <= 0 and current > 0:
        return f"Your {label} started growing this period."
    if previous <= 0:
        return f"Not enough previous {label} data yet."
    diff = current - previous
    pct = (diff / previous * Decimal("100")).quantize(Decimal("0.1"))
    direction = "increased" if diff >= 0 else "reduced"
    return f"Your {label} {direction} by {abs(pct)}% compared with the previous period."


def _daily_average(total, days):
    if days <= 0:
        return Decimal("0.00")
    return (money(total) / Decimal(days)).quantize(Decimal("0.01"))


def profit_analysis(owner):
    ranges = _date_ranges()
    week = _sale_totals(owner, ranges["week_start"])
    prev_week = _sale_totals(owner, ranges["prev_week_start"], ranges["prev_week_end"])
    week_expenses = _expense_total(owner, ranges["week_start"])
    prev_week_expenses = _expense_total(owner, ranges["prev_week_start"], ranges["prev_week_end"])
    net_profit = week["profit"] - week_expenses

    advice = [
        _change_text(week["profit"], prev_week["profit"], "profit"),
        _change_text(week_expenses, prev_week_expenses, "expenses"),
    ]
    if week_expenses > week["profit"]:
        advice.append("Your expenses are higher than your recorded profit this week. Review rent, transport, salaries, and supplies.")
    elif net_profit > 0:
        advice.append("Your shop is profitable this week. Keep tracking fast-moving products and avoid unnecessary expenses.")
    else:
        advice.append("Profit is still weak this week. Check product prices, supplier costs, and slow-moving stock.")

    return {
        "week_sales": serialize_money(week["sales"]),
        "week_profit": serialize_money(week["profit"]),
        "week_expenses": serialize_money(week_expenses),
        "net_profit": serialize_money(net_profit),
        "advice": advice,
    }


def low_stock_prediction(owner):
    since = timezone.localdate() - timedelta(days=13)
    sold_rows = (
        SaleItem.objects.filter(sale__user=owner, sale__created_at__date__gte=since)
        .values("product_id", "product__name")
        .annotate(quantity_sold=Sum("quantity"))
    )
    sold_map = {row["product_id"]: money(row["quantity_sold"]) for row in sold_rows}
    predictions = []
    products = Product.objects.filter(user=owner).order_by("name")
    for product in products:
        sold = sold_map.get(product.id, Decimal("0.00"))
        if sold <= 0:
            continue
        daily = sold / Decimal("14")
        stock = money(product.stock)
        days_left = int((stock / daily).to_integral_value(rounding=ROUND_CEILING)) if daily > 0 else None
        if days_left is not None and days_left <= 7:
            predictions.append({
                "product_id": product.id,
                "name": product.name,
                "stock": serialize_money(stock),
                "daily_sales_rate": serialize_money(daily),
                "days_left": max(days_left, 0),
                "message": f"{product.name} may finish in {max(days_left, 0)} day{'s' if days_left != 1 else ''}.",
            })
    return sorted(predictions, key=lambda item: item["days_left"])[:12]


def sales_forecast(owner):
    ranges = _date_ranges()
    last_30 = _sale_totals(owner, ranges["month_start"])
    daily_avg = _daily_average(last_30["sales"], 30)
    return {
        "daily": serialize_money(daily_avg),
        "weekly": serialize_money(daily_avg * Decimal("7")),
        "monthly": serialize_money(daily_avg * Decimal("30")),
        "message": "Forecast is based on the last 30 days of recorded sales.",
    }


def expense_warning(owner):
    ranges = _date_ranges()
    week = _expense_total(owner, ranges["week_start"])
    prev_week = _expense_total(owner, ranges["prev_week_start"], ranges["prev_week_end"])
    month_sales = _sale_totals(owner, ranges["month_start"])["sales"]
    month_expenses = _expense_total(owner, ranges["month_start"])
    ratio = (month_expenses / month_sales * Decimal("100")).quantize(Decimal("0.1")) if month_sales > 0 else Decimal("0.0")
    warnings = []
    if prev_week > 0 and week > prev_week * Decimal("1.25"):
        warnings.append("Expenses are rising fast compared with last week.")
    if month_sales > 0 and ratio >= Decimal("60"):
        warnings.append(f"Expenses are taking about {ratio}% of sales in the last 30 days.")
    if not warnings:
        warnings.append("Expenses look controlled based on current records.")
    return {
        "week_expenses": serialize_money(week),
        "previous_week_expenses": serialize_money(prev_week),
        "expense_to_sales_percent": str(ratio),
        "warnings": warnings,
    }


def customer_insights(owner):
    spending_rows = (
        Sale.objects.filter(user=owner, customer__isnull=False)
        .values("customer_id", "customer__first_name", "customer__last_name", "customer__phone")
        .annotate(total_spent=Sum("total_amount"), visits=Count("id"))
        .order_by("-total_spent")[:10]
    )
    best = [
        {
            "customer_id": row["customer_id"],
            "name": f"{row['customer__first_name']} {row['customer__last_name']}".strip(),
            "phone": row["customer__phone"],
            "total_spent": serialize_money(row["total_spent"]),
            "visits": row["visits"],
        }
        for row in spending_rows
    ]
    inactive_since = timezone.localdate() - timedelta(days=30)
    active_customer_ids = Sale.objects.filter(user=owner, customer__isnull=False, created_at__date__gte=inactive_since).values_list("customer_id", flat=True)
    inactive = [
        {
            "customer_id": customer.id,
            "name": f"{customer.first_name} {customer.last_name}".strip(),
            "phone": customer.phone,
        }
        for customer in Customer.objects.filter(user=owner).exclude(id__in=active_customer_ids).order_by("-created_at")[:10]
    ]
    return {"best_customers": best, "inactive_customers": inactive}


def fraud_signals(owner):
    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    signals = []
    staff_rows = (
        Sale.objects.filter(user=owner, handled_by_shopboy__isnull=False, created_at__date__gte=week_start)
        .values("handled_by_shopboy__full_name", "handled_by_shopboy__username")
        .annotate(total=Sum("total_amount"), count=Count("id"))
        .order_by("-total")[:8]
    )
    for row in staff_rows:
        average = money(row["total"]) / Decimal(row["count"] or 1)
        if row["count"] >= 8 and average < Decimal("500"):
            signals.append(f"{row['handled_by_shopboy__full_name']} has many small sales this week. Review receipts and cash handover.")

    low_margin_sales = Sale.objects.filter(user=owner, created_at__date__gte=week_start, total_amount__gt=0, total_profit__lt=0).count()
    if low_margin_sales:
        signals.append(f"{low_margin_sales} sales show negative profit this week. Check prices, discounts, or cost prices.")

    if not signals:
        signals.append("No obvious suspicious pattern found in recent staff sales.")
    return signals


def smart_product_search(owner, query, limit=12):
    query = (query or "").strip().lower()
    if not query:
        return []
    products = Product.objects.filter(user=owner).select_related("category").order_by("name")
    results = []
    query_tokens = set(re.findall(r"[a-z0-9]+", query))
    for product in products:
        haystack = " ".join([
            product.name or "",
            product.code or "",
            product.category.name if product.category else "",
        ]).lower()
        score = SequenceMatcher(None, query, haystack).ratio()
        if query in haystack:
            score += 0.55
        if query_tokens & SOFT_DRINK_WORDS and any(word in haystack for word in ["coca", "cola", "coke", "drink", "soda"]):
            score += 0.45
        if any(SequenceMatcher(None, token, word).ratio() >= 0.78 for token in query_tokens for word in re.findall(r"[a-z0-9]+", haystack)):
            score += 0.25
        if score >= 0.38:
            results.append({
                "id": product.id,
                "name": product.name,
                "code": product.code,
                "price": serialize_money(product.selling_price),
                "stock": serialize_money(product.stock),
                "score": round(score, 3),
            })
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]


def product_prefill_from_barcode(owner, barcode):
    code = (barcode or "").strip()
    if not code:
        return {"found": False, "message": "Barcode is empty."}

    existing = Product.objects.filter(user=owner, code__iexact=code).select_related("category").first()
    if existing:
        return {
            "found": True,
            "source": "inventory",
            "code": code,
            "name": existing.name,
            "category": existing.category.name if existing.category else "",
            "category_id": existing.category_id,
            "brand": "",
            "suggested_price": serialize_money(existing.selling_price),
            "cost_price": serialize_money(existing.cost_price),
            "stock": serialize_money(existing.stock),
            "image_url": "",
            "message": "Product already exists in your inventory.",
        }

    hint = BARCODE_PRODUCT_HINTS.get(code)
    if hint:
        return {
            "found": True,
            "source": "barcode_catalog",
            "code": code,
            "name": hint["name"],
            "category": hint["category"],
            "brand": hint["brand"],
            "suggested_price": hint["suggested_price"],
            "cost_price": "0.00",
            "stock": "1",
            "image_url": hint["image_url"],
            "message": "AI filled product details from the barcode catalog.",
        }

    return {
        "found": False,
        "source": "fallback",
        "code": code,
        "name": "",
        "category": "",
        "brand": "",
        "suggested_price": "0.00",
        "cost_price": "0.00",
        "stock": "1",
        "image_url": "",
        "message": "Barcode is new. Enter the product name once, then VilaStore will remember it in your inventory.",
    }


def parse_product_voice_form(transcript):
    text = (transcript or "").strip()
    lowered = text.lower()
    cleaned = re.sub(r"\b(add|saka|kara|karo|product|kaya|naira|ngn|n)\b", " ", lowered)
    quantity_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:pieces|piece|pcs|pc|carton|ctn|kwali|kwali-kwali)?", cleaned)
    price_matches = re.findall(r"(\d+(?:\.\d+)?)", cleaned)
    price = price_matches[-1] if price_matches else "0"
    quantity = quantity_match.group(1) if quantity_match else "1"

    words = re.findall(r"[a-zA-Z-]+", cleaned)
    stop_words = {
        "small", "big", "large", "pieces", "piece", "pcs", "pc", "carton", "ctn",
        "price", "for", "with", "qty", "quantity", "and", "na", "ne",
    }
    name_words = [word for word in words if word not in stop_words]
    product_name = " ".join(name_words).strip().title()
    category = ""
    brand = ""
    suggested_price = price
    for keyword, name, cat, brand_name, default_price in PRODUCT_KEYWORDS:
        if keyword in lowered:
            if not product_name or len(product_name) < 4:
                product_name = name
            category = cat
            brand = brand_name
            if price in {"0", "1"} and default_price != "0.00":
                suggested_price = default_price
            break

    if "carton" in lowered or "ctn" in lowered:
        product_name = f"{product_name} Carton".strip()
    elif "small" in lowered and product_name:
        product_name = f"{product_name} Small"

    return {
        "name": product_name,
        "category": category,
        "brand": brand,
        "stock": quantity,
        "cost_price": "0.00",
        "selling_price": serialize_money(suggested_price),
        "message": "Voice command parsed. Review product name, quantity, and price before saving.",
    }


def _clean_phrase(value):
    value = re.sub(r"[\"'`]+", "", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,:;-")


def _extract_labeled_text(text, labels, stop_labels=None):
    stop_labels = stop_labels or []
    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = "|".join(re.escape(label) for label in stop_labels)
    if stop_pattern:
        pattern = rf"(?:{label_pattern})\s*(?:is|shi|ta|ne|=|:)?\s*(.+?)(?=(?:\b(?:{stop_pattern})\b)|[,.;]|\n|$)"
    else:
        pattern = rf"(?:{label_pattern})\s*(?:is|shi|ta|ne|=|:)?\s*(.+?)(?:[,.;]|\n|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _clean_phrase(match.group(1)) if match else ""


def _extract_labeled_number(text, labels):
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*(?:is|shi|ta|ne|=|:)?\s*(?:ngn|n|₦)?\s*([0-9][0-9,]*(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).replace(",", "")


def parse_category_command(transcript):
    text = (transcript or "").strip()
    lowered = text.lower()
    labels = [
        "category name",
        "name",
        "sunan category",
        "sunan shi",
        "sunan ta",
        "sunan sa",
        "suna",
    ]
    name = _extract_labeled_text(text, labels)
    if not name:
        match = re.search(r"(?:category|rukuni)\s+(?:for|na|mai suna)?\s*([a-zA-Z0-9& -]+)", text, flags=re.IGNORECASE)
        if match:
            name = _clean_phrase(match.group(1))
    if not name and any(word in lowered for word in ["category", "rukuni"]):
        words = re.findall(r"[A-Za-z0-9&-]+", text)
        stop = {
            "create", "category", "for", "me", "the", "name", "is", "ka", "kirkiro", "kirkira",
            "min", "sunan", "shi", "ta", "sa", "rukuni",
        }
        candidates = [word for word in words if word.lower() not in stop]
        name = " ".join(candidates[-3:])
    missing = []
    if not name:
        missing.append("category name")
    return {
        "name": name.strip().title() if name else "",
        "missing": missing,
        "message": "Category details extracted. Review before saving." if not missing else "Please provide the category name.",
    }


def parse_inventory_product_command(transcript):
    text = (transcript or "").strip()
    lowered = text.lower()
    stop_labels = [
        "price", "farashi", "selling price", "cost price", "cost", "quantity", "qty", "stock",
        "category", "barcode", "code", "description", "bayani", "image", "photo",
    ]
    name = _extract_labeled_text(text, [
        "product name",
        "name",
        "sunan kaya",
        "sunan product",
        "kaya",
    ], stop_labels)
    category = _extract_labeled_text(text, ["category", "rukuni"], stop_labels)
    description = _extract_labeled_text(text, ["description", "bayani"], stop_labels)
    code = _extract_labeled_text(text, ["barcode", "bar code", "code"], stop_labels)
    image_url = _extract_labeled_text(text, ["image", "photo", "picture"], stop_labels)
    quantity = _extract_labeled_number(text, ["quantity", "qty", "stock", "adadi", "pieces"])
    selling_price = _extract_labeled_number(text, ["selling price", "price", "farashi"])
    cost_price = _extract_labeled_number(text, ["cost price", "cost", "buying price", "sayan", "sayen"])

    fallback = parse_product_voice_form(text)
    if not name:
        name = fallback.get("name", "")
    if not category:
        category = fallback.get("category", "")
    if not quantity:
        quantity = fallback.get("stock", "1")
    if not selling_price or selling_price == "0":
        selling_price = fallback.get("selling_price", "0.00")
    if not cost_price:
        cost_price = fallback.get("cost_price", "0.00")

    missing = []
    if not name:
        missing.append("product name")
    if not selling_price or money(selling_price) <= 0:
        missing.append("selling price")
    if not quantity:
        missing.append("quantity")

    return {
        "name": name,
        "category": category,
        "stock": quantity or "1",
        "cost_price": serialize_money(cost_price),
        "selling_price": serialize_money(selling_price),
        "suggested_price": serialize_money(selling_price),
        "code": code,
        "description": description,
        "image_url": image_url,
        "missing": missing,
        "message": "Product details extracted. Review before saving." if not missing else "Some required product details are missing.",
    }


HAUSA_TRANSLATION_TABLE = str.maketrans({
    "ƙ": "k", "Ƙ": "K", "ḳ": "k",
    "ɗ": "d", "Ɗ": "D",
    "ɓ": "b", "Ɓ": "B",
    "₦": "n",
})

INVENTORY_STOP_LABELS = [
    "product name", "name", "sunan kaya", "sunan product", "sunan category", "sunan shi", "sunan ta",
    "category", "rukuni", "price", "selling price", "farashi", "farashin saidawa", "cost price",
    "buying price", "farashin saye", "cost", "quantity", "qty", "stock", "adadi", "guda", "pieces",
    "barcode", "bar code", "code", "description", "bayani", "image", "photo", "picture",
]

PRODUCT_NAME_STOP_WORDS = {
    "add", "create", "make", "new", "register", "product", "products", "for", "me", "the", "name",
    "is", "ka", "min", "saka", "kara", "karo", "kirkira", "kirkiro", "sabon", "sunan", "shi", "ta",
    "ne", "kaya", "guda", "quantity", "qty", "stock", "adadi", "category", "rukuni", "farashi",
    "price", "naira", "ngn", "n",
}


def _normalize_inventory_text(value):
    value = (value or "").translate(HAUSA_TRANSLATION_TABLE)
    value = re.sub(r"\bnaira\b", " n ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _title_shop_phrase(value):
    value = _clean_phrase(value)
    if not value:
        return ""
    small_words = {"and", "or", "of", "for", "da", "na"}
    parts = []
    for word in value.split():
        if word.isupper() or any(char.isdigit() for char in word) or any(char.isupper() for char in word[1:]):
            parts.append(word)
        elif word.lower() in small_words:
            parts.append(word.lower())
        else:
            parts.append(word[:1].upper() + word[1:])
    return " ".join(parts)


def _label_regex(labels):
    return "|".join(sorted((re.escape(label) for label in labels), key=len, reverse=True))


def _extract_labeled_text(text, labels, stop_labels=None):
    stop_labels = stop_labels or INVENTORY_STOP_LABELS
    label_pattern = _label_regex(labels)
    stop_pattern = _label_regex(stop_labels)
    bridge = r"(?:\s+(?:is|are|as|called|mai suna|suna|shi|ita|ta|ne|na|=)|\s*[:=])?"
    pattern = rf"(?:^|[\s,.;])(?:{label_pattern}){bridge}\s+(.+?)(?=(?:[\s,.;]\s*(?:{stop_pattern})\b)|[,;\n]|$)"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        value = _clean_phrase(match.group(1))
        if value and value.lower() not in {"is", "shi", "ta", "ne", "na"}:
            return value
    return ""


def _parse_inventory_number(value):
    value = (value or "").strip().lower().replace(",", "")
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)(k)?", value)
    if not match:
        return ""
    number = Decimal(match.group(1))
    if match.group(2):
        number *= Decimal("1000")
    if number == number.to_integral_value():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def _extract_labeled_number(text, labels):
    label_pattern = _label_regex(labels)
    bridge = r"(?:\s+(?:is|are|as|shi|ta|ne|na|=)|\s*[:=])?"
    number = r"(?:ngn|n|#)?\s*([0-9][0-9,]*(?:\.\d+)?k?)"
    pattern = rf"(?:^|[\s,.;])(?:{label_pattern}){bridge}\s*{number}"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _parse_inventory_number(match.group(1)) if match else ""


def _extract_quantity(text):
    quantity = _extract_labeled_number(text, ["quantity", "qty", "stock", "adadi", "guda", "pieces", "piece", "pcs"])
    if quantity:
        return quantity
    match = re.search(r"\b(?:guda|pieces|piece|pcs)\s*([0-9][0-9,]*(?:\.\d+)?)\b", text, flags=re.IGNORECASE)
    if match:
        return _parse_inventory_number(match.group(1))
    match = re.search(r"\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:guda|pieces|piece|pcs|carton|ctn)\b", text, flags=re.IGNORECASE)
    return _parse_inventory_number(match.group(1)) if match else ""


def _extract_category_name_from_phrase(text):
    name = _extract_labeled_text(text, [
        "category name", "sunan category", "sunan rukuni", "sunan shi", "sunan ta", "name", "suna",
    ], ["price", "farashi", "quantity", "qty", "stock", "category", "rukuni", "product", "kaya"])
    if name:
        return name
    patterns = [
        r"\b(?:category|rukuni)\s+(?:called|mai suna|suna|name|na)?\s*([A-Za-z0-9& /\-]+)",
        r"\b(?:add|create|make|saka|kirkira|kirkiro)\s+(?:new|sabon)?\s*(?:category|rukuni)\s+([A-Za-z0-9& /\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_phrase(match.group(1))
    return ""


def _extract_product_name_by_fallback(text):
    working = re.sub(r"\b(?:ngn|naira|n)\s*[0-9][0-9,]*(?:\.\d+)?k?\b", " ", text, flags=re.IGNORECASE)
    working = re.sub(r"\b[0-9][0-9,]*(?:\.\d+)?k?\s*(?:naira|ngn|guda|pieces|piece|pcs|carton|ctn)\b", " ", working, flags=re.IGNORECASE)
    for label in INVENTORY_STOP_LABELS:
        working = re.sub(rf"\b{re.escape(label)}\b\s*(?:is|shi|ta|ne|na|=|:)?\s*[^,.;]*", " ", working, flags=re.IGNORECASE)
    words = re.findall(r"[A-Za-z0-9&/\-]+", working)
    candidates = [word for word in words if word.lower() not in PRODUCT_NAME_STOP_WORDS]
    return " ".join(candidates[:5])


def _detect_inventory_intent(text, preferred=None):
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    if preferred == "category":
        return "create_category"
    if preferred == "product":
        return "create_product"
    if tokens & CATEGORY_ACTION_WORDS and not (tokens & PRODUCT_ACTION_WORDS):
        return "create_category"
    if tokens & PRODUCT_ACTION_WORDS:
        return "create_product"
    if tokens & CREATE_WORDS and tokens & CATEGORY_ACTION_WORDS:
        return "create_category"
    return "create_product"


def _inventory_examples_for_intent(intent, limit=8):
    return [example["text"] for example in INVENTORY_COMMAND_EXAMPLES if example["intent"] == intent][:limit]


def parse_category_command(transcript):
    text = _normalize_inventory_text(transcript)
    name = _extract_category_name_from_phrase(text)
    missing = []
    if not name:
        missing.append("category name")
    category_name = _title_shop_phrase(name)
    return {
        "action": "create_category",
        "intent": "create_category",
        "category_name": category_name,
        "name": category_name,
        "missing": missing,
        "examples": _inventory_examples_for_intent("create_category"),
        "message": (
            "Category details extracted. Review before saving."
            if not missing
            else "Please provide the category name. Example: Create category for me, the name is Drinks."
        ),
    }


def parse_inventory_product_command(transcript):
    text = _normalize_inventory_text(transcript)
    name = _extract_labeled_text(text, [
        "product name", "sunan kaya", "sunan product", "item name", "name",
    ])
    if not name:
        name = _extract_product_name_by_fallback(text)

    category = _extract_labeled_text(text, ["category", "rukuni", "group", "section"])
    description = _extract_labeled_text(text, ["description", "bayani", "details", "note"])
    barcode = _extract_labeled_text(text, ["barcode", "bar code", "code", "sku"])
    image_url = _extract_labeled_text(text, ["image", "photo", "picture", "image url"])
    quantity = _extract_quantity(text)
    selling_price = _extract_labeled_number(text, ["selling price", "sale price", "price", "farashin saidawa", "farashi"])
    cost_price = _extract_labeled_number(text, ["cost price", "buying price", "purchase price", "cost", "farashin saye", "sayan", "sayen"])

    fallback = parse_product_voice_form(text)
    if not name:
        name = fallback.get("name", "")
    if not category:
        category = fallback.get("category", "")
    has_any_number = bool(re.search(r"\d", text))
    if not quantity and has_any_number:
        quantity = fallback.get("stock", "")
    if (not selling_price or selling_price == "0") and has_any_number:
        selling_price = fallback.get("selling_price", "0.00")
    if not cost_price:
        cost_price = fallback.get("cost_price", "0.00")

    product_name = _title_shop_phrase(name)
    category_name = _title_shop_phrase(category)
    missing = []
    if not product_name:
        missing.append("product name")
    if not selling_price or money(selling_price) <= 0:
        missing.append("selling price")
    if not quantity or money(quantity) <= 0:
        missing.append("quantity")

    return {
        "action": "create_product",
        "intent": "create_product",
        "product_name": product_name,
        "price": serialize_money(selling_price),
        "quantity": quantity or "",
        "category": category_name,
        "cost_price": serialize_money(cost_price),
        "selling_price": serialize_money(selling_price),
        "suggested_price": serialize_money(selling_price),
        "barcode": barcode,
        "code": barcode,
        "description": _clean_phrase(description),
        "image_url": image_url,
        "name": product_name,
        "stock": quantity or "",
        "missing": missing,
        "examples": _inventory_examples_for_intent("create_product"),
        "message": (
            "Product details extracted. Review before saving."
            if not missing
            else "Please provide: " + ", ".join(missing) + "."
        ),
    }


def _parse_inventory_command_rule_based(transcript, mode=None):
    text = _normalize_inventory_text(transcript)
    intent = _detect_inventory_intent(text, preferred=mode)
    if intent == "create_category":
        return parse_category_command(text)
    return parse_inventory_product_command(text)


def _inventory_model_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["create_category", "create_product"]},
            "category_name": {"type": "string"},
            "product_name": {"type": "string"},
            "price": {"type": "number"},
            "quantity": {"type": "number"},
            "category": {"type": "string"},
            "cost_price": {"type": "number"},
            "selling_price": {"type": "number"},
            "barcode": {"type": "string"},
            "description": {"type": "string"},
            "missing": {"type": "array", "items": {"type": "string"}},
            "message": {"type": "string"},
        },
        "required": [
            "action", "category_name", "product_name", "price", "quantity", "category",
            "cost_price", "selling_price", "barcode", "description", "missing", "message",
        ],
    }


def _inventory_model_system_prompt(mode=None):
    examples = json.dumps(INVENTORY_COMMAND_EXAMPLES, ensure_ascii=False)
    mode_note = f"The UI requested mode '{mode}'." if mode in {"category", "product"} else "Detect whether this is a category or product command."
    return (
        "You are VilaStore Inventory AI. Convert Hausa, Hausa-English, or English shop-owner commands "
        "into one JSON object for inventory form filling only. Do not save anything. "
        "Use action=create_category for category requests and action=create_product for product requests. "
        "For product requests, product_name, price/selling_price, and quantity are required. "
        "For category requests, category_name is required. If required details are missing, put their human names "
        "in missing and write a short message asking the shop owner for them. Use 0 for unavailable numeric fields. "
        "Keep product and category names exactly as spoken when possible, preserving brands like iPhone and Coca-Cola. "
        f"{mode_note}\nTraining examples:\n{examples}"
    )


def _extract_openai_response_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    return ""


def _model_number(value):
    if value in (None, ""):
        return "0"
    try:
        number = Decimal(str(value))
    except Exception:
        return "0"
    if number == number.to_integral_value():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def _normalize_inventory_model_result(raw, mode=None):
    action = raw.get("action") or _detect_inventory_intent("", preferred=mode)
    if action not in {"create_category", "create_product"}:
        action = "create_product"

    category_name = _title_shop_phrase(raw.get("category_name") or raw.get("category") or "")
    product_name = _title_shop_phrase(raw.get("product_name") or raw.get("name") or "")
    category = _title_shop_phrase(raw.get("category") or "")
    price = _model_number(raw.get("price") or raw.get("selling_price"))
    selling_price = _model_number(raw.get("selling_price") or raw.get("price"))
    cost_price = _model_number(raw.get("cost_price"))
    quantity = _model_number(raw.get("quantity") or raw.get("stock"))
    barcode = _clean_phrase(raw.get("barcode") or raw.get("code") or "")
    description = _clean_phrase(raw.get("description") or "")

    missing = list(raw.get("missing") or [])
    if action == "create_category":
        if not category_name and "category name" not in missing:
            missing.append("category name")
        message = raw.get("message") or (
            "Category details extracted. Review before saving."
            if not missing
            else "Please provide the category name."
        )
        return {
            "action": "create_category",
            "intent": "create_category",
            "category_name": category_name,
            "name": category_name,
            "missing": missing,
            "examples": _inventory_examples_for_intent("create_category"),
            "message": message,
            "ai_provider": "openai",
        }

    if not product_name and "product name" not in missing:
        missing.append("product name")
    if money(selling_price) <= 0 and "selling price" not in missing:
        missing.append("selling price")
    if money(quantity) <= 0 and "quantity" not in missing:
        missing.append("quantity")

    return {
        "action": "create_product",
        "intent": "create_product",
        "product_name": product_name,
        "price": serialize_money(selling_price),
        "quantity": quantity if money(quantity) > 0 else "",
        "category": category,
        "cost_price": serialize_money(cost_price),
        "selling_price": serialize_money(selling_price),
        "suggested_price": serialize_money(selling_price),
        "barcode": barcode,
        "code": barcode,
        "description": description,
        "image_url": _clean_phrase(raw.get("image_url") or ""),
        "name": product_name,
        "stock": quantity if money(quantity) > 0 else "",
        "missing": missing,
        "examples": _inventory_examples_for_intent("create_product"),
        "message": raw.get("message") or (
            "Product details extracted. Review before saving."
            if not missing
            else "Please provide: " + ", ".join(missing) + "."
        ),
        "ai_provider": "openai",
    }


def _parse_inventory_command_with_openai(transcript, mode=None):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "OPENAI_API_KEY is not configured."

    model = os.getenv("OPENAI_INVENTORY_MODEL", "gpt-5.2").strip() or "gpt-5.2"
    timeout = int(os.getenv("OPENAI_INVENTORY_TIMEOUT", "20"))
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": _inventory_model_system_prompt(mode)}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": transcript or ""}],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "vilastore_inventory_command",
                    "strict": True,
                    "schema": _inventory_model_schema(),
                }
            },
            "max_output_tokens": 800,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    output_text = _extract_openai_response_text(payload)
    if not output_text:
        return None, "OpenAI returned an empty inventory parser response."
    return _normalize_inventory_model_result(json.loads(output_text), mode=mode), ""


def parse_inventory_command(transcript, mode=None):
    provider = os.getenv("AI_INVENTORY_PROVIDER", "rules").strip().lower()
    if provider == "openai":
        try:
            parsed, error = _parse_inventory_command_with_openai(transcript, mode=mode)
            if parsed:
                return parsed
        except Exception as exc:
            error = str(exc)
        fallback = _parse_inventory_command_rule_based(transcript, mode=mode)
        fallback["ai_provider"] = "rules_fallback"
        fallback["ai_error"] = error
        return fallback

    parsed = _parse_inventory_command_rule_based(transcript, mode=mode)
    parsed["ai_provider"] = "rules"
    return parsed


def parse_receipt_text(owner, text):
    items = []
    for line in (text or "").splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        match = re.match(r"(.+?)\s+(?:x|qty)?\s*(\d+(?:\.\d+)?)\s+[#₦Nn]?\s*(\d+(?:\.\d+)?)", cleaned)
        if not match:
            continue
        name, qty, price = match.groups()
        matches = smart_product_search(owner, name, limit=1)
        items.append({
            "name": name.strip(),
            "quantity": serialize_money(qty),
            "price": serialize_money(price),
            "matched_product_id": matches[0]["id"] if matches else None,
            "matched_product_name": matches[0]["name"] if matches else "",
        })
    return items


def apply_receipt_inventory(owner, parsed_items):
    updated = []
    skipped = []
    for item in parsed_items or []:
        product_id = item.get("matched_product_id")
        qty = money(item.get("quantity"))
        if not product_id or qty <= 0:
            skipped.append(item)
            continue
        product = Product.objects.filter(user=owner, id=product_id).first()
        if not product:
            skipped.append(item)
            continue
        product.stock = money(product.stock) + qty
        product.save(update_fields=["stock"])
        updated.append({"product_id": product.id, "name": product.name, "added": serialize_money(qty), "stock": serialize_money(product.stock)})
    return {"updated": updated, "skipped": skipped}


def parse_voice_command(owner, transcript):
    text = (transcript or "").strip().lower()
    qty_match = re.search(r"(\d+(?:\.\d+)?)", text)
    qty = qty_match.group(1) if qty_match else "1"
    intent = "unknown"
    if any(word in text for word in ["sell", "sold", "sale", "sayar", "sayarwa"]):
        intent = "sale"
    elif any(word in text for word in ["add stock", "new stock", "restock", "kaya", "inventory"]):
        intent = "stock"
    product_query = re.sub(r"\b(sell|sold|sale|add|stock|new|restock|pieces|piece|carton|qty|quantity|na|kaya|sayar|sayarwa)\b", " ", text)
    product_query = re.sub(r"\d+(?:\.\d+)?", " ", product_query).strip()
    matches = smart_product_search(owner, product_query or text, limit=3)
    return {
        "intent": intent,
        "quantity": qty,
        "product_matches": matches,
        "message": "Review the match before saving. Voice AI uses fallback parsing for now.",
    }


def assistant_answer(owner, question):
    q = (question or "").strip().lower()
    data = ai_summary(owner)
    if "stock" in q or "finish" in q:
        items = data["low_stock_prediction"][:3]
        return " ".join(item["message"] for item in items) if items else "No product looks likely to finish soon based on recent sales."
    if "expense" in q:
        return " ".join(data["expense_warning"]["warnings"])
    if "customer" in q:
        best = data["customer_insights"]["best_customers"][:3]
        if not best:
            return "No customer spending pattern is available yet. Start linking sales to customers."
        return "Your best customers are " + ", ".join(f"{item['name']} (NGN {item['total_spent']})" for item in best) + "."
    if "forecast" in q or "sales" in q:
        forecast = data["sales_forecast"]
        return f"Expected sales are about NGN {forecast['daily']} daily, NGN {forecast['weekly']} weekly, and NGN {forecast['monthly']} monthly."
    return " ".join(data["profit_analysis"]["advice"][:2])


def ai_summary(owner):
    return {
        "profit_analysis": profit_analysis(owner),
        "low_stock_prediction": low_stock_prediction(owner),
        "sales_forecast": sales_forecast(owner),
        "expense_warning": expense_warning(owner),
        "customer_insights": customer_insights(owner),
        "fraud_signals": fraud_signals(owner),
        "generated_at": timezone.now().isoformat(),
    }
