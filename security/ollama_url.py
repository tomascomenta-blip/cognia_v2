"""
security/ollama_url.py
======================
Phase 9 H1: SSRF prevention for OLLAMA_URL.
Validates that the Ollama URL targets only localhost to prevent
Server-Side Request Forgery against cloud metadata services or
internal network endpoints.
"""
import logging
import urllib.parse

_logger = logging.getLogger(__name__)

_SAFE_HOSTS = {"localhost", "127.0.0.1", "::1"}
_FALLBACK   = "http://localhost:11434"


def validate_ollama_url(url: str) -> str:
    """
    Return url unchanged if it points to a safe local host (localhost,
    127.0.0.1, ::1). Log a WARNING and return the fallback URL otherwise.

    Blocks: 169.254.x.x (cloud metadata), 10.x, 192.168.x, public IPs.
    """
    if not url:
        return _FALLBACK
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in _SAFE_HOSTS:
            return url
    except Exception:
        pass
    _logger.warning(
        "OLLAMA_URL '%s' apunta a un host no-localhost — rechazada para "
        "prevenir SSRF. Usando fallback: %s",
        url,
        _FALLBACK,
    )
    return _FALLBACK
