"""The engine's wire format. Internal: only the provider reads it."""

from pydantic import BaseModel, Field

from engine.quality import Reason


class Checks(BaseModel):
    anti_spoofing: bool = Field(description="Passive models judged the face live.")
    anti_spoofing_score: float
    actions: bool = Field(description="Every requested head movement was made.")
    flash: bool = Field(description="The face reflected the colours shown.")
    flash_score: float
    consistent: bool = Field(description="Every frame shows the same person.")

    @property
    def live(self) -> bool:
        return self.anti_spoofing and self.actions and self.flash and self.consistent


class Capture(BaseModel):
    usable: bool = Field(
        description="Enough frames were good enough to judge. When false, "
        "`reasons` says what to fix and nothing else was decided."
    )
    reasons: list[Reason] = Field(description="Most common problem first.")
    checks: Checks | None = None
    live: bool = False
    model_version: str


class EnrollResult(Capture):
    embeddings: list[list[float]] = Field(
        default_factory=list, description="Best frames first; empty unless live."
    )
    qualities: list[float] = Field(default_factory=list)


class VerifyResult(Capture):
    matched: bool = False
    similarity: float = 0.0


class Info(BaseModel):
    model_version: str
    device: str
    providers: list[str]
    calibrated: bool
    match_threshold: float


class Meta(BaseModel):
    steps: list[str] = Field(description="What was asked of the person, per frame.")


class VerifyMeta(Meta):
    templates: list[list[float]] = Field(min_length=1)
