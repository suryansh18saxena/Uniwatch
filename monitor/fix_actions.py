"""
Predefined fix actions for common server alerts.
Each fix maps an alert type to SSH commands that resolve the issue.
"""


# Maps metric_name → dict with fix info
FIX_ACTIONS = {
    'cpu_usage': {
        'description': 'Kill top CPU-consuming processes & clear system caches',
        'commands': [
            # Show top CPU processes first (for logging)
            "ps aux --sort=-%cpu | head -10",
            # Kill any zombie processes
            "sudo kill -9 $(ps -eo pid,stat | awk '$2 ~ /Z/ {print $1}') 2>/dev/null || echo 'No zombie processes found'",
            # Restart any stuck systemd services
            "sudo systemctl list-units --state=failed --no-legend | awk '{print $1}' | xargs -r sudo systemctl restart 2>/dev/null || echo 'No failed services'",
            # Drop page cache, dentries, and inodes to free memory pressure on CPU
            "sudo sync && sudo sysctl -w vm.drop_caches=1",
        ],
    },

    'memory_usage': {
        'description': 'Clear system caches & free memory',
        'commands': [
            # Show current memory usage
            "free -h",
            # Clear page cache, dentries and inodes
            "sudo sync && sudo sysctl -w vm.drop_caches=3",
            # Clear swap if it's being used heavily
            "sudo swapoff -a && sudo swapon -a 2>/dev/null || echo 'Swap reset skipped'",
            # Show memory after cleanup
            "free -h",
        ],
    },

    'disk_usage': {
        'description': 'Clean temp files, old logs, and Docker junk',
        'commands': [
            # Show disk usage before
            "df -h /",
            # Clean apt cache
            "sudo apt-get clean 2>/dev/null || sudo yum clean all 2>/dev/null || echo 'Package cache clean skipped'",
            # Remove old journal logs (keep last 2 days)
            "sudo journalctl --vacuum-time=2d 2>/dev/null || echo 'Journal cleanup skipped'",
            # Clean temp files
            "sudo rm -rf /tmp/* /var/tmp/* 2>/dev/null || echo 'Temp cleanup done'",
            # Remove old log files (> 7 days)
            "sudo find /var/log -type f -name '*.gz' -mtime +7 -delete 2>/dev/null || echo 'Old logs cleanup done'",
            "sudo find /var/log -type f -name '*.old' -delete 2>/dev/null || echo 'Old logs cleanup done'",
            # Docker cleanup if Docker exists
            "sudo docker system prune -f 2>/dev/null || echo 'Docker cleanup skipped (Docker not installed)'",
            # Show disk usage after
            "df -h /",
        ],
    },

    'node_exporter_down': {
        'description': 'Restart the Node Exporter service',
        'commands': [
            # Check current status
            "sudo systemctl status node_exporter --no-pager 2>/dev/null || echo 'Service status unknown'",
            # Restart the service
            "sudo systemctl restart node_exporter",
            # Wait a moment
            "sleep 2",
            # Verify it's running
            "sudo systemctl is-active node_exporter",
            # Check if port 9100 is listening
            "ss -tlnp | grep 9100 || echo 'Port 9100 not listening!'",
        ],
    },

    'cadvisor_down': {
        'description': 'Restart the cAdvisor Docker container',
        'commands': [
            # Check current container status
            "sudo docker ps -a --filter name=cadvisor --format '{{.Status}}' 2>/dev/null || echo 'Docker not available'",
            # Stop and remove existing container
            "sudo docker stop cadvisor 2>/dev/null || true",
            "sudo docker rm cadvisor 2>/dev/null || true",
            # Restart cAdvisor container
            (
                "sudo docker run -d "
                "--name=cadvisor "
                "--restart=always "
                "-p 8080:8080 "
                "--volume=/:/rootfs:ro "
                "--volume=/var/run:/var/run:rw "
                "--volume=/sys:/sys:ro "
                "--volume=/var/lib/docker/:/var/lib/docker:ro "
                "--volume=/dev/disk/:/dev/disk:ro "
                "--privileged "
                "--device=/dev/kmsg "
                "gcr.io/cadvisor/cadvisor:latest"
            ),
            # Wait and verify
            "sleep 3",
            "sudo docker ps --filter name=cadvisor --format '{{.Status}}'",
        ],
    },
}


def get_fix_for_alert(metric_name):
    """
    Get the fix action for a given metric name.
    Returns (description, commands_list) or (None, None) if no fix exists.
    """
    fix = FIX_ACTIONS.get(metric_name)
    if fix:
        return fix['description'], fix['commands']
    return None, None


def get_combined_fix_command(metric_name):
    """
    Get all fix commands joined as a single string for display.
    """
    fix = FIX_ACTIONS.get(metric_name)
    if fix:
        return ' && '.join(fix['commands'])
    return ''
