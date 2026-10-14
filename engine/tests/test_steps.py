from engine.steps import is_valid


def test_known_steps_are_valid():
    for step in ("center", "turn_left", "turn_right", "look_up", "look_down"):
        assert is_valid(step)


def test_unknown_steps_are_not():
    for step in ("", "smile", "flash:red", "CENTER"):
        assert not is_valid(step)
