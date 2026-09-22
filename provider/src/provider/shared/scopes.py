"""The system API, scope, and role catalogue seeded by `scripts.seed`.

Everything here is flagged `is_system` in the database and cannot be renamed or
deleted through the admin API — without that guard an administrator could
delete `admin:roles:write` and lock the organization out of its own deployment.

Admin-created APIs, scopes, and roles carry no such flag and are fully mutable.
When a new admin resource ships, add its scopes here and re-run the seed.
"""

from dataclasses import dataclass

from provider.core.config import settings


@dataclass(frozen=True)
class ScopeSpec:
    value: str
    description: str


@dataclass(frozen=True)
class ApiSpec:
    name: str
    audience: str
    description: str
    scopes: tuple[ScopeSpec, ...]


@dataclass(frozen=True)
class RoleSpec:
    name: str
    description: str
    scopes: tuple[str, ...]


ADMIN_SCOPES = (
    ScopeSpec("admin:users:read", "View users, their roles, and their direct grants."),
    ScopeSpec(
        "admin:users:write",
        "Create, update, and delete users, and reset their passwords.",
    ),
    # Split out of `admin:users:write`, which used to carry both. Assigning
    # permissions is the one administrative act that can increase somebody's
    # authority, including the caller's own — so it is the one worth being able
    # to withhold. A help-desk account that creates people, renames them,
    # deactivates them and resets their passwords now needs `admin:users:write`
    # and not this.
    ScopeSpec(
        "admin:grants:write",
        "Assign roles and individual scopes to a person.",
    ),
    ScopeSpec("admin:groups:read", "View groups, their members, and their roles."),
    ScopeSpec(
        "admin:groups:write", "Create, update, and delete groups and membership."
    ),
    ScopeSpec("admin:roles:read", "View roles and the scopes they bundle."),
    ScopeSpec(
        "admin:roles:write", "Create, update, and delete roles and their scopes."
    ),
    ScopeSpec("admin:apis:read", "View registered resource APIs."),
    ScopeSpec("admin:apis:write", "Register, update, and delete resource APIs."),
    ScopeSpec("admin:scopes:read", "View the scopes defined under an API."),
    ScopeSpec("admin:scopes:write", "Define, update, and delete scopes under an API."),
    ScopeSpec("admin:clients:read", "View registered OAuth clients."),
    ScopeSpec("admin:clients:write", "Register clients and rotate their secrets."),
    # Read-only by design: the audit log is written by the requests it records
    # and has no write endpoint to grant.
    ScopeSpec("admin:audit:read", "Read the audit log."),
    ScopeSpec("admin:profile-fields:read", "View the organization's profile schema."),
    ScopeSpec(
        "admin:profile-fields:write",
        "Define the fields this organization collects about people.",
    ),
)

ENTITY_SCOPES = (
    ScopeSpec("entity:profile:read", "View your own profile."),
    ScopeSpec("entity:profile:write", "Update your own profile."),
    ScopeSpec("entity:credentials:write", "Change your own password."),
    ScopeSpec("entity:totp:read", "View the status of your authenticator app."),
    ScopeSpec("entity:totp:enroll", "Set up or remove your authenticator app."),
    ScopeSpec("entity:sessions:read", "See where you are signed in."),
    ScopeSpec("entity:sessions:revoke", "Sign yourself out of other sessions."),
    ScopeSpec(
        "entity:permissions:read", "See your own roles, groups, and permissions."
    ),
    ScopeSpec("entity:connections:read", "See which applications have access."),
    ScopeSpec("entity:connections:revoke", "Withdraw an application's access."),
)

# Self-service application registration, for people outside the organization who
# integrate with IDEN. Deliberately its own API rather than an `entity:` scope:
# `ENTITY_SCOPES` is handed wholesale to the `member` role, so anything added
# there makes every account a developer.
DEVELOPER_SCOPES = (
    ScopeSpec("developer:clients:read", "View the applications you registered."),
    ScopeSpec(
        "developer:clients:write",
        "Register your own applications and rotate their secrets.",
    ),
)

BIOMETRIC_SCOPES = (
    ScopeSpec("biometric:enroll", "Enrol a face template."),
    ScopeSpec("biometric:verify", "Verify a face against a claimed identity."),
    ScopeSpec("biometric:search", "Identify a face against all enrolled templates."),
    ScopeSpec("biometric:liveness", "Check whether a captured face is live."),
)


def system_apis() -> tuple[ApiSpec, ...]:
    apis = (
        ApiSpec(
            name="admin",
            audience=settings.admin_audience,
            description="IDEN administration — users, groups, roles, APIs, scopes, clients.",
            scopes=ADMIN_SCOPES,
        ),
        ApiSpec(
            name="entity",
            audience=settings.entity_audience,
            description="Self-service for the signed-in person.",
            scopes=ENTITY_SCOPES,
        ),
        ApiSpec(
            name="developer",
            audience=settings.developer_audience,
            description="Self-service application registration for developers.",
            scopes=DEVELOPER_SCOPES,
        ),
    )
    if settings.iden_biometric_enabled:
        apis += (
            ApiSpec(
                name="biometric",
                audience=settings.biometric_audience,
                description="Facial enrollment and verification.",
                scopes=BIOMETRIC_SCOPES,
            ),
        )
    return apis


# The prefixes whose scopes confer authority over somebody *other than* their
# holder, and which therefore cannot be handed out by an administrator who does
# not hold them — see `admin.delegation`.
#
# `entity:` and `developer:` are deliberately absent. They are self-service:
# holding `entity:profile:write` lets you edit your own profile and nobody
# else's, so granting one to someone increases their authority over themselves
# and the granter's over nothing. Restricting those would only stop an
# administrator doing the job the role exists for.
#
# Everything outside this set — an organization's own APIs — is unrestricted for
# the same reason, and a stronger one: an identity provider exists to let
# administrators grant permissions they do not personally hold. Requiring the
# registrar to hold `attendance:records:write` before granting it would mean
# holding every permission in the organization.
RESTRICTED_PREFIXES = frozenset({"admin", "biometric"})


def system_roles() -> tuple[RoleSpec, ...]:
    admin = tuple(s.value for s in ADMIN_SCOPES)
    entity = tuple(s.value for s in ENTITY_SCOPES)
    developer = tuple(s.value for s in DEVELOPER_SCOPES)
    # Held, not merely grantable. `RESTRICTED_PREFIXES` means a scope can only be
    # handed out by someone who holds it, so an administrator who did not hold
    # these could never assign them to the kiosk client that needs them — and
    # nobody else could either, which is a deployment with a biometric module it
    # cannot configure.
    biometric = (
        tuple(s.value for s in BIOMETRIC_SCOPES)
        if settings.iden_biometric_enabled
        else ()
    )
    return (
        RoleSpec(
            name="administrator",
            description="Full control over the deployment.",
            scopes=admin + entity + developer + biometric,
        ),
        RoleSpec(
            name="member",
            description="An ordinary person with self-service access only.",
            scopes=entity,
        ),
        RoleSpec(
            name="developer",
            description=(
                "Registers their own applications against IDEN. No authority "
                "over anyone else's application, and none over the directory."
            ),
            scopes=entity + developer,
        ),
    )
