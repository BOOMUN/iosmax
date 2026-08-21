from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..dependencies import get_current_user, get_db
from ..models import Device, User
from ..schemas import (
    DeviceCreate,
    DeviceProbeResponse,
    DeviceResponse,
    DeviceUpdate,
    JailbreakProbe,
    SystemActionRequest,
    SystemActionResponse,
)
from ..jailbreak import JailbreakType, normalize_jailbreak_type
from ..security import encrypt_secret
from ..services.connectivity import probe_port
from ..services.jailbreak import detect_device_jailbreak
from ..services.system_control import SystemControlError, send_system_action
from ..services.virtual_camera_packages import virtual_camera_package_for_device


router = APIRouter(prefix="/api/devices", tags=["devices"])


def serialize(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        host=device.host,
        ssh_port=device.ssh_port,
        ssh_username=device.ssh_username,
        vnc_port=device.vnc_port,
        frida_port=device.frida_port,
        jailbreak_type=device.jailbreak_type,
        enabled=device.enabled,
        notes=device.notes,
        has_ssh_password=bool(device.ssh_password_encrypted),
        has_vnc_password=bool(device.vnc_password_encrypted),
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def get_device_or_404(db: DbSession, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


async def probe_jailbreak(device: Device) -> JailbreakProbe:
    try:
        configured = normalize_jailbreak_type(device.jailbreak_type)
    except ValueError:
        configured = JailbreakType.ROOTLESS
    package_version = None
    package_architecture = None
    package_filename = None
    package_error = None
    try:
        package = virtual_camera_package_for_device(device)
        package_version = package.version
        package_architecture = package.architecture
        package_filename = package.filename
    except Exception as exc:
        package_error = str(exc)
    if not device.ssh_password_encrypted:
        return JailbreakProbe(
            configured=configured,
            error=package_error or "未配置 SSH 密码，无法自动检测越狱环境",
            package_version=package_version,
            package_architecture=package_architecture,
            package_filename=package_filename,
        )
    try:
        environment = await run_in_threadpool(detect_device_jailbreak, device)
    except Exception as exc:
        return JailbreakProbe(
            configured=configured,
            error=package_error or str(exc),
            package_version=package_version,
            package_architecture=package_architecture,
            package_filename=package_filename,
        )
    matches = configured is environment.jailbreak_type
    return JailbreakProbe(
        configured=configured,
        detected=environment.jailbreak_type,
        matches=matches,
        jbroot=environment.jbroot,
        error=(
            package_error
            if package_error
            else None if matches else "配置类型与设备实际越狱环境不一致"
        ),
        package_version=package_version,
        package_architecture=package_architecture,
        package_filename=package_filename,
    )


@router.get("", response_model=list[DeviceResponse])
def list_devices(
    _: User = Depends(get_current_user), db: DbSession = Depends(get_db)
):
    devices = db.scalars(select(Device).order_by(Device.name)).all()
    return [serialize(device) for device in devices]


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreate,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    values = payload.model_dump(exclude={"ssh_password", "vnc_password"})
    device = Device(**values)
    if payload.ssh_password:
        device.ssh_password_encrypted = encrypt_secret(payload.ssh_password)
    if payload.vnc_password:
        device.vnc_password_encrypted = encrypt_secret(payload.vnc_password)
    db.add(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="设备名称已存在") from exc
    db.refresh(device)
    return serialize(device)


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    device = get_device_or_404(db, device_id)
    values = payload.model_dump(
        exclude_unset=True,
        exclude={
            "ssh_password",
            "clear_ssh_password",
            "vnc_password",
            "clear_vnc_password",
        },
    )
    for key, value in values.items():
        setattr(device, key, value)
    if payload.clear_ssh_password:
        device.ssh_password_encrypted = None
    elif payload.ssh_password:
        device.ssh_password_encrypted = encrypt_secret(payload.ssh_password)
    if payload.clear_vnc_password:
        device.vnc_password_encrypted = None
    elif payload.vnc_password:
        device.vnc_password_encrypted = encrypt_secret(payload.vnc_password)
    db.add(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="设备名称已存在") from exc
    db.refresh(device)
    return serialize(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: int,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    device = get_device_or_404(db, device_id)
    db.delete(device)
    db.commit()


@router.post("/{device_id}/probe", response_model=DeviceProbeResponse)
async def probe_device(
    device_id: int,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    device = get_device_or_404(db, device_id)
    ssh, vnc, frida, jailbreak = await asyncio.gather(
        probe_port(device.host, device.ssh_port),
        probe_port(device.host, device.vnc_port),
        probe_port(device.host, device.frida_port),
        probe_jailbreak(device),
    )
    return DeviceProbeResponse(
        device_id=device.id,
        checked_at=datetime.now(timezone.utc),
        ssh=ssh,
        vnc=vnc,
        frida=frida,
        jailbreak=jailbreak,
    )


@router.post("/{device_id}/system", response_model=SystemActionResponse)
async def control_system(
    device_id: int,
    payload: SystemActionRequest,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    device = get_device_or_404(db, device_id)
    if not device.enabled:
        raise HTTPException(status_code=409, detail="设备已停用")
    try:
        result = await run_in_threadpool(send_system_action, device, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemControlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SystemActionResponse(
        success=True,
        action=result.action,
        message=result.message,
    )
