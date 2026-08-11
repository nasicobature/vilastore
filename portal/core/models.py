from django.conf import settings
from django.db import models
from django.utils import timezone


class Institution(models.Model):
    TYPE_CHOICES = [
        ('secondary', 'Secondary School'),
        ('tertiary', 'Tertiary Institution'),
    ]
    OWNERSHIP_CHOICES = [
        ('private', 'Private'),
        ('public', 'Public'),
        ('government', 'Government'),
    ]
    GRADING_CHOICES = [
        ('percentage', 'Percentage'),
        ('gpa', 'GPA'),
        ('custom', 'Custom'),
    ]
    BILLING_CHOICES = [
        ('term', 'Per Term'),
        ('session', 'Per Session'),
    ]

    name = models.CharField(max_length=200)
    school_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    short_name = models.CharField(max_length=20, blank=True)
    institution_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    ownership_type = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, default='private')
    year_established = models.PositiveIntegerField(null=True, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    cac_number = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Nigeria')
    state = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    has_faculties = models.BooleanField(default=False)
    has_departments = models.BooleanField(default=False)
    grading_system = models.CharField(max_length=20, choices=GRADING_CHOICES, default='percentage')
    max_grade = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    currency = models.CharField(max_length=10, default='NGN')
    payment_provider = models.CharField(max_length=50, blank=True)
    payment_public_key = models.CharField(max_length=200, blank=True)
    payment_secret_key = models.CharField(max_length=200, blank=True)
    allow_online_payment = models.BooleanField(default=False)
    admin_email = models.EmailField(blank=True)
    admin_phone = models.CharField(max_length=30, blank=True)
    logo = models.FileField(upload_to='institutions/logos/', blank=True, null=True)
    favicon = models.FileField(upload_to='institutions/favicons/', blank=True, null=True)
    theme_color = models.CharField(max_length=20, blank=True)
    selected_package = models.CharField(max_length=50, blank=True)
    billing_period = models.CharField(max_length=20, choices=BILLING_CHOICES, default='term')
    user_sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def _generate_code(self):
        base = (self.short_name or self.name or "SCHOOL").upper()
        base = "".join(ch for ch in base if ch.isalnum())
        base = base[:6] or "SCHOOL"
        code = base
        counter = 1
        while Institution.objects.filter(school_code=code).exclude(pk=self.pk).exists():
            counter += 1
            code = f"{base}{counter}"
        return code

    def save(self, *args, **kwargs):
        if not self.school_code:
            self.school_code = self._generate_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_institution_type_display()})"


class Faculty(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='faculties')
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.name} - {self.institution.name}"


class Department(models.Model):
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.name} ({self.faculty.name})"


class AcademicSession(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='sessions')
    name = models.CharField(max_length=20)
    is_current = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.institution.name}"


class AcademicTerm(models.Model):
    TERM_CHOICES = [
        ('first', 'First Term'),
        ('second', 'Second Term'),
        ('third', 'Third Term'),
    ]

    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name='terms')
    term = models.CharField(max_length=10, choices=TERM_CHOICES)
    is_current = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.get_term_display()} - {self.session.name}"


class AcademicClass(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='classes')
    name = models.CharField(max_length=50)
    level = models.IntegerField(default=1)
    subjects = models.ManyToManyField('Subject', through='ClassSubject', blank=True)

    def __str__(self):
        return f"{self.name} - {self.institution.name}"


class Subject(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='subjects')
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('registry', 'Registry'),
        ('accountant', 'Accountant'),
        ('teacher', 'Teacher'),
        ('examiner', 'Examiner'),
        ('student', 'Student'),
        ('vc', 'VC'),
        ('provost', 'Provost'),
        ('ict-admin', 'ICT Admin'),
        ('faculty-admin', 'Faculty Admin'),
        ('department-admin', 'Department Admin'),
        ('hod', 'HOD'),
        ('lecturer', 'Lecturer'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    institution = models.ForeignKey(Institution, on_delete=models.SET_NULL, null=True, blank=True)
    institution_type = models.CharField(max_length=20, choices=Institution.TYPE_CHOICES, default='secondary')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    faculty = models.ForeignKey(Faculty, on_delete=models.SET_NULL, null=True, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_profiles')
    created_via = models.CharField(max_length=20, blank=True)  # e.g., admin, registry, self
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_profiles')
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class Student(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='students')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    student_id = models.CharField(max_length=30, unique=True)
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, default='Active')
    next_of_kin_name = models.CharField(max_length=150, blank=True)
    next_of_kin_phone = models.CharField(max_length=30, blank=True)
    next_of_kin_relationship = models.CharField(max_length=50, blank=True)
    photo = models.ImageField(upload_to='students/photos/', blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.full_name} ({self.student_id})"


class Staff(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='staff')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    staff_id = models.CharField(max_length=30, unique=True)
    role = models.CharField(max_length=20, choices=Profile.ROLE_CHOICES, default='teacher')
    department = models.CharField(max_length=120, blank=True)
    photo = models.ImageField(upload_to='staff/photos/', blank=True, null=True)
    classes = models.ManyToManyField('AcademicClass', through='TeacherAssignment', blank=True)

    def __str__(self):
        return f"{self.full_name} ({self.staff_id})"


class Fee(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='fees')
    name = models.CharField(max_length=120)
    fee_type = models.CharField(max_length=60, blank=True)
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.SET_NULL, null=True, blank=True)
    classes = models.ManyToManyField(AcademicClass, related_name='fees', blank=True)
    departments = models.ManyToManyField(Department, related_name='fees', blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    term = models.CharField(max_length=50, blank=True)
    session = models.CharField(max_length=20, blank=True)
    due_date = models.DateField(null=True, blank=True)
    applies_to_all = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.amount}"


class Payment(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='payments')
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='Paid')
    paid_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.student} - {self.amount}"


class Result(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    test1 = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    test2 = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    assignment = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    exam = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    grade = models.CharField(max_length=2, blank=True)
    term = models.CharField(max_length=50, blank=True)
    session = models.CharField(max_length=20, blank=True)

    def save(self, *args, **kwargs):
        self.total = self.test1 + self.test2 + self.assignment + self.exam
        if not self.grade:
            if self.total >= 70:
                self.grade = 'A'
            elif self.total >= 60:
                self.grade = 'B'
            elif self.total >= 50:
                self.grade = 'C'
            elif self.total >= 45:
                self.grade = 'D'
            else:
                self.grade = 'F'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.subject}"


class ResultSubmission(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='result_submissions')
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    submitted_by = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='result_submissions')
    session = models.CharField(max_length=20, blank=True)
    term = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    submitted_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.academic_class.name} - {self.subject.name} ({self.status})"


class TeacherAssignment(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='teacher_assignments')
    teacher = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='assignments')
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.teacher.full_name} - {self.academic_class.name}"


class TeacherSubjectAssignment(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='teacher_subject_assignments')
    teacher = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='subject_assignments')
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('teacher', 'academic_class', 'subject')

    def __str__(self):
        return f"{self.teacher.full_name} - {self.academic_class.name} ({self.subject.name})"


class ClassSubject(models.Model):
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE, related_name='class_subjects')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='subject_classes')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('academic_class', 'subject')

    def __str__(self):
        return f"{self.academic_class.name} - {self.subject.name}"

# Create your models here.
