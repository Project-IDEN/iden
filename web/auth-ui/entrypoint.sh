#!/bin/sh
# Injects runtime configuration before nginx starts. Baking the issuer or the
# organization in at build time would mean one image per deployment.
set -e

# Escaped for the JavaScript string literals below. An organization named
# O'Brien" College would otherwise end the literal and leave the app with a
# syntax error and a blank page — and a value chosen to do so on purpose would
# be running its own code on this origin.
escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

ISSUER="${IDEN_ISSUER:-http://localhost:8000}"

cat > /usr/share/nginx/html/auth/config.js <<JS
window.__IDEN_CONFIG__ = {
  issuer: "$(escape "$ISSUER")",
  organization: "$(escape "${IDEN_ORG_NAME:-}")",
  organizationLogoUrl: "$(escape "${IDEN_ORG_LOGO_URL:-}")",
};
JS

# The content policy needs the issuer's origin: on a single-origin deployment
# the API is 'self', but in development this app is on :4000 and the provider on
# :8000, and a policy written without it blocks every call the app makes.
ORIGIN=$(printf '%s' "$ISSUER" | sed -E 's#^(https?://[^/]+).*#\1#')

cat > /etc/nginx/conf.d/security-headers.inc <<CONF
add_header Referrer-Policy "no-referrer" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Content-Security-Policy "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; frame-src 'self' $ORIGIN; img-src 'self' data: https: $ORIGIN; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self' $ORIGIN" always;
CONF
