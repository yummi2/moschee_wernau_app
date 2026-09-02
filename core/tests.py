import datetime as dt

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .school_years import can_switch_school_years
from .views import selected_school_year_ranges
from .models import (
    Assignment,
    AssignmentCompletion,
    AssignmentReminderDelivery,
    ClassRoom,
    PrayerStatus,
    RamadanItemDone,
)


class SchoolYearAccessTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_model = get_user_model()

    def make_user(self, username, joined_on):
        user = self.user_model.objects.create_user(username=username, password="test-pass")
        joined_at = timezone.make_aware(dt.datetime.combine(joined_on, dt.time(12)))
        self.user_model.objects.filter(pk=user.pk).update(date_joined=joined_at)
        user.refresh_from_db()
        return user

    def test_existing_account_can_switch_years(self):
        user = self.make_user("existing", dt.date(2026, 8, 29))
        self.assertTrue(can_switch_school_years(user))

    def test_new_account_is_forced_to_2027(self):
        user = self.make_user("new", dt.date(2026, 8, 30))
        request = self.factory.get("/")
        request.user = user
        request.session = {"school_year": "2026"}

        self.assertFalse(can_switch_school_years(user))
        self.assertEqual(selected_school_year_ranges(request)["year"], "2027")
        self.assertEqual(request.session["school_year"], "2027")


class LibraryTranslationTests(TestCase):
    def test_library_uses_content_specific_german_titles(self):
        beginner = self.client.get(reverse("library"), {"level": "beginner"})
        intermediate = self.client.get(reverse("library"), {"level": "intermediate"})

        self.assertContains(beginner, 'data-app-de="Satz 1"')
        self.assertContains(intermediate, 'data-app-de="Nur und der Besuch bei ihrer Großmutter"')

    def test_beginner_story_heading_has_german_title(self):
        response = self.client.get(reverse("library"), {"level": "beginner", "sid": "1"})
        self.assertContains(response, 'data-app-de="Satz 1"')


class AdminStatisticsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            "admin", password="x", is_staff=True,
        )
        get_user_model().objects.filter(pk=self.admin.pk).update(
            date_joined=timezone.make_aware(dt.datetime(2026, 8, 1, 12, 0))
        )
        self.admin.refresh_from_db()
        self.first_student = get_user_model().objects.create_user("student-a", password="x")
        self.second_student = get_user_model().objects.create_user("student-b", password="x")

    def test_non_staff_user_cannot_open_statistics(self):
        self.client.force_login(self.first_student)
        response = self.client.get(reverse("admin_statistics"))
        self.assertEqual(response.status_code, 403)

    def test_rankings_prioritize_complete_ramadan_days_and_weekly_prayers(self):
        item_keys = ["fasting", "athkar", "duaa", "quran", "hadith", "tarawih_witr", "good_deed"]
        for item_key in item_keys:
            RamadanItemDone.objects.create(
                user=self.first_student,
                day=1,
                item_key=item_key,
                school_year="2026",
                done=True,
            )
        for item_key in item_keys[:5]:
            RamadanItemDone.objects.create(
                user=self.second_student,
                day=1,
                item_key=item_key,
                school_year="2026",
                done=True,
            )

        today = timezone.localdate()
        week_start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
        for prayer in range(1, 4):
            PrayerStatus.objects.create(
                user=self.second_student,
                date=week_start,
                prayer=prayer,
                prayed=True,
            )
        PrayerStatus.objects.create(
            user=self.first_student,
            date=week_start,
            prayer=1,
            prayed=True,
        )

        self.client.force_login(self.admin)
        session = self.client.session
        session["school_year"] = "2026"
        session.save()
        response = self.client.get(reverse("admin_statistics"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ramadan_ranking"][0]["user"], self.first_student)
        self.assertEqual(response.context["ramadan_ranking"][0]["completed_days"], 1)
        self.assertEqual(response.context["prayer_ranking"][0]["user"], self.second_student)
        self.assertEqual(response.context["prayer_ranking"][0]["completed_prayers"], 3)

    def test_teacher_sees_only_assignments_from_own_class(self):
        teacher = get_user_model().objects.create_user(
            "teacher-stats", password="x", is_staff=True,
        )
        other_teacher = get_user_model().objects.create_user("other-teacher", password="x")
        own_class = ClassRoom.objects.create(name="Eigene Klasse")
        other_class = ClassRoom.objects.create(name="Andere Klasse")
        own_class.teachers.add(teacher)
        other_class.teachers.add(other_teacher)
        own_class.students.add(self.first_student)
        other_class.students.add(self.second_student)
        own_assignment = Assignment.objects.create(
            classroom=own_class,
            title="Eigene Aufgabe",
            due_at=timezone.now() + dt.timedelta(days=1),
            created_by=teacher,
        )
        Assignment.objects.create(
            classroom=own_class,
            title="Aufgabe eines Kollegen in derselben Klasse",
            due_at=timezone.now() + dt.timedelta(days=1),
            created_by=other_teacher,
        )
        Assignment.objects.create(
            classroom=other_class,
            title="Fremde Aufgabe",
            due_at=timezone.now() + dt.timedelta(days=1),
            created_by=other_teacher,
        )
        AssignmentCompletion.objects.create(user=self.first_student, assignment=own_assignment)

        self.client.force_login(teacher)
        response = self.client.get(reverse("admin_statistics"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_admin_statistics"])
        self.assertEqual(len(response.context["assignment_rows"]), 1)
        self.assertEqual(response.context["assignment_rows"][0]["assignment"], own_assignment)
        self.assertEqual(response.context["assignment_rows"][0]["completed_students"][0]["user"], self.first_student)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertTemplateUsed(home_response, "core/admin_statistics.html")
        self.assertContains(home_response, "Aufgabe eines Kollegen", count=0)

    def test_teacher_can_see_both_rankings(self):
        teacher = get_user_model().objects.create_user("teacher-ranking", password="x", is_staff=True)
        classroom = ClassRoom.objects.create(name="Ranking-Klasse")
        classroom.teachers.add(teacher)
        RamadanItemDone.objects.create(
            user=self.first_student, day=1, item_key="quran", school_year="2027", done=True,
        )
        PrayerStatus.objects.create(
            user=self.first_student, date=timezone.localdate(), prayer=1, prayed=True,
        )

        self.client.force_login(teacher)
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ramadan_ranking"][0]["user"], self.first_student)
        self.assertEqual(response.context["prayer_ranking"][0]["user"], self.first_student)

    def test_ramadan_ranking_uses_sidebar_year_and_prayer_period_can_switch(self):
        RamadanItemDone.objects.create(
            user=self.first_student,
            day=1,
            item_key="quran",
            school_year="2027",
            done=True,
        )
        today = timezone.localdate()
        PrayerStatus.objects.create(
            user=self.first_student,
            date=today,
            prayer=1,
            prayed=True,
        )

        self.client.force_login(self.admin)
        session = self.client.session
        session["school_year"] = "2027"
        session.save()
        response = self.client.get(reverse("admin_statistics"), {"prayer_period": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ramadan_year"], "2027")
        self.assertEqual(response.context["prayer_period"], "month")
        self.assertEqual(response.context["ramadan_ranking"][0]["completed_items"], 1)
        self.assertEqual(response.context["prayer_ranking"][0]["completed_prayers"], 1)

    def test_assignment_tracking_is_hidden_for_2026(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["school_year"] = "2026"
        session.save()

        response = self.client.get(reverse("admin_statistics"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_assignment_tracking"])
        self.assertNotContains(response, 'class="assignment-tracking"')


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AssignmentReminderTests(TestCase):
    def test_shared_email_receives_one_bundled_message_without_duplicates(self):
        teacher = get_user_model().objects.create_user("teacher", password="x")
        first = get_user_model().objects.create_user("child1", email="family@example.com", password="x")
        second = get_user_model().objects.create_user("child2", email="family@example.com", password="x")
        classroom = ClassRoom.objects.create(name="7A")
        classroom.students.add(first, second)
        send_date = dt.date(2026, 9, 10)
        due_at = timezone.make_aware(dt.datetime(2026, 9, 11, 16, 0))
        first_assignment = Assignment.objects.create(
            classroom=classroom, title="Aufgabe A", due_at=due_at, created_by=teacher,
        )
        second_assignment = Assignment.objects.create(
            classroom=classroom, title="Aufgabe B", due_at=due_at, created_by=teacher,
        )
        AssignmentCompletion.objects.create(user=first, assignment=second_assignment)

        call_command("send_assignment_reminders", date=send_date.isoformat())

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["family@example.com"])
        self.assertIn("child1: Aufgabe A", mail.outbox[0].body)
        self.assertIn("child2: Aufgabe A", mail.outbox[0].body)
        self.assertIn("child2: Aufgabe B", mail.outbox[0].body)
        self.assertNotIn("child1: Aufgabe B", mail.outbox[0].body)
        self.assertEqual(AssignmentReminderDelivery.objects.count(), 3)

        call_command("send_assignment_reminders", date=send_date.isoformat())
        self.assertEqual(len(mail.outbox), 1)
