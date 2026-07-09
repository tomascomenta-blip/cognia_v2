# -*- coding: utf-8 -*-
"""Mide el GAP real del 3B en herramientas de escena LCD (fase 2 fleet).

Pregunta que decide si se construye un experto "escenas": ¿el 3B con el
few-shot del loop YA elige la tool correcta y pasa args que el oraculo
valida? Si la cobertura es alta, la linea del experto LCD se cierra sin
gastar GPU (regla del repo: verificar antes de construir; leccion E-RZN:
el adapter paga solo donde hay gap de FORMATO medido).

20 tareas congeladas (10 crear / 5 editar / 5 consultar, es+en). Camino
REAL del deploy: prompt estilo loop (build_tools_doc + fewshot_for) contra
el backend llama del CLI, greedy. Checks deterministas:
  - tool correcta en el 1er paso (metrica primaria),
  - para crear: se ejecuta la tool con los args DEL MODELO y el oraculo
    control_check debe dar control 3/3 (o N/N segun la tarea),
  - para editar/consultar: la tool corre sin ERROR sobre una escena real.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_lcd_gap
"""
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

TAREAS = [
    # ── crear (10) ──
    ("crear", "crea una escena con una pelota verde a la izquierda de una caja amarilla", "escena_crear"),
    ("crear", "dibuja un gato negro sobre una alfombra roja", "escena_crear"),
    ("crear", "arma una escena: un arbol grande a la derecha de una casa azul", "escena_crear"),
    ("crear", "quiero una imagen de una taza roja sobre una mesa marron", "escena_crear"),
    ("crear", "create a scene with a blue bird above a green tree", "escena_crear"),
    ("crear", "draw a red car to the left of a yellow house", "escena_crear"),
    ("crear", "haz una escena con un sol amarillo arriba de una montana gris", "escena_crear"),
    ("crear", "make a scene: a white cat under a brown table", "escena_crear"),
    ("crear", "genera una escena de un perro marron a la derecha de una pelota azul", "escena_crear"),
    ("crear", "create an image of a black dog next to a red ball", "escena_crear"),
    # ── editar (5): la escena base ya existe ──
    ("editar", "cambia el color de la taza a verde", "escena_editar"),
    ("editar", "pinta la mesa de negro", "escena_editar"),
    ("editar", "make the cup blue", "escena_editar"),
    ("editar", "cambia la taza para que sea amarilla", "escena_editar"),
    ("editar", "change the table color to white", "escena_editar"),
    # ── consultar (5) ──
    ("consultar", "que objetos hay en la escena?", "escena_consultar"),
    ("consultar", "donde esta la taza?", "escena_consultar"),
    ("consultar", "what objects are in the scene?", "escena_consultar"),
    ("consultar", "de que color es la mesa?", "escena_consultar"),
    ("consultar", "is the cup on the table?", "escena_consultar"),
]


def main():
    from shattering.orchestrator import ShatteringOrchestrator
    from cognia.agent.fewshot import fewshot_for
    from cognia.agent.tools import build_tools_doc, run_tool
    import cognia.lcd.tools_lcd  # registra las tools de escena  # noqa: F401

    orch = ShatteringOrchestrator(
        manifest_path=str(REPO / "shattering" / "manifests" / "cognia_desktop.json"))
    orch._try_load_llama()

    doc = build_tools_doc({"escena_crear", "escena_editar", "escena_consultar",
                           "responder"})
    res = {"eval": "lcd_gap", "n": len(TAREAS), "items": [], "started":
           time.strftime("%Y-%m-%d %H:%M:%S")}
    t0 = time.time()
    ok_tool = ok_oraculo = 0
    for tipo, tarea, esperada in TAREAS:
        ctx = {"orch": orch}
        if tipo in ("editar", "consultar"):
            run_tool("escena_crear", "una taza roja sobre una mesa marron", ctx)
        fs = fewshot_for(esperada) or fewshot_for("escena_crear")
        prompt = (
            "You are an autonomous agent. Start your reply with ACCION: on the first line.\n\n"
            "ACCION: <tool> <args>\n\nTools:\n" + doc + "\n  responder <respuesta>\n\n"
            + fs + f"\n\nContexto de la tarea:\nTAREA: {tarea}\n\nSiguiente ACCION:")
        raw = orch.infer(prompt, temperature=0.0, max_tokens=64).text.strip()
        linea1 = raw.split("\n")[0]
        m = re.search(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", "ACCION: " + linea1
                      if not linea1.upper().startswith("ACCI") else linea1,
                      re.IGNORECASE)
        tool = (m.group(1).lower() if m else "")
        args = (m.group(2).strip() if m else "")
        eligio = tool == esperada
        oraculo = False
        if eligio:
            out = run_tool(tool, args, ctx)
            if tipo == "crear":
                mm = re.search(r"control (\d+)/(\d+)", out)
                oraculo = bool(mm) and mm.group(1) == mm.group(2) and int(mm.group(2)) >= 2
            else:
                oraculo = "ERROR" not in out
        ok_tool += eligio
        ok_oraculo += oraculo
        res["items"].append({"tipo": tipo, "tarea": tarea, "tool": tool,
                             "args": args[:80], "eligio": eligio,
                             "oraculo": bool(oraculo)})
        print(f"  [{tipo}] tool={'OK ' if eligio else 'MAL'} "
              f"oraculo={'OK ' if oraculo else 'MAL'} | {tarea[:50]} -> {tool} {args[:40]}",
              flush=True)
    res["tool_acc"] = round(ok_tool / len(TAREAS), 3)
    res["oraculo_acc"] = round(ok_oraculo / len(TAREAS), 3)
    res["wall_min"] = round((time.time() - t0) / 60, 1)
    out = REPO / "cognia_v3" / "eval" / "results_lcd_gap.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n[lcd-gap] tool: {res['tool_acc']:.0%}  oraculo e2e: {res['oraculo_acc']:.0%} "
          f"({res['wall_min']} min) -> {out.name}", flush=True)


if __name__ == "__main__":
    main()
