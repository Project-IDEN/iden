"""Validation and casting for organization-defined profile values.

Values are stored as text and cast at the boundary. That is the cost of keeping
them in a table rather than a JSONB column — the price paid for real uniqueness
constraints and indexed filtering. This module is the boundary, and it is shared
because both the person editing their own profile and the administrator editing
someone else's must be held to the same field definition.
"""

import re
from datetime import date
from typing import Any

from provider.shared.enums import FieldType
from provider.shared.models import ProfileField

# Claims fixed by OIDC Core and RFC 7519. A custom field that shadowed one of
# these would let an administrator forge the meaning of a token.
RESERVED_CLAIMS = frozenset(
    {
        "iss",
        "sub",
        "aud",
        "exp",
        "nbf",
        "iat",
        "jti",
        "auth_time",
        "nonce",
        "acr",
        "amr",
        "azp",
        "sid",
        "scope",
        "client_id",
        "token_type",
        # Standard OIDC claims IDEN emits itself under `profile` and `email`.
        # A field claiming one of these names would be silently overwritten at
        # mint time, so it is refused when the field is defined instead.
        "name",
        "preferred_username",
        "picture",
        "email",
        "email_verified",
    }
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9 ()\-]{6,20}$")

# A ceiling on one stored answer. Values live in a `Text` column, so without this
# a single writable field is somewhere to put as much data as the request body
# allows — and `pattern` below is then run over all of it.
MAX_VALUE_LENGTH = 4096

# The rules a field may carry, and the type each one has to be. An administrator
# writes this dict, and everything in it is applied to values other people
# submit, so it is checked when the *field* is defined rather than when someone
# fills it in: a rule that cannot be applied is the administrator's mistake to
# see, not a 500 for whoever happens to save their profile next.
VALIDATOR_TYPES: dict[str, type] = {
    "pattern": str,
    "min": int,
    "max": int,
    "min_length": int,
    "max_length": int,
}

# `pattern` is a regular expression IDEN runs against caller-supplied text, and
# Python's engine backtracks: `(a+)+$` over a few thousand characters does not
# finish. Neither a length cap nor `MAX_VALUE_LENGTH` makes that impossible, but
# together they bound it to something a worker survives. A field's format rule
# does not need more than this.
MAX_PATTERN_LENGTH = 256


class InvalidValidators(ValueError):
    """The rules on a field definition cannot be applied."""


def check_validators(rules: dict) -> dict:
    """Validate a field's `validators`, or raise `InvalidValidators`.

    Returns the rules unchanged: this says whether they are usable, it does not
    reshape them.
    """
    if unknown := sorted(set(rules) - set(VALIDATOR_TYPES)):
        allowed = ", ".join(sorted(VALIDATOR_TYPES))
        raise InvalidValidators(
            f"unknown validator: {', '.join(unknown)}. Allowed: {allowed}."
        )

    for name, value in rules.items():
        expected = VALIDATOR_TYPES[name]
        # `bool` is a subclass of `int`, and `min_length: true` is a mistake
        # rather than a length of one.
        if not isinstance(value, expected) or isinstance(value, bool):
            raise InvalidValidators(f"{name} must be {expected.__name__}")

    if (pattern := rules.get("pattern")) is not None:
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise InvalidValidators(
                f"pattern must be at most {MAX_PATTERN_LENGTH} characters"
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise InvalidValidators(
                f"pattern is not a valid expression: {exc}"
            ) from exc

    for name in ("min_length", "max_length"):
        if (
            length := rules.get(name)
        ) is not None and not 0 <= length <= MAX_VALUE_LENGTH:
            raise InvalidValidators(f"{name} must be between 0 and {MAX_VALUE_LENGTH}")

    return rules


class InvalidValue(ValueError):
    """The value does not satisfy the field's definition."""


def coerce(field: ProfileField, raw: Any) -> str:
    """Validate `raw` against the field and return what to store.

    Raises `InvalidValue` with a message written for the person who typed it.
    """
    if raw is None or raw == "":
        if field.required:
            raise InvalidValue(f"{field.label} is required.")
        return ""

    value = _check_type(field, raw)
    if len(value) > MAX_VALUE_LENGTH:
        raise InvalidValue(
            f"{field.label} must be at most {MAX_VALUE_LENGTH} characters."
        )
    _check_validators(field, value)
    return value


def _check_type(field: ProfileField, raw: Any) -> str:
    match field.data_type:
        case FieldType.INTEGER:
            try:
                return str(int(raw))
            except (TypeError, ValueError) as exc:
                raise InvalidValue(f"{field.label} must be a whole number.") from exc

        case FieldType.BOOLEAN:
            if isinstance(raw, bool):
                return "true" if raw else "false"
            if str(raw).lower() in {"true", "false"}:
                return str(raw).lower()
            raise InvalidValue(f"{field.label} must be true or false.")

        case FieldType.DATE:
            try:
                return date.fromisoformat(str(raw)).isoformat()
            except ValueError as exc:
                raise InvalidValue(
                    f"{field.label} must be a date, as YYYY-MM-DD."
                ) from exc

        case FieldType.ENUM:
            if str(raw) not in field.options:
                allowed = ", ".join(field.options)
                raise InvalidValue(f"{field.label} must be one of: {allowed}.")
            return str(raw)

        case FieldType.EMAIL:
            if not EMAIL_PATTERN.match(str(raw)):
                raise InvalidValue(f"{field.label} must be an email address.")
            return str(raw)

        case FieldType.PHONE:
            if not PHONE_PATTERN.match(str(raw)):
                raise InvalidValue(f"{field.label} must be a phone number.")
            return str(raw)

        case FieldType.URL:
            if "://" not in str(raw):
                raise InvalidValue(f"{field.label} must be a full URL.")
            return str(raw)

        case _:
            return str(raw)


def _check_validators(field: ProfileField, value: str) -> None:
    rules = field.validators or {}

    if (pattern := rules.get("pattern")) and not re.match(pattern, value):
        raise InvalidValue(f"{field.label} is not in the expected format.")

    if (minimum := rules.get("min_length")) and len(value) < minimum:
        raise InvalidValue(f"{field.label} must be at least {minimum} characters.")

    if (maximum := rules.get("max_length")) and len(value) > maximum:
        raise InvalidValue(f"{field.label} must be at most {maximum} characters.")

    if field.data_type is FieldType.INTEGER:
        number = int(value)
        if (minimum := rules.get("min")) is not None and number < minimum:
            raise InvalidValue(f"{field.label} must be at least {minimum}.")
        if (maximum := rules.get("max")) is not None and number > maximum:
            raise InvalidValue(f"{field.label} must be at most {maximum}.")


def render(field: ProfileField, stored: str) -> Any:
    """The stored text as the type the field declares — what a client reads."""
    if stored == "":
        return None
    match field.data_type:
        case FieldType.INTEGER:
            return int(stored)
        case FieldType.BOOLEAN:
            return stored == "true"
        case _:
            return stored


def applies_to(field: ProfileField, group_ids: set) -> bool:
    """Whether a field is part of this person's profile at all.

    A field bound to a group belongs only to its members — how students and
    staff get different forms without a second grouping concept.
    """
    return field.group_id is None or field.group_id in group_ids
