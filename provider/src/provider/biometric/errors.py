from provider.core.errors import (
    ConflictError,
    IdenError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)


class BiometricDisabled(NotFoundError):
    code = "biometric_disabled"
    message = "Face sign-in is not enabled on this deployment."


class EngineUnavailable(UnavailableError):
    code = "engine_unavailable"
    message = "Face checks are unavailable right now. Use another method."


class TicketInvalid(NotFoundError):
    code = "enrolment_ticket_invalid"
    message = "This enrolment code has expired or was already used."


class FaceChallengeInvalid(NotFoundError):
    code = "face_challenge_invalid"
    message = "This capture has expired. Start again."


class FaceNotEnrolled(NotFoundError):
    code = "face_not_enrolled"
    message = "No face is enrolled on this account."


class FaceOutdated(ConflictError):
    code = "face_enrolment_outdated"
    message = (
        "Your face was enrolled with an earlier version of the system. "
        "Enrol again at a kiosk."
    )


class PoorCapture(ValidationError):
    """Nothing was decided; the frames were not good enough to judge.

    Carries what to fix, which is safe to tell anyone: it describes the
    picture, not the person.
    """

    code = "poor_capture"
    message = "We could not see your face clearly enough."


class BadFrames(ValidationError):
    code = "invalid_frames"
    message = "The capture does not match what was asked for."


class NotLive(ValidationError):
    """Told to a kiosk only — a supervised device, not an attacker's loop."""

    code = "not_live"
    message = "The capture did not pass the liveness checks."


class FaceRejected(IdenError):
    """Not live, or not this person — deliberately not said which."""

    code = "face_rejected"
    message = "That did not match. Try again or use another method."
