from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from provider.admin.users import service
from provider.admin.users.schemas import (
    EffectiveScopes,
    Named,
    PasswordReset,
    PasswordResetResult,
    RoleAssignment,
    ScopeAssignment,
    ScopeSource,
    UserCreate,
    UserCreated,
    UserProfileResponse,
    UserProfileUpdate,
    UserResponse,
    UserUpdate,
)
from provider.authz.services.scope_resolver import scope_provenance
from provider.core.auth import AccessToken, require_scope
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep
from provider.entity.profile import service as profile_service

router = APIRouter(prefix="/admin/users", tags=["admin: users"])

READ = Depends(require_scope("admin:users:read"))
WRITE = Depends(require_scope("admin:users:write"))

# Assigning permissions is its own scope, split out of `admin:users:write`: it is
# the only administrative act that can raise somebody's authority, so it is the
# one worth being able to withhold from an account that otherwise manages people.
GrantsToken = Annotated[AccessToken, Depends(require_scope("admin:grants:write"))]

# Taken as a parameter rather than a bare dependency because the handler needs it:
# what a caller may grant is bounded by the scopes in their own token — see
# `admin.delegation`.
WriteToken = Annotated[AccessToken, Depends(require_scope("admin:users:write"))]

OUTRANK_NOTE = (
    "\n\n**You cannot act on an account above your own.** If the target holds an "
    "`admin:` or `biometric:` scope the caller does not, the request is refused "
    "with `403 cannot_administer` — otherwise resetting a password and clearing "
    "an authenticator would together be a way to become somebody more "
    "privileged than you."
)

DELEGATION_NOTE = (
    "\n\n**You cannot grant what you do not hold.** Any `admin:` or `biometric:` "
    "scope in what this would confer must already be in the caller's own token, "
    "or the request is refused with `403 cannot_delegate`. Scopes belonging to "
    "your organization's own APIs are unrestricted — granting those is what an "
    "administrator is for."
)


def to_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=[
            Named(id=r.id, name=r.name)
            for r in sorted(user.roles, key=lambda r: r.name)
        ],
        groups=[
            Named(id=g.id, name=g.name)
            for g in sorted(user.groups, key=lambda g: g.name)
        ],
        direct_scopes=sorted(s.value for s in user.scopes),
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get(
    "",
    response_model=Page[UserResponse],
    summary="List users",
    description=(
        "Filterable by group, role, active status, and a substring of email or "
        "username.\n\n"
        "**Required scope:** `admin:users:read`"
    ),
    dependencies=[READ],
)
async def list_users(
    session: DBSessionDep,
    page: PaginationDep,
    search: str | None = Query(None, description="Substring of email or username."),
    # Aliased so the query string is camelCase like every request and response
    # body. Without it a caller sending `groupId` gets an unfiltered list back,
    # which is the worst kind of wrong answer: a plausible one.
    group_id: UUID | None = Query(None, alias="groupId"),
    role_id: UUID | None = Query(None, alias="roleId"),
    is_active: bool | None = Query(None, alias="isActive"),
) -> Page[UserResponse]:
    users, total = await service.list_users(
        session,
        limit=page.limit,
        offset=page.offset,
        search=search,
        group_id=group_id,
        role_id=role_id,
        is_active=is_active,
    )

    return Page[UserResponse](
        items=[to_response(user) for user in users],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=UserCreated,
    status_code=201,
    summary="Create a user",
    description=(
        "Creates an account, optionally with roles and group memberships.\n\n"
        "Omit `password` and one is generated and returned **once** in "
        "`generatedPassword`. It is argon2-hashed on the way in and cannot be "
        "recovered afterwards.\n\n"
        "**Required scope:** `admin:users:write`" + DELEGATION_NOTE
    ),
    responses={
        403: {
            "model": ErrorResponse,
            "description": "A role or group would confer a scope the caller lacks",
        },
        404: {"model": ErrorResponse, "description": "Unknown role or group ids"},
        409: {"model": ErrorResponse, "description": "Email or username already taken"},
    },
)
async def create_user(
    body: UserCreate, session: DBSessionDep, token: WriteToken
) -> UserCreated:
    user, generated = await service.create_user(
        session, body, caller_scopes=token.scopes
    )
    return UserCreated(**to_response(user).model_dump(), generated_password=generated)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Read a user",
    description="**Required scope:** `admin:users:read`",
    responses={404: {"model": ErrorResponse, "description": "No such user"}},
    dependencies=[READ],
)
async def read_user(user_id: UUID, session: DBSessionDep) -> UserResponse:
    return to_response(await service.get_user(session, user_id))


@router.get(
    "/{user_id}/effective-scopes",
    response_model=EffectiveScopes,
    summary="Explain a user's permissions",
    description=(
        "Every scope this user holds, annotated with **where it came from** — a "
        "direct grant, a role, or a group's role.\n\n"
        "This is the endpoint that answers *why can this person do that?*, and "
        "the answer a permission audit needs. It is computed with the same "
        "resolver that runs at token issuance, so it cannot disagree with what a "
        "token would actually carry.\n\n"
        "**Required scope:** `admin:users:read`"
    ),
    responses={404: {"model": ErrorResponse, "description": "No such user"}},
    dependencies=[READ],
)
async def effective_scopes(user_id: UUID, session: DBSessionDep) -> EffectiveScopes:
    user = await service.get_user(session, user_id)

    return EffectiveScopes(
        user_id=user.id,
        scopes=[
            ScopeSource(
                value=source.value,
                via_direct=source.via_direct,
                via_roles=source.via_roles,
                via_groups=source.via_groups,
            )
            for source in scope_provenance(user)
        ],
    )


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user",
    description=(
        "Deactivating a user (`isActive: false`) immediately revokes every "
        "session and refresh token — otherwise the account stays usable until "
        "they expire on their own.\n\n"
        "Deactivating the last active administrator is refused with `409`.\n\n"
        "**Required scope:** `admin:users:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such user"},
        409: {
            "model": ErrorResponse,
            "description": "Email or username taken, or would leave no administrator",
        },
    },
)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    session: DBSessionDep,
    redis: RedisDep,
    token: WriteToken,
) -> UserResponse:
    return to_response(
        await service.update_user(
            session, redis, user_id, body, caller_scopes=token.scopes
        )
    )


@router.put(
    "/{user_id}/roles",
    response_model=UserResponse,
    summary="Set a user's roles",
    description=(
        "**Replaces the entire set.** Roles inherited from groups are unaffected "
        "— those are managed on the group.\n\n"
        "Refused with `409` when it would leave no active user holding "
        "`admin:grants:write`: nothing in the API can grant it back.\n\n"
        "**Required scope:** `admin:grants:write`" + DELEGATION_NOTE
    ),
    responses={
        403: {
            "model": ErrorResponse,
            "description": "A role would confer a scope the caller does not hold",
        },
        404: {
            "model": ErrorResponse,
            "description": "No such user, or unknown role ids",
        },
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
    },
)
async def set_roles(
    user_id: UUID, body: RoleAssignment, session: DBSessionDep, token: GrantsToken
) -> UserResponse:
    return to_response(
        await service.set_roles(
            session, user_id, body.role_ids, caller_scopes=token.scopes
        )
    )


@router.put(
    "/{user_id}/scopes",
    response_model=UserResponse,
    summary="Set a user's direct scope grants",
    description=(
        "Individual grants for exceptions that do not deserve a role. "
        "**Replaces the entire set.**\n\n"
        "Prefer roles: a direct grant is invisible in any role listing and is "
        "easy to forget when someone changes jobs.\n\n"
        "Refused with `409` when it would leave no active user holding "
        "`admin:grants:write`.\n\n"
        "**Required scope:** `admin:grants:write`" + DELEGATION_NOTE
    ),
    responses={
        403: {
            "model": ErrorResponse,
            "description": "One of the scopes is not one the caller holds",
        },
        404: {
            "model": ErrorResponse,
            "description": "No such user, or unknown scope ids",
        },
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
    },
)
async def set_scopes(
    user_id: UUID, body: ScopeAssignment, session: DBSessionDep, token: GrantsToken
) -> UserResponse:
    return to_response(
        await service.set_direct_scopes(
            session, user_id, body.scope_ids, caller_scopes=token.scopes
        )
    )


@router.post(
    "/{user_id}/reset-password",
    response_model=PasswordResetResult,
    summary="Reset a user's password",
    description=(
        "Sets a new password and signs the user out everywhere — every session "
        "and refresh token is revoked, because a credential change that leaves "
        "old sessions alive has not really taken effect.\n\n"
        "Omit `password` to have one generated and returned once.\n\n"
        "**Required scope:** `admin:users:write`" + OUTRANK_NOTE
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such user"},
        403: {
            "model": ErrorResponse,
            "description": "This account holds authority the caller does not",
        },
    },
)
async def reset_password(
    user_id: UUID,
    body: PasswordReset,
    session: DBSessionDep,
    redis: RedisDep,
    token: WriteToken,
) -> PasswordResetResult:
    generated = await service.reset_password(
        session, redis, user_id, body.password, caller_scopes=token.scopes
    )
    return PasswordResetResult(password=generated, sessions_revoked=True)


@router.delete(
    "/{user_id}/totp",
    status_code=204,
    summary="Clear a user's authenticator",
    description=(
        "The way back from a lost phone, and the only one there is.\n\n"
        "An enrolled authenticator is otherwise a one-way door: once confirmed "
        "it is owed at **every** sign-in, whatever the application asked for; "
        "removing it through `/entity/totp` needs a recent sign-in the person "
        "can no longer complete; and a password reset leaves the credential in "
        "place. Losing the device therefore locked the account for good, with a "
        "hand-edited database as the way out.\n\n"
        "**This lowers the account to a single factor** until they enrol again, "
        "so it is worth confirming who is asking by some means other than the "
        "request. It is recorded in the audit log with the administrator who did "
        "it.\n\n"
        "Returns `204` whether or not an authenticator was enrolled — there is "
        "nothing to report about the difference, and a `404` would only say "
        "whether a particular person uses one.\n\n"
        "**Required scope:** `admin:users:write`" + OUTRANK_NOTE
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such user"},
        403: {
            "model": ErrorResponse,
            "description": "This account holds authority the caller does not",
        },
    },
)
async def clear_totp(
    user_id: UUID, session: DBSessionDep, token: WriteToken
) -> Response:
    await service.clear_totp(session, user_id, caller_scopes=token.scopes)
    return Response(status_code=204)


@router.delete(
    "/{user_id}",
    status_code=204,
    summary="Delete a user",
    description=(
        "Removes the account and everything hanging off it. Consider "
        "deactivating instead — deletion loses the audit trail of who did what.\n\n"
        "**Required scope:** `admin:users:write`" + OUTRANK_NOTE
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such user"},
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
        403: {
            "model": ErrorResponse,
            "description": "This account holds authority the caller does not",
        },
    },
)
async def delete_user(
    user_id: UUID, session: DBSessionDep, redis: RedisDep, token: WriteToken
) -> Response:
    await service.delete_user(session, redis, user_id, caller_scopes=token.scopes)
    return Response(status_code=204)


@router.get(
    "/{user_id}/profile",
    response_model=UserProfileResponse,
    summary="Read a user's profile values",
    description=(
        "Every organization-defined field that applies to this person, "
        "including the ones they cannot see themselves.\n\n"
        "**Required scope:** `admin:users:read`"
    ),
    responses={404: {"model": ErrorResponse, "description": "No such user"}},
    dependencies=[READ],
)
async def read_user_profile(
    user_id: UUID, session: DBSessionDep
) -> UserProfileResponse:
    user = await service.get_user(session, user_id)
    return UserProfileResponse(
        fields=await profile_service.read_profile(session, user, readable_only=False)
    )


@router.patch(
    "/{user_id}/profile",
    response_model=UserProfileResponse,
    summary="Set a user's profile values",
    description=(
        "The other half of `userWritable`. A registrar sets `student_id` here; "
        "the student cannot set it through `/entity/profile`. An administrator "
        "is not held to the writability flag — being able to write what its "
        "owner cannot is exactly what the flag means.\n\n"
        "**Required scope:** `admin:users:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such user, or no such field"},
        409: {"model": ErrorResponse, "description": "A unique field's value is taken"},
        422: {
            "model": ErrorResponse,
            "description": "The value does not fit the field",
        },
    },
    dependencies=[WRITE],
)
async def update_user_profile(
    user_id: UUID, body: UserProfileUpdate, session: DBSessionDep
) -> UserProfileResponse:
    user = await service.get_user(session, user_id)
    await profile_service.write_values(
        session, user, body.fields, enforce_writable=False
    )
    return UserProfileResponse(
        fields=await profile_service.read_profile(session, user, readable_only=False)
    )
