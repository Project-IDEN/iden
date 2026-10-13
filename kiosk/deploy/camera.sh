#!/usr/bin/env bash
# Lock the camera's controls from camera.conf. Run by iden-kiosk-camera@.service
# with the device name, e.g. video0.
set -uo pipefail

device="/dev/${1:-video0}"
conf=/opt/iden-kiosk/camera.conf

# A UVC camera exposes metadata nodes too; only a capture node takes controls.
v4l2-ctl -d "$device" --all 2>/dev/null | grep -q "Video Capture" || exit 0

while IFS='=' read -r name value; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  v4l2-ctl -d "$device" --set-ctrl="$name=$value" 2>/dev/null \
    || echo "camera: $device has no control $name, or refused $value" >&2
done < "$conf"
