from .models import WeeklyBanner
from .school_years import can_switch_school_years


def navigation_banner(request):
    """Make the current competition map available to the shared navigation."""
    return {
        "banner": WeeklyBanner.objects.order_by("-updated_at").first(),
        "can_switch_school_years": can_switch_school_years(request.user),
    }
