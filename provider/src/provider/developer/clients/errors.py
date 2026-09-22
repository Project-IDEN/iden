from provider.core.errors import ConflictError, NotFoundError, ValidationError


class ApplicationNotFound(NotFoundError):
    code = "application_not_found"
    message = "No such application."


class ApplicationQuotaReached(ConflictError):
    code = "application_quota_reached"
    message = (
        "You have reached the number of applications one account may register. "
        "Delete one you no longer need, or ask an administrator."
    )


class PublicClientHasNoSecret(ValidationError):
    code = "public_client_has_no_secret"
    message = (
        "Public applications have no secret to rotate — they prove themselves with "
        "PKCE. Register a confidential application if a secret is required."
    )
