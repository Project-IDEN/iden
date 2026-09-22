"""Delivering a message to a person outside the browser.

One interface with one implementation, which writes to the log. Choosing an
SMTP provider is a deployment decision and a later phase; password recovery
should not wait on it, and a developer needs to see the link anyway.
"""

from provider.core.config import settings
from provider.core.logging import logger


async def send(*, to: str, subject: str, body: str) -> None:
    """Deliver a message. In development this is the log.

    In development the address and the body are both logged deliberately: there
    is no mailbox, so this *is* the inbox, and the reset link has to be readable
    somewhere.

    Outside development the body is withheld. It carries a single-use token that
    is enough to take an account over, and a log is the wrong place for a
    credential: it is aggregated, retained, and readable by people who are not
    the account's owner. What is logged instead says a message could not be
    delivered, because no transport is configured — replacing this function is
    what fixes that, and staying quiet about it would make a silently broken
    recovery flow look like a working one.
    """
    if settings.iden_env != "prod":
        logger.info("Notification", to=to, subject=subject, body=body)
        return

    logger.error(
        "Notification not delivered: no transport is configured",
        to=to,
        subject=subject,
    )
