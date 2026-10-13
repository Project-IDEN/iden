"""An application's logo: where it lives, and replacing or removing it.

Shared by `/admin/clients` and `/developer/clients`, which differ in who may
reach a client but not in what a logo is. Served without a token, like a
profile photo, because the consent screen shows it before anyone has one — so
the file name is unguessable and changes with every upload; see
`shared.avatars`.
"""

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core import images
from provider.core.config import settings
from provider.core.errors import ValidationError
from provider.core.logging import logger
from provider.core.storage import Storage
from provider.shared.avatars import new_name
from provider.shared.models import Client

PREFIX = "logos/"

# Small, because a logo is: 256px of WebP is a few kilobytes. It also keeps the
# upload under nginx's default body limit, so no proxy location is needed.
MAX_BYTES = 512 * 1024


class LogoTooLarge(ValidationError):
    code = "logo_too_large"
    message = f"A logo can be at most {MAX_BYTES // 1024} KB."


def object_key(name: str) -> str:
    return f"{PREFIX}{name}"


def public_url(name: str | None) -> str | None:
    if name is None:
        return None
    return f"{settings.iden_issuer}/media/logos/{name}"


async def replace(
    session: AsyncSession, client: Client, storage: Storage, data: bytes
) -> None:
    """Stored, then pointed at, then the old file removed: a crash anywhere
    leaves an unreferenced object rather than a client naming a missing file."""
    name = new_name()
    logo = await anyio.to_thread.run_sync(images.to_logo, data)
    await storage.put(object_key(name), logo, images.AVATAR_CONTENT_TYPE)

    previous = client.logo_key
    client.logo_key = name
    await session.commit()

    if previous:
        await storage.delete(object_key(previous))


async def remove(session: AsyncSession, client: Client, storage: Storage) -> None:
    previous = client.logo_key
    if previous is None:
        return

    client.logo_key = None
    await session.commit()
    await storage.delete(object_key(previous))


async def forget(name: str | None, storage: Storage | None) -> None:
    """The file of a client that has just been deleted.

    Best effort: the row is already gone, and a store that is down must not turn
    a completed deletion into an error. What is left behind is one unreferenced
    image under a name nobody can guess.
    """
    if name is None or storage is None:
        return
    try:
        await storage.delete(object_key(name))
    except Exception as exc:
        logger.warning("Could not delete a client's logo", error=str(exc))
