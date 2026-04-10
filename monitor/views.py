"""
Views for the Uniwatch monitoring platform.
Handles server management, setup orchestration, alerts, and fix execution.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from .models import Server, AlertRule, Alert
from .forms import AddServerForm
from .utils import setup_server, execute_remote_fix
from .prometheus_client import query_prometheus, get_server_metrics, check_prometheus_health
from .fix_actions import get_fix_for_alert, FIX_ACTIONS


def landing_page(request):
    """Marketing and acquisition landing page."""
    return render(request, 'monitor/landing.html')


def dashboard(request):
    """Main dashboard showing all monitored servers."""
    servers = Server.objects.all()
    
    first_server = servers.first()
    if first_server:
        return redirect('server_detail', server_id=first_server.id)

    stats = {'total': 0, 'active': 0, 'failed': 0, 'pending': 0}
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
    all_servers = Server.objects.all()

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
        'all_servers': all_servers,
        'metrics': metrics,
        'server_alerts': server_alerts,
    })


def server_timeseries_api(request, server_id):
    """API endpoint to get historical time-series data for a server."""
    server = get_object_or_404(Server, id=server_id)
    if not server.is_active:
        return JsonResponse({'error': 'Server is not active'}, status=400)
    
    try:
        from .prometheus_client import get_server_timeseries
        data = get_server_timeseries(server.ip_address, duration_minutes=30)
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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


# ──────────────────────────────────────────────────────────────────────
# Self-Healing / Auto-Remediation Views
# ──────────────────────────────────────────────────────────────────────

def api_fix_preview(request, server_id, metric_name):
    """
    GET: Return the list of whitelisted fix commands for a metric.
    Used by the frontend to show a preview before execution.
    """
    from .fix_actions import get_fix_actions
    server = get_object_or_404(Server, id=server_id)
    actions = get_fix_actions(metric_name)
    return JsonResponse({
        'server': server.name,
        'metric_name': metric_name,
        'actions': actions,
        'auto_fix_enabled': server.auto_fix_enabled,
    })


def api_fix_execute(request, server_id, metric_name):
    """
    POST: Execute fix actions for a metric on a server.
    Requires SSH key in POST body. Logs execution to FixExecution model.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from .fix_actions import get_fix_actions
    from .remediation import execute_fix
    from .models import Alert, FixExecution
    import json as json_module

    server = get_object_or_404(Server, id=server_id)
    ssh_key = request.POST.get('ssh_private_key', '')
    alert_id = request.POST.get('alert_id')
    stop_on_failure = request.POST.get('stop_on_failure', 'false') == 'true'

    # Parse action indices if provided
    action_indices_str = request.POST.get('action_indices', '')
    action_indices = None
    if action_indices_str:
        try:
            action_indices = json_module.loads(action_indices_str)
        except (json_module.JSONDecodeError, TypeError):
            action_indices = None

    if not ssh_key.strip():
        return JsonResponse({'error': 'SSH key is required to execute fixes.'}, status=400)

    # Execute the remediation
    result = execute_fix(
        ip_address=str(server.ip_address),
        ssh_user=server.ssh_user,
        private_key_content=ssh_key,
        metric_name=metric_name,
        stop_on_failure=stop_on_failure,
        action_indices=action_indices,
    )

    # Get associated alert if provided
    alert = None
    if alert_id:
        try:
            alert = Alert.objects.get(id=alert_id, server=server)
        except Alert.DoesNotExist:
            pass

    # Record execution in the database
    fix_exec = FixExecution.objects.create(
        server=server,
        alert=alert,
        metric_name=metric_name,
        commands_run=json_module.dumps(result['results']),
        summary=result['summary'],
        status=result['overall_status'],
        triggered_by='manual',
    )

    # If fix was successful and alert exists, mark alert as resolved
    if alert and result['overall_status'] == 'success':
        from django.utils import timezone
        alert.status = 'resolved'
        alert.resolved_at = timezone.now()
        alert.save()

    return JsonResponse({
        'execution_id': fix_exec.id,
        'overall_status': result['overall_status'],
        'summary': result['summary'],
        'results': result['results'],
    })


def api_fix_history(request, server_id):
    """
    GET: Return the last 20 fix executions for a server.
    """
    from .models import FixExecution
    server = get_object_or_404(Server, id=server_id)
    executions = FixExecution.objects.filter(server=server)[:20]
    data = [{
        'id': e.id,
        'metric_name': e.metric_name,
        'status': e.status,
        'summary': e.summary,
        'triggered_by': e.triggered_by,
        'created_at': e.created_at.isoformat(),
        'commands': e.commands_run_parsed,
    } for e in executions]
    return JsonResponse({'history': data})


def api_toggle_autofix(request, server_id):
    """
    POST: Toggle the auto_fix_enabled setting on a server.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    server = get_object_or_404(Server, id=server_id)
    server.auto_fix_enabled = not server.auto_fix_enabled
    server.save(update_fields=['auto_fix_enabled'])
    return JsonResponse({
        'server': server.name,
        'auto_fix_enabled': server.auto_fix_enabled,
    })
