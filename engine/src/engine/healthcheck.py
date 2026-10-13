"""The container's health check: is the engine answering, over TLS when it serves TLS."""

import ssl
import urllib.request

from engine.config import settings

scheme = "https" if settings.engine_tls_cert_file else "http"
# Checking itself on localhost; the certificate names the host the provider uses.
context = ssl._create_unverified_context() if scheme == "https" else None
urllib.request.urlopen(
    f"{scheme}://localhost:8000/health/live", context=context, timeout=2
)
