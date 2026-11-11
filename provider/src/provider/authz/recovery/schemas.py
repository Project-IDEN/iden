from typing import Annotated

from pydantic import Field, StringConstraints

from provider.core.schemas import CamelCaseBaseModel


class PasswordResetRequest(CamelCaseBaseModel):
    # Stored addresses are lowercase; a mailbox is case-insensitive.
    email: Annotated[str, StringConstraints(max_length=255, to_lower=True)]


class PasswordResetConfirm(CamelCaseBaseModel):
    token: str = Field(description="From the emailed link. Single use, 15 minutes.")
    new_password: str = Field(min_length=12, max_length=256)
