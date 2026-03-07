import secrets
import string
from django.db import models
from django.conf import settings
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from datetime import timedelta

class Queue(models.Model):
    name = models.CharField(max_length=31)
    short_id = models.CharField(max_length=6, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    color_hex = models.CharField(max_length=7, blank=True, null=True)
    served_count = models.PositiveIntegerField(default=0)
    total_wait_time = models.DurationField(default=timedelta)
    active = models.BooleanField(default=True)
    qr_code = models.FileField(upload_to='queue_codes/', blank=True, null=True)
    public_key = models.TextField(blank=True, null=True)

    owner = models.OneToOneField( settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='queue')

    @property
    def average_wait_time(self):
        return self.total_wait_time / self.served_count if self.served_count > 0 else timedelta(0)

    def save(self, *args, **kwargs):
        if not self.short_id:
            self.short_id = self.generate_unique_short_id()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_unique_short_id():
        allowed = "ACDEFGHJKLMNPQRSTUVWXYZ234679"
        while True:
            code = ''.join(secrets.choice(allowed) for _ in range(4))
            if not Queue.objects.filter(short_id=code).exists():
                return code

    def is_empty(self):
        return not self.customers.exists()

    def __str__(self):
        return f"{self.name} ({self.short_id})"

@receiver(post_delete, sender=Queue)
def delete_pdf_file(sender, instance, **kwargs):
    if instance.qr_code:
        instance.qr_code.delete(False)  # False = keep the model delete separate


class Customer(models.Model):

    secret_id = models.CharField(max_length=6, unique=True)
    called_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    info = models.TextField(max_length=1024, blank=True, null=True)
    public_key = models.TextField(blank=True, null=True)

    user = models.OneToOneField( settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='active_customer')
    queue = models.ForeignKey( Queue, on_delete=models.CASCADE, related_name='customers')

    @property
    def wait_time(self):
        if self.called_at:
        	return self.called_at - self.created_at
        return timedelta(0)

    @property
    def position(self):
        if self.called_at:
            return None  # Only waiting customers have a queue position
        return self.queue.customers.filter(
            called_at__isnull=True,
            created_at__lt=self.created_at
        ).count() + 1

    class Meta:
        unique_together = ('queue', 'user')
        ordering = ['pk']

    def save(self, *args, **kwargs):
        if not self.secret_id:
            self.secret_id = secrets.token_hex(3).upper()[:6]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} in {self.queue.short_id}"
