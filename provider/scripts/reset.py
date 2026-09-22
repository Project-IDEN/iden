"""Throw the development database away and build it again.

    uv run python -m scripts.reset         # asks first
    uv run python -m scripts.reset --yes   # does not

Four steps, because a reset that does fewer leaves something behind: drop the
schema, flush Redis, migrate, seed. Redis is the one people forget — sessions
outlive the rows they refer to, so a database-only reset leaves live cookies
naming users that no longer exist, and the next request fails in a way that
looks like a bug rather than a stale login.
"""

import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from provider.core.config import settings
from provider.core.db import engine
from provider.core.redis import client as redis
from scripts import seed

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


async def wipe() -> None:
    """Drop the schema rather than downgrading to base.

    A downgrade undoes only what its migrations remember to undo, and nothing
    checks that they do — `tests/test_migrations.py` compares the models
    against an upgrade. Dropping the schema cannot leave a stray table behind,
    which is the entire promise of the word "reset".
    """
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    await redis.flushdb()
    await redis.aclose()
    await engine.dispose()


def confirm() -> None:
    if settings.iden_env == "prod":
        sys.exit("IDEN_ENV is prod. Refusing.")

    if "--yes" in sys.argv:
        return

    # Printed rather than assumed: the URLs come from the environment, and the
    # whole risk here is running this against a database you did not picture.
    # Without the password, which these URLs now carry — this goes to a terminal
    # and from there into scrollback and shell history, and the host and database
    # name are the whole of what anyone needs to read here.
    print(f"  database  {make_url(settings.iden_database_url)}")
    print(f"  redis     {make_url(settings.iden_redis_url)}")
    try:
        answer = input("Everything above is deleted. Type 'reset' to continue: ")
    except EOFError:
        # Nothing on stdin. Silence is not consent, and a traceback is not an
        # answer, so say the same thing as a refusal.
        answer = ""

    if answer != "reset":
        sys.exit("Nothing was changed.")


def main() -> None:
    confirm()
    asyncio.run(wipe())
    # Alembic runs its own event loop, so it cannot be awaited from inside ours.
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    asyncio.run(seed.main())


if __name__ == "__main__":
    main()
