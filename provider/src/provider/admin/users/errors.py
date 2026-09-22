from provider.core.errors import ConflictError, NotFoundError


class UserNotFound(NotFoundError):
    code = "user_not_found"
    message = "No such user."


class EmailTaken(ConflictError):
    code = "email_taken"
    message = "A user with this email already exists."


class UsernameTaken(ConflictError):
    code = "username_taken"
    message = "A user with this username already exists."


class UnknownRoles(NotFoundError):
    code = "unknown_roles"
    message = "One or more role ids do not exist."


class UnknownGroups(NotFoundError):
    code = "unknown_groups"
    message = "One or more group ids do not exist."


class UnknownScopes(NotFoundError):
    code = "unknown_scopes"
    message = "One or more scope ids do not exist."
