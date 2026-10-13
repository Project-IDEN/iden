from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from provider.core.schemas import CamelCaseBaseModel

KioskStatus = Literal["never_paired", "online", "offline", "out_of_service"]


class KioskSettings(CamelCaseBaseModel):
    """Set in the dashboard, picked up by the device at its next heartbeat."""

    idle_seconds: int = Field(
        default=90,
        ge=30,
        le=600,
        description="Seconds without a touch before the kiosk clears the screen "
        "and returns to its welcome screen.",
    )
    in_service: bool = Field(
        default=True,
        description="Off: the kiosk shows *out of service* and IDEN refuses its "
        "enrolments.",
    )
    notice: str | None = Field(
        default=None,
        max_length=200,
        description="A line shown on the welcome screen — opening hours, where "
        "to get help.",
    )
    camera_label: str | None = Field(
        default=None,
        max_length=128,
        description="Part of the camera's name, to choose it when several are "
        "attached. Empty uses the first camera.",
    )


class KioskCreate(CamelCaseBaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        description="What people see in the email telling them their face was "
        "enrolled, e.g. `Library Kiosk 2`.",
    )
    location: str | None = Field(default=None, max_length=255)


class KioskUpdate(CamelCaseBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    settings: KioskSettings | None = Field(
        default=None, description="Replaces the settings as a whole."
    )


class KioskResponse(CamelCaseBaseModel):
    id: UUID
    client_id: str = Field(description="What the device signs in as.")
    name: str
    location: str | None
    status: KioskStatus = Field(
        description="`online` when it reported in within the last three "
        "heartbeats; `out_of_service` when switched off in its settings, whether "
        "or not it is reachable."
    )
    settings: KioskSettings
    paired_at: datetime | None
    last_seen_at: datetime | None
    last_seen_version: str | None = Field(description="Kiosk software version.")
    last_seen_camera: str | None = Field(
        description="The camera it last reported, or null when it had none."
    )
    last_seen_address: str | None
    created_at: datetime


class PairingCode(CamelCaseBaseModel):
    code: str = Field(
        description="Shown once. Enter or scan it on the kiosk; single use. The "
        "QR form is `iden-kiosk-pair:<code>`."
    )
    expires_at: datetime


class KioskCreated(KioskResponse):
    pairing: PairingCode


class KioskEnrolmentEvent(CamelCaseBaseModel):
    occurred_at: datetime
    outcome: Literal["enrolled", "failed"]
    error: str | None = Field(
        description="Why it failed: `poor_capture`, `not_live`, "
        "`enrolment_ticket_invalid`, …"
    )
    user_id: UUID | None = Field(
        description="Whose face. Null when the ticket did not name anyone."
    )
    user_label: str | None = Field(description="Their display name, as it is now.")
