import uuid
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login, logout
from .models import *
from .forms import *
from .utils import send_templated_email, PaystackAPI
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.db.models import Sum, Q, Count
import json
from django.db.models.functions import TruncMonth 
from collections import defaultdict
import datetime

# --- CUSTOM DECORATORS ---

def instructor_required(view_func):
    """
    Decorator for views that checks that the user is logged in and is an instructor.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_instructor:
            messages.error(request, "You do not have permission to access this page.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# --- CORE & AUTHENTICATION VIEWS ---

def home_view(request):
    """Displays the homepage with the 6 most recent published courses."""
    courses = Course.objects.filter(is_published=True).order_by('-created_at')[:6]
    context = {'courses': courses}
    return render(request, 'home.html', context)

def register_view(request):
    """Handles new user registration and initiates email verification."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # User cannot log in until verified
            user.save()

            token = EmailVerificationToken.objects.create(user=user)
            verification_url = request.build_absolute_uri(
                reverse('verify_email', kwargs={'token': token.id})
            )
            
            context = {
                'user': user,
                'verification_url': verification_url,
            }
            send_templated_email(
                'emails/verify_email.html',
                'Activate Your Erudio Account',
                [user.email],
                context
            )
            
            messages.success(request, 'Registration successful! Please check your email to activate your account.')
            return redirect('login')
    else:
        form = RegistrationForm()
        
    return render(request, 'accounts/register.html', {'form': form})

def login_view(request):
    """Handles user login."""
    if request.user.is_authenticated:
        return redirect('home')
        
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            if not user.is_verified:
                messages.warning(request, 'Your account is not verified. Please check your email for the activation link.')
                return redirect('login')
            
            login(request, user)
            messages.success(request, f'Welcome back, {user.first_name}!')
            next_page = request.GET.get('next')
            return redirect(next_page) if next_page else redirect('home')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})

@login_required
def logout_view(request):
    """Handles user logout."""
    logout(request)
    messages.info(request, "You have been successfully logged out.")
    return redirect('home')

def verify_email_view(request, token):
    """Handles the email verification from the link clicked by the user."""
    try:
        verification_token = EmailVerificationToken.objects.get(id=token)
        user = verification_token.user
        
        if verification_token.is_expired():
            messages.error(request, 'The verification link has expired. Please register again.')
            user.delete() 
            return redirect('register')
        
        user.is_active = True
        user.is_verified = True
        user.save()
        
        verification_token.delete()
    
        login(request, user)
        messages.success(request, 'Email verified! Your account is now active. Welcome to Erudio!')
        return redirect('home')

    except EmailVerificationToken.DoesNotExist:
        messages.error(request, 'The verification link is invalid or has already been used.')
        return redirect('home')

# --- PUBLIC COURSE VIEWS ---

def course_list_view(request):
    queryset = Course.objects.filter(is_published=True).order_by('-created_at')
    categories = Category.objects.all()
    search_query = request.GET.get('q')
    selected_category_slug = request.GET.get('category')

    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query) |
            Q(short_description__icontains=search_query) |
            Q(instructor__first_name__icontains=search_query) |
            Q(instructor__last_name__icontains=search_query)
        )
    if selected_category_slug:
        queryset = queryset.filter(category__slug=selected_category_slug)

    context = {
        'courses': queryset,
        'categories': categories,
        'search_query': search_query or '',
        'selected_category': selected_category_slug,
    }
    return render(request, 'course_list.html', context)


def course_detail_view(request, slug):
    """Displays the details for a single published course."""
    course = get_object_or_404(
        Course.objects.prefetch_related('modules__lessons'), 
        slug=slug, 
        is_published=True
    )
    context = {'course': course}
    return render(request, 'course_detail.html', context)

# --- STUDENT DASHBOARD & LEARNING VIEWS ---

@login_required
def my_courses_view(request):
    """Displays the list of courses the current user is enrolled in."""
    enrollments = Enrollment.objects.filter(student=request.user).select_related('course').order_by('-enrolled_at')
    context = {'enrollments': enrollments}
    return render(request, 'my_courses.html', context)

@login_required
def lesson_detail_view(request, course_slug, lesson_slug):
    """Displays the course player page for a specific lesson, verifying enrollment."""
    course = get_object_or_404(Course.objects.prefetch_related('modules__lessons'), slug=course_slug, is_published=True)
    
    if not Enrollment.objects.filter(student=request.user, course=course).exists():
        messages.error(request, "You must be enrolled in this course to view its lessons.")
        raise PermissionDenied("User is not enrolled in this course.")

    current_lesson = get_object_or_404(Lesson, slug=lesson_slug, module__course=course)

    context = {
        'course': course,
        'current_lesson': current_lesson
    }
    return render(request, 'course_player.html', context)

@login_required
def mark_lesson_complete_view(request, lesson_id):
    """Handles marking a lesson as complete via a POST request."""
    if request.method == 'POST':
        lesson = get_object_or_404(Lesson, id=lesson_id)
        course = lesson.module.course
        enrollment = get_object_or_404(Enrollment, student=request.user, course=course)
        enrollment.completed_lessons.add(lesson)

        # Find the next lesson to redirect to
        all_lessons = list(Lesson.objects.filter(module__course=course).order_by('module__order', 'order'))
        try:
            current_index = all_lessons.index(lesson)
            if current_index + 1 < len(all_lessons):
                next_lesson = all_lessons[current_index + 1]
                messages.success(request, f"Great job on completing '{lesson.title}'!")
                return redirect(next_lesson.get_absolute_url())
            else:
                messages.success(request, f"Congratulations! You have completed the course: '{course.title}'!")
                return redirect('my_courses')
        except ValueError:
            return redirect('my_courses')

    return redirect('home') # Should not be accessed via GET

# --- PAYMENT & ENROLLMENT VIEWS ---

@login_required
def initiate_payment_view(request, slug):
    """Initiates payment for a course or enrolls for free."""
    course = get_object_or_404(Course, slug=slug, is_published=True)

    if Enrollment.objects.filter(student=request.user, course=course).exists():
        messages.info(request, "You are already enrolled in this course.")
        return redirect('course_detail', slug=slug)

    if not course.is_paid or course.price == 0:
        Enrollment.objects.create(student=request.user, course=course)
        messages.success(request, f"You have successfully enrolled in '{course.title}'.")
        return redirect('my_courses')

    reference = f"ERUDIO-{request.user.id}-{course.id}-{uuid.uuid4().hex[:10].upper()}"
    
    Transaction.objects.create(
        student=request.user, course=course, reference=reference, amount=course.price, status='pending'
    )
    paystack = PaystackAPI()
    callback_url = request.build_absolute_uri(reverse('verify_payment'))
    amount_in_kobo = int(course.price * 100)
    api_response = paystack.initialize_transaction(request.user.email, amount_in_kobo, reference, callback_url)

    if api_response and api_response.get('status'):
        return redirect(api_response['data']['authorization_url'])
    else:
        messages.error(request, "We couldn't connect to the payment gateway. Please try again later.")
        return redirect('course_detail', slug=slug)

@login_required
def verify_payment_view(request):
    """Handles the callback from Paystack to verify a transaction."""
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, "Payment verification failed. No reference provided.")
        return redirect('course_list')

    try:
        transaction = Transaction.objects.get(reference=reference, student=request.user)
    except Transaction.DoesNotExist:
        messages.error(request, "Invalid transaction reference.")
        return redirect('course_list')

    paystack = PaystackAPI()
    api_response = paystack.verify_transaction(reference)

    if api_response and api_response.get('data') and api_response['data']['status'] == 'success':
        transaction.status = 'success'
        transaction.save()
        Enrollment.objects.get_or_create(student=transaction.student, course=transaction.course)
        messages.success(request, f"Payment successful! You are now enrolled in '{transaction.course.title}'.")
        return redirect('my_courses')
    else:
        transaction.status = 'failed'
        transaction.save()
        error_message = api_response.get('message', "Please contact support if you were debited.")
        messages.error(request, f"Payment verification failed. Reason: {error_message}")
        return redirect('course_detail', slug=transaction.course.slug)

# --- INSTRUCTOR DASHBOARD VIEWS ---

@instructor_required
def instructor_dashboard_view(request):
    """Main dashboard for instructors to view their courses."""
    courses = Course.objects.filter(instructor=request.user).order_by('-created_at')
    context = {'courses': courses}
    return render(request, 'instructor/dashboard.html', context)

@instructor_required
def course_create_view(request):
    """View for instructors to create a new course."""
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.instructor = request.user
            course.save()
            messages.success(request, f"Course '{course.title}' has been successfully created.")
            return redirect('instructor_dashboard')
    else:
        form = CourseForm()
    context = {'form': form}
    return render(request, 'instructor/course_form.html', context)

@instructor_required
def course_update_view(request, slug):
    """View for instructors to update their existing course."""
    course = get_object_or_404(Course, slug=slug, instructor=request.user)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, f"Course '{course.title}' has been successfully updated.")
            return redirect('instructor_dashboard')
    else:
        form = CourseForm(instance=course)
    context = {
        'form': form,
        'course': course 
    }
    return render(request, 'instructor/course_form.html', context)


@instructor_required
def course_manage_view(request, slug):
    course = get_object_or_404(Course.objects.prefetch_related('modules__lessons'), slug=slug, instructor=request.user)
    module_form = ModuleForm()
    lesson_form = LessonForm()
    context = {'course': course, 'module_form': module_form, 'lesson_form': lesson_form}
    return render(request, 'instructor/course_manage.html', context)


# --- AJAX API for COURSE MANAGEMENT ---

@instructor_required
def module_create_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug, instructor=request.user)
    if request.method == 'POST':
        form = ModuleForm(request.POST)
        if form.is_valid():
            module = form.save(commit=False)
            module.course = course
            module.save()
            html = render_to_string('partials/module_item.html', {'module': module})
            return JsonResponse({'status': 'success', 'html': html})
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@instructor_required
def module_update_view(request, module_id):
    module = get_object_or_404(Module, id=module_id, course__instructor=request.user)
    if request.method == 'POST':
        form = ModuleForm(request.POST, instance=module)
        if form.is_valid():
            module = form.save()
            return JsonResponse({'status': 'success', 'title': module.title, 'order': module.order})
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@instructor_required
def module_delete_view(request, module_id):
    module = get_object_or_404(Module, id=module_id, course__instructor=request.user)
    if request.method == 'POST':
        module.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

@instructor_required
def lesson_create_view(request, module_id):
    module = get_object_or_404(Module, id=module_id, course__instructor=request.user)
    if request.method == 'POST':
        form = LessonForm(request.POST)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.module = module
            lesson.save()
            html = render_to_string('partials/lesson_item.html', {'lesson': lesson})
            return JsonResponse({'status': 'success', 'html': html})
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@instructor_required
def lesson_update_view(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id, module__course__instructor=request.user)
    if request.method == 'POST':
        form = LessonForm(request.POST, instance=lesson)
        if form.is_valid():
            lesson = form.save()
            return JsonResponse({'status': 'success', 'title': lesson.title, 'order': lesson.order})
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@instructor_required
def lesson_delete_view(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id, module__course__instructor=request.user)
    if request.method == 'POST':
        lesson.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)


@instructor_required
def instructor_analytics_view(request):
    """
    Displays key performance indicators and enrollment trends for the instructor.
    """
    instructor = request.user
    courses = Course.objects.filter(instructor=instructor)
    course_ids = courses.values_list('id', flat=True)
    
    # KPIs
    total_enrollments = Enrollment.objects.filter(course_id__in=course_ids).count()
    total_students = Enrollment.objects.filter(course_id__in=course_ids).values('student').distinct().count()
    total_revenue = Transaction.objects.filter(course_id__in=course_ids, status='success').aggregate(total=Sum('amount'))['total'] or 0.00
    
    # Recent Enrollments & Top Courses
    recent_enrollments = Enrollment.objects.filter(course_id__in=course_ids).select_related('student', 'course').order_by('-enrolled_at')[:5]
    top_courses = courses.annotate(num_enrollments=Count('enrollments')).order_by('-num_enrollments')[:5]

    # Chart Data: Enrollments in the last 6 months
    today = datetime.date.today()
    six_months_ago = today - datetime.timedelta(days=180)
    
    enrollment_data = Enrollment.objects.filter(
        course_id__in=course_ids,
        enrolled_at__gte=six_months_ago
    ).annotate(month=TruncMonth('enrolled_at')).values('month').annotate(count=Count('id')).order_by('month')

    # Prepare data for Chart.js
    chart_labels = []
    chart_values = []
    month_dict = {i: 0 for i in range(1, 13)}
    
    for data in enrollment_data:
        month_dict[data['month'].month] = data['count']

    for i in range(6):
        month_num = (today.month - i - 1) % 12 + 1
        year = today.year if today.month > i else today.year -1
        month_name = datetime.date(year, month_num, 1).strftime('%b')
        chart_labels.insert(0, month_name)
        chart_values.insert(0, month_dict.get(month_num, 0))

    context = {
        'total_courses': courses.count(),
        'total_enrollments': total_enrollments,
        'total_students': total_students,
        'total_revenue': total_revenue,
        'recent_enrollments': recent_enrollments,
        'top_courses': top_courses,
        'chart_labels': chart_labels,
        'chart_values': chart_values,
    }
    return render(request, 'instructor/analytics.html', context)


@instructor_required
def category_create_view(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            html = render_to_string('partials/category_item.html', {'category': category})
            return JsonResponse({'status': 'success', 'html': html})
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    return JsonResponse({'status': 'error'}, status=405)

@instructor_required
def category_delete_view(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        if category.courses.exists():
            return JsonResponse({'status': 'error', 'message': 'This category is in use and cannot be deleted.'}, status=400)
        category.delete()

