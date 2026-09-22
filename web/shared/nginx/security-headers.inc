# Response headers for the two browser applications.
#
# The provider sets its own (see `provider/core/headers.py`); these two set
# none, and nothing in front of them filled the gap — so the admin console was
# served framable, with no content policy, and leaking the sign-in challenge in
# its `Referer`.
#
# Rewritten at container start by the app's entrypoint, which knows the issuer.
# This copy is the fallback, so nginx still starts if the entrypoint did not run.
#
# Included per `location` rather than set once on the `server`: nginx drops
# every inherited `add_header` in any block that declares one of its own, and
# each location here sets `Cache-Control`. Set at server level these would be
# silently absent from exactly the responses that carry the application.
#
# `.inc` rather than `.conf` so nginx's own `include conf.d/*.conf` does not
# also load it as a server configuration.

# The sign-in page is reached as `/auth/login?challenge=<id>`, and that id is a
# credential — it stands for a pending authorization request for ten minutes.
# Any subresource the page loads from another host would otherwise carry it in
# `Referer`, and `IDEN_ORG_LOGO_URL` is exactly such a host.
add_header Referrer-Policy "no-referrer" always;

add_header X-Content-Type-Options "nosniff" always;

# `frame-ancestors 'none'` is the one that matters most here: the dashboard
# performs administrative writes with a session the browser attaches on its own,
# which is what clickjacking is for.
add_header Content-Security-Policy "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; frame-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'" always;
