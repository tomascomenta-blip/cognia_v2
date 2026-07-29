"""
b2_diff_material.py — diff estructural gate-vs-hoy de la sonda de la
DISCREPANCIA (PREREG_DISCREPANCIA_TROCEO_20260729). Cero GPU.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_diff_material.py

Compara los prompts.jsonl del gate v2 (96, material de fase 1-2) y de las
capturas frescas de la etapa A: largo total, tamaño del bloque de feromona,
largo del brief, nº/largo de componentes REQUIRED. La tabla nombra al
sospechoso si la etapa B dice H-material.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
GATE = (RAIZ / "cognia" / "program_creator" / "generated_programs"
        / "b2_bon_gate_v2" / "prompts" / "prompts.jsonl")
FRESCO = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_ab_sin_troceo_capturas" / "prompts.jsonl")


def _stats(nombre: str, ruta: Path) -> None:
    lineas = [json.loads(l) for l in ruta.read_text(encoding="utf-8")
              .splitlines() if l.strip()]
    lineas = [p for p in lineas if p.get("lenguaje") == "html"]
    con_troceo = [p for p in lineas if "- REQUIRED component" in p["prompt"]]
    print(f"\n== {nombre}: {len(lineas)} prompts html "
          f"({len(con_troceo)} con troceo) ==")
    for etiqueta, grupo in (("con troceo", con_troceo),
                            ("sin troceo", [p for p in lineas
                                            if p not in con_troceo])):
        if not grupo:
            continue
        largos = [len(p["prompt"]) for p in grupo]
        fero, brief, req_n, req_l = [], [], [], []
        for p in grupo:
            t = p["prompt"]
            m = re.search(r"PROVEN PATTERNS.*?(?=\nRespond EXACTLY)", t,
                          re.S)
            fero.append(len(m.group(0)) if m else 0)
            m = re.search(r"TARGET LOOK, match it: (.*?)\*\*", t, re.S)
            brief.append(len(m.group(1)) if m else 0)
            comps = re.findall(r"^- REQUIRED component \d+: (.*)$", t, re.M)
            req_n.append(len(comps))
            req_l.extend(len(c) for c in comps)
        def med(xs):
            return f"{statistics.median(xs):.0f}" if xs else "-"
        print(f"  [{etiqueta}] n={len(grupo)}  largo_mediano={med(largos)}  "
              f"feromona_mediana={med(fero)}  brief_mediano={med(brief)}  "
              f"req_n_mediano={med(req_n)}  req_largo_mediano={med(req_l)}")
        sin_fero = sum(1 for f in fero if f == 0)
        sin_brief = sum(1 for b in brief if b == 0)
        print(f"             sin_feromona={sin_fero}/{len(grupo)}  "
              f"sin_brief={sin_brief}/{len(grupo)}")


def main(argv: list) -> int:
    for nombre, ruta in (("GATE v2 (material fase 1-2)", GATE),
                         ("FRESCO (etapa A de hoy)", FRESCO)):
        if not ruta.is_file():
            print(f"[!] falta {ruta}", file=sys.stderr)
            continue
        _stats(nombre, ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
