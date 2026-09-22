"""A ceiling on how large a request body the provider will read.

FastAPI reads a JSON body into memory in full before Pydantic sees it, and a
multipart upload is spooled to disk while it is parsed — both reachable without a
credential. `IDEN_AVATAR_MAX_BYTES` does not help: it is checked once the body
has arrived.

`deploy/nginx` refuses these earlier and more cheaply. This is the limit that
survives the proxy being absent or bypassed.

Pure ASGI because the body must be measured as it streams, which a
`BaseHTTPMiddleware` cannot do without consuming it.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from provider.core.config import settings

# Ample for any JSON this API accepts; the largest is a client registration with
# twenty redirect URIs.
MAX_BODY_BYTES = 64 * 1024

# Room for the multipart framing around a photo, whose own limit is
# IDEN_AVATAR_MAX_BYTES applied to the decoded upload.
MULTIPART_HEADROOM = 64 * 1024


def _limit_for(path: str) -> int:
    if path.endswith("/entity/profile/photo"):
        return settings.iden_avatar_max_bytes + MULTIPART_HEADROOM
    return MAX_BODY_BYTES


async def _too_large(send: Send, limit: int) -> None:
    body = (
        b'{"code":"payload_too_large",'
        b'"message":"The request body is larger than this endpoint accepts.",'
        b'"details":{"maxBytes":' + str(limit).encode() + b"}}"
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # Closed rather than drained: the rest of the body is what
                # this refuses to read.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope["path"])

        declared = next(
            (
                value
                for key, value in scope.get("headers") or []
                if key == b"content-length"
            ),
            None,
        )
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(send, limit)
            return

        received = 0
        exceeded = False

        async def receive_counting() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # A chunked body declares no length, so this is the only
                    # place to catch it. Whatever the endpoint then answers is
                    # discarded below in favour of the 413.
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        answered = False
        refused = False

        async def send_filtered(message: Message) -> None:
            nonlocal answered, refused
            # `answered` guards the other order: a response already on the wire
            # cannot be retracted, so an endpoint that began replying before the
            # limit was reached finishes rather than being cut off.
            if exceeded and not answered:
                if not refused:
                    refused = True
                    await _too_large(send, limit)
                return
            answered = True
            await send(message)

        await self.app(scope, receive_counting, send_filtered)
