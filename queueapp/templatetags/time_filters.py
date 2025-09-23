from django import template
from django.utils import timezone
from datetime import datetime, timedelta

register = template.Library()

@register.filter
def timedelta_display(value):
    if not value:
        return "0s"
    total_seconds = int(value.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


@register.filter
def timesince_display(value):
    """
    Accepts a datetime, returns how long ago it was in h m s.
    """
    if not value:
        return ""

    now = timezone.now()

    # ✅ Only apply timezone checks if value is a datetime
    if isinstance(value, datetime):
        if timezone.is_aware(value) and timezone.is_naive(now):
            now = timezone.make_aware(now)
        elif timezone.is_naive(value) and timezone.is_aware(now):
            value = timezone.make_aware(value)

        delta = now - value

    elif isinstance(value, timedelta):
        delta = value

    else:
        return ""

    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "0s"

    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"
