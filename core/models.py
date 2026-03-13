from django.db import models
import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password, identify_hasher


# Create your models here.


def _generate_referral_code() -> str:
    return uuid.uuid4().hex[:10].upper()


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
    # Business Information
    business_name = models.CharField(max_length=200)
    business_type = models.CharField(max_length=100)
    state = models.CharField(max_length=100)

    # Contact / Extra Info
    phone = models.CharField(max_length=20)
    address = models.TextField()
    country = models.CharField(max_length=100)

    # Profile
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)

    # Subscription
    plan = models.CharField(max_length=50)
    is_paid = models.BooleanField(default=False)

    # Email Verification
    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_code_sent_at = models.DateTimeField(null=True, blank=True)

    # Shop Code (for shop boy login)
    shop_code = models.CharField(max_length=20, unique=True, null=True, blank=True)

    # Agent referral
    referred_by_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name="referred_users")
    
    
    subscription_active_until = models.DateField(null=True, blank=True)
    monthly_fee = models.DecimalField(default=1000, max_digits=10, decimal_places=2)

    def __str__(self):
        return self.username
    
    

class Category(models.Model):
    name = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.name
    
    
class Product(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=255)

    image = models.ImageField(
        upload_to='products/',
        blank=True,
        null=True
    )

    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
    
class Customer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

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

    CHANNEL_CHOICES = [
        (CHANNEL_OWNER_POS, "Owner POS"),
        (CHANNEL_MARKETPLACE, "Marketplace"),
        (CHANNEL_SHOPBOY_PORTAL, "Shop Boy Portal"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    sales_channel = models.CharField(max_length=30, choices=CHANNEL_CHOICES, default=CHANNEL_OWNER_POS)
    handled_by_shopboy = models.ForeignKey("ShopBoy", on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_sales")

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_profit = models.DecimalField(max_digits=10, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    profit = models.DecimalField(max_digits=10, decimal_places=2)
    

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
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="Other")
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
    
class ShopBoy(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=255)

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


class MarketplaceSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="marketplace_settings")
    assigned_shopboy = models.ForeignKey(ShopBoy, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_assignments")
    is_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Marketplace Settings"


class MarketplaceBuyer(models.Model):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_code_sent_at = models.DateTimeField(null=True, blank=True)
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
