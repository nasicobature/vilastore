from django.db import models
import uuid
from decimal import Decimal
from datetime import timedelta
from io import BytesIO
from django.core.files.base import ContentFile
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password, identify_hasher
from PIL import Image, ImageOps
from django.utils import timezone


# Create your models here.


def _generate_referral_code() -> str:
    return uuid.uuid4().hex[:10].upper()


def _optimize_image_field(image_field, *, max_size=1200, quality=80, suffix="_opt"):
    if not image_field:
        return

    name = image_field.name or ""
    if suffix in name:
        return

    try:
        img = Image.open(image_field)
    except Exception:
        return

    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)

    if "." in name:
        base = name.rsplit(".", 1)[0]
    else:
        base = name
    new_name = f"{base}{suffix}.jpg"
    image_field.save(new_name, ContentFile(buffer.read()), save=False)


class Agent(models.Model):
    full_name = models.CharField(max_length=150)
    username = models.CharField(max_length=80, unique=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    password = models.CharField(max_length=255)
    referral_code = models.CharField(max_length=20, unique=True, blank=True)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.15"))
    is_active = models.BooleanField(default=True)
    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_code_sent_at = models.DateTimeField(null=True, blank=True)
    reset_code = models.CharField(max_length=6, blank=True)
    reset_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.password:
            try:
                identify_hasher(self.password)
            except Exception:
                self.password = make_password(self.password)

        if not self.referral_code:
            referral = _generate_referral_code()
            while Agent.objects.filter(referral_code=referral).exists():
                referral = _generate_referral_code()
            self.referral_code = referral

        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


class User(AbstractUser):
    ACCOUNT_TYPE_SHOP = "shop"
    ACCOUNT_TYPE_HOUSING = "housing"
    ACCOUNT_TYPE_CHOICES = [
        (ACCOUNT_TYPE_SHOP, "Shop Owner"),
        (ACCOUNT_TYPE_HOUSING, "Housing Owner"),
    ]

    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default=ACCOUNT_TYPE_SHOP)
    # Business Information
    business_name = models.CharField(max_length=200)
    business_type = models.CharField(max_length=100)
    state = models.CharField(max_length=100)

    # Contact / Extra Info
    phone = models.CharField(max_length=20)
    address = models.TextField()
    country = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100, blank=True, default="")
    bank_account_number = models.CharField(max_length=30, blank=True, default="")
    bank_account_name = models.CharField(max_length=120, blank=True, default="")

    # Profile
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)

    # Subscription
    plan = models.CharField(max_length=50)
    is_paid = models.BooleanField(default=False)

    # Tax profiling
    fixed_assets = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_professional_services = models.BooleanField(default=False)

    # Email Verification
    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_code_sent_at = models.DateTimeField(null=True, blank=True)

    # Shop Code (for shop boy login)
    shop_code = models.CharField(max_length=20, unique=True, null=True, blank=True)

    # Agent referral
    referred_by_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name="referred_users")
    
    
    subscription_active_until = models.DateField(null=True, blank=True)
    monthly_fee = models.DecimalField(default=4000, max_digits=10, decimal_places=2)

    # Offline staff sale controls
    allow_staff_offline_sales = models.BooleanField(default=True)
    offline_staff_max_sale_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offline_staff_pin = models.CharField(max_length=12, blank=True, default="")
    offline_staff_max_pending_sales = models.PositiveIntegerField(default=20)
    offline_sync_warning_hours = models.PositiveIntegerField(default=24)

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if self.profile_image:
            _optimize_image_field(self.profile_image, max_size=600, quality=80)
        super().save(*args, **kwargs)

    @property
    def is_housing_account(self):
        return self.account_type == self.ACCOUNT_TYPE_HOUSING

    @property
    def is_shop_account(self):
        return self.account_type == self.ACCOUNT_TYPE_SHOP
    
    

class Category(models.Model):
    name = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey("ShopBranch", on_delete=models.CASCADE, null=True, blank=True, related_name="categories")

    def __str__(self):
        return self.name
    
    
class ShopBranch(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=24, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_branch_name_per_user"),
        ]

    def __str__(self):
        return f"{self.user.business_name or self.user.username} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            raw = "".join(ch for ch in (self.name or "").upper() if ch.isalnum())[:6] or "BRANCH"
            candidate = raw
            counter = 1
            while ShopBranch.objects.exclude(pk=self.pk).filter(user=self.user, code=candidate).exists():
                counter += 1
                suffix = str(counter)
                candidate = f"{raw[: max(1, 6 - len(suffix))]}{suffix}"
            self.code = candidate

        super().save(*args, **kwargs)

        if self.is_default:
            ShopBranch.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)
        elif not ShopBranch.objects.filter(user=self.user, is_default=True).exists():
            ShopBranch.objects.filter(pk=self.pk).update(is_default=True)
            self.is_default = True


class Shop(models.Model):
    """A shop/business entity, decoupled from the User who manages it.

    Phase 1 of separating Shop Management from the shared User table:
    every existing shop-owner User is backfilled into exactly one Shop
    row (see core/management/commands/backfill_shop_membership.py).
    Shop-specific fields (business_name, shop_code, billing) still live
    on User for now -- moving reads/writes off User and onto Shop is a
    later phase, done once ShopMembership is wired through the call
    sites that currently assume a direct User foreign key.
    """

    business_name = models.CharField(max_length=200, blank=True)
    shop_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.business_name or self.shop_code or f"Shop #{self.pk}"


class ShopMembership(models.Model):
    """Links a user to a specific Shop with a role.

    Going forward, new Shop-side models should reference ShopMembership
    (or Shop, via a membership lookup) instead of taking a direct
    ForeignKey to User -- see the module docstring note on Shop.
    """

    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_STAFF, "Staff"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shop_memberships")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="memberships")
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OWNER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "shop"], name="unique_shop_membership_per_user"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.shop} ({self.role})"


class Product(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True)

    image = models.ImageField(
        upload_to='products/',
        blank=True,
        null=True
    )

    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)

    VAT_STANDARD = "standard"
    VAT_ZERO = "zero"
    VAT_EXEMPT = "exempt"
    VAT_STATUS_CHOICES = [
        (VAT_STANDARD, "Standard (7.5%)"),
        (VAT_ZERO, "Zero-rated (0%)"),
        (VAT_EXEMPT, "Exempt"),
    ]
    vat_status = models.CharField(max_length=10, choices=VAT_STATUS_CHOICES, default=VAT_STANDARD)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code"],
                condition=~models.Q(code=""),
                name="unique_product_code_per_user",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.image:
            _optimize_image_field(self.image, max_size=1200, quality=80)
        super().save(*args, **kwargs)
    
    
class BranchInventory(models.Model):
    branch = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name="inventory_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="branch_inventory")
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    track_separately = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "product"], name="unique_branch_product_inventory"),
        ]

    def __str__(self):
        return f"{self.branch.name} - {self.product.name}"


class Customer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="customers")

    RELIGION_NOT_SPECIFIED = ""
    RELIGION_MUSLIM = "muslim"
    RELIGION_CHRISTIAN = "christian"
    RELIGION_OTHER = "other"

    RELIGION_CHOICES = [
        (RELIGION_NOT_SPECIFIED, "Not specified"),
        (RELIGION_MUSLIM, "Muslim"),
        (RELIGION_CHRISTIAN, "Christian"),
        (RELIGION_OTHER, "Other"),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    religion = models.CharField(max_length=20, choices=RELIGION_CHOICES, blank=True, default="")
    tribe = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Feedback(models.Model):
    CATEGORY_GENERAL = "general"
    CATEGORY_BUG = "bug"
    CATEGORY_FEATURE = "feature"
    CATEGORY_SUPPORT = "support"

    CATEGORY_CHOICES = [
        (CATEGORY_GENERAL, "General Feedback"),
        (CATEGORY_BUG, "Bug Report"),
        (CATEGORY_FEATURE, "Feature Request"),
        (CATEGORY_SUPPORT, "Support"),
    ]

    name = models.CharField(max_length=120)
    email = models.EmailField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category})"
    
class Sale(models.Model):
    CHANNEL_OWNER_POS = "owner_pos"
    CHANNEL_MARKETPLACE = "marketplace"
    CHANNEL_SHOPBOY_PORTAL = "shopboy_portal"
    CHANNEL_CUSTOMER_SCAN = "customer_scan"

    CHANNEL_CHOICES = [
        (CHANNEL_OWNER_POS, "Owner POS"),
        (CHANNEL_MARKETPLACE, "Marketplace"),
        (CHANNEL_SHOPBOY_PORTAL, "Shop Boy Portal"),
        (CHANNEL_CUSTOMER_SCAN, "Customer Scanner"),
    ]

    PAYMENT_PAID = "paid"
    PAYMENT_LOAN = "loan"
    PAYMENT_PARTIAL = "partial"

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_LOAN, "Loan (Unpaid)"),
        (PAYMENT_PARTIAL, "Partially Paid"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=200, blank=True, default="")
    sales_channel = models.CharField(max_length=30, choices=CHANNEL_CHOICES, default=CHANNEL_OWNER_POS)
    handled_by_shopboy = models.ForeignKey("ShopBoy", on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_sales")

    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    total_profit = models.DecimalField(max_digits=14, decimal_places=2)
    vat_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PAID)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def remaining_balance(self):
        try:
            balance = Decimal(self.total_amount) - Decimal(self.amount_paid or Decimal("0.00"))
        except Exception:
            return Decimal("0.00")
        if balance < 0:
            return Decimal("0.00")
        return balance

    @property
    def display_customer_name(self):
        if self.customer:
            return f"{self.customer.first_name} {self.customer.last_name}".strip()
        return (self.customer_name or "").strip()
    

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    price = models.DecimalField(max_digits=14, decimal_places=2)
    profit = models.DecimalField(max_digits=14, decimal_places=2)
    vat_status = models.CharField(max_length=10, choices=Product.VAT_STATUS_CHOICES, default=Product.VAT_STANDARD)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_applicable = models.BooleanField(default=False)


class Investor(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    investment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ownership_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.password:
            try:
                identify_hasher(self.password)
            except Exception:
                self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Expense(models.Model):

    CATEGORY_CHOICES = [
        ("Transport", "Transport"),
        ("Rent", "Rent"),
        ("Electricity", "Electricity"),
        ("Salaries", "Salaries"),
        ("Supplies", "Supplies"),
        ("Maintenance", "Maintenance"),
        ("Marketing", "Marketing"),
        ("Other", "Other"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="Other")
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class AIReceiptScan(models.Model):
    STATUS_PARSED = "parsed"
    STATUS_APPLIED = "applied"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_CHOICES = [
        (STATUS_PARSED, "Parsed"),
        (STATUS_APPLIED, "Applied to inventory"),
        (STATUS_NEEDS_REVIEW, "Needs review"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_receipt_scans")
    uploaded_by_shopboy = models.ForeignKey("ShopBoy", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_receipt_scans")
    image = models.ImageField(upload_to="ai_receipts/", null=True, blank=True)
    raw_text = models.TextField(blank=True)
    parsed_items = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEEDS_REVIEW)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AI receipt scan #{self.id} - {self.user.username}"


class AIAssistantMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_assistant_messages")
    question = models.TextField()
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"AI assistant message #{self.id} - {self.user.username}"
    
class ShopBoy(models.Model):
    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_STAFF, "Staff / Shopboy"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_members")

    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)

    can_use_marketplace = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name


class MarketplaceShopProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="marketplace_profile")
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, blank=True)
    is_verified = models.BooleanField(default=False)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=4.50)
    logo = models.ImageField(upload_to="marketplace/logos/", null=True, blank=True)
    cover_image = models.ImageField(upload_to="marketplace/covers/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.business_name or self.user.username} Marketplace Profile"

    def save(self, *args, **kwargs):
        if self.logo:
            _optimize_image_field(self.logo, max_size=600, quality=80)
        if self.cover_image:
            _optimize_image_field(self.cover_image, max_size=1600, quality=80)
        super().save(*args, **kwargs)


class MarketplaceSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="marketplace_settings")
    assigned_shopboy = models.ForeignKey(ShopBoy, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_assignments")
    is_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Marketplace Settings"


class HouseListing(models.Model):
    MODE_RENT = "rent"
    MODE_SALE = "sale"
    LISTING_MODE_CHOICES = [
        (MODE_RENT, "For Rent"),
        (MODE_SALE, "For Sale"),
    ]

    TYPE_APARTMENT = "apartment"
    TYPE_DUPLEX = "duplex"
    TYPE_STUDIO = "studio"
    TYPE_SELF_CONTAIN = "self_contain"
    TYPE_ROOM = "room"
    TYPE_OFFICE = "office"
    TYPE_SHOP = "shop"
    TYPE_OTHER = "other"
    PROPERTY_TYPE_CHOICES = [
        (TYPE_APARTMENT, "Apartment"),
        (TYPE_DUPLEX, "Duplex"),
        (TYPE_STUDIO, "Studio"),
        (TYPE_SELF_CONTAIN, "Self Contain"),
        (TYPE_ROOM, "Single Room"),
        (TYPE_OFFICE, "Office Space"),
        (TYPE_SHOP, "Shop Space"),
        (TYPE_OTHER, "Other"),
    ]

    STATUS_AVAILABLE = "available"
    STATUS_OCCUPIED = "occupied"
    STATUS_PARTIAL = "partial"
    STATUS_RESERVED = "reserved"
    STATUS_MAINTENANCE = "maintenance"
    AVAILABILITY_STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_OCCUPIED, "Occupied"),
        (STATUS_PARTIAL, "Partially Occupied"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_MAINTENANCE, "Under Maintenance"),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="house_listings", null=True, blank=True)
    listing_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name="property_listings")
    managed_by_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name="managed_house_listings")
    title = models.CharField(max_length=200)
    listing_mode = models.CharField(max_length=10, choices=LISTING_MODE_CHOICES, default=MODE_RENT)
    property_type = models.CharField(max_length=30, choices=PROPERTY_TYPE_CHOICES, default=TYPE_APARTMENT)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    location = models.CharField(max_length=255)
    rooms_count = models.PositiveIntegerField(default=1)
    spaces_available = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)
    availability_status = models.CharField(max_length=20, choices=AVAILABILITY_STATUS_CHOICES, default=STATUS_AVAILABLE)
    is_approved = models.BooleanField(default=True)
    listed_in_marketplace = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_available(self):
        return self.availability_status in {self.STATUS_AVAILABLE, self.STATUS_PARTIAL}

    @property
    def display_owner_name(self):
        if self.owner:
            return self.owner.business_name or self.owner.username
        if self.listing_agent:
            return self.listing_agent.full_name
        return "VilaStore"

    @property
    def display_owner_phone(self):
        if self.owner:
            return self.owner.phone
        if self.listing_agent:
            return self.listing_agent.phone
        return ""

    @property
    def display_owner_address(self):
        if self.owner:
            return self.owner.address
        return self.location

    @property
    def primary_image(self):
        primary = self.images.filter(is_primary=True).first()
        if primary:
            return primary
        return self.images.first()

    @property
    def profile_type_label(self):
        property_label = self.get_property_type_display()
        room_based_types = {
            self.TYPE_APARTMENT,
            self.TYPE_DUPLEX,
            self.TYPE_ROOM,
        }
        if self.property_type in room_based_types and self.rooms_count:
            room_label = "Bedroom" if self.rooms_count == 1 else "Bedrooms"
            return f"{self.rooms_count} {room_label} {property_label}"
        if self.property_type == self.TYPE_STUDIO:
            return "Studio Apartment"
        if self.property_type == self.TYPE_SELF_CONTAIN:
            return "Self Contain"
        if self.property_type == self.TYPE_OFFICE:
            return "Office Space"
        if self.property_type == self.TYPE_SHOP:
            return "Shop Space"
        return property_label

    @property
    def units_summary(self):
        if self.spaces_available == 1:
            return "1 unit available"
        return f"{self.spaces_available} units available"

    @property
    def area_label(self):
        location = (self.location or "").strip()
        if not location:
            return "Location on request"
        parts = [part.strip() for part in location.split(",") if part.strip()]
        if len(parts) >= 2:
            return ", ".join(parts[-2:])
        return parts[0]

    @property
    def marketplace_agent(self):
        return self.managed_by_agent or self.listing_agent


class HouseListingImage(models.Model):
    house = models.ForeignKey(HouseListing, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="housing/listings/")
    caption = models.CharField(max_length=120, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]

    def __str__(self):
        return f"{self.house.title} image"

    def save(self, *args, **kwargs):
        if self.image:
            _optimize_image_field(self.image, max_size=1600, quality=82)
        super().save(*args, **kwargs)


class TenantRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenant_records")
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    emergency_contact = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class RentalRecord(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_TERMINATED = "terminated"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_TERMINATED, "Terminated"),
    ]

    PAYMENT_CURRENT = "current"
    PAYMENT_DUE = "due"
    PAYMENT_OVERDUE = "overdue"
    PAYMENT_PARTIAL = "partial"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_CURRENT, "Current"),
        (PAYMENT_DUE, "Due"),
        (PAYMENT_OVERDUE, "Overdue"),
        (PAYMENT_PARTIAL, "Partially Paid"),
    ]

    house = models.ForeignKey(HouseListing, on_delete=models.CASCADE, related_name="rentals")
    tenant = models.ForeignKey(TenantRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name="rentals")
    tenant_name = models.CharField(max_length=150)
    tenant_phone = models.CharField(max_length=30, blank=True)
    tenant_email = models.EmailField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2)
    next_due_date = models.DateField(null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_CURRENT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["end_date", "-created_at"]

    def __str__(self):
        return f"{self.house.title} - {self.tenant_name}"

    @property
    def reminder_date(self):
        return self.end_date - timedelta(days=60)

    @property
    def days_until_expiry(self):
        return (self.end_date - timezone.localdate()).days

    @property
    def needs_expiry_reminder(self):
        today = timezone.localdate()
        return (
            self.status == self.STATUS_ACTIVE
            and self.reminder_date <= today <= self.end_date
            and self.reminder_sent_at is None
        )


class RentalPayment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_PARTIAL = "partial"
    STATUS_OVERDUE = "overdue"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_PARTIAL, "Partially Paid"),
        (STATUS_OVERDUE, "Overdue"),
    ]

    rental = models.ForeignKey(RentalRecord, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField()
    paid_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-due_date", "-created_at"]

    def __str__(self):
        return f"{self.rental.tenant_name} - {self.amount}"


class MarketplaceBuyer(models.Model):
    ROLE_CUSTOMER = "customer"
    ROLE_RIDER = "rider"
    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_RIDER, "Rider"),
    ]

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True, default="")
    password = models.CharField(max_length=255)
    registration_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_code_sent_at = models.DateTimeField(null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)
    phone_verification_code = models.CharField(max_length=6, blank=True)
    phone_code_sent_at = models.DateTimeField(null=True, blank=True)
    reset_code = models.CharField(max_length=6, blank=True)
    reset_sent_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.email


class MarketplaceBuyerToken(models.Model):
    buyer = models.ForeignKey(MarketplaceBuyer, on_delete=models.CASCADE, related_name="tokens")
    token = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.buyer.email} ({self.token[:6]}...)"


class CustomerScanCart(models.Model):
    cart_token = models.CharField(max_length=80, unique=True, default=uuid.uuid4)
    shop_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="customer_scan_carts")
    buyer = models.ForeignKey(MarketplaceBuyer, on_delete=models.SET_NULL, null=True, blank=True, related_name="scan_carts")
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="customer_scan_carts")
    data = models.JSONField(default=dict, blank=True)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    pending_sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="scan_cart")
    is_checked_out = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DeliveryRider(models.Model):
    id = models.BigAutoField(primary_key=True)

    ID_TYPE_NIN = "nin"
    ID_TYPE_VOTER = "voter"
    ID_TYPE_DRIVER = "driver"
    ID_TYPE_CHOICES = [
        (ID_TYPE_NIN, "National ID (NIN)"),
        (ID_TYPE_VOTER, "Voter's Card"),
        (ID_TYPE_DRIVER, "Driver's License"),
    ]

    VEHICLE_BIKE = "bike"
    VEHICLE_CAR = "car"
    VEHICLE_TRICYCLE = "tricycle"
    VEHICLE_CHOICES = [
        (VEHICLE_BIKE, "Bike"),
        (VEHICLE_CAR, "Car"),
        (VEHICLE_TRICYCLE, "Tricycle"),
    ]

    RIDER_PERSONAL = "personal"
    RIDER_COMPANY = "company"
    RIDER_TYPE_CHOICES = [
        (RIDER_PERSONAL, "Personal Rider"),
        (RIDER_COMPANY, "Company Rider"),
    ]

    buyer = models.OneToOneField(
        MarketplaceBuyer, on_delete=models.CASCADE, related_name="delivery_rider"
    )
    company = models.ForeignKey("DeliveryCompany", on_delete=models.SET_NULL, null=True, blank=True, related_name="riders")
    rider_type = models.CharField(max_length=20, choices=RIDER_TYPE_CHOICES, default=RIDER_PERSONAL)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    home_address = models.CharField(max_length=255, blank=True)
    id_type = models.CharField(max_length=20, choices=ID_TYPE_CHOICES, blank=True)
    id_number = models.CharField(max_length=100, blank=True)
    id_document = models.ImageField(upload_to="delivery/ids/", null=True, blank=True)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES, blank=True)
    plate_number = models.CharField(max_length=30, blank=True)
    vehicle_color = models.CharField(max_length=50, blank=True)
    vehicle_model = models.CharField(max_length=80, blank=True)
    profile_photo = models.ImageField(upload_to="delivery/profile/", null=True, blank=True)
    vehicle_photo = models.ImageField(upload_to="delivery/vehicle/", null=True, blank=True)
    plate_photo = models.ImageField(upload_to="delivery/plate/", null=True, blank=True)
    city = models.CharField(max_length=80, blank=True)
    operating_areas = models.TextField(blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=30, blank=True)
    account_name = models.CharField(max_length=120, blank=True)
    allow_direct_call = models.BooleanField(default=True)
    terms_accepted = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)
    current_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name or self.buyer.email


class DeliveryCompany(models.Model):
    id = models.BigAutoField(primary_key=True)

    owner = models.OneToOneField(MarketplaceBuyer, on_delete=models.CASCADE, related_name="delivery_company")
    company_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80)
    operating_areas = models.TextField(blank=True)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=30)
    account_name = models.CharField(max_length=120)
    terms_accepted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name


class DeliveryRequest(models.Model):
    id = models.BigAutoField(primary_key=True)

    STATUS_REQUESTED = "requested"
    STATUS_RIDER_SELECTED = "rider_selected"
    STATUS_ACCEPTED = "accepted"
    STATUS_PICKED_UP = "picked_up"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_RIDER_SELECTED, "Rider Selected"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_PICKED_UP, "Picked Up"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    buyer = models.ForeignKey(MarketplaceBuyer, on_delete=models.CASCADE, related_name="delivery_requests")
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_requests")
    rider = models.ForeignKey(
        DeliveryRider, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_requests"
    )
    pickup_address = models.CharField(max_length=255)
    dropoff_address = models.CharField(max_length=255)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_km = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Delivery {self.public_id}"


class AuthToken(models.Model):
    ROLE_OWNER = "owner"
    ROLE_SHOPBOY = "shopboy"
    ROLE_AGENT = "agent"

    ROLE_CHOICES = [
        (ROLE_OWNER, "Shop Owner"),
        (ROLE_SHOPBOY, "Shop Boy"),
        (ROLE_AGENT, "Agent"),
    ]

    token = models.CharField(max_length=80, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="auth_tokens")
    shopboy = models.ForeignKey(ShopBoy, on_delete=models.CASCADE, null=True, blank=True, related_name="auth_tokens")
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, null=True, blank=True, related_name="auth_tokens")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.role} ({self.token[:6]}...)"


class ShopboyCart(models.Model):
    token = models.OneToOneField(AuthToken, on_delete=models.CASCADE, related_name="shopboy_cart")
    data = models.JSONField(default=dict, blank=True)
    last_sale_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ShopboyCart ({self.token_id})"


class OwnerCart(models.Model):
    token = models.OneToOneField(AuthToken, on_delete=models.CASCADE, related_name="owner_cart")
    data = models.JSONField(default=dict, blank=True)
    last_sale_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OwnerCart ({self.token_id})"


class MarketplaceOrder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_PAID = "paid"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_PAID, "Paid"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    access_token = models.UUIDField(default=uuid.uuid4, editable=False)
    shop_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="marketplace_orders")
    branch = models.ForeignKey(ShopBranch, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_orders")
    buyer = models.ForeignKey(MarketplaceBuyer, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    assigned_shopboy = models.ForeignKey(ShopBoy, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_orders")
    buyer_name = models.CharField(max_length=255)
    buyer_contact = models.CharField(max_length=255)
    buyer_address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale = models.OneToOneField(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_order")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Marketplace Order {self.public_id}"


class MarketplaceOrderItem(models.Model):
    order = models.ForeignKey(MarketplaceOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    def line_total(self):
        return self.unit_price * self.quantity


class MarketplaceChatMessage(models.Model):
    SENDER_BUYER = "buyer"
    SENDER_SELLER = "seller"
    SENDER_SYSTEM = "system"

    SENDER_CHOICES = [
        (SENDER_BUYER, "Buyer"),
        (SENDER_SELLER, "Seller"),
        (SENDER_SYSTEM, "System"),
    ]

    order = models.ForeignKey(MarketplaceOrder, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES, default=SENDER_BUYER)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.order.public_id} - {self.sender_type}"


class HouseInquiry(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    access_token = models.UUIDField(default=uuid.uuid4, editable=False)
    house = models.ForeignKey(HouseListing, on_delete=models.CASCADE, related_name="inquiries")
    buyer = models.ForeignKey(MarketplaceBuyer, on_delete=models.SET_NULL, null=True, blank=True, related_name="house_inquiries")
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="house_inquiries")
    buyer_name = models.CharField(max_length=255)
    buyer_contact = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return f"House Inquiry {self.public_id}"


class HouseInquiryMessage(models.Model):
    SENDER_BUYER = "buyer"
    SENDER_SELLER = "seller"
    SENDER_SYSTEM = "system"

    SENDER_CHOICES = [
        (SENDER_BUYER, "Buyer"),
        (SENDER_SELLER, "Seller"),
        (SENDER_SYSTEM, "System"),
    ]

    inquiry = models.ForeignKey(HouseInquiry, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES, default=SENDER_BUYER)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.inquiry.public_id} - {self.sender_type}"
