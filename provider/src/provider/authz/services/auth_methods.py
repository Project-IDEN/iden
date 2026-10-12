"""The authentication method registry and the acr derivation it feeds.

The seam the biometric module adds `face` through. `register()` covers acr
derivation and discovery; a new method also needs a check in
`login.service.enrolled_methods` and a form in the Auth UI.
"""

from collections.abc import Callable
from dataclasses import dataclass

from provider.core.config import settings
from provider.shared.enums import AcrLevel, AmrMethod


@dataclass(frozen=True)
class MethodSpec:
    name: AmrMethod
    description: str
    # Asked at each call rather than once at import, so a feature flag decides
    # what discovery advertises without a restart in between mattering.
    enabled: Callable[[], bool] = lambda: True


_registry: dict[AmrMethod, MethodSpec] = {}


def register(spec: MethodSpec) -> None:
    _registry[spec.name] = spec


def supported() -> list[str]:
    return [name.value for name, spec in _registry.items() if spec.enabled()]


register(MethodSpec(AmrMethod.PWD, "Password"))
register(MethodSpec(AmrMethod.OTP, "Time-based one-time code (RFC 6238)"))
register(
    MethodSpec(
        AmrMethod.FACE,
        "Facial match, liveness-verified",
        enabled=lambda: settings.iden_biometric_enabled,
    )
)

# What a person can offer after their password. Either one answers their own
# rule that a password alone is not enough.
SECOND_FACTORS = {AmrMethod.OTP.value, AmrMethod.FACE.value}


def normalized_amr(amr: list[str]) -> list[str]:
    """The `amr` claim as emitted: RFC 8176 adds `mfa` when two or more
    distinct factors were used."""
    factors = [m for m in amr if m != AmrMethod.MFA]
    if len(set(factors)) >= 2:
        return [*factors, AmrMethod.MFA.value]
    return factors


LEVELS = [AcrLevel.SFA, AcrLevel.MFA, AcrLevel.MFA_FACE]


def derive_acr(amr: list[str]) -> AcrLevel:
    """Assurance level from the methods actually used.

    Derived at issuance rather than stored, so a mid-session step-up upgrades
    the next token with no state to keep in sync.
    """
    factors = {m for m in amr if m != AmrMethod.MFA}

    if AmrMethod.FACE in factors and len(factors) >= 2:
        return AcrLevel.MFA_FACE
    if len(factors) >= 2:
        return AcrLevel.MFA
    return AcrLevel.SFA


def meets(acr: AcrLevel, required: str | None) -> bool:
    """Whether a session's level satisfies a client's `acr_values` request.

    Levels are ordered, so `mfa-face` satisfies a request for `mfa`.
    """
    if not required:
        return True

    requested = [AcrLevel(v) for v in required.split() if v in set(AcrLevel)]
    if not requested:
        return True

    return LEVELS.index(acr) >= min(LEVELS.index(level) for level in requested)


def reachable_levels() -> list[str]:
    """The levels some combination of registered methods can reach.

    What discovery may honestly advertise: `urn:iden:acr:mfa-face` needs a face, so it is
    listed once something registers one and not before.
    """
    top = derive_acr(supported())
    return [level.value for level in LEVELS[: LEVELS.index(top) + 1]]


def outstanding(amr: list[str], enrolled: set[str], required: str | None) -> list[str]:
    """The methods still to be used before this sign-in is enough — none when
    it already is.

    Two reasons to ask for more, answering to different people.

    The *client* demands a level through `acr_values`, worth asking for only when
    this person's methods can reach it — a level they cannot reach is for
    /authorize to refuse, not a form nobody could get past.

    The *person* demands a second factor by having set up an authenticator. A
    factor that applied only when an application asked would protect nobody,
    since whoever holds the password would use an application that does not
    ask. Any second factor answers it — a face as well as a code. An enrolled
    face alone does not create the demand: someone on a laptop without a camera
    must still be able to sign in.

    When a client's level is what is owed, only the methods that reach it are
    offered: a code does nothing for a request for `mfa-face`.
    """
    used = {m for m in amr if m != AmrMethod.MFA}
    unused = sorted(enrolled - used)

    owes_second_factor = AmrMethod.OTP in enrolled and len(used) < 2
    falls_short = not meets(derive_acr(amr), required) and meets(
        derive_acr(list(enrolled)), required
    )
    if falls_short:
        reaching = [m for m in unused if meets(derive_acr([*amr, m]), required)]
        return reaching or unused
    if owes_second_factor:
        return [m for m in unused if m in SECOND_FACTORS]
    return []
