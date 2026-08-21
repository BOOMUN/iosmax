from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Any

from ..jailbreak import JailbreakType
from ..models import Device
from .jailbreak import detect_jailbreak_environment, require_matching_environment
from .ssh import _connect


SHARED_RELATIVE_DIRECTORY = "var/mobile/Library/Caches/com.iosmax.virtualcamera"


class VirtualCameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class VirtualCameraLocation:
    jailbreak_type: JailbreakType
    jbroot: str

    @property
    def directory(self) -> str:
        if self.jailbreak_type is JailbreakType.ROOTLESS:
            return "/var/jb/var/mobile/Library/Caches/com.iosmax.virtualcamera"
        return posixpath.join(self.jbroot, SHARED_RELATIVE_DIRECTORY)

    @property
    def frame(self) -> str:
        return posixpath.join(self.directory, "frame.png")

    @property
    def control(self) -> str:
        return posixpath.join(self.directory, "daemon-control.txt")

    @property
    def status(self) -> str:
        return posixpath.join(self.directory, "daemon-status.txt")


def _find_location(
    client: Any, _sftp: Any, device: Device
) -> VirtualCameraLocation:
    try:
        environment = require_matching_environment(
            device, detect_jailbreak_environment(client)
        )
    except (RuntimeError, ValueError) as exc:
        raise VirtualCameraError(str(exc)) from exc
    return VirtualCameraLocation(
        jailbreak_type=environment.jailbreak_type,
        jbroot=environment.jbroot,
    )


def _ensure_directory(sftp: Any, path: str) -> None:
    current = "/"
    for component in path.strip("/").split("/"):
        current = posixpath.join(current, component)
        try:
            sftp.stat(current)
        except OSError:
            try:
                sftp.mkdir(current, mode=0o755)
            except OSError as exc:
                raise VirtualCameraError(f"无法创建虚拟相机目录：{current}") from exc


def _atomic_write(sftp: Any, path: str, data: bytes) -> None:
    temporary = f"{path}.iosmax-new"
    try:
        with sftp.open(temporary, "wb") as output:
            output.write(data)
        sftp.chmod(temporary, 0o644)
        try:
            sftp.posix_rename(temporary, path)
        except (AttributeError, OSError):
            try:
                sftp.remove(path)
            except OSError:
                pass
            sftp.rename(temporary, path)
    except OSError as exc:
        raise VirtualCameraError(f"无法写入虚拟相机文件：{path}") from exc


def _control_text(enabled: bool, target_pid: int = 0) -> bytes:
    if enabled and not 1 <= target_pid <= 2_147_483_647:
        raise VirtualCameraError("WhatsApp 进程 PID 无效")
    return (
        f"enabled={1 if enabled else 0}\n"
        f"target_pid={target_pid if enabled else 0}\n"
    ).encode("ascii")


def _parse_status(raw: bytes) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()

    def integer(name: str) -> int:
        try:
            return int(values.get(name, "0"))
        except ValueError:
            return 0

    event = values.get("event", "unknown")
    error_code = integer("error_code")
    return {
        "Event": event,
        "PID": integer("pid"),
        "TargetPID": integer("target_pid"),
        "HookInstalled": bool(integer("hook_installed")),
        "Enabled": bool(integer("enabled")),
        "BuffersSeen": integer("buffers_seen"),
        "FramesReplaced": integer("frames_replaced"),
        "SessionFramesReplaced": integer("session_frames_replaced"),
        "Width": integer("width"),
        "Height": integer("height"),
        "PixelFormat": integer("pixel_format"),
        "ErrorCode": error_code,
        "LastError": event if error_code else "",
    }


def enable_virtual_camera(
    device: Device,
    png: bytes,
    target_pid: int,
) -> VirtualCameraLocation:
    client = _connect(device)
    try:
        sftp = client.open_sftp()
        try:
            location = _find_location(client, sftp, device)
            _ensure_directory(sftp, location.directory)
            _atomic_write(sftp, location.frame, png)
            # Control is committed last, so mediaserverd never reads a partial PNG.
            _atomic_write(sftp, location.control, _control_text(True, target_pid))
            return location
        finally:
            sftp.close()
    finally:
        client.close()


def disable_virtual_camera(
    device: Device, location: VirtualCameraLocation | None = None
) -> VirtualCameraLocation:
    client = _connect(device)
    try:
        sftp = client.open_sftp()
        try:
            resolved = location or _find_location(client, sftp, device)
            _ensure_directory(sftp, resolved.directory)
            _atomic_write(sftp, resolved.control, _control_text(False))
            return resolved
        finally:
            sftp.close()
    finally:
        client.close()


def read_virtual_camera_status(
    device: Device, location: VirtualCameraLocation | None = None
) -> tuple[VirtualCameraLocation, dict[str, Any]]:
    client = _connect(device)
    try:
        sftp = client.open_sftp()
        try:
            resolved = location or _find_location(client, sftp, device)
            try:
                with sftp.open(resolved.status, "rb") as status_file:
                    status = _parse_status(status_file.read())
            except OSError as exc:
                raise VirtualCameraError(
                    "底层虚拟相机状态不存在，请确认 tweak 已安装并重启 mediaserverd"
                ) from exc
            return resolved, status
        finally:
            sftp.close()
    finally:
        client.close()
