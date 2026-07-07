"""Fixer post-auditoría de D1: dropea duplicados normalizados y overlaps
exactos con la suite G3 (train==eval). Reescribe los archivos in-place.

Correr: .\\venv312\\Scripts\\python.exe cognia_v3\\training\\cognia3b\\data\\fix_d1.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from valida_d1 import ARCHIVOS, norm_prompt  # noqa: E402

SUITES = os.path.abspath(os.path.join(HERE, "..", "..", "..", "eval", "suites"))


def main():
    with open(os.path.join(SUITES, "g3_identidad.jsonl"), encoding="utf-8") as f:
        g3 = {norm_prompt(json.loads(l)["prompt"]) for l in f if l.strip()}

    vistos, dropped = set(), []
    for nombre in ARCHIVOS:
        path = os.path.join(HERE, nombre)
        out = []
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                np = norm_prompt(r["prompt"])
                if np in g3:
                    dropped.append(f"{nombre}:{lineno} OVERLAP-G3 '{np[:50]}'")
                    continue
                if np in vistos:
                    dropped.append(f"{nombre}:{lineno} DUP '{np[:50]}'")
                    continue
                vistos.add(np)
                out.append(r)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{nombre}: {len(out)} pares (quedaron)")
    print(f"\ndropped: {len(dropped)}")
    for d in dropped:
        print(" ", d)


if __name__ == "__main__":
    main()
