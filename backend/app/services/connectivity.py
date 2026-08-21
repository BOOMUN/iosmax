from __future__ import annotations

import asyncio
import time

from ..schemas import PortStatus


async def probe_port(host: str, port: int, timeout: float = 2.5) -> PortStatus:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        latency = round((time.perf_counter() - started) * 1000)
        writer.close()
        await writer.wait_closed()
        return PortStatus(port=port, reachable=True, latency_ms=latency)
    except Exception as exc:
        return PortStatus(port=port, reachable=False, error=type(exc).__name__)

