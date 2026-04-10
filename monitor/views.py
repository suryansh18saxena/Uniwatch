"""
Views for the Uniwatch monitoring platform.
Handles server management, setup orchestration, alerts, and fix execution.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from .models import Server, AlertRule, Alert
from .forms import AddServerForm
from .utils import setup_server, execute_remote_fix
from .prometheus_client import query_prometheus, get_server_metrics, check_prometheus_health
from .fix_actions import get_fix_for_alert, FIX_ACTIONS


def dashboard(request):
    """Main dashboard showing all monitored servers."""
    servers = Server.objects.all()
    open_alerts = Alert.objects.filter(status='open').count()
    stats = {
        'total': servers.count(),
        'active': servers.filter(is_active=True).count(),
        'failed': servers.filter(setup_status='failed').count(),
        'alerts': open_alerts,
    }
    return render(request, 'monitor/dashboard.html', {
        'servers': servers,
        'stats': stats,
    })


def add_server(request):
    """Handle adding a new server — form + SSH setup."""
    if request.method == 'POST':
        form = AddServerForm(request.POST)
        if form.is_valid():
            # Save server WITHOUT the SSH key (it's not in the model)
            server = form.save(commit=False)
            server.setup_status = 'running'
            server.save()

            # Get the SSH key from the form (use once, never store)
            ssh_private_key = form.cleaned_data['ssh_private_key']

            # Run the setup via SSH
            success, logs = setup_server(
                ip_address=str(server.ip_address),
                ssh_user=server.ssh_user,
                private_key_content=ssh_private_key,
                install_cadvisor=server.has_containers,
            )

            # Update server status and logs
            server.setup_logs = logs
            if success:
                server.setup_status = 'success'
                server.is_active = True
                messages.success(request, f'🎉 Server "{server.name}" setup complete! Monitoring is active.')
            else:
                server.setup_status = 'failed'
                server.is_active = False
                messages.error(request, f'❌ Server "{server.name}" setup failed. Check the logs below.')

            server.save()

            # SSH key is now garbage collected — never stored!
            del ssh_private_key

            return redirect('server_detail', server_id=server.id)
    else:
        form = AddServerForm()

    return render(request, 'monitor/add_server.html', {'form': form})


def server_detail(request, server_id):
    """Show details and metrics for a specific server."""
    server = get_object_or_404(Server, id=server_id)

    # Try to get live metrics from Prometheus
    metrics = {}
    if server.is_active:
        try:
            metrics = get_server_metrics(server.ip_address)
        except Exception:
            metrics = {'error': 'Could not fetch metrics from Prometheus'}

    # Get alerts for this server
    server_alerts = Alert.objects.filter(server=server).order_by('-created_at')[:10]

    return render(request, 'monitor/server_detail.html', {
        'server': server,
        'metrics': metrics,
        'server_alerts': server_alerts,
    })


def delete_server(request, server_id):
    """Delete a server from monitoring."""
    server = get_object_or_404(Server, id=server_id)
    if request.method == 'POST':
        server_name = server.name
        server.delete()
        messages.success(request, f'Server "{server_name}" has been removed.')
        return redirect('dashboard')
    return redirect('server_detail', server_id=server_id)


def retry_setup(request, server_id):
    """Retry setup for a failed server — requires re-uploading SSH key."""
    server = get_object_or_404(Server, id=server_id)
    if request.method == 'POST':
        ssh_private_key = request.POST.get('ssh_private_key', '')
        if not ssh_private_key.strip():
            messages.error(request, 'Please provide your SSH private key to retry.')
            return redirect('server_detail', server_id=server.id)

        server.setup_status = 'running'
        server.save()

        success, logs = setup_server(
            ip_address=str(server.ip_address),
            ssh_user=server.ssh_user,
            private_key_content=ssh_private_key,
            install_cadvisor=server.has_containers,
        )

        server.setup_logs = logs
        if success:
            server.setup_status = 'success'
            server.is_active = True
            messages.success(request, f'🎉 Retry successful! "{server.name}" is now being monitored.')
        else:
            server.setup_status = 'failed'
            messages.error(request, f'❌ Retry failed for "{server.name}". Check logs.')

        server.save()
        del ssh_private_key

    return redirect('server_detail', server_id=server.id)


# ===========================
# ALERT SYSTEM VIEWS
# ===========================

def alerts_list(request):
    """Show all alerts with fix buttons. Supports filtering."""
    status_filter = request.GET.get('status', 'open')

    if status_filter == 'all':
        alerts = Alert.objects.all()
    else:
        alerts = Alert.objects.filter(status=status_filter)

    alert_counts = {
        'open': Alert.objects.filter(status='open').count(),
        'fixing': Alert.objects.filter(status='fixing').count(),
        'fixed': Alert.objects.filter(status='fixed').count(),
        'failed': Alert.objects.filter(status='failed').count(),
        'all': Alert.objects.count(),
    }

    return render(request, 'monitor/alerts.html', {
        'alerts': alerts,
        'alert_counts': alert_counts,
        'current_filter': status_filter,
    })


def alert_detail(request, alert_id):
    """Show details of a single alert including fix logs."""
    alert = get_object_or_404(Alert, id=alert_id)
    return render(request, 'monitor/alert_detail.html', {
        'alert': alert,
    })


def execute_fix(request, alert_id):
    """
    Execute a fix for an alert.
    Requires SSH key (use once, then delete).
    Flow: User clicks Fix → enters SSH key → backend SSHs → runs fix → shows result.
    """
    alert = get_object_or_404(Alert, id=alert_id)

    if request.method == 'POST':
        ssh_private_key = request.POST.get('ssh_private_key', '')

        if not ssh_private_key.strip():
            messages.error(request, '🔑 Please provide your SSH private key to execute the fix.')
            return redirect('alert_detail', alert_id=alert.id)

        if not alert.has_fix:
            messages.error(request, '❌ No fix command available for this alert.')
            return redirect('alert_detail', alert_id=alert.id)

        # Get the fix commands
        fix_desc, fix_commands = get_fix_for_alert(alert.metric_name)

        if not fix_commands:
            messages.error(request, '❌ No fix commands found for this alert type.')
            return redirect('alert_detail', alert_id=alert.id)

        # Update status to fixing
        alert.status = 'fixing'
        alert.save()

        # Execute the fix via SSH
        success, logs = execute_remote_fix(
            ip_address=str(alert.server.ip_address),
            ssh_user=alert.server.ssh_user,
            private_key_content=ssh_private_key,
            commands=fix_commands,
        )

        # Update alert with results
        alert.fix_logs = logs
        if success:
            alert.status = 'fixed'
            alert.fixed_at = timezone.now()
            messages.success(request, f'✅ Fix applied successfully on {alert.server.name}!')
        else:
            alert.status = 'failed'
            messages.error(request, f'❌ Fix failed on {alert.server.name}. Check the logs.')

        alert.save()

        # Delete SSH key from memory
        del ssh_private_key

        return redirect('alert_detail', alert_id=alert.id)

    return redirect('alert_detail', alert_id=alert.id)


def dismiss_alert(request, alert_id):
    """Dismiss an alert without fixing it."""
    alert = get_object_or_404(Alert, id=alert_id)
    if request.method == 'POST':
        alert.status = 'dismissed'
        alert.save()
        messages.success(request, f'Alert dismissed: {alert.title}')
    return redirect('alerts_list')


def check_alerts(request):
    """
    Manually trigger an alert check. Queries Prometheus for each active server
    and creates Alert records if thresholds are exceeded.
    """
    if request.method != 'POST':
        return redirect('alerts_list')

    rules = AlertRule.objects.filter(is_enabled=True)
    active_servers = Server.objects.filter(is_active=True)

    if not rules.exists():
        messages.warning(request, '⚠️ No alert rules configured. Go to Admin to create some.')
        return redirect('alerts_list')

    if not active_servers.exists():
        messages.warning(request, '⚠️ No active servers to check.')
        return redirect('alerts_list')

    # Check Prometheus health
    if not check_prometheus_health():
        messages.error(request, '❌ Cannot reach Prometheus. Make sure docker-compose is running.')
        return redirect('alerts_list')

    new_alerts = 0

    for server in active_servers:
        try:
            metrics = get_server_metrics(server.ip_address)
        except Exception:
            continue

        for rule in rules:
            current_value = None
            should_alert = False

            # Map rule.metric to actual metric value
            if rule.metric == 'cpu_usage' and metrics.get('cpu_usage') is not None:
                current_value = metrics['cpu_usage']
                should_alert = current_value > rule.threshold

            elif rule.metric == 'memory_usage' and metrics.get('memory_usage') is not None:
                current_value = metrics['memory_usage']
                should_alert = current_value > rule.threshold

            elif rule.metric == 'disk_usage' and metrics.get('disk_usage') is not None:
                current_value = metrics['disk_usage']
                should_alert = current_value > rule.threshold

            elif rule.metric == 'node_exporter_down':
                # If we can't get ANY metrics, node_exporter is likely down
                if not metrics or all(v is None for v in metrics.values() if isinstance(v, (int, float, type(None)))):
                    should_alert = True
                    current_value = 0

            elif rule.metric == 'cadvisor_down' and server.has_containers:
                cadvisor_result = query_prometheus(
                    f'up{{job="cadvisor",instance="{server.ip_address}:8080"}}'
                )

                if not cadvisor_result:
                    should_alert = True
                    current_value = 0
                else:
                    try:
                        current_value = float(cadvisor_result[0]['value'][1])
                        should_alert = current_value == 0
                    except (IndexError, KeyError, TypeError, ValueError):
                        should_alert = True
                        current_value = 0

            if should_alert:
                # Check if there's already an open alert for this server+metric
                existing = Alert.objects.filter(
                    server=server,
                    metric_name=rule.metric,
                    status='open'
                ).exists()

                if not existing:
                    fix_desc, fix_commands = get_fix_for_alert(rule.metric)

                    Alert.objects.create(
                        server=server,
                        rule=rule,
                        title=f"{rule.name} on {server.name}",
                        description=f"{rule.metric.replace('_', ' ').title()} is at {current_value}% (threshold: {rule.threshold}%)",
                        metric_name=rule.metric,
                        metric_value=current_value,
                        threshold_value=rule.threshold,
                        severity=rule.severity,
                        status='open',
                        fix_command='\n'.join(fix_commands) if fix_commands else '',
                        fix_description=fix_desc or '',
                    )
                    new_alerts += 1

    if new_alerts > 0:
        messages.warning(request, f'🚨 {new_alerts} new alert(s) triggered!')
    else:
        messages.success(request, '✅ All servers are healthy. No new alerts.')

    return redirect('alerts_list')