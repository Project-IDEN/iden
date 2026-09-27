from pydantic import Field

from provider.core.schemas import CamelCaseBaseModel


class PasswordChange(CamelCaseBaseModel):
    current_password: str = Field(
        description="Proves the person at the keyboard is the account's owner."
    )
    new_password: str = Field(min_length=12, max_length=256)


class CredentialChangeResponse(CamelCaseBaseModel):
    sessions_ended: int = Field(
        description="Other sessions signed out. A credential change that leaves "
        "old sessions alive has not really taken effect."
    )
