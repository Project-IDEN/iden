"""The guard against a one-way door.

Every other mistake an administrator can make is reversible by another
administrator. Removing the last one is not: `is_system` protects the scope
catalogue, but nothing protected the *assignment*, so deactivating the wrong
account or editing the wrong role left no way back in through the API at all.
Recovery meant editing the database by hand.

This is checked as a post-condition rather than by reasoning about each
operation. Every mutation asks the same question afterwards — *can anyone still
administer this?* — which is one rule to get right instead of nine, and it is
answered against the world the commit is about to create rather than a
prediction of it.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.errors import ConflictError
from provider.core.logging import logger
from provider.shared.models import (
    Scope,
    User,
    group_roles,
    role_scopes,
    user_groups,
    user_roles,
    user_scopes,
)

# The scope that can restore every other one: whoever holds it can set anyone's
# roles, including their own. It is therefore the only one whose last holder
# matters — lose it and no sequence of API calls puts it back.
#
# It used to be `admin:users:write`, which carried both halves of user
# administration. Assigning permissions is now its own scope, and this follows
# it: `admin:users:write` can no longer grant anything, so its last holder is
# replaceable by anyone who can assign roles, while this one's is not.
RECOVERY_SCOPE = "admin:grants:write"


class WouldLockEveryoneOut(ConflictError):
    code = "would_lock_everyone_out"
    message = (
        f"This would leave no active user holding `{RECOVERY_SCOPE}`, and no way "
        "to restore one through the API. Grant it to somebody else first."
    )


async def administrators_remaining(session: AsyncSession) -> int:
    """Active users who hold the recovery scope, however they came by it.

    Counted in SQL rather than by loading users and reusing
    `scope_resolver.effective_user_scopes`: this runs on every administrative
    write, and the resolver would need every active user in memory to answer it.
    """
    scope_id = await session.scalar(
        select(Scope.id).where(Scope.value == RECOVERY_SCOPE)
    )
    if scope_id is None:
        # No catalogue to protect, and refusing every write until there is one
        # would be its own lockout. Two very different situations reach here
        # though, and only the first is fine: a database nobody has seeded, and
        # one seeded before this scope existed. In the second the guard is off
        # while there are administrators to lose, so it says so rather than
        # passing quietly — the fix is one `scripts.seed` away.
        if await session.scalar(select(func.count(User.id))):
            logger.warning(
                "Lockout protection is inactive: the recovery scope is not in "
                "the catalogue. Run `python -m scripts.seed`.",
                scope=RECOVERY_SCOPE,
            )
        return -1

    granting_roles = select(role_scopes.c.role_id).where(
        role_scopes.c.scope_id == scope_id
    )

    return (
        await session.scalar(
            select(func.count(func.distinct(User.id)))
            .where(User.is_active)
            .where(
                or_(
                    User.id.in_(
                        select(user_scopes.c.user_id).where(
                            user_scopes.c.scope_id == scope_id
                        )
                    ),
                    User.id.in_(
                        select(user_roles.c.user_id).where(
                            user_roles.c.role_id.in_(granting_roles)
                        )
                    ),
                    User.id.in_(
                        select(user_groups.c.user_id).where(
                            user_groups.c.group_id.in_(
                                select(group_roles.c.group_id).where(
                                    group_roles.c.role_id.in_(granting_roles)
                                )
                            )
                        )
                    ),
                )
            )
        )
        or 0
    )


async def refuse_if_last(session: AsyncSession) -> None:
    """Call after the change and before the commit.

    The count reads through the pending change: issuing a query autoflushes it,
    so what is counted is what the commit would leave behind. Raising here
    aborts the request, and the session rolls back on the way out.
    """
    if await administrators_remaining(session) == 0:
        raise WouldLockEveryoneOut
