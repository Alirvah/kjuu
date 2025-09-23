import json
from django.db import transaction
from django.db.models import F, Max
from django.urls import reverse
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponseRedirect, HttpResponse, JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django_ratelimit.decorators import ratelimit

from .decorators import require_queue_owner
from .forms import QueueForm, AddInfoForm, SignUpForm, LoginForm
from .models import Queue, Customer
from .utils import generate_kjuu_pdf


def privacy(request):
    return render(request, 'queueapp/privacy.html')


def terms(request):
    return render(request, 'queueapp/terms.html')


def logout_view(request):
    logout(request)
    return redirect('queueapp:home')  # Redirect to login page


@ratelimit(key='header:x-forwarded-for', method=['POST'], rate='3/h')
def signup_view(request):
    next_url = request.GET.get('next', None)
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if not request.POST.get("consent"):
            messages.error(request, "Musíte súhlasiť s podmienkami používania a ochranou osobných údajov.")
        elif form.is_valid():
            user = form.save(commit=False)  
            user.save()
            login(request, user)  
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts=settings.ALLOWED_HOSTS):
                return HttpResponseRedirect(next_url)
            return redirect('queueapp:home')  
    else:
        form = SignUpForm()
    return render(request, 'queueapp/signup.html', {'form': form, 'next': next_url})


def login_view(request):
    next_url = request.GET.get('next', None)
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts=settings.ALLOWED_HOSTS):
                    return HttpResponseRedirect(next_url)
                return redirect('queueapp:home')  # Redirect after login
            else:
                form.add_error(None, "Invalid credentials")
    else:
        form = LoginForm()
    return render(request, 'queueapp/login.html', {'form': form, 'next': next_url})


@login_required
def delete_account(request):
    user = request.user
    owns_queue = hasattr(user, 'queue')
    is_in_queue = hasattr(user, 'active_customer')
    if owns_queue or is_in_queue:
        messages.error(request, "Pre zrušenie účtu, sa muisíte najprv odpojiť z virtuálneho radu, alebo ho zmazať.")
        return redirect("queueapp:home")
    if request.method == "POST":
        logout(request)
        user.delete()
        messages.success(request, "Váš účet bol zmazaný")
        return redirect("queueapp:home")
    return render(request, "queueapp/delete_account.html")


def home(request):
    if request.user.is_authenticated:
        return render(request, 'queueapp/home_logged_in.html', {
            'user_queue': getattr(request.user, 'queue', None),
            'active_customer': getattr(request.user, 'active_customer', None)
        })
    else:
        return render(request, 'queueapp/welcome.html')


@ratelimit(key='header:x-forwarded-for', rate='10/h')
def go_to_queue(request):
    short_id = request.POST.get('queue_id', request.GET.get('queue_id', '')).upper()
    if not short_id:
        messages.error(request, "Prosím zadajte kód Virtuálneho radu")
        return redirect('queueapp:home')

    if not Queue.objects.filter(short_id=short_id).exists():
        messages.error(request, f"Virtuálny rad s kódom {short_id} nebol nájdeny.")
        return redirect('queueapp:home')

    join_url = reverse('queueapp:join_queue', args=[short_id])
    if not request.user.is_authenticated:
        login_url = f"{reverse('queueapp:login')}?next={join_url}"
        return redirect(login_url)

    return redirect(join_url)


@login_required
def create_queue(request):
    if hasattr(request.user, 'queue'):
        messages.error(request, "Už vlastníte virtuálny rad.")
        return redirect('queueapp:queue_dashboard', short_id=request.user.queue.short_id)
    
    if request.method == 'POST':
        form = QueueForm(request.POST)
        if form.is_valid():
            queue = form.save(commit=False)
            queue.owner = request.user
            queue.save()

            base_url = request.build_absolute_uri('/').rstrip('/').replace('http://', 'https://')
            queue_url = f"{base_url}/queue/go/?queue_id={queue.short_id}"

            qr_message = f"Naskenovaím tohto QR kódu sa zaradíte do virtuálneho radu:"
            title = "Virtuálny rad - kjuu.sk"
            pdf_buffer = generate_kjuu_pdf(queue_url, title=title, description=qr_message, name=queue.name, short_code=queue.short_id)
            filename = f"{queue.short_id}.pdf"

            queue.qr_code.save(filename, ContentFile(pdf_buffer.read()))
            return redirect('queueapp:queue_dashboard', short_id=queue.short_id)
    else:
        form = QueueForm()
    return render(request, 'queueapp/create_queue.html', {'form': form})


@login_required
@ratelimit(key='user', rate='10/h', block=False)
def join_queue(request, short_id):

    if getattr(request.user, 'queue', None):
        return redirect('queueapp:home')

    try:
        queue = Queue.objects.get(short_id=short_id)
    except Queue.DoesNotExist:
        was_limited = getattr(request, 'limited', False)
        if was_limited:
            return HttpResponse('Sorry you are blocked.', status=429)
        
        messages.error(request, f"Virtuálny rad neexistuje.")
        return redirect('queueapp:home')

    active_customer = getattr(request.user, 'active_customer', None)

    if request.user == queue.owner:
        messages.error(request, "Nedá sa pripojiť do svojho vlastného radu ako zákazník.")
        return redirect('queueapp:home')

    if not queue.active and request.user is not queue.owner and not active_customer:
        messages.error(request, "Kapacita radu bola naplnená, zaradzovanie pozastavené.")
        return redirect('queueapp:home')

    if active_customer and active_customer.queue.short_id != short_id:
        messages.error( request, f"Už sa nachádzate v rade {active_customer.queue.short_id}. Najskôr z neho musíte odíjsť")
        return redirect('queueapp:join_queue', short_id=active_customer.queue.short_id)

    if active_customer and active_customer.queue.short_id == short_id:
        if request.method == 'POST':
            form = AddInfoForm(request.POST)
            if form.is_valid() and active_customer:
                active_customer.info = form.cleaned_data['info']
                active_customer.save()
                return redirect('queueapp:join_queue', short_id=short_id)
        else:
            form = AddInfoForm(initial={'info': active_customer.info})
        return render(request, 'queueapp/join_queue.html', {
            'queue': queue,
            'form': form,
        })

    if request.method == 'POST':
    	# Handle join attempt
        with transaction.atomic():
            Customer.objects.create(
                user=request.user,
                queue=queue,
            )
        return redirect('queueapp:join_queue', short_id=short_id)

	# Default view right before join
    waiting_customers = queue.customers.filter(called_at__isnull=True).count()
    return render(request, 'queueapp/join_queue.html', {
        'queue': queue,
        'waiting_customers': waiting_customers,
    })


@login_required
def leave_queue(request, short_id):
    customer = get_object_or_404(Customer, user=request.user, queue__short_id=short_id)
    queue = customer.queue
    customer.delete()

    base_url = request.build_absolute_uri('/').rstrip('/').replace('http://', 'https://')
    queue_html = f"<span style='text-decoration: underline;'><a href='{base_url}/queue/{queue.short_id}/join/'>{queue.short_id}</a></span>"
    messages.success(request, f"Opustili ste virtuálny rad {queue_html}")
    return redirect('queueapp:home')


@login_required
@require_queue_owner
def queue_dashboard(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)

    waiting_customers = queue.customers.filter(called_at__isnull=True)
    for i, customer in enumerate(waiting_customers, start=1):
        customer.calculated_position = i  

    return render(request, 'queueapp/dashboard.html', {
        'queue': queue,
        'waiting_customers': waiting_customers,
        'called_customer': queue.customers.filter(called_at__isnull=False).first(),
    })


@login_required
@require_queue_owner
def delete_queue(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id, owner=request.user)
    if not queue.is_empty():
        messages.error(request, "Nemôžte zmazať virtuálny rad, ktorý nieje prázdny.")
        return redirect('queueapp:queue_dashboard', short_id=short_id)
    queue.delete()
    messages.success(request, "Virtuálny rad bol zmazaný")
    return redirect('queueapp:home')


@login_required
@require_queue_owner
def call_next(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id, owner=request.user)

    current_called = queue.customers.filter(called_at__isnull=False).first()
    if current_called:
        if current_called.called_at:
           queue.total_wait_time += current_called.wait_time
           queue.served_count += 1
           queue.save()
           current_called.delete()

    next_customer = queue.customers.first()

    if next_customer:
        next_customer.called_at = timezone.now()
        next_customer.save()

    return redirect('queueapp:queue_dashboard', short_id=short_id)


@login_required
@require_queue_owner
def pause_queue(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)

    queue.active = not queue.active
    queue.save()

    if not queue.active:
        messages.success(request, "Virtuálny rad bol pozastavený, nový zákazníci sa nezaradia.")
    return redirect('queueapp:queue_dashboard', short_id=short_id)


@login_required
@require_queue_owner
def download_queue_qr(request, short_id):
    queue = get_object_or_404(Queue, short_id=short_id)
    if not queue.qr_code:
        raise Http404("QR code PDF pre tento virtuálny rad neexistuje.")

    return FileResponse(
        queue.qr_code.open(), 
        content_type='application/pdf',
        as_attachment=False, 
        filename=queue.qr_code.name
    )


@login_required
def register_public_key(request, short_id):
    """
    Called from JS when someone clicks “enter info” and we generate a new key pair.
    Body: public_key=BASE64
    """
    queue = get_object_or_404(Queue, short_id=short_id)

    try:
        payload = json.loads(request.body)  
    except Exception as e:
        return HttpResponseBadRequest(f"Bad info JSON: {str(e)}")

    pub = payload.get("public_key") 
    if not pub:
        return HttpResponseBadRequest("no public_key")

    # are we the owner or a customer?
    if request.user == queue.owner:
        queue.public_key = pub
        queue.save()
    else:
        cust, _ = Customer.objects.get_or_create(user=request.user, queue=queue)
        cust.public_key = pub
        cust.save()

    return JsonResponse({'status':'ok'})


@login_required
def submit_info(request, short_id):
    """
    Body: info=<JSON-string-with-to_owner-and-to_customer>
    """
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)  
            assert 'to_owner' in payload and 'to_customer' in payload
        except Exception as e:
            return HttpResponseBadRequest(f"Bad info JSON: {str(e)}")

        # Process and save the data as needed
        queue = get_object_or_404(Queue, short_id=short_id)
        customer = get_object_or_404(Customer, user=request.user, queue=queue)
        customer.info = json.dumps(payload)  # Save JSON data
        customer.save()

        return JsonResponse({'status': 'ok'})


@login_required
def clear_info(request, short_id):
    Customer.objects.filter(user=request.user, queue__short_id=short_id).update(info=None)
    return JsonResponse({'status': 'ok'})

