"""This kiosk, as IDEN knows it: its credentials, its settings, and the calls it
makes.

The UI never sees the client secret. It asks this process, which signs in as the
kiosk with `client_credentials` and keeps the token until shortly before it
expires.
"""

import time
from typing import Any

import httpx

from kiosk_server import credentials
from kiosk_server.config import settings
from kiosk_server.logging import logger
from kiosk_server.schemas import Credentials, KioskState

SCOPE = "biometric:enroll biometric:device"
# Fetch a new token this long before the current one expires, so a request
# never sets out with a token that lapses on the way.
TOKEN_MARGIN_SECONDS = 30


class NotPaired(Exception):
    """No credentials, or IDEN no longer accepts them."""


class Unreachable(Exception):
    """IDEN did not answer."""


class Device:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self.credentials = credentials.load()
        self.config: dict[str, Any] = {}
        self.camera: str | None = None
        self.online = False
        self._token: str | None = None
        self._token_expires = 0.0

    def state(self) -> KioskState:
        return KioskState(
            paired=self.credentials is not None,
            name=self.config.get("name")
            or (self.credentials.name if self.credentials else None),
            location=self.config.get("location"),
            settings=self.config.get("settings", {}),
            online=self.online,
            version=settings.kiosk_version,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            self.online = False
            raise Unreachable from exc
        self.online = True
        return response

    async def pair(self, code: str) -> httpx.Response:
        """Trades a pairing code for this kiosk's secret. Any previous pairing
        is replaced only once the new one has succeeded."""
        response = await self._request(
            "POST", "/biometric/kiosk/pair", json={"code": code}
        )
        if response.status_code == 200:
            self.credentials = Credentials.model_validate(response.json())
            credentials.save(self.credentials)
            self.config = {}
            self._token = None
            logger.info("Paired", client_id=self.credentials.client_id)
        return response

    def _forget(self) -> None:
        logger.warning("IDEN refused this kiosk's credentials; it must be paired again")
        credentials.forget()
        self.credentials = None
        self.config = {}
        self._token = None

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        if self.credentials is None:
            raise NotPaired

        response = await self._request(
            "POST",
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "scope": SCOPE,
            },
        )
        if response.status_code in (400, 401):
            # The kiosk was revoked, or paired again on another device.
            self._forget()
            raise NotPaired
        response.raise_for_status()
        body = response.json()
        self._token = body["access_token"]
        self._token_expires = (
            time.monotonic() + body["expires_in"] - TOKEN_MARGIN_SECONDS
        )
        return body["access_token"]

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A request as this kiosk. A 401 is retried once with a fresh token, in
        case the cached one was revoked; a second 401 means the kiosk was."""
        for attempt in range(2):
            token = await self._access_token()
            response = await self._request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
            if response.status_code != 401:
                return response
            self._token = None
            if attempt == 1:
                self._forget()
        raise NotPaired

    async def heartbeat(self) -> None:
        response = await self.call(
            "POST",
            "/biometric/kiosk/heartbeat",
            json={"softwareVersion": settings.kiosk_version, "camera": self.camera},
        )
        if response.status_code == 200:
            self.config = response.json()

    @property
    def heartbeat_seconds(self) -> int:
        return self.config.get("heartbeatSeconds", 60)
