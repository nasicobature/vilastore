from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User,
    Category,
    Product,
    Customer,
    Sale,
    SaleItem,
    Expense,
    ShopBoy,
    MarketplaceShopProfile,
    MarketplaceSettings,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceChatMessage,
    MarketplaceBuyer,
    MarketplaceBuyerToken,
    Investor,
    Feedback,
)


# =============================
# Custom User Admin
# =============================
class CustomUserAdmin(UserAdmin):
    model = User

    fieldsets = UserAdmin.fieldsets + (
        ("Business Info", {
            "fields": (
                "business_name",
                "business_type",
                "state",
                "phone",
                "address",
                "country",
                "profile_image",
                "plan",
                "is_paid",
                "subscription_active_until",
                "monthly_fee",
                "is_email_verified",
                "shop_code",
            )
        }),
    )

    list_display = (
        "username",
        "email",
        "business_name",
        "plan",
        "is_paid",
        "is_email_verified",
        "shop_code",
        "is_staff",
    )

    search_fields = ("username", "email", "business_name")
    list_filter = ("plan", "is_paid", "is_staff", "is_email_verified")


admin.site.register(User, CustomUserAdmin)


@admin.register(MarketplaceBuyer)
class MarketplaceBuyerAdmin(admin.ModelAdmin):
    list_display = ("email", "is_email_verified", "is_active", "created_at", "last_login")
    search_fields = ("email",)
    list_filter = ("is_active", "is_email_verified")


@admin.register(MarketplaceBuyerToken)
class MarketplaceBuyerTokenAdmin(admin.ModelAdmin):
    list_display = ("buyer", "token", "is_revoked", "created_at", "last_used_at", "expires_at")
    search_fields = ("buyer__email", "token")
    list_filter = ("is_revoked",)


# =============================
# Category Admin
# =============================
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user")
    search_fields = ("name",)
    list_filter = ("user",)


# =============================
# Product Admin
# =============================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "category",
        "selling_price",
        "stock",
        "low_stock_threshold",
        "created_at",
    )
    search_fields = ("name",)
    list_filter = ("category", "user")
    readonly_fields = ("created_at",)


# =============================
# Customer Admin
# =============================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "phone", "email", "religion", "tribe", "user")
    search_fields = ("first_name", "last_name", "phone", "email", "religion", "tribe")
    list_filter = ("user",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "category", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("name", "email", "message")
    readonly_fields = ("created_at",)


# =============================
# SaleItem Inline
# =============================
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


# =============================
# Sale Admin
# =============================
@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "sales_channel",
        "handled_by_shopboy",
        "customer",
        "total_amount",
        "total_profit",
        "created_at",
    )
    list_filter = ("user", "sales_channel", "handled_by_shopboy", "created_at")
    search_fields = ("user__username", "handled_by_shopboy__full_name", "handled_by_shopboy__username")
    inlines = [SaleItemInline]
    readonly_fields = ("created_at",)


# =============================
# Expense Admin
# =============================
@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "amount", "user", "created_at")
    list_filter = ("user",)
    search_fields = ("title",)
    readonly_fields = ("created_at",)

# =============================
# Investor Admin
# =============================
@admin.register(Investor)
class InvestorAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "ownership_percent", "investment_amount", "is_active", "created_at")
    search_fields = ("name", "email")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "last_login")


# =============================
# ShopBoy Admin
# =============================
@admin.register(ShopBoy)
class ShopBoyAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "username",
        "user",
        "can_use_marketplace",
        "is_active",
    )
    list_filter = ("can_use_marketplace", "is_active")
    search_fields = ("full_name", "username")


@admin.register(MarketplaceShopProfile)
class MarketplaceShopProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "location", "is_verified", "rating", "created_at")
    list_filter = ("is_verified", "category", "location")
    search_fields = ("user__username", "user__business_name")


@admin.register(MarketplaceSettings)
class MarketplaceSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "assigned_shopboy", "is_enabled", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("user__username",)


class MarketplaceOrderItemInline(admin.TabularInline):
    model = MarketplaceOrderItem
    extra = 0


@admin.register(MarketplaceOrder)
class MarketplaceOrderAdmin(admin.ModelAdmin):
    list_display = ("public_id", "shop_owner", "assigned_shopboy", "buyer_name", "status", "total_amount", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("public_id", "buyer_name", "buyer_contact")
    inlines = [MarketplaceOrderItemInline]


@admin.register(MarketplaceChatMessage)
class MarketplaceChatMessageAdmin(admin.ModelAdmin):
    list_display = ("order", "sender_type", "created_at")
    list_filter = ("sender_type", "created_at")
