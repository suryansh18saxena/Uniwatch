from django.db import models

class Server(models.Model):
    name = models.CharField(max_length=100, help_text="e.g., Production-Server-1")
    ip_address = models.GenericIPAddressField(unique=True)
    ssh_user = models.CharField(max_length=50, default='ubuntu')
    is_active = models.BooleanField(default=False, help_text="True if Ansible setup is complete")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"