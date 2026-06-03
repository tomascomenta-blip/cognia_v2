"""
security/ollama_url.py
======================
Phase 9 H1: SSRF prevention for OLLAMA_URL.
Validates that the Ollama URL targets only localhost to prevent
Server-Side Request Forgery against cloud metadata services or
internal network endpoints.
"""
import logging
import os
import urllib.parse

_logger = logging.getLogger(__name__)

_SAFE_HOSTS = {"localhost", "127.0.0.1", "::1"}
_FALLBACK   = "http://localhost:11434"


def validate_ollama_url(url: str) -> str:
    """
    Return url unchanged if it points to a safe local host.
    If COGNIA_REMOTE_OLLAMA=1 is set, also allow external URLs
    (use only when connecting to a trusted remote cognia node).
    """
    if not url:
        return _FALLBACK
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in _SAFE_HOSTS:
            return url
        if os.environ.get("COGNIA_REMOTE_OLLAMA") == "1":
            _logger.info("COGNIA_REMOTE_OLLAMA=1 — aceptando URL remota: %s", url)
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
