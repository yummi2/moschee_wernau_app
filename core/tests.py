import datetime as dt
import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .school_years import can_switch_school_years
from .views import selected_school_year_ranges, teaching_week_number, saturday_week_bounds
from .models import (
    Assignment,
    AssignmentCompletion,
    AssignmentReminderDelivery,
    ClassRoom,
    Profile,
    PrayerStatus,
    RamadanItemDone,
    StoryRead,
    TeacherPointAward,
    LiveCompetition,
    LiveCompetitionQuestion,
    LiveCompetitionGame,
    LiveCompetitionAnswer,
    DailyQuranReading,
    StudentPointActivity,
)
from .points import point_balance
from .ramadan_data import RAMADAN_ITEMS_ORDER


class TeachingWeekNumberTests(TestCase):
    def test_first_two_weeks_of_2027_school_year_are_numbered(self):
        self.assertEqual(
            teaching_week_number(dt.date(2026, 9, 19), dt.date(2026, 9, 25)),
            1,
        )
        self.assertEqual(
            teaching_week_number(dt.date(2026, 9, 26), dt.date(2026, 10, 2)),
            2,
        )

    def test_assignment_week_runs_from_saturday_through_friday(self):
        self.assertEqual(
            saturday_week_bounds(dt.date(2026, 9, 22)),
            (dt.date(2026, 9, 19), dt.date(2026, 9, 25)),
        )

    def test_holiday_week_has_no_teaching_week_number(self):
        self.assertIsNone(
            teaching_week_number(dt.date(2026, 10, 31), dt.date(2026, 11, 6))
        )


class LiveCompetitionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("quiz-admin", "admin@example.com", "x")
        self.students = [
            get_user_model().objects.create_user(f"quiz-child-{number}", password="x")
            for number in range(1, 5)
        ]
        self.competition = LiveCompetition.objects.create(title="Test-Wettbewerb", created_by=self.admin)
        for order in range(2):
            LiveCompetitionQuestion.objects.create(
                competition=self.competition,
                text=f"Frage {order + 1}",
                option_1="A",
                option_2="B",
                option_3="C",
                option_4="D",
                correct_option=2,
                order=order,
            )

    def test_admin_can_assign_live_teams_and_winners_receive_three_points_once(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("live_competition_start"), {
            "competition_id": self.competition.id,
            "team_a": [self.students[0].id, self.students[1].id],
            "team_b": [self.students[2].id, self.students[3].id],
        })
        game = LiveCompetitionGame.objects.get()
        self.assertRedirects(response, reverse("live_competition_game", args=[game.id]))

        self.client.post(reverse("live_competition_game", args=[game.id]), {
            "action": "answer", "team": "A", "selected_option": "2",
        })
        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "next"})
        self.client.post(reverse("live_competition_game", args=[game.id]), {
            "action": "answer", "team": "A", "selected_option": "1",
        })
        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "finish"})

        game.refresh_from_db()
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.winner, "A")
        self.assertEqual(game.team_a_score, 1)
        self.assertEqual(game.team_b_score, 0)
        self.assertEqual(TeacherPointAward.objects.count(), 4)
        awards = {award.student_id: award.points for award in TeacherPointAward.objects.all()}
        self.assertEqual(awards[self.students[0].id], 3)
        self.assertEqual(awards[self.students[1].id], 3)
        self.assertEqual(awards[self.students[2].id], 1)
        self.assertEqual(awards[self.students[3].id], 1)

        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "finish"})
        self.assertEqual(TeacherPointAward.objects.count(), 4)

    def test_student_cannot_open_live_control(self):
        self.client.force_login(self.students[0])
        response = self.client.get(reverse("live_competition_setup"))
        self.assertEqual(response.status_code, 403)

    def test_tie_awards_every_participant_two_points_once(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("live_competition_start"), {
            "competition_id": self.competition.id,
            "team_a": [self.students[0].id, self.students[1].id],
            "team_b": [self.students[2].id, self.students[3].id],
        })
        game = LiveCompetitionGame.objects.get()

        self.client.post(reverse("live_competition_game", args=[game.id]), {
            "action": "answer", "team": "A", "selected_option": "2",
        })
        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "next"})
        self.client.post(reverse("live_competition_game", args=[game.id]), {
            "action": "answer", "team": "B", "selected_option": "2",
        })
        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "finish"})

        game.refresh_from_db()
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.winner, "")
        self.assertEqual(game.team_a_score, game.team_b_score)
        self.assertEqual(TeacherPointAward.objects.count(), 4)
        self.assertTrue(all(award.points == 2 for award in TeacherPointAward.objects.all()))

        self.client.post(reverse("live_competition_game", args=[game.id]), {"action": "finish"})
        self.assertEqual(TeacherPointAward.objects.count(), 4)

    def test_answering_team_alternates_after_first_question(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("live_competition_start"), {
            "competition_id": self.competition.id,
            "team_a": [self.students[0].id, self.students[1].id],
            "team_b": [self.students[2].id, self.students[3].id],
        })
        game = LiveCompetitionGame.objects.get()
        game_url = reverse("live_competition_game", args=[game.id])

        self.client.post(game_url, {
            "action": "answer", "team": "A", "selected_option": "2",
        })
        self.client.post(game_url, {"action": "next"})
        response = self.client.get(game_url)
        self.assertEqual(response.context["answering_team"], "B")
        self.assertEqual(response.context["answering_team_name"], "صانعات الأمل")
        self.assertContains(response, "صانعات الأمل")
        self.assertNotContains(response, 'name="team"')

        self.client.post(game_url, {
            "action": "answer", "team": "A", "selected_option": "2",
        })
        second_question = self.competition.questions.order_by("order", "id")[1]
        self.assertEqual(
            LiveCompetitionAnswer.objects.get(game=game, question=second_question).team,
            "B",
        )


class DailyQuranReadingTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user("quran-student", password="x")

    def test_daily_reading_awards_one_point_only_once(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("complete_daily_quran"))
        self.assertRedirects(response, f"{reverse('home')}?tab=home&activity_saved=1")
        self.assertEqual(DailyQuranReading.objects.count(), 1)
        reading = DailyQuranReading.objects.get()
        self.assertEqual(reading.portion_index, 1)
        self.assertEqual(point_balance(self.student)["quran_points"], 0)
        self.assertEqual(point_balance(self.student)["total_points"], 0)
        self.assertEqual(StudentPointActivity.objects.get().status, "pending")

        self.client.post(reverse("complete_daily_quran"))
        self.assertEqual(DailyQuranReading.objects.count(), 1)
        self.assertEqual(point_balance(self.student)["quran_points"], 0)

    def test_unfinished_days_do_not_advance_the_half_page(self):
        DailyQuranReading.objects.create(
            student=self.student,
            portion_index=1,
            completed_on=timezone.localdate() - dt.timedelta(days=4),
        )
        self.client.force_login(self.student)
        response = self.client.get(f"{reverse('home')}?tab=home")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["daily_quran"]["page"], 1)
        self.assertEqual(response.context["daily_quran"]["half"], 2)
        self.assertFalse(response.context["daily_quran"]["completed_today"])

    def test_admin_overview_contains_students_latest_half_page(self):
        admin = get_user_model().objects.create_superuser("quran-admin", "admin@example.com", "x")
        reading = DailyQuranReading.objects.create(
            student=self.student,
            portion_index=3,
            completed_on=timezone.localdate(),
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("admin_statistics"))
        self.assertEqual(response.status_code, 200)
        row = next(row for row in response.context["quran_rows"] if row["student"] == self.student)
        self.assertEqual(row["latest"], reading)
        self.assertTrue(row["completed_today"])


class StudentPointsTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user("points-student", password="x")
        self.teacher = get_user_model().objects.create_user("points-teacher", password="x")
        self.other_teacher = get_user_model().objects.create_user("other-teacher", password="x")
        self.classroom = ClassRoom.objects.create(name="Punkteklasse")
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student)
        self.assignment = Assignment.objects.create(
            classroom=self.classroom,
            title="Testaufgabe",
            created_by=self.teacher,
        )

    def test_balance_combines_each_automatic_source_and_teacher_awards(self):
        AssignmentCompletion.objects.create(user=self.student, assignment=self.assignment)
        for prayer in range(1, 6):
            PrayerStatus.objects.create(
                user=self.student,
                date=dt.date(2026, 9, 8),
                prayer=prayer,
                prayed=True,
            )
        for item_key in RAMADAN_ITEMS_ORDER:
            RamadanItemDone.objects.create(
                user=self.student,
                day=1,
                item_key=item_key,
                school_year="2027",
                done=True,
            )
        TeacherPointAward.objects.create(
            student=self.student,
            teacher=self.teacher,
            points=4,
            reason="Gute Mitarbeit",
        )
        StoryRead.objects.create(user=self.student, level="beginner", sid="1")

        balance = point_balance(self.student)

        self.assertEqual(balance["assignment_points"], 1)
        self.assertEqual(balance["prayer_points"], 1)
        self.assertEqual(balance["ramadan_points"], 1)
        self.assertEqual(balance["story_points"], 1)
        self.assertEqual(balance["teacher_points"], 4)
        self.assertEqual(balance["total_points"], 8)


    def test_completed_ramadan_2026_days_do_not_give_points(self):
        for item_key in RAMADAN_ITEMS_ORDER:
            RamadanItemDone.objects.create(
                user=self.student,
                day=1,
                item_key=item_key,
                school_year="2026",
                done=True,
            )

        balance = point_balance(self.student)

        self.assertEqual(balance["ramadan_points"], 0)
        self.assertEqual(balance["total_points"], 0)

    def test_incomplete_prayer_or_ramadan_day_gives_no_point(self):
        for prayer in range(1, 5):
            PrayerStatus.objects.create(
                user=self.student,
                date=dt.date(2026, 9, 9),
                prayer=prayer,
                prayed=True,
            )
        for item_key in RAMADAN_ITEMS_ORDER[:-1]:
            RamadanItemDone.objects.create(
                user=self.student,
                day=2,
                item_key=item_key,
                school_year="2026",
                done=True,
            )

        balance = point_balance(self.student)

        self.assertEqual(balance["prayer_points"], 0)
        self.assertEqual(balance["ramadan_points"], 0)

    def test_teacher_can_award_any_student(self):
        outsider = get_user_model().objects.create_user("outsider", password="x")
        self.client.force_login(self.teacher)

        allowed = self.client.post(reverse("award_student_points"), {
            "student_id": self.student.id,
            "points": 3,
            "reason": "Hilfsbereit",
        })
        second_award = self.client.post(reverse("award_student_points"), {
            "student_id": outsider.id,
            "points": 3,
        })

        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(second_award.status_code, 302)
        self.assertEqual(TeacherPointAward.objects.filter(student=self.student).count(), 1)
        self.assertTrue(TeacherPointAward.objects.filter(student=outsider).exists())

    def test_non_teacher_cannot_award_points(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("award_student_points"), {
            "student_id": self.student.id,
            "points": 2,
        })
        self.assertEqual(response.status_code, 403)

    def test_teacher_student_picker_contains_students_from_other_classes(self):
        other_student = get_user_model().objects.create_user("other-student", password="x")
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("admin_statistics"))

        visible_ids = {student.id for student in response.context["teacher_students"]}
        self.assertIn(self.student.id, visible_ids)
        self.assertIn(other_student.id, visible_ids)

    def test_library_top10_is_sorted_by_read_items(self):
        other_student = get_user_model().objects.create_user("library-student", password="x")
        StoryRead.objects.create(user=self.student, level="beginner", sid="1")
        StoryRead.objects.create(user=other_student, level="beginner", sid="1")
        StoryRead.objects.create(user=other_student, level="beginner", sid="2")
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("admin_statistics"))

        self.assertEqual(response.context["library_ranking"][0]["user"], other_student)
        self.assertEqual(response.context["library_ranking"][0]["read_items"], 2)

    def test_student_home_shows_position_in_points_bank(self):
        other_student = get_user_model().objects.create_user("higher-points", password="x")
        other_teacher_class = ClassRoom.objects.create(name="Andere Lehrerklasse")
        other_teacher_class.teachers.add(self.other_teacher)
        TeacherPointAward.objects.create(
            student=other_student,
            teacher=self.teacher,
            points=5,
        )
        TeacherPointAward.objects.create(
            student=self.student,
            teacher=self.teacher,
            points=2,
        )
        self.client.force_login(self.student)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.context["student_point_rank"], 2)
        self.assertEqual(response.context["student_point_count"], 2)

    def test_library_top10_position_is_visible_in_both_school_year_views(self):
        StoryRead.objects.create(user=self.student, level="beginner", sid="1")
        get_user_model().objects.filter(pk=self.student.pk).update(
            date_joined=timezone.make_aware(dt.datetime(2026, 8, 1, 12, 0))
        )
        self.student.refresh_from_db()
        self.client.force_login(self.student)

        for school_year in ("2026", "2027"):
            with self.subTest(school_year=school_year):
                session = self.client.session
                session["school_year"] = school_year
                session.save()
                response = self.client.get(reverse("home"), {"tab": "home"})

                self.assertEqual(response.context["library_top10_rank"], 1)
                self.assertContains(response, "Du bist unter den Top 10 in der Bibliothek")

    def test_student_qualifying_in_all_rankings_gets_mosque_top10_message(self):
        StoryRead.objects.create(user=self.student, level="beginner", sid="1")
        for prayer in range(1, 6):
            PrayerStatus.objects.create(
                user=self.student,
                date=dt.date(2026, 9, 8),
                prayer=prayer,
                prayed=True,
            )
        for item_key in RAMADAN_ITEMS_ORDER:
            RamadanItemDone.objects.create(
                user=self.student,
                day=1,
                item_key=item_key,
                school_year="2027",
                done=True,
            )
        self.client.force_login(self.student)

        response_without_quran = self.client.get(reverse("home"), {"tab": "home"})
        self.assertFalse(response_without_quran.context["mosque_top10"])

        DailyQuranReading.objects.create(
            student=self.student,
            portion_index=1,
            completed_on=dt.date(2026, 9, 8),
        )
        response = self.client.get(reverse("home"), {"tab": "home"})

        self.assertTrue(response.context["mosque_top10"])
        self.assertContains(response, "Du bist unter den Top 10 der Moschee")

        self.client.force_login(self.teacher)
        teacher_response = self.client.get(reverse("home"))
        self.assertEqual(teacher_response.context["mosque_ranking"][0]["user"], self.student)
        self.assertContains(teacher_response, "Top 10 der Moschee")


@override_settings(PARENT_APPROVAL_PIN="1717")
class ParentPointApprovalTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user("approval-student", password="x")
        self.teacher = get_user_model().objects.create_user("approval-teacher", password="x")
        Profile.objects.create(user=self.teacher, is_teacher=True)
        self.classroom = ClassRoom.objects.create(name="Bestätigungsklasse")
        self.classroom.students.add(self.student)
        self.classroom.teachers.add(self.teacher)
        self.assignment = Assignment.objects.create(
            classroom=self.classroom,
            title="Eltern prüfen diese Aufgabe",
            created_by=self.teacher,
        )

    def complete_assignment(self):
        self.client.force_login(self.student)
        return self.client.post(
            reverse("mark_assignment_done"),
            data='{"assignment_id": %d}' % self.assignment.pk,
            content_type="application/json",
        )

    def test_new_activity_waits_for_parent_and_confirmation_awards_point(self):
        response = self.complete_assignment()
        self.assertTrue(response.json()["activity_saved"])
        activity = StudentPointActivity.objects.get(student=self.student)
        self.assertEqual(activity.status, "pending")
        self.assertEqual(point_balance(self.student)["assignment_points"], 0)

        page = self.client.get(reverse("parent_point_approvals"))
        self.assertContains(page, "Eltern prüfen diese Aufgabe")
        self.client.post(reverse("parent_point_approvals"), {
            "action": "confirm_day",
            "date": activity.activity_date.isoformat(),
            "pin": "1717",
        })

        activity.refresh_from_db()
        self.assertEqual(activity.status, "confirmed")
        self.assertEqual(point_balance(self.student)["assignment_points"], 1)
        self.assertNotContains(self.client.get(reverse("parent_point_approvals")), "Eltern prüfen diese Aufgabe")

    def test_parent_can_remove_one_activity_without_awarding_point(self):
        self.complete_assignment()
        activity = StudentPointActivity.objects.get(student=self.student)
        self.client.post(reverse("parent_point_approvals"), {
            "action": "remove_item",
            "activity_id": activity.pk,
        })
        activity.refresh_from_db()
        self.assertEqual(activity.status, "rejected")
        self.assertFalse(AssignmentCompletion.objects.filter(
            user=self.student, assignment=self.assignment,
        ).exists())
        self.assertEqual(point_balance(self.student)["assignment_points"], 0)

        response = self.complete_assignment()
        self.assertTrue(response.json()["activity_saved"])
        activity.refresh_from_db()
        self.assertEqual(activity.status, "pending")

    def test_pending_card_expires_after_seven_days(self):
        self.complete_assignment()
        activity = StudentPointActivity.objects.get(student=self.student)
        StudentPointActivity.objects.filter(pk=activity.pk).update(
            expires_at=timezone.now() - dt.timedelta(seconds=1),
        )
        response = self.client.get(reverse("parent_point_approvals"))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "expired")
        self.assertFalse(AssignmentCompletion.objects.filter(
            user=self.student, assignment=self.assignment,
        ).exists())
        self.assertNotContains(response, "Eltern prüfen diese Aufgabe")
        self.assertEqual(point_balance(self.student)["assignment_points"], 0)

    def test_wrong_parent_pin_keeps_activity_pending(self):
        self.complete_assignment()
        activity = StudentPointActivity.objects.get(student=self.student)
        response = self.client.post(reverse("parent_point_approvals"), {
            "action": "confirm_day",
            "date": activity.activity_date.isoformat(),
            "pin": "9999",
        }, follow=True)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "pending")
        self.assertEqual(point_balance(self.student)["assignment_points"], 0)
        self.assertContains(response, "Die PIN ist falsch")

    def test_teacher_cannot_open_parent_approval_page(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("parent_point_approvals")).status_code, 403)

    def test_prayer_library_and_ramadan_create_pending_parent_items(self):
        self.client.force_login(self.student)
        today = timezone.localdate()
        for prayer in range(1, 6):
            prayer_response = self.client.post(
                reverse("toggle_prayer"),
                data=json.dumps({"prayer": prayer, "date": today.isoformat()}),
                content_type="application/json",
            )
        self.assertTrue(prayer_response.json()["activity_saved"])

        story_response = self.client.post(
            reverse("mark_story_read"),
            data='{"level":"beginner","sid":"1"}',
            content_type="application/json",
        )
        self.assertTrue(story_response.json()["activity_saved"])

        get_user_model().objects.filter(pk=self.student.pk).update(
            date_joined=timezone.make_aware(dt.datetime(2026, 8, 1, 12, 0)),
        )
        self.student.refresh_from_db()
        session = self.client.session
        session["school_year"] = "2026"
        session.save()
        for item_key in RAMADAN_ITEMS_ORDER:
            ramadan_response = self.client.post(
                reverse("mark_ramadan_item_done"),
                data=json.dumps({"day": 1, "item_key": item_key}),
                content_type="application/json",
            )
        self.assertTrue(ramadan_response.json()["activity_saved"])

        self.assertEqual(
            set(StudentPointActivity.objects.values_list("category", flat=True)),
            {"prayer", "library", "ramadan"},
        )
        balance = point_balance(self.student)
        self.assertEqual(balance["prayer_points"], 0)
        self.assertEqual(balance["story_points"], 0)
        self.assertEqual(balance["ramadan_points"], 0)

        for activity in list(StudentPointActivity.objects.all()):
            self.client.post(reverse("parent_point_approvals"), {
                "action": "remove_item",
                "activity_id": activity.pk,
            })
        self.assertFalse(PrayerStatus.objects.filter(user=self.student, date=today).exists())
        self.assertFalse(StoryRead.objects.filter(user=self.student, level="beginner", sid="1").exists())
        self.assertFalse(RamadanItemDone.objects.filter(user=self.student, school_year="2026", day=1).exists())

    def test_removing_quran_activity_makes_reading_available_again(self):
        self.client.force_login(self.student)
        reading = DailyQuranReading.objects.create(
            student=self.student,
            portion_index=1,
            completed_on=timezone.localdate(),
        )
        activity = StudentPointActivity.objects.create(
            student=self.student,
            category="quran",
            source_key=str(reading.pk),
            activity_date=reading.completed_on,
            label_ar="ورد القرآن",
            label_de="Koranlesung",
            expires_at=timezone.now() + dt.timedelta(days=7),
        )
        self.client.post(reverse("parent_point_approvals"), {
            "action": "remove_item",
            "activity_id": activity.pk,
        })
        self.assertFalse(DailyQuranReading.objects.filter(pk=reading.pk).exists())


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
    def test_story_scroll_top_button_is_available_except_for_beginner_level(self):
        student = get_user_model().objects.create_user("story-scroll-reader", password="x")
        self.client.force_login(student)

        beginner = self.client.get(reverse("library"), {"level": "beginner", "sid": "1"})
        intermediate = self.client.get(reverse("library"), {"level": "intermediate", "sid": "1"})
        advanced = self.client.get(reverse("library"), {"level": "advanced", "sid": "1"})

        button_markup = '<button type="button" class="library-scroll-top"'
        self.assertNotContains(beginner, button_markup)
        self.assertContains(intermediate, button_markup)
        self.assertContains(advanced, button_markup)

    def test_books_level_contains_embedded_cloudinary_pdfs(self):
        response = self.client.get(reverse("library"), {"level": "books"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "الأربعون النووية")
        self.assertContains(response, "فاتتني صلاة")
        self.assertContains(response, "أنواع الصدقات")
        self.assertContains(response, "data-library-pdf-reader")
        self.assertContains(response, "data-library-pdf-save")
        self.assertContains(response, "Mir ist ein Gebet entgangen")
        self.assertContains(response, "Der Raschidi-Teil")
        self.assertContains(response, "Zum ersten Mal denke ich über den Koran nach")
        self.assertNotContains(response, "Sterne im Firmament des Prophetentums")
        self.assertNotContains(response, "data-library-pdf=")
        self.assertContains(response, "PDF öffnen")
        self.assertContains(response, "res.cloudinary.com", count=3)
        content = response.content.decode()
        self.assertLess(
            content.index("Zum ersten Mal denke ich über den Koran nach"),
            content.index("Mir ist ein Gebet entgangen"),
        )

    def test_finishing_a_book_adds_exactly_one_library_point(self):
        student = get_user_model().objects.create_user("book-reader", password="x")
        self.client.force_login(student)
        url = reverse("mark_story_read")

        first = self.client.post(
            url, data='{"level":"books","sid":"forty_nawawi"}', content_type="application/json"
        )
        second = self.client.post(
            url, data='{"level":"books","sid":"forty_nawawi"}', content_type="application/json"
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="books").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)

    def test_unknown_book_cannot_create_a_point(self):
        student = get_user_model().objects.create_user("invalid-book-reader", password="x")
        self.client.force_login(student)

        response = self.client.post(
            reverse("mark_story_read"),
            data='{"level":"books","sid":"invented-book"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(StoryRead.objects.filter(user=student).exists())

    def test_drive_pdf_proxy_requires_login(self):
        response = self.client.get(reverse("library_book_pdf", args=["rashidi_part"]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_library_uses_content_specific_german_titles(self):
        beginner = self.client.get(reverse("library"), {"level": "beginner"})
        intermediate = self.client.get(reverse("library"), {"level": "intermediate"})

        self.assertContains(beginner, 'data-app-de="Satz 1"')
        self.assertContains(intermediate, 'data-app-de="Nur und der Besuch bei ihrer Großmutter"')

    def test_beginner_story_heading_has_german_title(self):
        response = self.client.get(reverse("library"), {"level": "beginner", "sid": "1"})
        self.assertContains(response, 'data-app-de="Satz 1"')

    def test_ibrahim_story_keeps_arabic_content_and_has_german_title_and_quiz(self):
        student = get_user_model().objects.create_user("ibrahim-reader", password="x")
        self.client.force_login(student)

        response = self.client.get(reverse("library"), {"level": "advanced", "sid": "10"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-app-de="Prophet Ibrahim (Friede sei mit ihm)"')
        self.assertContains(response, "نَشْأَةُ الصَّادِقِ")
        self.assertContains(response, 'id="story-quiz-open"')
        self.assertContains(response, 'class="library-quiz-question"', count=5)
        self.assertContains(response, 'id="story-reading-view"')
        self.assertContains(response, 'data-app-de="Warum ließ Ibrahim den großen Götzen unzerstört?"')
        self.assertContains(response, 'data-app-de="Richtig"')
        self.assertContains(response, 'data-app-de="Um seinem Volk die Machtlosigkeit der Götzen zu zeigen"')
        self.assertContains(response, 'id="story-quiz-notice"')
        self.assertContains(response, "Bitte wähle bei jeder Frage eine Antwort aus.")
        self.assertContains(response, "Nicht alle fünf Antworten waren richtig. Bitte wiederhole das Quiz.")
        self.assertNotContains(response, 'value="true" required')
        self.assertNotContains(response, 'id="mark-read-btn"')

    def test_ibrahim_quiz_requires_all_answers_before_awarding_point(self):
        student = get_user_model().objects.create_user("ibrahim-quiz-reader", password="x")
        self.client.force_login(student)
        quiz_url = reverse("submit_story_quiz")

        failed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"10","answers":["false","2","3","false","3"]}',
            content_type="application/json",
        )

        self.assertEqual(failed.status_code, 200)
        self.assertFalse(failed.json()["passed"])
        self.assertFalse(StoryRead.objects.filter(user=student, level="advanced", sid="10").exists())
        self.assertEqual(point_balance(student)["story_points"], 0)

        passed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"10","answers":["true","2","3","false","3"]}',
            content_type="application/json",
        )
        repeated = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"10","answers":["true","2","3","false","3"]}',
            content_type="application/json",
        )

        self.assertTrue(passed.json()["passed"])
        self.assertTrue(passed.json()["created"])
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="advanced", sid="10").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)

    def test_quiz_story_cannot_be_completed_through_normal_read_endpoint(self):
        student = get_user_model().objects.create_user("quiz-bypass-reader", password="x")
        self.client.force_login(student)

        response = self.client.post(
            reverse("mark_story_read"),
            data='{"level":"advanced","sid":"10"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(StoryRead.objects.filter(user=student).exists())

    def test_musa_story_has_bilingual_quiz_and_arabic_content(self):
        student = get_user_model().objects.create_user("musa-reader", password="x")
        self.client.force_login(student)

        response = self.client.get(reverse("library"), {"level": "advanced", "sid": "11"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-app-de="Prophet Musa (Friede sei mit ihm)"')
        self.assertContains(response, "المَوْلِدُ وَالنَّجَاةُ المُعْجِزَةُ")
        self.assertContains(response, 'data-app-de="Was tat Musas Mutter, als sie Angst um ihn hatte?"')
        self.assertContains(response, 'data-app-de="Warum beschädigte Al-Chidr das Schiff?"')
        self.assertContains(response, 'class="library-quiz-question"', count=5)

    def test_musa_quiz_awards_exactly_one_point_only_when_all_answers_are_correct(self):
        student = get_user_model().objects.create_user("musa-quiz-reader", password="x")
        self.client.force_login(student)
        quiz_url = reverse("submit_story_quiz")

        failed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"11","answers":["3","true","2","true","3"]}',
            content_type="application/json",
        )
        passed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"11","answers":["3","true","2","false","3"]}',
            content_type="application/json",
        )
        repeated = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"11","answers":["3","true","2","false","3"]}',
            content_type="application/json",
        )

        self.assertFalse(failed.json()["passed"])
        self.assertTrue(passed.json()["passed"])
        self.assertTrue(passed.json()["created"])
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="advanced", sid="11").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)

    def test_yunus_story_has_bilingual_quiz_and_arabic_content(self):
        student = get_user_model().objects.create_user("yunus-reader", password="x")
        self.client.force_login(student)

        response = self.client.get(reverse("library"), {"level": "advanced", "sid": "12"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-app-de="Prophet Yunus (Friede sei mit ihm)"')
        self.assertContains(response, "يُونُسُ عَلَيْهِ السَّلَامُ وَأَهْلُ نِينَوَى")
        self.assertContains(response, 'data-app-de="Zu welchem Volk sandte Allah Yunus, Friede sei mit ihm?"')
        self.assertContains(response, 'data-app-de="Welches Bittgebet sprach Yunus im Bauch des Wals?"')
        self.assertContains(response, 'class="library-quiz-question"', count=5)

    def test_yunus_quiz_awards_exactly_one_point_only_when_all_answers_are_correct(self):
        student = get_user_model().objects.create_user("yunus-quiz-reader", password="x")
        self.client.force_login(student)
        quiz_url = reverse("submit_story_quiz")

        failed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"12","answers":["2","true","3","true","3"]}',
            content_type="application/json",
        )
        passed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"12","answers":["2","true","3","false","3"]}',
            content_type="application/json",
        )
        repeated = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"12","answers":["2","true","3","false","3"]}',
            content_type="application/json",
        )

        self.assertFalse(failed.json()["passed"])
        self.assertTrue(passed.json()["passed"])
        self.assertTrue(passed.json()["created"])
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="advanced", sid="12").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)

    def test_yusuf_story_has_bilingual_quiz_and_arabic_content(self):
        student = get_user_model().objects.create_user("yusuf-reader", password="x")
        self.client.force_login(student)

        response = self.client.get(reverse("library"), {"level": "advanced", "sid": "13"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-app-de="Prophet Yusuf (Friede sei mit ihm)"')
        self.assertNotContains(response, 'data-app-de="Satz 1"')
        self.assertContains(response, "رُؤْيَا يُوسُفَ عَلَيْهِ السَّلَامُ")
        self.assertContains(response, 'data-app-de="Was sah Yusuf, Friede sei mit ihm, in seinem Traum, als er noch jung war?"')
        self.assertContains(response, 'data-app-de="Was sagte Yusuf zu seinen Brüdern, nachdem er ihnen offenbart hatte, wer er war?"')
        self.assertContains(response, 'class="library-quiz-question"', count=5)

        overview = self.client.get(reverse("library"), {"level": "advanced"})
        self.assertContains(overview, 'data-app-de="Prophet Yusuf (Friede sei mit ihm)"')

    def test_yusuf_quiz_awards_exactly_one_point_only_when_all_answers_are_correct(self):
        student = get_user_model().objects.create_user("yusuf-quiz-reader", password="x")
        self.client.force_login(student)
        quiz_url = reverse("submit_story_quiz")

        failed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"13","answers":["2","true","2","true","1"]}',
            content_type="application/json",
        )
        passed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"13","answers":["2","true","2","false","1"]}',
            content_type="application/json",
        )
        repeated = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"13","answers":["2","true","2","false","1"]}',
            content_type="application/json",
        )

        self.assertFalse(failed.json()["passed"])
        self.assertTrue(passed.json()["passed"])
        self.assertTrue(passed.json()["created"])
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="advanced", sid="13").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)

    def test_maryam_story_has_bilingual_quiz_and_arabic_content(self):
        student = get_user_model().objects.create_user("maryam-reader", password="x")
        self.client.force_login(student)

        response = self.client.get(reverse("library"), {"level": "advanced", "sid": "14"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-app-de="Maryam (Friede sei mit ihr)"')
        self.assertContains(response, "وِلَادَةُ مَرْيَمَ عَلَيْهَا السَّلَامُ وَنَشْأَتُهَا")
        self.assertContains(
            response,
            'data-app-de="Wer übernahm die Fürsorge für Maryam, Friede sei mit ihr, als sie jung war?"',
        )
        self.assertContains(
            response,
            'data-app-de="Was geschah mit Isa, als seine Feinde ihn töten wollten?"',
        )
        self.assertContains(response, 'class="library-quiz-question"', count=5)

        overview = self.client.get(reverse("library"), {"level": "advanced"})
        self.assertContains(overview, 'data-app-de="Maryam (Friede sei mit ihr)"')

    def test_maryam_quiz_awards_exactly_one_point_only_when_all_answers_are_correct(self):
        student = get_user_model().objects.create_user("maryam-quiz-reader", password="x")
        self.client.force_login(student)
        quiz_url = reverse("submit_story_quiz")

        failed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"14","answers":["2","true","2","false","3"]}',
            content_type="application/json",
        )
        passed = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"14","answers":["2","true","2","true","3"]}',
            content_type="application/json",
        )
        repeated = self.client.post(
            quiz_url,
            data='{"level":"advanced","sid":"14","answers":["2","true","2","true","3"]}',
            content_type="application/json",
        )

        self.assertFalse(failed.json()["passed"])
        self.assertTrue(passed.json()["passed"])
        self.assertTrue(passed.json()["created"])
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(StoryRead.objects.filter(user=student, level="advanced", sid="14").count(), 1)
        self.assertEqual(point_balance(student)["story_points"], 0)


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

    def test_points_bank_is_hidden_in_2026_view(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["school_year"] = "2026"
        session.save()

        response = self.client.get(reverse("admin_statistics"))

        self.assertFalse(response.context["show_points_bank"])
        self.assertNotContains(response, "points-table-panel")
        self.assertNotContains(response, "points-history-panel")

    def test_mosque_top10_card_is_visible_in_2027_even_when_empty(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_statistics"))

        self.assertTrue(response.context["show_points_bank"])
        self.assertContains(response, "Top 10 der Moschee")
        self.assertContains(response, "Noch kein Schüler ist in den Top 10 der Moschee")
        self.assertContains(response, 'data-dashboard-tab="homework"')
        self.assertContains(response, 'data-dashboard-tab="points"')
        self.assertContains(response, 'data-dashboard-tab="mosque"')
        self.assertContains(response, 'data-dashboard-panel="mosque"')

    def test_student_home_keeps_ramadan_and_monthly_prayer_top10_achievements(self):
        RamadanItemDone.objects.create(
            user=self.first_student, day=1, item_key="quran", school_year="2027", done=True,
        )
        PrayerStatus.objects.create(
            user=self.first_student, date=dt.date(2026, 9, 1), prayer=1, prayed=True,
        )
        self.client.force_login(self.first_student)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ramadan_top10_rank"], 1)
        self.assertEqual(response.context["prayer_top10_months"][0]["month"], 9)
        self.assertContains(response, "Du bist unter den Top 10 im Ramadan-Wettbewerb")
        self.assertContains(response, "September")

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

        week_start = dt.date(2026, 8, 30)
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
        self.assertEqual(response.context["prayer_period"], "month")
        self.assertEqual(response.context["prayer_period_start"], dt.date(2026, 8, 1))
        self.assertEqual(response.context["prayer_period_end"], dt.date(2026, 8, 31))
        self.assertNotContains(response, 'href="?prayer_period=week"')

    def test_teacher_sees_only_assignments_from_own_class(self):
        teacher = get_user_model().objects.create_user(
            "teacher-stats", password="x", is_staff=True,
        )
        other_teacher = get_user_model().objects.create_user("other-teacher", password="x")
        own_class = ClassRoom.objects.create(name="Eigene Klasse")
        other_class = ClassRoom.objects.create(name="Andere Klasse")
        test_student_class = ClassRoom.objects.create(name="Test als Schüler")
        own_class.teachers.add(teacher)
        other_class.teachers.add(other_teacher)
        test_student_class.students.add(teacher)
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
        Assignment.objects.create(
            classroom=test_student_class,
            title="Testaufgabe für Lehrerkonto als Schüler",
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

        assignments_response = self.client.get(reverse("home"), {"tab": "assignments"})
        self.assertEqual(assignments_response.status_code, 200)
        self.assertTemplateUsed(assignments_response, "core/home.html")
        self.assertContains(assignments_response, "Eigene Aufgabe")
        self.assertContains(assignments_response, "Testaufgabe für Lehrerkonto als Schüler")
        self.assertNotContains(assignments_response, 'data-home-tab="checklist"')
        self.assertNotContains(assignments_response, 'data-home-tab="prayer"')

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
