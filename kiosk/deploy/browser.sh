#!/usr/bin/env bash
# The kiosk screen: Chromium, full screen, on the kiosk app. Run by
# iden-kiosk-browser.service in the desktop user's session, which restarts it
# if it exits; `iden-kiosk start` and `iden-kiosk stop` drive that service.
set -euo pipefail

url=http://localhost:8080
# Its own profile: a Chromium the desktop user opened themselves would
# otherwise take over the launch and ignore --kiosk.
profile="$HOME/.local/share/iden-kiosk/chromium"
browser="$(command -v chromium || command -v chromium-browser)" \
  || { echo "Chromium is not installed." >&2; exit 1; }

# A service does not inherit the desktop's environment, so find its display:
# Wayland on current Raspberry Pi OS, X11 on older desktops.
if [[ -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
  for socket in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/wayland-*; do
    [[ -S "$socket" ]] && { export WAYLAND_DISPLAY="${socket##*/}"; break; }
  done
  [[ -n "${WAYLAND_DISPLAY:-}" || ! -S /tmp/.X11-unix/X0 ]] || export DISPLAY=:0
fi
[[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] \
  || { echo "No desktop session to show the kiosk on." >&2; exit 1; }

# The server may still be starting after a boot.
until curl -fsS -o /dev/null "$url/api/state"; do sleep 2; done

# Killed rather than closed, Chromium offers to restore the last session.
# Tell it the last exit was a clean one.
preferences="$profile/Default/Preferences"
[[ -f "$preferences" ]] && sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "$preferences"

exec "$browser" \
  --kiosk "$url" \
  --user-data-dir="$profile" \
  --ozone-platform-hint=auto \
  --no-first-run \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  --password-store=basic
