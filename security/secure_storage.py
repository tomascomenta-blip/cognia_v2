"""
security/secure_storage.py
==========================
SecureEpisodicMemory — wrapper cifrado sobre EpisodicMemory.

DISEÑO:
  - Es un drop-in wrapper de EpisodicMemory: misma interfaz pública.
  - Cifra el campo 'observation' antes de escribir a la DB.
  - Descifra en RAM al leer — el texto plano NUNCA se escribe a disco.
  - El vector (embedding) NO se cifra: es necesario para búsqueda semántica
    y ya pasa por privacidad diferencial en la capa MESH (network/privacy.py).
  - Si KeyManager no está desbloqueado, opera en modo transparente (sin cifrado)
    con un aviso — no falla, para no romper el flujo de Cognia.
  - El campo 'observation' en la DB tendrá prefijo "ENC:" cuando está cifrado,
    para distinguirlo de observaciones en texto plano de versiones anteriores.

CAPAS DE PRIVACIDAD (alineado con network/privacy.py):
  Capa 1 PRIVADO    → observation cifrada, NUNCA sale del dispositivo.
  Capa 2 SEMI-PRIV  → solo resúmenes del label (no la observación).
  Capa 3 PÚBLICO    → triples KG anonimizados (manejado por privacy.py).

RESTRICCIONES:
  - Sin dependencias nuevas fuera de requirements.txt + security/.
  - Retrocompatible: lee observaciones sin cifrar (legacy) correctamente.
  - No modifica el esquema de la DB (las columnas ya existen).
  - Thread-safe: hereda el pool de conexiones de EpisodicMemory.
"""

from __future__ import annotations

from typing import List, Optional

from cognia.memory.episodic import EpisodicMemory
from cognia.config import DB_PATH
from logger_config import get_logger

from .key_manager import KeyManager, SecurityError, get_key_manager

logger = get_logger(__name__)

# Prefijo en el campo observation para identificar datos cifrados
_ENC_PREFIX = "ENC:"


class SecureEpisodicMemory(EpisodicMemory):
    """
    Wrapper cifrado sobre EpisodicMemory.

    Extiende EpisodicMemory sin modificar su código: sobreescribe store()
    y retrieve_similar() para cifrar/descifrar el campo 'observation'
    transparentemente.

    Parámetros
    ----------
    db_path    : str — ruta a la base de datos SQLite.
    key_manager: KeyManager | None — gestor de claves activo.
                 Si es None, usa get_key_manager() (singleton global).
                 Si no está desbloqueado, opera sin cifrado con aviso.

    Uso
    ---
        km = KeyManager()
        km.unlock("mi_passphrase")

        mem = SecureEpisodicMemory(db_path="cognia_memory.db", key_manager=km)
        mem.store(observation="Hoy aprendí X", label="aprendizaje", vector=[...])

        resultados = mem.retrieve_similar(vec, top_k=5)
        # resultados[i]["observation"] ya viene descifrado en RAM
    """

    def __init__(
        self,
        db_path: str = DB_PATH,
        key_manager: Optional[KeyManager] = None,
    ):
        super().__init__(db_path=db_path)
        self._km = key_manager or get_key_manager()

        mode = "cifrado" if self._km.is_unlocked else "sin cifrado (KeyManager bloqueado)"
        logger.info(
            f"SecureEpisodicMemory iniciada — modo: {mode}",
            extra={
                "op":      "secure_storage.__init__",
                "context": f"db={db_path} unlocked={self._km.is_unlocked}",
            },
        )

    # ── Propiedades ────────────────────────────────────────────────────

    @property
    def encryption_active(self) -> bool:
        """True si el KeyManager está desbloqueado y el cifrado está activo."""
        return self._km.is_unlocked

    # ── store() — cifra observation antes de escribir ──────────────────

    def store(
        self,
        observation: str,
        label: str,
        vector: list,
        confidence: float = 0.5,
        importance: float = 1.0,
        emotion: dict = None,
        surprise: float = 0.0,
        context_tags: list = None,
    ) -> int:
        """
        Almacena un episodio con la observation cifrada.

        Si el KeyManager está bloqueado, almacena en texto plano con aviso.
        El vector (embedding) nunca se cifra — necesario para búsqueda vectorial.
        """
        encrypted_obs = self._encrypt_observation(observation)

        ep_id = super().store(
            observation  = encrypted_obs,
            label        = label,
            vector       = vector,
            confidence   = confidence,
            importance   = importance,
            emotion      = emotion,
            surprise     = surprise,
            context_tags = context_tags,
        )

        if self.encryption_active and ep_id > 0:
            logger.debug(
                "Episodio cifrado almacenado",
                extra={
                    "op":      "secure_storage.store",
                    "context": f"ep_id={ep_id} label={label} enc=True",
                },
            )
        return ep_id

    # ── retrieve_similar() — descifra observations al leer ─────────────

    def retrieve_similar(self, vector: list, top_k: int = 10) -> List[dict]:
        """
        Recupera episodios similares con las observations descifradas en RAM.

        El texto plano se descifra aquí y NUNCA se escribe de vuelta a disco.
        Los episodios legacy (sin prefijo ENC:) se retornan tal cual.
        """
        results = super().retrieve_similar(vector, top_k=top_k)
        return [self._decrypt_episode(ep) for ep in results]

    # ── get_due_for_review() — descifra al leer ────────────────────────

    def get_due_for_review(self) -> List[dict]:
        """Retorna episodios para repaso espaciado con observations descifradas."""
        results = super().get_due_for_review()
        return [self._decrypt_episode(ep) for ep in results]

    # ── Helpers privados ───────────────────────────────────────────────

    def _encrypt_observation(self, observation: str) -> str:
        """
        Cifra la observación si el KeyManager está desbloqueado.

        Retorna "ENC:<base64_payload>" si cifra, o el texto original si no.
        NUNCA lanza excepción — en caso de error, retorna el texto plano con aviso.
        """
        if not self._km.is_unlocked:
            logger.warning(
                "store: KeyManager bloqueado — guardando sin cifrado",
                extra={
                    "op":      "secure_storage._encrypt_observation",
                    "context": "enc=False",
                },
            )
            return observation

        # No re-cifrar si ya tiene prefijo (idempotente)
        if observation.startswith(_ENC_PREFIX):
            return observation

        try:
            b64 = self._km.encrypt_text(observation, associated_data="cognia_episodic")
            return _ENC_PREFIX + b64
        except SecurityError as exc:
            logger.warning(
                f"_encrypt_observation: fallo de cifrado, guardando en claro: {exc}",
                extra={
                    "op":      "secure_storage._encrypt_observation",
                    "context": f"err={exc}",
                },
            )
            return observation

    def _decrypt_observation(self, stored: str) -> str:
        """
        Descifra una observación almacenada.

        - Si tiene prefijo ENC: y el KM está desbloqueado → descifrar.
        - Si tiene prefijo ENC: y el KM está bloqueado → retorna placeholder.
        - Si no tiene prefijo → legacy, retornar tal cual.

        NUNCA escribe a disco. NUNCA lanza excepción no manejada.
        """
        if not stored.startswith(_ENC_PREFIX):
            return stored  # legacy / no cifrado

        if not self._km.is_unlocked:
            logger.warning(
                "_decrypt_observation: KeyManager bloqueado — datos inaccesibles",
                extra={
                    "op":      "secure_storage._decrypt_observation",
                    "context": "enc=True locked=True",
                },
            )
            return "[🔒 Cifrado — desbloquea con unlock(passphrase)]"

        b64_payload = stored[len(_ENC_PREFIX):]
        try:
            return self._km.decrypt_text(b64_payload, associated_data="cognia_episodic")
        except SecurityError as exc:
            logger.warning(
                f"_decrypt_observation: fallo de descifrado: {exc}",
                extra={
                    "op":      "secure_storage._decrypt_observation",
                    "context": f"err={exc}",
                },
            )
            return "[⚠️ Error al descifrar — datos corruptos o passphrase incorrecta]"

    def _decrypt_episode(self, episode: dict) -> dict:
        """
        Descifra el campo 'observation' de un episodio dict en una copia.

        No modifica el dict original. Retorna un nuevo dict con el campo
        'observation' descifrado y un campo extra '_encrypted' (bool).
        """
        if not episode:
            return episode

        obs = episode.get("observation", "")
        is_enc = obs.startswith(_ENC_PREFIX)

        ep_copy = dict(episode)
        ep_copy["observation"] = self._decrypt_observation(obs)
        ep_copy["_encrypted"]  = is_enc
        return ep_copy

    # ── Métodos de gestión ─────────────────────────────────────────────

    def reencrypt_all(self, new_passphrase: str) -> dict:
        """
        Re-cifra TODOS los episodios de la DB con una nueva passphrase.

        Útil para rotación de clave. Proceso:
          1. Descifrar cada episodio con la clave actual.
          2. Crear nuevo KeyManager con el nuevo salt y nueva clave.
          3. Re-cifrar y actualizar en la DB.

        Requiere que el KM esté desbloqueado (clave actual activa).

        ADVERTENCIA: operación pesada y destructiva. Hace backup implícito
        de los datos descifrados en RAM durante el proceso.

        Retorna dict con estadísticas: {'updated': N, 'skipped': N, 'errors': N}
        """
        if not self._km.is_unlocked:
            raise SecurityError("KeyManager bloqueado. Desbloquea primero.")

        from storage.db_pool import db_connect_pooled as db_connect

        conn = db_connect(self.db)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, observation FROM episodic_memory WHERE forgotten=0"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        updated = skipped = errors = 0
        new_km = KeyManager(salt_path=self._km._salt_path + ".new")
        new_km.unlock(new_passphrase)

        conn = db_connect(self.db)
        try:
            for ep_id, stored_obs in rows:
                try:
                    # Descifrar con clave actual
                    plain = self._decrypt_observation(stored_obs)
                    if plain.startswith("["):
                        # Era un error de descifrado, saltar
                        skipped += 1
                        continue

                    # Re-cifrar con nueva clave
                    new_enc = _ENC_PREFIX + new_km.encrypt_text(
                        plain, associated_data="cognia_episodic"
                    )
                    conn.execute(
                        "UPDATE episodic_memory SET observation=? WHERE id=?",
                        (new_enc, ep_id),
                    )
                    updated += 1
                except Exception as exc:
                    logger.warning(
                        f"reencrypt_all: error en episodio {ep_id}: {exc}",
                        extra={"op": "secure_storage.reencrypt_all",
                               "context": f"ep_id={ep_id} err={exc}"},
                    )
                    errors += 1

            conn.commit()
        finally:
            conn.close()

        # Reemplazar el salt file y actualizar el KM activo
        import os
        old_path = self._km._salt_path
        new_path = new_km._salt_path
        os.replace(new_path, old_path)
        self._km.lock()
        self._km.unlock(new_passphrase)

        logger.info(
            f"reencrypt_all: completado — {updated} actualizados, "
            f"{skipped} omitidos, {errors} errores",
            extra={"op": "secure_storage.reencrypt_all",
                   "context": f"updated={updated}"},
        )
        return {"updated": updated, "skipped": skipped, "errors": errors}

    def status(self) -> dict:
        """
        Retorna un dict con el estado de cifrado del almacenamiento.

        Útil para diagnóstico y para mostrar en el CLI con el comando 'seguridad'.
        """
        from storage.db_pool import db_connect_pooled as db_connect

        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0")
            total = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM episodic_memory "
                "WHERE forgotten=0 AND observation LIKE 'ENC:%'"
            )
            encrypted_count = c.fetchone()[0]
        finally:
            conn.close()

        plain_count = total - encrypted_count
        return {
            "km_unlocked":     self._km.is_unlocked,
            "km_mode":         self._km.mode,
            "total_episodes":  total,
            "encrypted":       encrypted_count,
            "plaintext":       plain_count,
            "coverage_pct":    round(encrypted_count / max(1, total) * 100, 1),
        }


# ══════════════════════════════════════════════════════════════════════
# FACTORY
# ══════════════════════════════════════════════════════════════════════

def get_secure_memory(
    db_path: str = DB_PATH,
    key_manager: Optional[KeyManager] = None,
) -> SecureEpisodicMemory:
    """
    Factory que retorna una instancia de SecureEpisodicMemory.

    Si no se pasa key_manager, usa el singleton global (get_key_manager()).
    """
    return SecureEpisodicMemory(db_path=db_path, key_manager=key_manager)
