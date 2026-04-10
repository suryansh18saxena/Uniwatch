"""
Views for the Uniwatch monitoring platform.
Handles server management, setup orchestration, and metrics display.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Server
from .forms import AddServerForm
from .utils import setup_server
from .prometheus_client import query_prometheus, get_server_metrics


def dashboard(request):
    """Main dashboard showing all monitored servers."""
    servers = Server.objects.all()
    stats = {
        'total': servers.count(),
        'active': servers.filter(is_active=True).count(),
        'failed': servers.filter(setup_status='failed').count(),
        'pending': servers.filter(setup_status='pending').count(),
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

    return render(request, 'monitor/server_detail.html', {
        'server': server,
        'metrics': metrics,
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