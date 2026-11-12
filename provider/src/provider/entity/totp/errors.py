from provider.core.errors import ConflictError, NotFoundError, ValidationError


class AlreadyEnrolled(ConflictError):
    code = "totp_already_enrolled"
    message = "An authenticator is already set up. Remove it before enrolling another."


class NotEnrolling(NotFoundError):
    code = "totp_not_enrolling"
    message = "There is no pending enrolment to confirm."


class WrongCode(ValidationError):
    code = "totp_wrong_code"
    message = "That code is not right. Check the app's clock if it keeps failing."
