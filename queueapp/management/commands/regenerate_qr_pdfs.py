from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.translation import override

from queueapp.models import Queue
from queueapp.utils import generate_kjuu_pdf, get_pdf_locale_strings, normalize_supported_language


def _default_base_url():
    domain = (getattr(settings, "DOMAIN_NAME", "") or "").strip()
    if not domain:
        return "https://localhost"
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}".rstrip("/")


class Command(BaseCommand):
    help = "Regenerate QR PDF files for queues after QR/PDF layout updates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default=_default_base_url(),
            help="Base URL for QR join link, e.g. https://kjuu.sk",
        )
        parser.add_argument(
            "--queue",
            action="append",
            dest="queues",
            help="Regenerate only selected queue short_id (repeatable).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Regenerate only queues that do not have a stored QR PDF.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which queues would be regenerated without writing files.",
        )
        parser.add_argument(
            "--language",
            help="Override language for all generated PDF labels (e.g. sk or en).",
        )

    def handle(self, *args, **options):
        base_url = str(options["base_url"]).strip().rstrip("/")
        if not base_url:
            self.stderr.write(self.style.ERROR("Base URL cannot be empty."))
            return
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"

        selected = options.get("queues") or []
        short_ids = [value.upper().strip() for value in selected if str(value).strip()]

        queryset = Queue.objects.select_related("owner").all().order_by("short_id")
        if short_ids:
            queryset = queryset.filter(short_id__in=short_ids)

        total = queryset.count()
        dry_run = bool(options["dry_run"])
        regenerated = 0
        skipped = 0
        language_override = options.get("language")
        if language_override:
            language_override = normalize_supported_language(language_override)
        default_language = normalize_supported_language(getattr(settings, "LANGUAGE_CODE", "sk"))

        for queue in queryset:
            if options["only_missing"] and queue.qr_code:
                skipped += 1
                continue

            language = language_override or normalize_supported_language(queue.qr_language or default_language)
            with override(language):
                pdf_locale = get_pdf_locale_strings(language)
                qr_message = pdf_locale["default_description"]
                title = f"{pdf_locale['default_title']} - {settings.DOMAIN_NAME}"

                queue_url = f"{base_url}/queue/go/?queue_id={queue.short_id}"
                if dry_run:
                    self.stdout.write(f"[DRY-RUN] {queue.short_id} ({language}): {queue_url}")
                    regenerated += 1
                    continue

                if queue.qr_code:
                    queue.qr_code.delete(save=False)

                pdf_buffer = generate_kjuu_pdf(
                    queue_url,
                    title=title,
                    description=qr_message,
                    name=queue.name,
                    short_code=queue.short_id,
                )
                filename = f"{queue.short_id}.pdf"
                queue.qr_code.save(filename, ContentFile(pdf_buffer.read()))
                if queue.qr_language != language:
                    queue.qr_language = language
                    queue.save(update_fields=["qr_language"])
                regenerated += 1
                self.stdout.write(self.style.SUCCESS(f"Regenerated {queue.short_id} ({language})"))

        self.stdout.write(
            f"Done. total={total}, regenerated={regenerated}, skipped={skipped}, dry_run={dry_run}"
        )
