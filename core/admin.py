from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User,
    Category,
    Product,
    Customer,
    CustomerScanCart,
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
    HouseListing,
    HouseListingImage,
    Investor,
    Feedback,
    Agent,
    RentalPayment,
    RentalRecord,
    TenantRecord,
    AIReceiptScan,
    AIAssistantMessage,
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
                "bank_name",
                "bank_account_number",
                "bank_account_name",
                "profile_image",
                "plan",
                "is_paid",
                "subscription_active_until",
                "monthly_fee",
                "is_email_verified",
                "shop_code",
                "referred_by_agent",
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
        "referred_by_agent",
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


@admin.register(CustomerScanCart)
class CustomerScanCartAdmin(admin.ModelAdmin):
    list_display = ("cart_token", "shop_owner", "customer_name", "is_checked_out", "pending_sale", "created_at")
    list_filter = ("is_checked_out", "created_at")
    search_fields = ("cart_token", "shop_owner__username", "shop_owner__business_name", "customer_name", "customer_phone")


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


@admin.register(AIReceiptScan)
class AIReceiptScanAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "raw_text")
    readonly_fields = ("created_at",)


@admin.register(AIAssistantMessage)
class AIAssistantMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at")
    search_fields = ("user__username", "question", "answer")
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


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "username", "email", "referral_code", "commission_rate", "is_active", "created_at")
    search_fields = ("full_name", "username", "email", "referral_code")
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


class HouseListingImageInline(admin.TabularInline):
    model = HouseListingImage
    extra = 0


@admin.register(HouseListing)
class HouseListingAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "property_type", "location", "price", "availability_status", "listed_in_marketplace", "created_at")
    list_filter = ("property_type", "availability_status", "listed_in_marketplace", "is_active")
    search_fields = ("title", "location", "description", "owner__username", "owner__business_name")
    inlines = [HouseListingImageInline]


@admin.register(TenantRecord)
class TenantRecordAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "phone", "email", "created_at")
    list_filter = ("user",)
    search_fields = ("full_name", "phone", "email")


class RentalPaymentInline(admin.TabularInline):
    model = RentalPayment
    extra = 0


@admin.register(RentalRecord)
class RentalRecordAdmin(admin.ModelAdmin):
    list_display = ("house", "tenant_name", "start_date", "end_date", "monthly_rent", "payment_status", "status")
    list_filter = ("status", "payment_status", "house__owner")
    search_fields = ("tenant_name", "tenant_phone", "tenant_email", "house__title")
    inlines = [RentalPaymentInline]


@admin.register(RentalPayment)
class RentalPaymentAdmin(admin.ModelAdmin):
    list_display = ("rental", "amount", "due_date", "paid_on", "status", "created_at")
    list_filter = ("status", "due_date", "rental__house__owner")
    search_fields = ("rental__tenant_name", "rental__house__title", "notes")
