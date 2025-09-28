from django.contrib import admin
from .models import ClassRoom, Assignment, Submission

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

@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "submitted_at", "grade")
    list_filter = ("assignment", "grade")
    search_fields = ("student__username",)
