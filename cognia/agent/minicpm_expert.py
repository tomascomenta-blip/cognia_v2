# -*- coding: utf-8 -*-
"""Experto de tooling de la flota: MiniCPM5-1B servido en GPU (F3 del goal assets IA).

El plan (PLAN_ASSETS_IA.md, subsistema B): una base ligera MiniCPM5-1B
(Apache-2.0, arq. Llama) + N LoRAs por rol. Este módulo sirve la BASE en GPU y
expone tool-calling (el rol "tooling/workflows"), que el cerebro 14B puede delegar.
El LoRA por rol (QLoRA con Unsloth) y el ruteo desde fleet_router llegan encima
de esto; aquí queda la pieza que de verdad CORRE el modelo.

PODA 2026-08-01 (limpieza de huerfanas): el camino de tool-calling XML del BASE
(`generar`, `tool_call`, `_parsear_tool_calls`) se ELIMINO. Razones: (a) cero
llamadores en el repo — el unico rol cableado a produccion es "tooling" via
`generar_accion` (cli.py:_run_agent_task, opt-in COGNIA_MINICPM_TOOLING=1);
(b) el protocolo del loop es texto ACCION + GBNF (tools_grammar), no tools
OpenAI/XML — cablear el XML exigiria un camino de decision NUEVO en cli.py;
(c) el BASE tool-calleaba IMPERFECTO (medido 2026-07-22: ~2/3 en pedidos
mixtos, flojo en español) mientras el LoRA de tooling mide 97% tool-match.
Si F4-F6 del plan de assets necesita el XML, esta en git (pre 2026-08-01).

Diseño (igual que cognia/assets): imports de torch/transformers PEREZOSOS -> importar
este módulo en un nodo CPU no carga nada; modelo cacheado; GPU-only (coherente con
"sin PyTorch en nodos": la flota generativa vive en GPU, como el subsistema de imagen);
kill-switch COGNIA_FLEET_GPU=0.

El rol "tooling" YA tiene su LoRA entrenado (generar_accion): dado el prompt del
agente (TOOLS_DOC + contexto) emite la `ACCION: <tool> <args>` en el formato REAL de
Cognia. Entrenado sobre el dataset SFT verificado del repo; medido base 0% -> LoRA
97% tool-match / 77% exact en held-out de tareas no vistas.

Env:
  COGNIA_MINICPM_MODEL            id/ruta del base (default openbmb/MiniCPM5-1B)
  COGNIA_MINICPM_TOOLING_ADAPTER  ruta del LoRA de tooling (default ~/.cognia/loras/minicpm_tooling)
"""
from __future__ import annotations

import os
import re

_MODELO_DEFECTO = "openbmb/MiniCPM5-1B"
_MODEL = None
_TOK = None
_MODEL_TOOLING = None  # base + adapter de tooling (ACCION), cacheado aparte

# Adapter del rol "tooling": LoRA que enseña a emitir el formato REAL de Cognia
# (ACCION: <tool> <args>). Entrenado sobre el dataset SFT verificado del repo
# (cognia_v3/training/tooluse). Medido: base 0% -> LoRA 97% tool-match en held-out.
_ADAPTER_TOOLING = os.environ.get(
    "COGNIA_MINICPM_TOOLING_ADAPTER",
    os.path.expanduser("~/.cognia/loras/minicpm_tooling"))


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


# Formato de accion del protocolo REAL de Cognia (documenta lo que emite el
# LoRA de tooling; el parseo de produccion lo hace loop.first_action_block).
_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", re.IGNORECASE | re.DOTALL)


def tooling_disponible() -> tuple:
    """(ok, motivo). El experto de tooling (ACCION) además del base necesita el
    adapter LoRA en disco."""
    ok, motivo = expert_disponible()
    if not ok:
        return ok, motivo
    if not os.path.isdir(_ADAPTER_TOOLING):
        return False, (f"falta el adapter de tooling en {_ADAPTER_TOOLING} "
                       f"(entrenar con cognia_v3/training/tooluse/train_minicpm_lora.py)")
    return True, "ok"


def _cargar_tooling():
    """Carga (una vez) base + adapter de tooling como PeftModel en GPU, eval."""
    global _MODEL_TOOLING
    if _MODEL_TOOLING is not None:
        return _MODEL_TOOLING, _cargar()[1]
    ok, motivo = tooling_disponible()
    if not ok:
        raise ExpertoError(f"experto de tooling no disponible: {motivo}")
    from peft import PeftModel
    base, tok = _cargar()
    _MODEL_TOOLING = PeftModel.from_pretrained(base, _ADAPTER_TOOLING).eval()
    return _MODEL_TOOLING, tok


def generar_accion(agent_prompt: str, *, system: str = None,
                   max_tokens: int = 200) -> str:
    """Rol tooling: dado el prompt del agente (TOOLS_DOC + contexto de la tarea, el
    MISMO que arma cli.py:_run_agent_task), emite la siguiente `ACCION: <tool> <args>`
    en el formato REAL de Cognia. Devuelve solo el primer bloque ACCION (recortado
    como en el loop de producción). El LoRA de tooling hace que MiniCPM5-1B hable
    este protocolo (el base no lo hace: 0% -> 97% tool-match, medido)."""
    import torch
    if system is None:
        from shattering.model_constants import COGNIA_SYSTEM_PROMPT
        system = COGNIA_SYSTEM_PROMPT
    model, tok = _cargar_tooling()
    mensajes = [{"role": "system", "content": system},
                {"role": "user", "content": agent_prompt}]
    inputs = tok.apply_chat_template(
        mensajes, tokenize=True, add_generation_prompt=True,
        return_tensors="pt", return_dict=True, enable_thinking=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=int(max_tokens),
                             do_sample=False, pad_token_id=tok.eos_token_id)
    texto = tok.decode(out[0, inputs["input_ids"].shape[1]:],
                       skip_special_tokens=True).strip()
    # Recorta al primer bloque ACCION (el mismo criterio que el loop del deploy).
    try:
        from cognia.agent.loop import first_action_block
        texto = first_action_block(texto)
    except Exception:
        pass
    return texto
