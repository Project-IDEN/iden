import base64
import uuid
from datetime import timedelta
from typing import Annotated
from urllib.parse import unquote_plus, urlencode

import jwt
from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select

from provider.authz import session_cookie
from provider.authz.consent.service import consent_required
from provider.authz.deps import LoginSessionDep
from provider.authz.login.service import enrolled_methods
from provider.authz.logout import service as logout_service
from provider.authz.oauth.errors import (
    InvalidClient,
    InvalidGrant,
    OAuthError,
    RedirectableError,
)
from provider.authz.oauth.schemas import (
    IntrospectionResponse,
    OAuthErrorResponse,
    TokenResponse,
    UserInfoResponse,
)
from provider.authz.oauth.service import (
    authenticate_client,
    authenticate_endpoint_client,
    consume_code,
    get_client,
    issue_code,
    redirect_uri_registered,
)
from provider.authz.services import auth_methods, challenge_store, session_store
from provider.authz.services import token_service as tokens
from provider.authz.services.scope_resolver import (
    OFFLINE_ACCESS,
    format_scope,
    parse_scope,
    resolve_for_client,
    resolve_for_user,
)
from provider.core import ratelimit
from provider.core.config import settings
from provider.core.crypto import ACCESS_TOKEN_TYP, verify_jwt
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.security import hash_token
from provider.entity.profile import service as profile_service
from provider.shared.enums import (
    ClientType,
    CodeChallengeMethod,
    GrantType,
    Prompt,
)
from provider.shared.models import Client, RefreshToken, User

router = APIRouter(prefix="/oauth2", tags=["oauth2"])


# What `prompt=none` returns in place of each interaction it refused to start.
SILENT_ERRORS = {
    "/auth/login": "login_required",
    "/auth/consent": "consent_required",
}


def _stale(login_session: session_store.Session, max_age: int | None) -> bool:
    """Whether the login is older than the client is willing to accept.

    `max_age=0` therefore means *authenticate now*, which is the point of it.
    """
    if max_age is None:
        return False
    age = tokens.now() - login_session.authenticated_at
    return age.total_seconds() > max_age


async def _resumed(
    redis: Redis, challenge_id: str | None, params: dict[str, str]
) -> challenge_store.Challenge | None:
    """The challenge this request is returning from, if it is one.

    Only an exact match counts. A challenge vouches for the interactions done
    for *one* request; if any parameter differs this is a different request —
    another client, other scopes — and a consent given to the first must not
    carry over to it.
    """
    if not challenge_id:
        return None
    challenge = await challenge_store.get(redis, challenge_id)
    return challenge if challenge and challenge.params == params else None


def _id_token_claims(hint: str) -> dict | None:
    """The claims of an `id_token_hint`, or None if it is not one of ours.

    Expiry is allowed: ID tokens live ten minutes, so a hint about a past login
    is expected to be stale. A **logout token** is refused outright — it is
    signed by IDEN and carries `sub`, so without this check a client could
    replay the token that told it to sign out as evidence that someone is
    signed in. The `events` claim is exactly what distinguishes the two.
    """
    try:
        claims = verify_jwt(hint, allow_expired=True)
    except jwt.PyJWTError:
        return None
    return None if "events" in claims else claims


def _hint_mismatch(
    id_token_hint: str | None, login_session: session_store.Session
) -> bool:
    """Whether an `id_token_hint` names someone other than the session's owner.

    An unverifiable hint counts as a mismatch rather than as no hint at all: a
    client that asked about a specific person should not silently receive a
    code for a different one.
    """
    if not id_token_hint:
        return False
    claims = _id_token_claims(id_token_hint)
    return claims is None or claims.get("sub") != str(login_session.user_id)


def _hinted_client(id_token_hint: str | None) -> str | None:
    """The client an `id_token_hint` was issued to, from its `aud`.

    Only used to decide whether `post_logout_redirect_uri` is registered, so a
    hint IDEN did not sign is worth nothing and is discarded.
    """
    if not id_token_hint:
        return None
    claims = _id_token_claims(id_token_hint)
    if claims is None:
        return None
    audience = claims.get("aud")
    return audience if isinstance(audience, str) else None


def _auth_ui(path: str, challenge_id: str, **extra: str) -> RedirectResponse:
    query = urlencode({"challenge": challenge_id, **extra})
    return RedirectResponse(
        f"{settings.iden_auth_ui_base_url}{path}?{query}", status_code=303
    )


@router.get(
    "/authorize",
    summary="Start an authorization request",
    description=(
        "The entry point for the authorization code flow. **PKCE with `S256` is "
        "required of every client**, public or confidential — there is no "
        "non-PKCE path.\n\n"
        "Redirects to the hosted Auth UI when the browser has no session, when "
        "the session does not meet the requested `acr_values` or `max_age`, or "
        "when consent is needed. Otherwise issues a code and returns to "
        "`redirect_uri` — which is single sign-on: a second application reaching "
        "this endpoint with a live session gets a code without a prompt.\n\n"
        "An `acr_values` the person has no way to reach — a level that needs an "
        "authenticator they have not set up — returns "
        "`unmet_authentication_requirements` to `redirect_uri` rather than a "
        "sign-in page they could never get past.\n\n"
        "`prompt=none` never shows UI. When interaction would have been needed it "
        "returns `login_required`, `consent_required`, or "
        "`account_selection_required` to `redirect_uri` instead (OIDC Core "
        "Section 3.1.2.6) — this is how a browser application checks silently whether "
        "someone is still signed in.\n\n"
        "`client_id` and `redirect_uri` errors render as JSON rather than "
        "redirecting: before those two are validated the URI is unverified, and "
        "redirecting to it would make this an open redirector (RFC 6749 Section 3.1.2.3).\n\n"
        "**Required scope:** none — this is how tokens are obtained."
    ),
    responses={
        303: {
            "description": "Redirect to the Auth UI, or back to the client with a code"
        },
        400: {
            "model": OAuthErrorResponse,
            "description": "Unknown client or unregistered redirect_uri",
        },
    },
)
async def authorize(
    request: Request,
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
    client_id: Annotated[str, Query()],
    redirect_uri: Annotated[str, Query()],
    response_type: Annotated[str, Query()] = "code",
    scope: Annotated[str, Query()] = "",
    state: Annotated[str | None, Query()] = None,
    code_challenge: Annotated[str | None, Query()] = None,
    code_challenge_method: Annotated[str, Query()] = CodeChallengeMethod.S256,
    nonce: Annotated[str | None, Query()] = None,
    acr_values: Annotated[str | None, Query()] = None,
    prompt: Annotated[str | None, Query()] = None,
    max_age: Annotated[int | None, Query(ge=0)] = None,
    login_hint: Annotated[str | None, Query()] = None,
    id_token_hint: Annotated[str | None, Query()] = None,
    resume: Annotated[
        str | None,
        Query(
            description=(
                "Set by IDEN on the way back from the Auth UI, naming the "
                "challenge this request went through. Clients never send it."
            )
        ),
    ] = None,
) -> Response:
    client = await get_client(session, client_id)
    if client is None:
        raise OAuthError("invalid_client", "Unknown client.")

    if not redirect_uri_registered(client, redirect_uri):
        raise OAuthError(
            "invalid_request", "redirect_uri is not registered for this client."
        )

    # Past this point the redirect target is trusted, so errors go to the client.
    def fail(error: str, description: str) -> RedirectableError:
        return RedirectableError(error, description, redirect_uri, state)

    if response_type != "code":
        raise fail("unsupported_response_type", "Only response_type=code is supported.")

    if GrantType.AUTHORIZATION_CODE not in client.allowed_grants:
        raise fail(
            "unauthorized_client",
            "This client may not use the authorization code grant.",
        )

    if not code_challenge:
        raise fail(
            "invalid_request", "code_challenge is required — IDEN mandates PKCE."
        )

    if code_challenge_method != CodeChallengeMethod.S256:
        raise fail("invalid_request", "code_challenge_method must be S256.")

    prompts = set(prompt.split()) if prompt else set()
    if unknown := prompts - set(Prompt):
        raise fail(
            "invalid_request", f"Unsupported prompt: {' '.join(sorted(unknown))}"
        )
    if Prompt.NONE in prompts and len(prompts) > 1:
        raise fail(
            "invalid_request", "prompt=none cannot be combined with other values."
        )

    silent = Prompt.NONE in prompts
    params = dict(request.query_params)
    params.pop("resume", None)
    resumed = await _resumed(redis, resume, params)

    async def interact(
        path: str,
        user_id: uuid.UUID | None = None,
        methods: list[str] | None = None,
        **extra: str,
    ):
        """Hand the request to the Auth UI — unless the client forbade it.

        Under `prompt=none` this raises instead, and raises *before* creating a
        challenge: a challenge is the pending half of an interaction, and one
        left in Redis for an interaction that will never happen is both a leak
        and a lie about what took place.

        `methods` makes it a step-up: the browser is signed in and owes only
        one of those, so the page asks for that and not the password again.
        """
        if silent:
            raise fail(SILENT_ERRORS[path], "This request needs interaction.")
        # A returning request keeps its challenge. A new one would forget what
        # the first recorded — a login followed by consent would come back
        # with a challenge that never saw the login, and ask for it again.
        challenge = resumed or challenge_store.new(params)
        if user_id is not None:
            challenge.user_id = user_id
        challenge.methods = methods or []
        await challenge_store.save(redis, challenge)
        return _auth_ui(path, challenge.id, **extra)

    # A hint naming someone other than the person signed in is not an error --
    # it means this client is asking about a different account, so the session
    # in hand is not the one it wants (OIDC Core Section 3.1.3.1).
    if login_session is not None and _hint_mismatch(id_token_hint, login_session):
        login_session = None

    if login_session is None:
        return await interact("/auth/login")

    # Both demands below are met by a sign-in made for this request. Without
    # this, the resume URL — which carries the original `prompt` and `max_age`
    # — would demand the sign-in it had just been given, on every return.
    signed_in_for_this = (
        resumed is not None and login_session.authenticated_at >= resumed.created_at
    )

    # `prompt=login` and `select_account` force a fresh authentication. IDEN has
    # one account per session, so account selection is re-authentication; it is
    # accepted rather than refused so a conforming client is not broken by it.
    if not signed_in_for_this and prompts & {Prompt.LOGIN, Prompt.SELECT_ACCOUNT}:
        return await interact("/auth/login", step_up="1")

    if not signed_in_for_this and _stale(login_session, max_age):
        return await interact("/auth/login", login_session.user_id, step_up="1")

    user = await session.get(User, login_session.user_id)
    if user is None or not user.is_active:
        return await interact("/auth/login")

    # A level this person has no way to reach is refused here, before any form
    # is shown: asking for a code that cannot be enough — or that they have no
    # authenticator to produce — only leaves them stuck on the page. The error
    # is OIDC's own for this, and the client decides what to do instead.
    enrolled = await enrolled_methods(session, user.id)
    acr = auth_methods.derive_acr(login_session.amr)
    reachable = auth_methods.derive_acr(list(enrolled))
    if not auth_methods.meets(acr, acr_values) and not auth_methods.meets(
        reachable, acr_values
    ):
        raise fail(
            "unmet_authentication_requirements",
            f"This account has no sign-in method that reaches {acr_values}.",
        )

    # Enforced *here* rather than only in the login step machine because this
    # is the endpoint that issues the code: a session that skipped the code form
    # and came straight back to the resume URL would otherwise be handed one
    # anyway, which is the whole attack.
    if methods := auth_methods.outstanding(login_session.amr, enrolled, acr_values):
        return await interact("/auth/login", user.id, methods=methods)

    requested = parse_scope(scope)
    granted = resolve_for_user(requested, client, user)

    consented_for_this = resumed is not None and resumed.consented_by == user.id
    if (Prompt.CONSENT in prompts and not consented_for_this) or await consent_required(
        session, user, client, granted
    ):
        return await interact("/auth/consent", user.id)

    code = await issue_code(
        session,
        client=client,
        user=user,
        params={**params, "code_challenge_method": code_challenge_method},
        scopes=granted,
        acr=acr,
        amr=auth_methods.normalized_amr(login_session.amr),
        sid=login_session.public_id,
        authenticated_at=login_session.authenticated_at,
    )
    await session.commit()
    # Spent. A challenge left behind would let its resume URL be replayed for
    # ten minutes with everything it vouched for still vouched for.
    if resumed is not None:
        await challenge_store.delete(redis, resumed.id)
    # What makes single sign-out possible: this is the only record that the
    # session ever reached this client.
    await session_store.add_client(redis, login_session.id, client.client_id)

    # `iss` on every authorization response — RFC 9207. A client talking to more
    # than one provider cannot otherwise tell which one answered, which is the
    # opening for a mix-up attack: an attacker's provider returns a code the
    # client then redeems at the honest one.
    query = {"code": code, "iss": settings.iden_issuer}
    if state:
        query["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=303)


def _client_auth(request: Request, client_id: str | None, client_secret: str | None):
    """client_secret_basic takes precedence over client_secret_post — RFC 6749 Section 2.3.1."""
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")

    if scheme.lower() == "basic" and encoded:
        try:
            decoded = base64.b64decode(encoded).decode()
        except ValueError as exc:
            raise InvalidClient("Malformed Basic authorization header.") from exc
        name, _, secret = decoded.partition(":")
        # RFC 6749 Section 2.3.1 encodes both halves with `application/x-www-form-
        # urlencoded` *before* base64, so they have to be decoded after. IDEN's
        # own secrets are URL-safe and unaffected; an imported one containing a
        # reserved character failed as `invalid_client` with nothing to suggest
        # why.
        return unquote_plus(name), unquote_plus(secret)

    return client_id, client_secret


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Exchange a grant for tokens",
    description=(
        "Supports three grant types:\n\n"
        "- `authorization_code` — with `code_verifier`; returns access, ID, and refresh tokens\n"
        "- `refresh_token` — rotates the token and re-resolves permissions, so a "
        "revoked role takes effect here\n"
        "- `client_credentials` — confidential clients only; no user, so no ID or refresh token\n\n"
        "**Required scope:** none — client authentication only."
    ),
    responses={
        400: {
            "model": OAuthErrorResponse,
            "description": "invalid_grant or invalid_request",
        },
        401: {"model": OAuthErrorResponse, "description": "invalid_client"},
    },
    dependencies=[Depends(ratelimit.TOKEN_PER_IP)],
)
async def token(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
    grant_type: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    scope: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
) -> TokenResponse:
    name, secret = _client_auth(request, client_id, client_secret)
    client = await authenticate_client(session, name, secret, grant_type)

    match grant_type:
        case GrantType.AUTHORIZATION_CODE:
            if not code:
                raise OAuthError("invalid_request", "code is required.")
            return await _authorization_code_grant(
                session, client, code, redirect_uri, code_verifier
            )
        case GrantType.REFRESH_TOKEN:
            if not refresh_token:
                raise OAuthError("invalid_request", "refresh_token is required.")
            return await _refresh_token_grant(
                session, redis, client, refresh_token, scope
            )
        case GrantType.CLIENT_CREDENTIALS:
            return await _client_credentials_grant(session, client, scope)
        case _:
            raise OAuthError(
                "unsupported_grant_type", f"Unsupported grant_type: {grant_type}"
            )


async def _authorization_code_grant(
    session,
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
    user = await session.get(User, record.user_id)
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

    # Two conditions, and they say different things. `allowed_grants` is what
    # this client is *configured* to do; `offline_access` is what was asked for
    # and consented to on this request (OIDC Core Section 11). Issuing on the first
    # alone meant a client that never asked for offline access got it anyway,
    # and one that did ask was never told whether it had been granted.
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


async def _refresh_token_grant(
    session,
    redis,
    client: Client,
    refresh_token: str,
    requested_scope: str | None,
) -> TokenResponse:
    async with tokens.rotation_lock(redis, refresh_token):
        return await _rotate(session, redis, client, refresh_token, requested_scope)


async def _rotate(
    session,
    redis,
    client: Client,
    refresh_token: str,
    requested_scope: str | None,
) -> TokenResponse:
    # Asked before anything is spent: an entry exists only for a token that was
    # already exchanged, and only for a few seconds afterwards. Two tabs
    # refreshing at once, or one request retried after a timeout, both land
    # here and get the answer the first exchange produced.
    replay = await tokens.replayed_rotation(
        redis, refresh_token, client_id=client.client_id
    )
    if replay is not None:
        return TokenResponse(**replay)

    try:
        record = await tokens.consume_refresh_token(session, refresh_token)
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

    # `record.scope` is the *original* grant and stays that way across every
    # rotation. A `scope` parameter narrows this one response (RFC 6749 Section 6
    # forbids widening, and an intersection cannot widen) without shrinking the
    # grant itself — otherwise a client that once asked for less could never
    # get the rest back.
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
        refresh_token,
        client_id=client.client_id,
        response=response.model_dump(),
        expires_at=access_expires_at,
    )
    return response


async def _client_credentials_grant(
    session, client: Client, requested_scope: str | None
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


async def _verify_access_token(raw: str | None, redis) -> dict:
    """Verify a bearer token for IDEN's own OIDC endpoints.

    Audience is deliberately not checked here: an access token's `aud` names the
    resource APIs its scopes belong to, while /userinfo is IDEN describing the
    user to the client. Requiring `openid` is the real gate (OIDC Core Section 5.3).

    The **type** is checked, and that is what audience would otherwise have to
    stand in for. An ID token is signed by IDEN, names the same person, and has
    no `jti` — so before this it reached the `claims["jti"]` below and answered
    500 where 401 belongs (RFC 9068 Section 2.1).
    """
    if not raw:
        raise OAuthError(
            "invalid_token", "A bearer access token is required.", status_code=401
        )

    try:
        claims = verify_jwt(raw, typ=ACCESS_TOKEN_TYP)
    except jwt.PyJWTError as exc:
        raise OAuthError("invalid_token", str(exc), status_code=401) from exc

    if await tokens.is_denylisted(redis, claims["jti"]):
        raise OAuthError(
            "invalid_token", "This token has been revoked.", status_code=401
        )

    return claims


def _bearer_token(request: Request) -> str | None:
    """The credential from the Authorization header, if it is a Bearer one."""
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    return raw if scheme.lower() == "bearer" and raw else None


USERINFO_DOCS = {
    "response_model": UserInfoResponse,
    "response_model_exclude_none": True,
    "summary": "Claims about the signed-in user",
    "description": (
        "Returns the claims released by the granted scopes: `sub` always, plus "
        "`profile` and `email` claims when those scopes were granted.\n\n"
        "Available as both `GET` and `POST`, as OIDC Core Section 5.3.1 requires. The "
        "`POST` form accepts the token in the `access_token` form field as well "
        "as in the header (RFC 6750 Section 2.2), which is what conformance suites and "
        "several relying-party libraries send by default.\n\n"
        "**Required scope:** `openid`"
    ),
    "responses": {
        401: {
            "model": OAuthErrorResponse,
            "description": "Missing, invalid, or revoked token",
        },
        403: {
            "model": OAuthErrorResponse,
            "description": "The token does not carry `openid`",
        },
    },
}


async def _userinfo(raw: str | None, session, redis) -> UserInfoResponse:
    claims = await _verify_access_token(raw, redis)
    scopes = parse_scope(claims.get("scope"))

    if "openid" not in scopes:
        raise OAuthError(
            "insufficient_scope", "The openid scope is required.", status_code=403
        )

    user = await session.get(User, claims["sub"])
    if user is None:
        raise OAuthError(
            "invalid_token", "The subject no longer exists.", status_code=401
        )

    return UserInfoResponse(
        sub=str(user.id),
        **tokens.identity_claims(user, scopes),
        **await profile_service.claims_for(session, user, scopes),
    )


@router.get("/userinfo", **USERINFO_DOCS)
async def userinfo(
    request: Request, session: DBSessionDep, redis: RedisDep
) -> UserInfoResponse:
    return await _userinfo(_bearer_token(request), session, redis)


# A second handler rather than a second decorator: a route that declares a Form
# parameter parses a body on every method, and there is no body on the GET.
@router.post("/userinfo", **USERINFO_DOCS)
async def userinfo_post(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
    access_token: Annotated[str | None, Form()] = None,
) -> UserInfoResponse:
    # The header wins when both are present: it is the form RFC 6750 prefers,
    # and honouring the body over it would let a query-string token override a
    # properly presented one.
    return await _userinfo(_bearer_token(request) or access_token, session, redis)


@router.post(
    "/revoke",
    status_code=200,
    summary="Revoke a token",
    description=(
        "RFC 7009. A refresh token revokes its whole family; an access token is "
        "added to the `jti` denylist until it would have expired anyway.\n\n"
        "Always returns `200`, even for an unknown token — RFC 7009 Section 2.2 requires "
        "it, so that this endpoint cannot be used to probe which tokens exist.\n\n"
        "Public clients may revoke their **own** tokens (RFC 7009 Section 2.1); the "
        "caller must already hold the token, so there is nothing to learn.\n\n"
        "`tokenTypeHint` is honoured as an ordering hint (RFC 7009 Section 2.1): it "
        "decides which lookup runs first, never which ones are allowed, so a "
        "wrong hint costs a little time rather than the revocation.\n\n"
        "**Required scope:** none — client authentication only."
    ),
    responses={401: {"model": OAuthErrorResponse, "description": "invalid_client"}},
)
async def revoke(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
    token: Annotated[str, Form()],
    token_type_hint: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
) -> Response:
    name, secret = _client_auth(request, client_id, client_secret)
    client = await authenticate_endpoint_client(
        session, name, secret, require_confidential=False
    )

    async def as_refresh_token() -> bool:
        record = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
        if record is None or record.client_id != client.id:
            return False
        await tokens.revoke_family(session, record.family_id)
        await session.commit()
        return True

    async def as_access_token() -> bool:
        try:
            claims = verify_jwt(token, typ=ACCESS_TOKEN_TYP)
        except jwt.PyJWTError:
            return False
        if claims.get("client_id") != client.client_id:
            # Someone else's token. RFC 7009 Section 2.1 says answer 200 regardless, so
            # this reports "handled" without having revoked anything.
            return True
        await tokens.denylist_access_token(redis, claims["jti"], claims["exp"])
        return True

    # Both are always tried; the hint only says which to try first.
    attempts = (
        (as_access_token, as_refresh_token)
        if token_type_hint == "access_token"
        else (as_refresh_token, as_access_token)
    )
    for attempt in attempts:
        if await attempt():
            break

    return Response(status_code=200)


@router.post(
    "/introspect",
    response_model=IntrospectionResponse,
    response_model_exclude_none=True,
    summary="Inspect a token",
    description=(
        "RFC 7662. Present mainly for consumers that cannot validate a JWT "
        "locally — IDEN's own modules and any resource server with JWKS access "
        "should validate offline instead of calling this on every request.\n\n"
        "**Requires a confidential client.** The response describes someone "
        "else's token, so a `client_id` alone is not enough — it is public by "
        "definition (RFC 7662 Section 2.1).\n\n"
        "**A client may only introspect its own tokens.** Anything issued to "
        'another client answers `{"active": false}` — the same answer an '
        "expired or unknown token gets, so the endpoint reveals nothing about "
        "what exists (RFC 7662 Section 4).\n\n"
        "Both access tokens and refresh tokens are accepted; `tokenTypeHint` "
        "orders the lookups.\n\n"
        "**Required scope:** none — client authentication only."
    ),
    responses={401: {"model": OAuthErrorResponse, "description": "invalid_client"}},
)
async def introspect(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
    token: Annotated[str, Form()],
    token_type_hint: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
) -> IntrospectionResponse:
    name, secret = _client_auth(request, client_id, client_secret)
    client = await authenticate_endpoint_client(
        session, name, secret, require_confidential=True
    )

    async def as_access_token() -> IntrospectionResponse | None:
        try:
            claims = verify_jwt(token, typ=ACCESS_TOKEN_TYP)
        except jwt.PyJWTError:
            return None

        # Someone else's token is not this caller's business. Reported as
        # inactive rather than refused, so the answer is indistinguishable from
        # a token that never existed (RFC 7662 Section 4).
        if claims.get("client_id") != client.client_id:
            return IntrospectionResponse(active=False)

        if await tokens.is_denylisted(redis, claims["jti"]):
            return IntrospectionResponse(active=False)

        return IntrospectionResponse(
            active=True,
            scope=claims.get("scope"),
            client_id=claims.get("client_id"),
            sub=claims.get("sub"),
            aud=claims.get("aud"),
            exp=claims.get("exp"),
            iat=claims.get("iat"),
            jti=claims.get("jti"),
            token_type="Bearer",
        )

    async def as_refresh_token() -> IntrospectionResponse | None:
        record = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
        if record is None or record.client_id != client.id:
            return None
        if record.revoked_at is not None or record.expires_at <= tokens.now():
            return IntrospectionResponse(active=False)

        return IntrospectionResponse(
            active=True,
            scope=record.scope,
            client_id=client.client_id,
            sub=str(record.user_id),
            exp=int(record.expires_at.timestamp()),
            iat=int(record.created_at.timestamp()),
            token_type="refresh_token",
        )

    attempts = (
        (as_refresh_token, as_access_token)
        if token_type_hint == "refresh_token"
        else (as_access_token, as_refresh_token)
    )
    for attempt in attempts:
        if (answer := await attempt()) is not None:
            return answer

    return IntrospectionResponse(active=False)


LOGOUT_DOCS = {
    "summary": "End the session everywhere",
    "description": (
        "Single sign-out. Clears the browser session and its cookie, revokes the "
        "refresh tokens the session produced, and delivers a **logout token** to "
        "every client that registered a `backchannelLogoutUri` and was signed "
        "into during this session (OIDC Back-Channel Logout 1.0).\n\n"
        "Available as both `GET` and `POST`, as RP-Initiated Logout 1.0 Section 2 "
        "requires. Prefer `POST`: it keeps `id_token_hint` out of browser "
        "history and out of the `Referer` header of whatever comes next.\n\n"
        "Access tokens already issued stay valid until they expire — they are "
        "self-contained by design, and their ten-minute lifetime is the trade "
        "that buys offline validation. Refresh tokens do not, so nothing can be "
        "renewed after this.\n\n"
        "`idTokenHint` identifies the client for redirect validation. A request "
        "without a session cookie ends nothing: the hint says who was signed in, "
        "it is not a credential for ending someone else's session.\n\n"
        "**Required scope:** none."
    ),
    "responses": {303: {"description": "Redirect to post_logout_redirect_uri"}},
}


@router.get("/logout", **LOGOUT_DOCS)
async def logout(
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
    client_id: Annotated[str | None, Query()] = None,
    id_token_hint: Annotated[str | None, Query()] = None,
    post_logout_redirect_uri: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> Response:
    return await _logout(
        login_session,
        session,
        redis,
        client_id=client_id,
        id_token_hint=id_token_hint,
        post_logout_redirect_uri=post_logout_redirect_uri,
        state=state,
    )


# Separate handler for the same reason as /userinfo: a Form parameter would make
# the GET try to parse a body it does not have.
@router.post("/logout", **LOGOUT_DOCS)
async def logout_post(
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
    client_id: Annotated[str | None, Form()] = None,
    id_token_hint: Annotated[str | None, Form()] = None,
    post_logout_redirect_uri: Annotated[str | None, Form()] = None,
    state: Annotated[str | None, Form()] = None,
) -> Response:
    return await _logout(
        login_session,
        session,
        redis,
        client_id=client_id,
        id_token_hint=id_token_hint,
        post_logout_redirect_uri=post_logout_redirect_uri,
        state=state,
    )


async def _logout(
    login_session,
    session,
    redis,
    *,
    client_id: str | None,
    id_token_hint: str | None,
    post_logout_redirect_uri: str | None,
    state: str | None,
) -> Response:
    if login_session is not None:
        sid = login_session.public_id
        # Read before the delete: the record of which clients this session
        # reached lives with the session and goes when it does.
        client_ids = await session_store.clients_for(redis, login_session.id)

        await logout_service.revoke_session_tokens(session, sid)
        await logout_service.notify(
            session, client_ids=client_ids, subject=login_session.user_id, sid=sid
        )
        await session.commit()
        await session_store.delete(redis, login_session.id)

    client = await get_client(session, client_id or _hinted_client(id_token_hint))
    target = None
    if client and post_logout_redirect_uri in client.post_logout_redirect_uris:
        query = f"?{urlencode({'state': state})}" if state else ""
        target = f"{post_logout_redirect_uri}{query}"

    response = (
        RedirectResponse(target, status_code=303)
        if target
        else Response(status_code=204)
    )
    session_cookie.clear_session(response)
    return response
