from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *

# --- INLINES FOR A BETTER ADMIN EXPERIENCE ---

class ModuleInline(admin.TabularInline):
    """Allows editing modules directly within the course admin page."""
    model = Module
    extra = 1
    prepopulated_fields = {} # No slug here
    
class LessonInline(admin.TabularInline):
    """Allows editing lessons directly within the module admin page."""
    model = Lesson
    extra = 1
    prepopulated_fields = {'slug': ('title',)}


# --- MODELADMIN CONFIGURATIONS ---

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Customizes the admin interface for the CustomUser model."""
    model = CustomUser
    list_display = ('email', 'first_name', 'last_name', 'is_staff', 'is_instructor', 'is_verified', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'is_instructor', 'groups')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'is_instructor', 'is_verified', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    # This remains the same, but it's good practice to be explicit
    add_fieldsets = UserAdmin.add_fieldsets


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    """Customizes the admin interface for EmailVerificationToken."""
    list_display = ('user', 'id', 'created_at', 'is_expired')
    search_fields = ('user__email',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Customizes the admin interface for Category."""
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'instructor', 'display_categories', 'price', 'is_paid', 'is_published', 'created_at')
    list_filter = ('is_paid', 'is_published', 'category', 'instructor') # Corrected field name
    search_fields = ('title', 'short_description', 'long_description')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ModuleInline]
    list_editable = ('is_published', 'is_paid')
    
    def display_categories(self, obj):
        """Creates a string for the categories. This is required for ManyToMany fields."""
        return ", ".join([category.name for category in obj.category.all()])
    display_categories.short_description = 'Categories' # Sets column header name


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    """Customizes the admin interface for Module."""
    list_display = ('title', 'course', 'order')
    list_filter = ('course',)
    search_fields = ('title',)
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    """Customizes the admin interface for Lesson."""
    list_display = ('title', 'module', 'order', 'slug')
    list_filter = ('module__course',)
    search_fields = ('title',)
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    """Customizes the admin interface for Enrollment."""
    list_display = ('student', 'course', 'enrolled_at', 'get_progress_percentage')
    search_fields = ('student__email', 'course__title')
    list_filter = ('course',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Customizes the admin interface for Transaction."""
    list_display = ('student', 'course', 'reference', 'amount', 'status', 'created_at')
    list_filter = ('status', 'course')
    search_fields = ('student__email', 'reference')
    readonly_fields = ('created_at',)

