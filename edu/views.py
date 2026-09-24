from decimal import Decimal
from datetime import timedelta
from functools import wraps
import os
import secrets

import requests
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import EDU_PACKAGE_LIMITS, RESERVED_EDU_SUBDOMAINS, EduSubscriptionSettings, Institution, Student, Staff, Fee, Payment, SalaryVoucher, Result, Profile, AcademicClass, Faculty, Department, TeacherAssignment, AcademicSession, AcademicTerm, Subject, ClassSubject, ResultSubmission, TeacherSubjectAssignment, StudentClassHistory
from core.utils.notifications import send_email


EDU_DEFAULT_BILLING_CYCLE = 'termly'
EDU_DEFAULT_PACKAGE = 'starter'
EDU_PRICING_PACKAGES = [
    ('starter', 'Starter', '1 - 50 Students', EDU_PACKAGE_LIMITS['starter'], Decimal('20000.00')),
    ('basic', 'Basic', '51 - 100 Students', EDU_PACKAGE_LIMITS['basic'], Decimal('30000.00')),
    ('growth', 'Growth', '101 - 200 Students', EDU_PACKAGE_LIMITS['growth'], Decimal('45000.00')),
    ('standard', 'Standard', '201 - 350 Students', EDU_PACKAGE_LIMITS['standard'], Decimal('65000.00')),
    ('premium', 'Premium', '351 - 500 Students', EDU_PACKAGE_LIMITS['premium'], Decimal('85000.00')),
    ('enterprise', 'Enterprise', '501 - 750 Students', EDU_PACKAGE_LIMITS['enterprise'], Decimal('110000.00')),
    ('enterprise-plus', 'Enterprise Plus', '751+ Students', EDU_PACKAGE_LIMITS['enterprise-plus'], Decimal('150000.00')),
]
EDU_REGISTRATION_PACKAGES = {item[0] for item in EDU_PRICING_PACKAGES}


def _format_edu_price(amount):
    return f'{Decimal(amount):,.0f}'


def _session_price(term_amount):
    return (Decimal(term_amount) * Decimal('3') * Decimal('0.90')).quantize(Decimal('1'))


def _normalize_edu_package(value):
    package = (value or '').strip().lower()
    valid_packages = {item[0] for item in EDU_PRICING_PACKAGES}
    if package in valid_packages:
        return package
    return EDU_DEFAULT_PACKAGE


def _edu_package_limit(package_code):
    return EDU_PACKAGE_LIMITS.get(_normalize_edu_package(package_code), EDU_PACKAGE_LIMITS[EDU_DEFAULT_PACKAGE])


def _edu_pricing_packages():
    rows = []
    for code, name, student_range, student_limit, term_amount in EDU_PRICING_PACKAGES:
        is_custom = term_amount is None
        session_amount = None if is_custom else _session_price(term_amount)
        whatsapp_text = (
            f'Hi IntelS, I want to start a Free Trial on the {name} Package ({student_range.lower()}).'
            if not is_custom
            else f'Hi IntelS, I would like to discuss the {name} package for our school.'
        )
        rows.append({
            'code': code,
            'name': name,
            'student_range': student_range,
            'student_limit': student_limit,
            'is_unlimited': code == 'enterprise-plus',
            'term_amount': term_amount,
            'term_amount_display': 'Custom Pricing' if is_custom else _format_edu_price(term_amount),
            'session_amount': session_amount,
            'session_amount_display': 'Custom Pricing' if is_custom else _format_edu_price(session_amount),
            'is_custom': is_custom,
            'whatsapp_url': 'https://wa.me/2348136373831?text=' + requests.utils.quote(whatsapp_text),
        })
    return rows


def _edu_package(package_code):
    normalized = _normalize_edu_package(package_code)
    for package in _edu_pricing_packages():
        if package['code'] == normalized:
            return package
    return _edu_pricing_packages()[0]


def _edu_subscription_plans(package_code=None):
    package = _edu_package(package_code)
    term_amount = package['term_amount'] or Decimal('0.00')
    session_amount = package['session_amount'] or Decimal('0.00')
    return {
        'termly': {
            'cycle': 'termly',
            'name': 'Per Term',
            'duration_label': '1 term',
            'duration_days': 90,
            'amount': term_amount,
            'amount_display': 'Custom Pricing' if package['is_custom'] else _format_edu_price(term_amount),
            'standard_amount': term_amount,
            'standard_amount_display': 'Custom Pricing' if package['is_custom'] else _format_edu_price(term_amount),
            'discount': Decimal('0.00'),
            'discount_display': _format_edu_price(Decimal('0.00')),
            'summary': f"{package['name']} package for {package['student_range']}.",
            'package': package,
        },
        'session': {
            'cycle': 'session',
            'name': 'Per Session',
            'duration_label': '1 session',
            'duration_days': 270,
            'amount': session_amount,
            'amount_display': 'Custom Pricing' if package['is_custom'] else _format_edu_price(session_amount),
            'standard_amount': term_amount * Decimal('3'),
            'standard_amount_display': 'Custom Pricing' if package['is_custom'] else _format_edu_price(term_amount * Decimal('3')),
            'discount': (term_amount * Decimal('3')) - session_amount,
            'discount_display': '0' if package['is_custom'] else _format_edu_price((term_amount * Decimal('3')) - session_amount),
            'summary': 'Pay for a full session and save 10%.',
            'package': package,
        },
    }


def _normalize_edu_billing_cycle(value):
    cycle = (value or '').strip().lower()
    if cycle in _edu_subscription_plans():
        return cycle
    return EDU_DEFAULT_BILLING_CYCLE


def _edu_subscription_plan(cycle):
    return _edu_subscription_plans()[_normalize_edu_billing_cycle(cycle)]


def _edu_subscription_amount(cycle, package_code=None):
    return _edu_subscription_plans(package_code)[_normalize_edu_billing_cycle(cycle)]['amount']


EDU_REGISTRATION_FEE = _edu_subscription_amount(EDU_DEFAULT_BILLING_CYCLE, EDU_DEFAULT_PACKAGE)


EMAIL_TOKEN_HOURS = 48
PASSWORD_RESET_HOURS = 2
EDU_TRIAL_DAYS = 3


def _edu_abs_url(request, path):
    return request.build_absolute_uri(path)


def _profile_login_url(profile):
    if profile and profile.institution:
        return _institution_portal_url(profile.institution)
    return '/edu/'


def _institution_portal_url(institution, admin_id=None):
    if not institution or not institution.school_code:
        return ''
    url = f'https://vilastore.store/edu/portal/{institution.school_code.lower()}'
    if admin_id:
        url += f'?admin_id={requests.utils.quote(admin_id)}'
    return url


def _institution_portal_path(institution):
    if not institution or not institution.school_code:
        return ''
    return f'/edu/portal/{institution.school_code.lower()}'


def _institution_portal_dashboard_path(institution):
    path = _institution_portal_path(institution)
    return f'{path}/dashboard/' if path else ''


def _edu_trial_student_limit():
    return EduSubscriptionSettings.current().trial_student_limit


def _activate_trial_access(institution, profile):
    if institution.has_used_free_trial:
        return False
    now = timezone.now()
    today = timezone.localdate()
    institution.registration_payment_status = 'pending'
    institution.registration_payment_reference = '3-day-free-trial'
    institution.registration_payment_paid_at = None
    institution.subscription_status = 'trial'
    institution.subscription_start_date = today
    institution.trial_start_date = today
    institution.trial_end_date = today + timedelta(days=EDU_TRIAL_DAYS)
    institution.subscription_expiry_date = institution.trial_end_date
    institution.subscription_active_until = institution.trial_end_date
    institution.trial_student_limit = institution.student_limit or institution.package_student_limit or _edu_trial_student_limit()
    institution.has_used_free_trial = True
    institution.subscription_last_payment_reference = '3-day-free-trial'
    institution.subscription_last_paid_at = None
    institution.verification_status = 'approved'
    institution.verified_at = now
    institution.save(update_fields=[
        'registration_payment_status',
        'registration_payment_reference',
        'registration_payment_paid_at',
        'subscription_status',
        'subscription_start_date',
        'trial_start_date',
        'trial_end_date',
        'subscription_expiry_date',
        'subscription_active_until',
        'trial_student_limit',
        'has_used_free_trial',
        'subscription_last_payment_reference',
        'subscription_last_paid_at',
        'verification_status',
        'verified_at',
    ])
    profile.is_approved = True
    profile.email_verified = True
    profile.approved_at = now
    profile.save(update_fields=['is_approved', 'email_verified', 'approved_at'])
    return True


def _subscription_expiry_date(institution):
    if institution.subscription_status in {'trial', 'trial_expired'}:
        return institution.trial_end_date or institution.subscription_expiry_date or institution.subscription_active_until
    return institution.subscription_expiry_date or institution.subscription_active_until


def _subscription_is_expired(institution):
    if not institution:
        return True
    institution.refresh_subscription_status()
    if institution.subscription_status in {'trial_expired', 'expired'}:
        return True
    expiry = _subscription_expiry_date(institution)
    return bool(institution.subscription_status == 'active' and expiry and expiry < timezone.localdate())


def _subscription_usage(institution):
    institution.refresh_subscription_status()
    used = Student.objects.filter(institution=institution).count()
    limit = institution.current_student_limit
    is_expired = _subscription_is_expired(institution)
    trial_days_remaining = institution.trial_days_remaining
    is_unlimited = limit is None
    return {
        'package_code': institution.subscription_package,
        'package_name': institution.package_name,
        'status': institution.subscription_status,
        'status_display': institution.get_subscription_status_display(),
        'billing_cycle': institution.subscription_billing_cycle,
        'student_limit': limit,
        'student_limit_display': 'Unlimited' if is_unlimited else f'{limit}',
        'students_used': used,
        'students_remaining': None if is_unlimited else max(limit - used, 0),
        'students_remaining_display': 'Unlimited' if is_unlimited else f'{max(limit - used, 0)}',
        'is_unlimited': is_unlimited,
        'expiry_date': _subscription_expiry_date(institution),
        'trial_start_date': institution.trial_start_date,
        'trial_end_date': institution.trial_end_date,
        'trial_days_remaining': trial_days_remaining,
        'trial_message': f"{trial_days_remaining} day{'s' if trial_days_remaining != 1 else ''} remaining in your free trial.",
        'is_expired': is_expired,
        'is_trial': institution.subscription_status == 'trial',
        'is_trial_expired': institution.subscription_status == 'trial_expired',
    }


def _student_limit_message(institution):
    usage = _subscription_usage(institution)
    if usage['is_unlimited']:
        return ''
    return (
        f"You have reached the {usage['student_limit']}-student limit for your "
        f"{usage['package_name']} package. Upgrade your package to add more students."
    )


def _student_capacity_message(institution):
    usage = _subscription_usage(institution)
    if usage['is_trial_expired']:
        return 'Your 3-day free trial has ended. Choose a package to continue using VilaStore Edu Portal.'
    if usage['is_expired']:
        return 'Your Edu Portal subscription has expired. Renew or upgrade your package to add more students.'
    return _student_limit_message(institution)


def _can_add_students(institution, count=1):
    usage = _subscription_usage(institution)
    if usage['is_unlimited']:
        return not usage['is_expired']
    return not usage['is_expired'] and usage['students_used'] + count <= usage['student_limit']


def _expired_subscription_response(request, profile):
    institution = profile.institution
    if institution:
        institution.refresh_subscription_status()
    if institution and institution.subscription_status == 'trial_expired':
        messages.error(request, 'Your 3-day free trial has ended. Choose a package to continue using VilaStore Edu Portal.')
    else:
        messages.error(request, 'Your Edu Portal subscription has expired. Renew your package to continue.')
    if profile.role in ['admin', 'vc', 'provost']:
        return redirect('edu:subscription_renewal')
    auth_logout(request)
    return redirect('edu:index')


def edu_portal_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        tenant = getattr(request, 'edu_institution', None)
        if tenant and profile and profile.institution_id != tenant.id:
            auth_logout(request)
            messages.error(request, 'This account does not belong to this school portal.')
            return redirect(_institution_portal_url(tenant))
        if profile and profile.institution:
            profile.institution.refresh_subscription_status()
            if not profile.institution.has_active_subscription_access:
                return _expired_subscription_response(request, profile)
        return view_func(request, *args, **kwargs)
    return wrapper


def _email_is_available(email, user=None):
    email = (email or '').strip()
    if not email:
        return False
    qs = get_user_model().objects.filter(email__iexact=email)
    if user:
        qs = qs.exclude(pk=user.pk)
    return not qs.exists()


def _send_edu_verification_email(request, profile):
    user = profile.user
    if not user.email:
        return False
    token = secrets.token_urlsafe(36)
    profile.email_verification_token = token
    profile.email_verification_sent_at = timezone.now()
    profile.email_verification_expires_at = timezone.now() + timedelta(hours=EMAIL_TOKEN_HOURS)
    profile.save(update_fields=[
        'email_verification_token',
        'email_verification_sent_at',
        'email_verification_expires_at',
    ])
    verify_url = _edu_abs_url(request, f"/edu/verify-email/{token}/")
    subject = "Verify your VilaStore Edu email"
    message = (
        f"Hello {user.get_username()},\n\n"
        "Please verify your email address before accessing the VilaStore Edu Portal.\n\n"
        f"Verify email: {verify_url}\n\n"
        f"This link expires in {EMAIL_TOKEN_HOURS} hours."
    )
    return send_email(user.email, subject, message, fail_silently=True)


def _send_edu_password_reset_email(request, profile):
    user = profile.user
    if not user.email:
        return False
    token = secrets.token_urlsafe(36)
    profile.password_reset_token = token
    profile.password_reset_sent_at = timezone.now()
    profile.password_reset_expires_at = timezone.now() + timedelta(hours=PASSWORD_RESET_HOURS)
    profile.save(update_fields=[
        'password_reset_token',
        'password_reset_sent_at',
        'password_reset_expires_at',
    ])
    reset_url = _edu_abs_url(request, f"/edu/reset-password/{token}/")
    subject = "Reset your VilaStore Edu password"
    message = (
        f"Hello {user.get_username()},\n\n"
        "Use the secure link below to reset your VilaStore Edu Portal password.\n\n"
        f"Reset password: {reset_url}\n\n"
        f"This link expires in {PASSWORD_RESET_HOURS} hours. If you did not request it, ignore this email."
    )
    return send_email(user.email, subject, message, fail_silently=True)


def _mark_email_unverified(profile):
    profile.email_verified = False
    profile.email_verification_token = ''
    profile.email_verification_sent_at = None
    profile.email_verification_expires_at = None


def _find_edu_profile_by_identifier(institution_type, school_code, identifier):
    identifier = (identifier or '').strip()
    school_code = (school_code or '').strip().upper()
    if not identifier or not school_code:
        return None
    return Profile.objects.select_related('user', 'institution').filter(
        institution_type=institution_type,
        institution__school_code__iexact=school_code,
    ).filter(
        Q(user__username__iexact=identifier) |
        Q(user__email__iexact=identifier)
    ).first()


def _flutterwave_public_key():
    return (
        getattr(django_settings, 'FLUTTERWAVE_PUBLIC_KEY', '')
        or os.getenv('FLUTTERWAVE_PUBLIC_KEY', '')
    ).strip()


def _flutterwave_secret_key():
    return (
        getattr(django_settings, 'FLUTTERWAVE_SECRET_KEY', '')
        or os.getenv('FLUTTERWAVE_SECRET_KEY', '')
        or os.getenv('FLUTTERWAVE_CLIENT_SECRET', '')
    ).strip()


def _verify_flutterwave_reference(payment_reference):
    reference = (payment_reference or '').strip()
    secret = _flutterwave_secret_key()
    if not reference:
        return None, 'Payment reference is missing.'
    if not secret:
        return None, 'Flutterwave secret key is not configured.'
    headers = {'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'}
    try:
        if reference.isdigit():
            response = requests.get(
                f'https://api.flutterwave.com/v3/transactions/{reference}/verify',
                headers=headers,
                timeout=15,
            )
        else:
            response = requests.get(
                'https://api.flutterwave.com/v3/transactions/verify_by_reference',
                headers=headers,
                params={'tx_ref': reference},
                timeout=15,
            )
        payload = response.json()
    except Exception:
        return None, 'Could not verify payment right now. Please try again.'
    if response.status_code >= 400:
        return payload, 'Payment verification failed. Please try again.'
    return payload, ''


def _normalize_gateway(value):
    gateway = (value or '').strip().lower()
    if gateway in {'flutterwave', 'paystack', 'remita'}:
        return gateway
    return 'flutterwave'


def _verify_salary_account(institution, gateway, account_number, bank_code, provided_name):
    gateway = _normalize_gateway(gateway)
    account_number = (account_number or '').strip()
    bank_code = (bank_code or '').strip()
    provided_name = (provided_name or '').strip()
    if not account_number or len(account_number) < 10:
        return False, '', 'failed', 'Enter a valid bank account number.'
    if not bank_code and gateway in {'flutterwave', 'paystack'}:
        if provided_name:
            return True, provided_name, 'manual_review', 'Bank code is missing, so the account name was saved for manual review.'
        return False, '', 'failed', 'Bank code is required for automatic account verification.'

    secret = (institution.payment_secret_key or '').strip()
    if gateway == 'flutterwave' and secret:
        try:
            response = requests.post(
                'https://api.flutterwave.com/v3/accounts/resolve',
                headers={'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'},
                json={'account_number': account_number, 'account_bank': bank_code},
                timeout=15,
            )
            payload = response.json()
            data = payload.get('data') or {}
            account_name = (data.get('account_name') or '').strip()
            if response.ok and account_name:
                return True, account_name, 'verified', 'Account verified with Flutterwave.'
            return False, provided_name, 'failed', payload.get('message') or 'Flutterwave could not verify this account.'
        except Exception:
            return False, provided_name, 'failed', 'Flutterwave account verification failed. Please try again.'

    if gateway == 'paystack' and secret:
        try:
            response = requests.get(
                'https://api.paystack.co/bank/resolve',
                headers={'Authorization': f'Bearer {secret}'},
                params={'account_number': account_number, 'bank_code': bank_code},
                timeout=15,
            )
            payload = response.json()
            data = payload.get('data') or {}
            account_name = (data.get('account_name') or '').strip()
            if response.ok and account_name:
                return True, account_name, 'verified', 'Account verified with Paystack.'
            return False, provided_name, 'failed', payload.get('message') or 'Paystack could not verify this account.'
        except Exception:
            return False, provided_name, 'failed', 'Paystack account verification failed. Please try again.'

    if provided_name:
        label = gateway.title()
        return True, provided_name, 'manual_review', f'{label} automatic verification is not configured yet; saved for admin review.'
    return False, '', 'failed', 'Verified account name is required when automatic verification is not configured.'


def _process_salary_voucher(voucher):
    if voucher.status != 'approved':
        return False, 'Only approved vouchers can be processed.'
    if voucher.payment_date > timezone.localdate():
        return False, 'Payment date has not reached yet.'

    institution = voucher.institution
    secret = (institution.payment_secret_key or '').strip()
    gateway = _normalize_gateway(voucher.payment_gateway)
    if not secret:
        voucher.status = 'failed'
        voucher.failure_reason = 'Payment gateway secret key is not configured.'
        voucher.processed_at = timezone.now()
        voucher.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])
        return False, voucher.failure_reason

    try:
        if gateway == 'flutterwave':
            response = requests.post(
                'https://api.flutterwave.com/v3/transfers',
                headers={'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'},
                json={
                    'account_bank': voucher.bank_code,
                    'account_number': voucher.bank_account_number,
                    'amount': float(voucher.salary_amount),
                    'currency': institution.currency or 'NGN',
                    'narration': f'Salary payout {voucher.reference}',
                    'reference': voucher.reference,
                },
                timeout=20,
            )
            payload = response.json()
            data = payload.get('data') or {}
            if response.ok and str(payload.get('status')).lower() == 'success':
                voucher.status = 'paid'
                voucher.gateway_reference = str(data.get('id') or data.get('reference') or voucher.reference)
                voucher.failure_reason = ''
                voucher.processed_at = timezone.now()
                voucher.save(update_fields=['status', 'gateway_reference', 'failure_reason', 'processed_at', 'updated_at'])
                return True, 'Salary payout processed with Flutterwave.'
            message = payload.get('message') or 'Flutterwave payout failed.'
        elif gateway == 'paystack':
            message = 'Paystack transfer requires transfer recipient setup; voucher kept as failed for manual retry.'
        else:
            message = 'Remita payout API is not configured yet; process this voucher manually or add Remita integration keys.'
    except Exception:
        message = 'Payment gateway payout request failed. Please try again.'

    voucher.status = 'failed'
    voucher.failure_reason = message
    voucher.processed_at = timezone.now()
    voucher.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])
    return False, message


SECONDARY_ROLES = [
    {"slug": "admin", "label": "Admin"},
    {"slug": "registry", "label": "Registry"},
    {"slug": "accountant", "label": "Accountant"},
    {"slug": "teacher", "label": "Teacher"},
    {"slug": "examiner", "label": "Examiner"},
    {"slug": "student", "label": "Student"},
]

TERTIARY_ROLES = [
    {"slug": "vc", "label": "VC"},
    {"slug": "provost", "label": "Provost"},
    {"slug": "ict-admin", "label": "ICT Admin"},
    {"slug": "accountant", "label": "Accountant"},
    {"slug": "faculty-admin", "label": "Faculty Admin"},
    {"slug": "department-admin", "label": "Department Admin"},
    {"slug": "hod", "label": "HOD"},
    {"slug": "lecturer", "label": "Lecturer"},
    {"slug": "examiner", "label": "Examiner"},
    {"slug": "student", "label": "Student"},
]



def index(request):
    return render(request, 'edu/index.html', {
        'pricing_packages': _edu_pricing_packages(),
        'default_subscription_package': EDU_DEFAULT_PACKAGE,
        'default_subscription_cycle': EDU_DEFAULT_BILLING_CYCLE,
    })


def school_portal_lookup(request):
    portal_name = request.GET.get('school', '').strip()
    forgot_name = request.POST.get('school_name', '').strip()
    forgot_email = request.POST.get('school_email', '').strip()
    lookup_error = ''
    forgot_error = ''
    found_portal_url = ''

    if portal_name:
        school_code = Institution.normalize_subdomain(portal_name)
        if not school_code or school_code in RESERVED_EDU_SUBDOMAINS:
            lookup_error = "We couldn't find a school registered with that portal address. Check the portal name and try again."
        else:
            institution = Institution.objects.filter(school_code__iexact=school_code).first()
            if institution:
                return redirect(_institution_portal_url(institution))
            lookup_error = "We couldn't find a school registered with that portal address. Check the portal name and try again."

    if request.method == 'POST':
        if not forgot_name or not forgot_email:
            forgot_error = 'Enter the school name and registered school email.'
        else:
            institution = Institution.objects.filter(
                name__iexact=forgot_name,
                email__iexact=forgot_email,
            ).first()
            if institution:
                found_portal_url = _institution_portal_url(institution)
            else:
                forgot_error = "We couldn't find a school with those details. Check the information and try again."

    return render(request, 'edu/school_portal_lookup.html', {
        'portal_name': Institution.normalize_subdomain(portal_name),
        'lookup_error': lookup_error,
        'forgot_name': forgot_name,
        'forgot_email': forgot_email,
        'forgot_error': forgot_error,
        'found_portal_url': found_portal_url,
    })


def school_portal_dashboard(request, school_code):
    normalized_code = Institution.normalize_subdomain(school_code)
    institution = get_object_or_404(Institution, school_code__iexact=normalized_code)
    request.edu_institution = institution
    request.edu_portal_path = True
    if not request.user.is_authenticated:
        return redirect(_institution_portal_path(institution))
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_id != institution.id:
        messages.error(request, 'Log in with an account for this school portal.')
        return redirect(_institution_portal_path(institution))
    if profile.institution_type == 'tertiary':
        return redirect('edu:tertiary_dashboard', role=profile.role)
    return redirect('edu:secondary_dashboard', role=profile.role)


def school_portal_fallback(request, school_code):
    normalized_code = Institution.normalize_subdomain(school_code)
    institution = get_object_or_404(Institution, school_code__iexact=normalized_code)
    request.edu_institution = institution
    request.edu_portal_path = True
    template_name = 'edu/tertiary_login.html' if institution.institution_type == 'tertiary' else 'edu/secondary_login.html'
    return _login_for_institution(request, institution.institution_type, template_name)


def school_portal_fallback_dashboard(request, school_code):
    normalized_code = Institution.normalize_subdomain(school_code)
    return school_portal_dashboard(request, normalized_code)


def _resolve_login_user(institution_type, school_code, identifier):
    User = get_user_model()
    user = User.objects.filter(username__iexact=identifier).first()
    if user:
        return user

    if not school_code or not identifier:
        return None

    profile = Profile.objects.select_related('user', 'institution').filter(
        institution_type=institution_type,
        institution__school_code__iexact=school_code,
    ).filter(
        Q(user__email__iexact=identifier) |
        Q(institution__admin_email__iexact=identifier) |
        Q(institution__admin_phone__iexact=identifier)
    ).order_by('id').first()
    return profile.user if profile else None


def _get_or_repair_edu_profile(user, institution_type, school_code):
    profile = getattr(user, 'profile', None)
    if profile:
        return profile

    staff = Staff.objects.select_related('institution').filter(
        user=user,
        institution__institution_type=institution_type,
    ).first()
    if staff:
        profile, created = Profile.objects.get_or_create(user=user)
        profile.institution = staff.institution
        profile.institution_type = institution_type
        profile.role = staff.role
        profile.created_via = profile.created_via or 'repaired-login'
        profile.is_approved = staff.institution.verification_status == 'approved'
        profile.approved_at = timezone.now() if profile.is_approved and not profile.approved_at else profile.approved_at
        if created and user.email:
            profile.email_verified = True
        profile.save()
        return profile

    student = Student.objects.select_related('institution').filter(
        user=user,
        institution__institution_type=institution_type,
    ).first()
    if student:
        profile, created = Profile.objects.get_or_create(user=user)
        profile.institution = student.institution
        profile.institution_type = institution_type
        profile.role = 'student'
        profile.created_via = profile.created_via or 'repaired-login'
        profile.is_approved = student.institution.verification_status == 'approved'
        profile.approved_at = timezone.now() if profile.is_approved and not profile.approved_at else profile.approved_at
        if created and user.email:
            profile.email_verified = True
        profile.save()
        return profile

    institution = Institution.objects.filter(
        institution_type=institution_type,
        school_code__iexact=school_code,
    ).filter(
        Q(admin_email__iexact=user.email) | Q(admin_phone__iexact=user.username)
    ).first()
    if institution:
        profile, created = Profile.objects.get_or_create(user=user)
        profile.institution = institution
        profile.institution_type = institution_type
        profile.role = 'admin' if institution_type == 'secondary' else 'vc'
        profile.created_via = profile.created_via or 'school-register'
        profile.is_approved = institution.verification_status == 'approved'
        profile.approved_at = timezone.now() if profile.is_approved and not profile.approved_at else profile.approved_at
        if created and user.email:
            profile.email_verified = True
        profile.save()
        return profile

    return None


def _repair_trial_school_admin_login(profile):
    institution = profile.institution if profile else None
    if not institution:
        return profile
    if profile.is_approved and profile.email_verified:
        return profile
    if profile.created_via != 'school-register':
        return profile
    if profile.role not in {'admin', 'vc'}:
        return profile
    if institution.subscription_status != 'trial' or institution.verification_status != 'approved':
        return profile
    if institution.trial_end_date and institution.trial_end_date < timezone.localdate():
        return profile
    user_email = (profile.user.email or '').strip().lower()
    admin_email = (institution.admin_email or '').strip().lower()
    if user_email and admin_email and user_email != admin_email:
        return profile

    now = timezone.now()
    update_fields = []
    if not profile.is_approved:
        profile.is_approved = True
        profile.approved_at = profile.approved_at or now
        update_fields.extend(['is_approved', 'approved_at'])
    if not profile.email_verified:
        profile.email_verified = True
        update_fields.append('email_verified')
    if update_fields:
        profile.save(update_fields=update_fields)
    return profile


def _institution_from_portal_request(request, institution_type):
    tenant = getattr(request, 'edu_institution', None)
    if not tenant:
        return None
    if tenant.institution_type != institution_type:
        return None
    return tenant


def _login_for_institution(request, institution_type, template_name):
    roles = SECONDARY_ROLES if institution_type == 'secondary' else TERTIARY_ROLES
    portal_institution = _institution_from_portal_request(request, institution_type)
    if not portal_institution:
        messages.info(request, 'School users log in through their school portal link.')
        return redirect('edu:index')

    if request.method == 'POST':
        school_code = request.POST.get('school_code', '').strip().upper()
        if portal_institution:
            school_code = portal_institution.school_code.upper()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        resolved_user = _resolve_login_user(institution_type, school_code, username)
        auth_username = resolved_user.username if resolved_user else username
        user = authenticate(request, username=auth_username, password=password)
        if user is None:
            existing = resolved_user or get_user_model().objects.filter(username__iexact=username).first()
            if existing and not existing.is_active:
                messages.error(request, 'Account pending approval.')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            auth_login(request, user)
            request.session['active_portal'] = 'edu'
            profile = _get_or_repair_edu_profile(user, institution_type, school_code)
            profile = _repair_trial_school_admin_login(profile)
            if profile and profile.institution_type != institution_type:
                auth_logout(request)
                messages.error(request, 'This account belongs to a different portal.')
            elif profile:
                if not school_code or not profile.institution or profile.institution.school_code.upper() != school_code:
                    auth_logout(request)
                    messages.error(request, 'Invalid school code.')
                elif not profile.is_approved:
                    auth_logout(request)
                    if profile.institution and profile.institution.registration_payment_status != 'paid':
                        payment_url = f"/edu/{profile.institution_type}/register/{profile.institution.school_code}/payment/"
                        messages.error(request, f'EduPortal subscription payment is required before portal access. Complete payment here: {payment_url}')
                    elif profile.institution and profile.institution.verification_status == 'pending':
                        messages.error(request, 'School setup is still pending approval before portal access is granted.')
                    elif profile.institution and profile.institution.verification_status == 'rejected':
                        messages.error(request, 'School verification was rejected. Please contact VilaStore support for review details.')
                    else:
                        messages.error(request, 'Account pending approval.')
                elif not user.email:
                    auth_logout(request)
                    messages.error(request, 'This account needs an email address before portal access. Please contact your school admin.')
                elif not profile.email_verified:
                    auth_logout(request)
                    if _send_edu_verification_email(request, profile):
                        messages.error(request, 'Please verify your email address before login. We sent a fresh verification link to your email.')
                    else:
                        messages.error(request, 'Please verify your email address before login, but we could not send the verification email right now. Contact your school admin or try again later.')
                else:
                    if profile.institution:
                        profile.institution.refresh_subscription_status()
                    if getattr(request, 'edu_portal_path', False):
                        return redirect(_institution_portal_dashboard_path(profile.institution))
                    if profile.institution_type == 'tertiary':
                        return redirect('edu:tertiary_dashboard', role=profile.role)
                    return redirect('edu:secondary_dashboard', role=profile.role)
            else:
                messages.error(request, 'No profile found for this user.')

    return render(request, template_name, {
        'institution': institution_type,
        'roles': roles,
        'portal_institution': portal_institution,
        'subdomain_institution': portal_institution,
        'resolved_school_code': portal_institution.school_code if portal_institution else '',
        'initial_username': request.GET.get('admin_id', '').strip(),
    })


def secondary_login(request):
    return _login_for_institution(request, 'secondary', 'edu/secondary_login.html')


def tertiary_login(request):
    return _login_for_institution(request, 'tertiary', 'edu/tertiary_login.html')


def verify_email(request, token):
    profile = Profile.objects.select_related('user').filter(email_verification_token=token).first()
    if not profile or not profile.email_verification_expires_at or profile.email_verification_expires_at < timezone.now():
        messages.error(request, 'Verification link is invalid or expired. Please request a new link from the login page.')
        return redirect('edu:index')

    profile.email_verified = True
    profile.email_verification_token = ''
    profile.email_verification_sent_at = None
    profile.email_verification_expires_at = None
    profile.save(update_fields=[
        'email_verified',
        'email_verification_token',
        'email_verification_sent_at',
        'email_verification_expires_at',
    ])
    messages.success(request, 'Email verified successfully. You can now sign in.')
    return redirect(_profile_login_url(profile))


def forgot_password(request):
    institution_type = request.POST.get('institution_type') or request.GET.get('institution') or 'secondary'
    if institution_type not in ['secondary', 'tertiary']:
        institution_type = 'secondary'

    if request.method == 'POST':
        profile = _find_edu_profile_by_identifier(
            institution_type,
            request.POST.get('school_code', ''),
            request.POST.get('identifier', ''),
        )
        if profile and profile.user.email:
            # Message stays generic even on send failure to avoid leaking whether an account exists.
            _send_edu_password_reset_email(request, profile)
        messages.success(request, 'If the account exists, a password reset link has been sent to the registered email address.')
        return redirect(f"/edu/forgot-password/?institution={institution_type}")

    return render(request, 'edu/forgot_password.html', {
        'institution_type': institution_type,
        'login_url': '/edu/tertiary/login/' if institution_type == 'tertiary' else '/edu/secondary/login/',
    })


def reset_password(request, token):
    profile = Profile.objects.select_related('user').filter(password_reset_token=token).first()
    if not profile or not profile.password_reset_expires_at or profile.password_reset_expires_at < timezone.now():
        messages.error(request, 'Password reset link is invalid or expired. Please request a new reset link.')
        return redirect('edu:forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            profile.user.set_password(password)
            profile.user.save(update_fields=['password'])
            profile.email_verified = True
            profile.password_reset_token = ''
            profile.password_reset_sent_at = None
            profile.password_reset_expires_at = None
            profile.save(update_fields=[
                'email_verified',
                'password_reset_token',
                'password_reset_sent_at',
                'password_reset_expires_at',
            ])
            messages.success(request, 'Password reset successfully. You can now sign in.')
            return redirect(_profile_login_url(profile))

    return render(request, 'edu/reset_password.html', {
        'profile': profile,
    })


def _generate_student_id(prefix, institution):
    count = Student.objects.filter(institution=institution).count() + 1
    return f"{prefix}{institution.id:03d}-{count:04d}"


def _generate_staff_id(prefix, institution):
    count = Staff.objects.filter(institution=institution).count() + 1
    return f"{prefix}{institution.id:03d}-{count:04d}"


def _get_school_short(institution):
    if institution.short_name:
        return "".join(ch for ch in institution.short_name.upper() if ch.isalnum())[:6]
    words = [w for w in institution.name.split() if w]
    initials = "".join(w[0] for w in words).upper()
    initials = "".join(ch for ch in initials if ch.isalnum())
    return (initials or "SCH")[:6]


def _generate_user_id(institution):
    with transaction.atomic():
        inst = Institution.objects.select_for_update().get(pk=institution.pk)
        inst.user_sequence += 1
        inst.save(update_fields=['user_sequence'])
        year = timezone.now().year
        short = _get_school_short(inst)
        return f"{short}/{year}/{inst.user_sequence:03d}"


def _verification_uploads(request):
    return {
        'cac_certificate': request.FILES.get('cac_certificate'),
        'cac_status_report': request.FILES.get('cac_status_report'),
        'ministry_approval': request.FILES.get('ministry_approval'),
        'operating_license': request.FILES.get('operating_license'),
        'tin_certificate': request.FILES.get('tin_certificate'),
        'school_letterhead': request.FILES.get('school_letterhead'),
        'school_stamp': request.FILES.get('school_stamp'),
        'owner_valid_id': request.FILES.get('owner_valid_id'),
        'utility_bill': request.FILES.get('utility_bill'),
        'proof_of_address': request.FILES.get('proof_of_address'),
    }


def _missing_verification_requirements(request):
    uploads = _verification_uploads(request)
    missing = []

    if not request.POST.get('admin_email', '').strip():
        missing.append('Owner/Admin email address')
    if not request.POST.get('admin_phone', '').strip():
        missing.append('Owner/Admin phone number')

    return missing, uploads


def _fee_student_queryset(fee):
    students = Student.objects.filter(institution=fee.institution)
    if fee.applies_to_all:
        return students

    class_ids = list(fee.classes.values_list('id', flat=True))
    if class_ids:
        return students.filter(academic_class_id__in=class_ids)

    if fee.academic_class_id:
        return students.filter(academic_class=fee.academic_class)

    return students.none()


def _school_fee_summary(institution):
    fees = Fee.objects.filter(institution=institution).prefetch_related('classes', 'departments')
    expected_total = sum(fee.amount * _fee_student_queryset(fee).count() for fee in fees)
    paid_total = Payment.objects.filter(institution=institution, status='Paid').aggregate(total=Sum('amount'))['total'] or 0
    pending_total = Payment.objects.filter(institution=institution, status='Pending').aggregate(total=Sum('amount'))['total'] or 0
    outstanding = expected_total - paid_total
    if outstanding < 0:
        outstanding = 0
    return {
        'expected_total': expected_total,
        'paid_total': paid_total,
        'pending_total': pending_total,
        'outstanding_total': outstanding + pending_total,
    }


def _payment_receipt_url(payment):
    return f"/edu/secondary/payments/{payment.reference}/receipt/"


def _results_for_submission(submission):
    if not submission:
        return Result.objects.none()

    filters = Q(
        institution=submission.institution,
        academic_class=submission.academic_class,
        subject=submission.subject,
    )
    if submission.academic_session_id:
        filters &= Q(academic_session=submission.academic_session)
    else:
        filters &= Q(session=submission.session)
    if submission.academic_term_id:
        filters &= Q(academic_term=submission.academic_term)
    else:
        filters &= Q(term=submission.term)

    return Result.objects.filter(filters).select_related('student').order_by('student__full_name')


def _results_for_report_scope(institution, academic_class, academic_session, academic_term, session_name='', term_name=''):
    filters = Q(institution=institution, academic_class=academic_class)
    if academic_session:
        filters &= Q(academic_session=academic_session)
    elif session_name:
        filters &= Q(session=session_name)
    if academic_term:
        filters &= Q(academic_term=academic_term)
    elif term_name:
        filters &= Q(term=term_name)
    return Result.objects.filter(filters).select_related('student', 'subject', 'academic_class', 'academic_session', 'academic_term').order_by('student__full_name', 'subject__name')


def _report_card_previews_for_submission(submission):
    if not submission:
        return []

    students = Student.objects.filter(
        institution=submission.institution,
        academic_class=submission.academic_class,
    ).order_by('full_name')
    results = list(_results_for_report_scope(
        submission.institution,
        submission.academic_class,
        submission.academic_session,
        submission.academic_term,
        submission.session,
        submission.term,
    ))
    results_by_student = {}
    totals = {}
    for result in results:
        results_by_student.setdefault(result.student_id, []).append(result)
        totals[result.student_id] = totals.get(result.student_id, Decimal('0.00')) + result.total

    ranked_ids = sorted(totals, key=lambda student_id: totals[student_id], reverse=True)
    positions = {}
    last_score = None
    last_rank = 0
    for index, student_id in enumerate(ranked_ids, start=1):
        score = totals[student_id]
        if last_score is None or score != last_score:
            last_rank = index
            last_score = score
        positions[student_id] = _ordinal(last_rank)

    previews = []
    for student in students:
        student_results = results_by_student.get(student.id, [])
        total = totals.get(student.id, Decimal('0.00'))
        count = len(student_results)
        average = (total / Decimal(count)).quantize(Decimal('0.01')) if count else Decimal('0.00')
        previews.append({
            'student': student,
            'results': student_results,
            'total': total,
            'average': average,
            'position': positions.get(student.id, '-'),
            'academic_class': submission.academic_class,
            'session': submission.session,
            'term': submission.term,
            'teacher_comment': submission.teacher_comment,
            'examiner_comment': submission.examiner_comment,
            'admin_comment': submission.admin_comment,
            'approval_status': submission.get_status_display(),
            'is_preview': True,
        })
    return previews


def _get_secondary_accountant_profile(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'accountant':
        return None
    return profile


def _get_secondary_student_profile(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'student':
        return None
    return profile


def _get_selected_session_term(institution, session_id, term_id):
    session = AcademicSession.objects.filter(id=session_id, institution=institution).first()
    term = AcademicTerm.objects.filter(id=term_id, session=session).first() if session else None
    return session, term


def _ordinal(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 10 <= (number % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _get_secondary_nav(role):
    icons = {
        'dashboard': 'layout-dashboard',
        'users': 'users',
        'teachers': 'users',
        'classes': 'school',
        'subjects': 'book-open',
        'assign-teachers': 'user-check',
        'approve-results': 'clipboard-check',
        'settings': 'settings',
        'register': 'users',
        'assign-class': 'school',
        'sessions': 'folder-open',
        'student-ids': 'credit-card',
        'fees': 'credit-card',
        'payments': 'credit-card',
        'receipts': 'file-text',
        'reports': 'file-text',
        'salary-vouchers': 'banknote',
        'my-classes': 'school',
        'my-students': 'users',
        'enter-scores': 'clipboard-check',
        'submit-results': 'upload',
        'review-results': 'clipboard-check',
        'result-sheets': 'file-text',
        'subjects-student': 'book-open',
        'test-scores': 'clipboard-check',
        'results': 'graduation-cap',
        'pay-fees': 'credit-card',
        'profile': 'users',
    }

    role_map = {
        'admin': ['dashboard', 'users', 'teachers', 'classes', 'subjects', 'assign-teachers', 'approve-results', 'salary-vouchers', 'settings'],
        'registry': ['dashboard', 'register', 'teachers', 'assign-class', 'sessions', 'student-ids'],
        'accountant': ['dashboard', 'fees', 'salary-vouchers', 'payments', 'receipts', 'reports'],
        'teacher': ['dashboard', 'my-classes', 'my-students', 'enter-scores', 'submit-results'],
        'examiner': ['dashboard', 'review-results', 'result-sheets'],
        'student': ['dashboard', 'subjects-student', 'test-scores', 'results', 'pay-fees', 'profile'],
    }

    labels = {
        'dashboard': 'Dashboard',
        'users': 'Manage Users',
        'classes': 'Classes',
        'subjects': 'Subjects',
        'assign-teachers': 'Assign Teachers',
        'approve-results': 'Approve Results',
        'settings': 'Settings',
        'register': 'Register Students',
        'assign-class': 'Assign Classes',
        'teachers': 'Teachers',
        'sessions': 'Sessions & Terms',
        'student-ids': 'Student IDs',
        'fees': 'School Fees',
        'payments': 'Payments',
        'receipts': 'Receipts',
        'reports': 'Reports',
        'salary-vouchers': 'Salary Vouchers',
        'my-classes': 'My Classes',
        'my-students': 'My Students',
        'enter-scores': 'Enter Scores',
        'submit-results': 'Submit Results',
        'review-results': 'Review Results',
        'result-sheets': 'Result Sheets',
        'subjects-student': 'My Classes',
        'test-scores': 'Test Scores',
        'results': 'Exam Results',
        'pay-fees': 'Pay Fees',
        'profile': 'My Profile',
    }

    items = []
    for item_id in role_map.get(role, []):
        url = f"/edu/secondary/{role}/" if item_id == 'dashboard' else f"/edu/secondary/{role}/{item_id}/"
        items.append({
            'id': item_id,
            'label': labels.get(item_id, item_id.replace('-', ' ').title()),
            'icon': icons.get(item_id, 'layout-dashboard'),
            'url': url,
        })
    return items


def _get_tertiary_nav(role):
    icons = {
        'dashboard': 'layout-dashboard',
        'approve-results': 'clipboard-check',
        'analytics': 'file-text',
        'faculties': 'building-2',
        'cbt-exams': 'monitor',
        'questions': 'file-text',
        'users': 'users',
        'grading': 'settings',
        'fees': 'credit-card',
        'payments': 'credit-card',
        'receipts': 'file-text',
        'reports': 'file-text',
        'departments': 'building-2',
        'performance': 'file-text',
        'students': 'users',
        'courses': 'book-open',
        'lecturers': 'graduation-cap',
        'submit-results': 'upload',
        'my-courses': 'book-open',
        'my-students': 'users',
        'enter-scores': 'clipboard-check',
        'materials': 'upload',
        'review-results': 'clipboard-check',
        'verify-grading': 'file-text',
        'register-courses': 'book-open',
        'pay-fees': 'credit-card',
        'cbt-exams-student': 'monitor',
        'results': 'graduation-cap',
        'transcript': 'file-text',
        'payment-history': 'credit-card',
    }

    role_map = {
        'vc': ['dashboard', 'approve-results', 'analytics', 'faculties'],
        'provost': ['dashboard', 'approve-results', 'analytics', 'faculties'],
        'ict-admin': ['dashboard', 'cbt-exams', 'questions', 'users', 'grading'],
        'accountant': ['dashboard', 'fees', 'payments', 'receipts', 'reports'],
        'faculty-admin': ['dashboard', 'departments', 'performance', 'approve-results'],
        'department-admin': ['dashboard', 'students', 'courses', 'lecturers', 'submit-results'],
        'lecturer': ['dashboard', 'my-courses', 'my-students', 'enter-scores', 'materials', 'submit-results'],
        'examiner': ['dashboard', 'review-results', 'verify-grading'],
        'student': ['dashboard', 'register-courses', 'pay-fees', 'cbt-exams-student', 'results', 'transcript', 'payment-history'],
    }

    labels = {
        'dashboard': 'Dashboard',
        'approve-results': 'Approve Results',
        'analytics': 'Analytics',
        'faculties': 'Faculties',
        'cbt-exams': 'CBT Exams',
        'questions': 'Questions Bank',
        'users': 'Manage Users',
        'grading': 'Grading System',
        'fees': 'School Fees',
        'payments': 'Payments',
        'receipts': 'Receipts',
        'reports': 'Reports',
        'departments': 'Departments',
        'performance': 'Performance',
        'students': 'Students',
        'courses': 'Courses',
        'lecturers': 'Lecturers',
        'submit-results': 'Submit Results',
        'my-courses': 'My Courses',
        'my-students': 'My Students',
        'enter-scores': 'Enter Scores',
        'materials': 'Materials',
        'review-results': 'Review Results',
        'verify-grading': 'Verify Grading',
        'register-courses': 'Register Courses',
        'pay-fees': 'Pay Fees',
        'cbt-exams-student': 'CBT Exams',
        'results': 'Results',
        'transcript': 'Transcript',
        'payment-history': 'Payments',
    }

    items = []
    for item_id in role_map.get(role, []):
        url = f"/edu/tertiary/{role}/" if item_id == 'dashboard' else f"/edu/tertiary/{role}/{item_id}/"
        items.append({
            'id': item_id,
            'label': labels.get(item_id, item_id.replace('-', ' ').title()),
            'icon': icons.get(item_id, 'layout-dashboard'),
            'url': url,
        })
    return items


def edu_subdomain_availability(request):
    raw_subdomain = request.GET.get('subdomain') or request.GET.get('school_name') or ''
    subdomain = Institution.normalize_subdomain(raw_subdomain)
    available = bool(subdomain)
    message = 'Portal name available.'

    if not subdomain:
        message = 'Enter a school portal name.'
    elif subdomain in RESERVED_EDU_SUBDOMAINS:
        available = False
        message = 'This portal name is reserved. Choose another.'
    elif Institution.objects.filter(school_code__iexact=subdomain).exists():
        available = False
        message = 'Portal name already taken. Choose another.'

    return JsonResponse({
        'available': available,
        'subdomain': subdomain,
        'portal_url': f'https://vilastore.store/edu/portal/{subdomain}' if subdomain else '',
        'message': message,
    })


def _school_register_context(default_school_type='secondary', request=None):
    selected_package = _normalize_edu_package(request.GET.get('package')) if request else EDU_DEFAULT_PACKAGE
    if selected_package not in EDU_REGISTRATION_PACKAGES:
        selected_package = EDU_DEFAULT_PACKAGE
    selected_cycle = _normalize_edu_billing_cycle(request.GET.get('billing')) if request else EDU_DEFAULT_BILLING_CYCLE
    return {
        'type_choices': Institution.TYPE_CHOICES,
        'default_school_type': default_school_type,
        'reserved_subdomains': sorted(RESERVED_EDU_SUBDOMAINS),
        'pricing_packages': _edu_pricing_packages(),
        'subscription_plans': _edu_subscription_plans(),
        'default_subscription_package': selected_package,
        'default_subscription_cycle': selected_cycle,
    }


def _validation_error_messages(exc):
    if hasattr(exc, 'message_dict'):
        return [message for messages_list in exc.message_dict.values() for message in messages_list]
    if hasattr(exc, 'messages'):
        return exc.messages
    return [str(exc)]


def _register_school_with_trial(request, default_school_type='secondary'):
    duplicate_institution = None
    if request.method == 'POST':
        institution_name = request.POST.get('institution_name', '').strip()
        institution_type = request.POST.get('institution_type', default_school_type).strip()
        if institution_type not in {'secondary', 'tertiary'}:
            institution_type = default_school_type
        school_code = Institution.normalize_subdomain(request.POST.get('school_code') or institution_name)
        address = request.POST.get('address', '').strip()
        state = request.POST.get('state', '').strip()
        lga = request.POST.get('lga', '').strip()
        school_phone = request.POST.get('phone_number', '').strip()
        school_email = request.POST.get('email', '').strip()
        admin_full_name = request.POST.get('admin_full_name', '').strip()
        admin_email = request.POST.get('admin_email', '').strip()
        admin_phone = request.POST.get('admin_phone', '').strip()
        admin_password = request.POST.get('admin_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        subscription_package = _normalize_edu_package(request.POST.get('subscription_package'))
        billing_cycle = _normalize_edu_billing_cycle(request.POST.get('subscription_billing_cycle'))

        required_values = [
            institution_name,
            institution_type,
            address,
            state,
            lga,
            school_phone,
            school_email,
            admin_full_name,
            admin_email,
            admin_phone,
            admin_password,
            confirm_password,
            subscription_package,
            billing_cycle,
            school_code,
        ]

        if not all(required_values):
            messages.error(request, 'Please complete all required school, administrator, and portal fields.')
        elif admin_password != confirm_password:
            messages.error(request, 'Password and confirm password do not match.')
        elif subscription_package not in EDU_REGISTRATION_PACKAGES:
            messages.error(request, 'Please choose a valid registration package.')
        elif not _email_is_available(admin_email):
            messages.error(request, 'That administrator email address is already used by another account.')
        elif school_code in RESERVED_EDU_SUBDOMAINS:
            messages.error(request, 'That school portal name is reserved. Please choose another one.')
        elif Institution.objects.filter(school_code__iexact=school_code).exists():
            duplicate_institution = Institution.objects.filter(school_code__iexact=school_code).first()
            messages.error(request, 'This school portal already exists. Use the existing portal link below or choose another portal name.')
        else:
            try:
                with transaction.atomic():
                    admin_role = 'vc' if institution_type == 'tertiary' else 'admin'
                    staff_prefix = 'TERSTF' if institution_type == 'tertiary' else 'SECSTF'
                    institution = Institution.objects.create(
                        name=institution_name,
                        school_code=school_code,
                        short_name=school_code[:20],
                        institution_type=institution_type,
                        ownership_type='private',
                        country='Nigeria',
                        state=state,
                        city=lga,
                        address=address,
                        phone_number=school_phone,
                        email=school_email,
                        has_faculties=institution_type == 'tertiary',
                        has_departments=institution_type == 'tertiary',
                        grading_system='percentage',
                        max_grade=100,
                        currency='NGN',
                        subscription_package=subscription_package,
                        subscription_status='pending',
                        student_limit=_edu_package_limit(subscription_package),
                        subscription_billing_cycle=billing_cycle,
                        registration_payment_amount=_edu_subscription_amount(billing_cycle, subscription_package),
                        registration_payment_status='pending',
                        admin_email=admin_email,
                        admin_phone=admin_phone,
                        logo=request.FILES.get('logo'),
                        verification_status='pending',
                    )

                    User = get_user_model()
                    admin_username = _generate_user_id(institution)
                    user = User.objects.create_user(
                        username=admin_username,
                        email=admin_email,
                        password=admin_password,
                    )
                    user.is_active = True
                    user.save()

                    profile, _ = Profile.objects.get_or_create(user=user)
                    profile.institution = institution
                    profile.institution_type = institution_type
                    profile.role = admin_role
                    profile.created_via = 'school-register'
                    profile.is_approved = False
                    profile.approved_by = None
                    profile.approved_at = None
                    profile.save()

                    Staff.objects.create(
                        institution=institution,
                        user=user,
                        full_name=admin_full_name,
                        staff_id=_generate_staff_id(staff_prefix, institution),
                        role=admin_role,
                        department='',
                    )

                    if not _activate_trial_access(institution, profile):
                        raise ValidationError('This school has already used its free trial. Choose a package to continue.')

                return render(request, 'edu/registration_success.html', {
                    'institution': institution,
                    'admin_username': admin_username,
                    'portal_url': _institution_portal_url(institution),
                    'trial_days': EDU_TRIAL_DAYS,
                    'selected_package': _edu_package(subscription_package),
                    'selected_plan': _edu_subscription_plans(subscription_package)[billing_cycle],
                })
            except IntegrityError:
                duplicate_institution = Institution.objects.filter(school_code__iexact=school_code).first()
                if duplicate_institution:
                    messages.error(request, 'This school portal already exists. Use the existing portal link below or choose another portal name.')
                else:
                    messages.error(request, 'School portal name or administrator ID already exists.')
            except ValidationError as exc:
                for message in _validation_error_messages(exc):
                    messages.error(request, message)

    context = _school_register_context(default_school_type, request)
    if duplicate_institution:
        context['duplicate_institution'] = duplicate_institution
        context['duplicate_portal_url'] = _institution_portal_url(duplicate_institution)
    return render(request, 'edu/school_register.html', context)


def secondary_school_register(request):
    return _register_school_with_trial(request, 'secondary')


def _extend_subscription_until(institution, billing_cycle):
    plan = _edu_subscription_plans(institution.subscription_package)[_normalize_edu_billing_cycle(billing_cycle)]
    today = timezone.localdate()
    start_date = institution.subscription_active_until if institution.subscription_active_until and institution.subscription_active_until > today else today
    return start_date + timedelta(days=plan['duration_days'])


def _package_change_warning(institution, package_code):
    new_limit = _edu_package_limit(package_code)
    current_students = Student.objects.filter(institution=institution).count()
    if current_students > new_limit:
        package = _edu_package(package_code)
        return (
            f"This school already has {current_students} students. The {package['name']} "
            f"package allows {new_limit}, so no new students can be added until the count is reduced or the package is upgraded."
        )
    return ''


def _edu_payment_context(institution, login_url, mode='registration'):
    cycle = _normalize_edu_billing_cycle(institution.subscription_billing_cycle)
    package_code = _normalize_edu_package(institution.subscription_package)
    plan = _edu_subscription_plans(package_code)[cycle]
    amount = Decimal(plan['amount'])
    institution.refresh_subscription_status()
    subscription_expired = _subscription_is_expired(institution)
    return {
        'institution': institution,
        'amount': amount,
        'amount_display': _format_edu_price(amount),
        'selected_plan': plan,
        'pricing_packages': _edu_pricing_packages(),
        'selected_package': _edu_package(package_code),
        'subscription_plans': _edu_subscription_plans(package_code),
        'currency': institution.currency or 'NGN',
        'flutterwave_public_key': _flutterwave_public_key(),
        'login_url': login_url,
        'portal_url': _institution_portal_url(institution),
        'payment_mode': mode,
        'subscription_expired': subscription_expired,
        'subscription_usage': _subscription_usage(institution),
        'allow_payment_form': mode == 'renewal' or institution.registration_payment_status != 'paid' or subscription_expired,
    }


def _confirm_edu_subscription_payment(request, institution, payment_route_name, redirect_kwargs, login_route_name, success_message, mark_registration_paid=True):
    if request.method == 'POST':
        billing_cycle = _normalize_edu_billing_cycle(request.POST.get('subscription_billing_cycle') or institution.subscription_billing_cycle)
        package_code = _normalize_edu_package(request.POST.get('subscription_package') or institution.subscription_package)
        plan = _edu_subscription_plans(package_code)[billing_cycle]
        if plan['package']['is_custom']:
            messages.error(request, 'Please contact VilaStore to activate this custom package.')
            return redirect(payment_route_name, **redirect_kwargs)
        payment_reference = request.POST.get('payment_reference', '').strip()
        payload, error = _verify_flutterwave_reference(payment_reference)
        if error:
            update_fields = ['registration_payment_reference']
            institution.registration_payment_reference = payment_reference
            if mark_registration_paid:
                institution.registration_payment_status = 'failed'
                update_fields.append('registration_payment_status')
            institution.save(update_fields=update_fields)
            messages.error(request, error)
            return redirect(payment_route_name, **redirect_kwargs)

        data = (payload or {}).get('data') or {}
        status = str(data.get('status') or '').lower()
        try:
            amount = Decimal(str(data.get('amount') or '0'))
        except Exception:
            amount = Decimal('0')
        currency = str(data.get('currency') or '').upper()
        expected_amount = Decimal(plan['amount'])
        expected_currency = (institution.currency or 'NGN').upper()
        if status != 'successful':
            messages.error(request, 'Payment was not successful.')
            return redirect(payment_route_name, **redirect_kwargs)
        if currency and currency != expected_currency:
            messages.error(request, 'Payment currency does not match registration currency.')
            return redirect(payment_route_name, **redirect_kwargs)
        if amount < expected_amount:
            messages.error(request, 'Paid amount is lower than the selected Edu Portal subscription plan.')
            return redirect(payment_route_name, **redirect_kwargs)

        paid_at = timezone.now()
        start_date = timezone.localdate()
        institution.subscription_package = package_code
        institution.subscription_billing_cycle = billing_cycle
        institution.subscription_status = 'active'
        institution.subscription_start_date = start_date
        institution.sync_package_limit()
        institution.registration_payment_amount = expected_amount
        institution.registration_payment_reference = payment_reference
        institution.registration_payment_paid_at = paid_at
        institution.subscription_active_until = _extend_subscription_until(institution, billing_cycle)
        institution.subscription_expiry_date = institution.subscription_active_until
        institution.subscription_last_payment_reference = payment_reference
        institution.subscription_last_paid_at = paid_at
        update_fields = [
            'subscription_package',
            'subscription_billing_cycle',
            'subscription_status',
            'subscription_start_date',
            'subscription_expiry_date',
            'student_limit',
            'registration_payment_amount',
            'registration_payment_reference',
            'registration_payment_paid_at',
            'subscription_active_until',
            'subscription_last_payment_reference',
            'subscription_last_paid_at',
        ]
        if mark_registration_paid:
            institution.registration_payment_status = 'paid'
            update_fields.append('registration_payment_status')
        institution.save(update_fields=update_fields)
        warning = _package_change_warning(institution, package_code)
        if warning:
            messages.warning(request, warning)
        if institution.verification_status == 'approved':
            Profile.objects.filter(
                institution=institution,
                created_via='school-register',
                is_approved=False,
            ).update(is_approved=True, approved_at=timezone.now())
        messages.success(request, success_message)
        return redirect(login_route_name)

    return None


def _registration_payment(request, institution_type, school_code, login_route_name, login_url):
    institution = get_object_or_404(Institution, institution_type=institution_type, school_code__iexact=school_code)
    payment_route_name = f'edu:{institution_type}_registration_payment'
    if request.method == 'POST':
        response = _confirm_edu_subscription_payment(
            request,
            institution,
            payment_route_name,
            {'school_code': institution.school_code},
            login_route_name,
            'Payment confirmed. VilaStore will now complete the portal setup review.',
            mark_registration_paid=True,
        )
        if response:
            return response

    if not institution.registration_payment_amount:
        cycle = _normalize_edu_billing_cycle(institution.subscription_billing_cycle)
        institution.registration_payment_amount = _edu_subscription_amount(cycle, institution.subscription_package)
        institution.save(update_fields=['registration_payment_amount'])

    return render(request, 'edu/registration_payment.html', _edu_payment_context(institution, login_url, mode='registration'))


@login_required
def edu_subscription_renewal(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or not profile.institution:
        messages.error(request, 'School profile is required before renewal.')
        return redirect('edu:index')

    institution = profile.institution
    if profile.role not in {'admin', 'vc', 'provost'}:
        messages.error(request, 'Only school administrators can renew Edu Portal subscription.')
        return redirect('edu:secondary_dashboard' if profile.institution_type == 'secondary' else 'edu:tertiary_dashboard', role=profile.role)

    if request.method == 'POST':
        response = _confirm_edu_subscription_payment(
            request,
            institution,
            'edu:subscription_renewal',
            {},
            'edu:subscription_renewal',
            'Subscription renewed successfully.',
            mark_registration_paid=False,
        )
        if response:
            return response

    login_url = '/edu/tertiary/login/' if profile.institution_type == 'tertiary' else '/edu/secondary/login/'
    return render(request, 'edu/registration_payment.html', _edu_payment_context(institution, login_url, mode='renewal'))


def secondary_registration_payment(request, school_code):
    return _registration_payment(
        request,
        'secondary',
        school_code,
        'edu:secondary_login',
        '/edu/secondary/login/',
    )


def tertiary_registration_payment(request, school_code):
    return _registration_payment(
        request,
        'tertiary',
        school_code,
        'edu:tertiary_login',
        '/edu/tertiary/login/',
    )


@login_required(login_url='/edu/secondary/login/')
def secondary_admin_register(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'admin':
        messages.error(request, 'Only Admin can access this page.')
        return redirect('edu:secondary_login')

    institutions = Institution.objects.filter(institution_type='secondary').order_by('name')
    classes = AcademicClass.objects.filter(institution__institution_type='secondary').order_by('name')

    return render(request, 'edu/secondary_admin_register.html', {
        'institutions': institutions,
        'classes': classes,
        'role_options': SECONDARY_ROLES,
        'ownership_choices': Institution.OWNERSHIP_CHOICES,
        'grading_choices': Institution.GRADING_CHOICES,
    })


@login_required(login_url='/edu/secondary/login/')
def secondary_create_user(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'admin':
        messages.error(request, 'Only Admin can create users.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'student')
        class_id = request.POST.get('academic_class')

        if not all([password, full_name, email]):
            messages.error(request, 'Please fill all required fields, including email address.')
            return redirect('edu:secondary_dashboard', role=creator_profile.role)

        if not _email_is_available(email):
            messages.error(request, 'That email address is already used by another account.')
            return redirect('edu:secondary_dashboard', role=creator_profile.role)

        if role not in [r['slug'] for r in SECONDARY_ROLES]:
            role = 'student'

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = role
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()
            email_sent = _send_edu_verification_email(request, profile)

            if role == 'student':
                if not _can_add_students(creator_profile.institution):
                    user.delete()
                    messages.error(request, _student_capacity_message(creator_profile.institution))
                    return redirect('edu:secondary_dashboard', role=creator_profile.role)
                academic_class = AcademicClass.objects.filter(id=class_id).first()
                Student.objects.create(
                    institution=creator_profile.institution,
                    user=user,
                    full_name=full_name,
                    student_id=username,
                    academic_class=academic_class,
                    status='Active',
                )
            else:
                Staff.objects.create(
                    institution=creator_profile.institution,
                    user=user,
                    full_name=full_name,
                    staff_id=username,
                    role=role,
                    department='',
                )

            if email_sent:
                messages.success(request, f'Account created successfully. ID: {username}. Verification email sent.')
            else:
                messages.success(request, f'Account created successfully. ID: {username}. We could not send the verification email - share this ID with the user directly.')
        except IntegrityError:
            messages.error(request, 'Username already exists.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))

    return redirect('edu:secondary_dashboard', role=creator_profile.role)


@login_required(login_url='/edu/secondary/login/')
def secondary_add_class(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can add classes.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        name = request.POST.get('class_name', '').strip()
        level = request.POST.get('level') or 1
        if not name:
            messages.error(request, 'Class name is required.')
        else:
            AcademicClass.objects.get_or_create(
                institution=creator_profile.institution,
                name=name,
                defaults={'level': int(level)},
            )
            messages.success(request, 'Class saved.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='classes')


@login_required(login_url='/edu/secondary/login/')
def secondary_assign_subjects(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can assign subjects.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        class_id = request.POST.get('academic_class')
        subject_ids = request.POST.getlist('subjects')
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        if not academic_class:
            messages.error(request, 'Please select a class.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='classes')

        if subject_ids:
            for sid in subject_ids:
                subject = Subject.objects.filter(id=sid, institution=creator_profile.institution).first()
                if subject:
                    ClassSubject.objects.get_or_create(academic_class=academic_class, subject=subject)
            messages.success(request, 'Subjects assigned to class.')
        else:
            messages.error(request, 'Select at least one subject.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='classes')


@login_required
def secondary_create_fee(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can manage fees.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        fee_type = request.POST.get('fee_type', '').strip()
        amount = request.POST.get('amount', '').strip()
        term = request.POST.get('term', '').strip()
        session = request.POST.get('session', '').strip()
        due_date = request.POST.get('due_date', '').strip()
        applies_to_all = request.POST.get('applies_to_all') == 'on'
        class_ids = request.POST.getlist('classes')

        if not name or not amount:
            messages.error(request, 'Fee name and amount are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        fee = Fee.objects.create(
            institution=creator_profile.institution,
            name=name,
            fee_type=fee_type,
            amount=amount,
            term=term,
            session=session,
            due_date=due_date or None,
            applies_to_all=applies_to_all,
        )
        if class_ids:
            fee.classes.set(AcademicClass.objects.filter(id__in=class_ids, institution=creator_profile.institution))
        messages.success(request, 'Fee created.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_delete_fee(request, fee_id):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can manage fees.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        Fee.objects.filter(id=fee_id, institution=creator_profile.institution).delete()
        messages.success(request, 'Fee deleted.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_record_payment(request):
    creator_profile = _get_secondary_accountant_profile(request)
    if not creator_profile:
        messages.error(request, 'Only Accountants can record payments.')
        return redirect('edu:secondary_dashboard', role='accountant')

    if request.method == 'POST':
        fee_id = request.POST.get('fee')
        student_id = request.POST.get('student')
        amount = request.POST.get('amount', '').strip()
        status = request.POST.get('status', 'Paid').strip() or 'Paid'
        fee = Fee.objects.filter(id=fee_id, institution=creator_profile.institution).first()
        student = Student.objects.filter(id=student_id, institution=creator_profile.institution).first()

        if not fee or not student or not amount:
            messages.error(request, 'Fee, student, and amount are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        if status not in ['Paid', 'Pending']:
            status = 'Paid'

        eligible_students = _fee_student_queryset(fee)
        if not eligible_students.filter(id=student.id).exists():
            messages.error(request, 'Selected fee does not apply to this student.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        Payment.objects.create(
            institution=creator_profile.institution,
            fee=fee,
            student=student,
            amount=amount,
            status=status,
            payment_method='Manual',
        )
        messages.success(request, 'Payment recorded.')

    return redirect('edu:secondary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_online_payment(request):
    creator_profile = _get_secondary_accountant_profile(request)
    if not creator_profile:
        messages.error(request, 'Only Accountants can collect online payments.')
        return redirect('edu:secondary_dashboard', role='accountant')

    institution = creator_profile.institution

    if request.method == 'POST':
        fee_id = request.POST.get('fee')
        student_id = request.POST.get('student')
        amount_raw = request.POST.get('amount', '').strip()
        payment_reference = request.POST.get('payment_reference', '').strip()

        fee = Fee.objects.filter(id=fee_id, institution=institution).first()
        student = Student.objects.filter(id=student_id, institution=institution).first()
        if not fee or not student or not amount_raw or not payment_reference:
            messages.error(request, 'Fee, student, amount, and payment reference are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        if not institution.payment_secret_key:
            messages.error(request, 'Payment secret key is not configured for this school.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        if not _fee_student_queryset(fee).filter(id=student.id).exists():
            messages.error(request, 'Selected fee does not apply to this student.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        try:
            expected_amount = Decimal(amount_raw)
        except Exception:
            messages.error(request, 'Payment amount is invalid.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        try:
            verify_response = requests.get(
                f"https://api.flutterwave.com/v3/transactions/{payment_reference}/verify",
                headers={"Authorization": f"Bearer {institution.payment_secret_key}"},
                timeout=15,
            )
            verify_payload = verify_response.json()
        except Exception:
            messages.error(request, 'Could not verify payment right now. Please try again.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        tx_data = verify_payload.get('data') or {}
        tx_status = (tx_data.get('status') or '').strip().lower()
        if (verify_payload.get('status') or '').strip().lower() != 'success' or tx_status != 'successful':
            messages.error(request, 'Payment was not successful.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        try:
            paid_amount = Decimal(str(tx_data.get('amount') or '0'))
        except Exception:
            paid_amount = Decimal('0.00')
        if paid_amount < expected_amount:
            messages.error(request, 'Paid amount is less than the required fee amount.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        currency = (tx_data.get('currency') or '').strip().upper()
        if currency and currency != (institution.currency or 'NGN').upper():
            messages.error(request, 'Payment currency does not match school currency.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='fees')

        payment, created = Payment.objects.get_or_create(
            institution=institution,
            gateway_reference=payment_reference,
            defaults={
                'fee': fee,
                'student': student,
                'amount': paid_amount,
                'status': 'Paid',
                'payment_method': 'Flutterwave',
            },
        )
        if not created:
            messages.info(request, 'This payment was already recorded.')
        else:
            messages.success(request, f'Online payment confirmed. Receipt: {payment.reference}')
        return redirect(_payment_receipt_url(payment))

    return redirect('edu:secondary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_student_online_payment(request):
    profile = _get_secondary_student_profile(request)
    if not profile:
        messages.error(request, 'Only Students can pay school fees here.')
        return redirect('edu:secondary_dashboard', role='student')

    institution = profile.institution
    student = Student.objects.filter(user=request.user, institution=institution).first()
    if not student:
        messages.error(request, 'Student record not found.')
        return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

    if request.method == 'POST':
        fee_id = request.POST.get('fee')
        amount_raw = request.POST.get('amount', '').strip()
        payment_reference = request.POST.get('payment_reference', '').strip()
        fee = Fee.objects.filter(id=fee_id, institution=institution).first()

        if not fee or not amount_raw or not payment_reference:
            messages.error(request, 'Fee, amount, and payment reference are required.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')
        if not institution.payment_secret_key:
            messages.error(request, 'Payment secret key is not configured for this school.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')
        if not _fee_student_queryset(fee).filter(id=student.id).exists():
            messages.error(request, 'This fee does not apply to your class.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        try:
            expected_amount = Decimal(amount_raw)
        except Exception:
            messages.error(request, 'Payment amount is invalid.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        try:
            verify_response = requests.get(
                f"https://api.flutterwave.com/v3/transactions/{payment_reference}/verify",
                headers={"Authorization": f"Bearer {institution.payment_secret_key}"},
                timeout=15,
            )
            verify_payload = verify_response.json()
        except Exception:
            messages.error(request, 'Could not verify payment right now. Please try again.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        tx_data = verify_payload.get('data') or {}
        tx_status = (tx_data.get('status') or '').strip().lower()
        if (verify_payload.get('status') or '').strip().lower() != 'success' or tx_status != 'successful':
            messages.error(request, 'Payment was not successful.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        try:
            paid_amount = Decimal(str(tx_data.get('amount') or '0'))
        except Exception:
            paid_amount = Decimal('0.00')
        if paid_amount < expected_amount:
            messages.error(request, 'Paid amount is less than the required fee amount.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        currency = (tx_data.get('currency') or '').strip().upper()
        if currency and currency != (institution.currency or 'NGN').upper():
            messages.error(request, 'Payment currency does not match school currency.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')

        payment, created = Payment.objects.get_or_create(
            institution=institution,
            gateway_reference=payment_reference,
            defaults={
                'fee': fee,
                'student': student,
                'amount': paid_amount,
                'status': 'Paid',
                'payment_method': 'Flutterwave',
            },
        )
        if payment.student_id != student.id:
            messages.error(request, 'Payment reference belongs to another student.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')
        if created:
            messages.success(request, f'Payment confirmed. Receipt: {payment.reference}')
        else:
            messages.info(request, 'This payment was already recorded.')
        return redirect(_payment_receipt_url(payment))

    return redirect('edu:secondary_page', role=profile.role, page='pay-fees')


@login_required
def secondary_payment_receipt(request, reference):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary':
        messages.error(request, 'Access denied.')
        return redirect('edu:index')

    payment = get_object_or_404(
        Payment.objects.select_related('institution', 'student', 'fee'),
        reference=reference,
        institution=profile.institution,
    )
    if profile.role == 'student':
        student = Student.objects.filter(user=request.user, institution=profile.institution).first()
        if not student or payment.student_id != student.id:
            messages.error(request, 'Receipt not found for your account.')
            return redirect('edu:secondary_page', role=profile.role, page='pay-fees')
    return render(request, 'edu/payment_receipt.html', {
        'payment': payment,
        'institution': payment.institution,
    })


@login_required
def secondary_payment_settings(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can update payment settings.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        institution = creator_profile.institution
        institution.payment_provider = request.POST.get('payment_provider', '').strip()
        institution.payment_public_key = request.POST.get('payment_public_key', '').strip()
        institution.payment_secret_key = request.POST.get('payment_secret_key', '').strip()
        institution.allow_online_payment = request.POST.get('allow_online_payment') == 'on'
        institution.save(update_fields=['payment_provider', 'payment_public_key', 'payment_secret_key', 'allow_online_payment'])
        messages.success(request, 'Payment settings updated.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_create_salary_voucher(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'accountant':
        messages.error(request, 'Only Accountants can create salary vouchers.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'accountant')

    institution = profile.institution
    if request.method == 'POST':
        staff_id = request.POST.get('staff', '').strip()
        staff = Staff.objects.filter(id=staff_id, institution=institution).first()
        staff_name = (request.POST.get('staff_name') or (staff.full_name if staff else '')).strip()
        account_number = request.POST.get('bank_account_number', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        bank_code = request.POST.get('bank_code', '').strip()
        provided_account_name = request.POST.get('verified_account_name', '').strip()
        gateway = _normalize_gateway(request.POST.get('payment_gateway'))
        frequency = request.POST.get('payment_frequency', 'monthly').strip() or 'monthly'
        payment_date_raw = request.POST.get('payment_date', '').strip()
        amount_raw = request.POST.get('salary_amount', '').strip()

        try:
            salary_amount = Decimal(amount_raw)
            if salary_amount <= 0:
                raise ValueError
        except Exception:
            messages.error(request, 'Enter a valid salary amount.')
            return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')

        try:
            payment_date = timezone.datetime.strptime(payment_date_raw, '%Y-%m-%d').date()
        except Exception:
            messages.error(request, 'Select a valid salary payment date.')
            return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')

        if not staff_name or not bank_name:
            messages.error(request, 'Staff name and bank name are required.')
            return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')

        verified, account_name, account_status, note = _verify_salary_account(
            institution,
            gateway,
            account_number,
            bank_code,
            provided_account_name,
        )
        if not verified:
            messages.error(request, note)
            return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')

        SalaryVoucher.objects.create(
            institution=institution,
            staff=staff,
            staff_name=staff_name,
            bank_account_number=account_number,
            bank_name=bank_name,
            bank_code=bank_code,
            verified_account_name=account_name,
            salary_amount=salary_amount,
            payment_date=payment_date,
            payment_frequency=frequency if frequency in dict(SalaryVoucher.FREQUENCY_CHOICES) else 'monthly',
            payment_gateway=gateway,
            status='pending',
            account_verification_status=account_status,
            account_verification_note=note,
            created_by=request.user,
        )
        messages.success(request, 'Salary voucher created and sent to Admin for approval.')
    return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')


@login_required
def secondary_approve_salary_voucher(request, voucher_id):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'admin':
        messages.error(request, 'Only Admin can approve salary vouchers.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'admin')

    voucher = get_object_or_404(SalaryVoucher, id=voucher_id, institution=profile.institution)
    if request.method == 'POST':
        if voucher.status != 'pending':
            messages.error(request, 'Only pending salary vouchers can be approved.')
        elif voucher.account_verification_status not in {'verified', 'manual_review'}:
            messages.error(request, 'Voucher account must be verified or marked for manual review before approval.')
        else:
            voucher.status = 'approved'
            voucher.approved_by = request.user
            voucher.approved_at = timezone.now()
            voucher.failure_reason = ''
            voucher.save(update_fields=['status', 'approved_by', 'approved_at', 'failure_reason', 'updated_at'])
            messages.success(request, 'Salary voucher approved. It will be processed on the selected payment date.')
    return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')


@login_required
def secondary_process_salary_vouchers(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role not in {'admin', 'accountant'}:
        messages.error(request, 'Only Admin or Accountant can process due salary vouchers.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'admin')

    if request.method == 'POST':
        voucher_id = request.POST.get('voucher_id', '').strip()
        vouchers = SalaryVoucher.objects.filter(
            institution=profile.institution,
            status='approved',
            payment_date__lte=timezone.localdate(),
        )
        if voucher_id:
            vouchers = vouchers.filter(id=voucher_id)
        processed = 0
        failed = 0
        last_message = ''
        for voucher in vouchers:
            ok, message = _process_salary_voucher(voucher)
            last_message = message
            if ok:
                processed += 1
            else:
                failed += 1
        if processed:
            messages.success(request, f'{processed} salary payout(s) processed successfully.')
        if failed:
            messages.error(request, f'{failed} salary payout(s) failed. {last_message}')
        if not processed and not failed:
            messages.info(request, 'No approved salary vouchers are due for processing.')
    return redirect('edu:secondary_page', role=profile.role, page='salary-vouchers')


@login_required
def secondary_save_scores(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'teacher':
        messages.error(request, 'Only Teachers can enter scores.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'teacher')

    staff = Staff.objects.filter(user=request.user, institution=profile.institution).first()
    if not staff:
        messages.error(request, 'Teacher record not found.')
        return redirect('edu:secondary_page', role=profile.role, page='enter-scores')

    if request.method == 'POST':
        class_id = request.POST.get('academic_class')
        subject_id = request.POST.get('subject')
        session_id = request.POST.get('academic_session')
        term_id = request.POST.get('academic_term')

        academic_class = AcademicClass.objects.filter(id=class_id, institution=profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=profile.institution).first()
        session, term = _get_selected_session_term(profile.institution, session_id, term_id)
        if not session or not term or not academic_class or not subject:
            messages.error(request, 'Please select academic session, term, class, and subject.')
            return redirect('edu:secondary_page', role=profile.role, page='enter-scores')

        assigned = TeacherAssignment.objects.filter(teacher=staff, academic_class=academic_class).exists()
        if not assigned:
            messages.error(request, 'You are not assigned to that class.')
            return redirect('edu:secondary_page', role=profile.role, page='enter-scores')
        if not TeacherSubjectAssignment.objects.filter(teacher=staff, academic_class=academic_class, subject=subject).exists():
            messages.error(request, 'You are not assigned to that subject.')
            return redirect('edu:secondary_page', role=profile.role, page='enter-scores')

        student_ids = request.POST.getlist('students')
        students = Student.objects.filter(id__in=student_ids, academic_class=academic_class, institution=profile.institution)

        failed_students = []
        for student in students:
            def _to_decimal(value):
                try:
                    return Decimal(str(value or '0'))
                except Exception:
                    return Decimal('0.00')

            test1 = _to_decimal(request.POST.get(f'test1_{student.id}'))
            test2 = _to_decimal(request.POST.get(f'test2_{student.id}'))
            assignment = _to_decimal(request.POST.get(f'assignment_{student.id}'))
            exam = _to_decimal(request.POST.get(f'exam_{student.id}'))

            result = Result.objects.filter(
                institution=profile.institution,
                student=student,
                subject=subject,
                academic_session=session,
                academic_term=term,
            ).first()
            if result is None:
                result = Result(
                    institution=profile.institution,
                    student=student,
                    subject=subject,
                    academic_session=session,
                    academic_term=term,
                )
            result.academic_class = academic_class
            result.teacher = staff
            result.session = session.name
            result.term = term.get_term_display()
            result.test1 = test1
            result.test2 = test2
            result.assignment = assignment
            result.exam = exam
            result._changed_by = request.user
            try:
                result.save()
            except ValidationError as exc:
                failed_students.append(f"{student.full_name}: {'; '.join(exc.messages)}")

        if failed_students:
            messages.error(request, 'Could not save scores for: ' + ' | '.join(failed_students))
        else:
            messages.success(request, 'Scores saved.')

        ResultSubmission.objects.update_or_create(
            institution=profile.institution,
            academic_class=academic_class,
            subject=subject,
            submitted_by=staff,
            academic_session=session,
            academic_term=term,
            defaults={
                'session': session.name,
                'term': term.get_term_display(),
                'status': 'draft',
                'published_at': None,
            },
        )
    return redirect('edu:secondary_page', role=profile.role, page='enter-scores')


@login_required
def secondary_submit_results(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'teacher':
        messages.error(request, 'Only Teachers can submit results.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'teacher')

    staff = Staff.objects.filter(user=request.user, institution=profile.institution).first()
    if not staff:
        messages.error(request, 'Teacher record not found.')
        return redirect('edu:secondary_page', role=profile.role, page='submit-results')

    if request.method == 'POST':
        class_id = request.POST.get('academic_class')
        subject_id = request.POST.get('subject')
        session_id = request.POST.get('academic_session')
        term_id = request.POST.get('academic_term')

        academic_class = AcademicClass.objects.filter(id=class_id, institution=profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=profile.institution).first()
        session, term = _get_selected_session_term(profile.institution, session_id, term_id)
        if not session or not term or not academic_class or not subject:
            messages.error(request, 'Please select academic session, term, class, and subject.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')

        assigned = TeacherAssignment.objects.filter(teacher=staff, academic_class=academic_class).exists()
        if not assigned:
            messages.error(request, 'You are not assigned to that class.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')
        if not TeacherSubjectAssignment.objects.filter(teacher=staff, academic_class=academic_class, subject=subject).exists():
            messages.error(request, 'You are not assigned to that subject.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')

        teacher_comment = request.POST.get('teacher_comment', '').strip()
        ResultSubmission.objects.update_or_create(
            institution=profile.institution,
            academic_class=academic_class,
            subject=subject,
            submitted_by=staff,
            academic_session=session,
            academic_term=term,
            defaults={
                'session': session.name,
                'term': term.get_term_display(),
                'status': 'submitted_to_examiner',
                'teacher_comment': teacher_comment,
                'published_at': None,
            },
        )
        messages.success(request, 'Results submitted to Examiner.')
    return redirect('edu:secondary_page', role=profile.role, page='submit-results')


@login_required
def secondary_review_results(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'examiner':
        messages.error(request, 'Only Examiners can review results.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'examiner')

    if request.method == 'POST':
        submission_id = request.POST.get('submission_id')
        action = request.POST.get('action', 'approve')
        submission = ResultSubmission.objects.filter(id=submission_id, institution=profile.institution).first()
        if not submission:
            messages.error(request, 'Submission not found.')
            return redirect('edu:secondary_page', role=profile.role, page='review-results')
        if action == 'return':
            submission.status = 'returned_for_correction'
            submission.examiner_comment = request.POST.get('examiner_comment', '').strip()
            submission.published_at = None
            submission.save(update_fields=['status', 'examiner_comment', 'published_at'])
            messages.success(request, 'Result returned to teacher for correction.')
        else:
            submission.status = 'approved_by_examiner'
            submission.examiner_comment = request.POST.get('examiner_comment', '').strip()
            submission.published_at = None
            submission.save(update_fields=['status', 'examiner_comment', 'published_at'])
            messages.success(request, 'Result approved and sent to Admin.')
        return redirect(f"/edu/secondary/{profile.role}/review-results/?submission={submission.id}")

    return redirect('edu:secondary_page', role=profile.role, page='review-results')


@login_required
def secondary_admin_result_approval(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'admin':
        messages.error(request, 'Only Admin can approve and publish results.')
        return redirect('edu:secondary_dashboard', role=profile.role if profile else 'admin')

    if request.method == 'POST':
        submission_id = request.POST.get('submission_id')
        submission = ResultSubmission.objects.filter(
            id=submission_id,
            institution=profile.institution,
            status='approved_by_examiner',
        ).first()
        if not submission:
            messages.error(request, 'Result submission is not ready for Admin approval.')
            return redirect('edu:secondary_page', role=profile.role, page='approve-results')

        submission.status = 'published'
        submission.admin_comment = request.POST.get('admin_comment', '').strip()
        submission.published_at = timezone.now()
        submission.save(update_fields=['status', 'admin_comment', 'published_at'])
        messages.success(request, 'Result approved and published to students.')
    return redirect('edu:secondary_page', role=profile.role, page='approve-results')


@login_required
def secondary_student_profile_update(request):
    profile = _get_secondary_student_profile(request)
    if not profile:
        messages.error(request, 'Only Students can update this profile.')
        return redirect('edu:secondary_dashboard', role='student')

    student = Student.objects.filter(user=request.user, institution=profile.institution).first()
    if not student:
        messages.error(request, 'Student record not found.')
        return redirect('edu:secondary_page', role=profile.role, page='profile')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if email and get_user_model().objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
            messages.error(request, 'That email address is already used by another account.')
            return redirect('edu:secondary_page', role=profile.role, page='profile')
        email_changed = email and email.lower() != (request.user.email or '').lower()
        if email:
            request.user.email = email
        request.user.phone = request.POST.get('phone', '').strip()
        request.user.address = request.POST.get('home_address', '').strip()
        request.user.save(update_fields=['email', 'phone', 'address'])
        if email_changed:
            _mark_email_unverified(profile)
            profile.save(update_fields=[
                'email_verified',
                'email_verification_token',
                'email_verification_sent_at',
                'email_verification_expires_at',
            ])
            email_sent = _send_edu_verification_email(request, profile)

        student.next_of_kin_name = request.POST.get('next_of_kin_name', '').strip()
        student.next_of_kin_phone = request.POST.get('next_of_kin_phone', '').strip()
        student.next_of_kin_relationship = request.POST.get('next_of_kin_relationship', '').strip()
        student.save(update_fields=['next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship'])
        if email_changed and not email_sent:
            messages.warning(request, 'Profile updated, but we could not send the verification email to your new address. Contact your school admin.')
        else:
            messages.success(request, 'Profile updated. Please verify your new email address before your next login.' if email_changed else 'Profile updated.')

    return redirect('edu:secondary_page', role=profile.role, page='profile')


@login_required
def tertiary_create_fee(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'tertiary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can manage fees.')
        return redirect('edu:tertiary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        fee_type = request.POST.get('fee_type', '').strip()
        amount = request.POST.get('amount', '').strip()
        term = request.POST.get('term', '').strip()
        session = request.POST.get('session', '').strip()
        due_date = request.POST.get('due_date', '').strip()
        applies_to_all = request.POST.get('applies_to_all') == 'on'
        department_ids = request.POST.getlist('departments')

        if not name or not amount:
            messages.error(request, 'Fee name and amount are required.')
            return redirect('edu:tertiary_page', role=creator_profile.role, page='fees')

        fee = Fee.objects.create(
            institution=creator_profile.institution,
            name=name,
            fee_type=fee_type,
            amount=amount,
            term=term,
            session=session,
            due_date=due_date or None,
            applies_to_all=applies_to_all,
        )
        if department_ids:
            fee.departments.set(Department.objects.filter(id__in=department_ids, faculty__institution=creator_profile.institution))
        messages.success(request, 'Fee created.')
    return redirect('edu:tertiary_page', role=creator_profile.role, page='fees')


@login_required
def tertiary_delete_fee(request, fee_id):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'tertiary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can manage fees.')
        return redirect('edu:tertiary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        Fee.objects.filter(id=fee_id, institution=creator_profile.institution).delete()
        messages.success(request, 'Fee deleted.')
    return redirect('edu:tertiary_page', role=creator_profile.role, page='fees')


@login_required
def tertiary_payment_settings(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'tertiary' or creator_profile.role != 'accountant':
        messages.error(request, 'Only Accountants can update payment settings.')
        return redirect('edu:tertiary_dashboard', role=creator_profile.role if creator_profile else 'accountant')

    if request.method == 'POST':
        institution = creator_profile.institution
        institution.payment_provider = request.POST.get('payment_provider', '').strip()
        institution.payment_public_key = request.POST.get('payment_public_key', '').strip()
        institution.payment_secret_key = request.POST.get('payment_secret_key', '').strip()
        institution.allow_online_payment = request.POST.get('allow_online_payment') == 'on'
        institution.save(update_fields=['payment_provider', 'payment_public_key', 'payment_secret_key', 'allow_online_payment'])
        messages.success(request, 'Payment settings updated.')
    return redirect('edu:tertiary_page', role=creator_profile.role, page='fees')


@login_required
def secondary_remove_class_subject(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can update class subjects.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        class_id = request.POST.get('academic_class')
        subject_id = request.POST.get('subject')
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=creator_profile.institution).first()
        if academic_class and subject:
            ClassSubject.objects.filter(academic_class=academic_class, subject=subject).delete()
            messages.success(request, 'Subject removed from class.')
        else:
            messages.error(request, 'Invalid class or subject.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='classes')


@login_required(login_url='/edu/secondary/login/')
def secondary_add_session_term(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can add sessions/terms.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        session_name = request.POST.get('session_name', '').strip()
        term = request.POST.get('term', '').strip()
        is_current = request.POST.get('is_current') == 'on'
        if not session_name or not term:
            messages.error(request, 'Session and term are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='sessions')

        session, _ = AcademicSession.objects.get_or_create(
            institution=creator_profile.institution,
            name=session_name,
        )
        if is_current:
            AcademicSession.objects.filter(institution=creator_profile.institution).update(is_current=False)
            AcademicTerm.objects.filter(session__institution=creator_profile.institution).update(is_current=False)
            session.is_current = True
            session.save(update_fields=['is_current'])

        AcademicTerm.objects.update_or_create(
            session=session,
            term=term,
            defaults={'is_current': is_current},
        )
        messages.success(request, 'Session/term saved.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='sessions')


@login_required(login_url='/edu/secondary/login/')
def secondary_assign_class_session_term(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can assign class sessions.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        class_id = request.POST.get('academic_class')
        session_id = request.POST.get('academic_session')
        term_id = request.POST.get('academic_term')
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        session, term = _get_selected_session_term(creator_profile.institution, session_id, term_id)
        if not academic_class or not session or not term:
            messages.error(request, 'Class, academic session, and term are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='sessions')

        academic_class.academic_session = session
        academic_class.academic_term = term
        academic_class.save(update_fields=['academic_session', 'academic_term'])
        messages.success(request, f'{academic_class.name} assigned to {session.name} - {term.get_term_display()}.')

    return redirect('edu:secondary_page', role=creator_profile.role, page='sessions')


@login_required(login_url='/edu/secondary/login/')
def secondary_add_student(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can add students.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        class_id = request.POST.get('academic_class')
        teacher_id = request.POST.get('teacher')
        kin_name = request.POST.get('next_of_kin_name', '').strip()
        kin_phone = request.POST.get('next_of_kin_phone', '').strip()
        kin_relationship = request.POST.get('next_of_kin_relationship', '').strip()
        photo = request.FILES.get('photo')
        if not full_name or not password or not email:
            messages.error(request, 'Full name, email, and password are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='register')

        if not _email_is_available(email):
            messages.error(request, 'That email address is already used by another account.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='register')

        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        if not _can_add_students(creator_profile.institution):
            messages.error(request, _student_capacity_message(creator_profile.institution))
            return redirect('edu:secondary_page', role=creator_profile.role, page='register')
        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = 'student'
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()
            email_sent = _send_edu_verification_email(request, profile)

            Student.objects.create(
                institution=creator_profile.institution,
                user=user,
                full_name=full_name,
                student_id=username,
                academic_class=academic_class,
                status='Active',
                next_of_kin_name=kin_name,
                next_of_kin_phone=kin_phone,
                next_of_kin_relationship=kin_relationship,
                photo=photo,
            )

            if teacher_id and academic_class:
                teacher = Staff.objects.filter(id=teacher_id, institution=creator_profile.institution, role='teacher').first()
                if teacher:
                    TeacherAssignment.objects.get_or_create(
                        institution=creator_profile.institution,
                        teacher=teacher,
                        academic_class=academic_class,
                    )

            if email_sent:
                messages.success(request, f'Student registered. ID: {username}. Verification email sent.')
            else:
                messages.success(request, f'Student registered. ID: {username}. We could not send the verification email - share this ID with the user directly.')
        except IntegrityError:
            messages.error(request, 'Could not create student.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))

    return redirect('edu:secondary_page', role=creator_profile.role, page='register')


@login_required(login_url='/edu/secondary/login/')
def secondary_assign_student_class(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can assign student classes.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'registry')

    if request.method == 'POST':
        student_id = request.POST.get('student')
        class_id = request.POST.get('academic_class')
        session_id = request.POST.get('academic_session')
        term_id = request.POST.get('academic_term')
        student = Student.objects.filter(id=student_id, institution=creator_profile.institution).first()
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        session = AcademicSession.objects.filter(id=session_id, institution=creator_profile.institution).first()
        term = AcademicTerm.objects.filter(id=term_id, session__institution=creator_profile.institution).first()

        if not student or not academic_class:
            messages.error(request, 'Please select a valid student and class.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='assign-class')

        StudentClassHistory.objects.filter(student=student).update(is_current=False)
        student.academic_class = academic_class
        student.save(update_fields=['academic_class'])
        StudentClassHistory.objects.update_or_create(
            student=student,
            academic_class=academic_class,
            academic_session=session or academic_class.academic_session,
            academic_term=term or academic_class.academic_term,
            defaults={'is_current': True},
        )
        messages.success(request, f'{student.full_name} assigned to {academic_class.name}.')

    return redirect('edu:secondary_page', role=creator_profile.role, page='assign-class')


@login_required(login_url='/edu/secondary/login/')
def secondary_assign_teacher(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can assign teachers.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        teacher_id = request.POST.get('teacher')
        class_id = request.POST.get('academic_class')
        teacher = Staff.objects.filter(id=teacher_id, institution=creator_profile.institution, role='teacher').first()
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        if not teacher or not academic_class:
            messages.error(request, 'Please select teacher and class.')
        else:
            TeacherAssignment.objects.get_or_create(
                institution=creator_profile.institution,
                teacher=teacher,
                academic_class=academic_class,
            )
            messages.success(request, 'Teacher assigned to class.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='assign-teachers')


@login_required
def secondary_assign_teacher_subject(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can assign teacher subjects.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        teacher_id = request.POST.get('teacher')
        class_id = request.POST.get('academic_class')
        subject_id = request.POST.get('subject')

        teacher = Staff.objects.filter(id=teacher_id, institution=creator_profile.institution, role='teacher').first()
        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=creator_profile.institution).first()

        if not teacher or not academic_class or not subject:
            messages.error(request, 'Please select teacher, class, and subject.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='assign-teachers')

        if not TeacherAssignment.objects.filter(teacher=teacher, academic_class=academic_class).exists():
            messages.error(request, 'Teacher must be assigned to the class first.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='assign-teachers')

        if not ClassSubject.objects.filter(academic_class=academic_class, subject=subject).exists():
            messages.error(request, 'Subject must be assigned to the class first.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='assign-teachers')

        TeacherSubjectAssignment.objects.get_or_create(
            institution=creator_profile.institution,
            teacher=teacher,
            academic_class=academic_class,
            subject=subject,
        )
        messages.success(request, 'Teacher assigned to subject.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='assign-teachers')


@login_required(login_url='/edu/secondary/login/')
def secondary_add_subject(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role != 'admin':
        messages.error(request, 'Only Admin can add subjects.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        name = request.POST.get('subject_name', '').strip()
        code = request.POST.get('subject_code', '').strip()
        if not name:
            messages.error(request, 'Subject name is required.')
        else:
            Subject.objects.get_or_create(
                institution=creator_profile.institution,
                name=name,
                defaults={'code': code},
            )
            messages.success(request, 'Subject saved.')
    return redirect('edu:secondary_page', role=creator_profile.role, page='subjects')


@login_required(login_url='/edu/secondary/login/')
def secondary_add_teacher(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can add teachers.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'registry')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        photo = request.FILES.get('photo')
        if not full_name or not password or not email:
            messages.error(request, 'Full name, email, and password are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='users')

        if not _email_is_available(email):
            messages.error(request, 'That email address is already used by another account.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='users')

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = 'teacher'
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()
            email_sent = _send_edu_verification_email(request, profile)

            Staff.objects.create(
                institution=creator_profile.institution,
                user=user,
                full_name=full_name,
                staff_id=username,
                role='teacher',
                department='',
                photo=photo,
            )

            if email_sent:
                messages.success(request, f'Teacher created. ID: {username}. Verification email sent.')
            else:
                messages.success(request, f'Teacher created. ID: {username}. We could not send the verification email - share this ID with the teacher directly.')
        except IntegrityError:
            messages.error(request, 'Could not create teacher.')

    return redirect('edu:secondary_page', role=creator_profile.role, page='users')


@login_required(login_url='/edu/tertiary/login/')
def tertiary_create_user(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'tertiary' or creator_profile.role not in ['vc', 'provost']:
        messages.error(request, 'Only VC/Provost can create users.')
        return redirect('edu:tertiary_dashboard', role=creator_profile.role if creator_profile else 'vc')

    if request.method == 'POST':
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'student')
        faculty_id = request.POST.get('faculty')
        department_id = request.POST.get('department')

        if not all([password, full_name, email]):
            messages.error(request, 'Please fill all required fields, including email address.')
            return redirect('edu:tertiary_dashboard', role=creator_profile.role)

        if not _email_is_available(email):
            messages.error(request, 'That email address is already used by another account.')
            return redirect('edu:tertiary_dashboard', role=creator_profile.role)

        if role not in [r['slug'] for r in TERTIARY_ROLES]:
            role = 'student'

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.institution = creator_profile.institution
            profile.institution_type = 'tertiary'
            profile.role = role
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.faculty = Faculty.objects.filter(id=faculty_id).first() if faculty_id else None
            profile.department = Department.objects.filter(id=department_id).first() if department_id else None
            profile.save()
            email_sent = _send_edu_verification_email(request, profile)

            if role == 'student':
                if not _can_add_students(creator_profile.institution):
                    user.delete()
                    messages.error(request, _student_capacity_message(creator_profile.institution))
                    return redirect('edu:tertiary_dashboard', role=creator_profile.role)
                Student.objects.create(
                    institution=creator_profile.institution,
                    user=user,
                    full_name=full_name,
                    student_id=username,
                    status='Active',
                )
            else:
                Staff.objects.create(
                    institution=creator_profile.institution,
                    user=user,
                    full_name=full_name,
                    staff_id=username,
                    role=role,
                    department=profile.department.name if profile.department else '',
                )

            if email_sent:
                messages.success(request, f'Account created successfully. ID: {username}. Verification email sent.')
            else:
                messages.success(request, f'Account created successfully. ID: {username}. We could not send the verification email - share this ID with the user directly.')
        except IntegrityError:
            messages.error(request, 'Username already exists.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))

    return redirect('edu:tertiary_dashboard', role=creator_profile.role)


def tertiary_school_register(request):
    return _register_school_with_trial(request, 'tertiary')


def logout(request):
    active_portal = request.session.get('active_portal')
    auth_logout(request)
    if active_portal == 'shop':
        return redirect('login')
    return redirect('edu:index')


@login_required
def approve_profile(request, profile_id):
    approver = getattr(request.user, 'profile', None)
    if not approver:
        messages.error(request, 'Access denied.')
        return redirect('edu:index')

    if approver.institution_type == 'secondary' and approver.role != 'admin':
        messages.error(request, 'Only Admin can approve accounts.')
        return redirect('edu:secondary_dashboard', role=approver.role)

    if approver.institution_type == 'tertiary' and approver.role not in ['vc', 'provost']:
        messages.error(request, 'Only VC/Provost can approve accounts.')
        return redirect('edu:tertiary_dashboard', role=approver.role)

    profile = Profile.objects.filter(id=profile_id, institution=approver.institution).first()
    if not profile:
        messages.error(request, 'Profile not found.')
    else:
        profile.is_approved = True
        profile.approved_by = request.user
        profile.approved_at = timezone.now()
        profile.save()
        profile.user.is_active = True
        profile.user.save()
        messages.success(request, 'Account approved.')

    if approver.institution_type == 'secondary':
        return redirect('edu:secondary_dashboard', role=approver.role)
    return redirect('edu:tertiary_dashboard', role=approver.role)


@login_required
def secondary_dashboard(request, role):
    return secondary_page(request, role, 'dashboard')


@login_required
def secondary_page(request, role, page):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary':
        messages.error(request, 'Access denied for this dashboard.')
        return redirect('edu:index')

    role = profile.role

    institution = profile.institution
    if _subscription_is_expired(institution):
        return _expired_subscription_response(request, profile)

    today = timezone.localdate()
    students = Student.objects.filter(institution=institution).select_related('academic_class')[:5]
    fee_summary = _school_fee_summary(institution)
    fees_total = fee_summary['paid_total']
    fees_pending = fee_summary['outstanding_total']
    fees = Fee.objects.filter(institution=institution).prefetch_related('classes', 'departments').order_by('-id')
    payments_all = Payment.objects.filter(institution=institution).select_related('student', 'fee').order_by('-paid_at')
    payments = payments_all[:20]
    salary_vouchers_all = SalaryVoucher.objects.filter(institution=institution).select_related('staff', 'created_by', 'approved_by')
    salary_vouchers = salary_vouchers_all[:30]
    pending_salary_vouchers = salary_vouchers_all.filter(status='pending')
    approved_due_salary_vouchers = salary_vouchers_all.filter(status='approved', payment_date__lte=today)

    institution_results = Result.objects.filter(institution=institution)
    institution_results_count = institution_results.count()
    if institution_results_count:
        passed_count = institution_results.exclude(grade='F').count()
        pass_rate_display = f"{round((passed_count / institution_results_count) * 100)}%"
    else:
        pass_rate_display = "-"

    stats = [
        {"label": "Total Students", "value": str(Student.objects.filter(institution=institution).count())},
        {"label": "Total Staff", "value": str(Staff.objects.filter(institution=institution).count())},
        {"label": "Classes", "value": str(institution.classes.count() if institution else 0)},
        {"label": "Pass Rate", "value": pass_rate_display},
    ]

    role_label = next((r['label'] for r in SECONDARY_ROLES if r['slug'] == role), role.title())

    pending_profiles = []
    if profile.role == 'admin':
        pending_profiles = Profile.objects.filter(
            institution=institution,
            is_approved=False,
        ).select_related('user')

    students_all = Student.objects.filter(institution=institution).select_related('academic_class')
    staff_members = Staff.objects.filter(institution=institution).order_by('full_name')
    teachers = Staff.objects.filter(institution=institution, role='teacher').prefetch_related('assignments__academic_class', 'subject_assignments__academic_class', 'subject_assignments__subject')
    sessions = AcademicSession.objects.filter(institution=institution).order_by('-name')
    terms = AcademicTerm.objects.filter(session__institution=institution).select_related('session').order_by('-session__name', 'term')
    current_session = AcademicSession.objects.filter(institution=institution, is_current=True).first()
    current_term = AcademicTerm.objects.filter(session__institution=institution, is_current=True).first()
    subjects = Subject.objects.filter(institution=institution).order_by('name')
    class_subjects = AcademicClass.objects.filter(institution=institution).prefetch_related('class_subjects__subject').order_by('name')
    class_subject_map = {
        cls.id: [rel.subject_id for rel in cls.class_subjects.all()]
        for cls in class_subjects
    }
    teacher_classes = []
    teacher_students = Student.objects.none()
    teacher_subject_map = {}
    teacher_results_map = {}
    teacher_submissions = ResultSubmission.objects.none()
    teacher_dashboard_stats = []
    teacher_class_cards = []
    teacher_recent_submissions = []
    teacher_pending_corrections = []
    admin_dashboard_cards = []
    admin_recent_results = ResultSubmission.objects.none()
    admin_pending_count = 0
    registry_dashboard_cards = []
    registry_recent_students = Student.objects.none()
    registry_class_rows = []
    accountant_dashboard_cards = []
    accountant_fee_cards = []
    accountant_class_rows = []
    accountant_debtor_rows = []
    accountant_today_total = Decimal('0.00')
    accountant_pending_payments = Payment.objects.none()
    teacher_subject_assignments = TeacherSubjectAssignment.objects.filter(institution=institution).select_related('teacher', 'academic_class', 'subject')
    admin_result_submissions = ResultSubmission.objects.none()
    selected_admin_submission = None
    admin_review_results = Result.objects.none()
    admin_report_previews = []
    term_map = {}
    for term_obj in terms:
        term_map.setdefault(term_obj.session_id, []).append({
            'id': term_obj.id,
            'name': term_obj.get_term_display(),
        })
    examiner_submissions = ResultSubmission.objects.none()
    examiner_results = Result.objects.none()
    selected_submission = None
    examiner_report_previews = []
    examiner_dashboard_cards = []
    examiner_recent_submissions = ResultSubmission.objects.none()
    result_sheet_rows = []
    result_sheet_class = None
    result_sheet_session = ''
    result_sheet_term = ''
    id_card_students = students_all
    student_record = None
    student_subjects = Subject.objects.none()
    student_results = Result.objects.none()
    student_current_results = Result.objects.none()
    student_report_results = Result.objects.none()
    student_report_total = Decimal('0.00')
    student_report_average = Decimal('0.00')
    student_report_position = ''
    student_report_submission = None
    student_report_first_result = None
    student_report_card = None
    student_class_rows = []
    selected_student_class = None
    selected_class_subjects = Subject.objects.none()
    selected_class_results = Result.objects.none()
    selected_class_report_total = Decimal('0.00')
    selected_class_report_average = Decimal('0.00')
    selected_class_report_position = ''
    selected_class_report_submission = None
    selected_class_first_result = None
    selected_class_report_card = None
    student_payments = Payment.objects.none()
    student_fee_rows = []
    student_fee_total = Decimal('0.00')
    student_paid_total = Decimal('0.00')
    student_outstanding_total = Decimal('0.00')
    student_dashboard_cards = []
    selected_id_card_class_id = request.GET.get('class', '').strip()
    selected_id_card_session_id = request.GET.get('session', '').strip()
    if page == 'student-ids':
        if selected_id_card_class_id:
            id_card_students = id_card_students.filter(academic_class_id=selected_id_card_class_id)
        if selected_id_card_session_id:
            id_card_students = id_card_students.filter(academic_class__academic_session_id=selected_id_card_session_id)

    if role == 'admin':
        admin_result_submissions = ResultSubmission.objects.filter(
            institution=institution,
            status='approved_by_examiner',
        ).select_related('academic_class', 'subject', 'submitted_by').order_by('-submitted_at')
        admin_pending_count = pending_profiles.count()
        admin_recent_results = ResultSubmission.objects.filter(
            institution=institution,
        ).exclude(status='draft').select_related('academic_class', 'subject', 'submitted_by').order_by('-submitted_at')[:6]
        admin_dashboard_cards = [
            {'label': 'Students', 'value': students_all.count(), 'hint': 'Total registered learners', 'icon': 'graduation-cap'},
            {'label': 'Teachers', 'value': teachers.count(), 'hint': 'Teaching staff accounts', 'icon': 'users'},
            {'label': 'Classes', 'value': AcademicClass.objects.filter(institution=institution).count(), 'hint': 'Academic class groups', 'icon': 'school'},
            {'label': 'Pending Users', 'value': admin_pending_count, 'hint': 'Waiting for approval', 'icon': 'user-check'},
            {'label': 'Results to Approve', 'value': admin_result_submissions.count(), 'hint': 'Examiner-approved results', 'icon': 'file-check'},
            {'label': 'Outstanding Fees', 'value': f"NGN {fees_pending:.2f}", 'hint': 'School-wide balance', 'icon': 'wallet'},
        ]
        admin_submission_id = request.GET.get('submission')
        if admin_submission_id:
            selected_admin_submission = admin_result_submissions.filter(id=admin_submission_id).first()
        if not selected_admin_submission:
            selected_admin_submission = admin_result_submissions.first()
        if selected_admin_submission:
            admin_review_results = _results_for_submission(selected_admin_submission)
            admin_report_previews = _report_card_previews_for_submission(selected_admin_submission)

    if role == 'registry':
        registry_recent_students = students_all.order_by('-created_at')[:8]
        registry_class_rows = [
            {
                'class': cls,
                'students': students_all.filter(academic_class=cls).count(),
                'session': cls.academic_session,
                'term': cls.academic_term,
                'subjects': cls.class_subjects.count() if hasattr(cls, 'class_subjects') else 0,
            }
            for cls in AcademicClass.objects.filter(institution=institution).prefetch_related('class_subjects').order_by('level', 'name')
        ]
        registry_dashboard_cards = [
            {'label': 'Students', 'value': students_all.count(), 'hint': 'Total student records', 'icon': 'graduation-cap'},
            {'label': 'Classes', 'value': len(registry_class_rows), 'hint': 'Class records', 'icon': 'school'},
            {'label': 'Teachers', 'value': teachers.count(), 'hint': 'Staff records available', 'icon': 'users'},
            {'label': 'Sessions', 'value': sessions.count(), 'hint': 'Academic sessions', 'icon': 'calendar-days'},
            {'label': 'Current Session', 'value': current_session.name if current_session else '-', 'hint': current_term.get_term_display() if current_term else 'No current term', 'icon': 'calendar-check'},
            {'label': 'ID Cards', 'value': students_all.count(), 'hint': 'Students available for ID cards', 'icon': 'id-card'},
        ]

    if role == 'accountant':
        accountant_today_total = payments_all.filter(status='Paid', paid_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        accountant_pending_payments = payments_all.exclude(status='Paid')[:8]
        accountant_dashboard_cards = [
            {'label': 'Expected Fees', 'value': f"NGN {fee_summary['expected_total']:.2f}", 'hint': 'All assigned school fees', 'icon': 'receipt'},
            {'label': 'Total Collected', 'value': f"NGN {fees_total:.2f}", 'hint': 'Successful payments', 'icon': 'wallet'},
            {'label': 'Outstanding Balance', 'value': f"NGN {fees_pending:.2f}", 'hint': 'Unpaid and pending fees', 'icon': 'alert-circle'},
            {'label': "Today's Collection", 'value': f"NGN {accountant_today_total:.2f}", 'hint': today.strftime('%b %d, %Y'), 'icon': 'calendar-days'},
            {'label': 'Pending Payments', 'value': accountant_pending_payments.count(), 'hint': 'Needs follow-up', 'icon': 'clock'},
            {'label': 'Students Owing', 'value': 0, 'hint': 'Students with balance', 'icon': 'users'},
        ]
        for fee in fees:
            eligible_count = _fee_student_queryset(fee).count()
            expected = fee.amount * eligible_count
            collected = Payment.objects.filter(institution=institution, fee=fee, status='Paid').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            outstanding = expected - collected
            if outstanding < 0:
                outstanding = Decimal('0.00')
            accountant_fee_cards.append({
                'fee': fee,
                'eligible_count': eligible_count,
                'expected': expected,
                'collected': collected,
                'outstanding': outstanding,
                'is_complete': outstanding <= 0 and expected > 0,
            })
        for cls in AcademicClass.objects.filter(institution=institution).order_by('level', 'name'):
            class_students = students_all.filter(academic_class=cls)
            expected = Decimal('0.00')
            for fee in fees:
                if _fee_student_queryset(fee).filter(academic_class=cls).exists():
                    expected += fee.amount * class_students.count()
            collected = payments_all.filter(student__academic_class=cls, status='Paid').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            outstanding = expected - collected
            if outstanding < 0:
                outstanding = Decimal('0.00')
            if expected or collected:
                accountant_class_rows.append({
                    'class': cls,
                    'students': class_students.count(),
                    'expected': expected,
                    'collected': collected,
                    'outstanding': outstanding,
                })
        for student in students_all.order_by('academic_class__level', 'full_name'):
            expected = Decimal('0.00')
            for fee in fees:
                if _fee_student_queryset(fee).filter(id=student.id).exists():
                    expected += fee.amount
            paid = payments_all.filter(student=student, status='Paid').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            outstanding = expected - paid
            if outstanding > 0:
                accountant_debtor_rows.append({
                    'student': student,
                    'expected': expected,
                    'paid': paid,
                    'outstanding': outstanding,
                })
        accountant_debtor_total = len(accountant_debtor_rows)
        accountant_debtor_rows = sorted(accountant_debtor_rows, key=lambda row: row['outstanding'], reverse=True)[:10]
        if accountant_dashboard_cards:
            accountant_dashboard_cards[5]['value'] = accountant_debtor_total

    if role == 'teacher':
        staff = Staff.objects.filter(user=request.user, institution=institution).first()
        if staff:
            teacher_classes = AcademicClass.objects.filter(
                id__in=TeacherAssignment.objects.filter(teacher=staff).values_list('academic_class_id', flat=True),
                institution=institution,
            ).order_by('name')
            teacher_students = Student.objects.filter(academic_class__in=teacher_classes, institution=institution).select_related('academic_class')
            teacher_subject_map = {}
            subject_assignments = TeacherSubjectAssignment.objects.filter(
                teacher=staff,
                academic_class__in=teacher_classes,
            ).select_related('subject', 'academic_class')
            for assignment in subject_assignments:
                teacher_subject_map.setdefault(assignment.academic_class_id, []).append({
                    'id': assignment.subject_id,
                    'name': assignment.subject.name,
                })

            results = Result.objects.filter(student__in=teacher_students, subject__in=subjects, institution=institution).order_by('id')
            for res in results:
                key = f"{res.student_id}-{res.subject_id}-{res.academic_session_id or ''}-{res.academic_term_id or ''}"
                teacher_results_map[key] = {
                    'test1': float(res.test1),
                    'test2': float(res.test2),
                    'assignment': float(res.assignment),
                    'exam': float(res.exam),
                }

            teacher_submissions = ResultSubmission.objects.filter(submitted_by=staff).select_related('academic_class', 'subject').order_by('-submitted_at')
            teacher_recent_submissions = teacher_submissions[:6]
            teacher_pending_corrections = teacher_submissions.filter(status='returned_for_correction')[:5]
            assigned_subject_ids = subject_assignments.values_list('subject_id', flat=True)
            saved_scores = Result.objects.filter(
                institution=institution,
                teacher=staff,
                academic_class__in=teacher_classes,
                subject_id__in=assigned_subject_ids,
            )
            if current_session:
                saved_scores = saved_scores.filter(academic_session=current_session)
            if current_term:
                saved_scores = saved_scores.filter(academic_term=current_term)
            submitted_count = teacher_submissions.exclude(status='draft').count()
            teacher_dashboard_stats = [
                {'label': 'Assigned Classes', 'value': teacher_classes.count(), 'icon': 'school'},
                {'label': 'Assigned Subjects', 'value': subject_assignments.count(), 'icon': 'book-open'},
                {'label': 'My Students', 'value': teacher_students.count(), 'icon': 'users'},
                {'label': 'Scores Saved', 'value': saved_scores.count(), 'icon': 'clipboard-check'},
                {'label': 'Submitted Results', 'value': submitted_count, 'icon': 'send'},
                {'label': 'Corrections Needed', 'value': teacher_submissions.filter(status='returned_for_correction').count(), 'icon': 'alert-circle'},
            ]
            for cls in teacher_classes:
                class_subjects_for_teacher = list(subject_assignments.filter(academic_class=cls))
                subject_rows = []
                for assignment in class_subjects_for_teacher:
                    submission = teacher_submissions.filter(
                        academic_class=cls,
                        subject=assignment.subject,
                        academic_session=current_session,
                        academic_term=current_term,
                    ).first()
                    subject_rows.append({
                        'subject': assignment.subject,
                        'status': submission.get_status_display() if submission else 'Draft',
                        'status_code': submission.status if submission else 'draft',
                    })
                teacher_class_cards.append({
                    'class': cls,
                    'student_count': teacher_students.filter(academic_class=cls).count(),
                    'subjects': subject_rows,
                    'session': cls.academic_session or current_session,
                    'term': cls.academic_term or current_term,
                })
    elif role == 'student':
        student_record = Student.objects.filter(user=request.user, institution=institution).select_related('academic_class').first()
        if student_record:
            if student_record.academic_class:
                StudentClassHistory.objects.get_or_create(
                    student=student_record,
                    academic_class=student_record.academic_class,
                    academic_session=student_record.academic_class.academic_session,
                    academic_term=student_record.academic_class.academic_term,
                    defaults={'is_current': True},
                )
            student_subjects = Subject.objects.filter(
                subject_classes__academic_class=student_record.academic_class,
                institution=institution,
            ).distinct().order_by('name')
            student_results = Result.objects.filter(
                institution=institution,
                student=student_record,
            ).select_related('subject', 'academic_class', 'teacher', 'academic_session', 'academic_term').order_by('-session', 'subject__name')
            if student_record.academic_class:
                student_current_results = student_results.filter(
                    academic_class=student_record.academic_class,
                    academic_session=current_session,
                    academic_term=current_term,
                ).order_by('subject__name')
            published_submissions = ResultSubmission.objects.filter(
                institution=institution,
                academic_class=student_record.academic_class,
                academic_session=current_session,
                academic_term=current_term,
                status='published',
            ).select_related('academic_class', 'subject', 'submitted_by').order_by('-published_at', 'subject__name')
            published_filters = Q()
            for submission in published_submissions:
                published_filters |= Q(
                    subject=submission.subject,
                    academic_class=submission.academic_class,
                    academic_session=submission.academic_session,
                    academic_term=submission.academic_term,
                )
            if published_filters:
                student_report_results = Result.objects.filter(
                    published_filters,
                    institution=institution,
                    student=student_record,
                ).select_related('subject', 'academic_class', 'teacher', 'academic_session', 'academic_term').order_by('subject__name')
                student_report_total = sum((result.total for result in student_report_results), Decimal('0.00'))
                count = student_report_results.count()
                if count:
                    student_report_average = (student_report_total / Decimal(count)).quantize(Decimal('0.01'))
                    first_result = student_report_results.first()
                    student_report_first_result = first_result
                    student_report_submission = published_submissions.filter(
                        academic_session=first_result.academic_session,
                        academic_term=first_result.academic_term,
                    ).first()
                    class_results = Result.objects.filter(
                        institution=institution,
                        academic_class=first_result.academic_class,
                        academic_session=first_result.academic_session,
                        academic_term=first_result.academic_term,
                        subject__in=published_submissions.filter(
                            academic_session=first_result.academic_session,
                            academic_term=first_result.academic_term,
                        ).values('subject'),
                    ).values('student_id').annotate(total_score=Sum('total')).order_by('-total_score')
                    for index, item in enumerate(class_results, start=1):
                        if item['student_id'] == student_record.id:
                            student_report_position = _ordinal(index)
                            break
                    student_report_card = {
                        'student': student_record,
                        'results': student_report_results,
                        'total': student_report_total,
                        'average': student_report_average,
                        'position': student_report_position or '-',
                        'academic_class': first_result.academic_class,
                        'session': first_result.session,
                        'term': first_result.term,
                        'teacher_comment': student_report_submission.teacher_comment if student_report_submission else '',
                        'examiner_comment': student_report_submission.examiner_comment if student_report_submission else '',
                        'admin_comment': student_report_submission.admin_comment if student_report_submission else '',
                        'approval_status': student_report_submission.get_status_display() if student_report_submission else 'Published',
                        'is_preview': False,
                    }
            class_entries = {}
            if student_record.academic_class:
                class_entries[(student_record.academic_class_id, student_record.academic_class.academic_session_id, student_record.academic_class.academic_term_id)] = {
                    'class': student_record.academic_class,
                    'session': student_record.academic_class.academic_session,
                    'term': student_record.academic_class.academic_term,
                    'is_current': True,
                }
            for history in StudentClassHistory.objects.filter(student=student_record).select_related('academic_class', 'academic_session', 'academic_term'):
                key = (history.academic_class_id, history.academic_session_id, history.academic_term_id)
                class_entries[key] = {
                    'class': history.academic_class,
                    'session': history.academic_session,
                    'term': history.academic_term,
                    'is_current': history.is_current or (student_record.academic_class_id == history.academic_class_id),
                }
            published_class_results = Result.objects.filter(
                institution=institution,
                student=student_record,
                academic_class__isnull=False,
                academic_session__isnull=False,
                academic_term__isnull=False,
                academic_class__in=ResultSubmission.objects.filter(
                    institution=institution,
                    status='published',
                ).values('academic_class'),
            ).select_related('academic_class', 'academic_session', 'academic_term').order_by('academic_class__level', 'session', 'term')
            for result in published_class_results:
                if not ResultSubmission.objects.filter(
                    institution=institution,
                    status='published',
                    academic_class=result.academic_class,
                    subject=result.subject,
                    academic_session=result.academic_session,
                    academic_term=result.academic_term,
                ).exists():
                    continue
                key = (result.academic_class_id, result.academic_session_id, result.academic_term_id)
                class_entries.setdefault(key, {
                    'class': result.academic_class,
                    'session': result.academic_session,
                    'term': result.academic_term,
                    'is_current': student_record.academic_class_id == result.academic_class_id,
                })
            selected_key = request.GET.get('class_key', '').strip()
            for key, entry in class_entries.items():
                class_key = f"{key[0]}-{key[1] or 0}-{key[2] or 0}"
                entry['key'] = class_key
                student_class_rows.append(entry)
                if selected_key == class_key:
                    selected_student_class = entry
            student_class_rows.sort(key=lambda item: (item['class'].level, item['class'].name, item['session'].name if item['session'] else ''))
            if not selected_student_class and student_class_rows:
                selected_student_class = next((item for item in student_class_rows if item['is_current']), student_class_rows[-1])
            if selected_student_class:
                selected_class = selected_student_class['class']
                selected_session = selected_student_class['session']
                selected_term = selected_student_class['term']
                selected_class_subjects = Subject.objects.filter(
                    subject_classes__academic_class=selected_class,
                    institution=institution,
                ).distinct().order_by('name')
                selected_class_filters = Q(
                    institution=institution,
                    student=student_record,
                    academic_class=selected_class,
                )
                if selected_session:
                    selected_class_filters &= Q(academic_session=selected_session)
                if selected_term:
                    selected_class_filters &= Q(academic_term=selected_term)
                selected_class_results = Result.objects.filter(
                    selected_class_filters,
                    subject__in=ResultSubmission.objects.filter(
                        institution=institution,
                        status='published',
                        academic_class=selected_class,
                        academic_session=selected_session,
                        academic_term=selected_term,
                    ).values('subject'),
                ).select_related('subject', 'academic_class', 'academic_session', 'academic_term').order_by('subject__name')
                selected_class_report_total = sum((result.total for result in selected_class_results), Decimal('0.00'))
                selected_count = selected_class_results.count()
                if selected_count:
                    selected_class_report_average = (selected_class_report_total / Decimal(selected_count)).quantize(Decimal('0.01'))
                    selected_class_first_result = selected_class_results.first()
                    selected_class_report_submission = ResultSubmission.objects.filter(
                        institution=institution,
                        status='published',
                        academic_class=selected_class,
                        academic_session=selected_session,
                        academic_term=selected_term,
                    ).select_related('academic_class').first()
                    class_totals = Result.objects.filter(
                        institution=institution,
                        academic_class=selected_class,
                        academic_session=selected_session,
                        academic_term=selected_term,
                        subject__in=ResultSubmission.objects.filter(
                            institution=institution,
                            status='published',
                            academic_class=selected_class,
                            academic_session=selected_session,
                            academic_term=selected_term,
                        ).values('subject'),
                    ).values('student_id').annotate(total_score=Sum('total')).order_by('-total_score')
                    for index, item in enumerate(class_totals, start=1):
                        if item['student_id'] == student_record.id:
                            selected_class_report_position = _ordinal(index)
                            break
                    selected_class_report_card = {
                        'student': student_record,
                        'results': selected_class_results,
                        'total': selected_class_report_total,
                        'average': selected_class_report_average,
                        'position': selected_class_report_position or '-',
                        'academic_class': selected_class,
                        'session': selected_session.name if selected_session else '',
                        'term': selected_term.get_term_display() if selected_term else '',
                        'teacher_comment': selected_class_report_submission.teacher_comment if selected_class_report_submission else '',
                        'examiner_comment': selected_class_report_submission.examiner_comment if selected_class_report_submission else '',
                        'admin_comment': selected_class_report_submission.admin_comment if selected_class_report_submission else '',
                        'approval_status': selected_class_report_submission.get_status_display() if selected_class_report_submission else 'Published',
                        'is_preview': False,
                    }
            student_payments = Payment.objects.filter(
                institution=institution,
                student=student_record,
            ).select_related('fee').order_by('-paid_at')
            paid_by_fee = {}
            for payment in student_payments.filter(status='Paid'):
                if payment.fee_id:
                    paid_by_fee[payment.fee_id] = paid_by_fee.get(payment.fee_id, Decimal('0.00')) + payment.amount
            for fee in fees:
                if not _fee_student_queryset(fee).filter(id=student_record.id).exists():
                    continue
                paid_amount = paid_by_fee.get(fee.id, Decimal('0.00'))
                outstanding = fee.amount - paid_amount
                if outstanding < 0:
                    outstanding = Decimal('0.00')
                student_fee_total += fee.amount
                student_paid_total += paid_amount
                student_outstanding_total += outstanding
                student_fee_rows.append({
                    'fee': fee,
                    'paid': paid_amount,
                    'outstanding': outstanding,
                    'is_paid': outstanding <= 0,
                })
            student_dashboard_cards = [
                {
                    'label': 'Current Class',
                    'value': student_record.academic_class.name if student_record.academic_class else '-',
                    'hint': f"{current_session.name if current_session else 'No session'} / {current_term.get_term_display() if current_term else 'No term'}",
                    'icon': 'school',
                },
                {
                    'label': 'Outstanding Fees',
                    'value': f"NGN {student_outstanding_total}",
                    'hint': 'Balance from assigned fees',
                    'icon': 'wallet',
                },
                {
                    'label': 'Current Scores',
                    'value': student_current_results.count(),
                    'hint': 'Subjects with saved test records',
                    'icon': 'clipboard-list',
                },
                {
                    'label': 'Report Card',
                    'value': 'Published' if student_report_results.exists() else 'Not Published',
                    'hint': 'Visible after admin approval',
                    'icon': 'file-check',
                },
            ]
    elif role == 'examiner':
        examiner_submissions = ResultSubmission.objects.filter(
            institution=institution,
        ).exclude(status='draft').select_related('academic_class', 'subject', 'submitted_by').order_by('-submitted_at')
        examiner_recent_submissions = examiner_submissions[:8]
        examiner_dashboard_cards = [
            {'label': 'Submitted Results', 'value': examiner_submissions.filter(status='submitted_to_examiner').count(), 'hint': 'Waiting for examiner review', 'icon': 'inbox'},
            {'label': 'Returned Corrections', 'value': examiner_submissions.filter(status='returned_for_correction').count(), 'hint': 'Sent back to teachers', 'icon': 'rotate-ccw'},
            {'label': 'Approved by Examiner', 'value': examiner_submissions.filter(status='approved_by_examiner').count(), 'hint': 'Waiting for admin approval', 'icon': 'check-circle'},
            {'label': 'Published Results', 'value': examiner_submissions.filter(status='published').count(), 'hint': 'Visible to students', 'icon': 'file-check'},
            {'label': 'Classes', 'value': AcademicClass.objects.filter(institution=institution).count(), 'hint': 'Available for result sheets', 'icon': 'school'},
            {'label': 'Students', 'value': students_all.count(), 'hint': 'Ranking population', 'icon': 'users'},
        ]
        submission_id = request.GET.get('submission')
        if submission_id:
            selected_submission = examiner_submissions.filter(id=submission_id).first()
            if selected_submission:
                examiner_results = _results_for_submission(selected_submission)
                examiner_report_previews = _report_card_previews_for_submission(selected_submission)
        result_sheet_class_id = request.GET.get('class')
        result_sheet_session = request.GET.get('session', '').strip()
        result_sheet_term = request.GET.get('term', '').strip()
        current_session_name = current_session.name if current_session else ''
        current_term_name = current_term.get_term_display() if current_term else ''
        if not result_sheet_session:
            result_sheet_session = current_session_name
        if not result_sheet_term:
            result_sheet_term = current_term_name
        if result_sheet_class_id:
            result_sheet_class = AcademicClass.objects.filter(
                id=result_sheet_class_id,
                institution=institution,
            ).first()
            if result_sheet_class:
                students = Student.objects.filter(
                    academic_class=result_sheet_class,
                    institution=institution,
                ).order_by('full_name')
                totals = Result.objects.filter(
                    institution=institution,
                    student__in=students,
                    session=result_sheet_session,
                    term=result_sheet_term,
                ).values('student_id').annotate(total_score=Sum('total'))
                totals_map = {
                    item['student_id']: item['total_score'] or 0
                    for item in totals
                }
                result_sheet_rows = []
                for student in students:
                    result_sheet_rows.append({
                        'student': student,
                        'total': totals_map.get(student.id, 0),
                    })
                result_sheet_rows.sort(key=lambda row: row['student'].full_name)
                result_sheet_rows.sort(key=lambda row: row['total'], reverse=True)
                last_score = None
                last_rank = 0
                for index, row in enumerate(result_sheet_rows, start=1):
                    score = row['total']
                    if last_score is None or score != last_score:
                        last_rank = index
                        last_score = score
                    row['position'] = last_rank
                    row['position_display'] = _ordinal(last_rank)

    nav_items = _get_secondary_nav(role)
    nav_ids = {item['id'] for item in nav_items}
    if page not in nav_ids:
        page = 'dashboard'

    existing_sections = {
        'dashboard',
        'users',
        'teachers',
        'classes',
        'subjects',
        'assign-teachers',
        'assign-class',
        'register',
        'sessions',
        'student-ids',
        'approve-results',
        'fees',
        'payments',
        'receipts',
        'reports',
        'salary-vouchers',
        'my-classes',
        'my-students',
        'enter-scores',
        'submit-results',
        'review-results',
        'result-sheets',
        'subjects-student',
        'test-scores',
        'results',
        'pay-fees',
        'profile',
    }
    nav_placeholders = [item for item in nav_items if item['id'] not in existing_sections]

    return render(request, 'edu/secondary_page.html', {
        'role': role,
        'role_label': role_label,
        'nav_items': nav_items,
        'active_page': page,
        'nav_placeholders': nav_placeholders,
        'user_name': request.user.get_username(),
        'subscription_usage': _subscription_usage(institution),
        'stats': stats,
        'students': students,
        'students_all': students_all,
        'teachers': teachers,
        'staff_members': staff_members,
        'sessions': sessions,
        'terms': terms,
        'subjects': subjects,
        'class_subjects': class_subjects,
        'class_subject_map': class_subject_map,
        'term_map': term_map,
        'fees_total': fees_total,
        'fees_pending': fees_pending,
        'fees_expected': fee_summary['expected_total'],
        'accountant_dashboard_cards': accountant_dashboard_cards,
        'accountant_fee_cards': accountant_fee_cards,
        'accountant_class_rows': accountant_class_rows,
        'accountant_debtor_rows': accountant_debtor_rows,
        'accountant_today_total': accountant_today_total,
        'accountant_pending_payments': accountant_pending_payments,
        'fees': fees,
        'payments': payments,
        'salary_vouchers': salary_vouchers,
        'pending_salary_vouchers': pending_salary_vouchers,
        'approved_due_salary_vouchers': approved_due_salary_vouchers,
        'payment_public_key': institution.payment_public_key,
        'online_payment_enabled': institution.allow_online_payment and bool(institution.payment_public_key) and bool(institution.payment_secret_key),
        'pending_profiles': pending_profiles,
        'admin_dashboard_cards': admin_dashboard_cards,
        'admin_recent_results': admin_recent_results,
        'admin_pending_count': admin_pending_count,
        'registry_dashboard_cards': registry_dashboard_cards,
        'registry_recent_students': registry_recent_students,
        'registry_class_rows': registry_class_rows,
        'role_options': SECONDARY_ROLES,
        'classes': AcademicClass.objects.filter(institution=institution).select_related('academic_session', 'academic_term'),
        'institution_id': institution.id if institution else '',
        'teacher_classes': teacher_classes,
        'teacher_students': teacher_students,
        'teacher_subject_map': teacher_subject_map,
        'teacher_results_map': teacher_results_map,
        'teacher_submissions': teacher_submissions,
        'teacher_dashboard_stats': teacher_dashboard_stats,
        'teacher_class_cards': teacher_class_cards,
        'teacher_recent_submissions': teacher_recent_submissions,
        'teacher_pending_corrections': teacher_pending_corrections,
        'teacher_subject_assignments': teacher_subject_assignments,
        'admin_result_submissions': admin_result_submissions,
        'selected_admin_submission': selected_admin_submission,
        'admin_review_results': admin_review_results,
        'admin_report_previews': admin_report_previews,
        'examiner_submissions': examiner_submissions,
        'examiner_results': examiner_results,
        'selected_submission': selected_submission,
        'examiner_report_previews': examiner_report_previews,
        'examiner_dashboard_cards': examiner_dashboard_cards,
        'examiner_recent_submissions': examiner_recent_submissions,
        'result_sheet_rows': result_sheet_rows,
        'result_sheet_class': result_sheet_class,
        'result_sheet_session': result_sheet_session,
        'result_sheet_term': result_sheet_term,
        'id_card_students': id_card_students,
        'student_record': student_record,
        'student_subjects': student_subjects,
        'student_results': student_results,
        'student_current_results': student_current_results,
        'student_report_results': student_report_results,
        'student_report_total': student_report_total,
        'student_report_average': student_report_average,
        'student_report_position': student_report_position,
        'student_report_submission': student_report_submission,
        'student_report_first_result': student_report_first_result,
        'student_report_card': student_report_card,
        'student_class_rows': student_class_rows,
        'selected_student_class': selected_student_class,
        'selected_class_subjects': selected_class_subjects,
        'selected_class_results': selected_class_results,
        'selected_class_report_total': selected_class_report_total,
        'selected_class_report_average': selected_class_report_average,
        'selected_class_report_position': selected_class_report_position,
        'selected_class_report_submission': selected_class_report_submission,
        'selected_class_first_result': selected_class_first_result,
        'selected_class_report_card': selected_class_report_card,
        'student_payments': student_payments,
        'student_fee_rows': student_fee_rows,
        'student_fee_total': student_fee_total,
        'student_paid_total': student_paid_total,
        'student_outstanding_total': student_outstanding_total,
        'student_dashboard_cards': student_dashboard_cards,
        'selected_id_card_class_id': selected_id_card_class_id,
        'selected_id_card_session_id': selected_id_card_session_id,
        'current_session_name': current_session.name if current_session else '',
        'current_term_name': current_term.get_term_display() if current_term else '',
        'current_session_id': current_session.id if current_session else '',
        'current_term_id': current_term.id if current_term else '',
        'today': today,
    })


@login_required
def tertiary_dashboard(request, role):
    return tertiary_page(request, role, 'dashboard')


@login_required
def tertiary_page(request, role, page):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'tertiary':
        messages.error(request, 'Access denied for this dashboard.')
        return redirect('edu:index')

    role = profile.role

    institution = profile.institution
    if _subscription_is_expired(institution):
        return _expired_subscription_response(request, profile)

    stats = [
        {"label": "Faculties", "value": "7"},
        {"label": "Departments", "value": "31"},
        {"label": "Lecturers", "value": str(Staff.objects.filter(institution=institution).count())},
        {"label": "Enrollment", "value": str(Student.objects.filter(institution=institution).count())},
    ]
    fees_total = Payment.objects.filter(institution=institution, status='Paid').aggregate(total=Sum('amount'))['total'] or 0
    fees_pending = Payment.objects.filter(institution=institution, status='Pending').aggregate(total=Sum('amount'))['total'] or 0

    fees = Fee.objects.filter(institution=institution).prefetch_related('classes', 'departments').order_by('-id')

    recent_results = Result.objects.filter(institution=institution).select_related('student', 'subject')[:5]

    role_label = next((r['label'] for r in TERTIARY_ROLES if r['slug'] == role), role.upper())

    pending_profiles = []
    if profile.role in ['vc', 'provost']:
        pending_profiles = Profile.objects.filter(
            institution=institution,
            is_approved=False,
        ).select_related('user')

    nav_items = _get_tertiary_nav(role)
    nav_ids = {item['id'] for item in nav_items}
    if page not in nav_ids:
        page = 'dashboard'

    existing_sections = {'dashboard', 'users', 'approve-results', 'results', 'fees'}
    nav_placeholders = [item for item in nav_items if item['id'] not in existing_sections]

    return render(request, 'edu/tertiary_page.html', {
        'role': role,
        'role_label': role_label,
        'nav_items': nav_items,
        'active_page': page,
        'nav_placeholders': nav_placeholders,
        'user_name': request.user.get_username(),
        'subscription_usage': _subscription_usage(institution),
        'stats': stats,
        'recent_results': recent_results,
        'pending_profiles': pending_profiles,
        'fees': fees,
        'fees_total': fees_total,
        'fees_pending': fees_pending,
        'role_options': TERTIARY_ROLES,
        'institution_id': institution.id if institution else '',
        'faculties': Faculty.objects.filter(institution=institution),
        'departments': Department.objects.filter(faculty__institution=institution),
    })

