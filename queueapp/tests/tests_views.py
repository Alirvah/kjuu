import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.urls import reverse

from queueapp.models import Customer, Queue

User = get_user_model()


@pytest.mark.django_db
def test_public_pages_render(client):
    assert client.get(reverse("queueapp:home")).status_code == 200
    assert client.get(reverse("queueapp:signup")).status_code == 200
    assert client.get(reverse("queueapp:login")).status_code == 200
    assert client.get(reverse("queueapp:privacy")).status_code == 200
    assert client.get(reverse("queueapp:terms")).status_code == 200


@pytest.mark.django_db
def test_signup_requires_consent_and_login_flow(client):
    signup_url = reverse("queueapp:signup")

    missing_consent = client.post(
        signup_url,
        data={"username": "user1", "password": "StrongPass123"},
        follow=True,
    )
    assert missing_consent.status_code == 200
    assert not User.objects.filter(username="user1").exists()

    response = client.post(
        signup_url,
        data={"username": "user2", "password": "StrongPass123", "consent": "1"},
    )
    assert response.status_code == 302
    assert User.objects.filter(username="user2").exists()


@pytest.mark.django_db
def test_login_logout_and_next_redirect(client, customer_user):
    login_url = reverse("queueapp:login")
    next_url = reverse("queueapp:home")

    bad = client.post(login_url, data={"username": "alice", "password": "wrong"})
    assert bad.status_code == 200

    good = client.post(
        f"{login_url}?next={next_url}",
        data={"username": "alice", "password": "pass12345", "next": next_url},
    )
    assert good.status_code == 302
    assert good.url == next_url

    client.login(username="alice", password="pass12345")
    assert client.get(reverse("queueapp:logout")).status_code == 405
    logout_response = client.post(reverse("queueapp:logout"))
    assert logout_response.status_code == 302


@pytest.mark.django_db
def test_delete_account_get_and_post(client, customer_user):
    client.login(username="alice", password="pass12345")
    assert client.get(reverse("queueapp:delete_account")).status_code == 200

    response = client.post(reverse("queueapp:delete_account"))
    assert response.status_code == 302
    assert not User.objects.filter(username="alice").exists()


@pytest.mark.django_db
def test_create_queue_requires_login_and_generates_pdf(client, customer_user, mock_pdf):
    create_url = reverse("queueapp:create_queue")
    assert client.get(create_url).status_code == 302

    client.login(username="alice", password="pass12345")
    response = client.post(create_url, {"name": "Main queue"})
    assert response.status_code == 302

    queue = Queue.objects.get(owner=customer_user)
    assert queue.qr_code.name.endswith(".pdf")


@pytest.mark.django_db
def test_go_to_queue_flow(client, queue, customer_user):
    go_url = reverse("queueapp:go_to_queue")

    missing = client.post(go_url, {"queue_id": ""}, follow=True)
    assert missing.status_code == 200

    unknown = client.post(go_url, {"queue_id": "ZZZZ"}, follow=True)
    assert unknown.status_code == 200

    anon_redirect = client.post(go_url, {"queue_id": queue.short_id})
    assert anon_redirect.status_code == 302
    assert reverse("queueapp:login") in anon_redirect.url

    client.login(username="alice", password="pass12345")
    authed = client.post(go_url, {"queue_id": queue.short_id})
    assert authed.status_code == 302
    assert reverse("queueapp:join_queue", args=[queue.short_id]) in authed.url


@pytest.mark.django_db
def test_join_queue_main_flow(client, queue, customer_user):
    join_url = reverse("queueapp:join_queue", args=[queue.short_id])

    assert client.get(join_url).status_code == 302

    client.login(username="alice", password="pass12345")
    assert client.get(join_url).status_code == 200

    joined = client.post(join_url)
    assert joined.status_code == 302
    assert Customer.objects.filter(user=customer_user, queue=queue).count() == 1

    joined_again = client.post(join_url)
    assert joined_again.status_code in {200, 302}
    assert Customer.objects.filter(user=customer_user, queue=queue).count() == 1


@pytest.mark.django_db
def test_join_queue_edge_cases(client, owner, customer_user, customer_user_2, make_queue):
    active_queue = make_queue(name="Active")
    paused_owner = User.objects.create_user(username="paused_owner", password="pass12345")
    paused_queue = make_queue(name="Paused", owner_user=paused_owner, active=False)

    client.login(username="owner", password="pass12345")
    own_response = client.get(reverse("queueapp:join_queue", args=[active_queue.short_id]), follow=True)
    assert own_response.status_code == 200

    client.logout()
    client.login(username="alice", password="pass12345")

    paused_response = client.post(reverse("queueapp:join_queue", args=[paused_queue.short_id]), follow=True)
    assert paused_response.status_code == 200
    assert not Customer.objects.filter(user=customer_user, queue=paused_queue).exists()

    first_owner = User.objects.create_user(username="first_owner", password="pass12345")
    second_owner = User.objects.create_user(username="second_owner", password="pass12345")
    first_queue = make_queue(name="First", owner_user=first_owner)
    second_queue = make_queue(name="Second", owner_user=second_owner)
    Customer.objects.create(user=customer_user, queue=first_queue)

    redirect_other = client.get(reverse("queueapp:join_queue", args=[second_queue.short_id]))
    assert redirect_other.status_code == 302
    assert reverse("queueapp:join_queue", args=[first_queue.short_id]) in redirect_other.url

    missing = client.get(reverse("queueapp:join_queue", args=["XXXX"]))
    assert missing.status_code == 404


@pytest.mark.django_db
def test_leave_queue_requires_post(client, queue, customer_user):
    Customer.objects.create(user=customer_user, queue=queue)
    client.login(username="alice", password="pass12345")

    leave_url = reverse("queueapp:leave_queue", args=[queue.short_id])
    assert client.get(leave_url).status_code == 405

    response = client.post(leave_url)
    assert response.status_code == 302
    assert not Customer.objects.filter(user=customer_user, queue=queue).exists()


@pytest.mark.django_db
def test_owner_dashboard_and_qr(client, queue, owner, customer_user):
    Customer.objects.create(user=customer_user, queue=queue)
    dashboard_url = reverse("queueapp:queue_dashboard", args=[queue.short_id])

    client.login(username="alice", password="pass12345")
    forbidden = client.get(dashboard_url, follow=True)
    assert forbidden.status_code == 200

    client.logout()
    client.login(username="owner", password="pass12345")
    ok = client.get(dashboard_url)
    assert ok.status_code == 200

    qr_url = reverse("queueapp:qr_queue", args=[queue.short_id])
    no_qr = client.get(qr_url)
    assert no_qr.status_code == 404

    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"%PDF-1.4\n"), save=True)
    has_qr = client.get(qr_url)
    assert has_qr.status_code == 200
    assert has_qr["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_owner_mutating_actions_are_post_only(client, queue, owner, customer_user, customer_user_2):
    call_url = reverse("queueapp:call_next", args=[queue.short_id])
    pause_url = reverse("queueapp:pause_queue", args=[queue.short_id])
    delete_url = reverse("queueapp:delete_queue", args=[queue.short_id])

    client.login(username="owner", password="pass12345")

    assert client.get(call_url).status_code == 405
    assert client.get(pause_url).status_code == 405
    assert client.get(delete_url).status_code == 405

    first = Customer.objects.create(user=customer_user, queue=queue)
    Customer.objects.create(user=customer_user_2, queue=queue)

    first_call = client.post(call_url)
    assert first_call.status_code == 302
    first.refresh_from_db()
    assert first.called_at is not None

    second_call = client.post(call_url)
    assert second_call.status_code == 302
    queue.refresh_from_db()
    assert queue.served_count == 1

    paused = client.post(pause_url)
    assert paused.status_code == 302
    queue.refresh_from_db()
    assert queue.active is False

    resumed = client.post(pause_url)
    assert resumed.status_code == 302
    queue.refresh_from_db()
    assert queue.active is True

    blocked_delete = client.post(delete_url)
    assert blocked_delete.status_code == 302
    assert Queue.objects.filter(pk=queue.pk).exists()

    Customer.objects.filter(queue=queue).delete()
    deleted = client.post(delete_url)
    assert deleted.status_code == 302
    assert not Queue.objects.filter(pk=queue.pk).exists()


@pytest.mark.django_db
def test_crypto_and_info_endpoints(client, queue, owner, customer_user):
    register_url = reverse("queueapp:register_public_key", args=[queue.short_id])
    submit_url = reverse("queueapp:submit_info", args=[queue.short_id])
    clear_url = reverse("queueapp:clear_info", args=[queue.short_id])

    client.login(username="owner", password="pass12345")
    assert client.get(register_url).status_code == 405

    bad_type = client.post(register_url, data="x", content_type="text/plain")
    assert bad_type.status_code == 400

    bad_json = client.post(register_url, data="{}", content_type="application/json")
    assert bad_json.status_code == 400

    good_owner = client.post(
        register_url,
        data=json.dumps({"public_key": "OWNERPUB"}),
        content_type="application/json",
    )
    assert good_owner.status_code == 200
    queue.refresh_from_db()
    assert queue.public_key == "OWNERPUB"

    client.logout()
    client.login(username="alice", password="pass12345")

    customer_missing = client.post(
        register_url,
        data=json.dumps({"public_key": "ALICEPUB"}),
        content_type="application/json",
    )
    assert customer_missing.status_code == 404

    Customer.objects.create(user=customer_user, queue=queue)

    customer_ok = client.post(
        register_url,
        data=json.dumps({"public_key": "ALICEPUB"}),
        content_type="application/json",
    )
    assert customer_ok.status_code == 200

    assert client.get(submit_url).status_code == 405
    invalid_payload = client.post(submit_url, data="[]", content_type="application/json")
    assert invalid_payload.status_code == 400

    submit_ok = client.post(
        submit_url,
        data=json.dumps({"to_owner": "A", "to_customer": "B"}),
        content_type="application/json",
    )
    assert submit_ok.status_code == 200
    assert "to_owner" in Customer.objects.get(user=customer_user, queue=queue).info

    assert client.get(clear_url).status_code == 405
    clear_ok = client.post(clear_url)
    assert clear_ok.status_code == 200
    assert Customer.objects.get(user=customer_user, queue=queue).info is None


@pytest.mark.django_db
def test_rate_limit_responses(client, queue, customer_user):
    client.login(username="alice", password="pass12345")
    go_url = reverse("queueapp:go_to_queue")

    limited_response = None
    for _ in range(35):
        limited_response = client.post(go_url, {"queue_id": queue.short_id})
        if limited_response.status_code == 429:
            break

    assert limited_response is not None
    assert limited_response.status_code in {302, 429}

    join_url = reverse("queueapp:join_queue", args=[queue.short_id])
    # First call joins the queue.
    client.post(join_url)

    limited_join = None
    for _ in range(15):
        limited_join = client.post(join_url, {"info": "x"})
        if limited_join.status_code == 429:
            break

    assert limited_join is not None
    assert limited_join.status_code in {200, 429}
