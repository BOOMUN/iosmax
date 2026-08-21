import socketserver
import struct
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.system_control import SystemControlError, _wake_screen


def recv_exact(connection, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("VNC test client disconnected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class SystemControlHandler(socketserver.BaseRequestHandler):
    def handle(self):
        connection = self.request
        connection.sendall(b"RFB 003.008\n")
        assert recv_exact(connection, 12) == b"RFB 003.008\n"
        security_type = self.server.security_type
        connection.sendall(bytes([1, security_type]))
        assert recv_exact(connection, 1) == bytes([security_type])
        if security_type == 2:
            challenge = bytes(range(16))
            connection.sendall(challenge)
            self.server.auth_responses.append(recv_exact(connection, 16))
        connection.sendall(struct.pack("!I", 0))
        assert recv_exact(connection, 1) == b"\x01"

        name = b"Test iPhone"
        connection.sendall(
            struct.pack("!HH", 844, 1829)
            + bytes(16)
            + struct.pack("!I", len(name))
            + name
        )
        down = struct.unpack("!BBHH", recv_exact(connection, 6))
        up = struct.unpack("!BBHH", recv_exact(connection, 6))
        self.server.events.append((down, up))


class SystemControlServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, address, security_type=1):
        self.events = []
        self.security_type = security_type
        self.auth_responses = []
        super().__init__(address, SystemControlHandler)


def test_authenticated_system_controls_wake_and_send_home_button(monkeypatch):
    server = SystemControlServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    wake_device_ids = []
    monkeypatch.setattr(
        "app.services.system_control._wake_screen",
        lambda device: wake_device_ids.append(device.id),
    )
    try:
        with TestClient(app) as client:
            assert client.post("/api/devices/1/system", json={"action": "wake"}).status_code == 401
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "TestPassword123!"},
            )
            device = client.post(
                "/api/devices",
                json={
                    "name": "System Control Test",
                    "host": "127.0.0.1",
                    "vnc_port": server.server_address[1],
                },
            ).json()

            wake = client.post(
                f"/api/devices/{device['id']}/system", json={"action": "wake"}
            )
            assert wake.status_code == 200
            assert wake.json() == {
                "success": True,
                "action": "wake",
                "message": "屏幕已唤醒",
            }

            home = client.post(
                f"/api/devices/{device['id']}/system", json={"action": "home"}
            )
            assert home.status_code == 200
            assert home.json()["action"] == "home"

            invalid = client.post(
                f"/api/devices/{device['id']}/system", json={"action": "restart"}
            )
            assert invalid.status_code == 422
            assert "/api/devices/{device_id}/apps" not in app.openapi()["paths"]

        assert wake_device_ids == [device["id"]]
        assert [event[0][1] for event in server.events] == [4]
        assert [event[1][1] for event in server.events] == [0]
        assert all(event[0][2:] == (422, 914) for event in server.events)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_system_control_supports_encrypted_vnc_password():
    server = SystemControlServer(("127.0.0.1", 0), security_type=2)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "TestPassword123!"},
            )
            device = client.post(
                "/api/devices",
                json={
                    "name": "Password VNC Test",
                    "host": "127.0.0.1",
                    "vnc_port": server.server_address[1],
                    "vnc_password": "password",
                },
            ).json()
            assert device["has_vnc_password"] is True
            assert "vnc_password" not in device

            response = client.post(
                f"/api/devices/{device['id']}/system", json={"action": "home"}
            )
            assert response.status_code == 200

        assert [response.hex() for response in server.auth_responses] == [
            "b866924125c8eebb9debc1db61c538e2"
        ]
        assert server.events[0][0][1] == 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wake_uses_springboard_and_confirms_screen_state(monkeypatch):
    calls = []

    class FakeExports:
        def wake(self):
            calls.append("wake")
            return {"screen_on": False, "ui_locked": True}

        def state(self):
            calls.append("state")
            return {"screen_on": True, "ui_locked": True}

    class FakeScript:
        exports_sync = FakeExports()

        def load(self):
            calls.append("load")

    class FakeSession:
        def create_script(self, source):
            assert "turnOnScreenFullyWithBacklightSource_" in source
            calls.append("create-script")
            return FakeScript()

        def detach(self):
            calls.append("detach")

    class FakeRemote:
        def attach(self, process):
            assert process == "SpringBoard"
            calls.append("attach")
            return FakeSession()

    class FakeManager:
        def add_remote_device(self, endpoint):
            assert endpoint == "192.0.2.12:27042"
            calls.append("remote")
            return FakeRemote()

    monkeypatch.setattr(
        "app.services.system_control.frida.get_device_manager",
        lambda: FakeManager(),
    )
    _wake_screen(SimpleNamespace(host="192.0.2.12", frida_port=27042))

    assert calls == [
        "remote",
        "attach",
        "create-script",
        "load",
        "wake",
        "state",
        "detach",
    ]


def test_wake_rejects_unconfirmed_screen_state(monkeypatch):
    script = SimpleNamespace(
        load=lambda: None,
        exports_sync=SimpleNamespace(
            wake=lambda: {"screen_on": False},
            state=lambda: {"screen_on": False},
        ),
    )
    session = SimpleNamespace(create_script=lambda source: script, detach=lambda: None)
    remote = SimpleNamespace(attach=lambda process: session)
    manager = SimpleNamespace(add_remote_device=lambda endpoint: remote)
    monkeypatch.setattr(
        "app.services.system_control.frida.get_device_manager",
        lambda: manager,
    )
    monkeypatch.setattr("app.services.system_control.time.sleep", lambda _: None)

    with pytest.raises(SystemControlError, match="未确认屏幕已唤醒"):
        _wake_screen(SimpleNamespace(host="192.0.2.12", frida_port=27042))
