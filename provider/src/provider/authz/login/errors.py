from provider.core.errors import IdenError


class InvalidCredentials(IdenError):
    code = "invalid_credentials"
    message = "Email or password is incorrect."


class ChallengeNotFound(IdenError):
    code = "challenge_not_found"
    message = "This login attempt has expired. Start again from the application."


class TotpNotEnrolled(IdenError):
    code = "totp_not_enrolled"
    message = "This account has no authenticator app set up."


class InvalidTotpCode(IdenError):
    code = "invalid_totp_code"
    message = "That code is not valid."


class NoSession(IdenError):
    code = "no_session"
    message = "Not signed in."
