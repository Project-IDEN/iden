"""What a person agrees to before a kiosk enrols their face.

Written here rather than on the kiosk because it has to describe what this
deployment does — whether it keeps the photos — and because the version stored
beside a face must name the words that person was shown. The version is a hash
of those words, so any change to them, a setting's included, is a new version.
"""

import hashlib
import json

from provider.core.config import settings

TITLE = "Before we take your photos"


def statements() -> list[str]:
    kept = (
        "The photos are also kept, encrypted, so your face can be processed "
        "again when the system is upgraded."
        if settings.iden_biometric_keep_images
        else "The photos themselves are not kept."
    )
    return [
        "This kiosk will take a few photos of your face while you follow the "
        "instructions on the screen.",
        "IDEN turns them into a face template — numbers that describe your face — "
        "and stores it, encrypted, with your account. " + kept,
        "You can then use your face as a second step when you sign in. A face "
        "already enrolled on your account is replaced, and we email you to confirm.",
        "Taking part is your choice. You can remove your face at any time from "
        "Security in your account, and without it you sign in as you do today.",
    ]


def version() -> str:
    words = json.dumps([TITLE, *statements()], ensure_ascii=False)
    return hashlib.sha256(words.encode()).hexdigest()[:16]
