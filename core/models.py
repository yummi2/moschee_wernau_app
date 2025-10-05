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
    due_at = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments_created")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.classroom})"

class Profile(models.Model):
    user   = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

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