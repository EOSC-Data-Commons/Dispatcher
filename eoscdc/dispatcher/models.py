from django.db import models

class Request(models.Model):
    request_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20)  # e.g., "processing", "ready"
    redirect_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.request_id

# Create your models here.
