#!/usr/bin/env bash
# Turn a fresh Raspberry Pi OS (desktop) into an IDEN enrolment kiosk.
#
#     sudo ./install.sh --issuer https://id.example.org --image ghcr.io/example/iden-kiosk:latest
#
# Run from this directory. Safe to run again: it rewrites what it installed.
# Afterwards, reboot; the screen asks for the pairing code from the dashboard.
set -euo pipefail

issuer=""
image=""
user="${SUDO_USER:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issuer) issuer="$2"; shift 2 ;;
    --image) image="$2"; shift 2 ;;
    --user) user="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ -n "$issuer" && -n "$image" ]] || { echo "--issuer and --image are required" >&2; exit 2; }
[[ -n "$user" ]] || { echo "--user: the desktop user the screen runs as" >&2; exit 2; }
here="$(cd "$(dirname "$0")" && pwd)"
home="$(getent passwd "$user" | cut -d: -f6)"

echo "==> Packages"
apt-get update -qq
apt-get install -y -qq v4l-utils curl
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
command -v chromium >/dev/null || command -v chromium-browser >/dev/null \
  || apt-get install -y -qq chromium

echo "==> Kiosk server"
install -d /opt/iden-kiosk
install -m 0644 "$here/compose.yml" /opt/iden-kiosk/compose.yml
install -m 0755 "$here/camera.sh" "$here/display.sh" /opt/iden-kiosk/
# camera.conf is tuned per site; keep an edited one.
[[ -e /opt/iden-kiosk/camera.conf ]] || install -m 0644 "$here/camera.conf" /opt/iden-kiosk/
printf 'KIOSK_ISSUER=%s\nKIOSK_IMAGE=%s\n' "$issuer" "$image" > /opt/iden-kiosk/.env
(cd /opt/iden-kiosk && docker compose pull --quiet && docker compose up -d)

echo "==> Camera, screen, updates"
install -m 0644 "$here/iden-kiosk-camera@.service" "$here/iden-kiosk-display.service" \
  "$here/iden-kiosk-update.service" "$here/iden-kiosk-update.timer" /etc/systemd/system/
install -m 0644 "$here/99-iden-kiosk-camera.rules" /etc/udev/rules.d/
systemctl daemon-reload
udevadm control --reload
udevadm trigger --subsystem-match=video4linux --action=add
systemctl enable --now iden-kiosk-display.service iden-kiosk-update.timer
# No screen blanking: an idle kiosk still has to show how to use it.
command -v raspi-config >/dev/null && raspi-config nonint do_blanking 1

echo "==> Browser"
# The camera is allowed for the kiosk page without a prompt, and for nothing else.
install -d /etc/chromium/policies/managed
install -m 0644 "$here/chromium-policy.json" /etc/chromium/policies/managed/iden-kiosk.json
install -m 0755 "$here/browser.sh" /opt/iden-kiosk/browser.sh
autostart="$home/.config/labwc/autostart"
install -d -o "$user" -g "$user" "$(dirname "$autostart")"
touch "$autostart"
grep -q iden-kiosk/browser.sh "$autostart" || echo "/opt/iden-kiosk/browser.sh &" >> "$autostart"
chown "$user:$user" "$autostart"
# Sign the desktop user in automatically, so the screen comes up after a power cut.
command -v raspi-config >/dev/null && raspi-config nonint do_boot_behaviour B4

echo
echo "Done. Reboot, then pair the kiosk with the code from IDEN → Administration → Kiosks."
echo "Tune the camera first: v4l2-ctl -d /dev/video0 --list-ctrls-menus, then edit"
echo "/opt/iden-kiosk/camera.conf and replug the camera."
