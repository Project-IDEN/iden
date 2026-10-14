"""The engine's wire format. Internal: only the provider reads it."""

from pydantic import BaseModel, Field

from engine.quality import Reason


class Checks(BaseModel):
    anti_spoofing: bool = Field(description="The passive model judged the face live.")
    anti_spoofing_score: float = Field(
        description="Mean live probability over the straight-ahead frames."
    )
    actions: bool = Field(description="Every requested head movement was made.")
    actions_score: float = Field(
        default=0.0,
        description="How far the least-made movement went, as a share of what "
        "counts: 1.0 and above passes, below 0 is the wrong way.",
    )
    flash: bool = Field(description="The face reflected the colours shown.")
    flash_score: float = Field(
        description="Share of flash frames whose colour cast matched the colour shown."
    )
    flash_spread: float = Field(
        default=0.0, description="The largest colour change seen across them."
    )
    consistent: bool = Field(description="Every frame shows the same person.")
    consistency_score: float = Field(
        default=0.0, description="The least similar frame's similarity."
    )

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
    sources: list[int] = Field(
        default_factory=list, description="The frame each embedding came from."
    )


class EmbedResult(BaseModel):
    model_version: str
    embeddings: list[list[float] | None] = Field(
        description="One per photo, null where no single face was found."
    )


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
