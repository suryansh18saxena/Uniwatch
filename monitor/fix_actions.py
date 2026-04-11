"""
Self-Healing Fix Actions Registry.

Maps metric alert types to lists of SAFE, whitelisted shell commands.
Only commands defined here can be executed remotely — no dynamic or
user-generated commands are ever allowed.

Each action has:
  - label:       Human-readable description shown in the UI
  - command:     The exact shell command to execute
  - severity:    'safe' (read-only), 'moderate' (state-changing but reversible)
  - description: Explains what the command does for transparency
"""

# ──────────────────────────────────────────────────────────────────────
# WHITELISTED FIX ACTION REGISTRY
# ──────────────────────────────────────────────────────────────────────

FIX_ACTIONS = {
    'cpu_usage': [
        {
            'label': 'List Top CPU Processes',
            'command': 'ps aux --sort=-%cpu | head -15',
            'severity': 'safe',
            'description': 'Lists the top 15 processes consuming CPU. Read-only diagnostic.',
        },
        {
            'label': 'Kill Zombie Processes',
            'command': "sudo kill -9 $(ps -eo pid,stat | awk '$2 ~ /Z/ {print $1}') 2>/dev/null || echo 'No zombies found'",
            'severity': 'moderate',
            'description': 'Terminates any zombie processes stuck in Z state.',
        },
        {
            'label': 'Restart cron (if stuck)',
            'command': 'sudo systemctl restart cron || sudo systemctl restart crond || echo "cron not found"',
            'severity': 'moderate',
            'description': 'Restarts the cron daemon which can sometimes loop under load.',
        },
    ],

    'memory_usage': [
        {
            'label': 'List Top Memory Processes',
            'command': 'ps aux --sort=-%mem | head -15',
            'severity': 'safe',
            'description': 'Lists the top 15 processes consuming memory. Read-only diagnostic.',
        },
        {
            'label': 'Drop Page Cache',
            'command': 'sudo sync && sudo sh -c "echo 3 > /proc/sys/vm/drop_caches"',
            'severity': 'moderate',
            'description': 'Flushes the Linux page/dentry/inode cache to reclaim memory.',
        },
        {
            'label': 'Restart rsyslog',
            'command': 'sudo systemctl restart rsyslog 2>/dev/null || echo "rsyslog not found"',
            'severity': 'moderate',
            'description': 'Restarts the system logging daemon which can accumulate memory.',
        },
    ],

    'disk_usage': [
        {
            'label': 'Show Disk Usage Summary',
            'command': 'df -h / && echo "---" && du -sh /tmp /var/log /var/cache 2>/dev/null',
            'severity': 'safe',
            'description': 'Displays disk usage for root partition and large directories.',
        },
        {
            'label': 'Clean Temp Files',
            'command': 'sudo find /tmp -type f -atime +7 -delete 2>/dev/null && echo "Cleaned /tmp files older than 7 days"',
            'severity': 'moderate',
            'description': 'Removes temporary files not accessed in the last 7 days.',
        },
        {
            'label': 'Rotate and Compress Logs',
            'command': 'sudo logrotate --force /etc/logrotate.conf 2>/dev/null || echo "logrotate not available"',
            'severity': 'moderate',
            'description': 'Forces log rotation to reclaim space from large log files.',
        },
        {
            'label': 'Clean APT Cache',
            'command': 'sudo apt-get clean 2>/dev/null || sudo yum clean all 2>/dev/null || echo "No package manager cache cleaned"',
            'severity': 'moderate',
            'description': 'Cleans the system package manager download cache.',
        },
    ],

    'network': [
        {
            'label': 'Show Active Connections',
            'command': 'ss -tunap | head -30',
            'severity': 'safe',
            'description': 'Lists the top 30 active TCP/UDP connections with process info.',
        },
    ],

    'network_attack': [
        {
            'label': 'Show Connections by Source IP',
            'command': 'ss -ntu | awk \'{print $5}\' | cut -d: -f1 | sort | uniq -c | sort -rn | head -20',
            'severity': 'safe',
            'description': 'Lists the top 20 source IPs by active connection count. Read-only diagnostic.',
        },
        {
            'label': 'Show Connection States',
            'command': 'ss -nat | awk \'{print $1}\' | sort | uniq -c | sort -rn',
            'severity': 'safe',
            'description': 'Summarizes TCP connection states (ESTABLISHED, SYN_RECV, TIME_WAIT, etc.).',
        },
        {
            'label': 'Show Conntrack Table Stats',
            'command': 'sudo cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null && echo "/" && sudo cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo "conntrack not available"',
            'severity': 'safe',
            'description': 'Shows the current vs maximum connection tracking entries on the system.',
        },
        {
            'label': 'Rate-Limit HTTP (port 80)',
            'command': 'sudo iptables -A INPUT -p tcp --dport 80 -m limit --limit 25/minute --limit-burst 100 -j ACCEPT',
            'severity': 'moderate',
            'description': 'Limits new connections to port 80 to 25/min with a burst of 100. Mitigates HTTP flood without blocking all traffic.',
        },
        {
            'label': 'Rate-Limit HTTPS (port 443)',
            'command': 'sudo iptables -A INPUT -p tcp --dport 443 -m limit --limit 25/minute --limit-burst 100 -j ACCEPT',
            'severity': 'moderate',
            'description': 'Limits new connections to port 443 to 25/min with a burst of 100. Mitigates HTTPS flood.',
        },
        {
            'label': 'Enable SYN Flood Protection',
            'command': 'sudo sysctl -w net.ipv4.tcp_syncookies=1 && sudo sysctl -w net.ipv4.tcp_max_syn_backlog=2048 && sudo sysctl -w net.ipv4.tcp_synack_retries=2',
            'severity': 'moderate',
            'description': 'Enables kernel SYN cookies and tunes the SYN backlog to resist SYN flood attacks. Reversible via sysctl.',
        },
        {
            'label': 'Drop Invalid Packets',
            'command': 'sudo iptables -A INPUT -m conntrack --ctstate INVALID -j DROP',
            'severity': 'moderate',
            'description': 'Drops packets in INVALID conntrack state, which are often part of port scans or malformed attacks.',
        },
    ],
}

# ──────────────────────────────────────────────────────────────────────
# COMMAND BLACKLIST — extra safety net
# ──────────────────────────────────────────────────────────────────────

DANGEROUS_PATTERNS = [
    'rm -rf /',
    'mkfs',
    'dd if=',
    ':(){',            # fork bomb
    '> /dev/sda',
    'chmod -R 777 /',
    'mv / ',
    'shutdown',
    'reboot',
    'init 0',
    'halt',
    'iptables -F',     # flush all rules — could lock out SSH
    'iptables -X',     # delete all user chains
]


def _is_command_safe(command: str) -> bool:
    """Verify a command doesn't match any dangerous patterns."""
    cmd_lower = command.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return False
    return True


def get_fix_actions(metric_name: str) -> list:
    """
    Get the list of whitelisted fix actions for a given metric.

    Args:
        metric_name: One of 'cpu_usage', 'memory_usage', 'disk_usage', 'network', 'network_attack'

    Returns:
        List of action dicts with keys: label, command, severity, description.
        Returns empty list if the metric is not recognized.
    """
    actions = FIX_ACTIONS.get(metric_name, [])
    # Double-check every command against the blacklist (defense-in-depth)
    return [a for a in actions if _is_command_safe(a['command'])]


def get_all_metric_names() -> list:
    """Return all metric names that have fix actions defined."""
    return list(FIX_ACTIONS.keys())
