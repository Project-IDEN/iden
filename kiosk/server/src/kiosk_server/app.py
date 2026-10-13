import asyncio
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from kiosk_server import heartbeat
from kiosk_server.config import settings
from kiosk_server.device import Device
from kiosk_server.logging import configure_logging, logger
from kiosk_server.routes import router

configure_logging()


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`transport` lets the tests stand in for IDEN."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            base_url=settings.kiosk_issuer,
            timeout=settings.kiosk_timeout,
            transport=transport,
        ) as http:
            app.state.device = Device(http)
            app.state.wake = asyncio.Event()
            task = asyncio.create_task(heartbeat.run(app.state.device, app.state.wake))
            logger.info(
                "Kiosk starting",
                issuer=settings.kiosk_issuer,
                paired=app.state.device.credentials is not None,
            )
            yield
            task.cancel()

    app = FastAPI(title="IDEN Kiosk", version=settings.kiosk_version, lifespan=lifespan)
    # Only the browser on this device. A page elsewhere that resolves a name to
    # 127.0.0.1 (DNS rebinding) still sends its own name as the Host.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.include_router(router)
    if settings.kiosk_ui_dir is not None:
        app.mount(
            "/", StaticFiles(directory=settings.kiosk_ui_dir, html=True), name="ui"
        )
    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "kiosk_server.app:app",
        host="127.0.0.1",
        port=8080,
        log_config=None,
        reload=settings.kiosk_env == "dev",
    )
