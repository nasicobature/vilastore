from django.utils import timezone


def subscription_is_active(user, today=None):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    if not user.subscription_active_until:
        return False
    if today is None:
        today = timezone.localdate()
    return user.subscription_active_until >= today
