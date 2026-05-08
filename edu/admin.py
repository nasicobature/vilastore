from django.contrib import admin
from django.utils import timezone
from .models import (
    Institution,
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
    Result,
    TeacherAssignment,
    ClassSubject,
)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution_type', 'city', 'country', 'verification_status', 'verified_at')
    list_filter = ('institution_type', 'verification_status')
    search_fields = ('name', 'school_code', 'email', 'admin_email')
    readonly_fields = ('created_at', 'verified_at')
    fieldsets = (
        (None, {
            'fields': (
                'name', 'school_code', 'short_name', 'institution_type', 'ownership_type',
                'year_established', 'license_number', 'cac_number',
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

        if obj.verification_status == 'approved':
            Profile.objects.filter(
                institution=obj,
                created_via='school-register',
                is_approved=False,
            ).update(is_approved=True, approved_by=request.user, approved_at=timezone.now())


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
    list_display = ('name', 'institution', 'level')
    list_filter = ('institution',)


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


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'total', 'grade', 'term', 'session')
    list_filter = ('institution', 'term', 'session', 'grade')


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'academic_class', 'institution')
    list_filter = ('institution',)


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    list_display = ('academic_class', 'subject')

# Register your models here.
