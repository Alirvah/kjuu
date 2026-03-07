import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from queueapp.models import Customer, Queue
from queueapp.views import MAX_CIPHERTEXT_LENGTH, MAX_PUBLIC_KEY_LENGTH

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
def test_register_public_key_rejects_oversized_key_and_preserves_existing_values(
    client, queue, owner, customer_user
):
    customer = Customer.objects.create(
        user=customer_user,
        queue=queue,
        public_key="CUSTOMER_OLD",
        public_key_version=2,
    )
    queue.public_key = "OWNER_OLD"
    queue.public_key_version = 3
    queue.save(update_fields=["public_key", "public_key_version"])
    oversized_key = "X" * (MAX_PUBLIC_KEY_LENGTH + 1)
    url = reverse("queueapp:register_public_key", args=[queue.short_id])

    client.login(username="owner", password="pass12345")
    owner_rejected = client.post(
        url,
        data=json.dumps({"public_key": oversized_key}),
        content_type="application/json",
    )
    assert owner_rejected.status_code == 400

    queue.refresh_from_db()
    assert queue.public_key == "OWNER_OLD"
    assert queue.public_key_version == 3

    client.logout()
    client.login(username="alice", password="pass12345")
    customer_rejected = client.post(
        url,
        data=json.dumps({"public_key": oversized_key}),
        content_type="application/json",
    )
    assert customer_rejected.status_code == 400

    customer.refresh_from_db()
    assert customer.public_key == "CUSTOMER_OLD"
    assert customer.public_key_version == 2


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
    customer = Customer.objects.create(
        user=customer_user,
        queue=queue,
        public_key="CUSTOMER_KEY",
        public_key_version=1,
    )
    queue.public_key = "OWNER_KEY"
    queue.public_key_version = 1
    queue.save(update_fields=["public_key", "public_key_version"])

    client.login(username="alice", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    wrong_type = client.post(url, data="{}", content_type="text/plain")
    assert wrong_type.status_code == 400

    bad_json = client.post(url, data="{", content_type="application/json")
    assert bad_json.status_code == 400

    missing_field = client.post(
        url,
        data=json.dumps({"to_owner": "A", "to_customer": "B"}),
        content_type="application/json",
    )
    assert missing_field.status_code == 400

    non_string_field = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": 123,
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_123456789012",
            }
        ),
        content_type="application/json",
    )
    assert non_string_field.status_code == 400

    missing_versions = client.post(
        url,
        data=json.dumps({"to_owner": "A", "to_customer": "B", "nonce": "nonce_123456789012"}),
        content_type="application/json",
    )
    assert missing_versions.status_code == 400

    bad_nonce = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A",
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "short",
            }
        ),
        content_type="application/json",
    )
    assert bad_nonce.status_code == 400

    customer.refresh_from_db()
    assert customer.info is None


@pytest.mark.django_db
def test_submit_info_owner_cannot_submit_as_customer(client, queue, owner):
    client.login(username="owner", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    response = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A",
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_123456789012",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_submit_info_rejects_replay_and_key_version_mismatch(client, queue, customer_user):
    customer = Customer.objects.create(
        user=customer_user,
        queue=queue,
        public_key="CUSTOMER_KEY",
        public_key_version=1,
    )
    queue.public_key = "OWNER_KEY"
    queue.public_key_version = 1
    queue.save(update_fields=["public_key", "public_key_version"])

    client.login(username="alice", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])
    payload = {
        "to_owner": "A",
        "to_customer": "B",
        "owner_key_version": 1,
        "customer_key_version": 1,
        "nonce": "nonce_REPLAY_123456",
    }
    first = client.post(url, data=json.dumps(payload), content_type="application/json")
    assert first.status_code == 200

    replay = client.post(url, data=json.dumps(payload), content_type="application/json")
    assert replay.status_code == 400

    mismatch_payload = {
        "to_owner": "A",
        "to_customer": "B",
        "owner_key_version": 2,
        "customer_key_version": 1,
        "nonce": "nonce_MISMATCH_1234",
    }
    mismatch = client.post(url, data=json.dumps(mismatch_payload), content_type="application/json")
    assert mismatch.status_code == 400

    customer.refresh_from_db()
    assert customer.info is not None


@pytest.mark.django_db
def test_submit_info_rejects_oversized_ciphertext_and_invalid_nonce_charset(
    client, queue, customer_user
):
    customer = Customer.objects.create(
        user=customer_user,
        queue=queue,
        public_key="CUSTOMER_KEY",
        public_key_version=1,
    )
    queue.public_key = "OWNER_KEY"
    queue.public_key_version = 1
    queue.save(update_fields=["public_key", "public_key_version"])
    client.login(username="alice", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    oversized = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A" * (MAX_CIPHERTEXT_LENGTH + 1),
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_VALID1234567",
            }
        ),
        content_type="application/json",
    )
    assert oversized.status_code == 400

    bad_nonce_charset = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A",
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce.BAD_char_123",
            }
        ),
        content_type="application/json",
    )
    assert bad_nonce_charset.status_code == 400

    customer.refresh_from_db()
    assert customer.info is None
    assert customer.used_nonces.count() == 0


@pytest.mark.django_db
def test_submit_info_invalid_payload_does_not_overwrite_existing_note(client, queue, customer_user):
    customer = Customer.objects.create(
        user=customer_user,
        queue=queue,
        public_key="CUSTOMER_KEY",
        public_key_version=1,
    )
    queue.public_key = "OWNER_KEY"
    queue.public_key_version = 1
    queue.save(update_fields=["public_key", "public_key_version"])
    client.login(username="alice", password="pass12345")
    url = reverse("queueapp:submit_info", args=[queue.short_id])

    valid = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A1",
                "to_customer": "B1",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_VALID_existing",
            }
        ),
        content_type="application/json",
    )
    assert valid.status_code == 200

    customer.refresh_from_db()
    original_info = customer.info

    invalid = client.post(
        url,
        data=json.dumps(
            {
                "to_owner": "A2",
                "to_customer": "B" * (MAX_CIPHERTEXT_LENGTH + 1),
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_VALID_new_note",
            }
        ),
        content_type="application/json",
    )
    assert invalid.status_code == 400

    customer.refresh_from_db()
    assert customer.info == original_info
    assert customer.used_nonces.count() == 1


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
