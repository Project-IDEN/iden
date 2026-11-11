# Plan: blink and smile in the face enrolment challenge

Branch `feat/enrol-blink-smile`, from `dev` at `3e19428`. This covers kiosk enrolment only. Face sign-in, its challenge, its engine path and its UI are left exactly as they are.

## What the code does today

### Provider

- **`biometric/challenges.py`**
  - `issue()` draws `actions=_random.sample(ACTIONS, 2)` for `purpose == "enrol"` and `[]` for `"login"`. `_random` is already a `secrets.SystemRandom`, and `sample` already gives two distinct actions.
  - `ACTIONS` is the four head movements.
  - `FaceChallenge.steps` expands to 3 × `center`, then 3 frames per action (`CENTRE_FRAMES`, `FRAMES_PER_ACTION`): 9 frames in total.
  - The actions are stored in Redis (`face-challenge:<hash>`).
- **`biometric/service.py`**
  - `_matches_challenge` only compares the frame count to `len(challenge.steps)` and raises `BadFrames`, which is 422 `invalid_frames`.
  - `enrol()` sends `challenge.steps` through to `engine.enroll`. Then:
    - `usable=false` → 422 `poor_capture`.
    - `live=false` → 422 `not_live`, with `details.failed` drawn from `anti_spoofing`, `actions` and `consistent`.
  - A failed head movement is `failed: ["actions"]`.
- **`biometric/schemas.py`**
  - `Step = Literal["center", "turn_left", …]` is shared by the sign-in `FaceChallengeResponse` and by `KioskChallengeResponse`, which subclasses it.
- **`/biometric/enroll/challenge` and `/biometric/enroll` in `biometric/routes.py`**
  - The descriptions say "two head movements".
  - `deps.read_frames` caps the request at 16 frames (`MAX_FRAMES`).
- **`engine_client.py`**
  - Posts `meta={"steps": [...]}`. It doesn't know the action names, so new ones pass straight through.

### Engine

- **`steps.py`:** `Action` holds the four movements, and `is_valid` rejects any other step with a 400.
- **`pipeline.analyse`:**
  - Every frame is detected with SCRFD, which gives a box and **5 landmarks**.
  - `pose.estimate` turns those into yaw and pitch proxies.
  - Good centre frames give:
    - the reference embedding,
    - anti-spoofing (`pad.live_probability` on the centre frames),
    - the head-pose baseline.
  - `liveness.actions` checks that each requested movement's peak change from the baseline reaches `turn_delta` or `pitch_delta` (`[liveness]`).
  - `liveness.consistency` compares every frame with the reference (`consistency_frontal` for centre frames, `consistency_turned` for the rest).
  - `enroll()` stores the best ≤ 5 **centre** frames' embeddings.
- **`verify()`** (sign-in) runs the same `analyse` on three centre frames.
- **`models.toml` + `manifest.py` + `runtime.py`:**
  - Each model is a `ModelFile(file, sha256)`. `runtime._session` refuses a file whose SHA-256 differs.
  - `[[source]]` lists the archives `scripts/fetch_models.py` downloads. Each archive is verified by SHA-256, and then each extracted file is too.
  - `buffalo_l.zip` is already pinned (`80ffe37d…`) and holds `2d106det.onnx`: `f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf`, input `1×3×192×192`, output `1×212`, normalisation inside the graph.
- **What the 5 landmarks can't tell:** whether an eye is open or a mouth is smiling. That is why the 106-point model is needed.
- **Thresholds:**
  - `[policy]`: `live_threshold`, `live_fraction`.
  - `[liveness]`: movement and consistency thresholds.
  - `[recognizer]`: `match_threshold`, marked "NOT CALIBRATED".

### Kiosk client

- **`ui/capture-sequence.ts`:**
  - `guidedCapture` follows MediaPipe's pose (`head-tracker.ts`: yaw and pitch from the mesh) and takes a movement's frames once the head has gone far enough. A step that is never seen throws `StepTimeout(step)` after `ACTION_MAX_MS = 8 s`.
  - `timedCapture` is the fallback with no tracker, which just waits.
  - Each movement: 2 s "Next: …", a "go" tone, the frames, a "done" chime, at least 5 s per movement.
- **`ui/head-tracker.ts`:** creates the `FaceLandmarker` **without** blendshapes, and exposes only `latest(): Pose`.
- **`ui/face-capture.tsx`:**
  - `MOVES` holds the label and icon per movement.
  - A `StepTimeout` becomes "We couldn't see your face…" for `center`, and "We didn't see that movement. Start again, and keep going until you hear the chime." for any other step.
- **`ui/capture-problems.ts`:** advice for `poor_capture` reasons. It doesn't change.
- **`screens/enrol-problems.ts`:** the `not_live` advice for `actions` reads "Turn your head the way each arrow shows…".

### Kiosk server

- `MAX_FRAMES = 16` in `kiosk_server/routes.py`, matching the provider's 16 and the engine's `engine_max_frames = 16`.

### Tests that assume the old action set

- **`engine/tests/test_steps.py::test_unknown_steps_are_not`:** lists `"smile"` as an invalid step. This has to change.
- **`provider/tests/test_biometric.py:573`:** checks two distinct actions and the 3 + 3 + 3 expansion. It is still true with the new pool, so it stays unchanged.
- **`engine/tests/test_pipeline.py`:** uses `turn_left` + `look_up` explicitly. It is still valid and stays unchanged.
- **`provider/tests/test_tds_engine_integration.py`:** its docstring mentions "two random head movements" and the four movement files under `enrol/`. Its real-capture test reads `<step>_<n>.jpg` for whatever steps were drawn, so a drawn `blink` or `smile` needs those files too. The test and docstring are updated.
- **Kiosk Playwright (M07):** no case checks the movement texts. TC-209 (timed path, dark) is refused as `poor_capture` before any action is judged, so it shouldn't be affected. This will be checked by running it.

## Decisions

1. **Frame counts stay at 3 per step (9 in total, cap 16).**
   - A blink needs open, then closed, then open: exactly 3 frames when the kiosk picks them.
   - A smile needs a neutral frame, the peak, and the smile held. The neutral reference also comes from the centre frames.
   - So no step needs more than 3.
2. **Provider.**
   - `ACTIONS` becomes the 6 actions, still drawn with `_random.sample(ACTIONS, 2)` from `secrets.SystemRandom`.
   - Centre frames stay first, and sign-in still gets `[]`.
   - The kiosk response gets its own `EnrolStep` literal (the 7 step names). The sign-in `FaceChallengeResponse.steps` keeps the old `Step` literal, so sign-in's API schema doesn't change.
   - The route descriptions are updated.
   - Error contract: a missed blink or smile is the engine's `actions` check failing, so it is 422 `not_live` with `failed: ["actions"]`, as a missed head movement is. A wrong frame count is still 422 `invalid_frames`.
3. **Engine.**
   - New `[landmarks]` model, `2d106det.onnx`, pinned by SHA-256 and added to `buffalo_l.zip`'s `extract`. `runtime.Models.landmarker` loads it.
   - New `landmarks.py`: InsightFace's crop (box centre, 1.5 × the box, 192 px), batched.
   - New `expression.py`:
     - Eye openness: the height over the width of each eye's outline after levelling the eye line, averaged over both eyes.
     - Mouth width and corner lift, both over the inter-ocular distance.
   - New checks in `liveness.py`. The head-movement maths is untouched.
     - **blink:** the frame where the eyes are most closed must be below `blink_closed_ratio` × the person's open-eye baseline (the median of the centre frames). There must be a frame before it and a frame after it at or above `blink_open_ratio` × that baseline.
     - **smile:** the largest (width gain + corner-lift gain) over the person's neutral (the median of the centre frames) must be at least `smile_gain`.
   - The new thresholds go in `[policy]`, marked "NOT CALIBRATED - tune on team captures".
   - **Enrolment only** (`enroll()`, or any capture that contains a blink or smile step):
     - The 106-point model runs on every frame that has a face.
     - Anti-spoofing is judged only on centre frames whose eyes are open (≥ `blink_open_ratio` × baseline).
     - Stored templates are chosen only from those frames.
   - **Sign-in:** a `verify()` with centre steps only, which is all a sign-in ever sends, doesn't run the new model, and follows exactly today's code path.
   - The consistency check is unchanged and still covers every frame, blink and smile frames included (with the existing non-centre bar).
   - `version` is **not** bumped. Stored templates come from the recogniser only, which doesn't change, so existing enrolments stay comparable. Bumping it would force everyone to enrol again for nothing. A comment in `models.toml` says so.
4. **Kiosk client.**
   - `head-tracker.ts` turns on `outputFaceBlendshapes` and exposes `expression(): {blink, smile}`, the mean of `eyeBlinkLeft/Right` and of `mouthSmileLeft/Right`.
   - New `capture-actions.ts`, pure and with no DOM: a picker fed one reading at a time.
     - **blink:** the first open frame, then the most-closed frame (replaced while the eyes close further), then the first open frame after it.
     - **smile:** a neutral frame, the peak smile, then a frame with the smile held at least 400 ms after it first crossed.
   - `guidedCapture` uses the picker for `blink` and `smile`. It keeps the same prepare, tone, chime and minimum time as a movement, and throws `StepTimeout` after 8 s.
   - Labels "Blink slowly" (eye icon) and "Smile" (smile icon), and timeout texts:
     - "We didn't see you blink. Start again, and blink slowly."
     - "We didn't see a smile. Start again, and smile until you hear the chime."
   - The `not_live` `actions` advice becomes general.
   - The timed path (no tracker) takes the frames on the same timer as a movement. It can't pick frames, so a blink is caught only by chance. That is acceptable for a fallback, and it is documented.
5. **Tests.**
   - **Provider:** the 6-action pool, distinctness, centre first, sign-in without actions, and a wrong frame count on a blink or smile step → 422 `invalid_frames`.
   - **Engine:** synthetic-landmark unit tests for blink, smile and the open-eye anti-spoofing filter.
   - **Engine, real images:** tests on `engine/tests/data/actions/<action>_<n>.jpg`, skipped while that folder is missing.
   - **Engine script:** `engine/scripts/capture_actions.py` for the webcam capture.
   - **Kiosk client:** unit tests for the picker, using Node's built-in runner (Node 24 strips the types), so there is no new dependency.
6. **Runs.**
   - The provider, engine and kiosk server suites in the Linux container.
   - The kiosk Playwright suite against the rebuilt local stack.
