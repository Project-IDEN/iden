"""Move enrolled faces onto the engine's current model.

Embeddings from one model cannot be compared under another, so after a model
upgrade every face on file stops matching and the person sees "enrol again".
Where enrolment photos were kept (IDEN_BIOMETRIC_KEEP_IMAGES), this re-embeds
them instead, and nobody has to come back to a kiosk.

    uv run python -m scripts.reembed_faces            # re-embed
    uv run python -m scripts.reembed_faces --dry-run  # count only

Faces with no photos on file are reported and left alone: only enrolling again
can move them.
"""

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.biometric.engine_client import Engine, HttpEngine
from provider.biometric.service import pack
from provider.core.db import engine as db_engine
from provider.core.db import session_factory
from provider.core.security import decrypt_bytes
from provider.core.storage import Storage, get_storage
from provider.shared.models import FaceTemplate


@dataclass
class Report:
    version: str = ""
    moved: int = 0
    current: int = 0
    without_photos: int = 0
    unreadable: int = 0


async def reembed(
    session: AsyncSession, engine: Engine, storage: Storage, *, dry_run: bool = False
) -> Report:
    report = Report(version=(await engine.info()).model_version)
    rows = list(await session.scalars(select(FaceTemplate)))

    for row in rows:
        if row.model_version == report.version:
            report.current += 1
            continue
        sealed = await storage.get(row.image_key) if row.image_key else None
        if sealed is None:
            report.without_photos += 1
            continue
        if dry_run:
            report.moved += 1
            continue

        photo = decrypt_bytes(sealed, context=str(row.user_id))
        result = await engine.embed([photo])
        vector = result.embeddings[0] if result.embeddings else None
        if vector is None:
            report.unreadable += 1
            continue
        row.embedding_encrypted = pack(vector, row.user_id)
        row.model_version = result.model_version
        report.moved += 1

    if not dry_run:
        await session.commit()
    return report


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    async with session_factory() as session:
        report = await reembed(session, HttpEngine(), get_storage(), dry_run=dry_run)
    await db_engine.dispose()

    verb = "would move" if dry_run else "moved"
    print(f"Engine model: {report.version}")
    print(f"  {verb}: {report.moved}")
    print(f"  already current: {report.current}")
    print(f"  no photo on file (must enrol again): {report.without_photos}")
    print(f"  photo without a usable face: {report.unreadable}")


if __name__ == "__main__":
    asyncio.run(main())
