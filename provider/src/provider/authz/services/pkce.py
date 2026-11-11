"""Proof Key for Code Exchange — RFC 7636.

PKCE stops an attacker who intercepts an authorization code from redeeming it:
the client commits to a secret (`code_verifier`) by sending its hash
(`code_challenge`) at /authorize, and must reveal the secret at /token.

IDEN requires `S256` from every client, public and confidential. The `plain`
method (RFC 7636 Section 4.2) offers no protection against an attacker who can read
the authorization request, so it is rejected rather than supported.
"""

import base64
import hashlib
import hmac
import re

from provider.shared.enums import CodeChallengeMethod

# RFC 7636 Section 4.1: 43 to 128 unreserved characters.
_VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
# An S256 challenge is the unpadded base64url of a SHA-256 digest: always 43.
_S256_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")


def is_s256_challenge(challenge: str) -> bool:
    return _S256_CHALLENGE.fullmatch(challenge) is not None


def create_challenge(verifier: str) -> str:
    """S256: BASE64URL(SHA256(ASCII(verifier))), unpadded — RFC 7636 Section 4.2."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_challenge(verifier: str, challenge: str, method: str) -> bool:
    """RFC 7636 Section 4.6 — recompute the challenge and compare."""
    if method != CodeChallengeMethod.S256 or not _VERIFIER.fullmatch(verifier):
        return False
    return hmac.compare_digest(create_challenge(verifier), challenge)
