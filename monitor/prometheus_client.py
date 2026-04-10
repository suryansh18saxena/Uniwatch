"""
Prometheus HTTP API client for querying metrics.
Connects to the local Prometheus instance running via docker-compose.
"""

import requests
from urllib.parse import urljoin

# Prometheus runs locally via docker-compose
PROMETHEUS_URL = 'http://localhost:9090'


def query_prometheus(promql_query):
    """
    Execute an instant PromQL query against Prometheus.
    Returns the parsed JSON result or None on error.
    """
    try:
        response = requests.get(
            urljoin(PROMETHEUS_URL, '/api/v1/query'),
            params={'query': promql_query},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'success':
            return data.get('data', {}).get('result', [])
        return None
    except (requests.RequestException, ValueError):
        return None


def query_prometheus_range(promql_query, start, end, step='60s'):
    """
    Execute a range PromQL query for time-series charts.
    Returns list of {metric, values} or None on error.
    """
    try:
        response = requests.get(
            urljoin(PROMETHEUS_URL, '/api/v1/query_range'),
            params={
                'query': promql_query,
                'start': start,
                'end': end,
                'step': step,
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'success':
            return data.get('data', {}).get('result', [])
        return None
    except (requests.RequestException, ValueError):
        return None


def get_server_metrics(ip_address):
    """
    Fetch key metrics for a specific server from Prometheus.
    Returns a dict with CPU usage, memory, disk, and uptime.
    """
    instance = f'{ip_address}:9100'
    metrics = {}

    # CPU Usage (percentage, averaged over 5 minutes)
    cpu_result = query_prometheus(
        f'100 - (avg(rate(node_cpu_seconds_total{{instance="{instance}",mode="idle"}}[5m])) * 100)'
    )
    if cpu_result:
        try:
            metrics['cpu_usage'] = round(float(cpu_result[0]['value'][1]), 2)
        except (IndexError, KeyError, ValueError):
            metrics['cpu_usage'] = None

    # Memory Usage (percentage)
    mem_result = query_prometheus(
        f'(1 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}})) * 100'
    )
    if mem_result:
        try:
            metrics['memory_usage'] = round(float(mem_result[0]['value'][1]), 2)
        except (IndexError, KeyError, ValueError):
            metrics['memory_usage'] = None

    # Total Memory (GB)
    mem_total = query_prometheus(
        f'node_memory_MemTotal_bytes{{instance="{instance}"}} / 1073741824'
    )
    if mem_total:
        try:
            metrics['memory_total_gb'] = round(float(mem_total[0]['value'][1]), 2)
        except (IndexError, KeyError, ValueError):
            metrics['memory_total_gb'] = None

    # Disk Usage (percentage, root filesystem)
    disk_result = query_prometheus(
        f'(1 - (node_filesystem_avail_bytes{{instance="{instance}",mountpoint="/"}} / node_filesystem_size_bytes{{instance="{instance}",mountpoint="/"}})) * 100'
    )
    if disk_result:
        try:
            metrics['disk_usage'] = round(float(disk_result[0]['value'][1]), 2)
        except (IndexError, KeyError, ValueError):
            metrics['disk_usage'] = None

    # System Uptime (hours)
    uptime = query_prometheus(
        f'(time() - node_boot_time_seconds{{instance="{instance}"}}) / 3600'
    )
    if uptime:
        try:
            metrics['uptime_hours'] = round(float(uptime[0]['value'][1]), 1)
        except (IndexError, KeyError, ValueError):
            metrics['uptime_hours'] = None

    # Network (bytes received/transmitted per second)
    net_rx = query_prometheus(
        f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[5m])'
    )
    if net_rx:
        try:
            total_rx = sum(float(r['value'][1]) for r in net_rx)
            metrics['network_rx_mbps'] = round(total_rx / 1048576, 2)
        except (IndexError, KeyError, ValueError):
            metrics['network_rx_mbps'] = None

    return metrics


def check_prometheus_health():
    """Check if Prometheus is running and reachable."""
    try:
        response = requests.get(
            urljoin(PROMETHEUS_URL, '/-/healthy'),
            timeout=3
        )
        return response.status_code == 200
    except requests.RequestException:
        return False
