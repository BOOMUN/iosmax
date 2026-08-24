from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .api.auth import router as auth_router
from .api.camera import router as camera_router
from .api.devices import router as devices_router
from .config import settings
from .database import SessionLocal, create_tables
from .models import Device
from .security import COOKIE_NAME, seed_admin, user_from_session
from .services.camera_injection import camera_injection_manager
from .services.virtual_camera import disable_virtual_camera
from .services.wireless_tunnel import wireless_tunnel_manager


def disable_orphaned_virtual_camera(device: Device, reason: str) -> None:
    try:
        camera_injection_manager.stop(device.id, reason)
        disable_virtual_camera(device)
    except Exception:
        # A disconnected or mismatched device must not prevent the control
        # service from starting or stopping other managed devices.
        pass


async def recover_managed_virtual_cameras(reason: str) -> None:
    with SessionLocal() as db:
        devices = [
            device
            for device in db.query(Device).all()
            if device.enabled and device.ssh_password_encrypted
        ]
    await asyncio.gather(
        *(asyncio.to_thread(disable_orphaned_virtual_camera, device, reason)
          for device in devices)
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    with SessionLocal() as db:
        seed_admin(db)
    wireless_tunnel_manager.start()
    await asyncio.to_thread(wireless_tunnel_manager.wait_ready, 12)
    await recover_managed_virtual_cameras("后台启动时清理遗留注入")
    try:
        yield
    finally:
        await recover_managed_virtual_cameras("后台关闭时停止注入")
        wireless_tunnel_manager.stop()


app = FastAPI(
    title="iOSMax Control",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.include_router(auth_router)
app.include_router(devices_router)
app.include_router(camera_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


async def browser_to_device(websocket: WebSocket, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None and message.get("text") is not None:
                data = message["text"].encode()
            if data:
                writer.write(data)
                await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def device_to_browser(websocket: WebSocket, reader: asyncio.StreamReader) -> None:
    while data := await reader.read(65536):
        await websocket.send_bytes(data)


@app.websocket("/ws/vnc/{device_id}")
async def vnc_bridge(websocket: WebSocket, device_id: int):
    token = websocket.cookies.get(COOKIE_NAME)
    with SessionLocal() as db:
        user = user_from_session(db, token)
        device = db.get(Device, device_id)
        if user is None or device is None or not device.enabled:
            await websocket.close(code=4401 if user is None else 4404)
            return
        host, port = device.host, device.vnc_port

    protocols = websocket.headers.get("sec-websocket-protocol", "")
    subprotocol = "binary" if "binary" in protocols.split(", ") else None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 8)
    except Exception:
        await websocket.close(code=1013)
        return

    await websocket.accept(subprotocol=subprotocol)
    upstream = asyncio.create_task(browser_to_device(websocket, writer))
    downstream = asyncio.create_task(device_to_browser(websocket, reader))
    done, pending = await asyncio.wait(
        {upstream, downstream}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        try:
            task.result()
        except (WebSocketDisconnect, ConnectionError, asyncio.CancelledError):
            pass
        except RuntimeError:
            pass
    if websocket.client_state.name == "CONNECTED":
        await websocket.close()


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
