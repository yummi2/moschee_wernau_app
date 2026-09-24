from .parent_points import expire_pending_activities


class ExpireParentPointActivitiesMiddleware:
    """Roll back unconfirmed activities before views build their page state."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            expire_pending_activities(request.user)
        return self.get_response(request)
