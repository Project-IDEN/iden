# Response headers for the two browser applications. The provider sets its own,
# in `provider/core/headers.py`.
#
# Rewritten at container start by the app's entrypoint, which knows the issuer;
# this copy is the fallback so nginx still starts if that did not run.
#
# Included per `location` rather than once on the `server`, because nginx drops
# every inherited `add_header` in a block that declares one of its own — and each
# location here sets `Cache-Control`. `.inc` so `include conf.d/*.conf` does not
# load it as a server of its own.

# The sign-in page is reached as `/auth/login?challenge=<id>`, and that id stands
# for a pending authorization request for ten minutes. Any subresource from
# another host would otherwise carry it in `Referer`, and `IDEN_ORG_LOGO_URL` is
# exactly such a host.
add_header Referrer-Policy "no-referrer" always;

add_header X-Content-Type-Options "nosniff" always;

# `frame-ancestors 'none'` matters most: the dashboard performs administrative
# writes with a session the browser attaches on its own.
add_header Content-Security-Policy "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; frame-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'" always;
