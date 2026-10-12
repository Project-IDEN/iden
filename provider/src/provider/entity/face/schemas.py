from datetime import datetime

from pydantic import Field

from provider.core.schemas import CamelCaseBaseModel


class FaceStatus(CamelCaseBaseModel):
    enrolled: bool
    enrolled_at: datetime | None = None
    enrolled_by: str | None = Field(
        default=None, description="The kiosk the face was enrolled at."
    )
    samples: int = Field(default=0, description="Face samples on file.")


class EnrolmentTicket(CamelCaseBaseModel):
    ticket: str = Field(
        description=(
            "Show as a QR code for a kiosk to scan. Single use; asking for a new "
            "one retires this one."
        )
    )
    expires_at: datetime
