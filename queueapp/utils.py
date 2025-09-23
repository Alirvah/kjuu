from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
import qrcode


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def generate_qr_code(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def generate_kjuu_pdf(url, title=None, description=None, name=None, short_code=None):
    buffer = BytesIO()
    width, height = A4
    c = canvas.Canvas(buffer, pagesize=A4)

    if title:
        c.setFont("Helvetica-Bold", 24)
        title_width = c.stringWidth(title, "Helvetica-Bold", 24)
        c.drawString((width - title_width) / 2, height - 80, title)

    # QR Code image (centered)
    qr_buffer = generate_qr_code(url)
    qr_img = ImageReader(qr_buffer)
    qr_size = 300  # size in points

    qr_x = (width - qr_size) / 2
    qr_y = height / 2  # adjust as needed
    c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

    if description:
        c.setFont("Helvetica", 12)
        text_width = c.stringWidth(description, "Helvetica", 12)
        c.drawString((width - text_width) / 2, qr_y - 40, description)

    if name:
        c.setFont("Helvetica-Bold", 20)
        text_width = c.stringWidth(name, "Helvetica", 20)
        c.drawString((width - text_width) / 2, qr_y - 70, name)

    if short_code:
        c.setFont("Helvetica", 12)
        c.drawCentredString(width / 2, qr_y - 140, "Kód radu:")

        c.setFont("Helvetica", 60)
        text_width = c.stringWidth(short_code, "Helvetica", 60)
        c.drawString((width - text_width) / 2, qr_y - 200, short_code)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

