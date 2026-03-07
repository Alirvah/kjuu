from functools import wraps
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _

from .models import Queue


def require_queue_owner(view_func):
    @wraps(view_func)
    def _wrapped_view(request, short_id, *args, **kwargs):
        queue = get_object_or_404(Queue, short_id=short_id)
        if request.user != queue.owner:
            messages.error(request, _("You are not the owner of this queue."))
            return redirect("queueapp:home")
        return view_func(request, short_id, *args, **kwargs)
    return _wrapped_view
