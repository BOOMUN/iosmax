from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .jailbreak import JailbreakType


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


class UserResponse(BaseModel):
    id: int
    username: str
    must_change_password: bool


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str = Field(default="root", min_length=1, max_length=80)
    vnc_port: int = Field(default=5901, ge=1, le=65535)
    frida_port: int = Field(default=27042, ge=1, le=65535)
    jailbreak_type: JailbreakType = JailbreakType.ROOTLESS
    enabled: bool = True
    notes: str = Field(default="", max_length=2000)

    @field_validator("host")
    @classmethod
    def clean_host(cls, value: str) -> str:
        value = value.strip()
        if "://" in value or "/" in value:
            raise ValueError("请输入 IP 地址或主机名，不要包含协议和路径")
        return value


class DeviceCreate(DeviceBase):
    ssh_password: str | None = Field(default=None, max_length=256)
    vnc_password: str | None = Field(default=None, max_length=256)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_username: str | None = Field(default=None, min_length=1, max_length=80)
    ssh_password: str | None = Field(default=None, max_length=256)
    clear_ssh_password: bool = False
    vnc_port: int | None = Field(default=None, ge=1, le=65535)
    vnc_password: str | None = Field(default=None, max_length=256)
    clear_vnc_password: bool = False
    frida_port: int | None = Field(default=None, ge=1, le=65535)
    jailbreak_type: JailbreakType | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("host")
    @classmethod
    def clean_host(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if "://" in value or "/" in value:
            raise ValueError("请输入 IP 地址或主机名，不要包含协议和路径")
        return value


class DeviceResponse(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    has_ssh_password: bool
    has_vnc_password: bool
    created_at: datetime
    updated_at: datetime


class PortStatus(BaseModel):
    port: int
    reachable: bool
    latency_ms: int | None = None
    error: str | None = None


class JailbreakProbe(BaseModel):
    configured: JailbreakType
    detected: JailbreakType | None = None
    matches: bool | None = None
    jbroot: str | None = None
    error: str | None = None
    package_version: str | None = None
    package_architecture: str | None = None
    package_filename: str | None = None


class DeviceProbeResponse(BaseModel):
    device_id: int
    checked_at: datetime
    ssh: PortStatus
    vnc: PortStatus
    frida: PortStatus
    jailbreak: JailbreakProbe


class SystemActionRequest(BaseModel):
    action: Literal["wake", "home"]


class SystemActionResponse(BaseModel):
    success: bool
    action: Literal["wake", "home"]
    message: str


class CameraMetadataEvent(BaseModel):
    stage: str
    message: str
    timestamp: datetime
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)


class CameraInjectionStatus(BaseModel):
    device_id: int
    status: str
    message: str
    started_at: datetime | None = None
    expires_at: datetime | None = None
    delegate_class: str | None = None
    frames_replaced: int = 0
    app_version: str | None = None
    metadata_stage: str = "idle"
    metadata_output_found: bool | None = None
    controller_class: str | None = None
    qr_parsed: bool | None = None
    qr_version: int | None = None
    qr_data_length: int = 0
    qr_dispatched: bool = False
    qr_accepted: bool = False
    metadata_events: list[CameraMetadataEvent] = Field(default_factory=list)
