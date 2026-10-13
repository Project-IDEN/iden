#!/usr/bin/env bash
# The kiosk screen: Chromium, full screen, on the kiosk server. Started by the
# desktop session (labwc autostart) and restarted whenever it exits.
set -u

browser=$(command -v chromium || command -v chromium-browser)
url=http://localhost:8080

# The server may still be starting after a boot.
until curl -fsS -o /dev/null "$url/api/state"; do sleep 2; done

while true; do
  "$browser" \
    --kiosk "$url" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --check-for-update-interval=31536000 \
    --password-store=basic \
    --ozone-platform=wayland
  sleep 2
done
