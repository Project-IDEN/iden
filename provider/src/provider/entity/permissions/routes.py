from fastapi import APIRouter, Depends
from pydantic import Field

from provider.authz.services.scope_resolver import scope_provenance
from provider.core.auth import CurrentUserDep, require_scope
from provider.core.schemas import CamelCaseBaseModel

router = APIRouter(prefix="/entity/permissions", tags=["entity: permissions"])

READ = Depends(require_scope("entity:permissions:read"))


class PermissionSource(CamelCaseBaseModel):
    value: str
    via_direct: bool = Field(description="Granted to you personally.")
    via_roles: list[str] = Field(description="Roles that carry it.")
    via_groups: list[str] = Field(description="Groups, and the role within each.")


class PermissionsResponse(CamelCaseBaseModel):
    groups: list[str]
    roles: list[str]
    scopes: list[PermissionSource] = Field(
        description="Every permission you hold, and where each one comes from."
    )


@router.get(
    "",
    response_model=PermissionsResponse,
    summary="See what you are allowed to do",
    description=(
        "Every permission you hold and where it comes from — directly, through "
        "a role, or through a group's role. The same provenance an "
        "administrator sees at `/admin/users/{id}/effective-scopes`, from one "
        "implementation, so the two can never disagree.\n\n"
        "Read-only by definition: changing what you are allowed to do is "
        "authority, and authority is admin territory.\n\n"
        "**Required scope:** `entity:permissions:read`"
    ),
    dependencies=[READ],
)
async def read_permissions(user: CurrentUserDep) -> PermissionsResponse:
    return PermissionsResponse(
        groups=sorted(group.name for group in user.groups),
        roles=sorted(role.name for role in user.roles),
        scopes=[
            PermissionSource(
                value=source.value,
                via_direct=source.via_direct,
                via_roles=source.via_roles,
                via_groups=source.via_groups,
            )
            for source in scope_provenance(user)
        ],
    )
