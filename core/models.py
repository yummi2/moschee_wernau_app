from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
import os
from django.core.exceptions import ValidationError

class ClassRoom(models.Model):
    name = models.CharField(max_length=120)
    teachers = models.ManyToManyField(User, related_name="classes_as_teacher", blank=True)
    students = models.ManyToManyField(User, related_name="classes_as_student", blank=True)

    def __str__(self):
        return self.name

class Assignment(models.Model):
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name="assignments")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments_created")
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.URLField("Link", blank=True, null=True)
    def __str__(self):
        return f"{self.title} ({self.classroom})"

class Profile(models.Model):
    user   = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_teacher = models.BooleanField(default=False)
    classroom = models.ForeignKey(
        ClassRoom, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="profiles"
    )
    # String 'Group' verwenden, weil die Klasse weiter unten definiert ist
    groups = models.ManyToManyField('Group', blank=True, related_name="profiles")

    def __str__(self):
        return f"Profile({self.user.username})"

    def save(self, *args, **kwargs):
        old_path = None
        if self.pk:  # Falls das Profil schon existiert
            try:
                old = Profile.objects.get(pk=self.pk)
                if old.avatar and old.avatar != self.avatar:
                    old_path = old.avatar.path
            except Profile.DoesNotExist:
                pass

        super().save(*args, **kwargs)  # Neues Bild speichern

        # Altes Bild löschen
        if old_path and os.path.isfile(old_path):
            os.remove(old_path)

class Absence(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()  # der angeklickte Tag (der lila Samstag)
    marked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "date")  # pro User/Tag nur einmal        

class Group(models.Model):
    name = models.CharField(max_length=100, unique=True)
    classroom = models.ForeignKey('ClassRoom', null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='groups')

    def __str__(self):
        return self.name    

class ChecklistItem(models.Model):
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    # Sichtbarkeit: nur für diese Klassen. Wenn leer -> für alle Klassen sichtbar.
    classrooms = models.ManyToManyField('ClassRoom', blank=True, related_name='checklist_items')

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

class StudentChecklist(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='checkmarks')
    item    = models.ForeignKey(ChecklistItem, on_delete=models.CASCADE, related_name='checkmarks')
    checked = models.BooleanField(default=False)

    class Meta:
        unique_together = ('student', 'item')   

class WeeklyBanner(models.Model):
    # wir halten nur die aktuell gültige URL
    image_url = models.URLField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Banner ({self.updated_at:%Y-%m-%d %H:%M})" 

class TeacherNote(models.Model):
    teacher   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes_written")
    student   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes_received")
    classroom = models.ForeignKey("ClassRoom", on_delete=models.SET_NULL, null=True, blank=True)
    body      = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note to {self.student} by {self.teacher} @ {self.created_at:%Y-%m-%d}" 

class StoryRead(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="story_reads")
    level = models.CharField(max_length=32)   
    sid   = models.CharField(max_length=32)  
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "level", "sid")  # idempotent
        indexes = [
            models.Index(fields=["user", "level", "sid"]),
        ]

    def __str__(self):
        return f"{self.user} read {self.level}:{self.sid}"     


PRAYERS = [
    (1, "الفجر"),
    (2, "الظهر"),
    (3, "العصر"),
    (4, "المغرب"),
    (5, "العشاء"),
]

class PrayerStatus(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    prayer = models.IntegerField(choices=PRAYERS)
    prayed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "date", "prayer")

class RamadanItemDone(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    day = models.IntegerField()
    item_key = models.CharField(max_length=50)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    

    class Meta:
        unique_together = ("user", "day", "item_key")



class QuizScore(models.Model):
    QUIZ_TYPES = [
        ("islam", "Islam"),
        ("fiqh", "Fiqh"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quiz_type = models.CharField(max_length=20, choices=QUIZ_TYPES)

    # optional: falls du 5er-Seiten hast
    page = models.PositiveIntegerField(default=1)

    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["quiz_type", "user", "submitted_at"]),
        ]

    def __str__(self):
        return f"{self.user} {self.quiz_type} p{self.page}: {self.score}/{self.total}"
