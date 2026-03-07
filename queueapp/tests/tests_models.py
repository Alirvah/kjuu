import os
import re
from datetime import timedelta

from django.core.files.base import ContentFile
from django.utils import timezone

from queueapp.models import Customer, Queue


def test_queue_short_id_and_string(owner):
    queue = Queue.objects.create(name="Coffee Bar", owner=owner)
    assert re.fullmatch(r"[ACDEFGHJKLMNPQRSTUVWXYZ234679]{4}", queue.short_id)
    assert str(queue) == f"Coffee Bar ({queue.short_id})"


def test_queue_is_empty_and_average_wait(owner, customer_user):
    queue = Queue.objects.create(name="Shop", owner=owner)
    assert queue.is_empty() is True
    assert queue.average_wait_time == timedelta(0)

    customer = Customer.objects.create(user=customer_user, queue=queue)
    customer.called_at = customer.created_at + timedelta(minutes=6)
    customer.save(update_fields=["called_at"])

    queue.total_wait_time += customer.wait_time
    queue.served_count += 1
    queue.save(update_fields=["total_wait_time", "served_count"])

    assert queue.average_wait_time == timedelta(minutes=6)


def test_customer_wait_time_position_and_uniqueness(owner, customer_user, customer_user_2):
    queue = Queue.objects.create(name="Clinic", owner=owner)
    first = Customer.objects.create(user=customer_user, queue=queue)
    second = Customer.objects.create(user=customer_user_2, queue=queue)

    assert first.position == 1
    assert second.position == 2
    assert first.wait_time == timedelta(0)

    first.called_at = first.created_at + timedelta(minutes=3)
    first.save(update_fields=["called_at"])

    assert first.position is None
    assert first.wait_time == timedelta(minutes=3)


def test_queue_delete_removes_qr_file(owner, settings):
    queue = Queue.objects.create(name="PDF Queue", owner=owner)
    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"%PDF-1.4\n"), save=True)
    path = queue.qr_code.path

    assert os.path.exists(path)
    queue.delete()
    assert not os.path.exists(path)


def test_customer_secret_id_is_upper_hex(owner, customer_user):
    queue = Queue.objects.create(name="Hex", owner=owner)
    customer = Customer.objects.create(user=customer_user, queue=queue)

    assert re.fullmatch(r"[0-9A-F]{6}", customer.secret_id)
