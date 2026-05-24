from django.urls import path

from . import views

urlpatterns = [
    path("webhook/whatsapp/", views.whatsapp_webhook, name="whatsapp_webhook"),
    path("webhook/payment/", views.payment_webhook, name="payment_webhook"),
    path("api/data-plans/", views.data_plans_api, name="data_plans_api"),
    path("api/transactions/", views.transaction_history_api, name="transaction_history_api"),
]
