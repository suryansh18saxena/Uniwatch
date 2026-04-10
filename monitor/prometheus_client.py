"""
Prometheus HTTP API client for querying metrics.
Connects to the local Prometheus instance running via docker-compose.
"""

import requests
import time
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

    # CPU Usage (percentage, averaged over 1 minute)
    cpu_result = query_prometheus(
        f'100 - (avg(rate(node_cpu_seconds_total{{instance="{instance}",mode="idle"}}[1m])) * 100)'
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
        f'(time() - node_boot_time_seconds{{instance="{instance}"}})'
    )
    if uptime:
        try:
            uptime_seconds = float(uptime[0]['value'][1])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            mins = int((uptime_seconds % 3600) // 60)
            if days > 0:
                metrics['uptime_str'] = f'{days}d {hours}h'
            else:
                metrics['uptime_str'] = f'{hours}h {mins}m'
            metrics['uptime_hours'] = round(uptime_seconds / 3600, 1)
        except (IndexError, KeyError, ValueError):
            metrics['uptime_hours'] = None
            metrics['uptime_str'] = 'N/A'

    # Network (bytes received/transmitted per second)
    net_rx = query_prometheus(
        f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[5m])'
    )
    if net_rx:
        try:
            total_rx = sum(float(r['value'][1]) for r in net_rx)
            metrics['network_rx_mbps'] = round(total_rx / 1048576, 2)
        except (IndexError, KeyError, ValueError):
            metrics['network_rx_mbps'] = 0

    net_tx = query_prometheus(
        f'rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[5m])'
    )
    if net_tx:
        try:
            total_tx = sum(float(r['value'][1]) for r in net_tx)
            metrics['network_tx_mbps'] = round(total_tx / 1048576, 2)
        except (IndexError, KeyError, ValueError):
            metrics['network_tx_mbps'] = 0
            
    # Containers
    cadvisor_instance = f'{ip_address}:8080'
    containers = []
    container_info = query_prometheus(
        f'container_last_seen{{instance="{cadvisor_instance}", name!=""}}'
    )
    if container_info:
        for c in container_info:
            name = c['metric'].get('name', 'unknown')
            # ignore pause containers and similar infrastructural pods if desired
            if "POD" not in name:
                containers.append({
                    'name': name[:20],
                    'cpu': '--%',
                    'mem': '--%',
                    'status': '● Alive'
                })
    metrics['containers'] = containers

    # Dynamic Alert Evaluation
    alerts = []
    
    # Check CPU
    if metrics.get('cpu_usage') is not None and metrics['cpu_usage'] > 60:
        alerts.append({'severity': 'critical', 'title': 'High CPU Usage', 'message': f"CPU is averaging {metrics['cpu_usage']}%", 'time': 'Just now', 'metric_name': 'cpu_usage'})
        
    # Check Memory
    if metrics.get('memory_usage') is not None and metrics['memory_usage'] > 85:
        alerts.append({'severity': 'critical', 'title': 'High Memory Limit', 'message': f"Memory saturation at {metrics['memory_usage']}%", 'time': 'Just now', 'metric_name': 'memory_usage'})
        
    # Check Disk
    if metrics.get('disk_usage') is not None and metrics['disk_usage'] > 90:
        alerts.append({'severity': 'warning', 'title': 'Storage Capacity', 'message': f"Root partition is {metrics['disk_usage']}% full", 'time': 'Ongoing', 'metric_name': 'disk_usage'})
        
    # Check Network
    if metrics.get('network_rx_mbps') is not None and metrics['network_rx_mbps'] > 100:
        alerts.append({'severity': 'warning', 'title': 'High Network I/O', 'message': f"Ingest rate is {metrics['network_rx_mbps']} MB/s", 'time': 'Recent', 'metric_name': 'network'})
        
    metrics['alerts'] = alerts

    return metrics


def get_server_timeseries(ip_address, duration_minutes=30):
    """
    Fetch ranges of time-series data for the UI graphs.
    """
    instance = f'{ip_address}:9100'
    end_time = int(time.time())
    start_time = end_time - (duration_minutes * 60)
    
    timeseries = {
        'cpu': [], 'load1': [], 'load5': [], 'load15': [],
        'memory': [],
        'network_rx': [], 'network_tx': [], 'tcp_conns': [],
        'disk_io': [], 'disk_iops': []
    }
    
    # helper for parsing
    def parse_result(result):
        if not result or not result[0].get('values'): return []
        # Return format: [[timestamp, value], ...] where value is a float
        return [[int(v[0]), round(float(v[1]), 2)] for v in result[0]['values']]

    # 1. CPU Usage
    cpu = query_prometheus_range(
        f'100 - (avg(rate(node_cpu_seconds_total{{instance="{instance}",mode="idle"}}[1m])) * 100)',
        start=start_time, end=end_time, step='60s'
    )
    timeseries['cpu'] = parse_result(cpu)

    # 2. Memory Usage %
    mem = query_prometheus_range(
        f'(1 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}})) * 100',
        start=start_time, end=end_time, step='60s'
    )
    timeseries['memory'] = parse_result(mem)

    # 3. Network RX MB/s
    net_rx = query_prometheus_range(
        f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[1m]) / 1048576',
        start=start_time, end=end_time, step='60s'
    )
    # 4. Network TX MB/s
    net_tx = query_prometheus_range(
        f'rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[1m]) / 1048576',
        start=start_time, end=end_time, step='60s'
    )
    
    # Sum over all adapters if there are multiple datasets in result
    def sum_multiple_results(result):
        if not result: return []
        # Create a dict keyed by timestamp to sum values
        merged = {}
        for series in result:
            for v in series.get('values', []):
                ts = int(v[0])
                val = float(v[1])
                merged[ts] = merged.get(ts, 0.0) + val
        ordered = sorted(merged.items())
        return [[ts, round(val, 2)] for ts, val in ordered]

    timeseries['network_rx'] = sum_multiple_results(net_rx)
    timeseries['network_tx'] = sum_multiple_results(net_tx)

    # 5. Disk Read/Write (bytes/sec) - Sum of Reads + Writes combined as an anomaly load proxy
    disk_io = query_prometheus_range(
        f'(rate(node_disk_read_bytes_total{{instance="{instance}"}}[1m]) + rate(node_disk_written_bytes_total{{instance="{instance}"}}[1m])) / 1048576',
        start=start_time, end=end_time, step='60s'
    )
    timeseries['disk_io'] = sum_multiple_results(disk_io)

    # System Load Averages
    timeseries['load1'] = parse_result(query_prometheus_range(f'node_load1{{instance="{instance}"}}', start=start_time, end=end_time, step='60s'))
    timeseries['load5'] = parse_result(query_prometheus_range(f'node_load5{{instance="{instance}"}}', start=start_time, end=end_time, step='60s'))
    timeseries['load15'] = parse_result(query_prometheus_range(f'node_load15{{instance="{instance}"}}', start=start_time, end=end_time, step='60s'))

    # Disk IOPS (Reads + Writes)
    disk_iops = query_prometheus_range(
        f'rate(node_disk_reads_completed_total{{instance="{instance}"}}[1m]) + rate(node_disk_writes_completed_total{{instance="{instance}"}}[1m])',
        start=start_time, end=end_time, step='60s'
    )
    timeseries['disk_iops'] = sum_multiple_results(disk_iops)

    # TCP Connections
    timeseries['tcp_conns'] = parse_result(query_prometheus_range(f'node_netstat_Tcp_CurrEstab{{instance="{instance}"}}', start=start_time, end=end_time, step='60s'))

    return timeseries


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
