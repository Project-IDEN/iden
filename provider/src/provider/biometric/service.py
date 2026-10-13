"""Enrolling, verifying and removing faces. FastAPI-free.

The engine judges; this decides what the judgement means, and keeps the
results — encrypted embeddings, and photos only when the deployment asked.
"""

import base64
import uuid
from array import array
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.biometric.challenges import FaceChallenge
from provider.biometric.engine_client import Engine
from provider.biometric.errors import (
    BadFrames,
    FaceNotEnrolled,
    FaceOutdated,
    FaceRejected,
    NotLive,
    PoorCapture,
)
from provider.core import notifier
from provider.core.config import settings
from provider.core.security import (
    decrypt_secret,
    encrypt_bytes,
    encrypt_secret,
)
from provider.core.storage import Storage
from provider.shared.models import Client, FaceTemplate, User


def pack(vector: list[float], user_id: UUID) -> str:
    raw = array("f", vector).tobytes()
    return encrypt_secret(base64.b64encode(raw).decode(), context=str(user_id))


def unpack(stored: str, user_id: UUID) -> list[float]:
    raw = base64.b64decode(decrypt_secret(stored, context=str(user_id)))
    return array("f", raw).tolist()


async def templates(session: AsyncSession, user_id: UUID) -> list[FaceTemplate]:
    return list(
        await session.scalars(
            select(FaceTemplate)
            .where(FaceTemplate.user_id == user_id)
            .order_by(FaceTemplate.quality.desc())
        )
    )


async def is_enrolled(session: AsyncSession, user_id: UUID) -> bool:
    found = await session.scalar(
        select(FaceTemplate.id).where(FaceTemplate.user_id == user_id).limit(1)
    )
    return found is not None


def _matches_challenge(frames: list[bytes], challenge: FaceChallenge) -> None:
    if len(frames) != len(challenge.steps):
        raise BadFrames(
            f"Expected {len(challenge.steps)} frames, received {len(frames)}."
        )


async def enrol(
    session: AsyncSession,
    engine: Engine,
    storage: Storage | None,
    user: User,
    kiosk: Client,
    frames: list[bytes],
    challenge: FaceChallenge,
) -> list[FaceTemplate]:
    """Replace this person's face with the one in `frames`."""
    _matches_challenge(frames, challenge)
    result = await engine.enroll(frames, challenge.steps)
    if not result.usable:
        raise PoorCapture(reasons=result.reasons)
    if not result.live:
        raise NotLive(
            failed=result.checks.failed() if result.checks else [],
            scores=result.checks.scores() if result.checks else {},
        )

    previous = await templates(session, user.id)
    keep = settings.iden_biometric_keep_images and storage is not None
    rows = []
    for vector, quality, source in zip(
        result.embeddings, result.qualities, result.sources, strict=True
    ):
        image_key = None
        if keep and storage is not None:
            image_key = f"faces/{uuid.uuid7().hex}"
            await storage.put(
                image_key,
                encrypt_bytes(frames[source], context=str(user.id)),
                "application/octet-stream",
            )
        rows.append(
            FaceTemplate(
                user_id=user.id,
                model_version=result.model_version,
                embedding_encrypted=pack(vector, user.id),
                quality=quality,
                enrolled_by=kiosk.client_id,
                image_key=image_key,
            )
        )
    # Old and new swap in one transaction: a failure leaves the previous face
    # enrolled rather than none.
    await session.execute(delete(FaceTemplate).where(FaceTemplate.user_id == user.id))
    session.add_all(rows)
    await session.commit()
    await _delete_images(storage, previous)

    # Enrolment adds a way to sign in as this person, so they hear about it
    # from somewhere other than the kiosk — and know how to undo it.
    await notifier.send(
        to=user.email,
        subject="A face was enrolled on your account",
        body=(
            f"Your face was enrolled at {kiosk.name}. If this was not you, remove "
            f"it from Security in your account at {settings.iden_issuer} and "
            "change your password."
        ),
    )
    return rows


async def verify(
    session: AsyncSession,
    engine: Engine,
    user_id: UUID,
    frames: list[bytes],
    challenge: FaceChallenge,
) -> None:
    """Return quietly when the capture is live and is this person; raise otherwise."""
    rows = await templates(session, user_id)
    if not rows:
        raise FaceNotEnrolled
    _matches_challenge(frames, challenge)

    stored_version = rows[0].model_version
    result = await engine.verify(
        frames,
        challenge.steps,
        [unpack(row.embedding_encrypted, user_id) for row in rows],
    )
    # Compared under another model, the similarity means nothing.
    if result.model_version != stored_version:
        raise FaceOutdated
    if not result.usable:
        raise PoorCapture(reasons=result.reasons)
    if not (result.live and result.matched):
        raise FaceRejected


async def remove(session: AsyncSession, storage: Storage | None, user_id: UUID) -> None:
    rows = await templates(session, user_id)
    await session.execute(delete(FaceTemplate).where(FaceTemplate.user_id == user_id))
    await session.commit()
    await _delete_images(storage, rows)


async def _delete_images(storage: Storage | None, rows: list[FaceTemplate]) -> None:
    # After the commit: a photo left behind by a failure here is an orphan in
    # the bucket, where the other order would leave a template pointing at
    # nothing.
    if storage is None:
        return
    for row in rows:
        if row.image_key:
            await storage.delete(row.image_key)
