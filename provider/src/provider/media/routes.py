"""Public delivery of stored files.

Separate from `/entity/*` because it answers without a token. An `<img>` tag in
a relying application cannot present one, so the file name carries the secret
instead — see `shared.avatars`. Application logos are public for a plainer
reason: the consent screen shows one before anybody has a token.
"""

from fastapi import APIRouter, Path, Response

from provider.core.errors import NotFoundError
from provider.core.images import AVATAR_CONTENT_TYPE
from provider.core.storage import Storage, StorageDep
from provider.shared import avatars, logos

router = APIRouter(prefix="/media", tags=["media"])

# A year, and immutable: the name changes on every upload, so a cached copy can
# never be stale. It is the whole reason photos are not served from a URL keyed
# by user id.
CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get(
    "/avatars/{name}",
    response_class=Response,
    summary="Fetch a profile photo",
    description=(
        "The image bytes for one profile photo, as WebP.\n\n"
        "Public: this is the URL IDEN puts in the `picture` claim, and it is "
        "fetched by `<img>` tags that cannot send an `Authorization` header. "
        "The file name is unguessable and is replaced whenever the photo is, "
        "so the previous URL stops resolving.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
    responses={
        200: {"content": {AVATAR_CONTENT_TYPE: {}}, "description": "The image."},
        404: {"description": "No photo is stored under that name."},
        503: {"description": "This deployment has no file storage configured."},
    },
)
async def read_avatar(
    storage: Storage = StorageDep,
    name: str = Path(
        pattern=r"^[A-Za-z0-9_-]{1,58}\.webp$",
        description="The file name from `pictureUrl`.",
    ),
) -> Response:
    return await _serve(storage, avatars.object_key(name), "photo")


@router.get(
    "/logos/{name}",
    response_class=Response,
    summary="Fetch an application's logo",
    description=(
        "The image bytes for one application's logo, as WebP.\n\n"
        "Public: the consent screen shows it before anyone is signed in. The "
        "file name is unguessable and is replaced whenever the logo is.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
    responses={
        200: {"content": {AVATAR_CONTENT_TYPE: {}}, "description": "The image."},
        404: {"description": "No logo is stored under that name."},
        503: {"description": "This deployment has no file storage configured."},
    },
)
async def read_logo(
    storage: Storage = StorageDep,
    name: str = Path(
        pattern=r"^[A-Za-z0-9_-]{1,58}\.webp$",
        description="The file name from `logoUrl`.",
    ),
) -> Response:
    return await _serve(storage, logos.object_key(name), "logo")


async def _serve(storage: Storage, key: str, what: str) -> Response:
    data = await storage.get(key)
    if data is None:
        raise NotFoundError(f"No {what} is stored under that name.")
    return Response(
        content=data,
        media_type=AVATAR_CONTENT_TYPE,
        headers={"Cache-Control": CACHE_CONTROL},
    )
