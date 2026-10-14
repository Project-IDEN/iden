#!/usr/bin/env bash
# Full brightness: the screen is also a light on the face of the person in
# front of it, which helps the camera in a dim room.
for backlight in /sys/class/backlight/*; do
  [[ -e "$backlight/max_brightness" ]] && cat "$backlight/max_brightness" > "$backlight/brightness"
done
exit 0
