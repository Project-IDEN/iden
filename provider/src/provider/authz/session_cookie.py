"""The session cookie contract, in one place so every route sets it identically."""

from fastapi import Response

from provider.core.config import settings

NAME = "iden_session"


def set_session(response: Response, session_id: str) -> None:
    response.set_cookie(
        NAME,
        session_id,
        max_age=settings.iden_session_ttl,
        httponly=True,
        # Lax rather than Strict: the browser arrives at /authorize by top-level
        # navigation from the client application, and Strict would withhold the
        # cookie on exactly that hop.
        samesite="lax",
        secure=settings.iden_env == "prod",
        path="/",
    )


def clear_session(response: Response) -> None:
    # The same attributes it was set with. A browser keys a cookie on name,
    # domain and path, so the deletion lands either way — but a `Set-Cookie`
    # that drops `Secure` on an otherwise HTTPS-only cookie is the kind of
    # difference a proxy or a future browser rule can decide to treat as two
    # cookies, and there is nothing to gain from the two lines disagreeing.
    response.delete_cookie(
        NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.iden_env == "prod",
    )
