from engine.steps import ACTIONS, EXPRESSIONS, MOVEMENTS, is_valid


def test_known_steps_are_valid():
    for step in (
        "center",
        "turn_left",
        "turn_right",
        "look_up",
        "look_down",
        "blink",
        "smile",
    ):
        assert is_valid(step)


def test_unknown_steps_are_not():
    for step in ("", "frown", "wink", "flash:red", "CENTER", "Blink"):
        assert not is_valid(step)


def test_the_actions_are_the_movements_a_blink_and_a_smile():
    assert set(MOVEMENTS) == {"turn_left", "turn_right", "look_up", "look_down"}
    assert set(EXPRESSIONS) == {"blink", "smile"}
    assert ACTIONS == MOVEMENTS + EXPRESSIONS
