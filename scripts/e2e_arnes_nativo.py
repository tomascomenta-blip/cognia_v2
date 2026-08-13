# -*- coding: utf-8 -*-
"""GATE: las capacidades del arnés llegan al cerebro como TOOLS NATIVAS.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_arnes_nativo.py

Por qué existe (2026-08-12, pedido del dueño): que una capacidad esté
implementada y hasta registrada no significa que el modelo la reciba. Entre el
registry y el modelo hay tres traducciones que pueden romperse en silencio
—`catalogo_schemas()` → `schemas_para()` → el campo `tools` de
/v1/chat/completions— y el modo de fallo sería exactamente el que el dueño
quiere evitar: que el agente funcione "por instrucciones ciegas" del prompt en
vez de por tool-calling nativo.

Este gate habla con el llama-server DE VERDAD (no hay mocks) y exige:
  1. El perfil del modelo servido resuelve a régimen NATIVO.
  2. Las 4 tools del arnés están en el registry con `desc` y `params` ricos.
  3. Sus schemas OpenAI se generan bien (nombre, description, properties).
  4. El MODELO REAL, ante una tarea que las pide, responde con
     `finish_reason=tool_calls` y el nombre correcto — sin una sola línea de
     prosa explicándole cómo llamarlas.
  5. El puente inverso (`args_legacy`) reconstruye los args del protocolo texto.

Sale 0 sólo si pasan los 5. Cualquier otra cosa es 1 (y dice cuál falló).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOOLS_ARNES = ("recuperar", "consultar_oraculo", "buscar_herramientas",
               "deshacer_edicion")

# Las tools opt-in tienen que estar ENCENDIDAS para que el gate las vea: es lo
# que hace un usuario que quiere la capacidad, y así se prueba el camino real.
for flag in ("COGNIA_OFFLOAD", "COGNIA_ORACULO", "COGNIA_TOOLSEARCH",
             "COGNIA_UNDO_TOOL"):
    os.environ.setdefault(flag, "1")

fallos: list = []


def check(nombre: str, ok: bool, detalle: str = "") -> bool:
    print(f"  {'CHECK' if ok else 'FALLO'}  {nombre}" + (f" — {detalle}" if detalle else ""))
    if not ok:
        fallos.append(nombre)
    return ok


print("== 1. Regimen del modelo servido ==")
from cognia.agent.model_profiles import perfil_del_agente, verificar_arranque

perfil = perfil_del_agente(forzar=True)
print(f"  modelo: {perfil.get('modelo') or '(sin backend)'}")
check("el agente corre en regimen NATIVO", perfil.get("tools") == "nativo",
      f"tools={perfil.get('tools')}")
avisos = verificar_arranque(perfil)
check("sin avisos de coherencia perfil<->server", not avisos, "; ".join(avisos))

print("== 2. Registry: desc y params ricos ==")
from cognia.agent.tools import TOOLS, catalogo_schemas

for nombre in TOOLS_ARNES:
    spec = TOOLS.get(nombre) or {}
    check(f"'{nombre}' registrada", bool(spec))
    if spec:
        check(f"'{nombre}' tiene desc rica", len(spec.get("desc") or "") > 80,
              f"{len(spec.get('desc') or '')} chars")
        check(f"'{nombre}' declara params", bool(spec.get("params")))

print("== 3. Schemas OpenAI ==")
from cognia.agent.tool_schemas import schemas_para, args_legacy

schemas = schemas_para(set(TOOLS_ARNES))
por_nombre = {s.get("function", {}).get("name"): s for s in schemas}
for nombre in TOOLS_ARNES:
    s = por_nombre.get(nombre) or {}
    fn = s.get("function") or {}
    props = ((fn.get("parameters") or {}).get("properties") or {})
    check(f"schema de '{nombre}'", bool(fn.get("description")) and bool(props),
          f"{len(props)} propiedad(es)")

print("== 4. El MODELO REAL las invoca (sin instrucciones en prosa) ==")
from cognia.agent.chat_client import completar

CASOS = [
    ("recuperar",
     "La salida anterior era enorme y se guardo con el handle res:3f2a1b. "
     "Necesito ver las lineas 200 a 260 de esa salida."),
    ("buscar_herramientas",
     "Necesito convertir un fichero de audio a otro formato y no veo ninguna "
     "herramienta para eso en mi lista."),
]
for esperada, tarea in CASOS:
    resp = completar(
        [{"role": "system", "content": "Sos un agente con herramientas. Usa las "
                                       "que necesites."},
         {"role": "user", "content": tarea}],
        tools=schemas, max_tokens=1024,
        temperature=perfil.get("temperature", 0.7),
        top_p=perfil.get("top_p", 0.8), url=perfil.get("url", ""))
    llamadas = [tc.nombre for tc in (resp.tool_calls or [])]
    check(f"el modelo llama a '{esperada}'", esperada in llamadas,
          f"finish={resp.finish_reason} llamadas={llamadas or 'ninguna'}")
    if esperada in llamadas:
        tc = next(tc for tc in resp.tool_calls if tc.nombre == esperada)
        print(f"         argumentos: {json.dumps(tc.argumentos, ensure_ascii=False)}")
        print("== 5. Puente inverso al protocolo texto ==")
        try:
            legacy = args_legacy(tc.nombre, tc.argumentos)
            check(f"args_legacy('{tc.nombre}')", isinstance(legacy, str),
                  repr(legacy[:80]))
        except Exception as exc:
            check(f"args_legacy('{tc.nombre}')", False, str(exc))

print()
if fallos:
    print(f"ARNES NATIVO: {len(fallos)} fallo(s) -> {', '.join(fallos)}")
    raise SystemExit(1)
print("ARNES NATIVO: todo OK — las capacidades llegan al cerebro como tools nativas")
raise SystemExit(0)
