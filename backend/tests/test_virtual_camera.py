import pytest

from app.jailbreak import JailbreakType
from app.services.jailbreak import (
    JailbreakDetectionError,
    _parse_detection,
)
from app.services.virtual_camera import (
    VirtualCameraLocation,
    _control_text,
    _parse_status,
)
from app.services.virtual_camera_packages import load_virtual_camera_package


def test_daemon_control_targets_whatsapp_pid():
    assert _control_text(True, 12345) == b"enabled=1\ntarget_pid=12345\n"
    assert _control_text(False, 12345) == b"enabled=0\ntarget_pid=0\n"


def test_daemon_status_is_mapped_for_injection_manager():
    status = _parse_status(
        b"event=frame-replaced\n"
        b"pid=10958\n"
        b"target_pid=10345\n"
        b"hook_installed=1\n"
        b"enabled=1\n"
        b"buffers_seen=359\n"
        b"frames_replaced=120\n"
        b"session_frames_replaced=37\n"
        b"width=480\n"
        b"height=640\n"
        b"pixel_format=875704438\n"
        b"error_code=0\n"
    )
    assert status["Event"] == "frame-replaced"
    assert status["HookInstalled"] is True
    assert status["Enabled"] is True
    assert status["FramesReplaced"] == 120
    assert status["SessionFramesReplaced"] == 37
    assert status["TargetPID"] == 10345
    assert status["LastError"] == ""


def test_daemon_location_uses_roothide_shared_cache():
    location = VirtualCameraLocation(
        JailbreakType.ROOTHIDE,
        "/var/containers/Bundle/Application/.jbroot-ABC123",
    )
    assert location.control.endswith(
        "/var/mobile/Library/Caches/com.iosmax.virtualcamera/daemon-control.txt"
    )
    assert location.status.endswith("/daemon-status.txt")


def test_daemon_location_uses_dopamine_mobile_cache():
    location = VirtualCameraLocation(JailbreakType.ROOTLESS, "/var/jb")
    assert location.directory == "/var/jb/var/mobile/Library/Caches/com.iosmax.virtualcamera"
    assert location.control.endswith("/daemon-control.txt")


def test_jailbreak_detection_distinguishes_rootless_and_roothide():
    rootless = _parse_detection("rootless\t/var/jb\n")
    roothide = _parse_detection(
        "roothide\t/var/containers/Bundle/Application/.jbroot-ABC123/\n"
    )
    assert rootless.jailbreak_type is JailbreakType.ROOTLESS
    assert rootless.jbroot == "/var/jb"
    assert roothide.jailbreak_type is JailbreakType.ROOTHIDE


def test_jailbreak_detection_rejects_cross_variant_root():
    with pytest.raises(JailbreakDetectionError):
        _parse_detection("rootless\t/var/containers/Bundle/Application/.jbroot-ABC123")


def test_variant_manifests_resolve_separate_verified_packages():
    rootless = load_virtual_camera_package(JailbreakType.ROOTLESS)
    roothide = load_virtual_camera_package(JailbreakType.ROOTHIDE)
    assert rootless.architecture == "iphoneos-arm64"
    assert roothide.architecture == "iphoneos-arm64e"
    assert rootless.path.parent.name == "rootless"
    assert roothide.path.parent.name == "roothide"
    assert rootless.sha256 != roothide.sha256
