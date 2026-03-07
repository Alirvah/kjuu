from io import BytesIO
from datetime import UTC, datetime

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from django.utils.translation import get_language

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def generate_qr_code(url):
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_wrapped_centered_line(c, text, font_name, font_size, y, width, max_width):
    words = text.split()
    if not words:
        return y

    c.setFont(font_name, font_size)
    lines = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        if c.stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)

    for line in lines:
        text_width = c.stringWidth(line, font_name, font_size)
        c.drawString((width - text_width) / 2, y, line)
        y -= font_size * 1.35
    return y


def _is_slovak_language(language_code=None):
    lang = (language_code or get_language() or "").lower()
    return lang.startswith("sk")


def normalize_supported_language(language_code=None):
    return "sk" if _is_slovak_language(language_code) else "en"


def get_pdf_locale_strings(language_code=None):
    if normalize_supported_language(language_code) == "sk":
        return {
            "default_title": "Virtuálny rad",
            "default_description": "Naskenujte tento QR kód pre pripojenie do virtuálneho radu:",
            "tagline": "Naskenujte. Pripojte sa. Obslúžte.",
            "queue_code": "Kód radu",
            "join_url": "Odkaz pre vstup",
            "generated": "Vygenerované",
        }

    return {
        "default_title": "Virtual queue",
        "default_description": "Scan this QR code to join the virtual queue:",
        "tagline": "Scan. Join. Serve.",
        "queue_code": "Queue code",
        "join_url": "Join URL",
        "generated": "Generated",
    }


def generate_kjuu_pdf(
    url,
    title=None,
    description=None,
    name=None,
    short_code=None,
    tagline=None,
    queue_code_label=None,
    join_url_label=None,
    generated_label=None,
):
    locale_strings = get_pdf_locale_strings()
    buffer = BytesIO()
    width, height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    margin = 16 * mm
    card_width = width - (2 * margin)
    card_bottom = 20 * mm
    card_top = height - (20 * mm)
    card_height = card_top - card_bottom

    primary = colors.HexColor("#0F6AD8")
    accent = colors.HexColor("#15AABF")
    border = colors.HexColor("#CEDBEA")
    soft_bg = colors.HexColor("#F4F8FD")
    dark = colors.HexColor("#13253A")

    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, stroke=0, fill=1)

    c.setStrokeColor(border)
    c.setLineWidth(1.1)
    c.roundRect(margin, card_bottom, card_width, card_height, 12, stroke=1, fill=0)

    header_h = 34 * mm
    c.setFillColor(primary)
    c.roundRect(margin, card_top - header_h, card_width, header_h, 12, stroke=0, fill=1)
    c.setFillColor(accent)
    c.rect(margin, card_top - header_h, card_width, header_h * 0.35, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.circle(margin + 14 * mm, card_top - (header_h / 2), 8.5 * mm, stroke=0, fill=1)
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(margin + 14 * mm, card_top - (header_h / 2) - 3.5, "KJ")

    c.setFillColor(colors.white)
    resolved_title = title or locale_strings["default_title"]
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin + 29 * mm, card_top - 20 * mm, resolved_title)
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#DCEAFF"))
    c.drawString(margin + 29 * mm, card_top - 26.5 * mm, tagline or locale_strings["tagline"])

    content_top = card_top - header_h - (8 * mm)
    c.setFillColor(dark)
    if name:
        c.setFont("Helvetica-Bold", 19)
        c.drawCentredString(width / 2, content_top, name)
        content_top -= 8.5 * mm

    if description or locale_strings["default_description"]:
        c.setFillColor(colors.HexColor("#4A617A"))
        content_top = _draw_wrapped_centered_line(
            c,
            description or locale_strings["default_description"],
            "Helvetica",
            11,
            content_top,
            width,
            max_width=card_width - (22 * mm),
        )
        content_top -= 2 * mm

    qr_frame_size = 88 * mm
    qr_frame_x = (width - qr_frame_size) / 2
    qr_frame_y = content_top - qr_frame_size
    c.setFillColor(soft_bg)
    c.roundRect(qr_frame_x, qr_frame_y, qr_frame_size, qr_frame_size, 10, stroke=0, fill=1)
    c.setStrokeColor(border)
    c.roundRect(qr_frame_x, qr_frame_y, qr_frame_size, qr_frame_size, 10, stroke=1, fill=0)

    qr_buffer = generate_qr_code(url)
    qr_img = ImageReader(qr_buffer)
    qr_size = 76 * mm
    qr_x = (width - qr_size) / 2
    qr_y = qr_frame_y + ((qr_frame_size - qr_size) / 2)
    c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")

    after_qr_y = qr_frame_y - (7 * mm)
    if short_code:
        c.setFillColor(colors.HexColor("#4A617A"))
        c.setFont("Helvetica", 11)
        c.drawCentredString(width / 2, after_qr_y, queue_code_label or locale_strings["queue_code"])

        code_box_w = 52 * mm
        code_box_h = 15 * mm
        code_box_x = (width - code_box_w) / 2
        code_box_y = after_qr_y - code_box_h - 2
        c.setFillColor(colors.HexColor("#EAF3FF"))
        c.roundRect(code_box_x, code_box_y, code_box_w, code_box_h, 7, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#BDD6F7"))
        c.roundRect(code_box_x, code_box_y, code_box_w, code_box_h, 7, stroke=1, fill=0)
        c.setFillColor(primary)
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width / 2, code_box_y + 4.4 * mm, short_code)
        footer_y = code_box_y - (8.5 * mm)
    else:
        footer_y = after_qr_y - (8.5 * mm)

    c.setFillColor(colors.HexColor("#6D8097"))
    c.setFont("Helvetica", 9)
    footer_text = (
        f"{join_url_label or locale_strings['join_url']}: " + (url if len(url) <= 78 else (url[:75] + "..."))
    )
    c.drawCentredString(width / 2, footer_y, footer_text)
    c.drawCentredString(
        width / 2,
        footer_y - 11,
        f"{generated_label or locale_strings['generated']} {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
    )

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
