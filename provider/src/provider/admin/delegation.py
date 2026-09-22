"""Nobody can hand out, or borrow, authority they do not hold.

`admin:grants:write` decides *whether* somebody may assign permissions; this
decides *which*. Two rules, and each is useless alone:

- **granting** — you cannot confer a scope you lack (`refuse_undelegatable`)
- **borrowing** — you cannot act on a principal holding more than you
  (`refuse_if_outranked`, `refuse_if_client_outranks`). Otherwise resetting a
  password and clearing an authenticator is a way to become somebody who already
  has what you wanted.

Both measure against the caller's *token*, not their account: stricter, and it
makes them apply unchanged to `client_credentials`, where there is no person.

Both cover `admin:` and `biometric:` only — see `shared.scopes.RESTRICTED_PREFIXES`.
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

    `is_system` as well as the prefix: an administrator may define a scope of
    their own called `admin:anything`, and it grants nothing — no route asks for
    it. Restricting it would make a scope nobody could ever assign.
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
    return [scope for role in roles for scope in role.scopes]


def scopes_of_groups(groups: Iterable[Group]) -> list[Scope]:
    """What membership confers, by way of the groups' roles."""
    return [scope for group in groups for scope in scopes_of_roles(group.roles)]


def scopes_of_user(user: User) -> list[Scope]:
    """Everything a person holds: direct, role, and group."""
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
    """Raise unless the caller holds everything restricted that `target` does."""
    beyond = sorted(_restricted(scopes_of_user(target)) - caller_scopes)
    if beyond:
        raise CannotAdminister(
            "This account holds authority you do not: "
            f"{', '.join(beyond)}. Ask somebody who holds it.",
            scopes=beyond,
        )


def held_by_client(client: Client) -> list[Scope]:
    """What a client holds in its own right — the `granted` half.

    `grantable` is excluded: it reaches a token only through `/authorize`, where
    it is intersected with what the signed-in person holds, so it cannot exceed
    somebody's existing authority. `granted` goes into a `client_credentials`
    token on request, with no person involved.
    """
    return [link.scope for link in client.scopes if link.granted]


def refuse_if_client_outranks(caller_scopes: set[str], client: Client) -> None:
    """Raise unless the caller holds everything restricted that `client` holds.

    A scope a client holds is dormant only until somebody adds the
    `client_credentials` grant and rotates its secret — both `admin:clients:write`,
    neither a scope assignment.
    """
    beyond = sorted(_restricted(held_by_client(client)) - caller_scopes)
    if beyond:
        raise CannotAdminister(
            "This application holds authority you do not: "
            f"{', '.join(beyond)}. Ask somebody who holds it.",
            scopes=beyond,
        )
