from .models import WeeklyBanner


def navigation_banner(request):
    """Make the current competition map available to the shared navigation."""
    return {
        "banner": WeeklyBanner.objects.order_by("-updated_at").first(),
    }
