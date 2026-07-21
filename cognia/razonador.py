"""
cognia/razonador.py
===================
Razonamiento profundo con un modelo *thinking* dedicado (goal 2026-07-21).

El modelo principal (7B instruct) responde bien pero no "piensa largo". Este
modulo levanta un segundo llama-server con un modelo de la familia Qwen3 con
razonamiento nativo (<think>...</think>) y responde preguntas LARGAS y
complejas usando la generacion infinita ya medida del backend
(generate_long: auto-continuacion con guarda de ctx por cola deslizante).

Eleccion de modelo por perfil (env-overridable con COGNIA_RAZONADOR_GGUF):
  - GPU (LLAMA_N_GPU_LAYERS>0): Qwen3-4B-Thinking-2507 Q4_K_M (~2.4GB en VRAM;
    convive con el 7B principal: 7B~6.9GB + 4B~5GB < 16GB de la 5060 Ti).
  - CPU: Qwen3-1.7B Q4_K_M (thinking integrado, tamano que un CPU aguanta).

Puerto 8093: el principal usa 8088, portero 8090, heavy 8092.
Concreto: funciones planas + un singleton lazy. Sin tocar el agente ni el
camino feliz (/hacer) — cero danio colateral por construccion.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_PUERTO = 8093
_MODELOS = Path.home() / ".cognia" / "models"
_GPU_GGUF = _MODELOS / "Qwen3-4B-Thinking-2507-Q4_K_M.gguf"
_CPU_GGUF = _MODELOS / "Qwen3-1.7B-Q4_K_M.gguf"

_backend = None          # singleton lazy del LlamaServerBackend del razonador
_backend_gguf = None     # con que GGUF se levanto (para invalidar si cambia)


def _es_gpu() -> bool:
    try:
        return int(os.environ.get("LLAMA_N_GPU_LAYERS", "0") or 0) > 0
    except ValueError:
        return False


def _aplicar_config() -> None:
    """Carga ~/.cognia/config.env (LLAMA_N_GPU_LAYERS, SERVER_PATH...) ANTES de
    decidir el perfil — sin esto un proceso suelto elegia el GGUF de CPU aunque
    la maquina fuera GPU (cazado en el primer E2E: header decia CPU/1.7B)."""
    try:
        from cognia.first_run import apply_config
        apply_config()
    except Exception:
        pass


def gguf_razonador() -> Path:
    """El GGUF del razonador para ESTA maquina. Error accionable si falta."""
    _aplicar_config()
    env = os.environ.get("COGNIA_RAZONADOR_GGUF", "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise FileNotFoundError(
            f"COGNIA_RAZONADOR_GGUF apunta a un fichero inexistente: {p}")
    p = _GPU_GGUF if _es_gpu() else _CPU_GGUF
    if p.is_file():
        return p
    # el otro perfil puede estar descargado (mejor razonar lento que no razonar)
    alt = _CPU_GGUF if _es_gpu() else _GPU_GGUF
    if alt.is_file():
        return alt
    raise FileNotFoundError(
        f"No hay modelo de razonamiento en {_MODELOS} "
        f"(esperaba {p.name} o {alt.name}). Descargalo o exporta "
        f"COGNIA_RAZONADOR_GGUF.")


def obtener_backend():
    """LlamaServerBackend del razonador (arranca/adopta el server en :8093)."""
    global _backend, _backend_gguf
    gguf = gguf_razonador()   # (aplica config.env por dentro)
    if _backend is not None and _backend_gguf == gguf:
        return _backend
    from node.llama_backend import LlamaBackend, _LlamaServerBackend
    # ctx: 32k en GPU (thinking largo); 8k en CPU (RAM y velocidad realistas)
    ctx = 32768 if _es_gpu() else 8192
    # la fachada LlamaBackend aporta generate_long (la generacion infinita)
    _backend = LlamaBackend(_LlamaServerBackend(gguf, port=_PUERTO, ctx_size=ctx))
    _backend_gguf = gguf
    return _backend


def descartar() -> None:
    """Suelta el server del razonador (libera VRAM/RAM)."""
    global _backend, _backend_gguf
    b, _backend, _backend_gguf = _backend, None, None
    try:
        impl = getattr(b, "_impl", b)
        if impl is not None and getattr(impl, "_proc", None) is not None:
            impl._proc.terminate()
    except Exception:
        pass


_RE_THINK = re.compile(r"<think>(.*?)</think>", re.S)


def separar_pensamiento(texto: str) -> tuple[str, str]:
    """(pensamiento, respuesta). Qwen3-Thinking-2507 NO emite el tag de
    apertura <think> (solo el cierre); Qwen3 base emite ambos. Cubrir los dos:
    si hay </think> sin <think>, todo lo previo al cierre es pensamiento."""
    m = _RE_THINK.search(texto)
    if m:
        return m.group(1).strip(), _RE_THINK.sub("", texto).strip()
    if "</think>" in texto:
        pens, _, resp = texto.partition("</think>")
        return pens.strip(), resp.strip()
    return "", texto.strip()


def razonar(pregunta: str, print_fn=None, max_tokens: int = None,
            temperature: float = 0.6) -> Optional[dict]:
    """
    Responde una pregunta con razonamiento profundo y generacion infinita.

    Devuelve {"respuesta", "pensamiento", "tokens", "rounds", "stop_reason"}
    o None si el backend fallo de entrada. print_fn (opcional) recibe progreso:
    el PENSAMIENTO en lineas "[detail]...[/detail]" (el control remoto las
    clasifica como actividad plegable; el CLI las pinta en gris) y nada mas —
    la respuesta final la muestra el caller.
    """
    be = obtener_backend()
    if max_tokens is None:
        # GPU aguanta pensar MUY largo; CPU acota para no tardar una era
        max_tokens = 24000 if _es_gpu() else 6000
    prompt = (f"<|im_start|>user\n{pregunta.strip()}<|im_end|>\n"
              f"<|im_start|>assistant\n")

    emitidas = [0]     # cuantos chars del pensamiento ya se emitieron

    def _on_chunk(ronda, toks, total, stop, chunk):
        if not callable(print_fn):
            return
        # progreso honesto por ronda + streaming del pensamiento nuevo
        print_fn(f"[detail]razonando... ronda {ronda}, {total} tokens[/detail]")

    out = be.generate_long(prompt, max_total_tokens=max_tokens,
                           chunk_tokens=2048, temperature=temperature,
                           on_chunk=_on_chunk)
    if out is None:
        return None
    pensamiento, respuesta = separar_pensamiento(out["text"])
    if callable(print_fn) and pensamiento:
        # el pensamiento completo, plegable en el remoto (bloque actividad)
        for linea in pensamiento.splitlines():
            if linea.strip():
                print_fn(f"[detail]{linea.strip()}[/detail]")
    return {"respuesta": respuesta or out["text"].strip(),
            "pensamiento": pensamiento,
            "tokens": out.get("total_tokens"),
            "rounds": out.get("rounds"),
            "stop_reason": out.get("stop_reason")}
