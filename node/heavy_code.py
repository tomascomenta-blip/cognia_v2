r"""
node/heavy_code.py — Especialista de CAPACIDAD 7B para código duro (MoM fase 4)
=============================================================================
El único especialista de CAPACIDAD del repo: Qwen2.5-Coder-7B Q4_K_M. En código
duro mide 50% pass@1 solo, y en CASCADA 3B→7B (correr 3B, reintentar en 7B lo
que falla los tests) sube a 60% vs 40% del 3B — +20pp MEDIDO (benchmark_code,
results_code_hard_cascade_20260612_2006.json) que hoy vive SOLO en el benchmark.

Esta capa lo lleva al agente de producción como 2º server DEDICADO (mismo molde
que el portero 0.5B: singleton lazy, falla cacheada, kill-switch), en un puerto
propio (8092) para NO tocar el fleet del 3B (:8088, LoRA hot-swap accion/portero
intactos). El 7B es base pura (lora_path=None): aporta capacidad cruda, no el
adapter de formato.

Coherente con la tesis del programa (5 negativas de fine-tune): la CAPACIDAD se
compra con cómputo en inferencia, no con más adapters. El 7B es cómputo, no
entrenamiento.

Política de RAM: LAZY-LOAD-USAR-CERRAR por defecto (el caller hace close() tras
la tarea) → RAM steady-state 0. El i3 tiene ~12GB: 3B (1.93GB) + 7B (4.68GB) +
portero + KVs residentes = riesgo OOM, por eso NO se mantiene warm salvo opt-in
COGNIA_HEAVY_KEEPWARM (solo tras medir headroom).

Kill-switch: OPT-IN (default OFF); COGNIA_HEAVY_CODE=1 lo habilita. El gate de
calidad pasó (2026-07-10: 7B recupera 8/8 duras, +20pp, p=0.0078) pero el flujo
de producción no reprodujo esa ganancia (gap de prompt gate-vs-deploy, 2 e2e);
queda opt-in hasta cerrar ese gap. Ante CUALQUIER falla (GGUF faltante, server
no arranca) cae al resultado del 3B y no reintenta (la tarea nunca queda sin
código).

Auto-verificación REAL:  COGNIA_HEAVY_CODE=1 venv312\Scripts\python.exe -m node.heavy_code
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from node.llama_backend import _LlamaServerBackend

logger = logging.getLogger(__name__)

_HEAVY_PORT = int(os.environ.get("COGNIA_HEAVY_CODE_PORT", "8092"))
_HEAVY_CTX = int(os.environ.get("HEAVY_CODE_CTX_SIZE", "4096"))

# Singleton lazy + falla cacheada (no reintentar el arranque cada tarea dura).
_HEAVY_SINGLETON: Optional[_LlamaServerBackend] = None
_HEAVY_FAILED = False


def _habilitado() -> bool:
    # OPT-IN (default OFF): COGNIA_HEAVY_CODE=1 lo habilita. El gate de CALIDAD paso
    # (results_code_gate7b_n40, 2026-07-10: el 7B recupera 8/8 tareas duras
    # verificadas, +20pp 37.5->57.5%, p=0.0078) PERO el e2e de produccion NO
    # materializo esa ganancia: el flujo de generar_codigo (prompt envuelto + BoN)
    # no reproduce el greedy del gate que si extrae el rendimiento del 7B (2 e2e:
    # burst_balloons y single_number, ambas RECUPERADAS en el gate, fallaron por el
    # flujo de produccion). Default ON impondria latencia (7B ~2.2 tok/s) sin
    # capturar el +20pp de forma confiable -> queda opt-in hasta cerrar el gap de
    # prompt (ver ANALISIS_GATE_7B.md, "trabajo pendiente"). El mecanismo funciona
    # (escala, RAM 8.25GB<10GB medido); lo que falta es el prompt de deploy.
    return os.environ.get("COGNIA_HEAVY_CODE", "").strip().lower() in (
        "1", "true", "on", "yes")


def heavy_code_backend() -> Optional[_LlamaServerBackend]:
    """Backend del 7B para escalar código duro, o None (→ el resultado se queda
    en el 3B). Habilitado por COGNIA_HEAVY_CODE (default OFF). Singleton lazy;
    una falla de arranque se cachea (_HEAVY_FAILED) y no se reintenta.

    Puerto 8092 dedicado (8088=3B fleet, 8090=portero, 8091=deep-cascade): el
    7B vive en OTRO proceso, cero interacción con el hot-swap LoRA del 3B."""
    global _HEAVY_SINGLETON, _HEAVY_FAILED
    if not _habilitado():
        return None
    if _HEAVY_SINGLETON is not None:
        return _HEAVY_SINGLETON
    if _HEAVY_FAILED:
        return None
    from shattering.model_constants import resolve_gguf_path
    gguf = resolve_gguf_path("7b")
    if gguf is None or not gguf.is_file():
        logger.warning("[heavy_code] COGNIA_HEAVY_CODE activo pero falta el GGUF 7B "
                       "(%s); el código duro se queda en el 3B", gguf)
        _HEAVY_FAILED = True
        return None
    try:
        _HEAVY_SINGLETON = _LlamaServerBackend(
            gguf, port=_HEAVY_PORT, ctx_size=_HEAVY_CTX, lora_path=None)
        return _HEAVY_SINGLETON
    except Exception as exc:
        logger.warning("[heavy_code] el 7B no arrancó (%s); el código duro se "
                       "queda en el 3B", exc)
        _HEAVY_FAILED = True
        return None


def close_heavy_code() -> None:
    """Para el server 7B y libera la RAM (lazy-load-usar-cerrar). Opt-out con
    COGNIA_HEAVY_KEEPWARM=1 (mantener warm; solo con headroom de RAM medido).
    No-op si no hay server o si se pidió mantenerlo caliente."""
    global _HEAVY_SINGLETON
    if _HEAVY_SINGLETON is None:
        return
    if os.environ.get("COGNIA_HEAVY_KEEPWARM", "").strip().lower() in (
            "1", "true", "on", "yes"):
        return
    try:
        _HEAVY_SINGLETON.stop()
    except Exception:
        pass
    _HEAVY_SINGLETON = None


def _self_check() -> int:
    """Verificación REAL: arranca el 7B, genera código y cierra."""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ["COGNIA_HEAVY_CODE"] = "1"
    os.environ.pop("COGNIA_HEAVY_KEEPWARM", None)
    b = heavy_code_backend()
    if b is None:
        print("CHECK FALLO: heavy_code_backend() devolvió None (¿falta el GGUF 7B?)")
        return 1
    try:
        prompt = ("<|im_start|>user\nEscribe SOLO ```python``` con la función "
                  "es_par(n) que devuelve True si n es par.<|im_end|>\n"
                  "<|im_start|>assistant\n")
        txt = (b.generate(prompt, max_tokens=64, temperature=0.0) or "").strip()
        ok = "def es_par" in txt
        print(f"CHECK [{'OK' if ok else 'FALLO'}] 7B en :{_HEAVY_PORT} generó: {txt[:120]!r}")
        return 0 if ok else 1
    finally:
        close_heavy_code()
        print("[heavy_code] server 7B cerrado (RAM liberada)")


if __name__ == "__main__":
    import sys
    sys.exit(_self_check())
