from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import socket
import socketserver
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko

from ..config import settings
from ..database import SessionLocal
from ..models import Device
from ..security import decrypt_secret


logger = logging.getLogger(__name__)
MAX_DISCOVERY_HOSTS = 512


def ssh_key_sha256(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


@dataclass(frozen=True)
class PortForward:
    local_port: int
    remote_port: int
    remote_host: str = "127.0.0.1"


@dataclass(frozen=True)
class TunnelConfig:
    name: str
    source_device_id: int
    device_udid: str
    ssh_host: str
    ssh_port: int
    host_key_type: str
    host_key_sha256: str
    candidate_networks: tuple[str, ...]
    forwards: tuple[PortForward, ...]
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TunnelConfig":
        forwards = tuple(PortForward(**item) for item in raw.get("forwards", ()))
        if not forwards:
            raise ValueError("Wireless tunnel requires at least one port forward")
        local_ports = [item.local_port for item in forwards]
        if len(local_ports) != len(set(local_ports)):
            raise ValueError("Wireless tunnel local ports must be unique")
        for item in forwards:
            if not (1 <= item.local_port <= 65535 and 1 <= item.remote_port <= 65535):
                raise ValueError("Wireless tunnel port is outside 1-65535")
            if item.remote_host not in {"127.0.0.1", "::1"}:
                raise ValueError("Wireless tunnel remote host must remain loopback-only")
        return cls(
            name=str(raw["name"]),
            source_device_id=int(raw["source_device_id"]),
            device_udid=str(raw["device_udid"]),
            ssh_host=str(raw["ssh_host"]),
            ssh_port=int(raw.get("ssh_port", 22)),
            host_key_type=str(raw["host_key_type"]),
            host_key_sha256=str(raw["host_key_sha256"]),
            candidate_networks=tuple(str(item) for item in raw.get("candidate_networks", ())),
            forwards=forwards,
            enabled=bool(raw.get("enabled", True)),
        )


class _ForwardingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ManagedWirelessTunnel:
    def __init__(self, config: TunnelConfig) -> None:
        self.config = config
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._transport_lock = threading.RLock()
        self._transport: paramiko.Transport | None = None
        self._last_host = config.ssh_host
        self._servers: list[_ForwardingServer] = []
        self._server_threads: list[threading.Thread] = []
        self._connection_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._connection_thread is not None:
            return
        try:
            for forward in self.config.forwards:
                server = _ForwardingServer(
                    ("127.0.0.1", forward.local_port),
                    self._handler_for(forward),
                )
                thread = threading.Thread(
                    target=server.serve_forever,
                    name=f"wireless-{self.config.name}-{forward.local_port}",
                    daemon=True,
                )
                self._servers.append(server)
                self._server_threads.append(thread)
                thread.start()
        except Exception:
            self.stop()
            raise
        self._connection_thread = threading.Thread(
            target=self._connection_loop,
            name=f"wireless-{self.config.name}-ssh",
            daemon=True,
        )
        self._connection_thread.start()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        self._ready.clear()
        with self._transport_lock:
            transport, self._transport = self._transport, None
        if transport is not None:
            transport.close()
        for server in self._servers:
            server.shutdown()
            server.server_close()
        for thread in self._server_threads:
            thread.join(timeout=2)
        if self._connection_thread is not None:
            self._connection_thread.join(timeout=3)
        self._servers.clear()
        self._server_threads.clear()
        self._connection_thread = None

    def _handler_for(self, forward: PortForward):
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                owner._forward_connection(self.request, self.client_address, forward)

        return Handler

    def _active_transport(self) -> paramiko.Transport | None:
        with self._transport_lock:
            if self._transport is not None and self._transport.is_active():
                return self._transport
        return None

    def _forward_connection(
        self,
        client: socket.socket,
        client_address: tuple[str, int],
        forward: PortForward,
    ) -> None:
        transport = self._active_transport()
        if transport is None:
            return
        try:
            channel = transport.open_channel(
                "direct-tcpip",
                (forward.remote_host, forward.remote_port),
                client_address,
                timeout=8,
            )
        except Exception:
            logger.exception(
                "Unable to open %s wireless forward to %s:%s",
                self.config.name,
                forward.remote_host,
                forward.remote_port,
            )
            return
        if channel is None:
            return

        finished = threading.Event()
        client.settimeout(1)
        channel.settimeout(1)

        def pump(source, destination) -> None:
            try:
                while not self._stop.is_set() and not finished.is_set():
                    try:
                        data = source.recv(65536)
                    except (socket.timeout, TimeoutError):
                        continue
                    if not data:
                        break
                    destination.sendall(data)
            except (OSError, EOFError):
                pass
            finally:
                finished.set()

        upstream = threading.Thread(target=pump, args=(client, channel), daemon=True)
        upstream.start()
        pump(channel, client)
        try:
            channel.close()
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            upstream.join(timeout=2)

    def _connection_loop(self) -> None:
        while not self._stop.is_set():
            transport = None
            try:
                host = self._connect_host()
                transport = self._open_verified_transport(host)
                self._verify_udid(transport)
                transport.set_keepalive(15)
                with self._transport_lock:
                    self._transport = transport
                self._last_host = host
                self._ready.set()
                logger.info("Wireless tunnel %s connected through %s", self.config.name, host)
                while not self._stop.wait(1) and transport.is_active():
                    pass
            except Exception as exc:
                logger.warning("Wireless tunnel %s disconnected: %s", self.config.name, exc)
            finally:
                self._ready.clear()
                with self._transport_lock:
                    if self._transport is transport:
                        self._transport = None
                if transport is not None:
                    transport.close()
            self._stop.wait(15)

    def _credentials(self) -> tuple[str, str]:
        with SessionLocal() as db:
            device = db.get(Device, self.config.source_device_id)
            if device is None:
                raise RuntimeError(
                    f"Wireless source device {self.config.source_device_id} does not exist"
                )
            username = device.ssh_username
            password = decrypt_secret(device.ssh_password_encrypted)
        if not password:
            raise RuntimeError("Wireless source device has no SSH password")
        return username, password

    def _open_verified_transport(self, host: str) -> paramiko.Transport:
        username, password = self._credentials()
        raw_socket = socket.create_connection((host, self.config.ssh_port), timeout=5)
        transport = paramiko.Transport(raw_socket)
        try:
            transport.start_client(timeout=8)
            key = transport.get_remote_server_key()
            if (
                key.get_name() != self.config.host_key_type
                or ssh_key_sha256(key) != self.config.host_key_sha256
            ):
                raise RuntimeError(f"SSH host key mismatch for {host}")
            transport.auth_password(username, password)
            if not transport.is_authenticated():
                raise RuntimeError(f"SSH authentication failed for {host}")
            return transport
        except Exception:
            transport.close()
            raise

    def _verify_udid(self, transport: paramiko.Transport) -> None:
        channel = transport.open_session(timeout=8)
        try:
            channel.exec_command(
                "PATH=/var/jb/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin; "
                "deviceinfo uniqueid 2>/dev/null"
            )
            output = bytearray()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if channel.recv_ready():
                    output.extend(channel.recv(4096))
                if channel.exit_status_ready():
                    while channel.recv_ready():
                        output.extend(channel.recv(4096))
                    break
                time.sleep(0.05)
            actual = output.decode("utf-8", "replace").strip()
            if actual != self.config.device_udid:
                raise RuntimeError(f"Wireless device identity mismatch: {actual or 'unknown'}")
        finally:
            channel.close()

    def _connect_host(self) -> str:
        try:
            transport = self._open_verified_transport(self._last_host)
        except Exception:
            return self._discover_host()
        else:
            transport.close()
            return self._last_host

    def _discover_host(self) -> str:
        candidates: list[str] = []
        seen: set[str] = set()
        for network_text in self.config.candidate_networks:
            network = ipaddress.ip_network(network_text, strict=False)
            if network.version != 4 or network.num_addresses > 256:
                continue
            for host in network.hosts():
                text = str(host)
                if text not in seen:
                    seen.add(text)
                    candidates.append(text)
                if len(candidates) >= MAX_DISCOVERY_HOSTS:
                    break

        def matches(host: str) -> bool:
            raw_socket = None
            transport = None
            try:
                raw_socket = socket.create_connection((host, self.config.ssh_port), timeout=0.6)
                transport = paramiko.Transport(raw_socket)
                transport.start_client(timeout=2)
                key = transport.get_remote_server_key()
                return (
                    key.get_name() == self.config.host_key_type
                    and ssh_key_sha256(key) == self.config.host_key_sha256
                )
            except Exception:
                return False
            finally:
                if transport is not None:
                    transport.close()
                elif raw_socket is not None:
                    raw_socket.close()

        with ThreadPoolExecutor(max_workers=32) as pool:
            futures = {pool.submit(matches, host): host for host in candidates}
            for future in as_completed(futures):
                if self._stop.is_set():
                    break
                if future.result():
                    return futures[future]
        raise RuntimeError("Matching iPhone SSH host key was not found on configured networks")


class WirelessTunnelManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or settings.data_dir / "wireless_tunnels.json"
        self._tunnels: list[ManagedWirelessTunnel] = []
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._tunnels or not self.config_path.is_file():
                return
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            configs = [TunnelConfig.from_dict(item) for item in raw.get("tunnels", ())]
            tunnels = [ManagedWirelessTunnel(item) for item in configs if item.enabled]
            try:
                for tunnel in tunnels:
                    tunnel.start()
            except Exception:
                for tunnel in tunnels:
                    tunnel.stop()
                raise
            self._tunnels = tunnels

    def wait_ready(self, timeout: float = 12) -> bool:
        deadline = time.monotonic() + timeout
        with self._lock:
            tunnels = list(self._tunnels)
        return all(tunnel.wait_ready(max(0, deadline - time.monotonic())) for tunnel in tunnels)

    def stop(self) -> None:
        with self._lock:
            tunnels, self._tunnels = self._tunnels, []
        for tunnel in tunnels:
            tunnel.stop()


wireless_tunnel_manager = WirelessTunnelManager()
