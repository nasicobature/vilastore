from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from difflib import SequenceMatcher
import re

from django.db.models import Count, Sum
from django.utils import timezone

from .models import BranchInventory, Customer, Expense, Product, Sale, SaleItem


SOFT_DRINK_WORDS = {"coke", "coka", "cola", "soft drink", "softdrink", "soda", "minerals"}


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
