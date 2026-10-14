# Tuning the kiosk camera

How to set up the webcam on a [kiosk](kiosks.md) so that enrolment works first time, in the light
the kiosk actually has. Nothing here assumes a particular camera: every camera names and scales its
settings differently, so the guide shows how to find out what yours has, and what to do with it.

Budget **about twenty minutes**, with the kiosk standing where it will be used, at the time of day
it will be used. Settings tuned on a desk by a window are wrong under the ceiling lights of a lobby.

## Why the camera matters

When someone enrols, the kiosk takes 9 frames and the engine judges them twice.

**Is the picture good enough?** In every frame it looks for one face, large enough, sharp enough,
neither too dark nor too bright. When it is not, the person is told what to fix, and nothing is
decided. These failures are `poor_capture`.

**Is it a live person?** Three checks, and every one must pass: an anti-spoofing model judges the
straight-ahead frames, the head follows two movements drawn at random, and the face is the same
person throughout. These failures are `not_live`. The camera cannot break them outright, but a dark,
grainy or blurred picture makes the anti-spoofing model less sure and the landmarks the movements
are measured from less steady.

A webcam left on its automatic settings can get in the way:

| Automatic setting | What it does to a capture |
|---|---|
| **Exposure** | Darkens the face against a bright background, and in dim light slows the frame rate, which blurs a moving head. |
| **Focus** | Can hunt in the middle of a capture, blurring the frames it hunts across. |
| **White balance** | Harmless to the engine. Fix it only if skin looks orange or blue on screen and keeps shifting. |

So the goal is: **fix exposure and focus at values that suit the kiosk's light**, and let nothing
that matters change by itself during a capture.

## How the settings are applied

The settings live in **`/opt/iden-kiosk/camera.conf`** on the Pi, one `name=value` per line.
A small service holds every camera at those values for as long as it is plugged in.

It does more than set them once. Each time Chromium opens a camera, it resets every one of the
camera's settings to the factory default, which switches automatic white balance, exposure and
focus back on. So the service reads the settings back every second, and puts them back whenever
they have changed. You can see it happen:

```bash
iden-kiosk logs camera
```

```text
/dev/video0: holding auto_exposure,exposure_time_absolute,focus_automatic_continuous,focus_absolute from camera.conf
/dev/video0: set camera.conf again after the camera was reset
```

The second line appears when the kiosk app opens the camera. It is the service doing its job.

It also means **a change to `camera.conf` applies within a second of saving it**, to the picture on
screen. That is how you tune: edit, save, look at the screen.

## Choosing a camera

Any USB webcam that works on Linux will run the kiosk. For enrolment to be dependable, look for one
whose settings can be fixed by hand:

| | Want | Why |
|---|---|---|
| **Exposure** | Can be set manually | A face lit the same in every frame, and a frame rate that holds in dim light. |
| **White balance** | Anything | Automatic is fine. |
| **Focus** | Fixed focus, or autofocus that can be switched off | Fixed focus is fine at arm's length, and nothing to tune. |
| **Resolution** | 720p or more | The kiosk captures at 640 × 480; more is not needed. |
| **Field of view** | Ordinary (about 60–80°) | A very wide lens makes the face small at arm's length. |

To check a camera before you buy a batch, plug it into any Linux machine and run
`v4l2-ctl -d /dev/video0 --list-ctrls-menus` (from the `v4l-utils` package): it lists exactly the
settings described below.

## 1. See what your camera has

On the Pi:

```bash
iden-kiosk camera
```

It lists every camera and every setting it has, with the range and the current value. Part of a
typical listing — yours will differ:

```text
== /dev/video0: USB 2.0 Camera

User Controls

                     brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
           power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=1 value=1
				0: Disabled
				1: 50 Hz
				2: 60 Hz
      white_balance_temperature 0x0098091a (int)    : min=2800 max=6500 step=1 default=4600 value=4600 flags=inactive

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
				1: Manual Mode
				3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=1 max=5000 step=1 default=157 value=157 flags=inactive
     exposure_dynamic_framerate 0x009a0903 (bool)   : default=0 value=1
```

Note three things for each setting you will use: its **name** (first column), its **range**
(`min`, `max`), and its **default**. `flags=inactive` means it has no effect at the moment, usually
because the matching automatic mode is on.

### The names are not the same everywhere

The same setting has a different name on older Linux kernels. Use whichever your camera lists:

| Setting | Name on current Raspberry Pi OS | Name on older kernels |
|---|---|---|
| Automatic white balance | `white_balance_automatic` | `white_balance_temperature_auto` |
| White balance temperature | `white_balance_temperature` | `white_balance_temperature` |
| Exposure mode | `auto_exposure` | `exposure_auto` |
| Exposure time | `exposure_time_absolute` | `exposure_absolute` |
| Keep the frame rate in dim light | `exposure_dynamic_framerate` | `exposure_auto_priority` |
| Autofocus | `focus_automatic_continuous` | `focus_auto` |
| Focus distance | `focus_absolute` | `focus_absolute` |
| Mains frequency | `power_line_frequency` | `power_line_frequency` |

A setting that is missing from the list is a setting the camera does not have. Skip its step.

## 2. Get ready to tune

1. Put the kiosk where it will stand, in the light it will have. Switch on the room's usual lights;
   draw the blinds the way they usually are.
2. Enter kiosk mode, so the camera's picture is on screen: `iden-kiosk start`, then touch the idle
   screen to open the QR scanner. Its preview
   shows the live picture.
3. From your laptop, open a terminal on the Pi over SSH, and open the settings file:

    ```bash
    iden-kiosk camera edit
    ```

4. Stand — or have someone stand — where a person enrolling would: in front of the screen, about
   an arm's length away.

Each step below uncomments lines in `camera.conf`, sets a value, saves, and looks at the screen. In
`nano`, save with Ctrl+O then Enter, and keep the file open. Settings are applied in the order they
appear in the file, so keep each automatic switch above the value it unlocks.

## 3. Mains frequency

Fluorescent and many LED lights flicker at twice the mains frequency, which shows as rolling bands
in the picture. Tell the camera which mains you have:

```ini
power_line_frequency=1    # 1 = 50 Hz (most of the world), 2 = 60 Hz (the Americas, parts of Asia)
```

Check your camera's menu values in `iden-kiosk camera` — they are almost always these two.

## 4. Exposure

Switch automatic exposure off, then choose an exposure time:

```ini
auto_exposure=1               # Manual Mode — check the number in your camera's menu
exposure_time_absolute=200
exposure_dynamic_framerate=0
```

The exposure time is in units of **100 microseconds**, so `200` is 20 ms. Change it in steps,
saving each time, until the face is clearly lit: skin looks like skin, the eyes are visible, and
nothing on the face is washed out to white.

- **Stay at or below `333`** (33 ms, one frame at 30 frames a second). Longer, and the camera drops
  its frame rate, which blurs the head movements.
- **Prefer the flicker-free values.** On 50 Hz mains, multiples of `100`: `100`, `200`, `300`. On
  60 Hz, multiples of `83`: `83`, `167`, `250`, `333`.
- **Still too dark at `333`?** Raise `gain` if the camera has it, a little at a time — it brightens
  the picture without slowing the shutter, at the cost of some grain. Better still, add light in
  front of the person.

`exposure_dynamic_framerate=0` stops the camera slowing down by itself in dim light.

!!! note "When the camera has no manual exposure"
    Leave exposure on automatic. Some cameras offer only `exposure_time_absolute` without a mode, or
    a `backlight_compensation` setting: set `backlight_compensation=0`, so a bright background does
    not darken the face.

## 5. White balance (optional)

The engine does not depend on colour, so automatic white balance is fine and most kiosks can skip
this step. Fix it only if skin on screen looks orange or blue and keeps shifting as people come and
go. Switch automatic white balance off, then choose a colour temperature in kelvin:

```ini
white_balance_automatic=0
white_balance_temperature=4600
```

Pick the value at which skin looks natural on screen under the room's light — neither orange nor
blue. A starting point by kind of light:

| Light | Start at |
|---|---|
| Warm white bulbs, tungsten | `3000`–`3500` |
| Office LED or fluorescent, neutral white | `4000`–`4600` |
| Cool white LED, daylight from a window | `5000`–`6500` |

Stay within the camera's range from `iden-kiosk camera`. A value a few hundred kelvin off is fine.

## 6. Focus

**Fixed-focus cameras** — no `focus_` settings in the list — need nothing. Skip this step.

**Autofocus cameras:** switch autofocus off, then find the focus value for an arm's length:

```ini
focus_automatic_continuous=0
focus_absolute=30
```

The scale is the camera's own; there is no standard. Look at the range in `iden-kiosk camera`,
start in the lower part of it, and change it in steps of five or ten until the eyes and eyelashes of
someone standing at the kiosk are sharp. Which direction is closer differs between cameras.

## 7. Test it

Enrol a test account a few times — your own, or one made for the purpose. Have a few different
people do it if you can: different skin tones, glasses, heights. Each person creates the QR code in
the dashboard under **Security → Enrol at a kiosk**.

### Reading the results

While you test, follow the kiosk server's log in your SSH terminal:

```bash
iden-kiosk logs
```

Each enrolment the engine turns down is logged with why. Nothing about the person is logged — only
what the engine made of the picture. Shortened, the lines look like this:

```json
{"event": "Enrolment refused", "status": 422, "code": "poor_capture", "details": {"reasons": ["too_dark"]}}
{"event": "Enrolment refused", "status": 422, "code": "not_live", "details": {"failed": ["actions"]}}
```

The same failures, without the details, are on the kiosk's page in the dashboard.

| Logged | What it means | What to change |
|---|---|---|
| `too_dark` | The face is too dark to judge. | Raise `exposure_time_absolute` or `gain`, or add light in front. |
| `too_bright` | The face is washed out. | Lower `exposure_time_absolute` or `gain`. Move the kiosk out of direct sun. |
| `blurred` | The face is not sharp. | Focus (step 6). A long exposure also blurs moving heads: stay at or below `333`. |
| `too_small` | Too little face: the person was too far away, or the lens is very wide. | The kiosk app already asks for an arm's length; a narrower camera, or the camera closer to where people stand. |
| `no_face`, `off_angle` | No face found, or not looking straight ahead. | Usually the person, not the camera. If it is constant, check the camera's height and angle. |
| `out_of_frame` | The face is at the edge of the picture, or so close it nearly fills it: too little around it for the anti-spoofing model to judge. | Usually the person. If it is constant, the camera is aimed off where people stand, or the lens is too narrow. |
| `multiple_faces` | A second face is in view. | Something behind the kiosk: a poster, a mirror, a queue. |
| `not_live`, `anti_spoofing` | The anti-spoofing model judged the face not live. | Usually poor light or a noisy picture: more even light on the face, less `gain`. |
| `not_live`, `actions` | The head movements were not seen. | Usually the person: they did not turn far enough, or turned back before the frames were taken. The kiosk asks them to hold each position. |
| `not_live`, `consistent` | The face did not look like the same person throughout. | Someone else stepped in, or the frames were very poor. |

A tuned kiosk passes nearly every first attempt from people who follow the instructions. A failure
now and then is normal; the person is told what to fix and can try again.

## Several cameras

`camera.conf` applies to every camera plugged into the kiosk. With two attached, choose which one
the kiosk uses in the dashboard (the kiosk's **Camera** setting, matched against the camera's name),
and tune the file for that one.

## Changing the camera later

A different model of camera needs tuning again from step 1: its settings and their scales are its
own. Replace it with the kiosk in kiosk mode, then `iden-kiosk camera` to see the new one, and
`iden-kiosk camera edit` to adjust. The service picks a new camera up as soon as it is plugged in.

Tuning the camera is separate from calibrating the engine's match threshold, which measures how
alike two faces must be to count as the same person on your cameras. That is in
[Calibrate the threshold](biometric-engine.md#calibrate-the-threshold).
