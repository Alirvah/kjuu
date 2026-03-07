from django.test.client import RequestFactory
from django.utils import translation

from queueapp.utils import (
    generate_kjuu_pdf,
    generate_qr_code,
    get_client_ip,
    get_pdf_locale_strings,
    normalize_supported_language,
)


def test_get_client_ip_prefers_forwarded_header():
    request = RequestFactory().get(
        "/",
        HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.2",
        REMOTE_ADDR="127.0.0.1",
    )
    assert get_client_ip(request) == "203.0.113.5"


def test_get_client_ip_falls_back_to_remote_addr():
    request = RequestFactory().get("/", REMOTE_ADDR="198.51.100.9")
    assert get_client_ip(request) == "198.51.100.9"


def test_generate_qr_code_returns_png_bytes():
    buffer = generate_qr_code("https://example.test/queue/go/?queue_id=ABCD")
    data = buffer.read()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 100


def test_language_normalization_and_locale_strings():
    assert normalize_supported_language("sk-SK") == "sk"
    assert normalize_supported_language("sk") == "sk"
    assert normalize_supported_language("en-US") == "en"
    assert normalize_supported_language("de") == "en"
    assert normalize_supported_language(None) in {"sk", "en"}

    sk_strings = get_pdf_locale_strings("sk")
    en_strings = get_pdf_locale_strings("en")
    assert sk_strings["default_title"].startswith("Virtuálny rad")
    assert en_strings["default_title"].startswith("Virtual queue")
    assert sk_strings["join_url"] != en_strings["join_url"]


def test_generate_kjuu_pdf_smoke_and_overrides():
    with translation.override("en"):
        default_pdf = generate_kjuu_pdf("https://example.test/queue/go/?queue_id=ABCD")
    default_bytes = default_pdf.read()
    assert default_bytes.startswith(b"%PDF")
    assert len(default_bytes) > 1500

    with translation.override("sk"):
        custom_pdf = generate_kjuu_pdf(
            "https://example.test/queue/go/?queue_id=ABCD",
            title="Custom title",
            description="Custom description",
            name="Queue name",
            short_code="ABCD",
            tagline="Custom tagline",
            queue_code_label="Queue label",
            join_url_label="Join label",
            generated_label="Generated label",
        )
    custom_bytes = custom_pdf.read()
    assert custom_bytes.startswith(b"%PDF")
    assert len(custom_bytes) > 1500
