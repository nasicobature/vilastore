from django.contrib import admin
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
    list_display = ('name', 'institution_type', 'city', 'country')
    list_filter = ('institution_type',)


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
    list_display = ('student', 'institution', 'amount', 'status', 'paid_at')
    list_filter = ('institution', 'status')


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
