from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin.profile_fields.errors import (
    EnumNeedsOptions,
    FieldKeyTaken,
    FieldNotFound,
    ReservedClaimName,
    SystemFieldImmutable,
    UnknownClaimScope,
    UnknownGroup,
)
from provider.admin.profile_fields.schemas import (
    ProfileFieldCreate,
    ProfileFieldUpdate,
)
from provider.shared.enums import FieldType
from provider.shared.models import Group, ProfileField, Scope
from provider.shared.profile import RESERVED_CLAIMS


async def list_fields(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[ProfileField], int]:
    total = await session.scalar(select(func.count(ProfileField.id))) or 0
    fields = list(
        await session.scalars(
            select(ProfileField)
            .order_by(ProfileField.display_order, ProfileField.key)
            .limit(limit)
            .offset(offset)
        )
    )
    return fields, total


async def get_field(session: AsyncSession, field_id: UUID) -> ProfileField:
    field = await session.get(ProfileField, field_id)
    if field is None:
        raise FieldNotFound
    return field


async def _validate(
    session: AsyncSession,
    *,
    data_type: FieldType | str,
    options: list[str],
    claim_name: str | None,
    claim_scope: str | None,
) -> None:
    if data_type == FieldType.ENUM and not options:
        raise EnumNeedsOptions

    if claim_name and claim_name in RESERVED_CLAIMS:
        raise ReservedClaimName

    if claim_scope and not await session.scalar(
        select(Scope).where(Scope.value == claim_scope)
    ):
        raise UnknownClaimScope


async def create_field(session: AsyncSession, data: ProfileFieldCreate) -> ProfileField:
    if await session.scalar(select(ProfileField).where(ProfileField.key == data.key)):
        raise FieldKeyTaken

    if data.group_id is not None and await session.get(Group, data.group_id) is None:
        raise UnknownGroup

    await _validate(
        session,
        data_type=data.data_type,
        options=data.options,
        claim_name=data.claim_name,
        claim_scope=data.claim_scope,
    )

    # by_alias=False: the schema serialises camelCase for the wire, and these
    # are column names.
    field = ProfileField(**data.model_dump(by_alias=False))
    session.add(field)
    await session.commit()
    await session.refresh(field)
    return field


async def update_field(
    session: AsyncSession, field_id: UUID, data: ProfileFieldUpdate
) -> ProfileField:
    field = await get_field(session, field_id)
    if field.is_system:
        raise SystemFieldImmutable

    changes = data.model_dump(exclude_unset=True, by_alias=False)
    await _validate(
        session,
        data_type=field.data_type,
        options=changes.get("options", field.options),
        claim_name=changes.get("claim_name", field.claim_name),
        claim_scope=changes.get("claim_scope", field.claim_scope),
    )

    for name, value in changes.items():
        setattr(field, name, value)

    await session.commit()
    await session.refresh(field)
    return field


async def delete_field(session: AsyncSession, field_id: UUID) -> None:
    """Deleting a field deletes everyone's answers to it.

    Said plainly in the endpoint description rather than guarded against: an
    organization that stops collecting a field should stop holding the data,
    and the cascade is the only thing that actually accomplishes that.
    """
    field = await get_field(session, field_id)
    if field.is_system:
        raise SystemFieldImmutable

    await session.delete(field)
    await session.commit()
