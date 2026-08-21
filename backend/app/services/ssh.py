from __future__ import annotations

from dataclasses import dataclass

import paramiko

from ..config import settings
from ..models import Device
from ..security import decrypt_secret


@dataclass
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_status: int


def _connect(device: Device) -> paramiko.SSHClient:
    password = decrypt_secret(device.ssh_password_encrypted)
    if not password:
        raise ValueError("该设备尚未配置 SSH 密码")
    known_hosts = settings.data_dir / "known_hosts"
    client = paramiko.SSHClient()
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=device.host,
        port=device.ssh_port,
        username=device.ssh_username,
        password=password,
        timeout=8,
        auth_timeout=8,
        banner_timeout=8,
        look_for_keys=False,
        allow_agent=False,
    )
    client.save_host_keys(str(known_hosts))
    return client


def execute(device: Device, command: str) -> CommandResult:
    client = _connect(device)
    try:
        _, stdout, stderr = client.exec_command(command, timeout=15)
        exit_status = stdout.channel.recv_exit_status()
        return CommandResult(
            command=command,
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
            exit_status=exit_status,
        )
    finally:
        client.close()
