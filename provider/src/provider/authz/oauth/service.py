"""Client authentication, redirect validation, and authorization codes."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.oauth.errors import InvalidClient, InvalidGrant
from provider.authz.services.pkce import verify_challenge
from provider.authz.services.token_service import now
from provider.core.config import settings
from provider.core.security import generate_token, hash_token, verify_secret_async
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import AuthorizationCode, Client, User


async def get_client(session: AsyncSession, client_id: str | None) -> Client | None:
    if not client_id:
        return None
    return await session.scalar(select(Client).where(Client.client_id == client_id))


def redirect_uri_registered(client: Client, redirect_uri: str | None) -> bool:
    """Exact string comparison — RFC 6749 Section 3.1.2.3.

    Not a prefix or hostname match: sub-path and query tricks on a permissive
    comparison are how authorization codes get exfiltrated.
    """
    return redirect_uri is not None and redirect_uri in client.redirect_uris


async def authenticate_endpoint_client(
    session: AsyncSession,
    client_id: str | None,
    client_secret: str | None,
    *,
    require_confidential: bool,
) -> Client:
    """Client authentication for the management endpoints (revoke, introspect).

    Unlike the token endpoint this checks no grant type — these endpoints are not
    a grant. `require_confidential` is the difference between the two callers:

    - **Introspection must have it.** RFC 7662 Section 2.1 requires the endpoint be
      protected, and a `client_id` alone is not a credential — it is public by
      definition. Without this, naming any public client returns the contents of
      any token presented.
    - **Revocation does not.** RFC 7009 Section 2.1 lets a public client revoke its own
      tokens, and the caller must already hold the token to revoke it, so there
      is nothing to learn. The caller-side check that the token belongs to this
      client is what keeps one client from revoking another's.
    """
    client = await get_client(session, client_id)
    if client is None:
        raise InvalidClient("Unknown client.")

    if client.client_type == ClientType.CONFIDENTIAL:
        if not client_secret or not await verify_secret_async(
            client.client_secret_hash, client_secret
        ):
            raise InvalidClient()
        return client

    if require_confidential:
        raise InvalidClient("This endpoint requires a confidential client.")

    if client_secret:
        raise InvalidClient("A public client must not present a secret.")

    return client


async def authenticate_client(
    session: AsyncSession, client_id: str | None, client_secret: str | None, grant: str
) -> Client:
    """Client authentication for the token endpoint — RFC 6749 Section 2.3."""
    client = await get_client(session, client_id)
    if client is None:
        raise InvalidClient("Unknown client.")

    if client.client_type == ClientType.CONFIDENTIAL:
        if not client_secret or not await verify_secret_async(
            client.client_secret_hash, client_secret
        ):
            raise InvalidClient()
    elif client_secret:
        raise InvalidClient("A public client must not present a secret.")

    if grant not in client.allowed_grants:
        raise InvalidClient(f"This client may not use the {grant} grant.")

    return client


async def issue_code(
    session: AsyncSession,
    *,
    client: Client,
    user: User,
    params: dict[str, str],
    scopes: set[str],
    acr: str,
    amr: list[str],
    sid: str,
    authenticated_at: datetime,
) -> str:
    code = generate_token()
    session.add(
        AuthorizationCode(
            code_hash=hash_token(code),
            client_id=client.id,
            user_id=user.id,
            redirect_uri=params["redirect_uri"],
            scope=" ".join(sorted(scopes)),
            code_challenge=params["code_challenge"],
            code_challenge_method=params["code_challenge_method"],
            nonce=params.get("nonce"),
            acr=acr,
            amr=amr,
            sid=sid,
            authenticated_at=authenticated_at,
            expires_at=now() + timedelta(seconds=settings.iden_auth_code_ttl),
        )
    )
    await session.flush()
    return code


async def consume_code(
    session: AsyncSession,
    *,
    code: str,
    client: Client,
    redirect_uri: str | None,
    code_verifier: str | None,
) -> AuthorizationCode:
    """Validate and burn an authorization code — RFC 6749 Section 4.1.3, RFC 7636 Section 4.6."""
    # Locked for the duration of the transaction: the check on `used_at` below
    # and the write that burns it must not interleave with another redemption,
    # or a stolen code could be spent twice (RFC 6749 Section 4.1.2).
    record = await session.scalar(
        select(AuthorizationCode)
        .where(AuthorizationCode.code_hash == hash_token(code))
        .with_for_update()
    )
    if record is None:
        raise InvalidGrant("Unknown authorization code.")

    if record.used_at is not None:
        # RFC 6749 Section 4.1.2: a code presented twice is assumed compromised.
        raise InvalidGrant("This authorization code has already been used.")

    if record.expires_at <= now():
        raise InvalidGrant("This authorization code has expired.")

    if record.client_id != client.id:
        raise InvalidGrant("This code was issued to a different client.")

    if record.redirect_uri != redirect_uri:
        raise InvalidGrant("redirect_uri does not match the authorization request.")

    if not code_verifier or not verify_challenge(
        code_verifier, record.code_challenge, record.code_challenge_method
    ):
        raise InvalidGrant("PKCE verification failed.")

    record.used_at = now()
    await session.flush()
    return record


def grant_allowed(client: Client, grant: GrantType) -> bool:
    return grant in client.allowed_grants
