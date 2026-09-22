from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from provider.core.schemas import CamelCaseBaseModel
from provider.shared.client_uris import (
    BACKCHANNEL_URI_RULES,
    REDIRECT_URI_RULES,
    validate_backchannel_uri,
    validate_redirect_uris,
)
from provider.shared.enums import GrantType

# Higher than the developer surface's five: one organization legitimately
# registers a callback per environment for the same application. It is a ceiling
# on an accident, not a policy.
MAX_URIS = 20


class ClientCreate(CamelCaseBaseModel):
    client_id: str = Field(
        max_length=128,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="The public identifier the client sends at /authorize and /token.",
    )
    name: str = Field(
        max_length=255, description="Shown to users on the consent screen."
    )
    client_type: Literal["public", "confidential"] = Field(
        description=(
            "`public` — browser or mobile app; no secret, PKCE only. "
            "`confidential` — a backend that can keep a secret."
        )
    )
    allowed_grants: list[
        Literal["authorization_code", "refresh_token", "client_credentials"]
    ] = Field(default_factory=lambda: [GrantType.AUTHORIZATION_CODE.value])
    redirect_uris: list[str] = Field(
        default_factory=list,
        description=f"Matched exactly at /authorize. {REDIRECT_URI_RULES}",
    )
    post_logout_redirect_uris: list[str] = Field(
        default_factory=list, description="Same rules as `redirectUris`."
    )
    backchannel_logout_uri: str | None = Field(
        default=None,
        description=(
            "Where IDEN POSTs a logout token when a session this client was part "
            "of ends. Leave null and the client is never told: it keeps serving "
            f"its own session until something else fails.\n\n{BACKCHANNEL_URI_RULES}"
        ),
    )
    backchannel_logout_session_required: bool = Field(
        default=False,
        description=(
            "Whether that token must name the session with `sid`. Needed only by "
            "a client that can hold several sessions for one person."
        ),
    )
    skip_consent: bool = Field(
        default=False,
        description=(
            "First-party applications only. Consenting to your own organization's "
            "dashboard is noise; anything else should ask."
        ),
    )
    grantable_scope_ids: list[UUID] = Field(
        default_factory=list,
        description="Scopes this client may request on behalf of a user.",
    )
    granted_scope_ids: list[UUID] = Field(
        default_factory=list,
        description="Scopes the client holds in its own right, for client_credentials.",
    )

    @field_validator("redirect_uris", "post_logout_redirect_uris")
    @classmethod
    def check_uris(cls, values: list[str]) -> list[str]:
        return validate_redirect_uris(values, maximum=MAX_URIS)

    @field_validator("backchannel_logout_uri")
    @classmethod
    def check_backchannel_uri(cls, value: str | None) -> str | None:
        return validate_backchannel_uri(value)


class ClientUpdate(CamelCaseBaseModel):
    """Every field is optional; the ones left out are untouched.

    The URIs are validated here exactly as on create. They were not, which made
    the update body the way around every rule the create body enforced.
    """

    name: str | None = Field(default=None, max_length=255)
    allowed_grants: (
        list[Literal["authorization_code", "refresh_token", "client_credentials"]]
        | None
    ) = None
    redirect_uris: list[str] | None = Field(
        default=None, description=REDIRECT_URI_RULES
    )
    post_logout_redirect_uris: list[str] | None = None
    backchannel_logout_uri: str | None = Field(
        default=None, description=BACKCHANNEL_URI_RULES
    )
    backchannel_logout_session_required: bool | None = None
    skip_consent: bool | None = None

    @field_validator("redirect_uris", "post_logout_redirect_uris")
    @classmethod
    def check_uris(cls, values: list[str] | None) -> list[str] | None:
        return (
            None if values is None else validate_redirect_uris(values, maximum=MAX_URIS)
        )

    @field_validator("backchannel_logout_uri")
    @classmethod
    def check_backchannel_uri(cls, value: str | None) -> str | None:
        return validate_backchannel_uri(value)


class ClientScopeAssignment(CamelCaseBaseModel):
    grantable_scope_ids: list[UUID] = Field(default_factory=list)
    granted_scope_ids: list[UUID] = Field(default_factory=list)


class ScopeSummary(CamelCaseBaseModel):
    id: UUID
    value: str


class ClientResponse(CamelCaseBaseModel):
    id: UUID
    client_id: str
    name: str
    client_type: str
    allowed_grants: list[str]
    redirect_uris: list[str]
    post_logout_redirect_uris: list[str]
    backchannel_logout_uri: str | None
    backchannel_logout_session_required: bool
    skip_consent: bool
    is_system: bool
    owner_user_id: UUID | None = Field(
        description=(
            "Who registered it through `/developer/clients`. Null means the "
            "organization owns it — a bootstrap client, or one an administrator "
            "registered here."
        )
    )
    grantable_scopes: list[ScopeSummary]
    granted_scopes: list[ScopeSummary]
    created_at: datetime


class ClientCreated(ClientResponse):
    client_secret: str | None = Field(
        default=None,
        description="Shown once and never stored in the clear. Null for public clients.",
    )


class SecretRotated(CamelCaseBaseModel):
    client_secret: str = Field(
        description="Shown once. The previous secret stops working now."
    )
