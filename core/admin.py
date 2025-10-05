from django.contrib import admin
from .models import ClassRoom, Assignment, Absence

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