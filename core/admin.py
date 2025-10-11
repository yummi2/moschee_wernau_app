from django.contrib import admin
from .models import ClassRoom, Assignment, Absence, ChecklistItem, StudentChecklist
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import WeeklyBanner

User = get_user_model()
@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    filter_horizontal = ("teachers", "students")

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "due_at", "created_by", "created_at")
    list_filter = ("classroom",)
    search_fields = ("title",)


@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "marked_at")

@admin.register(ChecklistItem)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'order')
    list_editable = ('order',)
    list_display_links = ('title',)
    search_fields = ('title',)
    ordering = ('order', 'id')
    filter_horizontal = ('classrooms',)

@admin.register(StudentChecklist)
class StudentChecklistAdmin(admin.ModelAdmin):
    list_display = ('student', 'item', 'checked')
    list_filter = ('checked',)
    search_fields = ('student__username', 'item__title')
    list_display_links = ('student', 'item')

    def get_queryset(self, request):
        """Nur die Schüler zeigen, die vom Lehrer unterrichtet werden."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs

        # Alle Schüler-IDs aus Klassen, in denen der User Lehrer ist
        student_ids = (ClassRoom.objects
                       .filter(teachers=request.user)
                       .values_list('students__id', flat=True))
        return qs.filter(student_id__in=student_ids).distinct()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Auswahlfelder im Formular auf erlaubte Schüler/Items einschränken,
        damit ein Lehrer keine fremden Schüler/Items auswählen kann.
        """
        if not request.user.is_superuser:
            if db_field.name == 'student':
                kwargs['queryset'] = (User.objects
                    .filter(classes_as_student__teachers=request.user)
                    .distinct())
            if db_field.name == 'item':
                # Items, die für mind. eine Klasse des Lehrers gelten
                teacher_class_ids = (ClassRoom.objects
                                     .filter(teachers=request.user)
                                     .values_list('id', flat=True))
                kwargs['queryset'] = (ChecklistItem.objects
                    .filter(
                        Q(classrooms__id__in=teacher_class_ids) |
                        Q(classrooms__isnull=True)  # falls du „globale“ Items hast
                    )
                    .distinct())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # Harter Sicherheitsgurt: Änderungen nur, wenn der Datensatz im erlaubten Scope liegt
    def has_change_permission(self, request, obj=None):
        base = super().has_change_permission(request, obj)
        if not base or request.user.is_superuser or obj is None:
            return base
        return ClassRoom.objects.filter(teachers=request.user, students=obj.student).exists()

    def has_delete_permission(self, request, obj=None):
        base = super().has_delete_permission(request, obj)
        if not base or request.user.is_superuser or obj is None:
            return base
        return ClassRoom.objects.filter(teachers=request.user, students=obj.student).exists()

@admin.register(WeeklyBanner)
class WeeklyBannerAdmin(admin.ModelAdmin):
    list_display = ("image_url", "updated_at")