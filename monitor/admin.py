from django.contrib import admin
from .models import Server, AlertRule, Alert


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'ssh_user', 'setup_status', 'is_active', 'has_containers', 'created_at')
    list_filter = ('setup_status', 'is_active', 'has_containers')
    search_fields = ('name', 'ip_address')
    readonly_fields = ('setup_logs', 'created_at', 'updated_at')


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'metric', 'threshold', 'severity', 'is_enabled', 'created_at')
    list_filter = ('metric', 'severity', 'is_enabled')
    list_editable = ('threshold', 'severity', 'is_enabled')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'server', 'metric_name', 'metric_value', 'severity', 'status', 'created_at', 'fixed_at')
    list_filter = ('status', 'severity', 'metric_name')
    search_fields = ('title', 'server__name', 'server__ip_address')
    readonly_fields = ('fix_logs', 'created_at', 'fixed_at')
