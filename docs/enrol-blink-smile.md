# Blink and smile in face enrolment

Face enrolment at a kiosk now asks for two actions drawn at random from six: the four head movements (`turn_left`, `turn_right`, `look_up`, `look_down`), `blink` and `smile`. Any two can come up, for example `look_up` + `blink`, `smile` + `turn_left`, or `blink` + `smile`. Face sign-in hasn't changed: it still asks for three frames looking straight ahead and no action.

The plan, with the code as it was read before the change, is in [enrol-blink-smile-plan.md](enrol-blink-smile-plan.md).

## What changed

### The challenge (provider)

`provider/src/provider/biometric/challenges.py`

- `ACTIONS` holds the six actions.
- An enrolment draws `ACTIONS_PER_ENROLMENT = 2` of them with `secrets.SystemRandom().sample`, so the two are always different.
- The steps are always 3 × `center` first, then 3 frames per action: 9 frames, well under the 16-frame cap of the provider, the kiosk server and the engine.
- A sign-in challenge still has no actions.

`biometric/schemas.py`

- The kiosk's challenge response has its own `EnrolStep` type, which adds `blink` and `smile`.
- The sign-in response keeps `Step`, so its API schema is unchanged.

Error contract (unchanged):

| What went wrong | Response |
|---|---|
| A blink or smile the engine didn't see | `422 not_live`, `details.failed: ["actions"]`, the same as a missed head movement |
| The wrong number of frames | `422 invalid_frames` |
| A frame without a face | `422 poor_capture` (`no_face`) |

### The checks (engine)

- **`models.toml` `[landmarks]`:** InsightFace's 106-point model, `2d106det.onnx`, from the same `buffalo_l` pack as the detector and the recogniser.
  - Pinned by SHA-256: `f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf`.
  - Extracted by `scripts/fetch_models.py`.
  - Loaded as `Models.landmarker`, which refuses a file that doesn't match.
  - `version` is not bumped: templates still come from the recogniser alone, so existing enrolments stay valid.
- **`landmarks.py`:** InsightFace's crop (the box's centre, 1.5 × the box, 192 px), batched over the frames.
- **`expression.py`:** three measures per frame, each a ratio, so the distance to the camera doesn't matter:
  - `eye_openness`: the height of each eye's outline over its width, after levelling the eye line, averaged over both eyes.
  - `mouth_width`: corner to corner, in inter-ocular distances.
  - `mouth_lift`: how far the corners sit above the centre of the lips, in inter-ocular distances.
- **`liveness.py`:**
  - **`blink`:** the most-closed frame of the blink step must be below `blink_closed_ratio` × the person's own open-eye openness. That baseline is the median of the three frames looking ahead. A frame before it and a frame after it must be at or above `blink_open_ratio` × that baseline, in capture order. A dip in the first frame, or one that never reopens, fails.
  - **`smile`:** in at least one smile frame, (mouth width − neutral width) + (corner lift − neutral lift) must be at least `smile_gain`. "Neutral" is the median of the frames looking ahead.
  - Head movements are judged exactly as before. The `actions` check passes only if every requested action passes, and its score is the weakest one's (1.0 passes).
- **`pipeline.py`**, at enrolment, and for any capture that contains a blink or smile step:
  - The 106 landmarks are read for every frame that has a face.
  - Anti-spoofing judges only the frames looking ahead whose eyes are open (≥ `blink_open_ratio` × the baseline).
  - The stored templates come only from those frames.
  - The same-face consistency check is unchanged, and still covers every frame, blink and smile frames included.
- **At sign-in** (three frames looking ahead) the 106-point model doesn't run, and the path is the one it was before.
- **The engine never trusts the kiosk:** it judges the frames it is sent, whatever the kiosk's tracker decided.

### The kiosk (client)

- **`ui/head-tracker.ts`:** turns on MediaPipe's `outputFaceBlendshapes` and exposes `expression()`, made of:
  - `blink`: the mean of `eyeBlinkLeft` and `eyeBlinkRight`.
  - `smile`: the mean of `mouthSmileLeft` and `mouthSmileRight`.
- **`ui/capture-actions.ts`:** decides which three frames to send, as the action happens:
  - **blink:** the first open frame; the most-closed frame (replaced while the eyes close further); the first open frame after that.
  - **smile:** a neutral frame; the peak (replaced while the smile grows); a frame with the smile held `SMILE_HOLD_MS` after it began.
- **`ui/capture-sequence.ts`:** a blink or smile has the same rhythm as a head movement:
  - 2 s "Next: …", a tone, the frames, a chime, at least 5 s in all.
  - It fails after 8 s with `StepTimeout`.
  - Without a tracker (the timed path) its frames are taken on the same timer as a movement, so a blink is caught only by chance.
- **`ui/face-capture.tsx`:**
  - Prompts: "Blink slowly." (eye icon) and "Smile." (smile icon).
  - Timeouts: "We didn't see you blink. Start again, and blink slowly." and "We didn't see a smile. Start again, and smile until you hear the chime."
  - The idle text and the `not_live` advice for `actions` (`screens/enrol-problems.ts`) now name all the actions.

## Thresholds and their defaults

None of these is calibrated. Each one in `models.toml` is marked "NOT CALIBRATED - tune on team captures".

The engine's thresholds decide pass or fail. They are in `engine/models.toml` `[policy]`:

| Threshold | Default | Meaning |
|---|---|---|
| `blink_closed_ratio` | `0.6` | Eyes count as closed below this share of the person's own open-eye openness. |
| `blink_open_ratio` | `0.85` | Eyes count as open at or above this share. It applies before and after a blink, and to a frame looking ahead that anti-spoofing judges or that becomes a template. |
| `smile_gain` | `0.1` | How far a smile must move the mouth beyond the person's neutral mouth, in inter-ocular distances: width gain plus corner-lift gain. |

The kiosk's numbers only decide when to take a frame. They are in `kiosk/client/src/ui/capture-actions.ts` and are MediaPipe blendshape scores from 0 to 1:

| Constant | Default | Meaning |
|---|---|---|
| `BLINK_OPEN` | `0.3` | At or below this, the eyes count as open. |
| `BLINK_CLOSED` | `0.55` | At or above this, the eyes count as closed. |
| `SMILE_NEUTRAL` | `0.25` | At or below this, the face counts as neutral. |
| `SMILE_SMILING` | `0.55` | At or above this, the person counts as smiling. |
| `SMILE_HOLD_MS` | `400` | How long a smile must last before its "held" frame is taken. |

## Capturing test images

This is for consenting team members only. The photos are of your face.

From `engine/`, with the models fetched (`uv run python -m scripts.fetch_models`):

```bash
PYTHONUTF8=1 uv run python -m scripts.capture_actions          # --camera 1 for another webcam
```

1. It asks for consent.
2. It guides you, in the terminal, through:
   - looking straight ahead,
   - a slow blink,
   - a neutral face then a smile,
   - the four head movements.
3. For each step it counts down, rings the bell, and records a few seconds.
4. It keeps three frames per step, as the kiosk would, and runs the engine's own check on them. It prints the action score (1.00 passes), anti-spoofing and consistency, and offers to redo a step that failed.

It writes `engine/tests/data/actions/<step>_<n>.jpg`: 21 files, 640×480, unmirrored. The folder is git-ignored. Delete it when you no longer need it.

`PYTHONUTF8=1` is only needed on a Windows machine whose locale isn't UTF-8, where reading `models.toml` otherwise fails.

With the capture in place, these tests stop skipping:

- **`engine/tests/test_actions_real.py`**, 25 tests:
  - each action is seen;
  - all 15 pairs of actions enrol;
  - a blink out of order, open eyes alone, and a straight face are refused;
  - a smile isn't taken for a blink, nor a blink for a smile.
- **`provider/tests/test_tds_engine_integration.py::test_a_real_capture_enrols_encrypted_templates`**, through the real engine (`-m integration`, with the engine running).

## Tuning the thresholds

1. **Collect captures** from several consenting team members, in the light and with the camera the kiosk will use. Use `--out` to keep each person's capture in its own folder, for example `--out tests/data/actions-alice`.
2. **Read the scores.** Three sources give them:
   - `capture_actions` prints them for each step.
   - Every enrolment logs a `Liveness` line with `actions_score` and, per blink and smile step, `expression: {blink: …, smile: …}`. Each is a score where 1.0 passes. The line also has `eyes_open_frontal: n/3`, the number of frames looking ahead that had the eyes open.
   - `pytest tests/test_actions_real.py` on each capture (copy it to `tests/data/actions/`).
3. **Move each threshold so that genuine actions pass with a margin, and near-misses fail:**
   - **Blinks that score just under 1** (a fast blink, a camera that blurs the closed frame): raise `blink_closed_ratio` (towards 0.7), or slow the person down ("Blink slowly." is already the prompt).
   - **A squint that passes:** lower `blink_closed_ratio`.
   - **Frames looking ahead dropped as "closed"** (`eyes_open_frontal` below 3/3 for people who didn't blink): lower `blink_open_ratio` (towards 0.75).
   - **Genuine smiles that score under 1:** lower `smile_gain` (towards 0.07).
   - **Talking or a grimace that passes:** raise `smile_gain`.
4. **Engine changes** take effect when the engine restarts. Its thresholds are read from `models.toml` at start-up.
5. **If the kiosk is the bottleneck,** with frames never taken or the step timing out while the person clearly blinked or smiled, adjust the blendshape constants in `capture-actions.ts` and rebuild the kiosk client. Its unit tests (`pnpm test` in `kiosk/client`) show what each change picks.
6. **Once tuned,** replace "NOT CALIBRATED" with where the values came from: the number of people, the camera and the date.
