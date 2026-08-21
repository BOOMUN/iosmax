from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import frida
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from ..models import Device
from ..security import decrypt_secret


SystemAction = Literal["wake", "home"]

_HOME_BUTTON_MASK = 4  # TrollVNC maps the right pointer button to Home/Menu.
_AGENT_SOURCE = (
    Path(__file__).resolve().parents[1] / "frida_scripts" / "system_control.js"
).read_text(encoding="utf-8")


class SystemControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class SystemControlResult:
    action: SystemAction
    message: str


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise SystemControlError("TrollVNC 在系统按键发送前断开连接")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _reverse_bits(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)


def _vnc_auth_response(password: str, challenge: bytes) -> bytes:
    if len(challenge) != 16:
        raise SystemControlError("TrollVNC 返回了无效的认证挑战")
    password_bytes = password.encode("utf-8")[:8].ljust(8, b"\0")
    key = bytes(_reverse_bits(value) for value in password_bytes)
    encryptor = Cipher(TripleDES(key * 3), modes.ECB()).encryptor()
    return encryptor.update(challenge) + encryptor.finalize()


def _negotiate_vnc(
    connection: socket.socket, password: str | None
) -> tuple[int, int]:
    version = _recv_exact(connection, 12)
    if not version.startswith(b"RFB "):
        raise SystemControlError("TrollVNC 返回了无效的 RFB 握手")
    connection.sendall(b"RFB 003.008\n")

    security_count = _recv_exact(connection, 1)[0]
    if security_count == 0:
        reason_length = struct.unpack("!I", _recv_exact(connection, 4))[0]
        reason = _recv_exact(connection, reason_length).decode("utf-8", "replace")
        raise SystemControlError(f"TrollVNC 拒绝连接：{reason}")
    security_types = _recv_exact(connection, security_count)
    if password and 2 in security_types:
        selected_security = 2
    elif 1 in security_types:
        selected_security = 1
    elif 2 in security_types:
        raise SystemControlError("该设备需要 TrollVNC 密码，请在设备设置中保存密码")
    else:
        raise SystemControlError("TrollVNC 未提供支持的认证方式")
    connection.sendall(bytes([selected_security]))

    if selected_security == 2:
        challenge = _recv_exact(connection, 16)
        connection.sendall(_vnc_auth_response(password or "", challenge))

    security_result = struct.unpack("!I", _recv_exact(connection, 4))[0]
    if security_result != 0:
        raise SystemControlError("TrollVNC 身份验证失败")

    connection.sendall(b"\x01")  # Share the session with the live viewer.
    server_init = _recv_exact(connection, 24)
    width, height = struct.unpack("!HH", server_init[:4])
    name_length = struct.unpack("!I", server_init[20:24])[0]
    if not width or not height or name_length > 1024 * 1024:
        raise SystemControlError("TrollVNC 返回了无效的屏幕信息")
    _recv_exact(connection, name_length)
    return width, height


def _send_home_button(device: Device) -> None:
    try:
        password = decrypt_secret(device.vnc_password_encrypted)
        with socket.create_connection((device.host, device.vnc_port), timeout=8) as connection:
            connection.settimeout(8)
            width, height = _negotiate_vnc(connection, password)
            x, y = width // 2, height // 2
            connection.sendall(struct.pack("!BBHH", 5, _HOME_BUTTON_MASK, x, y))
            time.sleep(0.08)
            connection.sendall(struct.pack("!BBHH", 5, 0, x, y))
    except SystemControlError:
        raise
    except (OSError, TimeoutError) as exc:
        raise SystemControlError(f"无法连接 TrollVNC：{exc}") from exc


def _wake_screen(device: Device) -> None:
    session = None
    try:
        remote = frida.get_device_manager().add_remote_device(
            f"{device.host}:{device.frida_port}"
        )
        session = remote.attach("SpringBoard")
        script = session.create_script(_AGENT_SOURCE)
        script.load()
        state = script.exports_sync.wake()
        for _ in range(20):
            if isinstance(state, dict) and state.get("screen_on") is True:
                break
            time.sleep(0.1)
            state = script.exports_sync.state()
        if not isinstance(state, dict) or state.get("screen_on") is not True:
            raise SystemControlError("SpringBoard 未确认屏幕已唤醒")
    except SystemControlError:
        raise
    except Exception as exc:
        raise SystemControlError(f"无法通过 SpringBoard 唤醒屏幕：{exc}") from exc
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def send_system_action(device: Device, action: SystemAction) -> SystemControlResult:
    if action == "wake":
        _wake_screen(device)
        return SystemControlResult(action=action, message="屏幕已唤醒")
    if action == "home":
        _send_home_button(device)
        return SystemControlResult(action=action, message="已发送返回桌面按键")
    raise ValueError("不支持的系统操作")
