"""
b1_confound_repro.py — el confound del 14% ("el modelo no devolvio HTML"),
reproducido o cerrado.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b1_confound_repro.py

HIPOTESIS (pre-escrita, 2026-07-25 23:0x, antes de correr): el fallo
intermitente del camino Ollama era AGOTAMIENTO DE CONTEXTO con el num_ctx por
defecto (4096): un modelo de razonamiento gasta todo el presupuesto pensando y
devuelve contenido vacio con finish_reason=length. El dato que la sugiere: las
7 muestras muertas de b1_duras fallaron todas a ~51s (51.0-51.6, una 67) —
demasiado constante para red o carga, demasiado corto para el timeout de 500s —
y la corrida brutal n=6 POSTERIOR al fix laguna-16k tuvo 0 fallos en 48
muestras (P(0 fallos en 24 de laguna | tasa 14%) ~ 2.7%).

Las dos hipotesis que el dueno ya descarto (nombre del modelo; num_ctx) se
descartaron con LLAMADAS DIRECTAS cortas — que no agotan el contexto. Este
script usa el CAMINO REAL (generator._preguntar_constructor, mismo prompt de
sistema, misma tarea) y registra finish_reason + longitud del contenido.

DISENO:
  BRAZO A (control positivo): laguna-xs-2.1 (num_ctx default 4096), tarea
    'serpiente' (la que murio 3/3), n=3. PREDICE: contenido vacio o sin fence,
    finish_reason=length, ~40-70s.
  BRAZO B (config actual): laguna-16k, tareas serpiente + undo_redo, n=4 cada
    una. PREDICE: 8/8 con HTML.

LECTURA (pre-registrada):
  - A reproduce el fallo Y B sale 8/8         -> CERRADO: era el contexto.
  - A reproduce y B falla alguna               -> hay OTRO fallo ademas; medir B mas.
  - A NO reproduce                             -> la hipotesis es falsa; el
    confound sigue abierto y queda dicho.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import os
import urllib.request as req


def llamar(modelo: str, idea: str) -> dict:
    """El camino real: mismo endpoint, mismo system, mismos max_tokens que
    generator._preguntar_constructor — pero devolviendo el crudo entero para
    poder mirar finish_reason y usage en vez de solo el content."""
    from cognia.program_creator.generator import _SISTEMA_WEB
    cuerpo = json.dumps({
        "model": modelo,
        "messages": [{"role": "system", "content": _SISTEMA_WEB},
                     {"role": "user", "content": idea}],
        "temperature": 0.2,
        "max_tokens": 12000,
    }).encode("utf-8")
    peticion = req.Request("http://127.0.0.1:11434/v1/chat/completions",
                           data=cuerpo,
                           headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with req.urlopen(peticion, timeout=500) as r:
            datos = json.loads(r.read().decode("utf-8"))
        el = datos["choices"][0]
        contenido = el["message"].get("content") or ""
        return {"ok": True, "s": round(time.time() - t0, 1),
                "finish_reason": el.get("finish_reason"),
                "chars": len(contenido),
                "con_fence": "```" in contenido,
                "con_html": "<" in contenido,
                "usage": datos.get("usage", {})}
    except Exception as exc:
        return {"ok": False, "s": round(time.time() - t0, 1),
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    duras = json.loads((RAIZ / "scripts" / "b1_tareas_duras.json")
                       .read_text(encoding="utf-8"))["tareas"]
    ideas = {t["id"]: t["idea"] for t in duras}
    res = {"brazo_a": [], "brazo_b": []}

    print("=" * 74)
    print("BRAZO A — control positivo: laguna-xs-2.1 (num_ctx default), "
          "serpiente, n=3")
    print("=" * 74, flush=True)
    for i in range(3):
        r = llamar("laguna-xs-2.1", ideas["serpiente"])
        res["brazo_a"].append({"tarea": "serpiente", **r})
        print(f"  serpiente r{i+1}: {json.dumps(r, ensure_ascii=False)}",
              flush=True)

    print()
    print("=" * 74)
    print("BRAZO B — config actual: laguna-16k, serpiente + undo_redo, n=4")
    print("=" * 74, flush=True)
    for tarea in ("serpiente", "undo_redo"):
        for i in range(4):
            r = llamar("laguna-16k", ideas[tarea])
            res["brazo_b"].append({"tarea": tarea, **r})
            print(f"  {tarea} r{i+1}: {json.dumps(r, ensure_ascii=False)}",
                  flush=True)

    a_muertas = sum(1 for r in res["brazo_a"]
                    if not r.get("con_html") or not r.get("chars"))
    b_muertas = sum(1 for r in res["brazo_b"]
                    if not r.get("con_html") or not r.get("chars"))
    print(f"\nBRAZO A (config vieja): {a_muertas}/3 sin HTML")
    print(f"BRAZO B (config nueva): {b_muertas}/8 sin HTML")

    salida = (RAIZ / "cognia" / "program_creator" / "generated_programs"
              / "b1_oraculo" / "confound_repro.json")
    salida.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
