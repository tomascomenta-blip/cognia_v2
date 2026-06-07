"""
cognia/persona/persona_advisor.py
===================================
Analiza el perfil del usuario y recomienda una persona de comunicacion.
Sin LLM calls -- basado en heuristicas de patterns y topics.
"""

from __future__ import annotations

# Importaciones al nivel de modulo para permitir mockeo en tests.
# Envueltas en try/except porque la BD puede no estar disponible en entornos de test.
try:
    from cognia.profile.user_profile_builder import UserProfileBuilder
except Exception:  # pragma: no cover
    UserProfileBuilder = None  # type: ignore[assignment,misc]

try:
    from cognia.persona.persona_manager import PersonaManager
except Exception:  # pragma: no cover
    PersonaManager = None  # type: ignore[assignment,misc]

# Mapping de query patterns -> persona recomendada
_PATTERN_TO_PERSONA: dict[str, str] = {
    "asks_code": "tecnico",
    "asks_how":  "detallado",
    "asks_why":  "formal",
    "asks_list": "conciso",
    "asks_what": "detallado",
}

# Mapping de topic keywords -> persona recomendada (lowercase match)
_TOPIC_TO_PERSONA: dict[str, str] = {
    "python":     "tecnico",
    "javascript": "tecnico",
    "code":       "tecnico",
    "machine":    "tecnico",
    "fastapi":    "tecnico",
    "writing":    "formal",
    "design":     "casual",
    "learning":   "detallado",
    "datos":      "formal",
    "data":       "formal",
}


class PersonaAdvisor:
    """
    Recomienda y opcionalmente aplica la persona de comunicacion mas adecuada
    para un usuario dado, basandose en su perfil estadistico.
    Sin LLM calls -- heuristicas de voting sobre patterns y topics.
    """

    def recommend(self, user_id: str) -> dict:
        """
        Analiza el perfil del usuario y retorna una recomendacion.

        Returns:
            {
              "recommended_persona": str,   # nombre de persona
              "confidence": float,          # 0.0-1.0
              "reason": str,               # explicacion legible
              "already_set": bool          # True si el usuario ya tiene esa persona
            }
        """
        profile = self._get_profile(user_id)

        patterns = profile.get("query_patterns", []) if profile else []
        topics   = profile.get("top_topics", [])     if profile else []

        persona, confidence = self._score_persona(patterns, topics)

        # Comprobar si la persona ya esta configurada
        already_set = False
        try:
            if PersonaManager is not None:
                pm = PersonaManager()
                current = pm.get_persona(user_id)
                already_set = current.get("persona", "default") == persona
        except Exception:
            pass

        # Construir razon legible
        if confidence == 0.0:
            reason = "Sin datos de perfil suficientes para recomendar una persona."
        else:
            matched_patterns = [p for p in patterns if _PATTERN_TO_PERSONA.get(p) == persona]
            matched_topics   = [
                t["term"] for t in topics
                if any(t["term"].lower().startswith(k) for k in _TOPIC_TO_PERSONA
                       if _TOPIC_TO_PERSONA[k] == persona)
            ]
            parts = []
            if matched_patterns:
                parts.append(f"patrones: {', '.join(matched_patterns)}")
            if matched_topics:
                parts.append(f"temas: {', '.join(matched_topics[:3])}")
            reason = f"Persona '{persona}' recomendada por " + "; ".join(parts) + f" (confianza {confidence:.0%})."

        return {
            "recommended_persona": persona,
            "confidence":          round(confidence, 3),
            "reason":              reason,
            "already_set":         already_set,
        }

    def auto_apply(self, user_id: str, min_confidence: float = 0.6) -> dict:
        """
        Aplica automaticamente la persona recomendada si:
          - confidence >= min_confidence
          - el usuario no tiene ya esa persona configurada

        Returns:
            {"applied": bool, "persona": str, "confidence": float}
        """
        rec = self.recommend(user_id)
        persona    = rec["recommended_persona"]
        confidence = rec["confidence"]

        if confidence < min_confidence:
            return {"applied": False, "persona": persona, "confidence": confidence}

        if rec["already_set"]:
            return {"applied": False, "persona": persona, "confidence": confidence}

        # Persona aun no configurada y confianza suficiente -- aplicar
        try:
            if PersonaManager is None:
                raise RuntimeError("PersonaManager not available")
            pm = PersonaManager()
            pm.set_persona(user_id, persona)
            return {"applied": True, "persona": persona, "confidence": confidence}
        except Exception:
            return {"applied": False, "persona": persona, "confidence": confidence}

    # ── Internals ──────────────────────────────────────────────────────

    def _get_profile(self, user_id: str) -> dict | None:
        """Carga perfil via UserProfileBuilder.get_profile(). Retorna None en caso de error."""
        try:
            if UserProfileBuilder is None:
                return None
            builder = UserProfileBuilder()
            return builder.get_profile(user_id)
        except Exception:
            return None

    def _score_persona(
        self,
        patterns: list[str],
        topics: list[dict],
    ) -> tuple[str, float]:
        """
        Cuenta votos por persona usando _PATTERN_TO_PERSONA y _TOPIC_TO_PERSONA.

        - Cada pattern reconocido: 1 voto
        - Cada topic cuyo term (lowercase) comienza con una key de _TOPIC_TO_PERSONA: 1 voto

        Retorna (persona_con_mas_votos, votos/total_votos).
        Default ("default", 0.0) si 0 votos.
        """
        votes: dict[str, int] = {}

        for p in patterns:
            mapped = _PATTERN_TO_PERSONA.get(p)
            if mapped:
                votes[mapped] = votes.get(mapped, 0) + 1

        for topic in topics:
            term = topic.get("term", "").lower()
            for key, mapped in _TOPIC_TO_PERSONA.items():
                if term.startswith(key):
                    votes[mapped] = votes.get(mapped, 0) + 1
                    break  # un voto por topico maximo

        if not votes:
            return ("default", 0.0)

        total = sum(votes.values())
        best_persona = max(votes, key=lambda k: votes[k])
        confidence = votes[best_persona] / total
        return (best_persona, confidence)
