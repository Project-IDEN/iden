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
    # Separate from `admin:users:write`, because assigning permissions is the one
    # administrative act that can raise somebody's authority — including the
    # caller's own — so it is the one worth being able to withhold.
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

# Self-service application registration. Its own API rather than an `entity:`
# scope, because `ENTITY_SCOPES` goes wholesale to the `member` role and anything
# added there would make every account a developer.
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
# holder, and so cannot be handed out by an administrator who lacks them — see
# `admin.delegation`.
#
# `entity:` and `developer:` are absent because they are self-service: granting
# one raises the grantee's authority over themselves and the granter's over
# nobody. An organization's own APIs are absent for a stronger reason — an
# identity provider exists so administrators can grant permissions they do not
# personally hold.
RESTRICTED_PREFIXES = frozenset({"admin", "biometric"})


def system_roles() -> tuple[RoleSpec, ...]:
    admin = tuple(s.value for s in ADMIN_SCOPES)
    entity = tuple(s.value for s in ENTITY_SCOPES)
    developer = tuple(s.value for s in DEVELOPER_SCOPES)
    # Held, not merely grantable: under `RESTRICTED_PREFIXES` an administrator who
    # lacked these could never assign them to the kiosk client that needs them.
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
