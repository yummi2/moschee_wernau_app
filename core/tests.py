import datetime as dt

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .school_years import can_switch_school_years
from .views import selected_school_year_ranges
from .models import Assignment, AssignmentCompletion, AssignmentReminderDelivery, ClassRoom


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
