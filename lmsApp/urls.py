from django.urls import path
from . import views

urlpatterns = [
    # --- CORE & AUTHENTICATION URLs ---
    path('', views.home_view, name='home'),
    path('accounts/register/', views.register_view, name='register'),
    path('accounts/login/', views.login_view, name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),
    path('accounts/verify-email/<uuid:token>/', views.verify_email_view, name='verify_email'),

    # --- COURSE CATALOG & STUDENT EXPERIENCE URLs ---
    path('courses/', views.course_list_view, name='course_list'),
    path('course/<slug:slug>/', views.course_detail_view, name='course_detail'),
    path('dashboard/my-courses/', views.my_courses_view, name='my_courses'),
    path('course/<slug:course_slug>/learn/<slug:lesson_slug>/', views.lesson_detail_view, name='lesson_detail'),
    path('course/<slug:course_slug>/learn/<slug:lesson_slug>/complete/', views.mark_lesson_complete_view, name='mark_lesson_complete'),

    # --- PAYMENT FLOW URLs ---
    path('course/<slug:slug>/payment/initiate/', views.initiate_payment_view, name='initiate_payment'),
    path('payment/verify/', views.verify_payment_view, name='verify_payment'),

    # --- INSTRUCTOR DASHBOARD & MANAGEMENT URLs ---
    path('instructor/dashboard/', views.instructor_dashboard_view, name='instructor_dashboard'),
    path('instructor/analytics/', views.instructor_analytics_view, name='instructor_analytics'),
    path('instructor/course/create/', views.course_create_view, name='course_create'),
    path('instructor/course/<slug:slug>/update/', views.course_update_view, name='course_update'),
    path('instructor/course/<slug:slug>/manage/', views.course_manage_view, name='course_manage'),

    # --- AJAX API URLs for COURSE MANAGEMENT ---
    path('instructor/api/module/create/<slug:course_slug>/', views.module_create_view, name='module_create'),
    path('instructor/api/module/update/<int:module_id>/', views.module_update_view, name='module_update'),
    path('instructor/api/module/delete/<int:module_id>/', views.module_delete_view, name='module_delete'),
    path('instructor/api/lesson/create/<int:module_id>/', views.lesson_create_view, name='lesson_create'),
    path('instructor/api/lesson/update/<int:lesson_id>/', views.lesson_update_view, name='lesson_update'),
    path('instructor/api/lesson/delete/<int:lesson_id>/', views.lesson_delete_view, name='lesson_delete'),

    # --- AJAX API URLs for CATEGORY MANAGEMENT ---
    path('instructor/api/category/create/', views.category_create_view, name='category_create'),
    path('instructor/api/category/delete/<int:category_id>/', views.category_delete_view, name='category_delete'),

    # --- ACCOUNT SETTINGS URLs ---
    path('account/settings/', views.account_settings_view, name='account_settings'),
    path('account/delete/', views.delete_account_view, name='delete_account'),

    # --- CERTIFICATE URL ---
    path('enrollment/<int:enrollment_id>/send-certificate/', views.resend_certificate_view, name='send_certificate'),

    # --- "ERUDIO FOR BUSINESS" URLs ---
    path('business/', views.for_business_view, name='for_business'),
    path('business/subscribe/<int:plan_id>/', views.initiate_team_subscription_view, name='initiate_team_subscription'),
    path('business/verify-subscription/', views.verify_team_subscription_view, name='verify_team_subscription'),
    path('business/setup-team/', views.team_setup_view, name='team_setup'),
    path('team/dashboard/', views.team_dashboard_view, name='team_dashboard'),
    path('team/remove-member/<int:member_id>/', views.remove_team_member_view, name='remove_team_member'),

    # --- SUPER ADMIN URLs ---
    path('dashboard/', views.super_admin_dashboard_view, name='super_admin_dashboard'),
    path('plans/', views.plan_management_view, name='plan_management'),
    path('api/plans/<int:plan_id>/', views.plan_detail_view, name='plan_detail'),
    path('api/plans/<int:plan_id>/update/', views.plan_update_view, name='plan_update'),
    path('api/plans/<int:plan_id>/delete/', views.plan_delete_view, name='plan_delete'),
]

