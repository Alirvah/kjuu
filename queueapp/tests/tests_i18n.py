import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_set_language_switches_cookie(client):
    set_lang_url = reverse("set_language")

    to_en = client.post(set_lang_url, data={"language": "en", "next": "/"})
    assert to_en.status_code == 302
    assert to_en.url == "/"
    assert to_en.cookies["django_language"].value == "en"

    to_sk = client.post(set_lang_url, data={"language": "sk", "next": "/"})
    assert to_sk.status_code == 302
    assert to_sk.cookies["django_language"].value == "sk"


@pytest.mark.django_db
def test_home_page_is_translated_between_en_and_sk(client):
    home_url = reverse("queueapp:home")

    client.cookies["django_language"] = "en"
    en_response = client.get(home_url)
    assert en_response.status_code == 200
    assert "Stop waiting in line" in en_response.content.decode("utf-8")

    client.cookies["django_language"] = "sk"
    sk_response = client.get(home_url)
    assert sk_response.status_code == 200
    assert "Prestaňte čakať v rade" in sk_response.content.decode("utf-8")


@pytest.mark.django_db
def test_legal_pages_render_in_both_languages(client):
    privacy_url = reverse("queueapp:privacy")
    terms_url = reverse("queueapp:terms")

    client.cookies["django_language"] = "en"
    privacy_en = client.get(privacy_url).content.decode("utf-8")
    terms_en = client.get(terms_url).content.decode("utf-8")
    assert "Privacy Policy" in privacy_en
    assert "Terms of Service" in terms_en

    client.cookies["django_language"] = "sk"
    privacy_sk = client.get(privacy_url).content.decode("utf-8")
    terms_sk = client.get(terms_url).content.decode("utf-8")
    assert "Zásady ochrany osobných údajov" in privacy_sk
    assert "Podmienky používania" in terms_sk
