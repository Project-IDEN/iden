"""Every persisted model in IDEN. One file, one source of truth.

Sessions, login/consent challenges, and the access-token `jti` denylist are
deliberately absent — they are ephemeral and live in Redis under a TTL, so
expiry is the storage layer's job rather than a cleanup job's.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from provider.core.db import Base
from provider.shared.enums import ClientType, FieldType


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------
# Join tables
#
# Plain association tables: they carry no data of their own, so a mapped class
# would add a layer without adding anything to say.
# --------------------------------------------------------------------------

user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

group_roles = Table(
    "group_roles",
    Base.metadata,
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_scopes = Table(
    "role_scopes",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("scope_id", ForeignKey("scopes.id", ondelete="CASCADE"), primary_key=True),
)

# Direct user grants, for one-off exceptions that do not deserve a role.
user_scopes = Table(
    "user_scopes",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("scope_id", ForeignKey("scopes.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    # The file name of the profile photo in blob storage, not a URL. The bytes
    # live in the object store; this row only knows what they are called, and
    # the name changes on every upload so replacing a photo retires its URL.
    picture_key: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # selectin rather than lazy loading: these sets are small, they are always
    # needed together when resolving effective scopes, and a lazy load inside
    # async code fails with an unhelpful greenlet error.
    groups: Mapped[list[Group]] = relationship(
        secondary=user_groups, back_populates="users", lazy="selectin"
    )
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    scopes: Mapped[list[Scope]] = relationship(secondary=user_scopes, lazy="selectin")
    totp: Mapped[TotpCredential | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list[User]] = relationship(
        secondary=user_groups, back_populates="groups"
    )
    roles: Mapped[list[Role]] = relationship(secondary=group_roles, lazy="selectin")


class TotpCredential(Base, TimestampMixin):
    __tablename__ = "totp_credentials"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    secret: Mapped[str] = mapped_column(String(255))
    # Enrollment is two-step: the credential only counts once a generated code
    # has been confirmed, so a mis-scanned QR code cannot lock a user out.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="totp")


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


class ResourceApi(Base, TimestampMixin):
    __tablename__ = "resource_apis"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(128), unique=True)
    audience: Mapped[str] = mapped_column(String(512), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    scopes: Mapped[list[Scope]] = relationship(
        back_populates="api", cascade="all, delete-orphan"
    )


class Scope(Base, TimestampMixin):
    __tablename__ = "scopes"

    id: Mapped[uuid.UUID] = _pk()
    api_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resource_apis.id", ondelete="CASCADE")
    )
    # Globally unique, not merely unique per API: a token carries scopes as bare
    # strings, and the audience is resolved from the value. Two APIs sharing a
    # value would put both their audiences in one token.
    value: Mapped[str] = mapped_column(String(128), unique=True)
    # Required: this is the sentence a user reads on the consent screen.
    description: Mapped[str] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    api: Mapped[ResourceApi] = relationship(back_populates="scopes", lazy="selectin")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    scopes: Mapped[list[Scope]] = relationship(secondary=role_scopes, lazy="selectin")


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = _pk()
    client_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    client_type: Mapped[ClientType] = mapped_column(String(32))
    # Public clients have no secret and prove themselves with PKCE alone.
    client_secret_hash: Mapped[str | None] = mapped_column(String(255))
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    allowed_grants: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    post_logout_redirect_uris: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list
    )
    # Where to POST a logout token when a session this client was part of ends.
    # Null means the client is not told: it keeps its own session until whatever
    # it does next fails, which is the behaviour of every client today.
    backchannel_logout_uri: Mapped[str | None] = mapped_column(String(2048))
    # Whether that token must name the session. A client with one session per
    # user does not need it; one that can hold several does.
    backchannel_logout_session_required: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    skip_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # Who registered it through developer self-service. Null means the
    # organization owns it — the bootstrap clients, and anything an
    # administrator registered. `/developer/clients` only ever sees rows
    # carrying the caller's own id, which is what keeps one registrant out of
    # another's application.
    #
    # SET NULL rather than CASCADE: deleting a person should not silently break
    # every application they registered. It becomes organization-owned and an
    # administrator decides what happens to it.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    scopes: Mapped[list[ClientScope]] = relationship(
        back_populates="client", cascade="all, delete-orphan", lazy="selectin"
    )


class ClientScope(Base, TimestampMixin):
    """A client's relationship to one scope.

    `grantable` — may be requested on behalf of a user (authorization code).
    `granted`   — held by the client itself (client credentials).
    The two are independent: a kiosk holds `biometric:search` outright while a
    dashboard may only request `admin:users:read` for whoever is logged in.
    """

    __tablename__ = "client_scopes"
    __table_args__ = (UniqueConstraint("client_id", "scope_id"),)

    id: Mapped[uuid.UUID] = _pk()
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE")
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scopes.id", ondelete="CASCADE")
    )
    grantable: Mapped[bool] = mapped_column(Boolean, default=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=False)

    client: Mapped[Client] = relationship(back_populates="scopes")
    scope: Mapped[Scope] = relationship(lazy="selectin")


class AuthorizationCode(Base, TimestampMixin):
    __tablename__ = "authorization_codes"

    id: Mapped[uuid.UUID] = _pk()
    # Stored hashed, like every other credential: a database read must not
    # yield anything usable.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    scope: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(16))
    nonce: Mapped[str | None] = mapped_column(String(255))
    acr: Mapped[str] = mapped_column(String(32))
    amr: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # The browser session this code came from. Carried through to the `sid`
    # claim so a relying party can be told which session to end, and so
    # sign-out can find the tokens the session produced.
    sid: Mapped[str] = mapped_column(String(64))
    # When the *person* authenticated, which is not when the code was issued:
    # on the second application of an SSO session those differ by however long
    # the session has been alive, and `auth_time` is what a client's `max_age`
    # is measured against.
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_family_id", "family_id"),
        # Sign-out revokes every token a session produced, and that lookup runs
        # on the logout path where the user is waiting.
        Index("ix_refresh_tokens_sid", "sid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    scope: Mapped[str] = mapped_column(Text)
    # Carried so a refreshed token reports the same authentication event: acr is
    # derived from amr, and the original login is not repeated on refresh.
    acr: Mapped[str] = mapped_column(String(32))
    amr: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # Null only for tokens issued before sessions were recorded — a real
    # unknown, not an absent value.
    sid: Mapped[str | None] = mapped_column(String(64))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Rotation with reuse detection: presenting an already-rotated token revokes
    # the whole family, on the assumption it was stolen.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rotated_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsentGrant(Base, TimestampMixin):
    __tablename__ = "consent_grants"
    __table_args__ = (UniqueConstraint("user_id", "client_id"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE")
    )
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditEvent(Base):
    """One row per state-changing request. Append-only: never updated, never
    deleted by the application.

    No TimestampMixin — `updated_at` on an append-only table would be a lie, and
    `occurred_at` is the only time that means anything here.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # The route template rather than the resolved path — "POST
    # /admin/users/{user_id}/roles" groups, "POST /admin/users/9f2.../roles"
    # does not. The id it stands in for is in `target`.
    action: Mapped[str] = mapped_column(String(160))
    status_code: Mapped[int]
    target: Mapped[str | None] = mapped_column(String(255))

    # SET NULL, not CASCADE: deleting a user must not erase the record of what
    # they did. `actor_label` holds their email as it was at the time, for the
    # same reason — after the deletion it is all that is left of who this was.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_label: Mapped[str | None] = mapped_column(String(255))
    # The OAuth `client_id` string, not a foreign key: it is the stable public
    # name of the client, and the token carries it directly.
    actor_client: Mapped[str | None] = mapped_column(String(128))

    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProfileField(Base, TimestampMixin):
    """A profile field the organization defined at runtime.

    IDEN ships none of these. A university needs `student_id` and `department`;
    a company needs `employee_id` and `cost_centre`. Shipping either would make
    the other one's deployment wrong, so administrators define them the same
    way they define scopes.
    """

    __tablename__ = "profile_fields"

    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[FieldType] = mapped_column(String(16), default=FieldType.STRING)
    # Allowed values when data_type is `enum`; empty otherwise.
    options: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    # Enforced by a partial unique index on the values table, not by a check in
    # the service layer — a check-then-write races under load, and `student_id`
    # colliding is exactly the case that must not happen.
    unique: Mapped[bool] = mapped_column(Boolean, default=False)
    # pattern / min / max / min_length / max_length, applied at the boundary.
    validators: Mapped[dict] = mapped_column(JSONB, default=dict)

    # The pair that defines what self-service *means*. `student_id` is written
    # by the registrar and read-only to the student; `preferred_name` is theirs.
    # Same table, same endpoint, opposite permissions.
    user_readable: Mapped[bool] = mapped_column(Boolean, default=True)
    user_writable: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bound to a group, the field applies only to its members — which is how
    # students and staff get different fields without a second grouping concept.
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE")
    )

    # Opt-in token release. A field is invisible to clients until both are set,
    # and then only to a client granted `claim_scope` — data minimization by
    # default, reusing the scope system rather than inventing a second one.
    claim_name: Mapped[str | None] = mapped_column(String(64))
    claim_scope: Mapped[str | None] = mapped_column(String(128))

    display_order: Mapped[int] = mapped_column(default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    group: Mapped[Group | None] = relationship(lazy="selectin")


class UserProfileValue(Base, TimestampMixin):
    """One person's answer to one field.

    A row per value rather than a JSONB column on `users`: uniqueness has to be
    a database constraint, filtering by field has to be an indexed query, and
    renaming a field should rewrite one row instead of every profile.
    """

    __tablename__ = "user_profile_values"
    __table_args__ = (
        UniqueConstraint("user_id", "field_id"),
        # Only for fields marked unique. Partial, because two people leaving an
        # optional field blank is not a collision.
        Index(
            "ix_user_profile_values_unique",
            "field_id",
            "value",
            unique=True,
            postgresql_where=text("is_unique"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_fields.id", ondelete="CASCADE")
    )
    value: Mapped[str] = mapped_column(Text)
    # Copied from the field so the partial index can use it: an index predicate
    # cannot reach into another table.
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False)

    field: Mapped[ProfileField] = relationship(lazy="selectin")
