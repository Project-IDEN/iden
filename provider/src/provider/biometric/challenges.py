"""What a person is asked to do in front of the camera, chosen at random.

Enrolment asks for two head movements: a recording made before the challenge
was issued cannot contain the right ones in the right order. Sign-in asks for
none — only frames looking straight ahead, judged by the anti-spoofing model —
because it happens every day and enrolment once. Each challenge is good for one
capture: `consume` deletes it as it reads it.
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

CENTRE_FRAMES = 3
FRAMES_PER_ACTION = 3

# An enrolment capture takes about twenty seconds; this allows for reading the
# instructions.
TTL_SECONDS = 120

_random = secrets.SystemRandom()


@dataclass(frozen=True)
class FaceChallenge:
    id: str
    user_id: UUID
    purpose: Purpose
    actions: list[str]
    expires_at: datetime

    @property
    def steps(self) -> list[str]:
        """One entry per frame the camera must send, in order."""
        return ["center"] * CENTRE_FRAMES + [
            action for action in self.actions for _ in range(FRAMES_PER_ACTION)
        ]


def _key(challenge_id: str) -> str:
    return f"face-challenge:{hash_token(challenge_id)}"


async def issue(redis: Redis, user_id: UUID, purpose: Purpose) -> FaceChallenge:
    challenge = FaceChallenge(
        id=generate_token(),
        user_id=user_id,
        purpose=purpose,
        actions=_random.sample(ACTIONS, 2) if purpose == "enrol" else [],
        expires_at=datetime.now(UTC) + timedelta(seconds=TTL_SECONDS),
    )
    payload = {
        "user_id": str(user_id),
        "purpose": purpose,
        "actions": challenge.actions,
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
        expires_at=datetime.fromisoformat(data["expires_at"]),
    )
