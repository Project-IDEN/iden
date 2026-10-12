"""The capture protocol: what the person was asked to do in each frame.

The provider issues a challenge and expands it into one step per frame; the
camera side follows the same expansion. A frame is only ever judged against the
step it was captured for.
"""

from typing import Literal, get_args

Action = Literal["turn_left", "turn_right", "look_up", "look_down"]
FlashColour = Literal["red", "green", "blue"]

CENTRE = "center"
FLASH_PREFIX = "flash:"

ACTIONS: tuple[str, ...] = get_args(Action)
COLOURS: tuple[str, ...] = get_args(FlashColour)

# The channel each colour lifts, in OpenCV's BGR order.
CHANNEL = {"blue": 0, "green": 1, "red": 2}


def is_valid(step: str) -> bool:
    if step == CENTRE or step in ACTIONS:
        return True
    return step.startswith(FLASH_PREFIX) and step[len(FLASH_PREFIX) :] in COLOURS


def flash_colour(step: str) -> str | None:
    return step[len(FLASH_PREFIX) :] if step.startswith(FLASH_PREFIX) else None


def is_frontal(step: str) -> bool:
    """Frames where the person should be looking straight at the camera."""
    return step == CENTRE or flash_colour(step) is not None
