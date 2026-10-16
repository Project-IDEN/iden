from datetime import datetime
from typing import Any, Literal, Self

from pydantic import Field

from provider.admin.kiosks.schemas import KioskSettings
from provider.biometric.challenges import FaceChallenge
from provider.core.schemas import CamelCaseBaseModel

Step = Literal["center", "turn_left", "turn_right", "look_up", "look_down"]


class FaceChallengeResponse(CamelCaseBaseModel):
    face_challenge_id: str = Field(
        description="Send back with the frames. Good for one capture."
    )
    steps: list[Step] = Field(
        description=(
            "One entry per frame to capture, in order. `center`: look straight "
            "at the camera. `turn_left` / `turn_right`: turn your head to *your* "
            "left or right. `look_up` / `look_down`: tilt your head."
        )
    )
    expires_at: datetime

    @classmethod
    def of(cls, challenge: FaceChallenge, **extra: Any) -> Self:
        return cls(
            face_challenge_id=challenge.id,
            steps=challenge.steps,  # pyright: ignore[reportArgumentType]
            expires_at=challenge.expires_at,
            **extra,
        )


class KioskChallengeRequest(CamelCaseBaseModel):
    ticket: str = Field(description="Read from the QR code the person shows.")


class KioskChallengeResponse(FaceChallengeResponse):
    display_name: str = Field(
        description="Show it, so the person can confirm it is their account."
    )
    attempts_left: int = Field(
        description="Captures this ticket still allows after this one."
    )


class KioskEnrolment(CamelCaseBaseModel):
    enrolled: Literal[True]
    samples: int = Field(description="How many face samples were stored.")


class PairRequest(CamelCaseBaseModel):
    code: str = Field(
        max_length=32,
        description="The pairing code from the dashboard. Case, spaces and the "
        "dash do not matter.",
    )


class PairedKiosk(CamelCaseBaseModel):
    client_id: str
    client_secret: str = Field(
        description="Shown once. Store it on the device; it cannot be recovered, "
        "only replaced by pairing again."
    )
    name: str


class Heartbeat(CamelCaseBaseModel):
    software_version: str = Field(max_length=64)
    camera: str | None = Field(
        default=None,
        max_length=255,
        description="The camera the kiosk is using, by name; null when it has none.",
    )


class ConsentText(CamelCaseBaseModel):
    title: str
    statements: list[str] = Field(description="Show each as a paragraph, in order.")
    version: str = Field(
        description="Send back as `consent` with the enrolment once the person agrees."
    )


class KioskConfig(CamelCaseBaseModel):
    name: str
    location: str | None
    settings: KioskSettings
    heartbeat_seconds: int = Field(description="When to report in next.")
    consent: ConsentText = Field(
        description="What to show a person, and have them agree to, before "
        "anything is captured."
    )
