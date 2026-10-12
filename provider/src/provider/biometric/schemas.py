from datetime import datetime
from typing import Any, Literal, Self

from pydantic import Field

from provider.biometric.challenges import FLASH_SLOT_MS, FaceChallenge
from provider.core.schemas import CamelCaseBaseModel

Step = Literal[
    "center",
    "turn_left",
    "turn_right",
    "look_up",
    "look_down",
    "flash:red",
    "flash:green",
    "flash:blue",
]


class FaceChallengeResponse(CamelCaseBaseModel):
    face_challenge_id: str = Field(
        description="Send back with the frames. Good for one capture."
    )
    steps: list[Step] = Field(
        description=(
            "One entry per frame to capture, in order. `center`: look straight "
            "at the camera. `turn_left` / `turn_right`: turn your head to *your* "
            "left or right. `look_up` / `look_down`. `flash:<colour>`: fill the "
            "screen with that colour, then capture."
        )
    )
    flash_slot_ms: int = Field(
        description="How long to show each flash colour before capturing under it."
    )
    expires_at: datetime

    @classmethod
    def of(cls, challenge: FaceChallenge, **extra: Any) -> Self:
        return cls(
            face_challenge_id=challenge.id,
            steps=challenge.steps,  # pyright: ignore[reportArgumentType]
            flash_slot_ms=FLASH_SLOT_MS,
            expires_at=challenge.expires_at,
            **extra,
        )


class KioskChallengeRequest(CamelCaseBaseModel):
    ticket: str = Field(description="Read from the QR code the person shows.")


class KioskChallengeResponse(FaceChallengeResponse):
    display_name: str = Field(
        description="Show it, so the person can confirm it is their account."
    )


class KioskEnrolment(CamelCaseBaseModel):
    enrolled: Literal[True]
    samples: int = Field(description="How many face samples were stored.")
