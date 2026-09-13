from typing import Literal

from pydantic import Field

from provider.core.schemas import CamelCaseBaseModel


class LoginRequest(CamelCaseBaseModel):
    challenge_id: str = Field(
        description="From the `challenge` query parameter on the login page."
    )
    email: str
    password: str


class TotpRequest(CamelCaseBaseModel):
    challenge_id: str
    code: str = Field(
        min_length=6,
        max_length=6,
        description="Six-digit code from the authenticator app.",
    )


class AuthStepResponse(CamelCaseBaseModel):
    status: Literal["complete", "method_required"] = Field(
        description=(
            "`complete` — follow `resumeUrl`; the authorization request decides "
            "what happens next. `method_required` — another sign-in method is "
            "owed first, one of those in `methods`."
        )
    )
    methods: list[str] = Field(
        default_factory=list,
        description=(
            "The `amr` values that would satisfy a `method_required` step — any "
            "one of them is enough. Empty when the step is complete."
        ),
    )
    resume_url: str | None = Field(
        default=None,
        description="Where to send the browser next. Null while a method is owed.",
    )
    acr: str = Field(description="Assurance level reached so far.")
    amr: list[str] = Field(description="Methods used so far.")


class ChallengeScope(CamelCaseBaseModel):
    value: str
    description: str


class ChallengeResponse(CamelCaseBaseModel):
    """What the Auth UI needs to render a login or consent page — deliberately
    the minimum, so the UI never has to understand OAuth."""

    client_name: str
    scopes: list[ChallengeScope] = Field(description="Scopes the client is asking for.")
    acr_values: str | None = Field(
        default=None, description="Minimum assurance the client requested."
    )
    authenticated: bool = Field(
        description="Whether a session already exists in this browser."
    )
    methods: list[str] = Field(
        default_factory=list,
        description=(
            "Set for a step-up: the browser is signed in and owes one of these "
            "`amr` values, so the page starts there rather than at the password."
        ),
    )
    login_hint: str | None = Field(
        default=None,
        description=(
            "The address the client suggested, for prefilling the form. A hint "
            "from the client, never an assertion of who is signing in — the "
            "password is still what decides that."
        ),
    )
