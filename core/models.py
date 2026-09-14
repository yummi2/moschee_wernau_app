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


class AssignmentCompletion(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="assignment_completions",
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="completions",
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "assignment"),
                name="unique_assignment_completion",
            ),
        ]

    def __str__(self):
        return f"{self.user} – {self.assignment}"

class AssignmentReminderDelivery(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignment_reminders")
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="reminder_deliveries")
    recipient_email = models.EmailField()
    due_at = models.DateTimeField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "assignment", "due_at"),
                name="unique_assignment_due_reminder",
            ),
        ]

    def __str__(self):
        return f"{self.recipient_email}: {self.assignment}"


class TeacherPointAward(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="teacher_point_awards",
    )
    teacher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="points_awarded",
    )
    points = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def clean(self):
        if self.points < 1:
            raise ValidationError({"points": "Die Punktzahl muss mindestens 1 sein."})

    def __str__(self):
        return f"{self.student}: +{self.points} ({self.teacher})"


class LiveCompetition(models.Model):
    title = models.CharField(max_length=180)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="live_competitions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return self.title


class LiveCompetitionQuestion(models.Model):
    CORRECT_OPTIONS = [(number, f"Antwort {number}") for number in range(1, 5)]

    competition = models.ForeignKey(
        LiveCompetition, on_delete=models.CASCADE, related_name="questions"
    )
    text = models.TextField("Frage")
    option_1 = models.CharField("Antwort 1", max_length=300)
    option_2 = models.CharField("Antwort 2", max_length=300)
    option_3 = models.CharField("Antwort 3", max_length=300)
    option_4 = models.CharField("Antwort 4", max_length=300)
    correct_option = models.PositiveSmallIntegerField(choices=CORRECT_OPTIONS)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    @property
    def options(self):
        return [self.option_1, self.option_2, self.option_3, self.option_4]

    @property
    def correct_text(self):
        return self.options[self.correct_option - 1]

    def __str__(self):
        return f"{self.competition}: {self.text[:55]}"


class LiveCompetitionGame(models.Model):
    STATUS_CHOICES = [
        ("live", "Läuft"),
        ("finished", "Beendet"),
    ]

    competition = models.ForeignKey(
        LiveCompetition, on_delete=models.PROTECT, related_name="games"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="live_games_created"
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="live")
    current_question_index = models.PositiveIntegerField(default=0)
    team_a_score = models.PositiveIntegerField(default=0)
    team_b_score = models.PositiveIntegerField(default=0)
    winner = models.CharField(max_length=1, blank=True, choices=[("A", "Gruppe A"), ("B", "Gruppe B")])
    winner_points_awarded = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "-id")

    def __str__(self):
        return f"{self.competition} ({self.started_at:%d.%m.%Y %H:%M})"


class LiveCompetitionParticipant(models.Model):
    game = models.ForeignKey(
        LiveCompetitionGame, on_delete=models.CASCADE, related_name="participants"
    )
    student = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="live_competition_participations"
    )
    team = models.CharField(max_length=1, choices=[("A", "Gruppe A"), ("B", "Gruppe B")])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("game", "student"), name="unique_live_game_student"),
        ]

    def __str__(self):
        return f"{self.student} – Gruppe {self.team}"


class LiveCompetitionAnswer(models.Model):
    game = models.ForeignKey(
        LiveCompetitionGame, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(
        LiveCompetitionQuestion, on_delete=models.PROTECT, related_name="game_answers"
    )
    team = models.CharField(max_length=1, choices=[("A", "Gruppe A"), ("B", "Gruppe B")])
    selected_option = models.PositiveSmallIntegerField(choices=LiveCompetitionQuestion.CORRECT_OPTIONS)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("game", "question"), name="unique_live_game_question_answer"),
        ]

    def __str__(self):
        return f"{self.game} – Frage {self.question_id} – Gruppe {self.team}"


class DailyQuranReading(models.Model):
    student = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="daily_quran_readings"
    )
    portion_index = models.PositiveSmallIntegerField()
    completed_on = models.DateField()
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-completed_on", "-completed_at")
        constraints = [
            models.UniqueConstraint(fields=("student", "completed_on"), name="unique_daily_quran_reading"),
            models.UniqueConstraint(fields=("student", "portion_index"), name="unique_student_quran_portion"),
        ]

    @property
    def page_number(self):
        return (self.portion_index + 1) // 2

    @property
    def half_number(self):
        return 1 if self.portion_index % 2 else 2

    def clean(self):
        if not 1 <= self.portion_index <= 1208:
            raise ValidationError({"portion_index": "Der Abschnitt muss zwischen 1 und 1208 liegen."})

    def __str__(self):
        return f"{self.student} – Seite {self.page_number}, Hälfte {self.half_number}"


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

    zeugnis_link = models.URLField(
        blank=True,
        null=True,
        verbose_name="Zeugnis 1. Schulhalbjahr"
    )

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
    created_at = models.DateTimeField(auto_now_add=True)
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
    school_year = models.CharField(max_length=4, default="2026")
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    

    class Meta:
        unique_together = ("user", "day", "item_key", "school_year")



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
