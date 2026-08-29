import datetime as dt

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .school_years import can_switch_school_years
from .views import selected_school_year_ranges


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

# Create your tests here.
