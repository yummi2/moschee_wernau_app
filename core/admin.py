from django.contrib import admin
from .models import ClassRoom, Assignment, Absence, ChecklistItem, StudentChecklist

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
