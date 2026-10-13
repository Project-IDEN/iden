import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin.kiosks.errors import KioskNotFound
from provider.admin.kiosks.schemas import (
    KioskCreate,
    KioskEnrolmentEvent,
    KioskSettings,
    KioskStatus,
    KioskUpdate,
)
from provider.core.security import generate_token, hash_secret_async
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import AuditEvent, Client, ClientScope, Kiosk, Scope, User
from provider.shared.scopes import BIOMETRIC_SCOPES

# How often a kiosk reports in; it is told this at every heartbeat.
HEARTBEAT_SECONDS = 60
# Missing one report is a blip; missing three is a kiosk that is off.
OFFLINE_AFTER = timedelta(seconds=3 * HEARTBEAT_SECONDS)

ENROL_ACTION = "POST /biometric/enroll"


def settings_of(kiosk: Kiosk) -> KioskSettings:
    return KioskSettings.model_validate(kiosk.settings)


def status_of(kiosk: Kiosk) -> KioskStatus:
    if not settings_of(kiosk).in_service:
        return "out_of_service"
    if kiosk.paired_at is None:
        return "never_paired"
    seen = kiosk.last_seen_at
    if seen is not None and datetime.now(UTC) - seen < OFFLINE_AFTER:
        return "online"
    return "offline"


async def list_kiosks(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Kiosk], int]:
    total = await session.scalar(select(func.count(Kiosk.id))) or 0
    kiosks = list(
        await session.scalars(
            select(Kiosk)
            .join(Client)
            .order_by(Client.name, Kiosk.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return kiosks, total


async def get_kiosk(session: AsyncSession, kiosk_id: UUID) -> Kiosk:
    kiosk = await session.get(Kiosk, kiosk_id)
    if kiosk is None:
        raise KioskNotFound
    return kiosk


async def for_client(session: AsyncSession, client_id: str) -> Kiosk | None:
    """The kiosk a token's `client_id` belongs to, if it is one."""
    return await session.scalar(
        select(Kiosk).join(Client).where(Client.client_id == client_id)
    )


async def create_kiosk(session: AsyncSession, data: KioskCreate) -> Kiosk:
    """A kiosk and the client it will sign in as.

    The client has no secret until the device pairs, so nothing can sign in as
    it in the meantime.
    """
    client = Client(
        client_id=f"kiosk-{secrets.token_hex(5)}",
        name=data.name,
        client_type=ClientType.CONFIDENTIAL,
        allowed_grants=[GrantType.CLIENT_CREDENTIALS],
        skip_consent=True,
    )
    session.add(client)
    await session.flush()

    for scope in await session.scalars(
        select(Scope).where(Scope.value.in_([s.value for s in BIOMETRIC_SCOPES]))
    ):
        session.add(
            ClientScope(
                client_id=client.id, scope_id=scope.id, grantable=False, granted=True
            )
        )

    kiosk = Kiosk(
        client_id=client.id,
        location=data.location,
        settings=KioskSettings().model_dump(),
    )
    session.add(kiosk)
    await session.commit()
    await session.refresh(kiosk)
    return kiosk


async def update_kiosk(
    session: AsyncSession, kiosk_id: UUID, data: KioskUpdate
) -> Kiosk:
    kiosk = await get_kiosk(session, kiosk_id)
    if data.name is not None:
        kiosk.client.name = data.name
    if "location" in data.model_fields_set:
        kiosk.location = data.location
    if data.settings is not None:
        kiosk.settings = data.settings.model_dump()
    await session.commit()
    return kiosk


async def delete_kiosk(session: AsyncSession, kiosk_id: UUID) -> None:
    """Deletes the client too, which is what revokes the device: its secret no
    longer exists, and enrolment refuses a token whose client is not a kiosk."""
    kiosk = await get_kiosk(session, kiosk_id)
    await session.delete(kiosk.client)
    await session.commit()


async def pair(session: AsyncSession, kiosk_id: UUID) -> tuple[Kiosk, str]:
    """A new secret for the device presenting the pairing code. Whatever device
    held the previous one can no longer sign in."""
    kiosk = await get_kiosk(session, kiosk_id)
    secret = generate_token(32)
    kiosk.client.client_secret_hash = await hash_secret_async(secret)
    kiosk.paired_at = datetime.now(UTC)
    kiosk.last_seen_at = None
    await session.commit()
    return kiosk, secret


async def heartbeat(
    session: AsyncSession,
    kiosk: Kiosk,
    *,
    version: str,
    camera: str | None,
    address: str | None,
) -> Kiosk:
    kiosk.last_seen_at = datetime.now(UTC)
    kiosk.last_seen_version = version
    kiosk.last_seen_camera = camera
    kiosk.last_seen_address = address
    await session.commit()
    return kiosk


async def enrolments(
    session: AsyncSession, kiosk_id: UUID, *, limit: int, offset: int
) -> tuple[list[KioskEnrolmentEvent], int]:
    """What this kiosk enrolled, and what it tried to, newest first. Read from
    the audit log, which already holds every attempt and why it failed."""
    kiosk = await get_kiosk(session, kiosk_id)
    where = (
        AuditEvent.actor_client == kiosk.client.client_id,
        AuditEvent.action == ENROL_ACTION,
    )
    total = await session.scalar(select(func.count(AuditEvent.id)).where(*where)) or 0
    events = list(
        await session.scalars(
            select(AuditEvent)
            .where(*where)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )

    user_ids = {UUID(e.target) for e in events if e.target}
    users = {
        user.id: user
        for user in await session.scalars(select(User).where(User.id.in_(user_ids)))
    }

    def event(row: AuditEvent) -> KioskEnrolmentEvent:
        user = users.get(UUID(row.target)) if row.target else None
        return KioskEnrolmentEvent(
            occurred_at=row.occurred_at,
            outcome="enrolled" if row.status_code < 400 else "failed",
            error=row.detail.get("error") if row.status_code >= 400 else None,
            user_id=UUID(row.target) if row.target else None,
            user_label=(user.display_name or user.username) if user else None,
        )

    return [event(row) for row in events], total
