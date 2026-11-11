"""The capture protocol: what the person was asked to do in each frame.

The provider issues a challenge and expands it into one step per frame; the
camera side follows the same expansion. A frame is only ever judged against the
step it was captured for.
"""

from typing import Literal, get_args

Movement = Literal["turn_left", "turn_right", "look_up", "look_down"]
# Judged on the 106-point landmarks rather than head pose; enrolment only.
Expression = Literal["blink", "smile"]
Action = Movement | Expression

CENTRE = "center"

MOVEMENTS: tuple[str, ...] = get_args(Movement)
EXPRESSIONS: tuple[str, ...] = get_args(Expression)
ACTIONS: tuple[str, ...] = MOVEMENTS + EXPRESSIONS


def is_valid(step: str) -> bool:
    return step == CENTRE or step in ACTIONS
