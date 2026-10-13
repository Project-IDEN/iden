from provider.core.errors import NotFoundError


class KioskNotFound(NotFoundError):
    code = "kiosk_not_found"
    message = "No such kiosk."
