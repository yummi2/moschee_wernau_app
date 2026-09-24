from django import template
register = template.Library()

@register.filter
def dict_get(d, key):
    if not isinstance(d, dict):
        return None
    return d.get(key)


@register.filter
def is_teacher_account(user):
    if not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "profile", None)
    return bool(getattr(profile, "is_teacher", False)) or user.classes_as_teacher.exists()
