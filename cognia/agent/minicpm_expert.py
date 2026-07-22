# -*- coding: utf-8 -*-
"""Experto de tooling de la flota: MiniCPM5-1B servido en GPU (F3 del goal assets IA).

El plan (PLAN_ASSETS_IA.md, subsistema B): una base ligera MiniCPM5-1B
(Apache-2.0, arq. Llama) + N LoRAs por rol. Este módulo sirve la BASE en GPU y
expone tool-calling (el rol "tooling/workflows"), que el cerebro 14B puede delegar.
El LoRA por rol (QLoRA con Unsloth) y el ruteo desde fleet_router llegan encima
de esto; aquí queda la pieza que de verdad CORRE el modelo.

MiniCPM5-1B es un modelo de RAZONAMIENTO (emite <think>...</think>). Para tooling
conviene `pensar=False` (más rápido y, medido, menos alucinación de parámetros en
el 1B). Emite las llamadas en su formato XML nativo:
    <function name="F"><param name="A">valor</param></function>
`_parsear_tool_calls` lo convierte a [{'name': F, 'arguments': {A: valor}}].

LIMITACIÓN medida (2026-07-22, verificación GPU): el BASE tool-callea pero de forma
IMPERFECTA — ~2/3 en pedidos mixtos, y flojea en ESPAÑOL (leyó "comprar pan" como
"pan of food" en inglés y no reconoció crear_reminder aun estando disponible). Emite
y parsea bien las llamadas correctas; lo que falta es FIABILIDAD. Eso es justo lo que
endurece el LoRA de tooling del plan (adapter de openbmb/MiniCPM4-MCP, que bate a
GPT-4o, o QLoRA con xLAM/Glaive). Esta pieza sirve el base; el LoRA por rol va encima.

Diseño (igual que cognia/assets): imports de torch/transformers PEREZOSOS -> importar
este módulo en un nodo CPU no carga nada; modelo cacheado; GPU-only (coherente con
"sin PyTorch en nodos": la flota generativa vive en GPU, como el subsistema de imagen);
kill-switch COGNIA_FLEET_GPU=0.

Env:
  COGNIA_MINICPM_MODEL  id/ruta del base (default openbmb/MiniCPM5-1B)
"""
from __future__ import annotations

import os
import re

_MODELO_DEFECTO = "openbmb/MiniCPM5-1B"
_MODEL = None
_TOK = None


class ExpertoError(RuntimeError):
    """Fallo del experto de tooling GPU (mensaje accionable)."""


def _modelo_id() -> str:
    return os.environ.get("COGNIA_MINICPM_MODEL", _MODELO_DEFECTO)


def expert_disponible() -> tuple:
    """(ok, motivo). No carga el modelo: solo chequea prerequisitos baratos."""
    if os.environ.get("COGNIA_FLEET_GPU", "1") == "0":
        return False, "desactivado por COGNIA_FLEET_GPU=0"
    try:
        import torch  # noqa
    except Exception:
        return False, "torch no instalado (usa venv312gpu)"
    if not torch.cuda.is_available():
        return False, "sin CUDA/GPU (la flota generativa es GPU-only)"
    try:
        import transformers  # noqa
    except Exception:
        return False, "transformers no instalado (usa venv312gpu)"
    return True, "ok"


def _cargar():
    """Carga (una vez) MiniCPM5-1B + tokenizer en GPU, bf16, eval."""
    global _MODEL, _TOK
    if _MODEL is not None:
        return _MODEL, _TOK
    ok, motivo = expert_disponible()
    if not ok:
        raise ExpertoError(f"experto de tooling no disponible: {motivo}")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    mid = _modelo_id()
    _TOK = AutoTokenizer.from_pretrained(mid, trust_remote_code=True)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        mid, trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()
    return _MODEL, _TOK


# --- parseo de tool-calls (formato XML nativo de MiniCPM5). Puro texto: testeable
#     sin GPU. ---
_FUNC_RE = re.compile(r'<function\s+name="([^"]+)"\s*>(.*?)</function>', re.DOTALL)
_PARAM_RE = re.compile(r'<param\s+name="([^"]+)"\s*>(.*?)</param>', re.DOTALL)
_CDATA_RE = re.compile(r'^\s*<!\[CDATA\[(.*?)\]\]>\s*$', re.DOTALL)


def _desenvolver_cdata(v: str) -> str:
    m = _CDATA_RE.match(v)
    return m.group(1) if m else v.strip()


def _parsear_tool_calls(texto: str) -> list:
    """Extrae las llamadas del formato XML de MiniCPM5 ->
    [{'name': str, 'arguments': {str: str}}]. Lista vacía si no hay ninguna."""
    llamadas = []
    for nombre, cuerpo in _FUNC_RE.findall(texto or ""):
        args = {k: _desenvolver_cdata(v) for k, v in _PARAM_RE.findall(cuerpo)}
        llamadas.append({"name": nombre, "arguments": args})
    return llamadas


def _quitar_think(texto: str) -> str:
    """Quita un bloque <think>...</think> inicial (modo razonamiento)."""
    return re.sub(r"^\s*<think>.*?</think>\s*", "", texto or "", flags=re.DOTALL).strip()


# Tokens de control de chat a quitar cuando conservamos los tags de función.
_CTRL_TOKENS = ("<|im_end|>", "<|im_start|>", "<|endoftext|>")


def _generar_raw(mensajes, tools=None, max_tokens=256, temperature=0.0,
                 pensar=False, conservar_tags=False) -> str:
    """Corre el modelo sobre mensajes (+tools opcional) y devuelve el texto crudo.

    conservar_tags: MiniCPM5 registra <function>/<param> como tokens ESPECIALES;
    skip_special_tokens=True los borraría y rompería el parseo del tool-call. Para
    tool-calling decodificamos SIN saltar especiales y quitamos solo los tokens de
    control de chat, preservando la estructura XML de la llamada."""
    import torch
    model, tok = _cargar()
    inputs = tok.apply_chat_template(
        mensajes, tools=tools, tokenize=True, add_generation_prompt=True,
        return_tensors="pt", return_dict=True, enable_thinking=pensar).to("cuda")
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=int(max_tokens), do_sample=temperature > 0,
            temperature=temperature or None, top_p=0.9,
            pad_token_id=tok.eos_token_id)
    n = inputs["input_ids"].shape[1]
    texto = tok.decode(out[0, n:], skip_special_tokens=not conservar_tags)
    if conservar_tags:
        for t in _CTRL_TOKENS:
            texto = texto.replace(t, "")
    return texto.strip()


def generar(prompt: str, *, system: str = "", max_tokens: int = 256,
            temperature: float = 0.0, pensar: bool = False) -> str:
    """Completion de chat con MiniCPM5-1B. Compatible con el patrón LlmFn del repo
    (prompt, system, max_tokens, temperature). `pensar=True` deja el razonamiento
    <think>; por defecto se descarta y se devuelve solo la respuesta."""
    mensajes = []
    if system:
        mensajes.append({"role": "system", "content": system})
    mensajes.append({"role": "user", "content": prompt})
    texto = _generar_raw(mensajes, max_tokens=max_tokens, temperature=temperature,
                         pensar=pensar)
    return texto if pensar else _quitar_think(texto)


def tool_call(prompt: str, tools: list, *, system: str = "", max_tokens: int = 256,
              temperature: float = 0.0, pensar: bool = False) -> list:
    """Pide al experto que elija herramienta(s) para el pedido y devuelve las
    llamadas parseadas: [{'name', 'arguments'}]. `tools` en formato OpenAI
    (type/function/parameters). Lista vacía si el modelo no llamó a ninguna."""
    mensajes = []
    if system:
        mensajes.append({"role": "system", "content": system})
    mensajes.append({"role": "user", "content": prompt})
    texto = _generar_raw(mensajes, tools=tools, max_tokens=max_tokens,
                         temperature=temperature, pensar=pensar,
                         conservar_tags=True)
    return _parsear_tool_calls(texto)
