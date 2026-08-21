from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import frida
from PIL import Image, ImageOps, UnidentifiedImageError

from ..jailbreak import JailbreakType, normalize_jailbreak_type
from ..models import Device
from ..schemas import CameraInjectionStatus, CameraMetadataEvent
from .virtual_camera import (
    VirtualCameraError,
    VirtualCameraLocation,
    disable_virtual_camera,
    enable_virtual_camera,
    read_virtual_camera_status,
)
from .ssh import execute


WHATSAPP_BUNDLE_ID = "net.whatsapp.WhatsApp"
WHATSAPP_EXECUTABLE_SUFFIX = "/WhatsApp.app/WhatsApp"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
DEMO_STEP_SECONDS = 0.7


def delegate_priority(class_name: str | None) -> int:
    if not class_name:
        return -1
    if class_name == "WACameraController":
        return 100
    if class_name.startswith("WA"):
        return 80
    if class_name.startswith("META"):
        return 60
    if class_name.startswith("FB"):
        return 40
    return 0


class CameraInjectionError(RuntimeError):
    pass


def jailbreak_label(device: Device) -> str:
    resolved = normalize_jailbreak_type(device.jailbreak_type)
    return "RootHide" if resolved is JailbreakType.ROOTHIDE else "Rootless"


def _parse_whatsapp_pid(processes: str) -> int | None:
    for line in processes.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[1].endswith(WHATSAPP_EXECUTABLE_SUFFIX):
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        if pid > 0:
            return pid
    return None


def _resolve_whatsapp_process(device: Device) -> tuple[int, str | None]:
    try:
        remote = frida.get_device_manager().add_remote_device(
            f"{device.host}:{device.frida_port}"
        )
        apps = remote.enumerate_applications()
        app = next((item for item in apps if item.identifier == WHATSAPP_BUNDLE_ID), None)
        if app is not None and app.pid:
            parameters = getattr(app, "parameters", {}) or {}
            version = parameters.get("version") or parameters.get("shortVersion")
            return int(app.pid), version
    except Exception:
        # Virtual-camera deployments do not require Frida. SSH is already
        # needed to upload frame/control files, so use it to resolve the PID.
        pass

    result = execute(
        device,
        "PATH=/var/jb/usr/bin:/var/jb/usr/sbin:/var/jb/bin:/var/jb/sbin:"
        "/usr/bin:/bin:/usr/sbin:/sbin; ps -axo pid=,comm=",
    )
    if result.exit_status == 0:
        pid = _parse_whatsapp_pid(result.stdout)
        if pid is not None:
            return pid, None
    raise CameraInjectionError(
        "请先打开 WhatsApp 并进入‘设置 → 关联设备 → 关联设备’扫码页"
    )


def prepare_qr_png(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise CameraInjectionError("PNG 文件不能为空且不能超过 8 MB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != "PNG":
                raise CameraInjectionError("只支持 PNG 图片")
            source.load()
            if min(source.size) < 64 or max(source.size) > MAX_IMAGE_SIDE:
                raise CameraInjectionError("二维码尺寸必须在 64 到 4096 像素之间")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise CameraInjectionError("无法读取 PNG 图片") from exc

    # Preserve a quiet zone even when the browser crop is tight.
    side = max(image.size)
    padding = max(16, round(side * 0.08))
    canvas = Image.new("RGB", (side + padding * 2, side + padding * 2), "white")
    canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
    if canvas.width > 1400:
        canvas.thumbnail((1400, 1400), Image.Resampling.NEAREST)

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=False)
    return output.getvalue()


@dataclass
class InjectionJob:
    device_id: int
    status: str = "connecting"
    message: str = "正在连接 Frida"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    delegate_class: str | None = None
    frames_replaced: int = 0
    app_version: str | None = None
    qr_dispatched: bool = False
    qr_parsed: bool | None = None
    qr_data_length: int = 0
    qr_version: int | None = None
    qr_accepted: bool = False
    metadata_stage: str = "connecting"
    metadata_output_found: bool | None = None
    controller_class: str | None = None
    metadata_events: list[CameraMetadataEvent] = field(default_factory=list)
    session: Any = field(default=None, repr=False)
    script: Any = field(default=None, repr=False)
    timer: threading.Timer | None = field(default=None, repr=False)
    poll_timer: threading.Timer | None = field(default=None, repr=False)
    virtual_device: Device | None = field(default=None, repr=False)
    virtual_location: VirtualCameraLocation | None = field(default=None, repr=False)
    virtual_frame_baseline: int = field(default=0, repr=False)

    def response(self) -> CameraInjectionStatus:
        return CameraInjectionStatus(
            device_id=self.device_id,
            status=self.status,
            message=self.message,
            started_at=self.started_at,
            expires_at=self.expires_at,
            delegate_class=self.delegate_class,
            frames_replaced=self.frames_replaced,
            app_version=self.app_version,
            metadata_stage=self.metadata_stage,
            metadata_output_found=self.metadata_output_found,
            controller_class=self.controller_class,
            qr_parsed=self.qr_parsed,
            qr_version=self.qr_version,
            qr_data_length=self.qr_data_length,
            qr_dispatched=self.qr_dispatched,
            qr_accepted=self.qr_accepted,
            metadata_events=self.metadata_events,
        )


class CameraInjectionManager:
    def __init__(self) -> None:
        self._jobs: dict[int, InjectionJob] = {}
        self._lock = threading.RLock()
        self._agent_source = (
            Path(__file__).resolve().parents[1] / "frida_scripts" / "whatsapp_camera.js"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _record_event(
        job: InjectionJob,
        stage: str,
        message: str,
        **details: str | int | bool | None,
    ) -> None:
        job.metadata_stage = stage
        job.metadata_events.append(
            CameraMetadataEvent(
                stage=stage,
                message=message,
                timestamp=datetime.now(timezone.utc),
                details=details,
            )
        )
        del job.metadata_events[:-20]

    def get(self, device_id: int) -> CameraInjectionStatus:
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None:
                return CameraInjectionStatus(
                    device_id=device_id,
                    status="idle",
                    message="未启动",
                )
            return job.response()

    def start(
        self,
        device: Device,
        png: bytes,
        qr_text: str,
        qr_data_base64: str,
        qr_version: int,
        timeout_seconds: int = 30,
    ) -> CameraInjectionStatus:
        self.stop(device.id, "已被新任务替换")
        job = InjectionJob(device_id=device.id)
        job.expires_at = job.started_at + timedelta(seconds=timeout_seconds)
        job.qr_parsed = True
        job.qr_version = qr_version
        job.qr_data_length = max(0, len(qr_data_base64) * 3 // 4)
        job.delegate_class = "IOSMaxVirtualCamera"
        job.virtual_device = device
        variant_label = jailbreak_label(device)
        self._record_event(job, "connecting", f"正在连接 {variant_label} 虚拟相机")
        with self._lock:
            self._jobs[device.id] = job

        try:
            whatsapp_pid, job.app_version = _resolve_whatsapp_process(device)

            location, probe = read_virtual_camera_status(device)
            if not probe.get("HookInstalled"):
                raise CameraInjectionError(
                    f"{variant_label} 虚拟相机尚未加载，请重启相机服务后重试"
                )
            job.virtual_frame_baseline = int(probe.get("FramesReplaced", 0))
            job.virtual_location = enable_virtual_camera(device, png, whatsapp_pid)
            job.status = "injecting"
            job.message = f"二维码已送入 {variant_label} 相机源，正在替换扫码帧"
            job.metadata_stage = "camera-source"
            self._record_event(
                job,
                "camera-source",
                f"已启用 {variant_label} 相机源替换",
                hook_installed=True,
                qr_version=qr_version,
            )

            timer = threading.Timer(timeout_seconds, lambda: self._timeout(device.id))
            timer.daemon = True
            job.timer = timer
            timer.start()
            self._schedule_virtual_poll(device.id)
            return job.response()
        except Exception as exc:
            self._release(job)
            job.status = "failed"
            job.message = str(exc)
            if isinstance(exc, (CameraInjectionError, VirtualCameraError)):
                raise CameraInjectionError(str(exc)) from exc
            raise CameraInjectionError(f"{variant_label} 虚拟相机启动失败：{exc}") from exc

    def _schedule_virtual_poll(self, device_id: int) -> None:
        timer = threading.Timer(1.0, lambda: self._poll_virtual_camera(device_id))
        timer.daemon = True
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None or job.virtual_device is None or job.expires_at is None:
                return
            if job.poll_timer:
                job.poll_timer.cancel()
            job.poll_timer = timer
        timer.start()

    def _poll_virtual_camera(self, device_id: int) -> None:
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None or job.virtual_device is None:
                return
            device = job.virtual_device
            location = job.virtual_location

        try:
            resolved, status = read_virtual_camera_status(device, location)
        except Exception as exc:
            with self._lock:
                current = self._jobs.get(device_id)
                if current is job and current.expires_at is not None:
                    current.message = f"等待虚拟相机状态：{exc}"
            self._schedule_virtual_poll(device_id)
            return

        event = str(status.get("Event", "unknown"))
        if event == "fail-open" or status.get("LastError"):
            reason = str(status.get("LastError") or "虚拟相机已自动进入安全关闭状态")
            self.stop(device_id, reason, final_status="failed")
            return

        with self._lock:
            current = self._jobs.get(device_id)
            if current is not job or current.expires_at is None:
                return
            current.virtual_location = resolved
            total = int(status.get("FramesReplaced", 0))
            current.frames_replaced = max(0, total - current.virtual_frame_baseline)
            if status.get("Enabled") and current.frames_replaced > 0:
                current.status = "injecting"
                current.message = (
                    f"{jailbreak_label(device)} 相机源正在输出二维码"
                    f"（已替换 {current.frames_replaced} 帧）"
                )
                current.metadata_stage = "camera-source-active"
        self._schedule_virtual_poll(device_id)

    def _start_frida(
        self,
        device: Device,
        png: bytes,
        qr_text: str,
        qr_data_base64: str,
        qr_version: int,
        timeout_seconds: int = 30,
    ) -> CameraInjectionStatus:
        self.stop(device.id, "已被新任务替换")
        job = InjectionJob(device_id=device.id)
        self._record_event(job, "connecting", "开始连接 Frida")
        job.expires_at = job.started_at + timedelta(seconds=timeout_seconds)
        with self._lock:
            self._jobs[device.id] = job

        try:
            remote = frida.get_device_manager().add_remote_device(
                f"{device.host}:{device.frida_port}"
            )
            apps = remote.enumerate_applications()
            app = next((item for item in apps if item.identifier == WHATSAPP_BUNDLE_ID), None)
            if app is None:
                raise CameraInjectionError("未检测到手机端 WhatsApp")
            if not app.pid:
                raise CameraInjectionError("请先打开手机端 WhatsApp，再启动二维码注入")

            parameters = getattr(app, "parameters", {}) or {}
            job.app_version = parameters.get("version") or parameters.get("shortVersion")
            job.status = "attaching"
            job.message = "正在附加手机端 WhatsApp"
            self._record_event(job, "attaching", "已找到 WhatsApp，正在附加进程")
            job.session = remote.attach(app.pid)
            job.script = job.session.create_script(self._agent_source)
            job.script.on("message", lambda message, data: self._on_message(device.id, message))
            job.script.load()
            job.status = "waiting-camera"
            job.message = "正在构造二维码识别结果并等待 WhatsApp 扫码页面"
            self._record_event(job, "agent-loaded", "Metadata agent 已加载")
            job.script.post(
                {
                    "type": "set-qr",
                    "payload": {
                        "qrText": qr_text,
                        "qrDataBase64": qr_data_base64,
                        "qrVersion": qr_version,
                    },
                },
                data=png,
            )
            timer = threading.Timer(
                timeout_seconds,
                lambda: self._timeout(device.id),
            )
            timer.daemon = True
            job.timer = timer
            timer.start()
            return job.response()
        except Exception as exc:
            self._release(job)
            job.status = "failed"
            job.message = str(exc)
            if isinstance(exc, CameraInjectionError):
                raise
            raise CameraInjectionError(f"Frida 注入失败：{exc}") from exc

    def _timeout(self, device_id: int) -> None:
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None:
                return
            if job.qr_dispatched:
                reason = (
                    "二维码回调已提交，但 WhatsApp 未触发 didAcceptQRCode"
                    f"（解析={job.qr_parsed}，数据={job.qr_data_length} 字节）"
                )
            elif job.qr_parsed is not None:
                reason = "二维码对象已构造，但未找到关联设备扫码控制器"
            elif job.frames_replaced == 0:
                reason = "未检测到 WhatsApp 摄像头视频帧，请保持二维码扫描页面在前台"
            else:
                reason = f"已替换 {job.frames_replaced} 帧，但关联未在限定时间内完成"
            self._record_event(job, "timeout", reason)
        self.stop(device_id, reason, final_status="timeout")

    def start_demo(self, device_id: int, timeout_seconds: int = 30) -> CameraInjectionStatus:
        self.stop(device_id, "已被新任务替换")
        job = InjectionJob(
            device_id=device_id,
            message="本地演示：正在连接 Frida",
            app_version="本地演示",
        )
        job.expires_at = job.started_at + timedelta(seconds=timeout_seconds)
        with self._lock:
            self._jobs[device_id] = job
        self._schedule_demo_step(device_id, 0)
        return job.response()

    def _schedule_demo_step(self, device_id: int, step: int) -> None:
        steps = (
            ("attaching", "本地演示：正在附加 WhatsApp", None, 0),
            ("waiting-camera", "本地演示：二维码已载入，等待摄像头视频帧", "IOSMaxDemoCaptureDelegate", 0),
            ("injecting", "本地演示：已检测摄像头管线，正在替换画面", "IOSMaxDemoCaptureDelegate", 1),
            ("injecting", "本地演示：正在向 WhatsApp 摄像头注入二维码", "IOSMaxDemoCaptureDelegate", 30),
            ("stopped", "本地演示完成：界面反馈与帧替换状态正常", "IOSMaxDemoCaptureDelegate", 60),
        )

        def advance() -> None:
            with self._lock:
                job = self._jobs.get(device_id)
                if job is None or step >= len(steps):
                    return
                status, message, delegate, frames = steps[step]
                job.status = status
                job.message = message
                job.delegate_class = delegate
                job.frames_replaced = frames
                if status == "stopped":
                    job.expires_at = None
                    job.timer = None
                    return
                self._schedule_demo_step(device_id, step + 1)

        timer = threading.Timer(DEMO_STEP_SECONDS, advance)
        timer.daemon = True
        with self._lock:
            job = self._jobs.get(device_id)
            if job is not None:
                job.timer = timer
        timer.start()

    def stop(
        self,
        device_id: int,
        reason: str = "注入已停止",
        final_status: str = "stopped",
    ) -> CameraInjectionStatus:
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None:
                return CameraInjectionStatus(
                    device_id=device_id, status="idle", message="未启动"
                )
            self._release(job)
            job.status = final_status
            job.message = reason
            job.expires_at = None
            if (
                not job.qr_accepted
                and (not job.metadata_events or job.metadata_events[-1].message != reason)
            ):
                self._record_event(job, final_status, reason)
            return job.response()

    def _release(self, job: InjectionJob) -> None:
        if job.timer:
            job.timer.cancel()
            job.timer = None
        if job.poll_timer:
            job.poll_timer.cancel()
            job.poll_timer = None
        if job.virtual_device is not None:
            try:
                disable_virtual_camera(job.virtual_device, job.virtual_location)
            except Exception:
                pass
            job.virtual_device = None
            job.virtual_location = None
        if job.script:
            try:
                job.script.post({"type": "disable"})
                job.script.unload()
            except Exception:
                pass
            job.script = None
        if job.session:
            try:
                job.session.detach()
            except Exception:
                pass
            job.session = None

    def _on_message(self, device_id: int, message: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(device_id)
            if job is None:
                return
            if message.get("type") == "error":
                job.status = "failed"
                job.message = message.get("description", "Frida 脚本异常")
                self._record_event(job, "failed", job.message)
                return
            payload = message.get("payload")
            if not isinstance(payload, dict):
                return
            event = payload.get("type")
            if event == "hook-installed":
                class_name = payload.get("className")
                if delegate_priority(class_name) > delegate_priority(job.delegate_class):
                    job.delegate_class = class_name
                job.message = "已监听摄像头 delegate，等待视频帧"
            elif event == "camera-controller-captured":
                class_name = payload.get("className")
                job.controller_class = class_name
                job.message = f"已捕获实时相机控制器 {class_name}，等待扫码页"
                self._record_event(
                    job,
                    "controller-captured",
                    "已捕获 WhatsApp 实时相机控制器",
                    controller_class=class_name,
                )
            elif event == "video-controller-seen":
                class_name = payload.get("className")
                job.controller_class = class_name or job.controller_class
                job.message = f"检测到视频输入 controller：{class_name}"
                self._record_event(
                    job,
                    "controller-seen",
                    job.message,
                    controller_class=class_name,
                    output_class=payload.get("outputClass"),
                )
            elif event == "metadata-pipeline-captured":
                class_name = payload.get("controllerClass")
                job.controller_class = class_name or job.controller_class
                job.message = "已捕获 WhatsApp Metadata 相机控制器"
                self._record_event(
                    job,
                    "controller-captured",
                    job.message,
                    controller_class=job.controller_class,
                    output_class=payload.get("outputClass"),
                )
            elif event == "qr-ready":
                if payload.get("decoded"):
                    version = payload.get("symbolVersion", 0)
                    job.qr_parsed = bool(payload.get("parsed"))
                    job.qr_version = int(version)
                    job.qr_data_length = int(payload.get("dataLength", 0))
                    if payload.get("parsed"):
                        job.message = (
                            f"WhatsApp 已解析二维码（QR 版本 {version}，"
                            f"{job.qr_data_length} 字节），等待扫码控制器"
                        )
                    else:
                        job.message = f"二维码文本已就绪（QR 版本 {version}），使用兼容模式等待扫码控制器"
                    self._record_event(
                        job,
                        "qr-ready",
                        job.message,
                        parsed=job.qr_parsed,
                        qr_version=job.qr_version,
                        data_length=job.qr_data_length,
                    )
                    if job.script is not None:
                        job.script.post({"type": "enable"})
                else:
                    job.message = "二维码图片已载入，等待 WhatsApp 摄像头视频帧"
            elif event == "qr-dispatched":
                job.qr_dispatched = True
                job.status = "injecting"
                job.delegate_class = payload.get("delegateClass") or job.delegate_class
                job.message = "已将二维码识别结果提交给 WhatsApp 关联设备扫码器"
            elif event == "metadata-dispatched":
                job.qr_dispatched = True
                job.status = "injecting"
                job.delegate_class = payload.get("controllerClass") or job.delegate_class
                job.controller_class = payload.get("controllerClass") or job.controller_class
                job.metadata_output_found = bool(payload.get("outputFound"))
                output_state = "已定位" if payload.get("outputFound") else "未定位"
                job.message = f"已通过 WhatsApp Metadata 管线提交二维码（输出{output_state}）"
                self._record_event(
                    job,
                    "metadata-dispatched",
                    job.message,
                    output_found=job.metadata_output_found,
                    controller_class=job.controller_class,
                )
            elif event == "qr-will-accept":
                job.status = "injecting"
                job.message = "WhatsApp 正在校验关联二维码"
                self._record_event(job, "validating", job.message)
            elif event == "qr-accepted":
                job.status = "stopped"
                job.message = "WhatsApp 已接受关联二维码"
                job.qr_accepted = True
                self._record_event(job, "accepted", job.message)
                job.expires_at = None
                if job.timer:
                    job.timer.cancel()
                cleanup = threading.Timer(
                    1.0,
                    lambda: self.stop(device_id, "WhatsApp 已接受关联二维码"),
                )
                cleanup.daemon = True
                job.timer = cleanup
                cleanup.start()
            elif event == "pipeline-detected":
                job.status = "injecting"
                job.message = "已检测 AVCaptureVideoDataOutput，正在替换画面"
            elif event == "frame-replaced":
                job.status = "injecting"
                job.frames_replaced = int(payload.get("count", job.frames_replaced))
                if not job.qr_dispatched:
                    job.message = "正在向 WhatsApp 摄像头注入二维码"
            elif event == "agent-error":
                job.status = "failed"
                job.message = payload.get("message", "摄像头帧替换失败")
                self._record_event(job, "failed", job.message)


camera_injection_manager = CameraInjectionManager()
