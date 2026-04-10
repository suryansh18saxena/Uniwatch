from django.contrib import admin
from .models import Server, Alert, FixExecution


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'ssh_user', 'setup_status', 'is_active', 'has_containers', 'auto_fix_enabled', 'created_at')
    list_filter = ('setup_status', 'is_active', 'has_containers', 'auto_fix_enabled')
    search_fields = ('name', 'ip_address')
    readonly_fields = ('setup_logs', 'created_at', 'updated_at')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'server', 'metric_name', 'severity', 'status', 'metric_value', 'created_at')
    list_filter = ('severity', 'status', 'metric_name')
    search_fields = ('title', 'server__name')
    readonly_fields = ('created_at',)


@admin.register(FixExecution)
class FixExecutionAdmin(admin.ModelAdmin):
    list_display = ('server', 'metric_name', 'status', 'triggered_by', 'summary', 'created_at')
    list_filter = ('status', 'triggered_by', 'metric_name')
    search_fields = ('server__name',)
    readonly_fields = ('created_at', 'commands_run')
