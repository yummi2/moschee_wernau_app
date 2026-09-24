import datetime as dt

from django.utils import timezone
from django.db import transaction

from .models import (
    AssignmentCompletion,
    DailyQuranReading,
    PrayerStatus,
    RamadanItemDone,
    StoryRead,
    StudentPointActivity,
)


APPROVAL_WINDOW = dt.timedelta(days=7)


def queue_point_activity(*, student, category, source_key, activity_date, label_ar, label_de):
    """Create one immutable parent-review item for an earned automatic point."""
    activity, created = StudentPointActivity.objects.get_or_create(
        student=student,
        category=category,
        source_key=str(source_key),
        defaults={
            "activity_date": activity_date,
            "label_ar": label_ar,
            "label_de": label_de,
            "expires_at": timezone.now() + APPROVAL_WINDOW,
        },
    )
    if not created and activity.status in {"rejected", "expired"}:
        activity.activity_date = activity_date
        activity.label_ar = label_ar
        activity.label_de = label_de
        activity.status = "pending"
        activity.expires_at = timezone.now() + APPROVAL_WINDOW
        activity.confirmed_at = None
        activity.save(update_fields=(
            "activity_date", "label_ar", "label_de", "status",
            "expires_at", "confirmed_at",
        ))
        created = True
    return activity, created


def rollback_point_activity(activity):
    """Undo the completion represented by a pending parent-review item."""
    filters = {"user": activity.student}
    if activity.category == "assignment":
        AssignmentCompletion.objects.filter(
            **filters, assignment_id=activity.source_key
        ).delete()
    elif activity.category == "prayer":
        try:
            prayer_date = dt.date.fromisoformat(activity.source_key)
        except ValueError:
            return
        PrayerStatus.objects.filter(**filters, date=prayer_date).delete()
    elif activity.category == "ramadan":
        try:
            school_year, day = activity.source_key.split(":", 1)
            day = int(day)
        except (ValueError, TypeError):
            return
        RamadanItemDone.objects.filter(
            **filters, school_year=school_year, day=day
        ).delete()
    elif activity.category == "library":
        try:
            level, sid = activity.source_key.split(":", 1)
        except ValueError:
            return
        StoryRead.objects.filter(**filters, level=level, sid=sid).delete()
    elif activity.category == "quran":
        DailyQuranReading.objects.filter(
            student=activity.student, pk=activity.source_key
        ).delete()


@transaction.atomic
def expire_pending_activities(student):
    activities = list(StudentPointActivity.objects.select_for_update().filter(
        student=student,
        status="pending",
        expires_at__lte=timezone.now(),
    ))
    for activity in activities:
        rollback_point_activity(activity)
        activity.status = "expired"
        activity.save(update_fields=("status",))
    return len(activities)
