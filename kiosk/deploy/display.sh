#!/usr/bin/env bash
# Full brightness: the colour flashes are the screen lighting the face, and a
# dimmed panel lights it too little to measure.
for backlight in /sys/class/backlight/*; do
  [[ -e "$backlight/max_brightness" ]] && cat "$backlight/max_brightness" > "$backlight/brightness"
done
exit 0
