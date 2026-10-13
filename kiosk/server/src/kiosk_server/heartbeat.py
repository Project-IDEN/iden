"""Report in to IDEN every minute, and pick up this kiosk's settings."""

import asyncio

from kiosk_server.device import Device, NotPaired, Unreachable
from kiosk_server.logging import logger

# Until IDEN says otherwise, and while it cannot be reached.
RETRY_SECONDS = 15


async def run(device: Device, wake: asyncio.Event) -> None:
    """`wake` cuts a wait short — after pairing, the new settings are wanted now."""
    while True:
        wake.clear()
        delay = device.heartbeat_seconds
        try:
            await device.heartbeat()
        except NotPaired:
            pass
        except Unreachable:
            delay = RETRY_SECONDS
        except Exception:
            logger.exception("Heartbeat failed")
            delay = RETRY_SECONDS

        try:
            await asyncio.wait_for(wake.wait(), timeout=delay)
        except TimeoutError:
            pass
