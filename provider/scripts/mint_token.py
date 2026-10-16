"""Print an access token for a person, for load-testing the routes behind one.

Running the sign-in for every virtual user would measure argon2, not the route.
This signs a token the way `/oauth2/token` does, for the `dashboard` client,
from the host that holds the signing keys:

    EMAIL=admin@localhost uv run python -m scripts.mint_token
    docker compose run --rm -e EMAIL=admin@localhost provider \
        python -m scripts.mint_token

`SCOPES` defaults to the two the load test's `sessions` and `permissions`
scenarios need; `TTL` to an hour, so a long soak does not end in 401s. The token
is a real credential for that person until it expires.
"""

import asyncio
import os
import sys

from sqlalchemy import select

from provider.authz.services.token_service import mint_access_token, now
from provider.core.config import settings
from provider.core.db import engine, session_factory
from provider.shared.models import Client, User

DEFAULT_SCOPES = "entity:sessions:read entity:permissions:read"


async def main() -> None:
    email = os.environ.get("EMAIL") or settings.iden_bootstrap_admin_email
    scopes = set((os.environ.get("SCOPES") or DEFAULT_SCOPES).split())
    settings.iden_access_token_ttl = int(os.environ.get("TTL") or 3600)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            sys.exit(f"No user with email {email}.")
        dashboard = await session.scalar(
            select(Client).where(Client.client_id == "dashboard")
        )
        if dashboard is None:
            sys.exit("No dashboard client. Run: uv run python -m scripts.seed")
        token, _, _ = await mint_access_token(
            session,
            subject=str(user.id),
            client=dashboard,
            scopes=scopes,
            acr="urn:iden:acr:sfa",
            amr=["pwd"],
            authenticated_at=now(),
        )
    await engine.dispose()
    print(token)


if __name__ == "__main__":
    asyncio.run(main())
