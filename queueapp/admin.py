from django.contrib import admin, messages
from queueapp.models import Queue, Customer
from django.db.models import Count
from django.conf import settings
from queueapp.utils import generate_kjuu_pdf
from django.core.files.base import ContentFile
import os

@admin.action(description="Regenerate & attach QR PDF for selected queues")
def regenerate_qr_pdf(modeladmin, request, queryset):
    base_url = settings.HTTPS_DOMAIN_NAME
    ok, failed = 0, 0

    for q in queryset:
        try:
            if q.qr_code:
                try:
                    old_path = q.qr_code.path
                except Exception:
                    old_path = None
                q.qr_code.delete(save=False)
                if old_path and os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            queue_url = f"{base_url}/queue/go/?queue_id={q.short_id}"
            qr_message = "Naskenovaím tohto QR kódu sa zaradíte do virtuálneho radu:"
            title = f"Virtuálny rad - {settings.DOMAIN_NAME}"

            pdf_buffer = generate_kjuu_pdf(
                queue_url,
                title=title,
                description=qr_message,
                name=q.name,
                short_code=q.short_id,
            )

            try:
                pdf_buffer.seek(0)
                data = pdf_buffer.read()
            except Exception:
                data = pdf_buffer  # already bytes

            filename = f"{q.short_id}.pdf"
            q.qr_code.save(filename, ContentFile(data), save=True)
            ok += 1
        except Exception as e:
            failed += 1
            modeladmin.message_user(
                request, f"Queue {q.pk} ({q.name}) failed: {e}", level=messages.ERROR
            )

    if ok:
        modeladmin.message_user(
            request, f"Regenerated QR PDFs for {ok} queue(s).", level=messages.SUCCESS
        )
    if failed:
        modeladmin.message_user(
            request, f"{failed} queue(s) failed. Check errors above.", level=messages.WARNING
        )

@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_id', 'owner', 'customers_count', 'served_count', 'average_wait_time', 'created_at')
    actions = [regenerate_qr_pdf]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_customers_count=Count('customers'))

    def customers_count(self, obj):
        return obj._customers_count
    customers_count.admin_order_field = '_customers_count'
    customers_count.short_description = 'Number of Customers'

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'queue', 'created_at', 'position', 'called_at')

