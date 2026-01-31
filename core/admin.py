from django.contrib import admin
from .models import ClassRoom, Assignment, Absence, ChecklistItem, StudentChecklist, WeeklyBanner, TeacherNote, StoryRead, PrayerStatus, RamadanItemDone, QuizScore
from django.contrib.auth import get_user_model
from django.db.models import Q
from .views import STORIES

User = get_user_model()
@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    filter_horizontal = ("teachers", "students")

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "due_at", "created_by", "created_at", 
    "link")
    list_filter = ("classroom",)
    search_fields = ("title","link")
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "created_by":
            # Nur Benutzer aus der Gruppe "Lehrer" anzeigen
            kwargs["queryset"] = User.objects.filter(groups__name="Lehrer")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "marked_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "sid")

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

@admin.register(TeacherNote)
class TeacherNoteAdmin(admin.ModelAdmin):
    list_display = ("student", "teacher", "classroom", "created_at", "short_body")
    search_fields = ("student__username", "teacher__username", "body")
    list_filter = ("teacher", "classroom", "created_at")
    exclude = ("teacher",)
    date_hierarchy = "created_at"

    # verkürzte Body-Spalte
    def short_body(self, obj):
        return (obj.body or "")[:60]
    short_body.short_description = "Body"

    # Nicht-Superuser: Auswahl einschränken
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if db_field.name == "student":
                kwargs["queryset"] = User.objects.filter(
                    classes_as_student__teachers=request.user
                ).distinct()
            if db_field.name == "classroom":
                kwargs["queryset"] = ClassRoom.objects.filter(
                    teachers=request.user
                ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # teacher automatisch auf den eingeloggten Benutzer setzen
    def save_model(self, request, obj, form, change):
        if not obj.teacher_id:
            obj.teacher = request.user
        super().save_model(request, obj, form, change)

    # Superuser: alle Notizen; sonst nur eigene
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(teacher=request.user)

@admin.register(StoryRead)
class StoryReadAdmin(admin.ModelAdmin):
    list_display = ("user", "story_title", "read_at")
    list_filter = ("level",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "sid")
    autocomplete_fields = ("user",)

    def story_title(self, obj):
        story = STORIES.get(obj.level, {}).get(obj.sid)
        return story["title"] if story else f"{obj.level}:{obj.sid}"

    story_title.short_description = "Story Titel"

@admin.register(PrayerStatus)
class PrayerStatusAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "prayer", "prayed")
    list_filter = ("date", "prayer", "prayed")
    search_fields = ("user__username",)

@admin.register(RamadanItemDone)
class RamadanItemDoneAdmin(admin.ModelAdmin):
    list_display = ("user", "day", "item_key", "done")
    list_filter = ("day", "item_key", "done")
    search_fields = ("user__username",)

@admin.register(QuizScore)
class QuizScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "quiz_type", "page", "score", "total", "submitted_at")
    list_filter = ("quiz_type", "page", "submitted_at")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs

        # Lehrer sieht nur Schüler aus seinen Klassen
        student_ids = (ClassRoom.objects
                       .filter(teachers=request.user)
                       .values_list("students__id", flat=True))
        return qs.filter(user_id__in=student_ids).distinct()