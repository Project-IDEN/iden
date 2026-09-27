from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from provider.core.schemas import CamelCaseBaseModel

USERNAME_PATTERN = r"^[a-zA-Z0-9._-]+$"

# A dot, dash or underscore only between letters or digits: `a..b@` and `.a@`
# are not addresses.
LOCAL_PART_PATTERN = r"^[a-zA-Z0-9]+([._-][a-zA-Z0-9]+)*$"


class UserCreate(CamelCaseBaseModel):
    # A caller still sending `email` believes it chose the address. Refusing the
    # field says otherwise; ignoring it would create someone else's.
    model_config = CamelCaseBaseModel.model_config | ConfigDict(extra="forbid")

    email_local_part: str = Field(
        max_length=64,
        pattern=LOCAL_PART_PATTERN,
        description=(
            "What goes before the `@`. The address is "
            "`<emailLocalPart>@<IDEN_MAIL_DOMAIN>`, lowercased; there is no way "
            "to choose another domain, and no way to change it afterwards."
        ),
    )
    username: str = Field(max_length=64, pattern=USERNAME_PATTERN)
    display_name: str | None = None
    password: str | None = Field(
        default=None,
        min_length=12,
        description="Omit to have one generated and returned once in the response.",
    )
    role_ids: list[UUID] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(CamelCaseBaseModel):
    # The address is fixed at creation — it names a mailbox on the organization's
    # domain, and a mailbox cannot be renamed. Refused rather than ignored, so a
    # caller still sending `email` learns the change did not happen.
    model_config = CamelCaseBaseModel.model_config | ConfigDict(extra="forbid")

    username: str | None = Field(default=None, max_length=64, pattern=USERNAME_PATTERN)
    display_name: str | None = None
    is_active: bool | None = Field(
        default=None,
        description="Deactivating blocks login and refresh, but leaves the record intact.",
    )


class RoleAssignment(CamelCaseBaseModel):
    role_ids: list[UUID] = Field(
        description="The complete new set. Roles not listed are removed from the user."
    )


class ScopeAssignment(CamelCaseBaseModel):
    scope_ids: list[UUID] = Field(
        description=(
            "Direct grants, for one-off exceptions that do not deserve a role. "
            "The complete new set."
        )
    )


class Named(CamelCaseBaseModel):
    id: UUID
    name: str


class UserResponse(CamelCaseBaseModel):
    id: UUID
    email: str
    username: str
    display_name: str | None
    is_active: bool
    roles: list[Named]
    groups: list[Named]
    direct_scopes: list[str]
    last_login_at: datetime | None
    created_at: datetime


class UserCreated(UserResponse):
    generated_password: str | None = Field(
        default=None,
        description="Shown once and never recoverable. Null when a password was supplied.",
    )


class PasswordReset(CamelCaseBaseModel):
    password: str | None = Field(
        default=None, min_length=12, description="Omit to have one generated."
    )


class PasswordResetResult(CamelCaseBaseModel):
    password: str | None = Field(
        default=None,
        description="The generated password, shown once. Null when one was supplied.",
    )
    sessions_revoked: bool = Field(
        description="Always true — a password change invalidates every session and refresh token."
    )


class ScopeSource(CamelCaseBaseModel):
    """Why the user holds this scope."""

    value: str
    via_direct: bool = Field(description="Granted to the user individually.")
    via_roles: list[str] = Field(description="Roles assigned directly to the user.")
    via_groups: list[str] = Field(description="`group → role` paths that grant it.")


class EffectiveScopes(CamelCaseBaseModel):
    user_id: UUID
    scopes: list[ScopeSource]


class UserProfileResponse(CamelCaseBaseModel):
    fields: dict[str, Any] = Field(
        description="Organization-defined values, keyed by field key."
    )


class UserProfileUpdate(CamelCaseBaseModel):
    fields: dict[str, Any] = Field(
        default_factory=dict, description="Values to set, keyed by field key."
    )
