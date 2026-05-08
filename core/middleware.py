from django.contrib import messages
from django.shortcuts import redirect

from .subscription import subscription_is_active


EXEMPT_PATH_PREFIXES = (
    "/login/",
    "/logout/",
    "/signup/",
    "/send-code/",
    "/verify-code/",
    "/forgot-password/",
    "/subscription/payment/",
    "/admin/",
    "/admin-portal/",
    "/edu/",
    "/shopboy/",
    "/marketplace/",
    "/static/",
    "/media/",
)


class SubscriptionRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not subscription_is_active(request.user):
            path = request.path or ""
            if not path.startswith(EXEMPT_PATH_PREFIXES):
                if hasattr(request, "_messages"):
                    messages.error(request, "Subscription payment required. Please make the payment to continue.")
                return redirect("subscription_payment")
        return self.get_response(request)
