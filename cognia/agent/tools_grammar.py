# -*- coding: utf-8 -*-
"""
cognia/agent/tools_grammar.py — GBNF auto-generada del registry (harness #3)
============================================================================
Del research del harness (HARNESS_RESEARCH.md): cada retry por acción malformada
en CPU cuesta un prefill+decode completo (decenas de segundos), y el 3B degenera
generando NOMBRES DE TOOL BASURA ('start_busqueda_archivosuseralgmaps'...) que
fallan en cadena y crecen el prompt. Cognia ya validó GBNF en estructura cerrada
(JSON 7→0 errores, p=0.016). Acá se genera una gramática DESDE el registry de
tools que fuerza el turno de decisión a:

    ACCION: <tool VÁLIDA> <args libres>

Solo restringe el NOMBRE de la tool (la parte que degenera); los args quedan
libres (incluye multilínea de escribir_archivo). Se genera de las tools
permitidas (rol), así un sub-agente investigador no puede ni nombrar una tool
de escritura.

Opt-in por COGNIA_TOOL_GRAMMAR=1 (cambia el sampling; se activa tras validar
contra el server real, como toda estructura cerrada del repo).
"""
from __future__ import annotations

import os


def _escapar(nombre: str) -> str:
    """Escapa un nombre de tool para un literal GBNF (comillas dobles)."""
    return nombre.replace("\\", "\\\\").replace('"', '\\"')


def build_action_grammar(tool_names) -> str:
    """GBNF que fuerza 'ACCION: <tool> <args>' con tool ∈ tool_names.

    - tool: alternativa de literales (los nombres válidos).
    - rest: cualquier secuencia de chars (incluye saltos de línea: args
      multilínea de escribir_archivo no se rompen).
    Devuelve "" si no hay tools (sin gramática = comportamiento actual)."""
    nombres = [n for n in dict.fromkeys(tool_names) if n]   # únicos, orden
    if not nombres:
        return ""
    alternativas = " | ".join(f'"{_escapar(n)}"' for n in nombres)
    # [^\x00] = cualquier char salvo NUL -> incluye '\n' (args multilínea).
    return (
        'root ::= "ACCION: " tool rest\n'
        f"tool ::= {alternativas}\n"
        'rest ::= [^\\x00]*\n'
    )


def grammar_para(allowed=None) -> str | None:
    """Gramática de acción para el loop, o None si el opt-in está OFF.
    allowed = set de tools permitidas (rol del sub-agente) o None = todas."""
    if os.environ.get("COGNIA_TOOL_GRAMMAR", "").strip().lower() not in (
            "1", "on", "true", "yes"):
        return None
    try:
        from cognia.agent.tools import TOOLS
    except Exception:
        return None
    nombres = list(TOOLS.keys()) if allowed is None else [
        n for n in TOOLS if n in allowed]
    # 'responder' NO está en el registry (el loop lo intercepta) pero es el
    # cierre universal: la gramática SIEMPRE debe permitirlo o el agente no
    # puede terminar.
    if "responder" not in nombres:
        nombres.append("responder")
    g = build_action_grammar(nombres)
    return g or None
