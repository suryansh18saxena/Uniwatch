from django.db import models
import json


class Server(models.Model):
    """
    Represents a user's server/instance that we monitor.
    SSH key is NOT stored — it's used once during setup and then discarded.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Setup Running'),
        ('success', 'Setup Successful'),
        ('failed', 'Setup Failed'),
    ]

    name = models.CharField(max_length=100, help_text="e.g., Production-Server-1")
    ip_address = models.GenericIPAddressField(unique=True)
    ssh_user = models.CharField(max_length=50, default='ubuntu')
    has_containers = models.BooleanField(
        default=False,
        help_text="If True, cAdvisor will also be installed for container monitoring"
    )
    setup_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    setup_logs = models.TextField(blank=True, default='', help_text="Logs from the setup process")
    is_active = models.BooleanField(default=False, help_text="True if monitoring agents are running")
    node_exporter_port = models.IntegerField(default=9100)
    cadvisor_port = models.IntegerField(default=8080)
    auto_fix_enabled = models.BooleanField(
        default=False,
        help_text="If True, self-healing actions will execute automatically on critical alerts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

    @property
    def status_emoji(self):
        return {
            'pending': '⏳',
            'running': '🔄',
            'success': '✅',
            'failed': '❌',
        }.get(self.setup_status, '❓')


class Alert(models.Model):
    """
    Records a triggered alert from the monitoring system.
    Created when a metric crosses its threshold.
    """

    SEVERITY_CHOICES = [
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
        ('auto_fixed', 'Auto-Fixed'),
    ]

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='alerts')
    metric_name = models.CharField(max_length=50, help_text="e.g., cpu_usage, memory_usage, disk_usage")
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default='')
    metric_value = models.FloatField(null=True, blank=True, help_text="The metric value that triggered the alert")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title} on {self.server.name}"


class FixExecution(models.Model):
    """
    Records every self-healing execution attempt.
    Linked to a server and optionally to the alert that triggered it.
    """

    STATUS_CHOICES = [
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
    ]

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='fix_executions')
    alert = models.ForeignKey(Alert, on_delete=models.SET_NULL, null=True, blank=True, related_name='fix_executions')
    metric_name = models.CharField(max_length=50)
    commands_run = models.TextField(
        blank=True, default='[]',
        help_text="JSON array of command result objects"
    )
    summary = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='failed')
    triggered_by = models.CharField(
        max_length=20, default='manual',
        help_text="'manual' or 'auto'"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Fix [{self.status}] {self.metric_name} on {self.server.name} at {self.created_at}"

    @property
    def commands_run_parsed(self):
        """Return the commands_run field as a Python list."""
        try:
            return json.loads(self.commands_run)
        except (json.JSONDecodeError, TypeError):
            return []
