# Project layout
#
# tests/
# ├─ conftest.py
# ├─ test_models.py
# └─ test_views.py
#
# Copy these into the files above. They refactor your current tests.py into a tidy, fast pytest suite
# with temp MEDIA_ROOT, fast password hashing, and a patched PDF generator.

# ===================== tests/conftest.py =====================
import io
import os
import re
import json
import tempfile
import shutil
from contextlib import contextmanager
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.contrib.messages import get_messages
from django.core.files.base import ContentFile

from queueapp.models import Queue, Customer

User = get_user_model()


# --- Global test speedups ---
@pytest.fixture(autouse=True)
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def _fast_passwords():
    yield


@pytest.fixture(autouse=True)
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="kjuu-media-"))
def _temp_media_root():
    yield


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner", password="x")


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", password="x")


@pytest.fixture
def user2(db):
    return User.objects.create_user(username="bob", password="x")


@pytest.fixture
def queue(owner):
    # Let model generate a valid 4-char short_id
    return Queue.objects.create(name="Test Q", owner=owner)


@pytest.fixture
def make_queue(owner):
    def _mk(name="Q", owner_user=None):
        return Queue.objects.create(name=name, owner=owner_user or owner)
    return _mk

@pytest.fixture(autouse=True)
def isolated_media_storage(tmp_path, settings):
    """
    Force a fresh MEDIA_ROOT and local FileSystemStorage per test.
    Files land in a temp dir that is wiped after each test.
    """
    media_dir = tmp_path / "media"
    upload_tmp = tmp_path / "uploadtmp"
    media_dir.mkdir(parents=True, exist_ok=True)
    upload_tmp.mkdir(parents=True, exist_ok=True)

    settings.MEDIA_ROOT = str(media_dir)
    settings.FILE_UPLOAD_TEMP_DIR = str(upload_tmp)
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    yield
    shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

@pytest.fixture
def make_customer():
    def _mk(user, queue, **kwargs):
        return Customer.objects.create(user=user, queue=queue, **kwargs)
    return _mk


@contextmanager
def patched_pdf(monkeypatch, data=b"%PDF-kjuu"):
    """Patch generate_kjuu_pdf to return a BytesIO without requiring ReportLab during tests."""
    from queueapp import utils as qutils
    monkeypatch.setattr(qutils, "generate_kjuu_pdf", lambda *a, **k: io.BytesIO(data))
    yield


# ===================== tests/test_models.py =====================
from datetime import timedelta
from django.utils import timezone
from queueapp.models import Queue, Customer


def test_queue_str_and_short_id_format(owner):
    q = Queue.objects.create(name="Test Queue", owner=owner)
    assert re.fullmatch(r"[ACDEFGHJKLMNPQRSTUVWXYZ234679]{4}", q.short_id)
    assert str(q) == f"Test Queue ({q.short_id})"


def test_queue_is_empty_and_average_wait_time(owner, user):
    q = Queue.objects.create(name="Shop", owner=owner)
    assert q.is_empty() is True
    assert q.average_wait_time == timedelta(0)

    # Add served stats and recompute
    c = Customer.objects.create(user=user, queue=q)
    c.created_at = timezone.now() - timedelta(minutes=5)
    c.called_at = timezone.now()
    c.save(update_fields=["created_at", "called_at"])

    q.total_wait_time += c.wait_time
    q.served_count += 1
    q.save()

    assert q.average_wait_time.total_seconds() > 0


def test_customer_wait_time_and_position(owner, user, user2):
    q = Queue.objects.create(name="Q", owner=owner)
    c1 = Customer.objects.create(user=user, queue=q)
    c2 = Customer.objects.create(user=user2, queue=q)
    assert c1.position == 1
    assert c2.position == 2

    # When called, position is None and wait_time >= 0
    c1.called_at = c1.created_at + timedelta(minutes=15)
    c1.save(update_fields=["called_at"])
    assert c1.position is None
    assert c1.wait_time == timedelta(minutes=15)


def test_customer_secret_id_format(owner, user):
    q = Queue.objects.create(name="Q", owner=owner)
    c = Customer.objects.create(user=user, queue=q)
    assert re.fullmatch(r"[0-9A-F]{6}", c.secret_id)


# ===================== tests/test_views.py =====================
import io
import os
import json
import tempfile
import pytest
from datetime import timedelta
from unittest import mock
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import override_settings
from queueapp.models import Queue, Customer

User = get_user_model()


# --------- Basic pages and auth ---------

def test_home_signup_login_pages(client):
    assert client.get(reverse('queueapp:home')).status_code == 200
    assert client.get(reverse('queueapp:signup')).status_code == 200
    assert client.get(reverse('queueapp:login')).status_code == 200


def test_logout_redirects_home(client, user):
    client.login(username='alice', password='x')
    resp = client.get(reverse('queueapp:logout'))
    assert resp.status_code == 302 and reverse('queueapp:home') in resp.url


def test_delete_account_requires_login(client):
    resp = client.post(reverse('queueapp:delete_account'))
    assert resp.status_code == 302 and reverse('queueapp:login') in resp.url


def test_delete_account_flow(client, user):
    client.login(username='alice', password='x')
    resp = client.post(reverse('queueapp:delete_account'))
    assert resp.status_code == 302
    assert not User.objects.filter(username='alice').exists()


# --------- Queue creation + QR PDF ---------
@pytest.mark.django_db
def test_create_queue_restrictions(client, user, owner):
    # anon -> redirect to login
    r = client.get(reverse('queueapp:create_queue'))
    assert r.status_code == 302

    client.login(username='alice', password='x')  # no queue yet
    assert client.get(reverse('queueapp:create_queue')).status_code == 200

    # Owner who already has queue gets redirected to dashboard
    client.logout(); client.login(username='owner', password='x')
    q = Queue.objects.create(name='Has', owner=owner)
    r = client.get(reverse('queueapp:create_queue'))
    assert r.status_code == 302


@pytest.mark.django_db
def test_create_queue_saves_pdf(client, user, monkeypatch, request):
    client.login(username='alice', password='x')
    with patched_pdf(monkeypatch):
        r = client.post(reverse('queueapp:create_queue'), {'name': 'CombinedQueue'})
    assert r.status_code == 302
    q = Queue.objects.get(owner__username='alice')
    assert q.qr_code and q.qr_code.name.endswith('.pdf')
    request.addfinalizer(lambda: q.delete())


# --------- Join / leave flow ---------
@pytest.mark.django_db
def test_join_leave_flow(client, user, queue):
    client.login(username='alice', password='x')
    join_url = reverse('queueapp:join_queue', args=[queue.short_id])

    # GET join page
    assert client.get(join_url).status_code == 200
    # POST join
    r = client.post(join_url)
    assert r.status_code == 302
    assert Customer.objects.filter(user__username='alice', queue=queue).exists()

    # leave
    r = client.post(reverse('queueapp:leave_queue', args=[queue.short_id]))
    assert r.status_code == 302
    assert not Customer.objects.filter(user__username='alice').exists()


@pytest.mark.django_db
def test_prevent_double_join(client, user, queue):
    client.login(username='alice', password='x')
    url = reverse('queueapp:join_queue', args=[queue.short_id])
    client.post(url)
    r = client.post(url)
    # You redirect back to join page; count stays one
    assert r.status_code == 302
    assert Customer.objects.filter(user=user, queue=queue).count() == 1


@pytest.mark.django_db
def test_leave_without_join_404(client, user, queue):
    client.login(username='alice', password='x')
    r = client.post(reverse('queueapp:leave_queue', args=[queue.short_id]))
    assert r.status_code == 404


@pytest.mark.django_db
def test_owner_cannot_join_own_queue(client, owner, queue):
    client.login(username='owner', password='x')

    # Attempt to join own queue
    resp = client.post(reverse('queueapp:join_queue', args=[queue.short_id]), follow=True)

    # Should end up on home
    assert resp.status_code == 200
    assert resp.request["PATH_INFO"] == reverse("queueapp:home")

    # And crucially: no Customer created for the owner in their own queue
    assert not Customer.objects.filter(user=owner, queue=queue).exists()


# --------- Pause / unpause and joining while paused ---------
@pytest.mark.django_db
def test_pause_unpause_and_block_new_customers(client, owner, queue, user):
    client.login(username='owner', password='x')
    pause_url = reverse('queueapp:pause_queue', args=[queue.short_id])
    # Pause
    client.post(pause_url)
    queue.refresh_from_db(); assert queue.active is False

    client.logout(); client.login(username='alice', password='x')
    r = client.post(reverse('queueapp:join_queue', args=[queue.short_id]), follow=True)
    msgs = list(r.context.get('messages'))
    assert any('pozastaven' in m.message for m in msgs)

    # Unpause
    client.logout(); client.login(username='owner', password='x')
    client.post(pause_url)
    queue.refresh_from_db(); assert queue.active is True


# --------- Calling next and stats ---------
@pytest.mark.django_db
def test_call_next_updates_wait_stats(client, owner, queue, user, user2):
    client.login(username='owner', password='x')
    c1 = Customer.objects.create(user=user, queue=queue)
    c1.created_at = timezone.now() - timedelta(minutes=3)
    c1.save(update_fields=["created_at"])
    Customer.objects.create(user=user2, queue=queue)

    # 1st call -> c1 gets called
    client.post(reverse('queueapp:call_next', args=[queue.short_id]))
    c1.refresh_from_db(); assert c1.called_at is not None

    # 2nd call -> c1 served & stats updated, c2 called
    client.post(reverse('queueapp:call_next', args=[queue.short_id]))
    queue.refresh_from_db()
    assert queue.served_count == 1
    assert queue.total_wait_time.total_seconds() > 0


# --------- Dashboard & QR download ---------
@pytest.mark.django_db
def test_queue_dashboard_context_and_qr_download(client, owner, queue, user, request):
    # Put someone in the queue so the dashboard has content
    Customer.objects.create(user=user, queue=queue)

    # Owner can view dashboard with expected context keys
    client.login(username='owner', password='x')
    dash = client.get(reverse('queueapp:queue_dashboard', args=[queue.short_id]))
    assert dash.status_code == 200
    assert {'queue', 'waiting_customers', 'called_customer'} <= set(dash.context.keys())

    # No QR yet -> expect 404
    qr_url = reverse('queueapp:qr_queue', args=[queue.short_id])
    resp = client.get(qr_url)
    assert resp.status_code == 404

    # Attach a fake PDF to this existing queue (owner can have only one)
    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"%PDF-1.4\n% mocked pdf %"), save=True)

    # Now the QR endpoint should stream the PDF
    resp = client.get(qr_url)
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"

    request.addfinalizer(lambda: queue.delete())


# --------- Public-key + info JSON endpoints ---------
@pytest.mark.django_db
def test_register_public_key_owner_and_customer(client, owner, user, queue):
    client.login(username='owner', password='x')
    url = reverse('queueapp:register_public_key', args=[queue.short_id])
    r = client.post(url, data=json.dumps({'public_key': 'PUBQ'}), content_type='application/json')
    assert r.status_code == 200
    queue.refresh_from_db(); assert queue.public_key == 'PUBQ'

    client.logout(); client.login(username='alice', password='x')
    Customer.objects.create(user=user, queue=queue)
    r = client.post(url, data=json.dumps({'public_key': 'PUBC'}), content_type='application/json')
    assert r.status_code == 200
    assert Customer.objects.get(user=user, queue=queue).public_key == 'PUBC'


@pytest.mark.django_db
def test_register_public_key_bad_json_and_missing_key(client, owner, queue):
    client.login(username='owner', password='x')
    url = reverse('queueapp:register_public_key', args=[queue.short_id])
    r = client.post(url, data='not-json', content_type='application/json')
    assert r.status_code == 400
    r = client.post(url, data=json.dumps({}), content_type='application/json')
    assert r.status_code == 400


@pytest.mark.django_db
def test_submit_and_clear_info(client, user, queue):
    client.login(username='alice', password='x')
    Customer.objects.create(user=user, queue=queue)
    url_submit = reverse('queueapp:submit_info', args=[queue.short_id])
    payload = {"to_owner": "AAA", "to_customer": "BBB"}
    r = client.post(url_submit, data=json.dumps(payload), content_type='application/json')
    assert r.status_code == 200
    cust = Customer.objects.get(user=user, queue=queue)
    assert cust.info and 'AAA' in cust.info

    url_clear = reverse('queueapp:clear_info', args=[queue.short_id])
    r = client.post(url_clear)
    assert r.status_code == 200
    cust.refresh_from_db(); assert cust.info is None


# --------- go_to_queue helper ---------
@pytest.mark.django_db
def test_go_to_queue_empty_and_nonexistent_and_redirects(client, user, queue):
    # empty id -> error + redirect home
    r = client.post(reverse('queueapp:go_to_queue'), {"queue_id": ""}, follow=True)
    assert r.status_code == 200

    # nonexistent -> error + redirect home
    r = client.post(reverse('queueapp:go_to_queue'), {"queue_id": "ZZZZ"}, follow=True)
    assert r.status_code == 200

    # anon valid -> login redirect with next
    r = client.post(reverse('queueapp:go_to_queue'), {"queue_id": queue.short_id})
    assert r.status_code == 302 and reverse('queueapp:login') in r.url

    # authed -> redirect to join
    client.login(username='alice', password='x')
    r = client.post(reverse('queueapp:go_to_queue'), {"queue_id": queue.short_id})
    assert r.status_code == 302
    assert reverse('queueapp:join_queue', args=[queue.short_id]) in r.url


# --------- Storage cleanup signal ---------
@pytest.mark.django_db
def test_delete_queue_removes_pdf_file(client, owner, monkeypatch):
    client.login(username='owner', password='x')
    with patched_pdf(monkeypatch):
        r = client.post(reverse('queueapp:create_queue'), {'name': 'HasPDF'})
    q = Queue.objects.get(owner__username='owner')
    path = q.qr_code.path
    assert os.path.exists(path)
    q.delete()
    assert not os.path.exists(path)
