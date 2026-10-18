import datetime as dt

from django.utils import timezone

from .models import WeeklyBanner
from .school_years import can_switch_school_years


LIBRARY_UPDATES_NEW_UNTIL = dt.date(2026, 11, 1)


def library_updates_are_new(today=None):
    """Keep the library update badge temporary without requiring a later deploy."""
    return (today or timezone.localdate()) <= LIBRARY_UPDATES_NEW_UNTIL


def navigation_banner(request):
    """Make the current competition map available to the shared navigation."""
    can_view_student_stats = False
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        can_view_student_stats = (
            request.user.is_staff
            or bool(profile and profile.is_teacher)
            or request.user.classes_as_teacher.exists()
        )
    return {
        "banner": WeeklyBanner.objects.order_by("-updated_at").first(),
        "can_switch_school_years": can_switch_school_years(request.user),
        "can_view_student_stats": can_view_student_stats,
        "show_library_new_badge": library_updates_are_new(),
    }
