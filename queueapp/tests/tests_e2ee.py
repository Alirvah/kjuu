import json

import pytest
from django.urls import reverse

from queueapp.models import Customer


@pytest.mark.django_db
def test_e2ee_submit_requires_registered_keys(client, queue, owner, customer_user):
    customer = Customer.objects.create(user=customer_user, queue=queue)
    client.login(username="alice", password="pass12345")

    submit_url = reverse("queueapp:submit_info", args=[queue.short_id])
    payload = {"to_owner": "OWNERCIPHERTEXT", "to_customer": "CUSTOMERCIPHERTEXT"}

    missing_owner_key = client.post(submit_url, data=json.dumps(payload), content_type="application/json")
    assert missing_owner_key.status_code == 400

    queue.public_key = "OWNER_PUBLIC_KEY"
    queue.save(update_fields=["public_key"])
    missing_customer_key = client.post(submit_url, data=json.dumps(payload), content_type="application/json")
    assert missing_customer_key.status_code == 400

    customer.public_key = "CUSTOMER_PUBLIC_KEY"
    customer.save(update_fields=["public_key"])
    ok = client.post(submit_url, data=json.dumps(payload), content_type="application/json")
    assert ok.status_code == 200

    customer.refresh_from_db()
    stored = json.loads(customer.info)
    assert stored == payload


@pytest.mark.django_db
def test_e2ee_submit_rejects_empty_encrypted_fields(client, queue, customer_user):
    customer = Customer.objects.create(user=customer_user, queue=queue, public_key="CUSTOMER_KEY")
    queue.public_key = "OWNER_KEY"
    queue.save(update_fields=["public_key"])

    client.login(username="alice", password="pass12345")
    submit_url = reverse("queueapp:submit_info", args=[queue.short_id])

    empty_payload = {"to_owner": "", "to_customer": "   "}
    response = client.post(submit_url, data=json.dumps(empty_payload), content_type="application/json")
    assert response.status_code == 400

    customer.refresh_from_db()
    assert customer.info is None


@pytest.mark.django_db
def test_join_post_does_not_store_plaintext_info(client, queue, customer_user):
    customer = Customer.objects.create(user=customer_user, queue=queue)
    customer.info = None
    customer.save(update_fields=["info"])

    client.login(username="alice", password="pass12345")
    join_url = reverse("queueapp:join_queue", args=[queue.short_id])

    response = client.post(join_url, {"info": "plaintext-note"})
    assert response.status_code in {200, 302}

    customer.refresh_from_db()
    assert customer.info is None


@pytest.mark.django_db
def test_register_public_key_strips_whitespace(client, queue, customer_user):
    customer = Customer.objects.create(user=customer_user, queue=queue)
    client.login(username="alice", password="pass12345")

    register_url = reverse("queueapp:register_public_key", args=[queue.short_id])
    response = client.post(
        register_url,
        data=json.dumps({"public_key": "  PUBKEY123  "}),
        content_type="application/json",
    )

    assert response.status_code == 200
    customer.refresh_from_db()
    assert customer.public_key == "PUBKEY123"
