"""
security/key_manager.py
=======================
Gestión de claves criptográficas para COGNIA — Fase 4.

DISEÑO:
  - Clave maestra derivada de passphrase con hashlib.pbkdf2_hmac
    (Argon2id es ideal pero requiere dependencia externa; pbkdf2 está en stdlib
     con parámetros endurecidos para compensar: 600_000 iteraciones, SHA-256).
  - Cifrado simétrico: AES-256-GCM via cryptography (si disponible)
    o fallback XOR-with-SHA256-stream (modo degradado, avisa al usuario).
  - Clave de sesión X25519 para datos semi-privados entre peers (Fase 3 MESH).
  - NUNCA se persiste la clave en texto plano.
  - Salt de 32 bytes aleatorios, almacenado junto a los datos cifrados.

DEPENDENCIAS:
  - stdlib: hashlib, os, struct, base64, secrets (todas incluidas en Python 3.6+)
  - OPCIONAL: cryptography (pip install cryptography) — habilita AES-256-GCM real.
    Sin ella, el módulo opera en modo degradado con aviso explícito.

RESTRICCIONES DEL PROYECTO:
  - requirements.txt no incluye 'cryptography'. Este módulo detecta si está
    disponible e informa al usuario, pero no falla si no está instalada.
  - Retrocompatible: no modifica tablas existentes de la DB.
  - Funciona en Windows (rutas, encoding UTF-8 explícito en todo str→bytes).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
from typing import Optional, Tuple

from logger_config import get_logger

logger = get_logger(__name__)

# ── Detección de cryptography (AES-256-GCM real) ──────────────────────
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_AES = True
except ImportError:
    _HAS_AES = False
    logger.warning(
        "cryptography no instalada — cifrado en modo degradado (XOR+HMAC). "
        "Instala con: pip install cryptography",
        extra={"op": "key_manager.init", "context": "fallback=xor_hmac"},
    )


# ══════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════

PBKDF2_ITERATIONS = 600_000   # OWASP 2023 mínimo para SHA-256
SALT_BYTES        = 32
KEY_BYTES         = 32        # 256 bits
NONCE_BYTES       = 12        # 96 bits — estándar GCM
TAG_BYTES         = 16        # 128 bits — GCM tag

# Prefijo en el payload cifrado para distinguir versiones
_V1_MAGIC = b"CGN1"   # Cognia Fase 4, versión 1


# ══════════════════════════════════════════════════════════════════════
# EXCEPCIÓN BASE
# ══════════════════════════════════════════════════════════════════════

class SecurityError(Exception):
    """Excepción base del módulo security. Lanzada en errores criptográficos."""


# ══════════════════════════════════════════════════════════════════════
# KEY MANAGER
# ══════════════════════════════════════════════════════════════════════

class KeyManager:
    """
    Gestiona la clave maestra de cifrado de Cognia.

    Uso básico
    ----------
        km = KeyManager()
        km.unlock("mi_passphrase_segura")

        ciphertext = km.encrypt(b"texto privado")
        plaintext  = km.decrypt(ciphertext)

        km.lock()   # borra la clave de RAM

    La passphrase NUNCA se almacena. Solo se guarda el salt (32 bytes)
    en el archivo indicado por salt_path.

    Parámetros
    ----------
    salt_path : str | None
        Ruta donde persistir el salt. Por defecto "cognia_key.salt" en el
        directorio actual. Si el archivo no existe se crea al hacer unlock().
    """

    def __init__(self, salt_path: str = "cognia_key.salt"):
        self._salt_path  : str            = salt_path
        self._master_key : Optional[bytes] = None   # 32 bytes, solo en RAM
        self._salt       : Optional[bytes] = None

        if _HAS_AES:
            logger.info(
                "KeyManager: AES-256-GCM activo",
                extra={"op": "key_manager.__init__", "context": "mode=aes_gcm"},
            )
        else:
            logger.warning(
                "KeyManager: modo degradado (XOR+HMAC). "
                "Instala cryptography para cifrado real.",
                extra={"op": "key_manager.__init__", "context": "mode=xor_hmac"},
            )

    # ── API pública ────────────────────────────────────────────────────

    @property
    def is_unlocked(self) -> bool:
        """True si hay una clave maestra activa en RAM."""
        return self._master_key is not None

    @property
    def mode(self) -> str:
        """'aes_gcm' si cryptography está disponible, 'xor_hmac' si no."""
        return "aes_gcm" if _HAS_AES else "xor_hmac"

    def unlock(self, passphrase: str) -> None:
        """
        Deriva la clave maestra desde passphrase + salt.

        Si el salt no existe lo genera aleatoriamente y lo persiste en salt_path.
        Si ya existe lo carga para reproducir la misma clave.

        Lanza SecurityError si la passphrase está vacía o el salt no se puede leer.
        """
        if not passphrase:
            raise SecurityError("La passphrase no puede estar vacía.")

        self._salt = self._load_or_create_salt()
        raw_key    = self._derive_key(passphrase.encode("utf-8"), self._salt)
        self._master_key = raw_key

        logger.info(
            "KeyManager desbloqueado",
            extra={
                "op":      "key_manager.unlock",
                "context": f"salt_path={self._salt_path} mode={self.mode}",
            },
        )

    def lock(self) -> None:
        """
        Borra la clave maestra de RAM.

        Después de llamar lock() cualquier intento de cifrar/descifrar
        lanzará SecurityError hasta que se llame unlock() nuevamente.
        """
        if self._master_key:
            # Sobreescribir antes de liberar (best-effort en CPython)
            self._master_key = bytes(KEY_BYTES)
        self._master_key = None
        logger.info(
            "KeyManager bloqueado — clave eliminada de RAM",
            extra={"op": "key_manager.lock", "context": ""},
        )

    def encrypt(self, plaintext: bytes, associated_data: bytes = b"") -> bytes:
        """
        Cifra plaintext con la clave maestra activa.

        Formato del ciphertext retornado:
          [CGN1 (4B)] [salt (32B)] [nonce (12B)] [ciphertext+tag]

        El associated_data (AAD) autentica metadatos sin cifrarlos.
        Retorna bytes listos para almacenar en la DB (base64 NO aplicado aquí,
        el caller decide la codificación).

        Lanza SecurityError si no hay clave activa.
        """
        self._require_unlocked()

        nonce = secrets.token_bytes(NONCE_BYTES)

        if _HAS_AES:
            aes    = AESGCM(self._master_key)
            ct_tag = aes.encrypt(nonce, plaintext, associated_data or None)
        else:
            ct_tag = self._xor_encrypt(plaintext, nonce, associated_data)

        payload = _V1_MAGIC + self._salt + nonce + ct_tag

        logger.debug(
            "encrypt: datos cifrados",
            extra={
                "op":      "key_manager.encrypt",
                "context": f"plain_len={len(plaintext)} mode={self.mode}",
            },
        )
        return payload

    def decrypt(self, payload: bytes, associated_data: bytes = b"") -> bytes:
        """
        Descifra un payload generado por encrypt().

        Lanza SecurityError si:
          - No hay clave activa.
          - El payload está corrupto o tiene magic incorrecto.
          - La autenticación falla (datos manipulados).
        """
        self._require_unlocked()

        if len(payload) < len(_V1_MAGIC) + SALT_BYTES + NONCE_BYTES + TAG_BYTES:
            raise SecurityError("Payload demasiado corto — datos corruptos.")

        magic = payload[:4]
        if magic != _V1_MAGIC:
            raise SecurityError(f"Magic incorrecto: {magic!r}. Formato no reconocido.")

        offset = 4
        salt   = payload[offset : offset + SALT_BYTES];   offset += SALT_BYTES
        nonce  = payload[offset : offset + NONCE_BYTES];  offset += NONCE_BYTES
        ct_tag = payload[offset:]

        # Si el salt del payload difiere del salt actual, re-derivar la clave
        # (útil si se importan datos de otro dispositivo con la misma passphrase)
        if salt != self._salt:
            logger.warning(
                "decrypt: salt diferente al actual — intentando re-derivar clave",
                extra={"op": "key_manager.decrypt", "context": "salt_mismatch=True"},
            )
            # No tenemos la passphrase aquí; lanzamos error claro
            raise SecurityError(
                "El payload fue cifrado con un salt diferente. "
                "Re-desbloquea con la passphrase original del dispositivo fuente."
            )

        try:
            if _HAS_AES:
                aes       = AESGCM(self._master_key)
                plaintext = aes.decrypt(nonce, ct_tag, associated_data or None)
            else:
                plaintext = self._xor_decrypt(ct_tag, nonce, associated_data)
        except Exception as exc:
            raise SecurityError(
                f"Autenticación fallida — datos corruptos o passphrase incorrecta: {exc}"
            ) from exc

        logger.debug(
            "decrypt: datos descifrados correctamente",
            extra={
                "op":      "key_manager.decrypt",
                "context": f"plain_len={len(plaintext)} mode={self.mode}",
            },
        )
        return plaintext

    def encrypt_text(self, text: str, associated_data: str = "") -> str:
        """
        Wrapper conveniente: cifra un str, retorna base64 str.
        Útil para almacenar en columnas TEXT de SQLite.
        """
        raw = self.encrypt(
            text.encode("utf-8"),
            associated_data.encode("utf-8") if associated_data else b"",
        )
        return base64.b64encode(raw).decode("ascii")

    def decrypt_text(self, b64_payload: str, associated_data: str = "") -> str:
        """
        Wrapper conveniente: recibe base64 str, retorna str descifrado.
        """
        raw = base64.b64decode(b64_payload.encode("ascii"))
        return self.decrypt(
            raw,
            associated_data.encode("utf-8") if associated_data else b"",
        ).decode("utf-8")

    # ── Helpers privados ───────────────────────────────────────────────

    def _require_unlocked(self) -> None:
        if self._master_key is None:
            raise SecurityError(
                "KeyManager bloqueado. Llama unlock(passphrase) primero."
            )

    def _load_or_create_salt(self) -> bytes:
        """Carga el salt desde disco o genera uno nuevo."""
        if os.path.exists(self._salt_path):
            try:
                with open(self._salt_path, "rb") as f:
                    salt = f.read()
                if len(salt) != SALT_BYTES:
                    raise SecurityError(
                        f"Salt en {self._salt_path} tiene longitud incorrecta "
                        f"({len(salt)}B, esperado {SALT_BYTES}B)."
                    )
                logger.debug(
                    "Salt cargado desde disco",
                    extra={"op": "key_manager._load_or_create_salt",
                           "context": f"path={self._salt_path}"},
                )
                return salt
            except OSError as exc:
                raise SecurityError(
                    f"No se pudo leer el salt en {self._salt_path}: {exc}"
                ) from exc
        else:
            salt = secrets.token_bytes(SALT_BYTES)
            try:
                with open(self._salt_path, "wb") as f:
                    f.write(salt)
                logger.info(
                    "Nuevo salt generado y guardado",
                    extra={"op": "key_manager._load_or_create_salt",
                           "context": f"path={self._salt_path}"},
                )
            except OSError as exc:
                raise SecurityError(
                    f"No se pudo escribir el salt en {self._salt_path}: {exc}"
                ) from exc
            return salt

    @staticmethod
    def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
        """PBKDF2-HMAC-SHA256 con 600k iteraciones → 32 bytes."""
        return hashlib.pbkdf2_hmac(
            hash_name   = "sha256",
            password    = passphrase,
            salt        = salt,
            iterations  = PBKDF2_ITERATIONS,
            dklen       = KEY_BYTES,
        )

    # ── Fallback XOR+HMAC (sin cryptography) ──────────────────────────

    def _xor_encrypt(self, plaintext: bytes, nonce: bytes,
                     associated_data: bytes) -> bytes:
        """
        Cifrado de emergencia: XOR con keystream SHA-256 + HMAC-SHA256 tag.
        NO es AES-GCM. Es mejor que nada pero no debe usarse en producción.
        Formato: [ciphertext (N bytes)] [hmac-tag (32 bytes)]
        """
        keystream = self._sha256_keystream(nonce, len(plaintext))
        ct        = bytes(p ^ k for p, k in zip(plaintext, keystream))
        tag       = self._hmac_tag(ct, nonce, associated_data)
        return ct + tag

    def _xor_decrypt(self, ct_tag: bytes, nonce: bytes,
                     associated_data: bytes) -> bytes:
        if len(ct_tag) < 32:
            raise SecurityError("Payload fallback demasiado corto.")
        ct, tag = ct_tag[:-32], ct_tag[-32:]
        expected = self._hmac_tag(ct, nonce, associated_data)
        if not hmac.compare_digest(tag, expected):
            raise SecurityError("HMAC inválido — datos corruptos o clave incorrecta.")
        keystream = self._sha256_keystream(nonce, len(ct))
        return bytes(c ^ k for c, k in zip(ct, keystream))

    def _sha256_keystream(self, nonce: bytes, length: int) -> bytes:
        """Genera keystream pseudo-aleatorio derivado de master_key + nonce."""
        stream = b""
        counter = 0
        while len(stream) < length:
            block_input = self._master_key + nonce + struct.pack(">Q", counter)
            stream += hashlib.sha256(block_input).digest()
            counter += 1
        return stream[:length]

    def _hmac_tag(self, ciphertext: bytes, nonce: bytes,
                  associated_data: bytes) -> bytes:
        """HMAC-SHA256 sobre nonce + AAD_len + AAD + ciphertext."""
        h = hmac.new(self._master_key, digestmod=hashlib.sha256)
        h.update(nonce)
        h.update(struct.pack(">Q", len(associated_data)))
        h.update(associated_data)
        h.update(ciphertext)
        return h.digest()


# ══════════════════════════════════════════════════════════════════════
# SINGLETON GLOBAL (opcional)
# ══════════════════════════════════════════════════════════════════════

_global_km: Optional[KeyManager] = None


def get_key_manager(salt_path: str = "cognia_key.salt") -> KeyManager:
    """
    Retorna el KeyManager singleton de la sesión.

    Crea uno nuevo si no existe. El singleton vive mientras el proceso
    esté activo. Al reiniciar, la clave se pierde (correcto por diseño).
    """
    global _global_km
    if _global_km is None:
        _global_km = KeyManager(salt_path=salt_path)
    return _global_km
