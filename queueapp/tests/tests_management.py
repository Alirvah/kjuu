import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command

from queueapp.models import Queue

User = get_user_model()


@pytest.mark.django_db
def test_regenerate_qr_pdfs_rewrites_all(queue, monkeypatch):
    owner_two = User.objects.create_user(username="owner_two", password="pass12345")
    queue_two = Queue.objects.create(name="Queue Two", owner=owner_two)

    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"OLDPDF"), save=True)

    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(f"PDF::{url}".encode("utf-8"))

    monkeypatch.setattr(
        "queueapp.management.commands.regenerate_qr_pdfs.generate_kjuu_pdf",
        fake_generate,
    )
    call_command("regenerate_qr_pdfs", base_url="https://example.test")

    queue.refresh_from_db()
    queue_two.refresh_from_db()

    assert len(calls) == 2
    called_urls = {entry[0] for entry in calls}
    assert f"https://example.test/queue/go/?queue_id={queue.short_id}" in called_urls
    assert f"https://example.test/queue/go/?queue_id={queue_two.short_id}" in called_urls

    with queue.qr_code.open("rb") as file_obj:
        queue_one_pdf = file_obj.read()
    with queue_two.qr_code.open("rb") as file_obj:
        queue_two_pdf = file_obj.read()

    assert queue_one_pdf != b"OLDPDF"
    assert queue_one_pdf.startswith(b"PDF::https://example.test/")
    assert queue_two_pdf.startswith(b"PDF::https://example.test/")


@pytest.mark.django_db
def test_regenerate_qr_pdfs_dry_run_makes_no_changes(queue, monkeypatch):
    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"OLDPDF"), save=True)

    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(b"NEWPDF")

    monkeypatch.setattr(
        "queueapp.management.commands.regenerate_qr_pdfs.generate_kjuu_pdf",
        fake_generate,
    )
    call_command("regenerate_qr_pdfs", base_url="https://example.test", dry_run=True)

    queue.refresh_from_db()
    with queue.qr_code.open("rb") as file_obj:
        queue_pdf = file_obj.read()

    assert calls == []
    assert queue_pdf == b"OLDPDF"


@pytest.mark.django_db
def test_regenerate_qr_pdfs_only_missing(queue, monkeypatch):
    owner_two = User.objects.create_user(username="owner_two_missing", password="pass12345")
    queue_two = Queue.objects.create(name="Queue Two Missing", owner=owner_two)
    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"OLDPDF"), save=True)

    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(b"NEWPDF")

    monkeypatch.setattr(
        "queueapp.management.commands.regenerate_qr_pdfs.generate_kjuu_pdf",
        fake_generate,
    )
    call_command("regenerate_qr_pdfs", base_url="https://example.test", only_missing=True)

    queue.refresh_from_db()
    queue_two.refresh_from_db()

    with queue.qr_code.open("rb") as file_obj:
        queue_one_pdf = file_obj.read()
    with queue_two.qr_code.open("rb") as file_obj:
        queue_two_pdf = file_obj.read()

    assert len(calls) == 1
    assert calls[0][0] == f"https://example.test/queue/go/?queue_id={queue_two.short_id}"
    assert queue_one_pdf == b"OLDPDF"
    assert queue_two_pdf == b"NEWPDF"


@pytest.mark.django_db
def test_regenerate_qr_pdfs_respects_language_option(queue, monkeypatch):
    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(b"PDF")

    monkeypatch.setattr(
        "queueapp.management.commands.regenerate_qr_pdfs.generate_kjuu_pdf",
        fake_generate,
    )

    call_command(
        "regenerate_qr_pdfs",
        base_url="https://example.test",
        queues=[queue.short_id],
        language="en",
    )
    assert calls[-1][1]["title"].startswith("Virtual queue")
    assert calls[-1][1]["description"].startswith("Scan this QR code")
    queue.refresh_from_db()
    assert queue.qr_language == "en"

    call_command(
        "regenerate_qr_pdfs",
        base_url="https://example.test",
        queues=[queue.short_id],
        language="sk",
    )
    assert calls[-1][1]["title"].startswith("Virtuálny rad")
    assert calls[-1][1]["description"].startswith("Naskenujte tento QR kód")
    queue.refresh_from_db()
    assert queue.qr_language == "sk"


@pytest.mark.django_db
def test_regenerate_qr_pdfs_uses_queue_stored_language_by_default(queue, monkeypatch):
    owner_two = User.objects.create_user(username="owner_two_lang", password="pass12345")
    queue_two = Queue.objects.create(name="Queue Two Lang", owner=owner_two, qr_language="en")
    queue.qr_language = "sk"
    queue.save(update_fields=["qr_language"])

    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(b"PDF")

    monkeypatch.setattr(
        "queueapp.management.commands.regenerate_qr_pdfs.generate_kjuu_pdf",
        fake_generate,
    )

    call_command("regenerate_qr_pdfs", base_url="https://example.test")

    details = {entry[0]: entry[1] for entry in calls}
    sk_url = f"https://example.test/queue/go/?queue_id={queue.short_id}"
    en_url = f"https://example.test/queue/go/?queue_id={queue_two.short_id}"
    assert details[sk_url]["title"].startswith("Virtuálny rad")
    assert details[en_url]["title"].startswith("Virtual queue")
