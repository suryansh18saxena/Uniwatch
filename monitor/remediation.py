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
"""

import paramiko
import io
import json
import logging
from datetime import datetime

from .fix_actions import get_fix_actions, _is_command_safe

logger = logging.getLogger(__name__)

# Maximum seconds per command before we kill it
COMMAND_TIMEOUT = 30
# Maximum retries per failed command
MAX_RETRIES = 1


def execute_fix(ip_address, ssh_user, private_key_content, metric_name,
                stop_on_failure=False, action_indices=None):
    """
    Execute whitelisted fix actions for a given metric on a remote server.

    Args:
        ip_address:          Target server IP
        ssh_user:            SSH username
        private_key_content: Raw SSH private key (used once, not stored)
        metric_name:         One of 'cpu_usage', 'memory_usage', 'disk_usage'
        stop_on_failure:     If True, abort remaining commands after first failure
        action_indices:      Optional list of action indices to run (if None, run all)

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
    actions = get_fix_actions(metric_name)
    if not actions:
        return {
            'overall_status': 'failed',
            'results': [],
            'summary': f'No fix actions defined for metric: {metric_name}',
        }

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
