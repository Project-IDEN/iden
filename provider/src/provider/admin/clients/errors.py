from provider.core.errors import (
    ConflictError,
    ImmutableError,
    NotFoundError,
    ValidationError,
)


class ClientNotFound(NotFoundError):
    code = "client_not_found"
    message = "No such client."


class ClientIdTaken(ConflictError):
    code = "client_id_taken"
    message = "A client with this client_id already exists."


class SystemClientImmutable(ImmutableError):
    code = "system_client_immutable"
    message = "Bootstrap clients cannot be deleted."


class PublicClientHasNoSecret(ValidationError):
    code = "public_client_has_no_secret"
    message = (
        "Public clients have no secret to rotate — they prove themselves with PKCE. "
        "Register a confidential client if a secret is required."
    )


class RedirectUriRequired(ValidationError):
    code = "redirect_uri_required"
    message = (
        "A client using the authorization code grant needs at least one redirect URI."
    )


class UnknownScopes(NotFoundError):
    code = "unknown_scopes"
    message = "One or more scope ids do not exist."


class RestrictedScopeOnOwnedClient(ValidationError):
    code = "restricted_scope_on_owned_client"
    message = (
        "An application registered by a developer cannot be given an `admin:` or "
        "`biometric:` scope: its owner controls where its tokens are delivered."
    )
