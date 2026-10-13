#!/usr/bin/env bash
# Make a Raspberry Pi (Raspberry Pi OS with desktop, 64-bit) an IDEN enrolment
# kiosk. Run from this directory:
#
#     sudo ./install.sh --issuer https://id.example.org --image ghcr.io/<you>/iden-kiosk:latest
#
# It installs the kiosk server and the `iden-kiosk` command, and changes
# nothing about how the Pi starts: the desktop stays a desktop until you run
# `iden-kiosk start`, or `iden-kiosk enable` to enter kiosk mode at every boot.
#
# Options:
#   --issuer URL   IDEN's public address
#   --image REF    the kiosk image (kiosk/build.sh)
#   --user NAME    the desktop user the screen runs as; default: whoever ran sudo
#
# Safe to run again, to change the issuer or image or to upgrade these files.
# A tuned camera.conf is kept.
set -euo pipefail

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

fail() {
  echo "install.sh: $*" >&2
  exit 1
}

issuer=""
image=""
user="${SUDO_USER:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --issuer) issuer="${2:-}"; shift 2 || shift ;;
    --image) image="${2:-}"; shift 2 || shift ;;
    --user) user="${2:-}"; shift 2 || shift ;;
    -h | --help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done

[[ $EUID -eq 0 ]] || fail "run it with sudo."
[[ -n "$issuer" && -n "$image" ]] || usage
[[ "$issuer" =~ ^https?://[^/]+$ ]] \
  || fail "--issuer is IDEN's address with no path or trailing slash, like https://id.example.org"
[[ -n "$user" && "$user" != root ]] || fail "--user: the desktop user the screen runs as."
home="$(getent passwd "$user" | cut -d: -f6)"
[[ -n "$home" ]] || fail "there is no user called $user."
command -v apt-get >/dev/null || fail "this installer is for Raspberry Pi OS or Debian."

here="$(cd "$(dirname "$0")" && pwd)"
target=/opt/iden-kiosk

echo "==> Packages"
apt-get update -qq
apt-get install -y -qq v4l-utils curl jq >/dev/null
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  apt-get install -y -qq chromium >/dev/null
fi
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
docker compose version >/dev/null 2>&1 \
  || fail "Docker is installed without the Compose plugin. Install docker-compose-plugin."

echo "==> Kiosk server"
install -d "$target"
install -m 0644 "$here/compose.yml" "$target/"
install -m 0755 "$here/browser.sh" "$here/camera.sh" "$here/display.sh" \
  "$here/autostart.sh" "$target/"
[[ -e "$target/camera.conf" ]] || install -m 0644 "$here/camera.conf" "$target/"
printf 'KIOSK_ISSUER=%s\nKIOSK_IMAGE=%s\nKIOSK_USER=%s\n' "$issuer" "$image" "$user" \
  >"$target/.env"
install -m 0755 "$here/iden-kiosk" /usr/local/bin/iden-kiosk
# A missing image is reported by `up`; a failed pull of one already here (built
# on this device with kiosk/build.sh --local) is not a reason to stop.
docker compose -f "$target/compose.yml" pull --quiet --ignore-pull-failures
docker compose -f "$target/compose.yml" up --detach --remove-orphans

echo "==> Camera, screen, nightly updates"
install -m 0644 "$here/iden-kiosk-camera@.service" "$here/iden-kiosk-display.service" \
  "$here/iden-kiosk-update.service" "$here/iden-kiosk-update.timer" /etc/systemd/system/
install -m 0644 "$here/99-iden-kiosk-camera.rules" /etc/udev/rules.d/
systemctl daemon-reload
# A camera already held by an earlier version of the watcher picks up this one.
systemctl stop 'iden-kiosk-camera@*.service' 2>/dev/null || true
udevadm control --reload
udevadm trigger --subsystem-match=video4linux --action=add
systemctl enable --now iden-kiosk-display.service iden-kiosk-update.timer
# No screen blanking: an idle kiosk still has to show how to use it.
if command -v raspi-config >/dev/null; then raspi-config nonint do_blanking 1; fi

echo "==> Browser"
# The camera is allowed for the kiosk app without a prompt, and for nothing else.
install -d /etc/chromium/policies/managed
install -m 0644 "$here/chromium-policy.json" /etc/chromium/policies/managed/iden-kiosk.json
install -m 0644 "$here/iden-kiosk-browser.service" /etc/systemd/user/
install -m 0644 "$here/iden-kiosk.desktop" /etc/xdg/autostart/
# An earlier version of this script started the browser from the user's own
# labwc autostart file. labwc reads only the first autostart file it finds, so
# that file also hid the desktop's own; remove it if nothing else is in it.
labwc_autostart="$home/.config/labwc/autostart"
if [[ -f "$labwc_autostart" ]]; then
  sed -i '\#/opt/iden-kiosk/browser.sh#d' "$labwc_autostart"
  [[ -s "$labwc_autostart" ]] || rm "$labwc_autostart"
fi

cat <<EOF

Installed. The desktop is unchanged; kiosk mode starts only when you ask:

  iden-kiosk start     enter kiosk mode now
  iden-kiosk stop      leave it
  iden-kiosk enable    enter it by itself at every boot
  iden-kiosk status    what is running

Next: pair this kiosk from IDEN → Administration → Kiosks (start kiosk mode to
show the pairing screen), then tune the camera: doc/operations/kiosk-camera.md.
EOF
