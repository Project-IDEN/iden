from engine.steps import flash_colour, is_frontal, is_valid


def test_known_steps_are_valid():
    for step in ("center", "turn_left", "look_down", "flash:red", "flash:blue"):
        assert is_valid(step)


def test_unknown_steps_are_not():
    for step in ("", "smile", "flash:purple", "flash:", "CENTER"):
        assert not is_valid(step)


def test_flash_and_centre_frames_are_frontal():
    assert is_frontal("center")
    assert is_frontal("flash:green")
    assert not is_frontal("turn_right")
    assert flash_colour("flash:green") == "green"
    assert flash_colour("look_up") is None
