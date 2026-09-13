"""Set a user's password from the command line.

A demo convenience for the account that cannot use the API to get back in.
Email and password come from the environment:

    docker compose run --rm -e EMAIL=admin@example.com -e PASSWORD=... \
        provider python -m scripts.change_pass

Every session and refresh token the user holds is revoked, the same as the
admin reset endpoint: a password changed while the old logins still work has
not really been changed.
"""

import asyncio
import os
import sys

from sqlalchemy import select

from provider.admin.users.service import revoke_everything
from provider.core.db import engine, session_factory
from provider.core.redis import client as redis
from provider.core.security import hash_secret
from provider.shared.models import User


async def main() -> None:
    email = os.environ.get("EMAIL")
    password = os.environ.get("PASSWORD")

    if not email or not password:
        sys.exit("Set EMAIL and PASSWORD in the environment.")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            sys.exit(f"No user with email {email}.")

        user.password_hash = hash_secret(password)
        await revoke_everything(session, redis, user.id)
        await session.commit()

    await redis.aclose()
    await engine.dispose()

    print(f"Password changed for {email}.")
    print("Every session and refresh token was revoked — sign in again.")


if __name__ == "__main__":
    asyncio.run(main())
