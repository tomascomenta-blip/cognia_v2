"""
security/__init__.py
====================
Módulo de privacidad y seguridad — Fase 4.

Exports públicos:
  KeyManager        — derivación de clave maestra + cifrado AES-256-GCM
  SecureEpisodicMemory — wrapper cifrado/descifrado de EpisodicMemory
  SecurityError     — excepción base del módulo
"""

from .key_manager import KeyManager, SecurityError
from .secure_storage import SecureEpisodicMemory

__all__ = ["KeyManager", "SecureEpisodicMemory", "SecurityError"]
