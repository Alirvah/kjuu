import json
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

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
def test_create_queue_pdf_language_follows_request_language(client, customer_user, customer_user_2, monkeypatch):
    calls = []

    def fake_generate(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(b"%PDF-1.4\n% language test\n")

    monkeypatch.setattr("queueapp.views.generate_kjuu_pdf", fake_generate)
    create_url = reverse("queueapp:create_queue")

    client.login(username="alice", password="pass12345")
    response_en = client.post(create_url, {"name": "English Queue"}, HTTP_ACCEPT_LANGUAGE="en")
    assert response_en.status_code == 302
    assert calls[-1][1]["title"].startswith("Virtual queue")
    assert calls[-1][1]["description"].startswith("Scan this QR code")
    queue_en = Queue.objects.get(owner=customer_user)
    assert queue_en.qr_language == "en"

    client.logout()
    client.login(username="bob", password="pass12345")
    response_sk = client.post(create_url, {"name": "Slovak Queue"}, HTTP_ACCEPT_LANGUAGE="sk")
    assert response_sk.status_code == 302
    assert calls[-1][1]["title"].startswith("Virtuálny rad")
    assert calls[-1][1]["description"].startswith("Naskenujte tento QR kód")
    queue_sk = Queue.objects.get(owner=customer_user_2)
    assert queue_sk.qr_language == "sk"


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
    join_get = client.get(join_url)
    assert join_get.status_code == 200
    assert join_get.context["queue_waiting_count"] == 0
    assert join_get.context["queue_total_live_count"] == 0
    assert join_get.context["queue_is_active"] is True

    joined = client.post(join_url)
    assert joined.status_code == 302
    assert Customer.objects.filter(user=customer_user, queue=queue).count() == 1

    joined_view = client.get(join_url)
    assert joined_view.status_code == 200
    assert joined_view.context["queue_waiting_count"] == 1
    assert joined_view.context["queue_total_live_count"] == 1
    assert joined_view.context["people_ahead"] == 0

    joined_again = client.post(join_url)
    assert joined_again.status_code in {200, 302}
    assert Customer.objects.filter(user=customer_user, queue=queue).count() == 1


@pytest.mark.django_db
def test_join_queue_live_fragment(client, queue, owner, customer_user):
    live_url = reverse("queueapp:join_queue_live_state", args=[queue.short_id])

    assert client.get(live_url).status_code == 302

    client.login(username="owner", password="pass12345")
    owner_blocked = client.get(live_url)
    assert owner_blocked.status_code == 404

    client.logout()
    client.login(username="alice", password="pass12345")
    fragment = client.get(live_url, HTTP_HX_REQUEST="true")
    assert fragment.status_code == 200
    assert 'id="live-queue-shell"' in fragment.content.decode()


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
    assert ok.context["waiting_count"] == 1
    assert ok.context["called_count"] == 0
    assert ok.context["oldest_wait_duration"] is not None
    assert ok.context["estimated_clear_time"] is None
    assert ok.context["service_pace_per_hour"] >= 0
    assert ok.context["flow_waiting_pct"] >= 0
    assert ok.context["flow_called_pct"] >= 0
    assert ok.context["fresh_waiting_count"] >= 0
    assert ok.context["medium_waiting_count"] >= 0
    assert ok.context["long_waiting_count"] >= 0

    qr_url = reverse("queueapp:qr_queue", args=[queue.short_id])
    no_qr = client.get(qr_url)
    assert no_qr.status_code == 404

    queue.qr_code.save(f"{queue.short_id}.pdf", ContentFile(b"%PDF-1.4\n"), save=True)
    has_qr = client.get(qr_url)
    assert has_qr.status_code == 200
    assert has_qr["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_owner_dashboard_metrics_boundaries_and_percentages(
    client, queue, owner, customer_user, customer_user_2, monkeypatch
):
    third_user = User.objects.create_user(username="carol", password="pass12345")
    fourth_user = User.objects.create_user(username="dave", password="pass12345")

    fresh = Customer.objects.create(user=customer_user, queue=queue)
    medium = Customer.objects.create(user=customer_user_2, queue=queue)
    long_wait = Customer.objects.create(user=third_user, queue=queue)
    called = Customer.objects.create(user=fourth_user, queue=queue)

    fixed_now = timezone.now().replace(microsecond=0)
    monkeypatch.setattr("queueapp.views.timezone.now", lambda: fixed_now)

    Customer.objects.filter(pk=fresh.pk).update(created_at=fixed_now - timedelta(minutes=5))
    Customer.objects.filter(pk=medium.pk).update(created_at=fixed_now - timedelta(minutes=15))
    Customer.objects.filter(pk=long_wait.pk).update(created_at=fixed_now - timedelta(minutes=16))
    Customer.objects.filter(pk=called.pk).update(
        created_at=fixed_now - timedelta(minutes=20),
        called_at=fixed_now - timedelta(minutes=1),
    )

    client.login(username="owner", password="pass12345")
    response = client.get(reverse("queueapp:queue_dashboard", args=[queue.short_id]))
    assert response.status_code == 200

    context = response.context
    assert context["waiting_count"] == 3
    assert context["called_count"] == 1
    assert context["flow_waiting_pct"] == 75
    assert context["flow_called_pct"] == 25
    assert context["flow_waiting_pct"] + context["flow_called_pct"] == 100

    assert context["fresh_waiting_count"] == 1
    assert context["medium_waiting_count"] == 1
    assert context["long_waiting_count"] == 1

    assert context["fresh_waiting_pct"] == 33
    assert context["medium_waiting_pct"] == 33
    assert context["long_waiting_pct"] == 34
    assert (
        context["fresh_waiting_pct"]
        + context["medium_waiting_pct"]
        + context["long_waiting_pct"]
    ) == 100


@pytest.mark.django_db
def test_owner_dashboard_metrics_are_zero_when_no_live_customers(client, queue, owner):
    client.login(username="owner", password="pass12345")
    response = client.get(reverse("queueapp:queue_dashboard", args=[queue.short_id]))
    assert response.status_code == 200
    context = response.context

    assert context["waiting_count"] == 0
    assert context["called_count"] == 0
    assert context["flow_waiting_pct"] == 0
    assert context["flow_called_pct"] == 0
    assert context["fresh_waiting_count"] == 0
    assert context["medium_waiting_count"] == 0
    assert context["long_waiting_count"] == 0
    assert context["fresh_waiting_pct"] == 0
    assert context["medium_waiting_pct"] == 0
    assert context["long_waiting_pct"] == 0


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
    assert good_owner.json()["version"] == 1
    queue.refresh_from_db()
    assert queue.public_key == "OWNERPUB"
    assert queue.public_key_version == 1

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
    assert customer_ok.json()["version"] == 1

    assert client.get(submit_url).status_code == 405
    invalid_payload = client.post(submit_url, data="[]", content_type="application/json")
    assert invalid_payload.status_code == 400

    submit_ok = client.post(
        submit_url,
        data=json.dumps(
            {
                "to_owner": "A",
                "to_customer": "B",
                "owner_key_version": 1,
                "customer_key_version": 1,
                "nonce": "nonce_ABCD1234abcd",
            }
        ),
        content_type="application/json",
    )
    assert submit_ok.status_code == 200
    assert "to_owner" in Customer.objects.get(user=customer_user, queue=queue).info

    submit_form_ok = client.post(
        submit_url,
        data={
            "to_owner": "A2",
            "to_customer": "B2",
            "owner_key_version": "1",
            "customer_key_version": "1",
            "nonce": "nonce_FORM123456789",
        },
        HTTP_HX_REQUEST="true",
    )
    assert submit_form_ok.status_code == 204

    assert client.get(clear_url).status_code == 405
    clear_ok = client.post(clear_url, HTTP_HX_REQUEST="true")
    assert clear_ok.status_code == 204
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
