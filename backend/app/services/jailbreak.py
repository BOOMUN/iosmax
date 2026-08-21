from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..jailbreak import JailbreakType, normalize_jailbreak_type
from ..models import Device
from .ssh import _connect


ROOTHIDE_JBROOT_PATTERN = re.compile(
    r"^/var/containers/Bundle/Application/\.jbroot-[A-Za-z0-9._-]+$"
)


class JailbreakDetectionError(RuntimeError):
    pass


class JailbreakTypeMismatchError(JailbreakDetectionError):
    pass


@dataclass(frozen=True)
class JailbreakEnvironment:
    jailbreak_type: JailbreakType
    jbroot: str


DETECTION_COMMAND = (
    "if [ -x /usr/bin/jbroot ]; then "
    "root=$(/usr/bin/jbroot 2>/dev/null || true); "
    "case \"$root\" in "
    "/var/containers/Bundle/Application/.jbroot-*) "
    "printf 'roothide\\t%s\\n' \"$root\"; exit 0;; "
    "esac; fi; "
    "if [ -d /var/jb ]; then printf 'rootless\\t/var/jb\\n'; exit 0; fi; "
    "echo 'unsupported jailbreak environment' >&2; exit 1"
)


def _parse_detection(raw: str) -> JailbreakEnvironment:
    kind, separator, jbroot = raw.strip().partition("\t")
    if not separator:
        raise JailbreakDetectionError("设备未返回有效的越狱环境信息")
    jbroot = jbroot.rstrip("/") or "/"
    try:
        jailbreak_type = normalize_jailbreak_type(kind)
    except ValueError as exc:
        raise JailbreakDetectionError(str(exc)) from exc
    if jailbreak_type is JailbreakType.ROOTLESS and jbroot != "/var/jb":
        raise JailbreakDetectionError(f"rootless 根目录无效：{jbroot}")
    if (
        jailbreak_type is JailbreakType.ROOTHIDE
        and not ROOTHIDE_JBROOT_PATTERN.fullmatch(jbroot)
    ):
        raise JailbreakDetectionError(f"RootHide 根目录无效：{jbroot}")
    return JailbreakEnvironment(jailbreak_type=jailbreak_type, jbroot=jbroot)


def detect_jailbreak_environment(client: Any) -> JailbreakEnvironment:
    try:
        _, stdout, stderr = client.exec_command(DETECTION_COMMAND, timeout=10)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace").strip()
        exit_status = stdout.channel.recv_exit_status()
    except OSError as exc:
        raise JailbreakDetectionError("无法查询设备越狱环境") from exc
    if exit_status != 0:
        raise JailbreakDetectionError(error or "未检测到 rootless 或 RootHide 环境")
    return _parse_detection(output)


def detect_device_jailbreak(device: Device) -> JailbreakEnvironment:
    client = _connect(device)
    try:
        return detect_jailbreak_environment(client)
    finally:
        client.close()


def require_matching_environment(
    device: Device, environment: JailbreakEnvironment
) -> JailbreakEnvironment:
    configured = normalize_jailbreak_type(device.jailbreak_type)
    if configured is not environment.jailbreak_type:
        raise JailbreakTypeMismatchError(
            f"设备配置为 {configured.value}，实际检测为 "
            f"{environment.jailbreak_type.value}；请先修正设备类型，禁止跨版本注入"
        )
    return environment
