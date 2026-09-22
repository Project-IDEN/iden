"""A ceiling on how large a request body the provider will read.

The application had none. FastAPI reads a JSON body into memory in full before
Pydantic sees it, and a multipart upload is spooled to a temporary file while it
is parsed — so `POST /api/v1/auth/login` with a gigabyte of JSON is a gigabyte of
memory, from a caller holding no credential, and a photo upload is however much
disk the attacker feels like sending. `IDEN_AVATAR_MAX_BYTES` does not help: it
is checked after the body has already been received.

`deploy/nginx` sets `client_max_body_size`, which is the right place for the
general case and stops this before Python is involved. This exists because it is
the only limit that is still there when the proxy is missing, misconfigured, or
bypassed — and a provider reachable directly is exactly the case the deployment
checklist warns about.

Pure ASGI: the body has to be measured as it streams, which a
`BaseHTTPMiddleware` function cannot do without consuming the stream the endpoint
is about to read.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from provider.core.config import settings

# Enough for any JSON this API accepts — the largest is a client registration
# with twenty redirect URIs — and small enough that a body of this size costs
# nothing to hold.
MAX_BODY_BYTES = 64 * 1024

# The one endpoint that takes a file. Its own limit is `IDEN_AVATAR_MAX_BYTES`,
# applied to the decoded upload; this is the envelope, with room for the
# multipart framing around it.
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
                # The connection is closed rather than drained: the rest of the
                # body is exactly what this refuses to read.
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
                    # place it can be caught. The endpoint is handed the end of
                    # the body and will fail to parse what it has; whatever it
                    # answers is discarded below in favour of the 413.
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        answered = False
        refused = False

        async def send_filtered(message: Message) -> None:
            nonlocal answered, refused
            # Nothing has gone out yet and the body was over the limit: answer
            # 413 rather than the endpoint's complaint about a body it was handed
            # in truncated form, and drop everything it goes on to produce.
            #
            # `answered` is what makes the other order safe. A response already
            # on the wire cannot be retracted, so if the endpoint had started
            # replying before the limit was reached, its response is finished
            # rather than interrupted.
            if exceeded and not answered:
                if not refused:
                    refused = True
                    await _too_large(send, limit)
                return
            answered = True
            await send(message)

        await self.app(scope, receive_counting, send_filtered)
