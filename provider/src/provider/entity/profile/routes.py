from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.auth import CurrentUserDep, require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse
from provider.core.storage import Storage, StorageDep
from provider.entity.profile import service
from provider.entity.profile.errors import PhotoTooLarge
from provider.entity.profile.schemas import (
    FieldSchema,
    ProfileResponse,
    ProfileSchemaResponse,
    ProfileUpdate,
)
from provider.shared import avatars
from provider.shared.models import User

router = APIRouter(prefix="/entity/profile", tags=["entity: profile"])

READ = Depends(require_scope("entity:profile:read"))
WRITE = Depends(require_scope("entity:profile:write"))


async def _profile(session: AsyncSession, user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        picture_url=avatars.public_url(user.picture_key),
        email_verified=user.email_verified_at is not None,
        fields=await service.read_profile(session, user),
    )


@router.get(
    "",
    response_model=ProfileResponse,
    summary="Read your own profile",
    description=(
        "The signed-in person's profile. There is no path parameter and no way "
        "to ask for anyone else's — the subject comes from the token.\n\n"
        "`fields` holds whatever this organization defined, filtered to the "
        "fields marked readable and to those that apply to the groups this "
        "person belongs to.\n\n"
        "**Required scope:** `entity:profile:read`"
    ),
    dependencies=[READ],
)
async def read_profile(user: CurrentUserDep, session: DBSessionDep) -> ProfileResponse:
    return await _profile(session, user)


@router.patch(
    "",
    response_model=ProfileResponse,
    summary="Update your own profile",
    description=(
        "Accepts exactly the fields an administrator marked writable. Writing "
        "anything else is refused rather than quietly dropped, so a client "
        "never believes it saved something it did not.\n\n"
        "Nothing here can change what you are *allowed* to do: roles, groups "
        "and scopes are absent from this module entirely.\n\n"
        "**Required scope:** `entity:profile:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No field with that key"},
        409: {"model": ErrorResponse, "description": "A unique field's value is taken"},
        422: {
            "model": ErrorResponse,
            "description": "Field is not yours to write, or the value does not fit",
        },
    },
    dependencies=[WRITE],
)
async def update_profile(
    body: ProfileUpdate, user: CurrentUserDep, session: DBSessionDep
) -> ProfileResponse:
    if body.display_name is not None:
        user.display_name = body.display_name

    await service.write_values(session, user, body.fields, enforce_writable=True)
    await session.commit()

    return await _profile(session, user)


@router.get(
    "/schema",
    response_model=ProfileSchemaResponse,
    summary="Read the shape of your profile",
    description=(
        "The field definitions that apply to you, in display order. A dashboard "
        "renders its form from this rather than hardcoding one organization's "
        "fields into a general-purpose identity provider.\n\n"
        "`writable: false` means the field is shown but belongs to the "
        "organization — a student sees `student_id` and cannot change it.\n\n"
        "**Required scope:** `entity:profile:read`"
    ),
    dependencies=[READ],
)
async def read_schema(
    user: CurrentUserDep, session: DBSessionDep
) -> ProfileSchemaResponse:
    fields = await service.fields_for(session, user)
    return ProfileSchemaResponse(
        fields=[
            FieldSchema(
                key=field.key,
                label=field.label,
                description=field.description,
                data_type=field.data_type,
                options=field.options,
                required=field.required,
                writable=field.user_writable,
                validators=field.validators,
            )
            for field in fields
            if field.user_readable
        ]
    )


@router.put(
    "/photo",
    response_model=ProfileResponse,
    summary="Set your profile photo",
    description=(
        "Uploads an image and makes it your profile photo, replacing any "
        "previous one.\n\n"
        "The file is decoded, turned upright from its EXIF orientation, "
        "cropped square, resized to 512px and re-encoded as WebP. Nothing you "
        "upload is stored as it arrived — re-encoding is what discards the "
        "metadata a camera records, including where the photo was taken.\n\n"
        "The new photo is served from a fresh unguessable URL, so the one the "
        "previous photo used stops resolving. Clients granted the `profile` "
        "scope see the URL as the standard `picture` claim.\n\n"
        "**Required scope:** `entity:profile:write`"
    ),
    responses={
        422: {
            "model": ErrorResponse,
            "description": "The file is not a readable image, or is too large",
        },
        503: {
            "model": ErrorResponse,
            "description": "This deployment has no file storage configured",
        },
    },
    dependencies=[WRITE],
)
async def set_photo(
    user: CurrentUserDep,
    session: DBSessionDep,
    storage: Storage = StorageDep,
    file: UploadFile = File(description="The image to use. JPEG, PNG, WebP or GIF."),
) -> ProfileResponse:
    # Read one byte past the limit rather than the whole file: that is enough
    # to know it is over without holding what went over it.
    data = await file.read(settings.iden_avatar_max_bytes + 1)
    if len(data) > settings.iden_avatar_max_bytes:
        raise PhotoTooLarge

    await service.set_photo(session, user, storage, data)
    return await _profile(session, user)


@router.delete(
    "/photo",
    response_model=ProfileResponse,
    summary="Remove your profile photo",
    description=(
        "Deletes the stored image and clears `pictureUrl`. Removing a photo "
        "that is not set succeeds and changes nothing.\n\n"
        "**Required scope:** `entity:profile:write`"
    ),
    responses={
        503: {
            "model": ErrorResponse,
            "description": "This deployment has no file storage configured",
        }
    },
    dependencies=[WRITE],
)
async def delete_photo(
    user: CurrentUserDep,
    session: DBSessionDep,
    storage: Storage = StorageDep,
) -> ProfileResponse:
    await service.clear_photo(session, user, storage)
    return await _profile(session, user)
