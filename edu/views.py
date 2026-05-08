from decimal import Decimal

import requests
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render

from .models import Institution, Student, Staff, Fee, Payment, Result, Profile, AcademicClass, Faculty, Department, TeacherAssignment, AcademicSession, AcademicTerm, Subject, ClassSubject, ResultSubmission, TeacherSubjectAssignment

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
    return render(request, 'edu/index.html')


def _login_for_institution(request, institution_type, template_name):
    roles = SECONDARY_ROLES if institution_type == 'secondary' else TERTIARY_ROLES

    if request.method == 'POST':
        school_code = request.POST.get('school_code', '').strip().upper()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is None:
            existing = get_user_model().objects.filter(username=username).first()
            if existing and not existing.is_active:
                messages.error(request, 'Account pending approval.')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            auth_login(request, user)
            profile = getattr(user, 'profile', None)
            if profile and profile.institution_type != institution_type:
                auth_logout(request)
                messages.error(request, 'This account belongs to a different portal.')
            elif profile:
                if not school_code or not profile.institution or profile.institution.school_code.upper() != school_code:
                    auth_logout(request)
                    messages.error(request, 'Invalid school code.')
                    return None
                if not profile.is_approved:
                    auth_logout(request)
                    messages.error(request, 'Account pending approval.')
                    return None
                if profile.institution_type == 'tertiary':
                    return redirect('edu:tertiary_dashboard', role=profile.role)
                return redirect('edu:secondary_dashboard', role=profile.role)
            else:
                messages.error(request, 'No profile found for this user.')

    return render(request, template_name, {
        'institution': institution_type,
        'roles': roles,
    })


def secondary_login(request):
    return _login_for_institution(request, 'secondary', 'edu/secondary_login.html')


def tertiary_login(request):
    return _login_for_institution(request, 'tertiary', 'edu/tertiary_login.html')


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

    required_uploads = {
        'cac_certificate': 'CAC Certificate',
        'cac_status_report': 'CAC Status Report',
        'tin_certificate': 'TIN or Tax Certificate',
        'school_letterhead': 'Official School Letterhead',
        'school_stamp': 'School Stamp/Seal',
        'owner_valid_id': 'Owner/Admin Valid ID',
    }
    for field_name, label in required_uploads.items():
        if not uploads[field_name]:
            missing.append(label)

    if not uploads['ministry_approval'] and not uploads['operating_license']:
        missing.append('Ministry of Education approval or school operating license')

    if not uploads['utility_bill'] and not uploads['proof_of_address']:
        missing.append('Utility bill or proof of address')

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


def _get_secondary_accountant_profile(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.institution_type != 'secondary' or profile.role != 'accountant':
        return None
    return profile


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
        'admin': ['dashboard', 'users', 'teachers', 'classes', 'subjects', 'assign-teachers', 'approve-results', 'settings'],
        'registry': ['dashboard', 'register', 'teachers', 'assign-class', 'sessions', 'student-ids'],
        'accountant': ['dashboard', 'fees', 'payments', 'receipts', 'reports'],
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
        'my-classes': 'My Classes',
        'my-students': 'My Students',
        'enter-scores': 'Enter Scores',
        'submit-results': 'Submit Results',
        'review-results': 'Review Results',
        'result-sheets': 'Result Sheets',
        'subjects-student': 'My Subjects',
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


def secondary_school_register(request):
    if request.method == 'POST':
        institution_name = request.POST.get('institution_name', '').strip()
        school_code = request.POST.get('school_code', '').strip().upper()
        admin_full_name = request.POST.get('admin_full_name', '').strip()
        admin_password = request.POST.get('admin_password', '').strip()
        missing_verification, verification_uploads = _missing_verification_requirements(request)

        if not all([institution_name, admin_full_name, admin_password]):
            messages.error(request, 'Please fill all required fields.')
        elif missing_verification:
            messages.error(request, 'Please complete verification requirements: ' + ', '.join(missing_verification) + '.')
        else:
            try:
                institution = Institution.objects.create(
                    name=institution_name,
                    school_code=school_code or None,
                    short_name=request.POST.get('short_name', '').strip(),
                    institution_type='secondary',
                    ownership_type=request.POST.get('ownership_type', 'private'),
                    year_established=request.POST.get('year_established') or None,
                    license_number=request.POST.get('license_number', '').strip(),
                    cac_number=request.POST.get('cac_number', '').strip(),
                    country=request.POST.get('country', 'Nigeria').strip() or 'Nigeria',
                    state=request.POST.get('state', '').strip(),
                    city=request.POST.get('city', '').strip(),
                    address=request.POST.get('address', '').strip(),
                    postal_code=request.POST.get('postal_code', '').strip(),
                    phone_number=request.POST.get('phone_number', '').strip(),
                    email=request.POST.get('email', '').strip(),
                    website=request.POST.get('website', '').strip(),
                    grading_system=request.POST.get('grading_system', 'percentage'),
                    max_grade=request.POST.get('max_grade') or 100,
                    currency=request.POST.get('currency', 'NGN').strip() or 'NGN',
                    payment_provider=request.POST.get('payment_provider', '').strip(),
                    payment_public_key=request.POST.get('payment_public_key', '').strip(),
                    payment_secret_key=request.POST.get('payment_secret_key', '').strip(),
                    allow_online_payment=bool(request.POST.get('allow_online_payment')),
                    admin_email=request.POST.get('admin_email', '').strip(),
                    admin_phone=request.POST.get('admin_phone', '').strip(),
                    theme_color=request.POST.get('theme_color', '').strip(),
                    logo=request.FILES.get('logo'),
                    favicon=request.FILES.get('favicon'),
                    verification_status='pending',
                    **verification_uploads,
                )

                User = get_user_model()
                admin_username = _generate_user_id(institution)
                user = User.objects.create_user(username=admin_username, password=admin_password)
                user.is_active = True
                user.save()

                profile = user.profile
                profile.institution = institution
                profile.institution_type = 'secondary'
                profile.role = 'admin'
                profile.created_via = 'school-register'
                profile.is_approved = False
                profile.approved_by = None
                profile.approved_at = None
                profile.save()

                Staff.objects.create(
                    institution=institution,
                    user=user,
                    full_name=admin_full_name,
                    staff_id=_generate_staff_id('SECSTF', institution),
                    role='admin',
                    department='',
                )

                messages.success(request, f'School verification submitted. VilaStore will review your documents before portal access is granted. School code: {institution.school_code}. Admin ID: {admin_username}')
                return redirect('edu:secondary_login')
            except IntegrityError:
                messages.error(request, 'School code or username already exists.')

    return render(request, 'edu/secondary_register.html', {
        'ownership_choices': Institution.OWNERSHIP_CHOICES,
        'grading_choices': Institution.GRADING_CHOICES,
    })


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
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'student')
        class_id = request.POST.get('academic_class')

        if not all([password, full_name]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('edu:secondary_dashboard', role=creator_profile.role)

        if role not in [r['slug'] for r in SECONDARY_ROLES]:
            role = 'student'

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, password=password)
            user.is_active = True
            user.save()

            profile = user.profile
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = role
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()

            if role == 'student':
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

            messages.success(request, f'Account created successfully. ID: {username}')
        except IntegrityError:
            messages.error(request, 'Username already exists.')

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
        session = request.POST.get('session', '').strip()
        term = request.POST.get('term', '').strip()
        if not session:
            current_session = AcademicSession.objects.filter(institution=profile.institution, is_current=True).first()
            session = current_session.name if current_session else ''
        if not term:
            current_term = AcademicTerm.objects.filter(session__institution=profile.institution, is_current=True).first()
            term = current_term.term if current_term else ''

        academic_class = AcademicClass.objects.filter(id=class_id, institution=profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=profile.institution).first()
        if not academic_class or not subject:
            messages.error(request, 'Please select class and subject.')
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

        for student in students:
            def _to_decimal(value):
                try:
                    return float(value or 0)
                except ValueError:
                    return 0

            test1 = _to_decimal(request.POST.get(f'test1_{student.id}'))
            test2 = _to_decimal(request.POST.get(f'test2_{student.id}'))
            assignment = _to_decimal(request.POST.get(f'assignment_{student.id}'))
            exam = _to_decimal(request.POST.get(f'exam_{student.id}'))

            Result.objects.update_or_create(
                institution=profile.institution,
                student=student,
                subject=subject,
                session=session,
                term=term,
                defaults={
                    'test1': test1,
                    'test2': test2,
                    'assignment': assignment,
                    'exam': exam,
                },
            )

        messages.success(request, 'Scores saved.')
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
        session = request.POST.get('session', '').strip()
        term = request.POST.get('term', '').strip()
        if not session:
            current_session = AcademicSession.objects.filter(institution=profile.institution, is_current=True).first()
            session = current_session.name if current_session else ''
        if not term:
            current_term = AcademicTerm.objects.filter(session__institution=profile.institution, is_current=True).first()
            term = current_term.term if current_term else ''

        academic_class = AcademicClass.objects.filter(id=class_id, institution=profile.institution).first()
        subject = Subject.objects.filter(id=subject_id, institution=profile.institution).first()
        if not academic_class or not subject:
            messages.error(request, 'Please select class and subject.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')

        assigned = TeacherAssignment.objects.filter(teacher=staff, academic_class=academic_class).exists()
        if not assigned:
            messages.error(request, 'You are not assigned to that class.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')
        if not TeacherSubjectAssignment.objects.filter(teacher=staff, academic_class=academic_class, subject=subject).exists():
            messages.error(request, 'You are not assigned to that subject.')
            return redirect('edu:secondary_page', role=profile.role, page='submit-results')

        ResultSubmission.objects.create(
            institution=profile.institution,
            academic_class=academic_class,
            subject=subject,
            submitted_by=staff,
            session=session,
            term=term,
            status='submitted',
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
        submission = ResultSubmission.objects.filter(id=submission_id, institution=profile.institution).first()
        if not submission:
            messages.error(request, 'Submission not found.')
            return redirect('edu:secondary_page', role=profile.role, page='review-results')
        submission.status = 'reviewed'
        submission.save(update_fields=['status'])
        messages.success(request, 'Results marked as reviewed.')
        return redirect(f"/edu/secondary/{profile.role}/review-results/?submission={submission.id}")

    return redirect('edu:secondary_page', role=profile.role, page='review-results')


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
def secondary_add_student(request):
    creator_profile = getattr(request.user, 'profile', None)
    if not creator_profile or creator_profile.institution_type != 'secondary' or creator_profile.role not in ['admin', 'registry']:
        messages.error(request, 'Only Admin/Registry can add students.')
        return redirect('edu:secondary_dashboard', role=creator_profile.role if creator_profile else 'admin')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        password = request.POST.get('password', '').strip()
        class_id = request.POST.get('academic_class')
        teacher_id = request.POST.get('teacher')
        kin_name = request.POST.get('next_of_kin_name', '').strip()
        kin_phone = request.POST.get('next_of_kin_phone', '').strip()
        kin_relationship = request.POST.get('next_of_kin_relationship', '').strip()
        photo = request.FILES.get('photo')
        if not full_name or not password:
            messages.error(request, 'Full name and password are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='register')

        academic_class = AcademicClass.objects.filter(id=class_id, institution=creator_profile.institution).first()
        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, password=password)
            user.is_active = True
            user.save()

            profile = user.profile
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = 'student'
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()

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

            messages.success(request, f'Student registered. ID: {username}')
        except IntegrityError:
            messages.error(request, 'Could not create student.')

    return redirect('edu:secondary_page', role=creator_profile.role, page='register')


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
        photo = request.FILES.get('photo')
        if not full_name or not password:
            messages.error(request, 'Full name and password are required.')
            return redirect('edu:secondary_page', role=creator_profile.role, page='users')

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, password=password)
            user.is_active = True
            user.save()

            profile = user.profile
            profile.institution = creator_profile.institution
            profile.institution_type = 'secondary'
            profile.role = 'teacher'
            profile.created_by = request.user
            profile.created_via = creator_profile.role
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()

            Staff.objects.create(
                institution=creator_profile.institution,
                user=user,
                full_name=full_name,
                staff_id=username,
                role='teacher',
                department='',
                photo=photo,
            )

            messages.success(request, f'Teacher created. ID: {username}')
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
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'student')
        faculty_id = request.POST.get('faculty')
        department_id = request.POST.get('department')

        if not all([password, full_name]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('edu:tertiary_dashboard', role=creator_profile.role)

        if role not in [r['slug'] for r in TERTIARY_ROLES]:
            role = 'student'

        try:
            User = get_user_model()
            username = _generate_user_id(creator_profile.institution)
            user = User.objects.create_user(username=username, password=password)
            user.is_active = True
            user.save()

            profile = user.profile
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

            if role == 'student':
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

            messages.success(request, f'Account created successfully. ID: {username}')
        except IntegrityError:
            messages.error(request, 'Username already exists.')

    return redirect('edu:tertiary_dashboard', role=creator_profile.role)


def tertiary_school_register(request):
    if request.method == 'POST':
        institution_name = request.POST.get('institution_name', '').strip()
        school_code = request.POST.get('school_code', '').strip().upper()
        vc_full_name = request.POST.get('vc_full_name', '').strip()
        vc_password = request.POST.get('vc_password', '').strip()
        vc_role = request.POST.get('vc_role', 'vc')
        missing_verification, verification_uploads = _missing_verification_requirements(request)

        if not all([institution_name, vc_full_name, vc_password]):
            messages.error(request, 'Please fill all required fields.')
        elif missing_verification:
            messages.error(request, 'Please complete verification requirements: ' + ', '.join(missing_verification) + '.')
        else:
            try:
                institution = Institution.objects.create(
                    name=institution_name,
                    school_code=school_code or None,
                    short_name=request.POST.get('short_name', '').strip(),
                    institution_type='tertiary',
                    ownership_type=request.POST.get('ownership_type', 'private'),
                    year_established=request.POST.get('year_established') or None,
                    license_number=request.POST.get('license_number', '').strip(),
                    cac_number=request.POST.get('cac_number', '').strip(),
                    country=request.POST.get('country', 'Nigeria').strip() or 'Nigeria',
                    state=request.POST.get('state', '').strip(),
                    city=request.POST.get('city', '').strip(),
                    address=request.POST.get('address', '').strip(),
                    postal_code=request.POST.get('postal_code', '').strip(),
                    phone_number=request.POST.get('phone_number', '').strip(),
                    email=request.POST.get('email', '').strip(),
                    website=request.POST.get('website', '').strip(),
                    has_faculties=True,
                    has_departments=True,
                    grading_system=request.POST.get('grading_system', 'percentage'),
                    max_grade=request.POST.get('max_grade') or 100,
                    currency=request.POST.get('currency', 'NGN').strip() or 'NGN',
                    payment_provider=request.POST.get('payment_provider', '').strip(),
                    payment_public_key=request.POST.get('payment_public_key', '').strip(),
                    payment_secret_key=request.POST.get('payment_secret_key', '').strip(),
                    allow_online_payment=bool(request.POST.get('allow_online_payment')),
                    admin_email=request.POST.get('admin_email', '').strip(),
                    admin_phone=request.POST.get('admin_phone', '').strip(),
                    theme_color=request.POST.get('theme_color', '').strip(),
                    logo=request.FILES.get('logo'),
                    favicon=request.FILES.get('favicon'),
                    verification_status='pending',
                    **verification_uploads,
                )

                User = get_user_model()
                vc_username = _generate_user_id(institution)
                user = User.objects.create_user(username=vc_username, password=vc_password)
                user.is_active = True
                user.save()

                profile = user.profile
                profile.institution = institution
                profile.institution_type = 'tertiary'
                profile.role = vc_role if vc_role in ['vc', 'provost'] else 'vc'
                profile.created_via = 'school-register'
                profile.is_approved = False
                profile.approved_by = None
                profile.approved_at = None
                profile.save()

                Staff.objects.create(
                    institution=institution,
                    user=user,
                    full_name=vc_full_name,
                    staff_id=_generate_staff_id('TERSTF', institution),
                    role=profile.role,
                    department='',
                )

                messages.success(request, f'Institution verification submitted. VilaStore will review your documents before portal access is granted. School code: {institution.school_code}. ID: {vc_username}')
                return redirect('edu:tertiary_login')
            except IntegrityError:
                messages.error(request, 'School code or username already exists.')

    return render(request, 'edu/tertiary_register.html', {
        'ownership_choices': Institution.OWNERSHIP_CHOICES,
        'grading_choices': Institution.GRADING_CHOICES,
    })


def logout(request):
    auth_logout(request)
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
    students = Student.objects.filter(institution=institution).select_related('academic_class')[:5]
    fee_summary = _school_fee_summary(institution)
    fees_total = fee_summary['paid_total']
    fees_pending = fee_summary['outstanding_total']
    fees = Fee.objects.filter(institution=institution).prefetch_related('classes', 'departments').order_by('-id')
    payments = Payment.objects.filter(institution=institution).select_related('student', 'fee').order_by('-paid_at')[:20]

    stats = [
        {"label": "Total Students", "value": str(Student.objects.filter(institution=institution).count())},
        {"label": "Total Staff", "value": str(Staff.objects.filter(institution=institution).count())},
        {"label": "Classes", "value": str(institution.classes.count() if institution else 0)},
        {"label": "Pass Rate", "value": "92%"},
    ]

    role_label = next((r['label'] for r in SECONDARY_ROLES if r['slug'] == role), role.title())

    pending_profiles = []
    if profile.role == 'admin':
        pending_profiles = Profile.objects.filter(
            institution=institution,
            is_approved=False,
        ).select_related('user')

    students_all = Student.objects.filter(institution=institution).select_related('academic_class')
    teachers = Staff.objects.filter(institution=institution, role='teacher').prefetch_related('assignments__academic_class', 'subject_assignments__academic_class', 'subject_assignments__subject')
    sessions = AcademicSession.objects.filter(institution=institution).order_by('-name')
    terms = AcademicTerm.objects.filter(session__institution=institution).select_related('session')
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
    teacher_subject_assignments = TeacherSubjectAssignment.objects.filter(institution=institution).select_related('teacher', 'academic_class', 'subject')
    examiner_submissions = ResultSubmission.objects.none()
    examiner_results = Result.objects.none()
    selected_submission = None
    result_sheet_rows = []
    result_sheet_class = None
    result_sheet_session = ''
    result_sheet_term = ''

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
                key = f"{res.student_id}-{res.subject_id}"
                teacher_results_map[key] = {
                    'test1': float(res.test1),
                    'test2': float(res.test2),
                    'assignment': float(res.assignment),
                    'exam': float(res.exam),
                }

            teacher_submissions = ResultSubmission.objects.filter(submitted_by=staff).select_related('academic_class', 'subject').order_by('-submitted_at')
    elif role == 'examiner':
        examiner_submissions = ResultSubmission.objects.filter(
            institution=institution,
        ).select_related('academic_class', 'subject', 'submitted_by').order_by('-submitted_at')
        submission_id = request.GET.get('submission')
        if submission_id:
            selected_submission = examiner_submissions.filter(id=submission_id).first()
            if selected_submission:
                examiner_results = Result.objects.filter(
                    institution=institution,
                    subject=selected_submission.subject,
                    student__academic_class=selected_submission.academic_class,
                    session=selected_submission.session,
                    term=selected_submission.term,
                ).select_related('student').order_by('student__full_name')
        result_sheet_class_id = request.GET.get('class')
        result_sheet_session = request.GET.get('session', '').strip()
        result_sheet_term = request.GET.get('term', '').strip()
        current_session_name = current_session.name if current_session else ''
        current_term_name = current_term.term if current_term else ''
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
        'register',
        'sessions',
        'approve-results',
        'fees',
        'my-classes',
        'my-students',
        'enter-scores',
        'submit-results',
        'review-results',
        'result-sheets',
    }
    nav_placeholders = [item for item in nav_items if item['id'] not in existing_sections]

    return render(request, 'edu/secondary_page.html', {
        'role': role,
        'role_label': role_label,
        'nav_items': nav_items,
        'active_page': page,
        'nav_placeholders': nav_placeholders,
        'user_name': request.user.get_username(),
        'stats': stats,
        'students': students,
        'students_all': students_all,
        'teachers': teachers,
        'sessions': sessions,
        'terms': terms,
        'subjects': subjects,
        'class_subjects': class_subjects,
        'class_subject_map': class_subject_map,
        'fees_total': fees_total,
        'fees_pending': fees_pending,
        'fees_expected': fee_summary['expected_total'],
        'fees': fees,
        'payments': payments,
        'payment_public_key': institution.payment_public_key,
        'online_payment_enabled': institution.allow_online_payment and bool(institution.payment_public_key),
        'pending_profiles': pending_profiles,
        'role_options': SECONDARY_ROLES,
        'classes': AcademicClass.objects.filter(institution=institution),
        'institution_id': institution.id if institution else '',
        'teacher_classes': teacher_classes,
        'teacher_students': teacher_students,
        'teacher_subject_map': teacher_subject_map,
        'teacher_results_map': teacher_results_map,
        'teacher_submissions': teacher_submissions,
        'teacher_subject_assignments': teacher_subject_assignments,
        'examiner_submissions': examiner_submissions,
        'examiner_results': examiner_results,
        'selected_submission': selected_submission,
        'result_sheet_rows': result_sheet_rows,
        'result_sheet_class': result_sheet_class,
        'result_sheet_session': result_sheet_session,
        'result_sheet_term': result_sheet_term,
        'current_session_name': current_session.name if current_session else '',
        'current_term_name': current_term.term if current_term else '',
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

