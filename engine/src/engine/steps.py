"""The capture protocol: what the person was asked to do in each frame.

The provider issues a challenge and expands it into one step per frame; the
camera side follows the same expansion. A frame is only ever judged against the
step it was captured for.
"""

from typing import Literal, get_args

Action = Literal["turn_left", "turn_right", "look_up", "look_down"]

CENTRE = "center"

ACTIONS: tuple[str, ...] = get_args(Action)


def is_valid(step: str) -> bool:
    return step == CENTRE or step in ACTIONS
