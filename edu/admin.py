from django.contrib import admin
from django.utils import timezone
from .models import (
    EduSubscriptionSettings,
    Institution,
    InstitutionDocumentVerification,
    Faculty,
    Department,
    AcademicSession,
    AcademicTerm,
    AcademicClass,
    Subject,
    Profile,
    Student,
    Staff,
    Fee,
    Payment,
    SalaryVoucher,
    Result,
    ResultAuditLog,
    EduMembership,
    StudentGuardian,
    TeacherAssignment,
    ClassSubject,
)
from .verification import verify_document_with_api


class InstitutionDocumentVerificationInline(admin.TabularInline):
    model = InstitutionDocumentVerification
    extra = 0
    readonly_fields = ('document_type', 'status', 'provider', 'reference_value', 'api_checked_at', 'reviewed_by', 'reviewed_at')
    fields = ('document_type', 'status', 'provider', 'reference_value', 'api_checked_at', 'reviewed_by', 'reviewed_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution_type', 'city', 'country', 'subscription_status', 'subscription_package', 'student_limit', 'trial_student_limit', 'subscription_active_until', 'verification_status', 'verified_at')
    list_filter = ('institution_type', 'verification_status', 'registration_payment_status', 'subscription_status', 'subscription_package', 'subscription_billing_cycle')
    search_fields = ('name', 'school_code', 'email', 'admin_email')
    readonly_fields = ('created_at', 'verified_at')
    inlines = (InstitutionDocumentVerificationInline,)
    fieldsets = (
        (None, {
            'fields': (
                'name', 'school_code', 'short_name', 'institution_type', 'ownership_type',
                'year_established', 'license_number', 'cac_number', 'tin_number', 'owner_id_number',
            )
        }),
        ('Contact and Location', {
            'fields': (
                'country', 'state', 'city', 'address', 'postal_code',
                'phone_number', 'email', 'website', 'admin_email', 'admin_phone',
            )
        }),
        ('Academic and Payment Setup', {
            'fields': (
                'has_faculties', 'has_departments', 'grading_system', 'max_grade',
                'currency', 'payment_provider', 'payment_public_key', 'payment_secret_key',
                'allow_online_payment',
            )
        }),
        ('Registration Payment', {
            'fields': (
                'subscription_package', 'subscription_status', 'subscription_billing_cycle', 'student_limit',
                'trial_start_date', 'trial_end_date', 'trial_student_limit', 'has_used_free_trial',
                'subscription_start_date', 'subscription_expiry_date',
                'registration_payment_status', 'registration_payment_amount',
                'registration_payment_reference', 'registration_payment_paid_at',
                'subscription_active_until', 'subscription_last_payment_reference', 'subscription_last_paid_at',
            )
        }),
        ('Branding', {
            'fields': ('logo', 'favicon', 'theme_color')
        }),
        ('Verification Review', {
            'fields': ('verification_status', 'verification_review_note', 'verified_at')
        }),
        ('Submitted Verification Documents', {
            'fields': (
                'cac_certificate', 'cac_status_report',
                'ministry_approval', 'operating_license',
                'tin_certificate', 'school_letterhead', 'school_stamp',
                'owner_valid_id', 'utility_bill', 'proof_of_address',
            )
        }),
    )

    def save_model(self, request, obj, form, change):
        if 'verification_status' in form.changed_data:
            if obj.verification_status == 'approved' and not obj.verified_at:
                obj.verified_at = timezone.now()
            elif obj.verification_status != 'approved':
                obj.verified_at = None

        super().save_model(request, obj, form, change)

        if obj.verification_status == 'approved' and obj.registration_payment_status == 'paid':
            Profile.objects.filter(
                institution=obj,
                created_via='school-register',
                is_approved=False,
            ).update(is_approved=True, approved_by=request.user, approved_at=timezone.now())


@admin.register(EduSubscriptionSettings)
class EduSubscriptionSettingsAdmin(admin.ModelAdmin):
    list_display = ('trial_student_limit', 'updated_at')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not EduSubscriptionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InstitutionDocumentVerification)
class InstitutionDocumentVerificationAdmin(admin.ModelAdmin):
    list_display = (
        'institution', 'document_type', 'status', 'provider',
        'reference_value', 'api_checked_at', 'reviewed_by', 'reviewed_at',
    )
    list_filter = ('status', 'document_type', 'provider', 'institution__institution_type')
    search_fields = ('institution__name', 'institution__school_code', 'reference_value')
    readonly_fields = ('api_checked_at', 'api_response', 'created_at', 'updated_at')
    actions = ('run_api_verification', 'approve_documents', 'reject_documents')
    fieldsets = (
        (None, {
            'fields': ('institution', 'document_type', 'document_file', 'reference_value', 'status')
        }),
        ('API Verification', {
            'fields': ('provider', 'api_checked_at', 'api_response')
        }),
        ('Agent/Admin Review', {
            'fields': ('review_note', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    @admin.action(description='Run CAC/TIN/NIN API verification')
    def run_api_verification(self, request, queryset):
        for document in queryset:
            verify_document_with_api(document)
        self.message_user(request, f'API verification checked for {queryset.count()} document(s).')

    @admin.action(description='Approve selected documents')
    def approve_documents(self, request, queryset):
        queryset.update(status='approved', reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'{queryset.count()} document(s) approved.')

    @admin.action(description='Reject selected documents')
    def reject_documents(self, request, queryset):
        queryset.update(status='rejected', reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'{queryset.count()} document(s) rejected.')


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'code')
    list_filter = ('institution',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'faculty', 'code')
    list_filter = ('faculty',)


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'is_current')
    list_filter = ('institution', 'is_current')


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ('session', 'term', 'is_current')
    list_filter = ('term', 'is_current')


@admin.register(AcademicClass)
class AcademicClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'level', 'academic_session', 'academic_term')
    list_filter = ('institution', 'academic_session', 'academic_term')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'code')
    list_filter = ('institution',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'institution', 'institution_type')
    list_filter = ('role', 'institution_type')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'student_id', 'institution', 'academic_class', 'status')
    list_filter = ('institution', 'status')
    search_fields = ('full_name', 'student_id')


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'staff_id', 'institution', 'role')
    list_filter = ('institution', 'role')
    search_fields = ('full_name', 'staff_id')


@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'academic_class', 'amount', 'term', 'session')
    list_filter = ('institution', 'term', 'session')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('student', 'fee', 'institution', 'amount', 'status', 'payment_method', 'reference', 'paid_at')
    list_filter = ('institution', 'fee', 'status', 'payment_method')
    search_fields = ('reference', 'gateway_reference', 'student__full_name', 'student__student_id')


@admin.register(SalaryVoucher)
class SalaryVoucherAdmin(admin.ModelAdmin):
    list_display = ('reference', 'staff_name', 'institution', 'salary_amount', 'payment_gateway', 'payment_date', 'status', 'account_verification_status')
    list_filter = ('institution', 'payment_gateway', 'payment_frequency', 'status', 'account_verification_status', 'payment_date')
    search_fields = ('reference', 'staff_name', 'bank_account_number', 'verified_account_name', 'gateway_reference')
    readonly_fields = ('reference', 'created_at', 'updated_at', 'approved_at', 'processed_at')


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_class', 'subject', 'teacher', 'total', 'grade', 'term', 'session')
    list_filter = ('institution', 'academic_class', 'academic_session', 'academic_term', 'grade')


@admin.register(ResultAuditLog)
class ResultAuditLogAdmin(admin.ModelAdmin):
    list_display = ('result', 'changed_by', 'previous_total', 'previous_grade', 'changed_at')
    list_filter = ('changed_at',)
    search_fields = ('result__student__full_name', 'result__student__student_id', 'changed_by__username')
    readonly_fields = [f.name for f in ResultAuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EduMembership)
class EduMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'institution', 'role', 'is_approved', 'created_at')
    list_filter = ('role', 'is_approved')
    search_fields = ('user__username', 'user__email', 'institution__name')


@admin.register(StudentGuardian)
class StudentGuardianAdmin(admin.ModelAdmin):
    list_display = ('student', 'membership', 'relationship', 'created_at')
    search_fields = ('student__full_name', 'student__student_id', 'membership__user__email')


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'academic_class', 'institution')
    list_filter = ('institution',)


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    list_display = ('academic_class', 'subject')

# Register your models here.
