import io

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from queueapp.models import Customer, Queue

User = get_user_model()


@pytest.fixture(autouse=True)
def stable_test_settings(settings, tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = str(media_root)
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.SECURE_SSL_REDIRECT = False
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
    settings.RATELIMIT_ENABLE = True

    yield
    cache.clear()


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner", password="pass12345")


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(username="alice", password="pass12345")


@pytest.fixture
def customer_user_2(db):
    return User.objects.create_user(username="bob", password="pass12345")


@pytest.fixture
def queue(owner):
    return Queue.objects.create(name="Test Queue", owner=owner)


@pytest.fixture
def make_queue(owner):
    def _make(name="Queue", owner_user=None, active=True):
        q = Queue.objects.create(name=name, owner=owner_user or owner)
        q.active = active
        q.save(update_fields=["active"])
        return q

    return _make


@pytest.fixture
def make_customer():
    def _make(user, queue_obj, **kwargs):
        return Customer.objects.create(user=user, queue=queue_obj, **kwargs)

    return _make


@pytest.fixture
def mock_pdf(monkeypatch):
    monkeypatch.setattr(
        "queueapp.views.generate_kjuu_pdf",
        lambda *args, **kwargs: io.BytesIO(b"%PDF-1.4\n% kjuu test pdf\n"),
    )
