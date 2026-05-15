from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal


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
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    REGISTRATION_PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(max_length=200)
    school_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    short_name = models.CharField(max_length=20, blank=True)
    institution_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    ownership_type = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, default='private')
    year_established = models.PositiveIntegerField(null=True, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    cac_number = models.CharField(max_length=100, blank=True)
    tin_number = models.CharField(max_length=100, blank=True)
    owner_id_number = models.CharField(max_length=100, blank=True)
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
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS_CHOICES, default='pending')
    verification_review_note = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    registration_payment_status = models.CharField(max_length=20, choices=REGISTRATION_PAYMENT_STATUS_CHOICES, default='pending')
    registration_payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('25000.00'))
    registration_payment_reference = models.CharField(max_length=120, blank=True)
    registration_payment_paid_at = models.DateTimeField(null=True, blank=True)
    cac_certificate = models.FileField(upload_to='institutions/verification/cac_certificates/', blank=True, null=True)
    cac_status_report = models.FileField(upload_to='institutions/verification/cac_status_reports/', blank=True, null=True)
    ministry_approval = models.FileField(upload_to='institutions/verification/ministry_approvals/', blank=True, null=True)
    operating_license = models.FileField(upload_to='institutions/verification/operating_licenses/', blank=True, null=True)
    tin_certificate = models.FileField(upload_to='institutions/verification/tax_documents/', blank=True, null=True)
    school_letterhead = models.FileField(upload_to='institutions/verification/letterheads/', blank=True, null=True)
    school_stamp = models.FileField(upload_to='institutions/verification/stamps/', blank=True, null=True)
    owner_valid_id = models.FileField(upload_to='institutions/verification/owner_ids/', blank=True, null=True)
    utility_bill = models.FileField(upload_to='institutions/verification/address_documents/', blank=True, null=True)
    proof_of_address = models.FileField(upload_to='institutions/verification/address_documents/', blank=True, null=True)
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


class InstitutionDocumentVerification(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('cac_certificate', 'CAC Certificate'),
        ('cac_status_report', 'CAC Status Report'),
        ('ministry_approval', 'Ministry Approval'),
        ('operating_license', 'Operating License'),
        ('tin_certificate', 'TIN or Tax Certificate'),
        ('school_letterhead', 'School Letterhead'),
        ('school_stamp', 'School Stamp/Seal'),
        ('owner_valid_id', 'Owner/Admin Valid ID'),
        ('utility_bill', 'Utility Bill'),
        ('proof_of_address', 'Proof of Address'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending API Check'),
        ('api_verified', 'API Verified'),
        ('api_failed', 'API Failed'),
        ('manual_review', 'Manual Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='document_verifications')
    document_type = models.CharField(max_length=40, choices=DOCUMENT_TYPE_CHOICES)
    document_file = models.FileField(upload_to='institutions/document_verifications/', blank=True, null=True)
    reference_value = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    provider = models.CharField(max_length=100, blank=True)
    api_checked_at = models.DateTimeField(null=True, blank=True)
    api_response = models.JSONField(default=dict, blank=True)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='edu_document_reviews')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('institution', 'document_type')
        ordering = ['institution__name', 'document_type']

    def __str__(self):
        return f"{self.institution.name} - {self.get_document_type_display()}"


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
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
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


class StudentClassHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='class_history')
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE, related_name='student_history')
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_class_history')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_class_history')
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('student', 'academic_class', 'academic_session', 'academic_term')

    def __str__(self):
        return f"{self.student.full_name} - {self.academic_class.name}"


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
    fee = models.ForeignKey(Fee, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='Paid')
    payment_method = models.CharField(max_length=30, default='Manual')
    reference = models.CharField(max_length=80, unique=True, null=True, blank=True)
    gateway_reference = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self.reference:
            prefix = 'EDURCPT'
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            base = f"{prefix}-{timestamp}"
            reference = base
            counter = 1
            while Payment.objects.filter(reference=reference).exclude(pk=self.pk).exists():
                counter += 1
                reference = f"{base}-{counter}"
            self.reference = reference
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.amount}"


class SalaryVoucher(models.Model):
    GATEWAY_CHOICES = [
        ('flutterwave', 'Flutterwave'),
        ('paystack', 'Paystack'),
        ('remita', 'Remita'),
    ]
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('one_time', 'One-time'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ]
    ACCOUNT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('failed', 'Failed'),
        ('manual_review', 'Manual Review'),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='salary_vouchers')
    staff = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name='salary_vouchers')
    staff_name = models.CharField(max_length=150)
    bank_account_number = models.CharField(max_length=30)
    bank_name = models.CharField(max_length=120)
    bank_code = models.CharField(max_length=30, blank=True)
    verified_account_name = models.CharField(max_length=150)
    salary_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    payment_gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES, default='flutterwave')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    account_verification_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default='pending')
    account_verification_note = models.TextField(blank=True)
    reference = models.CharField(max_length=80, unique=True, null=True, blank=True)
    gateway_reference = models.CharField(max_length=120, blank=True)
    failure_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_salary_vouchers')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_salary_vouchers')
    approved_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def save(self, *args, **kwargs):
        if not self.reference:
            prefix = 'EDUSAL'
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            base = f"{prefix}-{timestamp}"
            reference = base
            counter = 1
            while SalaryVoucher.objects.filter(reference=reference).exclude(pk=self.pk).exists():
                counter += 1
                reference = f"{base}-{counter}"
            self.reference = reference
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff_name} - {self.salary_amount} ({self.status})"


class Result(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    test1 = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    test2 = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    assignment = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    exam = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    grade = models.CharField(max_length=2, blank=True)
    term = models.CharField(max_length=50, blank=True)
    session = models.CharField(max_length=20, blank=True)

    def save(self, *args, **kwargs):
        self.test1 = Decimal(str(self.test1 or 0))
        self.test2 = Decimal(str(self.test2 or 0))
        self.assignment = Decimal(str(self.assignment or 0))
        self.exam = Decimal(str(self.exam or 0))
        self.total = self.test1 + self.test2 + self.assignment + self.exam
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
        ('draft', 'Draft'),
        ('submitted_to_examiner', 'Submitted to Examiner'),
        ('returned_for_correction', 'Returned for Correction'),
        ('approved_by_examiner', 'Approved by Examiner'),
        ('approved_by_admin', 'Approved by Admin'),
        ('published', 'Published'),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='result_submissions')
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    submitted_by = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='result_submissions')
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='result_submissions')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='result_submissions')
    session = models.CharField(max_length=20, blank=True)
    term = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    teacher_comment = models.TextField(blank=True)
    examiner_comment = models.TextField(blank=True)
    admin_comment = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)

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
