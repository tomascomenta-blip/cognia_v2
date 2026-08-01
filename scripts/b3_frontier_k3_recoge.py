# -*- coding: utf-8 -*-
"""
b3_frontier_k3_recoge.py — colecciona las muestras k=3 del frontier desde los
ficheros del workflow al raw canónico, con clave única (id, s).

DISENO_REFERENCIA_FRONTIER_20260731.md, enmienda 5.1 punto 3: el raw se
escribe con clave (id, s) única y atómica; los duplicados ABORTAN (no se
pisa una muestra ya coleccionada: si un relanzamiento re-generó un (id,s),
eso es un error de orquestación y se decide a mano, no en silencio).

Entradas:
  - el JSON de salida del task del workflow (workflowProgress: label
    "k3:<id>:s<s>", agentId, toolCalls, model, state)
  - el journal.jsonl del workflow (una línea {"type":"result", agentId,
    result:{codigo}} por agente)

Por muestra se guarda: codigo, modelo, tool_calls (gate de obediencia: 2),
agentId y chars. `--gate` exige tool_calls==2 y código no vacío en TODAS las
muestras nuevas (para el piloto y para cada lote).

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_frontier_k3_recoge.py
        <task_output.json> <journal.jsonl> [--salida frontier_k3_raw.json]
        [--gate]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b3_codigo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_output")
    ap.add_argument("journal")
    ap.add_argument("--salida", default="frontier_k3_raw.json")
    ap.add_argument("--gate", action="store_true")
    # enmienda 5.1 punto 1: un (id,s) caído se relanza UNA vez aparte. Para
    # que el lote y su reintento no colisionen en el raw, el lote se
    # colecciona omitiendo esas claves y el reintento se colecciona después.
    ap.add_argument("--omitir", default="",
                    help="ids a saltar (coma; 'arc191_d' salta todos sus s)")
    args = ap.parse_args()
    omitidos = {x.strip() for x in args.omitir.split(",") if x.strip()}

    out = json.loads(Path(args.task_output).read_text(encoding="utf-8"))
    progreso = [p for p in out.get("workflowProgress", [])
                if p.get("type") == "workflow_agent"
                and str(p.get("label", "")).startswith("k3:")]
    por_agente = {}
    for p in progreso:
        m = re.match(r"k3:(.+):s(\d+)$", p["label"])
        if not m:
            print(f"ABORTA: label no parseable: {p['label']}")
            sys.exit(2)
        por_agente[p["agentId"]] = {
            "id": m.group(1), "s": int(m.group(2)),
            "modelo": p.get("model", ""),
            "tool_calls": p.get("toolCalls"),
            "estado": p.get("state")}

    resultados = {}
    with open(args.journal, encoding="utf-8") as f:
        for line in f:
            if '"type":"result"' not in line:
                continue
            o = json.loads(line)
            if o.get("agentId") in por_agente:
                resultados[o["agentId"]] = (o.get("result") or {})

    destino = SALIDA / args.salida
    raw = {"experimento": "frontier_k3",
           "diseno": "DISENO_REFERENCIA_FRONTIER_20260731.md (enmiendas 5 y 5.1)",
           "muestras": []}
    if destino.exists():
        raw = json.loads(destino.read_text(encoding="utf-8"))
    claves = {(m["id"], m["s"]) for m in raw["muestras"]}

    nuevas, gate_mal = [], []
    for aid, info in sorted(por_agente.items(), key=lambda kv: (kv[1]["id"],
                                                                kv[1]["s"])):
        clave = (info["id"], info["s"])
        if info["id"] in omitidos:
            print(f"[rec] omitida ({clave[0]}, s={clave[1]}) por --omitir")
            continue
        if clave in claves:
            print(f"ABORTA: ({clave[0]}, s={clave[1]}) ya está en "
                  f"{destino.name}; un (id,s) no se colecciona dos veces.")
            sys.exit(2)
        codigo = (resultados.get(aid) or {}).get("codigo") or ""
        reg = {"id": info["id"], "s": info["s"], "dificultad": "hard",
               "codigo": codigo, "chars": len(codigo),
               "modelo": info["modelo"], "tool_calls": info["tool_calls"],
               "agente": aid,
               # enmienda 5.1 punto 1: perdida/vacía = FALLO con instrumento
               "instrumento": "" if codigo else "sin_codigo"}
        if info["tool_calls"] != 2 or not codigo:
            gate_mal.append((clave, info["tool_calls"], len(codigo)))
        raw["muestras"].append(reg)
        claves.add(clave)
        nuevas.append(clave)

    if args.gate and gate_mal:
        print(f"GATE FALLA ({len(gate_mal)}): {gate_mal}")
        print("No se escribe nada: corrige antes de coleccionar.")
        sys.exit(3)

    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, destino)
    modelos = sorted({m["modelo"] for m in raw["muestras"]})
    print(f"[rec] +{len(nuevas)} muestras (total {len(raw['muestras'])}) -> "
          f"{destino.name}")
    print(f"[rec] modelos: {modelos}  obediencia 2-tool-uses: "
          f"{sum(1 for m in raw['muestras'] if m['tool_calls'] == 2)}"
          f"/{len(raw['muestras'])}  vacías: "
          f"{sum(1 for m in raw['muestras'] if not m['codigo'])}")


if __name__ == "__main__":
    main()
