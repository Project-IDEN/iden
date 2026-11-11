astronaut.jpg — Eileen Collins, NASA portrait; public domain. Taken from the
scikit-image sample data (`skimage.data.astronaut`).

sunita_williams.jpg — Sunita Williams, NASA official portrait; public domain
("This file is in the public domain in the United States because it was solely
created by NASA."). Source: https://commons.wikimedia.org/wiki/File:Sunita_Williams.jpg
(original https://upload.wikimedia.org/wikipedia/commons/c/cb/Sunita_Williams.jpg,
2400×3000). Cropped around the face (5.5 × the eye distance) and resized to
512×512, JPEG quality 90, so it is framed like a kiosk capture. Used by
provider/tests/test_tds_engine_integration.py as "a different person".

actions/ (optional, git-ignored, never committed) — a consenting team member's
own capture: `<step>_<n>.jpg`, three frames each for `center` and the six
actions (`turn_left`, `turn_right`, `look_up`, `look_down`, `blink`, `smile`),
written by `uv run python -m scripts.capture_actions` from a webcam. Read by
tests/test_actions_real.py and provider/tests/test_tds_engine_integration.py;
both skip without it. A still photograph cannot blink, smile or move.
