import uuid
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash, authenticate
from .models import *
from .forms import *
from .utils import *
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.db.models import Sum, Q, Count
from django.db.models.functions import TruncMonth 
import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.sites.shortcuts import get_current_site


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

def superuser_required(view_func):
    """Decorator for views that checks that the user is logged in and is a superuser."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
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

def about_us_view(request):
    return render(request, 'about_us.html')


from django.http import HttpResponse
from django.contrib.auth import get_user_model

User = get_user_model()

def bootstrap_superuser(request):
    # change these values before deploying!
    username = "Dhamilare"
    email = "samuelholuwatosin@gmail.com"
    password = "Klassnics@1759"
    first_name = "Samuel"
    last_name = "Omoyin"

    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        return HttpResponse(f"Superuser '{username}' created successfully.")
    else:
        return HttpResponse(f"Superuser '{username}' already exists.")



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
    """
    Handles user login with special checks for unverified, invited, and inactive B2B users.
    """
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        
        email = request.POST.get('username')
        password = request.POST.get('password')
        
        # We fetch the user object first to perform our custom checks.
        user_check = CustomUser.objects.filter(email__iexact=email).first()

        if user_check:
            # Case 1: The user is an invited B2B member who hasn't set their password yet.
            if user_check.is_invited and not user_check.has_usable_password():
                 messages.warning(request, "This account was created via an invitation. Please use the link in your invitation email to set your password.")
                 return redirect('login')

            # Case 2: The user is a B2B member whose account has been deactivated (subscription expired).
            if not user_check.is_active and user_check.is_b2b_member:
                user_auth = authenticate(request, email=email, password=password)
                if user_auth is None:
                    messages.error(request, "Your account is inactive. Your team's subscription may have expired. Please contact your team manager.")
                    return render(request, 'accounts/login.html', {'form': form})

            # Case 3: The user exists but has not verified their email.
            if not user_check.is_verified:
                # We check the password is correct before showing the verification error.
                if user_check.check_password(password):
                    messages.warning(request, 'Your account is not verified. Please check your email for the activation link.')
                    return redirect('login')

        # If all our custom checks pass, we proceed with Django's standard validation.
        # This will handle the generic "incorrect password" error for us.
        if form.is_valid():
            user = form.get_user()
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


def send_custom_password_reset_email(user, request):
    current_site = get_current_site(request)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    context = {
        "protocol": "https" if request.is_secure() else "http",
        "domain": current_site.domain,
        "uid": uid,
        "token": token,
        "user": user
    }

    send_templated_email(
        template_name="accounts/password_reset_email.html",
        subject="Your Erudio Password Reset Request",
        recipient_list=[user.email],
        context=context
    )
    

def custom_password_reset(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            users = User.objects.filter(email=email, is_active=True)
            if users.exists():
                for user in users:
                    send_custom_password_reset_email(user, request)
            return redirect('password_reset_done')
            
    else:
        form = PasswordResetForm()

    context = {
        "form": form,
    }
    return render(request, "accounts/password_reset.html", context)





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


@login_required
def course_detail_view(request, slug):
    course = get_object_or_404(Course.objects.prefetch_related('modules__lessons'), slug=slug, is_published=True)
    
    # Check if the current user is enrolled in this course.
    is_enrolled = False
    enrollment = None
    if request.user.is_authenticated:
        enrollment = Enrollment.objects.filter(student=request.user, course=course).first()
        if enrollment:
            is_enrolled = True

    context = {
        'course': course,
        'is_enrolled': is_enrolled,
        'enrollment': enrollment, # Pass the enrollment object to the template
    }
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
    """
    Displays the course player page with sequential module unlocking.
    """
    course = get_object_or_404(Course.objects.prefetch_related('modules__lessons'), slug=course_slug, is_published=True)
    
    # Robustly fetch the specific enrollment record for this user and course.
    enrollment = get_object_or_404(Enrollment, student=request.user, course=course)
    
    current_lesson = get_object_or_404(Lesson, slug=lesson_slug, module__course=course)

    # Build a list of all modules for the sidebar, calculating their lock status.
    modules_with_status = []
    previous_module_complete = True  # The first module is always considered unlocked.
    for module in course.modules.all(): # Assumes modules are ordered by the 'order' field.
        is_unlocked = previous_module_complete
        modules_with_status.append({
            'module': module,
            'is_unlocked': is_unlocked
        })
        # The lock status of the *next* module depends on the completion of the *current* one.
        if not enrollment.is_module_complete(module):
            previous_module_complete = False

    # Security Check: Prevent users from accessing lessons in a locked module via the URL.
    current_module_is_unlocked = False
    for m_data in modules_with_status:
        if m_data['module'] == current_lesson.module:
            current_module_is_unlocked = m_data['is_unlocked']
            break
            
    if not current_module_is_unlocked:
        messages.error(request, "You must complete the previous module to access this lesson.")
        # Redirect the user to the correct next lesson they should be on.
        next_lesson_to_complete = enrollment.get_next_lesson()
        if next_lesson_to_complete:
            return redirect(next_lesson_to_complete.get_absolute_url())
        return redirect('my_courses') # Failsafe redirect.

    embed_url = get_youtube_embed_url(current_lesson.video_url)
    context = {
        'course': course,
        'current_lesson': current_lesson,
        'enrollment': enrollment,
        'modules_with_status': modules_with_status,
        'embed_url': embed_url
    }
    return render(request, 'course_player.html', context)

@login_required
def mark_lesson_complete_view(request, course_slug, lesson_slug):
    """Handles marking a lesson as complete via a POST request."""
    if request.method == 'POST':
        course = get_object_or_404(Course, slug=course_slug)
        lesson = get_object_or_404(Lesson, slug=lesson_slug, module__course=course)
        enrollment = get_object_or_404(Enrollment, student=request.user, course=course)
        enrollment.completed_lessons.add(lesson)

        # Find the next lesson to redirect to
        all_lessons = list(
            Lesson.objects.filter(module__course=course).order_by('module__order', 'order')
        )
        try:
            current_index = all_lessons.index(lesson)
            if current_index + 1 < len(all_lessons):
                next_lesson = all_lessons[current_index + 1]
                messages.success(request, f"✅ Great job on completing '{lesson.title}'!")
                return redirect(next_lesson.get_absolute_url())
            else:
                messages.success(request, f"🎉 Congratulations! You’ve completed the course: '{course.title}'!")
                send_completion_certificate_email(enrollment)
                return redirect('my_courses')
        except ValueError:
            return redirect('my_courses')

    return redirect('home')  # Should not be accessed via GET


# --- PAYMENT & ENROLLMENT VIEWS ---

@login_required
def initiate_payment_view(request, slug):
    """Initiates payment for a course or enrolls for free."""
    course = get_object_or_404(Course, slug=slug, is_published=True)

    if Enrollment.objects.filter(student=request.user, course=course).exists():
        messages.info(request, "You are already enrolled in this course.")
        return redirect('course_detail', slug=slug)

    if not course.is_paid or course.price == 0:
        enrollment = Enrollment.objects.create(student=request.user, course=course)
        messages.success(request, f"You have successfully enrolled in '{course.title}'.")
        send_enrollment_confirmation_email(enrollment)
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
        enrollment, created = Enrollment.objects.get_or_create(student=transaction.student, course=transaction.course)
        messages.success(request, f"Payment successful! You are now enrolled in '{transaction.course.title}'.")
        if created:
            send_enrollment_confirmation_email(enrollment)
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


@superuser_required
def super_admin_dashboard_view(request):
    """
    Calculates and displays sitewide analytics for the super admin.
    """
    # --- KPI Calculations ---
    total_users = CustomUser.objects.count()
    total_students = CustomUser.objects.filter(is_instructor=False, is_superuser=False).count()
    total_instructors = CustomUser.objects.filter(is_instructor=True).count()
    total_courses = Course.objects.count()
    total_enrollments = Enrollment.objects.count()
    total_revenue = Transaction.objects.filter(status='success').aggregate(total=Sum('amount'))['total'] or 0.00
    total_teams = Team.objects.count()

    # --- Chart Data: New Users in the last 6 months ---
    now = timezone.now()
    six_months_ago = now - datetime.timedelta(days=180)
    
    # 1. Get the raw data from the database
    user_data = CustomUser.objects.filter(
        date_joined__gte=six_months_ago
    ).annotate(
        month=TruncMonth('date_joined')
    ).values('month').annotate(count=Count('id')).order_by('month')

    # 2. Create a simple map of the data for easy lookup
    # The key is now a simple 'YYYY-MM' string, which avoids all date/datetime issues.
    data_map = {item['month'].strftime('%Y-%m'): item['count'] for item in user_data}

    # 3. Generate the labels and values for the last 6 months in chronological order.
    chart_labels = []
    chart_values = []
    for i in range(5, -1, -1): # Loop backwards from 5 down to 0
        # Calculate the correct month and year for the last 6 months
        month_offset = now.month - i
        year_offset = now.year
        if month_offset <= 0:
            month_offset += 12
            year_offset -= 1
        
        month_date = datetime.date(year_offset, month_offset, 1)
        
        # Format the label (e.g., "Oct 2025") and the lookup key (e.g., "2025-10")
        label = month_date.strftime('%b %Y')
        key = month_date.strftime('%Y-%m')
        
        # Get the value from our data map, defaulting to 0 if no users signed up in that month.
        value = data_map.get(key, 0)
        
        chart_labels.append(label)
        chart_values.append(value)

    # --- Recent Activity Lists ---
    recent_users = CustomUser.objects.order_by('-date_joined')[:5]
    recent_transactions = Transaction.objects.filter(status='success').select_related('student', 'course').order_by('-created_at')[:5]
    recent_teams = Team.objects.select_related('owner', 'plan').order_by('-created_at')[:5]

    context = {
        'total_users': total_users, 'total_students': total_students, 'total_instructors': total_instructors,
        'total_courses': total_courses, 'total_enrollments': total_enrollments, 'total_revenue': total_revenue,
        'total_teams': total_teams, 'recent_users': recent_users, 'recent_transactions': recent_transactions,
        'recent_teams': recent_teams, 'chart_labels': chart_labels, 'chart_values': chart_values,
    }
    return render(request, 'admin/dashboard.html', context)


@login_required
def account_settings_view(request):
    user = request.user
    active_tab = 'profile' 
    
    profile_form = ProfileUpdateForm(instance=user)
    password_form = StyledPasswordChangeForm(user=user)
    notification_form = NotificationSettingsForm(instance=user)
    delete_form = AccountDeleteConfirmationForm()

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'profile':
            profile_form = ProfileUpdateForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Your profile has been updated successfully.')
                return redirect('account_settings')
            else:
                active_tab = 'profile'

        elif form_type == 'password':
            password_form = StyledPasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password was successfully updated.')
                return redirect('account_settings')
            else:
                active_tab = 'security'

        elif form_type == 'notifications':
            notification_form = NotificationSettingsForm(request.POST, instance=user)
            if notification_form.is_valid():
                notification_form.save()
                messages.success(request, 'Your notification preferences have been saved.')
                return redirect('account_settings')
            else:
                active_tab = 'notifications'

    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'notification_form': notification_form,
        'delete_form': delete_form,
        'active_tab': active_tab,
    }
    return render(request, 'account_settings.html', context)


@login_required
def delete_account_view(request):
    """
    Handles the actual account deletion after explicit text confirmation.
    """
    if request.method == 'POST':
        form = AccountDeleteConfirmationForm(request.POST)
        user = request.user

        if form.is_valid():
            # The form is valid only if the user typed 'DELETE' correctly.
            # We can now proceed with permanent deletion.
            user.delete()
            logout(request)
            messages.success(request, 'Your account and all associated data have been permanently deleted.')
            return redirect('home')
        else:
            # The user did not type 'DELETE' correctly.
            # The form error will be stored in form.errors
            error_message = form.errors.get('confirmation_text', ['Confirmation failed.'])[0]
            messages.error(request, error_message)
            return redirect('account_settings')
    
    return redirect('account_settings')

@login_required
def resend_certificate_view(request, enrollment_id):
    """
    Handles a request to re-send a completion certificate via email.
    """
    if request.method == 'POST':
        enrollment = get_object_or_404(Enrollment, id=enrollment_id, student=request.user)
        
        if enrollment.get_progress_percentage >= 100:
            try:
                send_completion_certificate_email(enrollment)
                return JsonResponse({'status': 'success', 'message': f"Your certificate for '{enrollment.course.title}' has been sent to your email."})
            except Exception as e:
                import traceback
                traceback.print_exc()
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        else:
            return JsonResponse({'status': 'error', 'message': 'You have not completed this course yet.'}, status=400)
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)


def for_business_view(request):
    """
    Displays the 'For Business' pricing page with available subscription plans.
    """
    plans = SubscriptionPlan.objects.all().order_by('price')
    context = {'plans': plans}
    return render(request, 'business/for_business.html', context)


@login_required
def team_setup_view(request):
    """
    Allows a new team owner to provide their business details.
    This view creates the team, activates the subscription, grants course access,
    and sends the confirmation email.
    """
    plan_id = request.session.get('pending_subscription_plan_id')
    
    # Security: If the user hasn't just completed a payment, they cannot access this page.
    if not plan_id:
        messages.error(request, "No pending subscription found. Please choose a plan to continue.")
        return redirect('for_business')

    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    
    if request.method == 'POST':
        form = TeamCreationForm(request.POST)
        if form.is_valid():
            team, created = Team.objects.get_or_create(
                owner=request.user,
                defaults={'name': form.cleaned_data['name']}
            )
            
            # Update team details from the form
            team.name = form.cleaned_data['name']
            team.phone_number = form.cleaned_data['phone_number']
            team.address = form.cleaned_data['address']
            
            # Activate or Renew the subscription
            team.plan = plan
            team.is_active = True
            team.subscription_ends = timezone.now() + datetime.timedelta(days=30)
            team.save()
            
            # Grant all-access to existing team members
            team.grant_all_members_course_access()
            send_subscription_confirmation_email(team)
            
            # Clean up the session variable
            del request.session['pending_subscription_plan_id']

            messages.success(request, f"Welcome! Your team '{team.name}' has been created successfully.")
            return redirect('team_dashboard')
    else:
        form = TeamCreationForm()

    context = {'form': form, 'plan': plan}
    return render(request, 'business/team_setup.html', context)



@login_required
def team_dashboard_view(request):
    """
    Displays the management dashboard and handles inviting/adding members.
    """
    try:
        team = request.user.owned_team
    except Team.DoesNotExist:
        messages.error(request, "You do not have a team dashboard. Contact sales to get started.")
        return redirect('for_business')

    if request.method == 'POST':
        email_to_add = request.POST.get('email', '').strip()
        if email_to_add:
            # First, check if the team's subscription is active and has space
            if not team.is_active:
                 messages.error(request, "Your team's subscription is inactive. Please renew to add members.")
                 return redirect('team_dashboard')
            if team.members.count() >= team.plan.max_members:
                messages.error(request, f"You have reached the maximum of {team.plan.max_members} members for your plan.")
                return redirect('team_dashboard')

            # Use get_or_create to either find an existing user or create a new one
            user_to_add, created = CustomUser.objects.get_or_create(
                email__iexact=email_to_add,
                defaults={'email': email_to_add.lower()}
            )

            if user_to_add == team.owner:
                messages.warning(request, "You cannot add the team owner as a member.")
            elif user_to_add in team.members.all():
                 messages.warning(request, f"{user_to_add.get_full_name() or user_to_add.email} is already a member of your team.")
            else:
                if created:
                    # This is a brand new user. Set them up for invitation.
                    user_to_add.set_unusable_password()
                    user_to_add.is_active = True # B2B users are active by default
                    user_to_add.is_verified = True # B2B users are implicitly verified
                    user_to_add.is_invited = True
                    user_to_add.save()
                    
                    # Send them an invitation email to set their password
                    send_team_invitation_email(request, user_to_add, team)
                    messages.success(request, f"An invitation has been sent to {user_to_add.email}.")
                else:
                    messages.success(request, f"Successfully added existing user {user_to_add.get_full_name() or user_to_add.email} to your team.")
                
                # Add user to the team and grant access
                team.members.add(user_to_add)
                user_to_add.is_b2b_member = True
                user_to_add.save()
                team.grant_all_members_course_access()

        else:
            messages.error(request, "Please provide an email address.")
        
        return redirect('team_dashboard')
    
    # Fetch all members and their related enrollments efficiently
    members = team.members.all().prefetch_related('enrollments__course', 'enrollments__completed_lessons')
    all_enrollments = Enrollment.objects.filter(student__in=members)

    # Calculate the overall average progress percentage for the team
    total_progress = 0
    if all_enrollments.exists():
        for enrollment in all_enrollments:
            total_progress += enrollment.get_progress_percentage
        average_progress = total_progress / all_enrollments.count()
    else:
        average_progress = 0
        
    seat_usage_percentage = 0
    if team.plan and team.plan.max_members > 0:
        seat_usage_percentage = (team.members.count() / team.plan.max_members) * 100
    
    context = {
        'team': team,
        'seat_usage_percentage': seat_usage_percentage,
        'members': members,
        'average_progress': average_progress,
    }
    return render(request, 'business/team_dashboard.html', context)


@login_required
def remove_team_member_view(request, member_id):
    """
    Removes a member from the logged-in user's team.
    """
    try:
        team = request.user.owned_team
        member_to_remove = get_object_or_404(CustomUser, id=member_id)
        
        if member_to_remove in team.members.all():
            team.members.remove(member_to_remove)
            messages.success(request, f"{member_to_remove.get_full_name()} has been removed from your team.")
        else:
            messages.error(request, "This user is not a member of your team.")

    except Team.DoesNotExist:
        messages.error(request, "You do not have a team to manage.")
    
    return redirect('team_dashboard')

@superuser_required
def plan_management_view(request):
    """
    Displays the plan management page and handles AJAX creation of new plans.
    """
    plans = SubscriptionPlan.objects.all().order_by('price')
    form = SubscriptionPlanForm()

    if request.method == 'POST': # Handles AJAX POST for creating a new plan
        form = SubscriptionPlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            # Render just the new table row to be inserted by JavaScript
            html = render_to_string('partials/plan_list_item.html', {'plan': plan})
            return JsonResponse({'status': 'success', 'html': html})
        else:
            return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

    context = {'plans': plans, 'form': form}
    return render(request, 'admin/plan_management.html', context)

@superuser_required
def plan_detail_view(request, plan_id):
    """
    API endpoint to get the details of a single plan for editing.
    """
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    data = {
        'name': plan.name,
        'price': str(plan.price),
        'max_members': plan.max_members,
        'description': plan.description or '',
        'features': plan.features or '',
    }
    return JsonResponse(data)


@superuser_required
def plan_update_view(request, plan_id):
    """
    Handles AJAX POST for updating an existing subscription plan.
    """
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    if request.method == 'POST':
        form = SubscriptionPlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            # Render the updated table row to replace the old one
            html = render_to_string('partials/plan_list_item.html', {'plan': plan})
            return JsonResponse({'status': 'success', 'html': html, 'plan_id': plan.id})
        else:
            return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    return JsonResponse({'status': 'error'}, status=405)


@superuser_required
def plan_delete_view(request, plan_id):
    """
    Handles AJAX POST for deleting a subscription plan.
    """
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    if request.method == 'POST':
        # Add a check to prevent deleting a plan that is in use
        if Team.objects.filter(plan=plan).exists():
            return JsonResponse({'status': 'error', 'message': 'This plan is currently assigned to one or more teams and cannot be deleted.'}, status=400)
        plan.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=405)


@login_required
def initiate_team_subscription_view(request, plan_id):
    """
    Handles the start of a B2B subscription process.
    """
    if hasattr(request.user, 'owned_team'):
        messages.warning(request, "You already manage a team. You cannot subscribe to a new plan.")
        return redirect('team_dashboard')

    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    reference = f"ERUDIO-SUB-{request.user.id}-{plan.id}-{uuid.uuid4().hex[:10].upper()}"
    paystack = PaystackAPI()
    
    # Add plan_id to the callback URL so we know what was paid for
    callback_url = request.build_absolute_uri(
        f"{reverse('verify_team_subscription')}?plan_id={plan.id}"
    )
    amount_in_kobo = int(plan.price * 100)

    api_response = paystack.initialize_transaction(request.user.email, amount_in_kobo, reference, callback_url)

    if api_response and api_response.get('status'):
        return redirect(api_response['data']['authorization_url'])
    else:
        messages.error(request, "We couldn't connect to the payment gateway. Please try again later.")
        return redirect('for_business')


@login_required
def verify_team_subscription_view(request):
    """
    Handles the callback from Paystack. Verifies payment and redirects to the team setup page.
    """
    reference = request.GET.get('reference')
    plan_id = request.GET.get('plan_id')
    
    if not reference or not plan_id:
        messages.error(request, "Invalid subscription verification link.")
        return redirect('for_business')

    paystack = PaystackAPI()
    api_response = paystack.verify_transaction(reference)

    if api_response and api_response.get('data') and api_response['data']['status'] == 'success':
        # Payment is successful. Store the plan_id in the session
        # and redirect the user to the final setup step.
        request.session['pending_subscription_plan_id'] = plan_id
        
        return redirect('team_setup')
    else:
        messages.error(request, "Payment verification failed. Please try again or contact support if you were debited.")
        return redirect('for_business')