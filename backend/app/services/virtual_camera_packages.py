from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..jailbreak import JailbreakType, normalize_jailbreak_type
from ..models import Device


PACKAGE_ID = "com.iosmax.virtualcamera"


class VirtualCameraPackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class VirtualCameraPackage:
    jailbreak_type: JailbreakType
    package_id: str
    version: str
    architecture: str
    filename: str
    sha256: str
    path: Path


def load_virtual_camera_package(
    jailbreak_type: str | JailbreakType,
) -> VirtualCameraPackage:
    resolved_type = normalize_jailbreak_type(jailbreak_type)
    variant_directory = (
        settings.project_root
        / "artifacts"
        / "virtual-camera"
        / resolved_type.value
    ).resolve()
    manifest_path = variant_directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VirtualCameraPackageError(
            f"无法读取 {resolved_type.value} 虚拟摄像头清单"
        ) from exc

    if manifest.get("jailbreak_type") != resolved_type.value:
        raise VirtualCameraPackageError("安装包清单的越狱类型不匹配")
    if manifest.get("package_id") != PACKAGE_ID:
        raise VirtualCameraPackageError("安装包清单的 package id 无效")
    if manifest.get("deployable") is not True:
        raise VirtualCameraPackageError("该越狱类型当前没有可部署安装包")

    filename = str(manifest.get("filename", ""))
    package_path = (variant_directory / filename).resolve()
    try:
        package_path.relative_to(variant_directory)
    except ValueError as exc:
        raise VirtualCameraPackageError("安装包路径越出对应变体目录") from exc
    if not package_path.is_file():
        raise VirtualCameraPackageError(f"安装包不存在：{filename}")

    expected_sha256 = str(manifest.get("sha256", "")).lower()
    actual_sha256 = hashlib.sha256(package_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise VirtualCameraPackageError(f"安装包校验失败：{filename}")

    return VirtualCameraPackage(
        jailbreak_type=resolved_type,
        package_id=PACKAGE_ID,
        version=str(manifest.get("version", "")),
        architecture=str(manifest.get("architecture", "")),
        filename=filename,
        sha256=actual_sha256,
        path=package_path,
    )


def virtual_camera_package_for_device(device: Device) -> VirtualCameraPackage:
    return load_virtual_camera_package(device.jailbreak_type)
