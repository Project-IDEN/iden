"""What a person agrees to before a kiosk enrols their face.

Written here rather than on the kiosk because it has to describe what this
deployment does — whether it keeps the photos — and because the version stored
beside a face must name the words that person was shown. The version is a hash
of those words, so any change to them, a setting's included, is a new version;
the words of every version someone agreed to are kept in `consent_wordings`.
"""

import hashlib
import json

from provider.core.config import settings

TITLE = "Before we take your photos"


def statements() -> list[str]:
    keep = settings.iden_biometric_keep_images
    stored = (
        "The photos are also kept, encrypted, so your face can be processed "
        "again when the system is upgraded."
        if keep
        else "The photos themselves are not kept."
    )
    removed = "the template and the photos" if keep else "the template"
    return [
        "This kiosk will take a few photos of your face while you follow the "
        "instructions on the screen, such as turning your head. These steps show "
        "that a real person is in front of the camera, not a photo or a screen.",
        "The kiosk sends the photos straight to IDEN and keeps none of them.",
        "IDEN turns them into a face template — numbers that describe your face — "
        "and stores it, encrypted, with your account. " + stored,
        "Your face is used for one thing: as a second step when you sign in, it "
        "is compared with the template on your account and no other. The apps "
        "you sign in to never receive your photos or your template.",
        "A face already enrolled on your account is replaced by this one. "
        "Security in your account shows when, and at which kiosk, your face was "
        "enrolled.",
        "Taking part is your choice. If you say no, nothing is captured and you "
        "sign in as you do today. You can remove your face at any time from "
        f"Security in your account, which deletes {removed}.",
    ]


def version() -> str:
    words = json.dumps([TITLE, *statements()], ensure_ascii=False)
    return hashlib.sha256(words.encode()).hexdigest()[:16]
