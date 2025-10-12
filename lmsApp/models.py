import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.utils.text import slugify
from django.urls import reverse

# === USER MANAGEMENT MODELS ===

class CustomUserManager(BaseUserManager):
    """
    Custom user model manager where email is the unique identifier
    for authentication instead of usernames.
    """
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('is_instructor', True) # Superusers are also instructors
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    """
    Custom User model. Email is the username field.
    """
    username = None
    email = models.EmailField('email address', unique=True)
    is_verified = models.BooleanField(default=False)
    is_instructor = models.BooleanField(default=False)
    profile_picture_url = models.URLField(max_length=500, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    receives_new_course_emails = models.BooleanField(default=True)
    receives_progress_reminders = models.BooleanField(default=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = CustomUserManager()

    def __str__(self):
        return self.email


class EmailVerificationToken(models.Model):
    """
    Model to store tokens for email verification.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='verification_token')
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        expiration_time = self.created_at + timezone.timedelta(hours=24)
        return timezone.now() > expiration_time

    def __str__(self):
        return f"Token for {self.user.email}"

# === COURSE CONTENT MODELS ===

class Category(models.Model):
    """
    Model for course categories.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "Categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Course(models.Model):
    """
    Represents a course in the platform.
    """
    DIFFICULTY_CHOICES = [
        ('Beginner', 'Beginner'),
        ('Intermediate', 'Intermediate'),
        ('Advanced', 'Advanced'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField(max_length=255)
    long_description = models.TextField()
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='courses_taught',
        limit_choices_to={'is_instructor': True}
    )
    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default='Beginner'
    )
    category = models.ManyToManyField(Category, null=True, blank=True, related_name='courses')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    thumbnail_url = models.URLField(max_length=500, blank=True, null=True)
    is_paid = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    what_you_will_learn = models.TextField(
        blank=True, 
        null=True, 
        help_text="Enter one learning outcome per line."
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Course.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('course_detail', kwargs={'slug': self.slug})

    def get_total_lesson_count(self):
        return sum(module.lessons.count() for module in self.modules.all())
    
    @property
    def learning_outcomes(self):
        """Returns a list of learning outcomes from the text field."""
        if not self.what_you_will_learn:
            return []
        return [line.strip() for line in self.what_you_will_learn.split('\n') if line.strip()]

    def __str__(self):
        return self.title


class Module(models.Model):
    """
    A module within a course, containing several lessons.
    """
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)


    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.course.title} - Module {self.order}: {self.title}"


class Lesson(models.Model):
    """
    A single lesson within a module.
    """
    module = models.ForeignKey(Module, related_name='lessons', on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, blank=True)
    video_url = models.URLField(max_length=500)
    content = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        unique_together = ('module', 'slug')
        ordering = ['order']

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            # Ensure slug is unique within the course
            while Lesson.objects.filter(module__course=self.module.course, slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('lesson_detail', kwargs={
            'course_slug': self.module.course.slug,
            'lesson_slug': self.slug
        })

    def __str__(self):
        return self.title

# === STUDENT & PAYMENT MODELS ===

class Enrollment(models.Model):
    """
    Model to track user enrollment in courses and their progress.
    """
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_lessons = models.ManyToManyField('Lesson', blank=True)

    class Meta:
        unique_together = ('student', 'course')

    @property
    def get_progress_percentage(self):
        total_lessons = self.course.get_total_lesson_count()
        if total_lessons == 0:
            return 0
        completed_count = self.completed_lessons.count()
        return int((completed_count / total_lessons) * 100)
    
    def get_next_lesson(self):
        """
        Finds the first lesson in the course that the user has not completed.
        Returns the lesson object or None if the course is complete.
        """
        all_lessons = Lesson.objects.filter(module__course=self.course, is_published=True).order_by('module__order', 'order')
        completed_lesson_ids = self.completed_lessons.values_list('id', flat=True)
        
        for lesson in all_lessons:
            if lesson.id not in completed_lesson_ids:
                return lesson
        # If all lessons are completed, return None
        return None
    
    def is_module_complete(self, module):
        """
        Checks if all published lessons in a given module have been completed by the student.
        """
        module_lessons = module.lessons.filter(is_published=True)
        # If a module has no lessons, it's considered complete.
        if not module_lessons.exists():
            return True
        
        completed_lessons_in_module = self.completed_lessons.filter(module=module)
        return completed_lessons_in_module.count() >= module_lessons.count()
    
    def __str__(self):
        return f"{self.student.email} enrolled in {self.course.title}"


class Transaction(models.Model):
    """
    Model to store payment transaction details from Paystack.
    """
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Transaction {self.reference} for {self.student.email}"


class SubscriptionPlan(models.Model):
    """
    Defines a B2B subscription plan that a Team can subscribe to.
    """
    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per month in NGN.")
    max_members = models.PositiveIntegerField(help_text="Maximum number of members allowed in the team.")
    description = models.TextField(blank=True, null=True)
    features = models.TextField(help_text="Enter one feature per line. This will be displayed as a list.", blank=True, null=True)

    def __str__(self):
        return f"{self.name} - ₦{self.price}/month"

    @property
    def feature_list(self):
        if not self.features:
            return []
        return [line.strip() for line in self.features.split('\n') if line.strip()]


class Team(models.Model):
    """
    Represents a company or organization on the Erudio for Business platform.
    """
    name = models.CharField(max_length=200, help_text="The name of the company or team.")
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='owned_team',
        help_text="The user who manages this team."
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        related_name='teams', 
        blank=True,
        help_text="Employees who are members of this team."
    )
    phone_number = models.CharField(max_length=20, blank=True, null=True, help_text="Contact phone number for the team/company.")
    address = models.TextField(blank=True, null=True, help_text="Registered business address for invoicing.")
    created_at = models.DateTimeField(auto_now_add=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=False, help_text="Is the subscription for this team currently active?")
    subscription_ends = models.DateTimeField(null=True, blank=True)

    @property
    def has_expired(self):
        """Checks if the subscription has expired."""
        if self.is_active and self.subscription_ends and self.subscription_ends < timezone.now():
            return True
        return False
    
    def __str__(self):
        return f"{self.name} (Managed by {self.owner.email})"