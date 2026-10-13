#!/usr/bin/env bash
# Run by the desktop at sign-in (iden-kiosk.desktop). Enters kiosk mode only
# after `iden-kiosk enable`, and only for the kiosk's own desktop user.
# shellcheck source=/dev/null
source /opt/iden-kiosk/.env
[[ -e /opt/iden-kiosk/start-at-boot && "$(id -un)" == "$KIOSK_USER" ]] || exit 0
systemctl --user daemon-reload
exec systemctl --user start iden-kiosk-browser.service
