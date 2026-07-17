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

Kill-switch: default ON (2026-07-10, tras cerrar el deploy: gate 8/8 +20pp +
probe 7B-greedy 4/4 + e2e single_number PASS); COGNIA_HEAVY_CODE=0 lo apaga.
Ante CUALQUIER falla (GGUF faltante, server no arranca) cae al resultado del 3B
y no reintenta (la tarea nunca queda sin código).

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
# Opt-in de tests: los tests de ESTE modulo (con fakes propios) lo setean a
# True para atravesar el guard anti-spawn de pytest de heavy_code_backend.
_PYTEST_REAL_OK = False


def _resolve_heavy_gguf():
    """Ruta al GGUF del 7B (Path) o None. Orden de resolución (cubre dev Y el
    producto instalado por pip, que NO tiene el repo):
      1) COGNIA_HEAVY_CODE_GGUF — override explícito (tests / ruta a mano).
      2) HEAVY_CODE_GGUF_PATH — lo persiste `cognia install-model --with-heavy-code`
         en ~/.cognia/config.env; apply_config() lo mete en os.environ al arrancar.
      3) resolve_gguf_path("7b") — el registry del repo (modo dev / desde fuente).
    Devuelve None si ninguna ruta existe en disco → heavy_code_backend cae al 3B."""
    from pathlib import Path
    for var in ("COGNIA_HEAVY_CODE_GGUF", "HEAVY_CODE_GGUF_PATH"):
        val = os.environ.get(var, "").strip()
        if val:
            p = Path(val)
            if p.is_file():
                return p
    from shattering.model_constants import resolve_gguf_path
    p = resolve_gguf_path("7b")
    return p if (p is not None and p.is_file()) else None


def _habilitado() -> bool:
    # Default ON tras cerrar el deploy (2026-07-10). Recorrido: el gate de CALIDAD
    # paso (results_code_gate7b_n40: 7B recupera 8/8 duras, +20pp 37.5->57.5%,
    # p=0.0078), pero 3 e2e mostraron que el flujo de produccion (best_of_n + juez
    # de tests visibles debiles) descartaba el candidato correcto del 7B. El probe
    # aislo la causa (JUEZ, no modelo ni prompt): el 7B GREEDY recupera 4/4. El fix
    # (escalar con greedy del 7B, no best_of_n) cerro el deploy: e2e single_number
    # PASS (codigo correcto, RAM 7.8GB<10GB). El escalado es reactivo + pre-filtrado
    # por dificultad, asi que solo paga latencia (7B ~2.2 tok/s) en codigo duro que
    # el 3B ya fallo. COGNIA_HEAVY_CODE=0 lo apaga. En instalaciones sin el GGUF 7B,
    # heavy_code_backend() cae a None -> fallback al 3B (default ON no rompe).
    return os.environ.get("COGNIA_HEAVY_CODE", "").strip().lower() not in (
        "0", "off", "false", "no")


def heavy_code_backend() -> Optional[_LlamaServerBackend]:
    """Backend del 7B para escalar código duro, o None (→ el resultado se queda
    en el 3B). Habilitado por COGNIA_HEAVY_CODE (default ON; =0 lo apaga); el GGUF
    se resuelve con _resolve_heavy_gguf() (override / config instalada / registry).
    Singleton lazy; una falla de arranque se cachea (_HEAVY_FAILED) y no reintenta.

    Puerto 8092 dedicado (8088=3B fleet, 8090=portero, 8091=deep-cascade): el
    7B vive en OTRO proceso, cero interacción con el hot-swap LoRA del 3B."""
    global _HEAVY_SINGLETON, _HEAVY_FAILED
    if not _habilitado():
        return None
    # Higiene del instrumento (mismo patron que fleet_registry, 2026-07-16):
    # bajo pytest NO se arranca el 7B real; los tests del escalado
    # monkeypatchean esta funcion, los de ESTE modulo setean
    # _PYTEST_REAL_OK=True (sus fakes cubren backend/resolucion), y uno que
    # quiera el 7B de verdad setea el override explicito
    # COGNIA_HEAVY_CODE_GGUF (no la var de config instalada, que
    # apply_config exportaria y burlaria el guard).
    if (os.environ.get("PYTEST_CURRENT_TEST") and not _PYTEST_REAL_OK
            and not os.environ.get("COGNIA_HEAVY_CODE_GGUF")):
        return None
    if _HEAVY_SINGLETON is not None:
        return _HEAVY_SINGLETON
    if _HEAVY_FAILED:
        return None
    gguf = _resolve_heavy_gguf()
    if gguf is None:
        logger.warning("[heavy_code] COGNIA_HEAVY_CODE activo pero no hay GGUF 7B "
                       "(ni HEAVY_CODE_GGUF_PATH ni el registry del repo); el "
                       "código duro se queda en el 3B. Instalá con: "
                       "cognia install-model --with-heavy-code")
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
    try:
        from cognia.first_run import apply_config
        apply_config()   # config.env instalado (fix auditoria 2026-07-15)
    except Exception:
        pass
    sys.exit(_self_check())
