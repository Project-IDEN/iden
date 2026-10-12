"""What a person is asked to do in front of the camera, chosen at random.

A recording made before the challenge was issued cannot contain the right
movements in the right order, nor reflect colours nobody had chosen yet. Each
challenge is good for one capture: `consume` deletes it as it reads it.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from redis.asyncio import Redis

from provider.core.security import generate_token, hash_token

Purpose = Literal["enrol", "login"]

ACTIONS: tuple[str, ...] = ("turn_left", "turn_right", "look_up", "look_down")
COLOURS: tuple[str, ...] = ("red", "green", "blue")

CENTRE_FRAMES = 3
FRAMES_PER_ACTION = 3
FLASH_SLOTS = 4
# How long each flash colour is shown. Long enough for the camera to expose a
# frame under it, short enough that auto white balance has not yet cancelled it.
FLASH_SLOT_MS = 400

# A capture takes about ten seconds; this allows for reading the instructions.
TTL_SECONDS = 120

_random = secrets.SystemRandom()


@dataclass(frozen=True)
class FaceChallenge:
    id: str
    user_id: UUID
    purpose: Purpose
    actions: list[str]
    colours: list[str]
    expires_at: datetime

    @property
    def steps(self) -> list[str]:
        """One entry per frame the camera must send, in order."""
        return (
            ["center"] * CENTRE_FRAMES
            + [action for action in self.actions for _ in range(FRAMES_PER_ACTION)]
            + [f"flash:{colour}" for colour in self.colours]
        )


def _colours() -> list[str]:
    """Every colour at least once, never the same twice in a row — so the
    reflection has to change from frame to frame."""
    colours = _random.sample(COLOURS, len(COLOURS))
    colours.append(_random.choice([c for c in COLOURS if c != colours[-1]]))
    return colours[:FLASH_SLOTS]


def _key(challenge_id: str) -> str:
    return f"face-challenge:{hash_token(challenge_id)}"


async def issue(redis: Redis, user_id: UUID, purpose: Purpose) -> FaceChallenge:
    challenge = FaceChallenge(
        id=generate_token(),
        user_id=user_id,
        purpose=purpose,
        actions=_random.sample(ACTIONS, 2),
        colours=_colours(),
        expires_at=datetime.now(UTC) + timedelta(seconds=TTL_SECONDS),
    )
    payload = {
        "user_id": str(user_id),
        "purpose": purpose,
        "actions": challenge.actions,
        "colours": challenge.colours,
        "expires_at": challenge.expires_at.isoformat(),
    }
    await redis.set(_key(challenge.id), json.dumps(payload), ex=TTL_SECONDS)
    return challenge


async def consume(
    redis: Redis, challenge_id: str, user_id: UUID, purpose: Purpose
) -> FaceChallenge | None:
    """The challenge, once — and only for the person and purpose it was for."""
    raw = await redis.getdel(_key(challenge_id))
    if raw is None:
        return None

    data = json.loads(raw)
    if data["user_id"] != str(user_id) or data["purpose"] != purpose:
        return None
    return FaceChallenge(
        id=challenge_id,
        user_id=user_id,
        purpose=purpose,
        actions=data["actions"],
        colours=data["colours"],
        expires_at=datetime.fromisoformat(data["expires_at"]),
    )
