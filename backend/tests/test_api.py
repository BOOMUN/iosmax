import socketserver
import threading
import time
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas import CameraInjectionStatus
from app.services.camera_injection import prepare_qr_png


def test_auth_and_device_lifecycle():
    with TestClient(app) as client:
        assert client.get("/api/devices").status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword123!"},
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True

        created = client.post(
            "/api/devices",
            json={
                "name": "Hong Kong iPhone 12",
                "host": "100.64.0.2",
                "ssh_password": "not-returned",
                "vnc_password": "also-not-returned",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["vnc_port"] == 5901
        assert body["jailbreak_type"] == "rootless"
        assert body["has_ssh_password"] is True
        assert body["has_vnc_password"] is True
        assert "ssh_password" not in body
        assert "vnc_password" not in body

        updated = client.patch(
            f"/api/devices/{body['id']}", json={"jailbreak_type": "roothide"}
        )
        assert updated.status_code == 200
        assert updated.json()["jailbreak_type"] == "roothide"

        listed = client.get("/api/devices")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        changed = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "TestPassword123!",
                "new_password": "A-Different-Password123!",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["must_change_password"] is False

        deleted = client.delete(f"/api/devices/{body['id']}")
        assert deleted.status_code == 204


def test_rejects_host_with_protocol():
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword123!"},
        )
        response = client.post(
            "/api/devices",
            json={"name": "Bad host", "host": "http://100.64.0.2"},
        )
        assert response.status_code == 422


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(65536):
            self.request.sendall(data)


def test_authenticated_vnc_binary_bridge():
    server = socketserver.TCPServer(("127.0.0.1", 0), EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "TestPassword123!"},
            )
            created = client.post(
                "/api/devices",
                json={
                    "name": "Echo VNC",
                    "host": "127.0.0.1",
                    "vnc_port": server.server_address[1],
                },
            ).json()
            with client.websocket_connect(
                f"/ws/vnc/{created['id']}", subprotocols=["binary"]
            ) as websocket:
                greeting = b"RFB 003.008\n"
                websocket.send_bytes(greeting)
                assert websocket.receive_bytes() == greeting
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_qr_png_is_normalized_with_white_margin():
    source = Image.new("RGB", (120, 100), "black")
    raw = BytesIO()
    source.save(raw, format="PNG")

    result = Image.open(BytesIO(prepare_qr_png(raw.getvalue())))
    assert result.format == "PNG"
    assert result.width == result.height
    assert result.width > 120
    assert result.getpixel((0, 0)) == (255, 255, 255)


def test_camera_injection_accepts_authenticated_png(monkeypatch):
    source = Image.new("RGB", (128, 128), "white")
    raw = BytesIO()
    source.save(raw, format="PNG")

    def fake_start(device, png, qr_text, qr_data_base64, qr_version, timeout_seconds):
        assert device.host == "127.0.0.1"
        assert png.startswith(b"\x89PNG")
        assert qr_text == "test"
        assert qr_data_base64 == "dGVzdA=="
        assert qr_version == 1
        assert timeout_seconds == 30
        return CameraInjectionStatus(
            device_id=device.id,
            status="waiting-camera",
            message="等待摄像头",
        )

    monkeypatch.setattr(
        "app.api.camera.camera_injection_manager.start", fake_start
    )
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword123!"},
        )
        device = client.post(
            "/api/devices", json={"name": "Camera Test", "host": "127.0.0.1"}
        ).json()
        response = client.post(
            f"/api/devices/{device['id']}/camera-injection",
            data={
                "timeout_seconds": "30",
                "qr_text": "test",
                "qr_data_base64": "dGVzdA==",
                "qr_version": "1",
            },
            files={"image": ("qr.png", raw.getvalue(), "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "waiting-camera"


def test_camera_injection_demo_reports_frame_progress(monkeypatch):
    monkeypatch.setattr("app.services.camera_injection.DEMO_STEP_SECONDS", 0.01)
    source = Image.new("RGB", (128, 128), "white")
    raw = BytesIO()
    source.save(raw, format="PNG")

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword123!"},
        )
        device = client.post(
            "/api/devices", json={"name": "Demo Device", "host": "127.0.0.1"}
        ).json()
        started = client.post(
            f"/api/devices/{device['id']}/camera-injection",
            data={
                "timeout_seconds": "30",
                "demo": "true",
                "qr_text": "test",
                "qr_data_base64": "dGVzdA==",
                "qr_version": "1",
            },
            files={"image": ("qr.png", raw.getvalue(), "image/png")},
        )
        assert started.status_code == 200
        assert started.json()["status"] == "connecting"

        time.sleep(0.15)
        completed = client.get(
            f"/api/devices/{device['id']}/camera-injection"
        ).json()
        assert completed["status"] == "stopped"
        assert completed["frames_replaced"] == 60
        assert completed["delegate_class"] == "IOSMaxDemoCaptureDelegate"
        assert "演示完成" in completed["message"]


def test_frida_agent_bundles_version_17_objc_bridge():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "frida_scripts"
        / "whatsapp_camera.js"
    ).read_text(encoding="utf-8")
    assert "getGlobalExportByName" in source
    assert "node_modules/frida-objc-bridge/" in source
    assert "captureOutput:didOutputSampleBuffer:fromConnection:" in source
    assert "render_toCVPixelBuffer_bounds_colorSpace_" in source
    assert "return [[x, y], [width, height]]" in source
    assert "const size = extent[1]" in source
    assert "WAWebClientQRCodeScannerViewController" in source
    assert "CIDetector" not in source
    assert "CACurrentMediaTime" in source
    assert "qr-accepted" in source
    assert "captureOutput_didOutputMetadataObjects_fromConnection_" in source
    assert "metadata-dispatched" in source
    assert "metadata-pipeline-captured" in source
    assert "video-controller-seen" in source
