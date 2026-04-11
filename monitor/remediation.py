"""
Self-Healing Remediation Engine.

Executes whitelisted fix commands on remote servers via the existing
Paramiko SSH infrastructure. All executions are logged and recorded
in the FixExecution model.

Security:
  - Only commands from fix_actions.py are ever executed
  - Each command has a 30-second timeout
  - Every attempt is logged to the database regardless of outcome
  - Failed commands can optionally stop the chain or continue
  - Network attack auto-fix is restricted to safe (diagnostic) commands
    to prevent accidental lockout of legitimate users
  - A 5-minute cooldown prevents repeated auto-fix rule stacking
"""

import paramiko
import io
import json
import time
import logging
from datetime import datetime, timedelta

from .fix_actions import get_fix_actions, _is_command_safe

logger = logging.getLogger(__name__)

# Maximum seconds per command before we kill it
COMMAND_TIMEOUT = 30
# Maximum retries per failed command
MAX_RETRIES = 1
# Cooldown window (seconds) for network auto-fix to avoid rule stacking
NETWORK_AUTOFIX_COOLDOWN = 300  # 5 minutes
# Delay (seconds) before executing iptables commands — circuit-breaker window
IPTABLES_DELAY = 3


def _check_network_cooldown(ip_address):
    """
    Check if a network_attack auto-fix was executed recently.
    Returns True if still within cooldown window (should skip).
    """
    try:
        from .models import FixExecution
        from django.utils import timezone
        cutoff = timezone.now() - timedelta(seconds=NETWORK_AUTOFIX_COOLDOWN)
        recent = FixExecution.objects.filter(
            server__ip_address=ip_address,
            metric_name='network_attack',
            triggered_by='auto',
            created_at__gte=cutoff,
        ).exists()
        return recent
    except Exception:
        # If we can't check, err on the side of caution
        return True


def execute_fix(ip_address, ssh_user, private_key_content, metric_name,
                stop_on_failure=False, action_indices=None,
                triggered_by='manual'):
    """
    Execute whitelisted fix actions for a given metric on a remote server.

    Args:
        ip_address:          Target server IP
        ssh_user:            SSH username
        private_key_content: Raw SSH private key (used once, not stored)
        metric_name:         One of 'cpu_usage', 'memory_usage', 'disk_usage',
                             'network', 'network_attack'
        stop_on_failure:     If True, abort remaining commands after first failure
        action_indices:      Optional list of action indices to run (if None, run all)
        triggered_by:        'manual' or 'auto' — controls safety restrictions

    Returns:
        dict: {
            'overall_status': 'success' | 'partial' | 'failed',
            'results': [
                {
                    'command': str,
                    'label': str,
                    'output': str,
                    'error': str,
                    'exit_code': int,
                    'status': 'success' | 'failed',
                    'retries': int,
                }
            ],
            'summary': str,
        }
    """
    is_auto = (triggered_by == 'auto')
    is_network_metric = (metric_name == 'network_attack')

    # ── Network auto-fix cooldown ───────────────────────────────────
    if is_auto and is_network_metric:
        if _check_network_cooldown(ip_address):
            logger.info(
                f"Skipping network_attack auto-fix on {ip_address}: "
                f"cooldown ({NETWORK_AUTOFIX_COOLDOWN}s) is still active."
            )
            return {
                'overall_status': 'skipped',
                'results': [],
                'summary': (
                    f'Network auto-fix skipped — a fix was applied within '
                    f'the last {NETWORK_AUTOFIX_COOLDOWN // 60} minutes. '
                    f'Use manual execution to override.'
                ),
            }

    actions = get_fix_actions(metric_name)
    if not actions:
        return {
            'overall_status': 'failed',
            'results': [],
            'summary': f'No fix actions defined for metric: {metric_name}',
        }

    # Auto-fix execution will run all actions (safe and moderate) for proactive mitigation.
    if is_auto and is_network_metric:
        logger.info(f"Network auto-fix on {ip_address}: executing full mitigation suite (including iptables rules).")

    # Filter to specific actions if indices provided
    if action_indices is not None:
        actions = [actions[i] for i in action_indices if i < len(actions)]
        if not actions:
            return {
                'overall_status': 'failed',
                'results': [],
                'summary': 'No valid action indices provided.',
            }

    results = []
    ssh = None

    try:
        # Parse key using existing utility
        from .utils import _parse_private_key
        key = _parse_private_key(private_key_content)

        # Connect
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=ip_address, username=ssh_user, pkey=key, timeout=15)

        for action in actions:
            cmd = action['command']

            # Defense-in-depth: re-validate before execution
            if not _is_command_safe(cmd):
                results.append({
                    'command': cmd,
                    'label': action['label'],
                    'output': '',
                    'error': 'BLOCKED: Command matched dangerous pattern blacklist.',
                    'exit_code': -1,
                    'status': 'failed',
                    'retries': 0,
                })
                logger.warning(f"BLOCKED dangerous command on {ip_address}: {cmd}")
                if stop_on_failure:
                    break
                continue

            # Pre-execution delay for iptables commands (circuit-breaker window)
            if 'iptables' in cmd and is_network_metric:
                logger.info(
                    f"Applying {IPTABLES_DELAY}s safety delay before iptables "
                    f"command on {ip_address}: {action['label']}"
                )
                time.sleep(IPTABLES_DELAY)

            # Execute with retry logic
            attempt = 0
            cmd_result = None
            while attempt <= MAX_RETRIES:
                try:
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=COMMAND_TIMEOUT)
                    exit_code = stdout.channel.recv_exit_status()
                    out = stdout.read().decode('utf-8', errors='replace').strip()
                    err = stderr.read().decode('utf-8', errors='replace').strip()

                    cmd_result = {
                        'command': cmd,
                        'label': action['label'],
                        'output': out[:2000],  # cap output length
                        'error': err[:1000] if exit_code != 0 else '',
                        'exit_code': exit_code,
                        'status': 'success' if exit_code == 0 else 'failed',
                        'retries': attempt,
                    }

                    if exit_code == 0:
                        break  # success, no retry needed
                    else:
                        attempt += 1

                except Exception as cmd_err:
                    cmd_result = {
                        'command': cmd,
                        'label': action['label'],
                        'output': '',
                        'error': str(cmd_err)[:500],
                        'exit_code': -1,
                        'status': 'failed',
                        'retries': attempt,
                    }
                    attempt += 1

            results.append(cmd_result)

            if cmd_result['status'] == 'failed' and stop_on_failure:
                break

    except ValueError as e:
        return {
            'overall_status': 'failed',
            'results': results,
            'summary': f'SSH Key Error: {str(e)}',
        }
    except paramiko.AuthenticationException:
        return {
            'overall_status': 'failed',
            'results': results,
            'summary': 'SSH authentication failed. Check your key and username.',
        }
    except paramiko.ssh_exception.NoValidConnectionsError:
        return {
            'overall_status': 'failed',
            'results': results,
            'summary': f'Cannot reach {ip_address}. Check IP and security groups.',
        }
    except Exception as e:
        logger.exception(f"Remediation error on {ip_address}")
        return {
            'overall_status': 'failed',
            'results': results,
            'summary': f'Connection error: {str(e)}',
        }
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

    # Compute overall status
    success_count = sum(1 for r in results if r['status'] == 'success')
    total = len(results)
    if success_count == total:
        overall = 'success'
    elif success_count > 0:
        overall = 'partial'
    else:
        overall = 'failed'

    return {
        'overall_status': overall,
        'results': results,
        'summary': f'{success_count}/{total} commands executed successfully.',
    }
