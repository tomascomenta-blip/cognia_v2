# -*- coding: utf-8 -*-
"""Tool `repo_a_prompt` para el agente (ingenieria inversa de repos).

Wrapper fino sobre cognia/knowledge/repo_reverse.py: parsea la linea ACCION,
inyecta el infer_fn (UNICA via LLM permitida: _orch(ctx).infer, la misma de
_resumir/_generar_codigo — cero HTTP, cero proveedores, cero router) y mapea
las excepciones a RESULTADO ... ERROR legible. Patron identico a image_tools/
screen_tools: register(tool) llamado desde tools.py bajo opt-in
COGNIA_REPO_REVERSE=1.

max_tokens=1200, no 300: leccion "presupuesto-tokens-razonamiento" — todo
max_tokens debe cubrir el PENSAMIENTO del razonador ademas de las 120-220
palabras de salida.
"""
from __future__ import annotations

import re
from pathlib import Path

from cognia.agents.workers import dev_tools
from cognia.knowledge.repo_reverse import repo_a_prompt


def register(tool):
    @tool("repo_a_prompt",
          "repo_a_prompt <ruta-o-url> [| salida]  -- reconstruye la "
          "especificacion/prompt de un repo (local o GitHub)")
    def _repo_a_prompt(args, ctx):
        parts = re.split(r"\s*\|\s*", args, maxsplit=1)
        entrada = parts[0].strip()
        if not entrada:
            return ("RESULTADO repo_a_prompt ERROR: uso: repo_a_prompt "
                    "<ruta-o-url> [| archivo_salida]")

        def infer_fn(system, user):
            # Import LAZY: tools.py ya esta cargado en runtime, sin ciclo.
            from cognia.agent.tools import _orch
            res = _orch(ctx).infer(user, system=system, max_tokens=1200,
                                   temperature=0.2)
            return res.text or ""

        dir_clones = Path(dev_tools._root_actual()) / ".repo_reverse"
        try:
            res = repo_a_prompt(entrada, infer_fn=infer_fn,
                                dir_clones=dir_clones)
        except (ValueError, RuntimeError) as exc:
            return f"RESULTADO repo_a_prompt ERROR: {exc}"

        extra = ""
        if len(parts) == 2 and parts[1].strip():
            from cognia.agent.tools import _disp
            try:
                # write_file y no write_text directo: mismo gate de
                # confinamiento (resolve_write_path adentro) MAS el backup
                # .bak y el arbitro de colisiones al pisar un archivo.
                info = dev_tools.write_file(parts[1].strip(), res["texto"])
                extra = f"; guardado en {_disp(Path(info['path']))}"
                if info["backup"]:
                    extra += " (anterior en .bak)"
            except ValueError as exc:
                extra = f"; AVISO escritura: {exc}"

        aviso = f"; AVISO: {res['aviso']}" if res["aviso"] else ""
        return (f"RESULTADO repo_a_prompt (modo={res['modo']}{aviso}{extra}):\n"
                f"{res['texto']}")
