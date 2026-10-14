"""What `/oauth2/token` issues for each grant type, once the client is known."""

from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.oauth.errors import InvalidClient, InvalidGrant
from provider.authz.oauth.schemas import TokenResponse
from provider.authz.oauth.service import consume_code
from provider.authz.services import token_service as tokens
from provider.authz.services.scope_resolver import (
    OFFLINE_ACCESS,
    format_scope,
    parse_scope,
    resolve_for_client,
    resolve_for_user,
)
from provider.entity.profile import service as profile_service
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, User


async def authorization_code(
    session: AsyncSession,
    client: Client,
    code: str,
    redirect_uri: str | None,
    code_verifier: str | None,
) -> TokenResponse:
    record = await consume_code(
        session,
        code=code,
        client=client,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    # Deactivating or deleting an account ends its sessions, but a code issued
    # a moment before still names it.
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        await session.commit()
        raise InvalidGrant("The user is no longer active.")
    scopes = parse_scope(record.scope)

    access_token, _, expires_in = await tokens.mint_access_token(
        session,
        subject=str(user.id),
        client=client,
        scopes=scopes,
        acr=record.acr,
        amr=record.amr,
        authenticated_at=record.authenticated_at,
    )

    # Two different things: `allowed_grants` is what this client is *configured*
    # to do, `offline_access` is what was asked for and consented to on this
    # request (OIDC Core Section 11). The first alone gave a refresh token to a
    # client that never asked.
    refresh = None
    if GrantType.REFRESH_TOKEN in client.allowed_grants and OFFLINE_ACCESS in scopes:
        refresh, _ = await tokens.issue_refresh_token(
            session,
            client=client,
            user=user,
            scope=record.scope,
            acr=record.acr,
            amr=record.amr,
            authenticated_at=record.authenticated_at,
            sid=record.sid,
        )

    id_token = None
    if "openid" in scopes:
        id_token = tokens.mint_id_token(
            user,
            client,
            scopes=scopes,
            acr=record.acr,
            amr=record.amr,
            authenticated_at=record.authenticated_at,
            sid=record.sid,
            nonce=record.nonce,
            extra_claims=await profile_service.claims_for(session, user, scopes),
        )

    await session.commit()
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        scope=record.scope,
        refresh_token=refresh,
        id_token=id_token,
    )


async def refresh_token(
    session: AsyncSession,
    redis: Redis,
    client: Client,
    token: str,
    requested_scope: str | None,
) -> TokenResponse:
    async with tokens.rotation_lock(redis, token):
        return await _rotate(session, redis, client, token, requested_scope)


async def _rotate(
    session: AsyncSession,
    redis: Redis,
    client: Client,
    token: str,
    requested_scope: str | None,
) -> TokenResponse:
    # Before anything is spent. An entry exists only for a token already
    # exchanged, and only briefly, so two tabs refreshing at once both get the
    # answer the first exchange produced.
    replay = await tokens.replayed_rotation(redis, token, client_id=client.client_id)
    if replay is not None:
        return TokenResponse(**replay)

    try:
        record = await tokens.consume_refresh_token(session, token)
    except tokens.RefreshTokenReuse as exc:
        await session.commit()
        raise InvalidGrant(
            "Refresh token reuse detected; the token family has been revoked."
        ) from exc

    if record is None:
        raise InvalidGrant("Unknown or expired refresh token.")

    if record.client_id != client.id:
        raise InvalidGrant("This refresh token was issued to a different client.")

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        await tokens.revoke_family(session, record.family_id)
        await session.commit()
        raise InvalidGrant("The user is no longer active.")

    # `record.scope` is the original grant and stays so across every rotation. A
    # `scope` parameter narrows this one response without shrinking the grant,
    # so a client that once asked for less can still get the rest back.
    granted_scope = parse_scope(record.scope)
    requested = (
        parse_scope(requested_scope) & granted_scope
        if requested_scope
        else granted_scope
    )

    # Re-resolved rather than replayed: this is where a revoked role or a
    # narrowed client actually takes effect.
    granted = resolve_for_user(requested, client, user)

    new_token, new_record = await tokens.issue_refresh_token(
        session,
        client=client,
        user=user,
        scope=format_scope(granted_scope),
        acr=record.acr,
        amr=record.amr,
        authenticated_at=record.authenticated_at,
        sid=record.sid,
        family_id=record.family_id,
    )
    record.rotated_to_id = new_record.id
    record.revoked_at = tokens.now()

    access_token, _, expires_in = await tokens.mint_access_token(
        session,
        subject=str(user.id),
        client=client,
        scopes=granted,
        acr=record.acr,
        amr=record.amr,
        authenticated_at=record.authenticated_at,
    )
    access_expires_at = tokens.now() + timedelta(seconds=expires_in)

    id_token = None
    if "openid" in granted:
        id_token = tokens.mint_id_token(
            user,
            client,
            scopes=granted,
            acr=record.acr,
            amr=record.amr,
            authenticated_at=record.authenticated_at,
            sid=record.sid,
            extra_claims=await profile_service.claims_for(session, user, granted),
        )

    await session.commit()

    response = TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        scope=format_scope(granted),
        refresh_token=new_token,
        id_token=id_token,
    )
    await tokens.remember_rotation(
        redis,
        token,
        client_id=client.client_id,
        response=response.model_dump(),
        expires_at=access_expires_at,
    )
    return response


async def client_credentials(
    session: AsyncSession, client: Client, requested_scope: str | None
) -> TokenResponse:
    if client.client_type != ClientType.CONFIDENTIAL:
        raise InvalidClient("Only confidential clients may use client_credentials.")

    granted = resolve_for_client(parse_scope(requested_scope), client)

    # sub is the client itself: there is no person behind this token.
    access_token, _, expires_in = await tokens.mint_access_token(
        session, subject=client.client_id, client=client, scopes=granted
    )
    await session.commit()

    return TokenResponse(
        access_token=access_token, expires_in=expires_in, scope=format_scope(granted)
    )
