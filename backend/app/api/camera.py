import base64
import binascii

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..dependencies import get_current_user, get_db
from ..models import Device, User
from ..schemas import CameraInjectionStatus
from ..services.camera_injection import (
    CameraInjectionError,
    camera_injection_manager,
    prepare_qr_png,
)


router = APIRouter(prefix="/api/devices", tags=["camera-injection"])


def get_device_or_404(db: DbSession, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


@router.get("/{device_id}/camera-injection", response_model=CameraInjectionStatus)
def injection_status(
    device_id: int,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    get_device_or_404(db, device_id)
    return camera_injection_manager.get(device_id)


@router.post("/{device_id}/camera-injection", response_model=CameraInjectionStatus)
async def start_injection(
    device_id: int,
    image: UploadFile = File(...),
    qr_text: str = Form(..., min_length=1, max_length=8192),
    qr_version: int = Form(..., ge=1, le=40),
    qr_data_base64: str = Form(..., min_length=1, max_length=16384),
    timeout_seconds: int = Form(default=30, ge=10, le=90),
    demo: bool = Form(default=False),
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    device = get_device_or_404(db, device_id)
    if not device.enabled:
        raise HTTPException(status_code=409, detail="设备已停用")
    if image.content_type not in {"image/png", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="只支持 PNG 图片")
    raw = await image.read(8 * 1024 * 1024 + 1)
    try:
        try:
            qr_data = base64.b64decode(qr_data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CameraInjectionError("二维码原始数据不是有效 Base64") from exc
        if not qr_data or len(qr_data) > 8192:
            raise CameraInjectionError("二维码原始数据长度无效")
        png = await run_in_threadpool(prepare_qr_png, raw)
        if demo:
            if not settings.injection_demo:
                raise CameraInjectionError("本地反馈演示未启用")
            return camera_injection_manager.start_demo(device.id, timeout_seconds)
        return await run_in_threadpool(
            camera_injection_manager.start,
            device,
            png,
            qr_text,
            qr_data_base64,
            qr_version,
            timeout_seconds,
        )
    except CameraInjectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await image.close()


@router.delete("/{device_id}/camera-injection", response_model=CameraInjectionStatus)
def stop_injection(
    device_id: int,
    _: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    get_device_or_404(db, device_id)
    return camera_injection_manager.stop(device_id)
