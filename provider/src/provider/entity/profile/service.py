"""Reading and writing one person's profile."""

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core import images
from provider.core.storage import Storage
from provider.entity.profile.errors import (
    FieldNotWritable,
    InvalidFieldValue,
    UnknownField,
    ValueTaken,
)
from provider.shared import avatars
from provider.shared import profile as values
from provider.shared.models import ProfileField, User, UserProfileValue


async def fields_for(session: AsyncSession, user: User) -> list[ProfileField]:
    """The fields that are part of this person's profile, in form order.

    A field bound to a group belongs only to its members, so two people in the
    same deployment can have genuinely different profiles.
    """
    group_ids = {group.id for group in user.groups}
    all_fields = await session.scalars(
        select(ProfileField).order_by(ProfileField.display_order, ProfileField.key)
    )
    return [field for field in all_fields if values.applies_to(field, group_ids)]


async def values_for(session: AsyncSession, user: User) -> dict[str, UserProfileValue]:
    rows = await session.scalars(
        select(UserProfileValue).where(UserProfileValue.user_id == user.id)
    )
    return {row.field.key: row for row in rows}


async def read_profile(
    session: AsyncSession, user: User, *, readable_only: bool = True
) -> dict:
    """Field values as their declared types.

    `readable_only` is what the person themselves sees; an administrator reads
    the same profile without that filter.
    """
    stored = await values_for(session, user)
    result = {}
    for field in await fields_for(session, user):
        if readable_only and not field.user_readable:
            continue
        row = stored.get(field.key)
        result[field.key] = values.render(field, row.value) if row else None
    return result


async def write_values(
    session: AsyncSession,
    user: User,
    updates: dict,
    *,
    enforce_writable: bool,
) -> None:
    """Set field values, validating each against its definition.

    `enforce_writable` is the whole self-service rule: when the person is
    editing their own profile, only fields an administrator marked writable are
    accepted. An administrator writing the same profile is not held to it —
    that is what `user_writable=False` means.
    """
    if not updates:
        return

    fields = {field.key: field for field in await fields_for(session, user)}
    stored = await values_for(session, user)

    for key, raw in updates.items():
        field = fields.get(key)
        if field is None:
            raise UnknownField(field=key)
        if enforce_writable and not field.user_writable:
            raise FieldNotWritable(field=key)

        try:
            value = values.coerce(field, raw)
        except values.InvalidValue as exc:
            raise InvalidFieldValue(str(exc), field=key) from exc

        row = stored.get(key)
        if row is None:
            row = UserProfileValue(user_id=user.id, field_id=field.id)
            session.add(row)
        row.value = value
        # Mirrored from the field so the partial unique index can use it: an
        # index predicate cannot reach into another table.
        row.is_unique = field.unique

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueTaken from exc


async def claims_for(session: AsyncSession, user: User, scopes: set[str]) -> dict:
    """Organization-defined fields released as token claims.

    A field is invisible to clients until an administrator sets both
    `claim_name` and `claim_scope`, and then only reaches a client that was
    granted that scope. Data minimization by default, and it reuses the scope
    system rather than inventing a second release mechanism beside it.
    """
    stored = await values_for(session, user)
    released = {}

    for field in await fields_for(session, user):
        if not field.claim_name or field.claim_scope not in scopes:
            continue
        row = stored.get(field.key)
        if row is not None:
            released[field.claim_name] = values.render(field, row.value)

    return released


async def set_photo(
    session: AsyncSession, user: User, storage: Storage, data: bytes
) -> None:
    """Replace this person's profile photo with the uploaded file.

    Written to the store, then pointed at, then the old file removed. In that
    order a crash anywhere leaves an unreferenced object rather than a row
    naming a file that is not there.
    """
    name = avatars.new_name()
    # Off the event loop: decoding and resampling a large photo is seconds of
    # CPU, and every other request on this worker would wait for it.
    avatar = await anyio.to_thread.run_sync(images.to_avatar, data)
    await storage.put(avatars.object_key(name), avatar, images.AVATAR_CONTENT_TYPE)

    previous = user.picture_key
    user.picture_key = name
    await session.commit()

    if previous:
        await storage.delete(avatars.object_key(previous))


async def clear_photo(session: AsyncSession, user: User, storage: Storage) -> None:
    previous = user.picture_key
    if previous is None:
        return

    user.picture_key = None
    await session.commit()
    await storage.delete(avatars.object_key(previous))
