from django.contrib import admin
from .models import Server


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'ssh_user', 'setup_status', 'is_active', 'has_containers', 'created_at')
    list_filter = ('setup_status', 'is_active', 'has_containers')
    search_fields = ('name', 'ip_address')
    readonly_fields = ('setup_logs', 'created_at', 'updated_at')
