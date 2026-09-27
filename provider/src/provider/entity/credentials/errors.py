from provider.core.errors import ValidationError


class WrongPassword(ValidationError):
    code = "wrong_password"
    message = "The current password is not correct."


class SamePassword(ValidationError):
    code = "same_password"
    message = "The new password must differ from the current one."
