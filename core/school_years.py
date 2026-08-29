import datetime as dt

from django.utils import timezone


NEW_ACCOUNT_2027_ONLY_FROM = dt.date(2026, 8, 30)


def can_switch_school_years(user):
    """Return whether an account may still access the archived 2026 view."""
    if not getattr(user, "is_authenticated", False):
        return False

    joined_at = user.date_joined
    if timezone.is_aware(joined_at):
        joined_at = timezone.localtime(joined_at)
    return joined_at.date() < NEW_ACCOUNT_2027_ONLY_FROM
