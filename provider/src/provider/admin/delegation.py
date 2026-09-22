"""Nobody can hand out, or borrow, authority they do not hold.

`admin:grants:write` decides *whether* somebody may assign permissions. This
decides *which* — and without it the first is nearly meaningless, because the
scope that lets you assign roles lets you assign the role that contains it.

Two rules, and each is useless alone.

**Granting** (`refuse_undelegatable`). A scope reaches a principal by more paths
than it looks: named directly, by a role containing it, by a group whose roles
contain it, by joining such a group, by the meaning of a role changing under
everyone already holding it, and by a client holding it in its own right —
including a scope already attached as `grantable` being promoted to `granted`,
which attaches no new row and confers a new power. Miss one and the rest are
decoration.

**Borrowing** (`refuse_if_outranked`, `refuse_if_client_outranks`). Stopping an
administrator granting what they lack achieves nothing if they can instead take
it from somebody who has it. Resetting a password and clearing an authenticator
are together an account takeover; adding the `client_credentials` grant to a
client that already holds a scope and rotating its secret is the same move
against the other kind of principal. Neither touches a scope assignment, so
neither is caught by the first rule. So: you may only act on people and
applications that are not above you.

What both measure against is the **caller's token**, not the caller's account.
That is deliberate and it is stricter: a token carries the intersection of what
was requested, what the client may request and what the person holds, so an
administrator working through a narrowly-scoped client cannot delegate past that
token. It also makes the rules apply unchanged to `client_credentials`, where
there is no person at all.

Both cover `admin:` and `biometric:` only — see `shared.scopes.RESTRICTED_PREFIXES`
for why restricting the rest would stop an administrator doing the job the role
exists for.
"""

from collections.abc import Iterable

from provider.core.errors import ForbiddenError
from provider.shared.models import Client, Group, Role, Scope, User
from provider.shared.scopes import RESTRICTED_PREFIXES


class CannotDelegate(ForbiddenError):
    code = "cannot_delegate"
    message = (
        "You cannot grant a permission you do not hold yourself. Ask somebody "
        "who holds it, or have it granted to you first."
    )


def _restricted(scopes: Iterable[Scope]) -> set[str]:
    """Those of `scopes` that confer authority over somebody else.

    `is_system` is part of the test rather than the prefix alone: an
    administrator may define a scope of their own called `admin:anything`, and it
    grants nothing — no route asks for it, and its audience is its own API's.
    Treating it as restricted would make a scope nobody could ever assign.
    """
    return {
        scope.value
        for scope in scopes
        if scope.is_system and scope.value.split(":")[0] in RESTRICTED_PREFIXES
    }


def refuse_undelegatable(caller_scopes: set[str], conferring: Iterable[Scope]) -> None:
    """Raise unless every restricted scope in `conferring` is one the caller holds."""
    beyond = sorted(_restricted(conferring) - caller_scopes)
    if beyond:
        raise CannotDelegate(
            "You cannot grant a permission you do not hold yourself: "
            f"{', '.join(beyond)}.",
            scopes=beyond,
        )


def scopes_of_roles(roles: Iterable[Role]) -> list[Scope]:
    """Everything a set of roles confers, for the check above."""
    return [scope for role in roles for scope in role.scopes]


def scopes_of_groups(groups: Iterable[Group]) -> list[Scope]:
    """Everything membership of a set of groups confers, by way of their roles."""
    return [scope for group in groups for scope in scopes_of_roles(group.roles)]


def scopes_of_user(user: User) -> list[Scope]:
    """Everything a person holds, by every route — direct, role, and group."""
    return [
        *user.scopes,
        *scopes_of_roles(user.roles),
        *scopes_of_groups(user.groups),
    ]


class CannotAdminister(ForbiddenError):
    code = "cannot_administer"
    message = (
        "You cannot act on an account that holds authority you do not hold yourself."
    )


def refuse_if_outranked(caller_scopes: set[str], target: User) -> None:
    """Raise unless the caller holds everything restricted that `target` does.

    The mirror of `refuse_undelegatable`, and the half without which that one
    does not hold. Delegation stops an administrator *granting* authority they
    lack; this stops them *borrowing* it. Managing a person includes resetting
    their password and clearing their authenticator, and those two together are
    an account takeover: reset the password of somebody more privileged, clear
    the second factor that would have stopped you, and sign in as them.

    So the rule is that you may only administer people who are not above you.
    `admin:users:write` on its own then means what it looks like it means —
    managing ordinary accounts — instead of being a route to every permission
    by way of whoever already has it.
    """
    beyond = sorted(_restricted(scopes_of_user(target)) - caller_scopes)
    if beyond:
        raise CannotAdminister(
            "This account holds authority you do not: "
            f"{', '.join(beyond)}. Ask somebody who holds it.",
            scopes=beyond,
        )


def held_by_client(client: Client) -> list[Scope]:
    """What a client holds **in its own right** — the `granted` half.

    `grantable` is deliberately excluded. A grantable scope reaches a token only
    through `/authorize`, where it is intersected with what the signed-in person
    holds, so it can never exceed somebody's existing authority. `granted` has no
    such bound: it goes into a `client_credentials` token on request, with no
    person involved at all.
    """
    return [link.scope for link in client.scopes if link.granted]


def refuse_if_client_outranks(caller_scopes: set[str], client: Client) -> None:
    """Raise unless the caller holds everything restricted that `client` holds.

    The same rule as `refuse_if_outranked`, for the other kind of principal, and
    it closes the same shape of hole. A client that holds a scope outright is
    only dormant until somebody gives it the `client_credentials` grant and
    rotates its secret — both of which are `admin:clients:write`, and neither of
    which touches a scope assignment at all. Without this, editing such a client
    was a way to pick up its authority without ever being granted it.
    """
    beyond = sorted(_restricted(held_by_client(client)) - caller_scopes)
    if beyond:
        raise CannotAdminister(
            "This application holds authority you do not: "
            f"{', '.join(beyond)}. Ask somebody who holds it.",
            scopes=beyond,
        )
