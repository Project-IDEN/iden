from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelCaseBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class Credentials(CamelCaseBaseModel):
    client_id: str
    client_secret: str
    name: str


class KioskState(CamelCaseBaseModel):
    paired: bool
    name: str | None = Field(description="The kiosk's name, as set in the dashboard.")
    location: str | None
    settings: dict[str, Any] = Field(
        description="As set in the dashboard: `idleSeconds`, `inService`, "
        "`notice`, `cameraLabel`. Empty until the first heartbeat answers."
    )
    online: bool | None = Field(
        description="Whether IDEN answered the last request; null before the first."
    )
    version: str


class PairRequest(CamelCaseBaseModel):
    code: str = Field(max_length=32)


class CameraReport(CamelCaseBaseModel):
    camera: str | None = Field(
        default=None, max_length=255, description="The camera's name, or null."
    )


class TicketRequest(CamelCaseBaseModel):
    ticket: str = Field(max_length=512)
