from fastapi import APIRouter
from sqlalchemy import select

from provider.authz.discovery.schemas import JsonWebKeySet, OpenIDConfiguration
from provider.authz.services import auth_methods
from provider.authz.services.scope_resolver import OIDC_SCOPES
from provider.core.config import settings
from provider.core.crypto import jwks
from provider.core.db import DBSessionDep
from provider.shared.enums import CodeChallengeMethod, GrantType, Prompt
from provider.shared.models import Scope

router = APIRouter(tags=["discovery"])


@router.get(
    "/.well-known/openid-configuration",
    response_model=OpenIDConfiguration,
    summary="OpenID provider metadata",
    description=(
        "Everything a client needs to talk to IDEN, per OIDC Discovery 1.0.\n\n"
        "`scopes_supported` is queried from the database on every request rather "
        "than hard-coded, because administrators define scopes at runtime.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
)
async def openid_configuration(session: DBSessionDep) -> OpenIDConfiguration:
    return await _metadata(session)


@router.get(
    "/.well-known/oauth-authorization-server",
    response_model=OpenIDConfiguration,
    summary="OAuth 2.0 authorization server metadata",
    description=(
        "The same document, at the location RFC 8414 defines.\n\n"
        "A pure OAuth 2.0 client with no OIDC layer looks only here and would "
        "otherwise conclude the server has no metadata at all. The content is "
        "identical — every field RFC 8414 defines is already in the OIDC "
        "document, which is a superset of it.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
)
async def oauth_authorization_server(session: DBSessionDep) -> OpenIDConfiguration:
    return await _metadata(session)


async def _metadata(session: DBSessionDep) -> OpenIDConfiguration:
    values = await session.scalars(select(Scope.value).order_by(Scope.value))
    issuer = settings.iden_issuer

    return OpenIDConfiguration(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/oauth2/authorize",
        token_endpoint=f"{issuer}/oauth2/token",
        userinfo_endpoint=f"{issuer}/oauth2/userinfo",
        jwks_uri=f"{issuer}/.well-known/jwks.json",
        revocation_endpoint=f"{issuer}/oauth2/revoke",
        introspection_endpoint=f"{issuer}/oauth2/introspect",
        end_session_endpoint=f"{issuer}/oauth2/logout",
        scopes_supported=sorted(OIDC_SCOPES) + list(values),
        response_types_supported=["code"],
        grant_types_supported=[g.value for g in GrantType],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=[settings.iden_signing_algorithm],
        token_endpoint_auth_methods_supported=[
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        code_challenge_methods_supported=[CodeChallengeMethod.S256.value],
        acr_values_supported=auth_methods.reachable_levels(),
        amr_values_supported=auth_methods.supported(),
        prompt_values_supported=[value.value for value in Prompt],
        backchannel_logout_supported=True,
        backchannel_logout_session_supported=True,
        claims_supported=[
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "auth_time",
            "nonce",
            "acr",
            "amr",
            "sid",
            "name",
            "preferred_username",
            "email",
            "email_verified",
        ],
        response_modes_supported=["query"],
        request_parameter_supported=False,
        request_uri_parameter_supported=False,
        claims_parameter_supported=False,
        authorization_response_iss_parameter_supported=True,
        revocation_endpoint_auth_methods_supported=[
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        # No `none`: introspection describes someone else's token, and a
        # client_id alone is public by definition (RFC 7662 Section 2.1).
        introspection_endpoint_auth_methods_supported=[
            "client_secret_basic",
            "client_secret_post",
        ],
    )


@router.get(
    "/.well-known/jwks.json",
    response_model=JsonWebKeySet,
    summary="JSON Web Key Set",
    description=(
        "Public signing keys, one JWK per `kid`. Resource servers validate "
        "access tokens against these offline — no call back to IDEN.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
)
def json_web_key_set() -> JsonWebKeySet:
    return JsonWebKeySet(**jwks())
