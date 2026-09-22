"""Turning a User-Agent header into something a person recognises.

Deliberately a short table rather than a parser library. The regex databases
those ship go stale, and updating one becomes a reason to redeploy the
provider — for a field whose only job is to help someone spot the session that
is not theirs. A short list that degrades to `None` is better than a long one
that is confidently wrong.

Best effort is the contract: every return is nullable, and a browser IDEN has
never heard of shows as an unnamed session rather than a broken row.
"""

import re

# How much of the header is kept. It is caller-supplied and unbounded on the
# wire, while everything downstream is not: the audit column is 512 characters,
# a session payload is held in Redis for a day, and `describe` scans whatever it
# is given. Nothing after the first hundred characters or so identifies a
# browser anyway.
MAX_LENGTH = 512


def capture(raw: str | None) -> str | None:
    """The header as it should be stored — see `MAX_LENGTH`."""
    return raw[:MAX_LENGTH] if raw else None


# Order matters. Every modern browser lies about being several others in its
# User-Agent — Edge claims Chrome and Safari, Chrome claims Safari — so the
# most specific claim has to be tested first or everything reads as Safari.
_BROWSERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)")),
    ("Opera", re.compile(r"OPR/(\d+)")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/(\d+)")),
    ("Firefox", re.compile(r"(?:Firefox|FxiOS)/(\d+)")),
    ("Chrome", re.compile(r"(?:Chrome|CriOS)/(\d+)")),
    ("Safari", re.compile(r"Version/(\d+).*Safari/")),
)

# Checked before the desktop patterns: an iPad reports "Macintosh" in desktop
# mode, and Android reports "Linux".
_DEVICES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iPhone", re.compile(r"iPhone")),
    ("iPad", re.compile(r"iPad")),
    ("Android", re.compile(r"Android")),
    ("Mac", re.compile(r"Macintosh|Mac OS X")),
    ("Windows", re.compile(r"Windows NT")),
    ("Linux", re.compile(r"X11|Linux")),
)


def describe(raw: str | None) -> tuple[str | None, str | None]:
    """`(device, browser)` for display, e.g. `("Mac", "Chrome 142")`.

    Either half is `None` when nothing matched, and both are `None` for an
    absent header — a caller that sends no User-Agent is not an error, just
    unidentified.
    """
    if not raw:
        return None, None

    device = next((name for name, pattern in _DEVICES if pattern.search(raw)), None)

    browser = None
    for name, pattern in _BROWSERS:
        if match := pattern.search(raw):
            browser = f"{name} {match.group(1)}"
            break

    return device, browser
