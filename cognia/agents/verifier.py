"""
cognia/agents/verifier.py — Phase 23

Verifier 100% determinista. Sin LLM. Sin generación de texto.
Diagnostics estructurados (strings código:línea) que el Supervisor interpreta directamente.

Estrategias por tipo de output:
  - código Python: ast.parse() + code_executor.run() con timeout
  - texto/respuesta: similitud coseno vs KnowledgeGraph local (VectorCache)
  - genérico: longitud mínima + no vacío
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Optional


# ── Umbrales (en model_constants.py en Phase posterior; aquí como defaults) ──

SCORE_THRESHOLD      = 0.6    # por debajo → retry
KG_SIM_THRESHOLD     = 0.30   # umbral de similitud coseno mínima para texto
MIN_TEXT_LENGTH      = 20     # chars mínimos para una respuesta no vacía


@dataclass
class VerifyResult:
    passed:      bool
    score:       float
    fail_reason: Optional[str]   # None si passed; "CODE:SYNTAX_ERROR:line:N" | "TEXT:LOW_CONFIDENCE" | etc.


# ── Verificación de código ───────────────────────────────────────────────────

def _verify_code(content: str) -> VerifyResult:
    # 1. Syntax check (gratuito, <1ms)
    try:
        ast.parse(content)
    except SyntaxError as e:
        return VerifyResult(False, 0.0, f"CODE:SYNTAX_ERROR:line:{e.lineno}")

    # 2. Blocked imports (reutiliza el scanner de code_executor)
    try:
        from cognia_v3.interfaces.code_executor import _scan_blocked_imports
        blocked = _scan_blocked_imports(content)
        if blocked:
            return VerifyResult(False, 0.1, f"CODE:BLOCKED_IMPORT:{blocked[0]}")
    except ImportError:
        pass

    # 3. Ejecución en sandbox con timeout
    try:
        from cognia_v3.interfaces.code_executor import get_code_executor
        exec_result = get_code_executor().run(content, language="python")
        if exec_result.timed_out:
            return VerifyResult(False, 0.2, "CODE:EXEC_TIMEOUT")
        if not exec_result.success:
            short_err = (exec_result.errors or "unknown error")[:80].replace("\n", " ")
            return VerifyResult(False, 0.3, f"CODE:EXEC_FAILED:{short_err}")
        return VerifyResult(True, 0.9, None)
    except ImportError:
        # sin executor: syntax OK es suficiente
        return VerifyResult(True, 0.7, None)


# ── Verificación de texto ────────────────────────────────────────────────────

def _verify_text(content: str, vector_cache=None) -> VerifyResult:
    # 1. Longitud mínima
    if len(content.strip()) < MIN_TEXT_LENGTH:
        return VerifyResult(False, 0.0, "TEXT:TOO_SHORT")

    # 2. Similitud coseno contra VectorCache si está disponible
    if vector_cache is not None:
        try:
            from cognia.cognia_embedding import text_to_vector_fast
            import numpy as np
            emb = text_to_vector_fast(content)
            results = vector_cache.search(emb, top_k=1)
            if results:
                sim = float(getattr(results[0], "similarity", 0.0))
                if sim < KG_SIM_THRESHOLD:
                    return VerifyResult(False, sim, "TEXT:LOW_CONFIDENCE")
                return VerifyResult(True, sim, None)
        except Exception:
            pass

    # sin vector_cache: aceptar si tiene longitud suficiente
    return VerifyResult(True, 0.6, None)


# ── Verificación genérica ────────────────────────────────────────────────────

def _verify_generic(content: Any) -> VerifyResult:
    if content is None:
        return VerifyResult(False, 0.0, "GENERIC:NONE_OUTPUT")
    s = str(content).strip()
    if not s:
        return VerifyResult(False, 0.0, "GENERIC:EMPTY_OUTPUT")
    return VerifyResult(True, 0.6, None)


# ── Entry point ──────────────────────────────────────────────────────────────

def verify(
    output: Any,
    output_type: str = "generic",
    vector_cache=None,
) -> VerifyResult:
    """
    Verifica el output de un worker.

    Args:
        output:      el contenido a verificar (str para código/texto, cualquier cosa para genérico)
        output_type: "code" | "text" | "generic"
        vector_cache: instancia opcional de VectorCache para verificación semántica de texto

    Returns:
        VerifyResult con passed, score (0-1), y fail_reason estructurado
    """
    if output_type == "code":
        return _verify_code(str(output) if output is not None else "")
    if output_type == "text":
        return _verify_text(str(output) if output is not None else "", vector_cache)
    return _verify_generic(output)
