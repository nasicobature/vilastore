from django.contrib import admin, messages
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import DataPlan, Payment, ResellerProfile, Transaction, Wallet, WhatsAppUser
from .services.vtu import VTUClient


@admin.register(WhatsAppUser)
class WhatsAppUserAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "display_name", "bot_state", "is_active", "last_seen_at", "created_at")
    search_fields = ("phone_number", "display_name")
    list_filter = ("is_active", "bot_state")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__phone_number",)


@admin.register(ResellerProfile)
class ResellerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business_name", "status", "approved_at", "created_at")
    list_filter = ("status",)
    search_fields = ("user__phone_number", "business_name")
    actions = ("approve_resellers", "reject_resellers")

    @admin.action(description="Approve selected resellers")
    def approve_resellers(self, request, queryset):
        updated = queryset.update(status=ResellerProfile.STATUS_APPROVED, approved_at=timezone.now())
        self.message_user(request, f"{updated} reseller profile(s) approved.", messages.SUCCESS)

    @admin.action(description="Reject selected resellers")
    def reject_resellers(self, request, queryset):
        updated = queryset.update(status=ResellerProfile.STATUS_REJECTED)
        self.message_user(request, f"{updated} reseller profile(s) rejected.", messages.WARNING)


@admin.register(DataPlan)
class DataPlanAdmin(admin.ModelAdmin):
    list_display = ("network", "plan_name", "size", "validity", "cost_price", "normal_price", "reseller_price", "is_active")
    list_filter = ("network", "is_active")
    search_fields = ("plan_name", "size", "vtu_plan_code")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "transaction_type", "recipient_phone", "amount", "status", "created_at")
    list_filter = ("status", "transaction_type", "data_plan__network")
    search_fields = ("reference", "recipient_phone", "user__phone_number", "provider_reference")
    readonly_fields = ("provider_response",)
    actions = ("retry_failed_transactions",)

    @admin.action(description="Retry failed data transactions")
    def retry_failed_transactions(self, request, queryset):
        client = VTUClient()
        retried = 0
        for tx in queryset.filter(status=Transaction.STATUS_FAILED, transaction_type=Transaction.TYPE_DATA):
            if not tx.data_plan:
                continue
            with db_transaction.atomic():
                locked = Transaction.objects.select_for_update().get(pk=tx.pk)
                result = client.purchase_data(
                    network=locked.data_plan.network,
                    plan_code=locked.data_plan.vtu_plan_code,
                    recipient_phone=locked.recipient_phone,
                    reference=locked.reference,
                    amount=locked.amount,
                )
                locked.provider_response = result.raw
                locked.provider_reference = result.provider_reference
                locked.failure_reason = result.message if not result.success else ""
                locked.status = Transaction.STATUS_SUCCESS if result.success else Transaction.STATUS_FAILED
                locked.save(update_fields=["provider_response", "provider_reference", "failure_reason", "status", "updated_at"])
                retried += 1
        self.message_user(request, f"{retried} failed transaction(s) retried.", messages.INFO)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "status", "gateway", "processed_at", "created_at")
    list_filter = ("status", "gateway")
    search_fields = ("reference", "gateway_reference", "user__phone_number")
    readonly_fields = ("raw_payload",)
