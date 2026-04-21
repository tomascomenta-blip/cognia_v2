"""
language_corrector.py — Cognia Paso 3
=======================================
Normaliza y limpia texto en dos contextos:

  1. ENTRADA (labels y observaciones del TeacherInterface)
     - Elimina caracteres de control, normaliza espacios
     - Convierte labels a snake_case limpio
     - Detecta idioma para consistencia

  2. SALIDA (respuestas del EngineResult antes de llegar al usuario)
     - Elimina frases de relleno redundantes que el LLM genera
     - Asegura que la respuesta no empiece/termine con artefactos
     - Detecta respuestas truncadas y las marca para el engine
     - Normaliza la puntuación al final de párrafos

Sin dependencias externas — usa únicamente la biblioteca estándar.
Diseño deliberadamente ligero para no añadir latencia al pipeline.
"""

import re
import unicodedata
from typing import Tuple

# ── Patrones de relleno del LLM a eliminar ────────────────────────────
_LLM_FILLER_PATTERNS = [
    # Frases de arranque vacías
    r"^(Claro[,!.]?\s*)",
    r"^(Por supuesto[,!.]?\s*)",
    r"^(¡Por supuesto!\s*)",
    r"^(Entendido[,!.]?\s*)",
    r"^(Desde luego[,!.]?\s*)",
    r"^(¡Claro que sí!\s*)",
    r"^(Como IA[,]?\s*(te diré|puedo decirte|debo mencionar)[,]?\s*)",
    r"^(Como modelo de lenguaje[,]?\s*)",
    r"^(En tanto IA[,]?\s*)",
    # Cierres vacíos al final
    r"(\s*¿(Hay algo más|Puedo ayudarte|Tienes alguna otra pregunta)[^?]*\?)\s*$",
    r"(\s*Si (tienes|necesitas) (más|alguna) (pregunta|duda|información)[^.]*\.)\s*$",
    r"(\s*Espero (haber|que esto) (ayudado|sea útil|te haya sido útil)[^.]*\.)\s*$",
    # En inglés
    r"^(Sure[,!.]?\s*)",
    r"^(Of course[,!.]?\s*)",
    r"^(Certainly[,!.]?\s*)",
    r"^(As an AI[,]?\s*)",
    r"(\s*Is there anything else[^?]*\?)\s*$",
    r"(\s*I hope (this|that) (helps|was helpful)[^.]*\.)\s*$",
]

_COMPILED_FILLERS = [re.compile(p, re.IGNORECASE | re.MULTILINE)
                     for p in _LLM_FILLER_PATTERNS]

# ── Patrones de respuesta truncada ────────────────────────────────────
_TRUNCATION_SIGNALS = [
    r"\.\.\.$",           # termina con ...
    r"[a-záéíóúñ]\s*$",  # termina en medio de palabra (sin puntuación)
    r",\s*$",             # termina en coma
]
_COMPILED_TRUNCATION = [re.compile(p, re.IGNORECASE) for p in _TRUNCATION_SIGNALS]

# ── Label snake_case: solo letras, números, guión bajo ───────────────
_LABEL_CLEAN = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")
_MULTI_UNDER = re.compile(r"_+")


class LanguageCorrector:
    """
    Corrector ligero para entradas y salidas del pipeline de Cognia.

    No modifica semántica — solo limpia artefactos tipográficos y
    frases de relleno del LLM.
    """

    # ── API para TeacherInterface (entrada) ───────────────────────────

    def clean(self, text: str) -> str:
        """
        Limpia una observación de entrada:
          - Elimina caracteres de control (excepto newlines)
          - Normaliza espacios múltiples
          - Strip de los extremos
        """
        if not text:
            return text
        # Eliminar caracteres de control salvo \n y \t
        text = "".join(
            c for c in text
            if unicodedata.category(c)[0] != "C" or c in "\n\t"
        )
        text = _MULTI_SPACE.sub(" ", text).strip()
        return text

    def normalize_label(self, label: str) -> str:
        """
        Convierte un label a snake_case normalizado:
          "Color Azul"  → "color_azul"
          "color-azul"  → "color_azul"
          "MAMÍFEROS"   → "mamiferos"
          "café con leche" → "cafe_con_leche"
        """
        if not label:
            return label
        # Normalizar unicode: é → e, ñ → n, etc. solo para el label
        label = unicodedata.normalize("NFKD", label)
        label = "".join(
            c for c in label
            if not unicodedata.combining(c)
        )
        label = label.lower()
        label = _LABEL_CLEAN.sub(" ", label)   # eliminar puntuación
        label = label.replace("-", "_").replace(" ", "_")
        label = _MULTI_UNDER.sub("_", label).strip("_")
        return label

    def detect_language(self, text: str) -> str:
        """
        Detección de idioma muy ligera basada en heurísticas léxicas.
        Retorna "es" o "en". Suficiente para user_profile.
        """
        text_lower = text.lower()
        es_markers = sum(1 for w in ["que", "es", "de", "en", "por", "con",
                                      "para", "una", "los", "las"]
                         if f" {w} " in text_lower or text_lower.startswith(f"{w} "))
        en_markers = sum(1 for w in ["the", "is", "of", "in", "to", "and",
                                      "a", "for", "with", "that"]
                         if f" {w} " in text_lower or text_lower.startswith(f"{w} "))
        return "es" if es_markers >= en_markers else "en"

    # ── API para LanguageEngine (salida) ─────────────────────────────

    def clean_response(self, text: str) -> Tuple[str, bool]:
        """
        Limpia una respuesta del engine antes de entregarla al usuario.

        Retorna (texto_limpio, is_truncated).
          - is_truncated=True señala al engine que considere pedir
            regeneración o añadir un sufijo de continuación.

        Operaciones:
          1. Eliminar frases de relleno del LLM
          2. Normalizar puntuación al final
          3. Detectar truncamiento
          4. Strip final
        """
        if not text:
            return text, False

        cleaned = text

        # 1. Eliminar frases de relleno
        for pattern in _COMPILED_FILLERS:
            cleaned = pattern.sub("", cleaned)

        # 2. Normalizar múltiples líneas en blanco
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # 3. Normalizar espacios antes de puntuación
        cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)

        cleaned = cleaned.strip()

        # 4. Detectar truncamiento
        is_truncated = any(p.search(cleaned) for p in _COMPILED_TRUNCATION)

        # 5. Si termina en palabra sin puntuación y no es una lista, añadir punto
        if cleaned and not is_truncated:
            last_char = cleaned[-1]
            if last_char not in ".!?…\"'»)":
                cleaned += "."

        return cleaned, is_truncated

    def fix_truncated(self, text: str) -> str:
        """
        Intenta reparar una respuesta truncada:
          - Si termina en '...' lo elimina y añade una nota
          - Si termina en coma, la convierte en punto
          - Si termina en palabra sin puntuación, añade punto
        """
        text = text.rstrip()
        if text.endswith("..."):
            text = text[:-3].rstrip() + "."
        elif text.endswith(","):
            text = text[:-1] + "."
        elif text and text[-1] not in ".!?":
            text += "."
        return text

    def validate_response(self, text: str) -> dict:
        """
        Valida una respuesta y retorna un reporte de calidad.
        Usado por el PromptOptimizer para feedback de evolución.

        Retorna dict con:
          is_empty, is_truncated, has_filler, word_count, quality_score (0-1)
        """
        if not text or not text.strip():
            return {"is_empty": True, "is_truncated": False,
                    "has_filler": False, "word_count": 0, "quality_score": 0.0}

        has_filler   = any(p.search(text) for p in _COMPILED_FILLERS[:6])
        is_truncated = any(p.search(text.strip()) for p in _COMPILED_TRUNCATION)
        word_count   = len(text.split())

        score = 1.0
        if has_filler:    score -= 0.15
        if is_truncated:  score -= 0.30
        if word_count < 5: score -= 0.25
        score = max(0.0, round(score, 2))

        return {
            "is_empty":    False,
            "is_truncated": is_truncated,
            "has_filler":   has_filler,
            "word_count":   word_count,
            "quality_score": score,
        }
