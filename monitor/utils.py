"""
SSH-based setup utilities for deploying monitoring agents on remote servers.
Uses Paramiko for SSH connections. SSH keys are used once and never stored.
"""

import paramiko
import io
import json
import os
from pathlib import Path


# Path to Prometheus file-based service discovery targets
PROMETHEUS_TARGETS_DIR = Path(__file__).resolve().parent.parent / 'prometheus' / 'targets'


def _parse_private_key(private_key_content):
    """
    Try parsing an SSH private key string as RSA, Ed25519, or ECDSA.
    Returns a paramiko key object.
    """
    private_key_content = private_key_content.strip()
    key_file = io.StringIO(private_key_content)

    # Try RSA first (most common for AWS)
    try:
        return paramiko.RSAKey.from_private_key(key_file)
    except paramiko.ssh_exception.SSHException:
        pass

    # Try Ed25519
    key_file.seek(0)
    try:
        return paramiko.Ed25519Key.from_private_key(key_file)
    except paramiko.ssh_exception.SSHException:
        pass

    # Try ECDSA
    key_file.seek(0)
    try:
        return paramiko.ECDSAKey.from_private_key(key_file)
    except paramiko.ssh_exception.SSHException:
        raise ValueError("Unsupported SSH key type. We support RSA, Ed25519, and ECDSA keys.")


def _get_node_exporter_commands():
    """Commands to install and start Prometheus Node Exporter."""
    return [
        # Create dedicated user
        "sudo useradd --system --no-create-home --shell /bin/false node_exporter || true",
        # Download node_exporter
        "wget -qO- https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz | tar xvz -C /tmp/",
        # Move binary
        "sudo mv /tmp/node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/ || true",
        # Set ownership
        "sudo chown node_exporter:node_exporter /usr/local/bin/node_exporter",
        # Create systemd service
        (
            "sudo bash -c 'cat <<EOF > /etc/systemd/system/node_exporter.service\n"
            "[Unit]\n"
            "Description=Prometheus Node Exporter\n"
            "After=network.target\n"
            "\n"
            "[Service]\n"
            "User=node_exporter\n"
            "Group=node_exporter\n"
            "Type=simple\n"
            "ExecStart=/usr/local/bin/node_exporter\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "EOF'"
        ),
        # Reload and start
        "sudo systemctl daemon-reload",
        "sudo systemctl start node_exporter",
        "sudo systemctl enable node_exporter",
    ]


def _get_cadvisor_commands():
    """Commands to install and run cAdvisor as a Docker container."""
    return [
        # Check if Docker is installed
        "docker --version",
        # Stop existing cAdvisor if any
        "sudo docker stop cadvisor || true",
        "sudo docker rm cadvisor || true",
        # Run cAdvisor container
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
    ]


def setup_server(ip_address, ssh_user, private_key_content, install_cadvisor=False):
    """
    Connect to a remote server via SSH and install monitoring agents.

    Args:
        ip_address: Target server IP
        ssh_user: SSH username (e.g., 'ubuntu', 'ec2-user')
        private_key_content: Raw SSH private key string (used once, not stored)
        install_cadvisor: If True, also install cAdvisor for container monitoring

    Returns:
        tuple: (success: bool, logs: str)
    """
    logs = f"🚀 Starting monitoring setup for {ip_address}...\n"
    logs += f"   User: {ssh_user}\n"
    logs += f"   cAdvisor: {'Yes' if install_cadvisor else 'No'}\n"
    logs += "=" * 50 + "\n\n"

    ssh = None

    try:
        # Parse the SSH key
        logs += "🔑 Parsing SSH key...\n"
        key = _parse_private_key(private_key_content)
        logs += "   Key parsed successfully!\n\n"

        # Connect via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        logs += f"🔗 Connecting to {ip_address} as {ssh_user}...\n"
        ssh.connect(hostname=ip_address, username=ssh_user, pkey=key, timeout=15)
        logs += "   ✅ SSH Connection Successful!\n\n"

        # Install Node Exporter
        logs += "📦 Installing Node Exporter...\n"
        logs += "-" * 40 + "\n"

        for cmd in _get_node_exporter_commands():
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
            exit_status = stdout.channel.recv_exit_status()

            cmd_display = cmd[:80] + "..." if len(cmd) > 80 else cmd
            if exit_status == 0:
                logs += f"   ✅ {cmd_display}\n"
            else:
                error_msg = stderr.read().decode().strip()
                logs += f"   ❌ FAILED: {cmd_display}\n"
                logs += f"      Error: {error_msg}\n"
                return False, logs

        logs += "\n🎉 Node Exporter installed and running on port 9100!\n\n"

        # Install cAdvisor if requested
        if install_cadvisor:
            logs += "🐳 Installing cAdvisor...\n"
            logs += "-" * 40 + "\n"

            for cmd in _get_cadvisor_commands():
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
                exit_status = stdout.channel.recv_exit_status()

                cmd_display = cmd[:80] + "..." if len(cmd) > 80 else cmd
                if exit_status == 0:
                    logs += f"   ✅ {cmd_display}\n"
                else:
                    error_msg = stderr.read().decode().strip()
                    logs += f"   ❌ FAILED: {cmd_display}\n"
                    logs += f"      Error: {error_msg}\n"
                    if "docker" in cmd.lower() and "version" in cmd.lower():
                        logs += "      ⚠️ Docker is not installed! cAdvisor requires Docker.\n"
                    return False, logs

            logs += "\n🎉 cAdvisor installed and running on port 8080!\n\n"

        # Update Prometheus targets for auto-discovery
        _update_prometheus_targets(ip_address, install_cadvisor)
        logs += "📡 Prometheus targets updated for auto-discovery.\n"

        logs += "\n" + "=" * 50 + "\n"
        logs += "✅ Setup Complete! All monitoring agents are running.\n"
        return True, logs

    except ValueError as e:
        logs += f"\n❌ KEY ERROR: {str(e)}\n"
        return False, logs
    except paramiko.AuthenticationException:
        logs += f"\n❌ AUTH ERROR: SSH authentication failed. Check your key and username.\n"
        return False, logs
    except paramiko.ssh_exception.NoValidConnectionsError:
        logs += f"\n❌ CONNECTION ERROR: Cannot reach {ip_address}. Check IP and security groups.\n"
        return False, logs
    except Exception as e:
        logs += f"\n❌ CRITICAL ERROR: {str(e)}\n"
        return False, logs
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _update_prometheus_targets(ip_address, has_cadvisor=False):
    """
    Update the Prometheus file-based service discovery targets.
    Creates/updates a JSON file that Prometheus watches for new targets.
    """
    PROMETHEUS_TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    targets_file = PROMETHEUS_TARGETS_DIR / 'uniwatch_targets.json'

    # Load existing targets or start fresh
    existing_targets = []
    if targets_file.exists():
        try:
            with open(targets_file, 'r') as f:
                existing_targets = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing_targets = []

    # Remove any existing entries for this IP
    existing_targets = [
        t for t in existing_targets
        if not any(ip_address in target for target in t.get('targets', []))
    ]

    # Add node_exporter target
    existing_targets.append({
        'targets': [f'{ip_address}:9100'],
        'labels': {
            'job': 'node_exporter',
            'instance_name': ip_address,
        }
    })

    # Add cAdvisor target if applicable
    if has_cadvisor:
        existing_targets.append({
            'targets': [f'{ip_address}:8080'],
            'labels': {
                'job': 'cadvisor',
                'instance_name': ip_address,
            }
        })

    # Write updated targets
    with open(targets_file, 'w') as f:
        json.dump(existing_targets, f, indent=2)


def remove_prometheus_target(ip_address):
    """
    Remove a server from Prometheus targets file upon deletion.
    """
    targets_file = PROMETHEUS_TARGETS_DIR / 'uniwatch_targets.json'
    if not targets_file.exists():
        return
        
    try:
        with open(targets_file, 'r') as f:
            existing_targets = json.load(f)
            
        # Filter out targets containing this IP address
        filtered_targets = [
            t for t in existing_targets
            if not any(ip_address in target for target in t.get('targets', []))
        ]
        
        with open(targets_file, 'w') as f:
            json.dump(filtered_targets, f, indent=2)
    except (json.JSONDecodeError, IOError):
        pass


def execute_remote_fix(ip_address, ssh_user, private_key_content, commands):
    """
    SSH into a server and execute fix commands.
    Used by the alert system when user clicks "Fix" button.

    Args:
        ip_address: Target server IP
        ssh_user: SSH username
        private_key_content: Raw SSH private key (used once, then deleted)
        commands: List of shell commands to execute

    Returns:
        tuple: (success: bool, logs: str)
    """
    logs = f"🔧 Executing fix on {ip_address}...\n"
    logs += "=" * 50 + "\n\n"

    ssh = None

    try:
        # Parse SSH key
        logs += "🔑 Authenticating...\n"
        key = _parse_private_key(private_key_content)

        # Connect
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=ip_address, username=ssh_user, pkey=key, timeout=15)
        logs += f"   ✅ Connected to {ip_address}\n\n"

        # Execute each fix command
        all_success = True
        for i, cmd in enumerate(commands, 1):
            cmd_display = cmd[:100] + "..." if len(cmd) > 100 else cmd
            logs += f"📌 Step {i}: {cmd_display}\n"

            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
            exit_status = stdout.channel.recv_exit_status()

            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

            if output:
                logs += f"   📄 Output:\n"
                for line in output.split('\n'):
                    logs += f"      {line}\n"

            if exit_status == 0:
                logs += f"   ✅ Success (exit code: 0)\n\n"
            else:
                logs += f"   ⚠️ Exit code: {exit_status}\n"
                if error:
                    logs += f"   Error: {error}\n"
                logs += "\n"
                # Don't fail on non-zero exit codes for cleanup commands
                # (some commands intentionally return non-zero, like "kill" when no process found)

        logs += "=" * 50 + "\n"
        logs += "✅ Fix execution completed!\n"
        return True, logs

    except ValueError as e:
        logs += f"\n❌ KEY ERROR: {str(e)}\n"
        return False, logs
    except paramiko.AuthenticationException:
        logs += f"\n❌ AUTH ERROR: SSH authentication failed.\n"
        return False, logs
    except paramiko.ssh_exception.NoValidConnectionsError:
        logs += f"\n❌ CONNECTION ERROR: Cannot reach {ip_address}.\n"
        return False, logs
    except Exception as e:
        logs += f"\n❌ ERROR: {str(e)}\n"
        return False, logs
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass