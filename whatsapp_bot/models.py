import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class WhatsAppUser(models.Model):
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    display_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    bot_state = models.CharField(max_length=60, blank=True, default="")
    session_data = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name or self.phone_number


class Wallet(models.Model):
    user = models.OneToOneField(WhatsAppUser, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.phone_number} - {self.balance}"


class ResellerProfile(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.OneToOneField(WhatsAppUser, on_delete=models.CASCADE, related_name="reseller_profile")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    business_name = models.CharField(max_length=150, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    def __str__(self):
        return f"{self.user.phone_number} - {self.status}"


class DataPlan(models.Model):
    NETWORK_MTN = "mtn"
    NETWORK_AIRTEL = "airtel"
    NETWORK_GLO = "glo"
    NETWORK_9MOBILE = "9mobile"
    NETWORK_CHOICES = [
        (NETWORK_MTN, "MTN"),
        (NETWORK_AIRTEL, "Airtel"),
        (NETWORK_GLO, "Glo"),
        (NETWORK_9MOBILE, "9mobile"),
    ]

    network = models.CharField(max_length=20, choices=NETWORK_CHOICES, db_index=True)
    plan_name = models.CharField(max_length=120)
    size = models.CharField(max_length=60)
    validity = models.CharField(max_length=60)
    vtu_plan_code = models.CharField(max_length=80)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    normal_price = models.DecimalField(max_digits=12, decimal_places=2)
    reseller_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["network", "normal_price", "id"]

    def __str__(self):
        return f"{self.get_network_display()} {self.size} - {self.validity}"


class Transaction(models.Model):
    TYPE_DATA = "data"
    TYPE_AIRTIME = "airtime"
    TYPE_CHOICES = [
        (TYPE_DATA, "Data"),
        (TYPE_AIRTIME, "Airtime"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    reference = models.CharField(max_length=40, unique=True, default=uuid.uuid4)
    user = models.ForeignKey(WhatsAppUser, on_delete=models.CASCADE, related_name="transactions")
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_DATA)
    data_plan = models.ForeignKey(DataPlan, on_delete=models.SET_NULL, null=True, blank=True)
    recipient_phone = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider_reference = models.CharField(max_length=120, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.status}"


class Payment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    reference = models.CharField(max_length=80, unique=True, default=uuid.uuid4)
    user = models.ForeignKey(WhatsAppUser, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    gateway = models.CharField(max_length=40, blank=True, default="payment_gateway")
    gateway_reference = models.CharField(max_length=120, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.status}"
