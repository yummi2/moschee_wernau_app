import datetime as dt

from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum

from .models import AssignmentCompletion, PrayerStatus, RamadanItemDone, StoryRead, TeacherPointAward
from .ramadan_data import RAMADAN_ITEMS_ORDER


POINTS_PRAYER_START = dt.date(2026, 9, 1)
POINTS_PRAYER_END = dt.date(2027, 7, 31)
# Ramadan 2027 belongs to the app's 2026/2027 school-year dataset.
POINTS_RAMADAN_SCHOOL_YEAR = "2026"


def student_users():
    return (
        User.objects.filter(is_staff=False)
        .filter(Q(profile__is_teacher=False) | Q(profile__isnull=True))
        .exclude(classes_as_teacher__isnull=False)
        .distinct()
    )


def point_balances(users=None):
    users = list(users if users is not None else student_users())
    user_ids = [user.id for user in users]
    balances = {
        user.id: {
            "user": user,
            "assignment_points": 0,
            "prayer_points": 0,
            "ramadan_points": 0,
            "story_points": 0,
            "teacher_points": 0,
            "total_points": 0,
        }
        for user in users
    }
    if not user_ids:
        return balances

    for row in (
        AssignmentCompletion.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(total=Count("id"))
    ):
        balances[row["user_id"]]["assignment_points"] = row["total"]

    complete_prayer_days = (
        PrayerStatus.objects.filter(
            user_id__in=user_ids,
            prayed=True,
            date__range=(POINTS_PRAYER_START, POINTS_PRAYER_END),
        )
        .values("user_id", "date")
        .annotate(prayer_count=Count("prayer", distinct=True))
        .filter(prayer_count=5)
    )
    for row in complete_prayer_days:
        balances[row["user_id"]]["prayer_points"] += 1

    complete_ramadan_days = (
        RamadanItemDone.objects.filter(
            user_id__in=user_ids,
            school_year=POINTS_RAMADAN_SCHOOL_YEAR,
            done=True,
            item_key__in=RAMADAN_ITEMS_ORDER,
        )
        .values("user_id", "day")
        .annotate(item_count=Count("item_key", distinct=True))
        .filter(item_count=len(RAMADAN_ITEMS_ORDER))
    )
    for row in complete_ramadan_days:
        balances[row["user_id"]]["ramadan_points"] += 1

    for row in (
        StoryRead.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(total=Count("id"))
    ):
        balances[row["user_id"]]["story_points"] = row["total"]

    for row in (
        TeacherPointAward.objects.filter(student_id__in=user_ids)
        .values("student_id")
        .annotate(total=Sum("points"))
    ):
        balances[row["student_id"]]["teacher_points"] = row["total"] or 0

    for balance in balances.values():
        balance["total_points"] = sum(
            balance[key]
            for key in (
                "assignment_points",
                "prayer_points",
                "ramadan_points",
                "story_points",
                "teacher_points",
            )
        )
    return balances


def point_balance(user):
    return point_balances([user])[user.id]
