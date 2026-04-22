"""
cognia/user_profile.py — Perfiles Cognitivos por Usuario
=========================================================
Implementa el sistema de personalización descrito en la Fase 6:

  • CognitiveProfile   — preferencias de atención, estilo, historial (rollback)
  • UserProfileManager — persistencia en SQLite + carga/guardado por user_id
  • Integración con AttentionSystem — pesos dinámicos por perfil

ROLLBACK ("Control Z cognitivo"):
  profile.snapshot()               → guarda estado actual
  profile.rollback(steps=1)        → deshace N cambios de perfil
  profile.history()                → lista de snapshots disponibles

INTEGRACIÓN EN cognia.py:
  from cognia.user_profile import get_profile_manager
  self.profile_manager = get_profile_manager(self.db)
  self.user_profile = self.profile_manager.load("default")

  # Adaptar AttentionSystem con pesos del perfil:
  self.attention = self.user_profile.build_attention_system()

  # Guardar cambios:
  self.profile_manager.save(self.user_profile)

FEEDBACK → ACTUALIZACIÓN AUTOMÁTICA:
  self.user_profile.update_from_feedback("más detalle")
  self.profile_manager.save(self.user_profile)
"""

from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════

MAX_SNAPSHOTS      = 10       # máximo de estados guardados para rollback
FEEDBACK_DELTA     = 0.02     # cuánto cambia un peso por cada feedback
WEIGHT_MIN         = 0.05     # peso mínimo de cualquier dimensión de atención
WEIGHT_MAX         = 0.75     # peso máximo

VALID_FEEDBACK     = frozenset([
    "más detalle",     "más corto",
    "correcto",        "incorrecto",
    "útil",            "no útil",
    "más técnico",     "más simple",
])

VALID_STYLES       = frozenset(["balanced", "concise", "detailed", "socratic"])
VALID_LANGUAGES    = frozenset(["es", "en", "pt", "fr", "de"])


# ══════════════════════════════════════════════════════════════════════
# PERFIL COGNITIVO
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CognitiveProfile:
    """
    Perfil cognitivo de un usuario.

    Los attention_weights determinan cómo AttentionSystem pondera memorias.
    El sistema normaliza automáticamente los pesos para que sumen 1.0.
    """

    user_id: str = "default"

    # Pesos del sistema de atención (se normalizan a suma=1.0)
    attention_weights: dict = field(default_factory=lambda: {
        "semantic":   0.40,
        "emotion":    0.25,
        "recency":    0.20,
        "frequency":  0.15,
    })

    # Estilo de respuesta preferido
    response_style: str = "balanced"      # "concise" | "detailed" | "socratic"
    preferred_language: str = "es"
    domain_interests: list = field(default_factory=list)

    # Métricas de uso
    total_interactions: int = 0
    feedback_counts: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Historial de snapshots (para rollback)
    _snapshots: list = field(default_factory=list, repr=False)

    # ─────────────────────────────────────────────────────────────────
    # ROLLBACK
    # ─────────────────────────────────────────────────────────────────

    def snapshot(self, label: str = "") -> int:
        """
        Guarda el estado actual como checkpoint para rollback posterior.
        Retorna el número de version guardado.
        """
        snap = {
            "version":            len(self._snapshots),
            "timestamp":          time.time(),
            "label":              label,
            "attention_weights":  dict(self.attention_weights),
            "response_style":     self.response_style,
            "preferred_language": self.preferred_language,
            "domain_interests":   list(self.domain_interests),
        }
        self._snapshots.append(snap)
        # Mantener solo los últimos MAX_SNAPSHOTS
        if len(self._snapshots) > MAX_SNAPSHOTS:
            self._snapshots = self._snapshots[-MAX_SNAPSHOTS:]
        logger.debug(
            f"Snapshot guardado: version={snap['version']} label='{label}'",
            extra={"op": "profile.snapshot", "context": f"user={self.user_id}"},
        )
        return snap["version"]

    def rollback(self, steps: int = 1) -> bool:
        """
        Deshace los últimos N cambios de perfil.
        Retorna True si el rollback fue exitoso.
        """
        if not self._snapshots:
            logger.warning(
                "Rollback solicitado pero no hay snapshots disponibles",
                extra={"op": "profile.rollback", "context": f"user={self.user_id}"},
            )
            return False

        idx = max(0, len(self._snapshots) - steps)
        target = self._snapshots[idx]

        self.attention_weights  = dict(target["attention_weights"])
        self.response_style     = target["response_style"]
        self.preferred_language = target["preferred_language"]
        self.domain_interests   = list(target["domain_interests"])
        self.updated_at         = datetime.now().isoformat()

        # Eliminar snapshots más nuevos que el target
        self._snapshots = self._snapshots[:idx]

        logger.info(
            f"Rollback aplicado a version={target['version']} label='{target['label']}'",
            extra={"op": "profile.rollback", "context": f"user={self.user_id} steps={steps}"},
        )
        return True

    def history(self) -> list:
        """Lista los snapshots disponibles para rollback."""
        return [
            {
                "version":   s["version"],
                "label":     s["label"],
                "timestamp": datetime.fromtimestamp(s["timestamp"]).isoformat(),
            }
            for s in reversed(self._snapshots)
        ]

    # ─────────────────────────────────────────────────────────────────
    # ACTUALIZACIÓN POR FEEDBACK
    # ─────────────────────────────────────────────────────────────────

    def update_from_feedback(self, feedback: str) -> bool:
        """
        Ajusta los pesos de atención según el feedback del usuario.
        Guarda snapshot automáticamente antes de modificar.

        feedback válidos: ver VALID_FEEDBACK

        Lógica de ajuste:
          "más detalle"  → ↑ semantic, ↓ recency
          "más corto"    → ↓ semantic, ↑ recency
          "más técnico"  → ↑ semantic, ↓ emotion
          "más simple"   → ↓ semantic, ↑ frequency
          "correcto"     → refuerzo leve de semantic
          "incorrecto"   → reducción leve de semantic
        """
        if feedback not in VALID_FEEDBACK:
            logger.warning(
                f"Feedback desconocido: '{feedback}'",
                extra={"op": "profile.update_from_feedback",
                       "context": f"user={self.user_id}"},
            )
            return False

        self.snapshot(label=f"pre:{feedback}")

        w = self.attention_weights
        d = FEEDBACK_DELTA

        if feedback == "más detalle":
            w["semantic"]   = min(WEIGHT_MAX, w["semantic"]  + d)
            w["recency"]    = max(WEIGHT_MIN, w["recency"]   - d)
        elif feedback == "más corto":
            w["semantic"]   = max(WEIGHT_MIN, w["semantic"]  - d)
            w["recency"]    = min(WEIGHT_MAX, w["recency"]   + d)
        elif feedback == "más técnico":
            w["semantic"]   = min(WEIGHT_MAX, w["semantic"]  + d)
            w["emotion"]    = max(WEIGHT_MIN, w["emotion"]   - d)
        elif feedback == "más simple":
            w["semantic"]   = max(WEIGHT_MIN, w["semantic"]  - d * 0.5)
            w["frequency"]  = min(WEIGHT_MAX, w["frequency"] + d * 0.5)
        elif feedback == "correcto":
            w["semantic"]   = min(WEIGHT_MAX, w["semantic"]  + d * 0.5)
        elif feedback == "incorrecto":
            w["semantic"]   = max(WEIGHT_MIN, w["semantic"]  - d * 0.5)
        elif feedback == "útil":
            w["frequency"]  = min(WEIGHT_MAX, w["frequency"] + d * 0.5)
        elif feedback == "no útil":
            w["recency"]    = min(WEIGHT_MAX, w["recency"]   + d * 0.5)

        self._normalize_weights()
        self.updated_at = datetime.now().isoformat()
        self.feedback_counts[feedback] = self.feedback_counts.get(feedback, 0) + 1

        logger.info(
            f"Perfil actualizado por feedback='{feedback}' weights={w}",
            extra={"op": "profile.update_from_feedback",
                   "context": f"user={self.user_id}"},
        )
        return True

    def set_style(self, style: str) -> bool:
        """Cambia el estilo de respuesta. Retorna False si el estilo es inválido."""
        if style not in VALID_STYLES:
            return False
        self.snapshot(label=f"style:{self.response_style}→{style}")
        self.response_style = style
        self.updated_at = datetime.now().isoformat()
        return True

    def add_interest(self, domain: str):
        """Añade un dominio de interés si no existe ya."""
        domain = domain.strip().lower()
        if domain and domain not in self.domain_interests:
            self.snapshot(label=f"interest+{domain}")
            self.domain_interests.append(domain)
            self.updated_at = datetime.now().isoformat()

    # ─────────────────────────────────────────────────────────────────
    # INTEGRACIÓN CON AttentionSystem
    # ─────────────────────────────────────────────────────────────────

    def build_attention_system(self):
        """
        Construye un AttentionSystem con los pesos del perfil.
        Uso:
            self.attention = self.user_profile.build_attention_system()
        """
        try:
            from cognia.attention import AttentionSystem
            w = self.attention_weights
            return AttentionSystem(
                w_semantic=w.get("semantic",  0.40),
                w_emotion=w.get("emotion",    0.25),
                w_recency=w.get("recency",    0.20),
                w_frequency=w.get("frequency", 0.15),
            )
        except ImportError:
            logger.warning(
                "AttentionSystem no disponible — perfil no puede construir atención",
                extra={"op": "profile.build_attention_system",
                       "context": f"user={self.user_id}"},
            )
            return None

    # ─────────────────────────────────────────────────────────────────
    # SERIALIZACIÓN
    # ─────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "user_id":             self.user_id,
            "attention_weights":   dict(self.attention_weights),
            "response_style":      self.response_style,
            "preferred_language":  self.preferred_language,
            "domain_interests":    list(self.domain_interests),
            "total_interactions":  self.total_interactions,
            "feedback_counts":     dict(self.feedback_counts),
            "created_at":          self.created_at,
            "updated_at":          self.updated_at,
            "_snapshots":          list(self._snapshots),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CognitiveProfile":
        p = cls(user_id=data.get("user_id", "default"))
        p.attention_weights   = data.get("attention_weights",  p.attention_weights)
        p.response_style      = data.get("response_style",     p.response_style)
        p.preferred_language  = data.get("preferred_language", p.preferred_language)
        p.domain_interests    = data.get("domain_interests",   [])
        p.total_interactions  = data.get("total_interactions", 0)
        p.feedback_counts     = data.get("feedback_counts",    {})
        p.created_at          = data.get("created_at",         p.created_at)
        p.updated_at          = data.get("updated_at",         p.updated_at)
        p._snapshots          = data.get("_snapshots",         [])
        p._normalize_weights()
        return p

    # ─────────────────────────────────────────────────────────────────
    # PRIVADO
    # ─────────────────────────────────────────────────────────────────

    def _normalize_weights(self):
        """Asegura que los pesos sumen exactamente 1.0."""
        w     = self.attention_weights
        total = sum(w.values())
        if total > 0:
            self.attention_weights = {k: round(v / total, 6) for k, v in w.items()}

    def __repr__(self) -> str:
        w = self.attention_weights
        return (
            f"CognitiveProfile(user={self.user_id!r} style={self.response_style!r} "
            f"sem={w.get('semantic',0):.2f} emo={w.get('emotion',0):.2f} "
            f"rec={w.get('recency',0):.2f} freq={w.get('frequency',0):.2f} "
            f"snapshots={len(self._snapshots)})"
        )


# ══════════════════════════════════════════════════════════════════════
# MANAGER — persistencia en SQLite
# ══════════════════════════════════════════════════════════════════════

class UserProfileManager:
    """
    Persiste CognitiveProfile en la tabla `user_profile` de SQLite.
    Un perfil = una fila con key='profile:{user_id}' y value=JSON.

    La tabla user_profile ya existe en el schema de cognia/database.py.
    """

    def __init__(self, db_path: str):
        self.db = db_path
        self._lock = threading.Lock()
        self._cache: dict[str, CognitiveProfile] = {}

    def load(self, user_id: str = "default") -> CognitiveProfile:
        """
        Carga el perfil desde SQLite.
        Si no existe, crea uno nuevo con valores por defecto.
        """
        if user_id in self._cache:
            return self._cache[user_id]

        key = f"profile:{user_id}"
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db)
            row = conn.execute(
                "SELECT value FROM user_profile WHERE key=?", (key,)
            ).fetchone()
            conn.close()

            if row and row[0]:
                data    = json.loads(row[0])
                profile = CognitiveProfile.from_dict(data)
                logger.info(
                    f"Perfil cargado desde DB: user={user_id}",
                    extra={"op": "profile_manager.load",
                           "context": f"user={user_id} style={profile.response_style}"},
                )
            else:
                profile = CognitiveProfile(user_id=user_id)
                logger.info(
                    f"Perfil nuevo creado: user={user_id}",
                    extra={"op": "profile_manager.load",
                           "context": f"user={user_id} (new)"},
                )

        except Exception as exc:
            log_db_error(logger, "profile_manager.load", exc,
                         extra_ctx=f"user={user_id}")
            profile = CognitiveProfile(user_id=user_id)

        with self._lock:
            self._cache[user_id] = profile
        return profile

    def save(self, profile: CognitiveProfile) -> bool:
        """Persiste el perfil en SQLite. Retorna True si tuvo éxito."""
        key   = f"profile:{profile.user_id}"
        value = json.dumps(profile.to_dict())
        now   = datetime.now().isoformat()

        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db)
            conn.execute("""
                INSERT INTO user_profile (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                               updated_at=excluded.updated_at
            """, (key, value, now))
            conn.close()

            with self._lock:
                self._cache[profile.user_id] = profile

            logger.debug(
                f"Perfil guardado: user={profile.user_id}",
                extra={"op": "profile_manager.save",
                       "context": f"user={profile.user_id}"},
            )
            return True

        except Exception as exc:
            log_db_error(logger, "profile_manager.save", exc,
                         extra_ctx=f"user={profile.user_id}")
            return False

    def delete(self, user_id: str) -> bool:
        """Elimina el perfil de un usuario."""
        key = f"profile:{user_id}"
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db)
            conn.execute("DELETE FROM user_profile WHERE key=?", (key,))
            conn.close()
            with self._lock:
                self._cache.pop(user_id, None)
            return True
        except Exception as exc:
            log_db_error(logger, "profile_manager.delete", exc,
                         extra_ctx=f"user={user_id}")
            return False

    def list_users(self) -> list[str]:
        """Lista todos los user_id con perfil guardado."""
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db)
            rows = conn.execute(
                "SELECT key FROM user_profile WHERE key LIKE 'profile:%'"
            ).fetchall()
            conn.close()
            return [r[0].replace("profile:", "") for r in rows]
        except Exception as exc:
            log_db_error(logger, "profile_manager.list_users", exc)
            return []


# ══════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════

_MANAGER: Optional[UserProfileManager] = None
_MANAGER_LOCK = threading.Lock()


def get_profile_manager(db_path: str = None) -> UserProfileManager:
    """
    Retorna la instancia singleton del manager de perfiles.
    Uso en cognia.py:
        from cognia.user_profile import get_profile_manager
        self.profile_manager = get_profile_manager(self.db)
        self.user_profile = self.profile_manager.load("default")
    """
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                if db_path is None:
                    try:
                        from cognia.config import DB_PATH
                        db_path = DB_PATH
                    except ImportError:
                        db_path = "cognia_memory.db"
                _MANAGER = UserProfileManager(db_path)
    return _MANAGER
