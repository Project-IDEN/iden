#!/usr/bin/env bash
# Hold a camera at the settings in camera.conf. Run by iden-kiosk-camera@.service
# for each camera, with its device name (video0), for as long as it is plugged in.
#
# Setting them once is not enough. Every time Chromium opens a camera it resets
# all of its controls to their defaults, which switches automatic white balance,
# exposure and focus back on (ResetUserAndCameraControlsToDefault, in Chromium's
# V4L2 capture code). So the values are read back every second and set again when
# they drift — and when camera.conf changes, which makes tuning live.
set -uo pipefail

device="/dev/${1:?usage: camera.sh video0}"
conf=/opt/iden-kiosk/camera.conf

# A UVC camera has a metadata node beside its capture node; it has no controls.
v4l2-ctl -d "$device" --list-ctrls 2>/dev/null | grep -q . || exit 0

controls=""  # the ones this camera accepted, comma-separated
expected=""  # how they read back after the last apply

# `name=value` lines, comments and spaces removed, in file order: auto_exposure
# has to be manual before an exposure time is accepted.
wanted() { sed -e 's/#.*//' -e 's/[[:space:]]//g' "$conf" 2>/dev/null | grep '=' || true; }

read_back() { [[ -z "$controls" ]] || v4l2-ctl -d "$device" --get-ctrl="$controls" 2>/dev/null; }

apply() {
  local report="$1" name value accepted=()
  while IFS='=' read -r name value; do
    if v4l2-ctl -d "$device" --set-ctrl="$name=$value" 2>/dev/null; then
      accepted+=("$name")
    elif $report; then
      echo "$device has no control $name, or refused $value; see: iden-kiosk camera"
    fi
  done < <(wanted)
  controls="$(IFS=,; echo "${accepted[*]}")"
  expected="$(read_back)"
}

stamp=""
while [[ -e "$device" ]]; do
  now="$(stat -c %y "$conf" 2>/dev/null)"
  if [[ "$now" != "$stamp" ]]; then
    stamp="$now"
    apply true
    echo "$device: holding ${controls:-nothing} from camera.conf"
  elif [[ -n "$controls" && "$(read_back)" != "$expected" ]]; then
    apply false
    echo "$device: set camera.conf again after the camera was reset"
  fi
  sleep 1
done
