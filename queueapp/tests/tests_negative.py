import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from queueapp.models import Customer, Queue

User = get_user_model()


@pytest.mark.django_db
def test_register_public_key_requires_authentication(client, queue):
    url = reverse("queueapp:register_public_key", args=[queue.short_id])
    response = client.post(url, data=json.dumps({"public_key": "PUB"}), content_type="application/json")

    assert response.status_code == 302
    assert reverse("queueapp:login") in response.url


@pytest.mark.django_db
def test_register_public_key_rejects_invalid_payloads(client, queue, owner):
    client.login(username="owner", password="pass12345")
    url = reverse("queueapp:register_public_key", args=[queue.short_id])

    non_object = client.post(url, data=json.dumps(["PUB"]), content_type="application/json")
    assert non_object.status_code == 400

    blank_key = client.post(url, data=json.dumps({"public_key": "   "}), content_type="application/json")
    assert blank_key.status_code == 400

    queue.refresh_from_db()
    assert queue.public_key in {None, ""}


@pytest.mark.django_db
def test_register_public_key_cannot_cross_register_membership(client, queue, customer_user, make_queue):
    other_owner = User.objects.create_user(username="other_owner", password="pass12345")
    other_queue = make_queue(name="Other queue", owner_user=other_owner)

    Customer.objects.create(user=customer_user, queue=queue)
    client.login(username="alice", password="pass12345")

    url = reverse("queueapp:register_public_key", args=[other_queue.short_id])
    response = client.post(url, data=json.dumps({"public_key": "ATTACK"}), content_type="application/json")

    assert response.status_code == 404
    assert not Customer.objects.filter(user=customer_user, queue=other_queue).exists()


@pytest.mark.django_db
def test_submit_info_rejects_invalid_content_and_shape(client, queue, customer_user):
    customer = Customer.objects.create(user=customer_user, queue=queue, public_key="CUSTOMER_KEY")
    queue.public_key = "OWNER_KEY"
    queue.save(update_fields=["public_key"])

    client.login(username="alice", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    wrong_type = client.post(url, data="{}", content_type="text/plain")
    assert wrong_type.status_code == 400

    bad_json = client.post(url, data="{", content_type="application/json")
    assert bad_json.status_code == 400

    missing_field = client.post(
        url,
        data=json.dumps({"to_owner": "A"}),
        content_type="application/json",
    )
    assert missing_field.status_code == 400

    non_string_field = client.post(
        url,
        data=json.dumps({"to_owner": 123, "to_customer": "B"}),
        content_type="application/json",
    )
    assert non_string_field.status_code == 400

    customer.refresh_from_db()
    assert customer.info is None


@pytest.mark.django_db
def test_submit_info_owner_cannot_submit_as_customer(client, queue, owner):
    client.login(username="owner", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    response = client.post(
        url,
        data=json.dumps({"to_owner": "A", "to_customer": "B"}),
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_clear_info_cannot_modify_other_queue_membership(client, queue, customer_user, make_queue):
    other_owner = User.objects.create_user(username="owner_three", password="pass12345")
    other_queue = make_queue(name="Private queue", owner_user=other_owner)

    customer = Customer.objects.create(user=customer_user, queue=queue)
    customer.info = json.dumps({"to_owner": "x", "to_customer": "y"})
    customer.save(update_fields=["info"])

    client.login(username="alice", password="pass12345")

    url = reverse("queueapp:clear_info", args=[other_queue.short_id])
    response = client.post(url)
    assert response.status_code == 404

    customer.refresh_from_db()
    assert customer.info is not None


@pytest.mark.django_db
def test_owner_mutation_post_blocked_for_non_owner(client, queue, customer_user):
    Customer.objects.create(user=customer_user, queue=queue)
    client.login(username="alice", password="pass12345")

    call_url = reverse("queueapp:call_next", args=[queue.short_id])
    pause_url = reverse("queueapp:pause_queue", args=[queue.short_id])
    delete_url = reverse("queueapp:delete_queue", args=[queue.short_id])

    call_res = client.post(call_url, follow=True)
    pause_res = client.post(pause_url, follow=True)
    delete_res = client.post(delete_url, follow=True)

    assert call_res.status_code == 200
    assert pause_res.status_code == 200
    assert delete_res.status_code == 200

    queue.refresh_from_db()
    assert queue.active is True
    assert Queue.objects.filter(pk=queue.pk).exists()

    waiting = Customer.objects.filter(queue=queue, called_at__isnull=True).count()
    called = Customer.objects.filter(queue=queue, called_at__isnull=False).count()
    assert waiting == 1
    assert called == 0


@pytest.mark.django_db
def test_delete_account_blocked_when_queue_relationship_exists(client, queue, owner):
    client.login(username="owner", password="pass12345")
    url = reverse("queueapp:delete_account")

    response = client.post(url, follow=True)
    assert response.status_code == 200

    assert User.objects.filter(username="owner").exists()
