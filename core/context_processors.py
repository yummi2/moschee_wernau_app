from .models import WeeklyBanner
from .school_years import can_switch_school_years


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
    }
