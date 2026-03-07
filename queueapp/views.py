import json
import re
from collections.abc import Mapping
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from .decorators import require_queue_owner
from .forms import LoginForm, QueueForm, SignUpForm
from .models import Customer, CustomerNoteNonce, Queue
from .utils import generate_kjuu_pdf, get_pdf_locale_strings, normalize_supported_language


MAX_PUBLIC_KEY_LENGTH = 4096
MAX_CIPHERTEXT_LENGTH = 8192
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _get_next_url(request):
    return request.POST.get("next") or request.GET.get("next")


def _is_safe_next(next_url):
    return bool(
        next_url
        and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts=settings.ALLOWED_HOSTS,
            require_https=not settings.DEBUG,
        )
    )


def _get_json_payload(request):
    content_type = request.content_type or ""
    if not content_type.startswith("application/json"):
        return None, HttpResponseBadRequest(_("Expected JSON request body."))

    try:
        return json.loads(request.body.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, HttpResponseBadRequest(_("Invalid JSON payload."))


def _is_htmx_request(request):
    return request.headers.get("HX-Request") == "true"


def _join_queue_context(request, queue):
    context = {"queue": queue}
    active_customer = getattr(request.user, "active_customer", None)
    waiting_count = queue.customers.filter(called_at__isnull=True).count()
    called_count = queue.customers.filter(called_at__isnull=False).count()
    total_live_count = waiting_count + called_count
    has_wait_baseline = queue.served_count > 0

    waiting_pct = int(round((waiting_count / total_live_count) * 100)) if total_live_count else 0
    called_pct = 100 - waiting_pct if total_live_count else 0

    context.update(
        {
            "waiting_customers": waiting_count,
            "queue_waiting_count": waiting_count,
            "queue_called_count": called_count,
            "queue_total_live_count": total_live_count,
            "queue_waiting_pct": waiting_pct,
            "queue_called_pct": called_pct,
            "queue_has_wait_baseline": has_wait_baseline,
            "queue_average_wait": queue.average_wait_time if has_wait_baseline else None,
            "queue_is_active": queue.active,
        }
    )

    if active_customer and active_customer.queue_id == queue.id and not active_customer.called_at:
        position = active_customer.position or waiting_count
        people_ahead = max(position - 1, 0)
        people_behind = max(waiting_count - position, 0)
        ahead_pct = int(round((people_ahead / waiting_count) * 100)) if waiting_count else 0
        behind_pct = max(100 - ahead_pct, 0) if waiting_count else 0
        context["people_ahead"] = people_ahead
        context["people_behind"] = people_behind
        context["people_ahead_pct"] = ahead_pct
        context["people_behind_pct"] = behind_pct
        context["estimated_wait"] = queue.average_wait_time * people_ahead if has_wait_baseline else None
    else:
        context["people_ahead"] = None
        context["people_behind"] = None
        context["people_ahead_pct"] = None
        context["people_behind_pct"] = None
        context["estimated_wait"] = None
    return context


def _parse_int_field(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def privacy(request):
    return render(request, "queueapp/privacy.html")


def terms(request):
    return render(request, "queueapp/terms.html")


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("queueapp:home")


@ratelimit(key="ip", method=["POST"], rate="3/h", block=True)
@require_http_methods(["GET", "POST"])
def signup_view(request):
    next_url = _get_next_url(request)

    if request.method == "POST":
        form = SignUpForm(request.POST)

        if not request.POST.get("consent"):
            messages.error(
                request,
                _("You must agree to the Terms and Privacy Policy."),
            )
        elif form.is_valid():
            user = form.save()
            login(request, user)
            if _is_safe_next(next_url):
                return HttpResponseRedirect(next_url)
            return redirect("queueapp:home")
    else:
        form = SignUpForm()

    return render(request, "queueapp/signup.html", {"form": form, "next": next_url})


@ratelimit(key="ip", method=["POST"], rate="10/h", block=True)
@require_http_methods(["GET", "POST"])
def login_view(request):
    next_url = _get_next_url(request)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if _is_safe_next(next_url):
                    return HttpResponseRedirect(next_url)
                return redirect("queueapp:home")
            form.add_error(None, _("Invalid credentials."))
    else:
        form = LoginForm()

    return render(request, "queueapp/login.html", {"form": form, "next": next_url})


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    user = request.user
    owns_queue = hasattr(user, "queue")
    is_in_queue = hasattr(user, "active_customer")

    if owns_queue or is_in_queue:
        messages.error(
            request,
            _("To delete your account, first leave or delete your active queue."),
        )
        return redirect("queueapp:home")

    if request.method == "POST":
        logout(request)
        user.delete()
        messages.success(request, _("Your account has been deleted."))
        return redirect("queueapp:home")

    return render(request, "queueapp/delete_account.html")


def home(request):
    if request.user.is_authenticated:
        return render(
            request,
            "queueapp/home_logged_in.html",
            {
                "user_queue": getattr(request.user, "queue", None),
                "active_customer": getattr(request.user, "active_customer", None),
            },
        )
    return render(request, "queueapp/welcome.html")


@ratelimit(key="ip", rate="30/m", block=False)
@require_http_methods(["GET", "POST"])
def go_to_queue(request):
    if getattr(request, "limited", False):
        return HttpResponse(_("Too many requests. Please try again later."), status=429)

    short_id = request.POST.get("queue_id", request.GET.get("queue_id", "")).upper().strip()
    if not short_id:
        messages.error(request, _("Please enter a queue code."))
        return redirect("queueapp:home")

    if not Queue.objects.filter(short_id=short_id).exists():
        messages.error(request, _("Queue with code %(code)s was not found.") % {"code": short_id})
        return redirect("queueapp:home")

    join_url = reverse("queueapp:join_queue", args=[short_id])
    if not request.user.is_authenticated:
        login_url = f"{reverse('queueapp:login')}?next={join_url}"
        return redirect(login_url)

    return redirect(join_url)


@login_required
@require_http_methods(["GET", "POST"])
def create_queue(request):
    if hasattr(request.user, "queue"):
        messages.error(request, _("You already own a queue."))
        return redirect("queueapp:queue_dashboard", short_id=request.user.queue.short_id)

    if request.method == "POST":
        form = QueueForm(request.POST)
        if form.is_valid():
            queue = form.save(commit=False)
            queue.owner = request.user
            queue.qr_language = normalize_supported_language(request.LANGUAGE_CODE)
            queue.save()

            base_url = request.build_absolute_uri("/").rstrip("/").replace("http://", "https://")
            queue_url = f"{base_url}/queue/go/?queue_id={queue.short_id}"

            pdf_locale = get_pdf_locale_strings(queue.qr_language)
            qr_message = pdf_locale["default_description"]
            title = f"{pdf_locale['default_title']} - {settings.DOMAIN_NAME}"
            pdf_buffer = generate_kjuu_pdf(
                queue_url,
                title=title,
                description=qr_message,
                name=queue.name,
                short_code=queue.short_id,
            )
            queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(pdf_buffer.read()))
            return redirect("queueapp:queue_dashboard", short_id=queue.short_id)
    else:
        form = QueueForm()

    return render(request, "queueapp/create_queue.html", {"form": form})


@login_required
@ratelimit(key="user", method=["POST"], rate="10/h", block=False)
@require_http_methods(["GET", "POST"])
def join_queue(request, short_id):
    if request.method == "POST" and getattr(request, "limited", False):
        return HttpResponse(_("Too many requests. Please try again later."), status=429)

    if getattr(request.user, "queue", None):
        return redirect("queueapp:home")

    queue = get_object_or_404(Queue, short_id=short_id)
    active_customer = getattr(request.user, "active_customer", None)

    if request.user == queue.owner:
        messages.error(request, _("You cannot join your own queue as a customer."))
        return redirect("queueapp:home")

    if not queue.active and not active_customer:
        messages.error(request, _("Queue is paused. New customers cannot join right now."))
        return redirect("queueapp:home")

    if active_customer and active_customer.queue.short_id != short_id:
        messages.error(
            request,
            _("You are already in queue %(code)s. Leave it before joining another.")
            % {"code": active_customer.queue.short_id},
        )
        return redirect("queueapp:join_queue", short_id=active_customer.queue.short_id)

    if active_customer and active_customer.queue.short_id == short_id:
        return render(request, "queueapp/join_queue.html", _join_queue_context(request, queue))

    if request.method == "POST":
        try:
            with transaction.atomic():
                Customer.objects.create(user=request.user, queue=queue)
        except IntegrityError:
            pass
        return redirect("queueapp:join_queue", short_id=short_id)

    return render(request, "queueapp/join_queue.html", _join_queue_context(request, queue))


@login_required
@require_http_methods(["GET"])
def join_queue_live_state(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    active_customer = getattr(request.user, "active_customer", None)

    if request.user == queue.owner:
        raise Http404(_("Queue owner cannot open customer live state."))

    if active_customer and active_customer.queue.short_id != short_id:
        raise Http404(_("User is active in another queue."))

    if not active_customer and not queue.active:
        raise Http404(_("Queue is not available for new customers."))

    return render(request, "queueapp/partials/join_live_shell.html", _join_queue_context(request, queue))


@login_required
@require_POST
def leave_queue(request, short_id):
    customer = get_object_or_404(Customer, user=request.user, queue__short_id=short_id)
    queue = customer.queue
    customer.delete()

    messages.success(
        request,
        _("You have left virtual queue %(code)s.") % {"code": queue.short_id},
    )
    return redirect("queueapp:home")


@login_required
@require_queue_owner
def queue_dashboard(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    waiting_customers = queue.customers.filter(called_at__isnull=True).order_by("created_at")
    called_customer = queue.customers.filter(called_at__isnull=False).first()
    waiting_count = waiting_customers.count()
    called_count = 1 if called_customer else 0
    total_live_count = waiting_count + called_count
    now = timezone.now()

    oldest_waiting_customer = waiting_customers.first()
    oldest_wait_duration = (
        now - oldest_waiting_customer.created_at if oldest_waiting_customer else None
    )
    estimated_clear_time = (
        queue.average_wait_time * waiting_count if queue.served_count > 0 else None
    )
    queue_age = now - (queue.created_at or now)
    queue_age_hours = max(queue_age.total_seconds() / 3600, 0.0)
    service_pace_per_hour = (
        queue.served_count / queue_age_hours if queue_age_hours > 0 else 0.0
    )
    flow_waiting_pct = int(round((waiting_count / total_live_count) * 100)) if total_live_count else 0
    flow_called_pct = 100 - flow_waiting_pct if total_live_count else 0

    fresh_waiting = 0
    medium_waiting = 0
    long_waiting = 0
    for customer in waiting_customers:
        wait_seconds = (now - customer.created_at).total_seconds()
        if wait_seconds <= 5 * 60:
            fresh_waiting += 1
        elif wait_seconds <= 15 * 60:
            medium_waiting += 1
        else:
            long_waiting += 1

    if waiting_count:
        fresh_pct = int(round((fresh_waiting / waiting_count) * 100))
        medium_pct = int(round((medium_waiting / waiting_count) * 100))
        long_pct = max(100 - fresh_pct - medium_pct, 0)
    else:
        fresh_pct = 0
        medium_pct = 0
        long_pct = 0

    for index, customer in enumerate(waiting_customers, start=1):
        customer.calculated_position = index

    return render(
        request,
        "queueapp/dashboard.html",
        {
            "queue": queue,
            "waiting_customers": waiting_customers,
            "called_customer": called_customer,
            "waiting_count": waiting_count,
            "called_count": called_count,
            "oldest_wait_duration": oldest_wait_duration,
            "estimated_clear_time": estimated_clear_time,
            "service_pace_per_hour": service_pace_per_hour,
            "queue_uptime": queue_age if queue_age > timedelta(0) else timedelta(0),
            "flow_waiting_pct": flow_waiting_pct,
            "flow_called_pct": flow_called_pct,
            "fresh_waiting_count": fresh_waiting,
            "medium_waiting_count": medium_waiting,
            "long_waiting_count": long_waiting,
            "fresh_waiting_pct": fresh_pct,
            "medium_waiting_pct": medium_pct,
            "long_waiting_pct": long_pct,
        },
    )


@login_required
@require_queue_owner
@require_POST
def delete_queue(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id, owner=request.user)
    if not queue.is_empty():
        messages.error(request, _("You cannot delete a queue that is not empty."))
        return redirect("queueapp:queue_dashboard", short_id=short_id)

    queue.delete()
    messages.success(request, _("Queue has been deleted."))
    return redirect("queueapp:home")


@login_required
@require_queue_owner
@require_POST
def call_next(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id, owner=request.user)

    current_called = queue.customers.filter(called_at__isnull=False).first()
    if current_called and current_called.called_at:
        queue.total_wait_time += current_called.wait_time
        queue.served_count += 1
        queue.save(update_fields=["total_wait_time", "served_count"])
        current_called.delete()

    next_customer = queue.customers.filter(called_at__isnull=True).first()
    if next_customer:
        next_customer.called_at = timezone.now()
        next_customer.save(update_fields=["called_at"])

    return redirect("queueapp:queue_dashboard", short_id=short_id)


@login_required
@require_queue_owner
@require_POST
def pause_queue(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    queue.active = not queue.active
    queue.save(update_fields=["active"])

    if queue.active:
        messages.success(request, _("Queue has been resumed."))
    else:
        messages.success(request, _("Queue has been paused. New customers cannot join."))

    return redirect("queueapp:queue_dashboard", short_id=short_id)


@login_required
@require_queue_owner
def download_queue_qr(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    if not queue.qr_code:
        raise Http404(_("QR code PDF for this queue does not exist."))

    return FileResponse(
        queue.qr_code.open(),
        content_type="application/pdf",
        as_attachment=False,
        filename=queue.qr_code.name,
    )


@login_required
@require_POST
def register_public_key(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    payload, error_response = _get_json_payload(request)
    if error_response:
        return error_response

    public_key = payload.get("public_key") if isinstance(payload, dict) else None
    if not isinstance(public_key, str) or not public_key.strip():
        return HttpResponseBadRequest(_("Missing or invalid public_key."))

    public_key = public_key.strip()
    if len(public_key) > MAX_PUBLIC_KEY_LENGTH:
        return HttpResponseBadRequest(_("Public key is too large."))

    if request.user == queue.owner:
        if queue.public_key != public_key:
            queue.public_key = public_key
            queue.public_key_version += 1
            queue.save(update_fields=["public_key", "public_key_version"])
        return JsonResponse({"status": "ok", "version": queue.public_key_version})
    else:
        customer = get_object_or_404(Customer, user=request.user, queue=queue)
        if customer.public_key != public_key:
            customer.public_key = public_key
            customer.public_key_version += 1
            customer.save(update_fields=["public_key", "public_key_version"])
        return JsonResponse({"status": "ok", "version": customer.public_key_version})


@login_required
@require_POST
def submit_info(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    customer = get_object_or_404(Customer, user=request.user, queue=queue)

    if (request.content_type or "").startswith("application/json"):
        payload, error_response = _get_json_payload(request)
        if error_response:
            return error_response
    else:
        payload = request.POST

    if not isinstance(payload, Mapping):
        return HttpResponseBadRequest(_("Payload must be a JSON object."))

    to_owner = payload.get("to_owner")
    to_customer = payload.get("to_customer")
    owner_key_version = _parse_int_field(payload.get("owner_key_version"))
    customer_key_version = _parse_int_field(payload.get("customer_key_version"))
    nonce = payload.get("nonce")
    if not isinstance(to_owner, str) or not isinstance(to_customer, str):
        return HttpResponseBadRequest(
            _("Payload must contain string fields 'to_owner' and 'to_customer'.")
        )
    if not isinstance(owner_key_version, int) or owner_key_version < 1:
        return HttpResponseBadRequest(_("owner_key_version must be a positive integer."))
    if not isinstance(customer_key_version, int) or customer_key_version < 1:
        return HttpResponseBadRequest(_("customer_key_version must be a positive integer."))
    if not isinstance(nonce, str) or not NONCE_PATTERN.match(nonce):
        return HttpResponseBadRequest(_("Invalid nonce format."))
    if not queue.public_key:
        return HttpResponseBadRequest(
            _("Queue owner public key is missing. Register owner key first.")
        )
    if not customer.public_key:
        return HttpResponseBadRequest(
            _("Customer public key is missing. Register customer key first.")
        )
    if not to_owner.strip() or not to_customer.strip():
        return HttpResponseBadRequest(
            _("Encrypted fields cannot be empty.")
        )
    if len(to_owner) > MAX_CIPHERTEXT_LENGTH or len(to_customer) > MAX_CIPHERTEXT_LENGTH:
        return HttpResponseBadRequest(_("Encrypted payload is too large."))
    if queue.public_key_version != owner_key_version:
        return HttpResponseBadRequest(_("Owner key version mismatch. Refresh and retry."))
    if customer.public_key_version != customer_key_version:
        return HttpResponseBadRequest(_("Customer key version mismatch. Refresh and retry."))

    try:
        with transaction.atomic():
            CustomerNoteNonce.objects.create(customer=customer, nonce=nonce)
    except IntegrityError:
        return HttpResponseBadRequest(_("Replay detected: nonce already used."))

    stale_ids = (
        CustomerNoteNonce.objects.filter(customer=customer)
        .order_by("-created_at")
        .values_list("id", flat=True)[100:]
    )
    if stale_ids:
        CustomerNoteNonce.objects.filter(id__in=list(stale_ids)).delete()

    customer.info = json.dumps(
        {
            "to_owner": to_owner,
            "to_customer": to_customer,
            "owner_key_version": owner_key_version,
            "customer_key_version": customer_key_version,
            "nonce": nonce,
        }
    )
    customer.save(update_fields=["info"])

    if _is_htmx_request(request):
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "secure-note-updated"
        return response

    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def clear_info(request, short_id):
    customer = get_object_or_404(Customer, user=request.user, queue__short_id=short_id)
    customer.info = None
    customer.save(update_fields=["info"])
    if _is_htmx_request(request):
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "secure-note-updated"
        return response
    return JsonResponse({"status": "ok"})
