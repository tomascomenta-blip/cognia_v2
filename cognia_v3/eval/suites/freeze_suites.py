"""Congela por hash las suites held-out (P0-ii, DC-10).

Valida cada suite con carga_suite() y escribe SUITES_FROZEN.json con el sha256
de cada archivo. Si ya existe un freeze previo, se NIEGA a re-congelar un
archivo cuyo hash cambió (anti-Goodhart, Parte 3 §3.4: cambio de suite =
suite NUEVA con otro nombre, nunca edición silenciosa).

Correr: .\\venv312\\Scripts\\python.exe cognia_v3\\eval\\suites\\freeze_suites.py
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from suite_oracle import carga_suite  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "SUITES_FROZEN.json")
SUITES = ["g1_general.jsonl", "g2_razonamiento.jsonl",
          "g3_identidad.jsonl", "g5_espanol.jsonl", "g2_accion.jsonl"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    previo = {}
    if os.path.exists(FROZEN):
        with open(FROZEN, encoding="utf-8") as f:
            previo = json.load(f).get("suites", {})

    registro, errores = {}, []
    for nombre in SUITES:
        path = os.path.join(HERE, nombre)
        if not os.path.exists(path):
            errores.append(f"{nombre}: NO EXISTE")
            continue
        try:
            items = carga_suite(path)
        except ValueError as e:
            errores.append(f"{nombre}: INVÁLIDA — {e}")
            continue
        h = sha256(path)
        if nombre in previo and previo[nombre]["sha256"] != h:
            errores.append(
                f"{nombre}: YA CONGELADA con otro hash "
                f"({previo[nombre]['sha256'][:12]}… vs {h[:12]}…). "
                "Una suite congelada NO se edita: crear una suite nueva.")
            continue
        registro[nombre] = {"sha256": h, "n_items": len(items),
                            "frozen": previo.get(nombre, {}).get(
                                "frozen", time.strftime("%Y-%m-%d"))}
        print(f"OK  {nombre}: {len(items)} ítems  sha256={h[:16]}…")

    if errores:
        for e in errores:
            print("ERROR", e)
        sys.exit(1)

    with open(FROZEN, "w", encoding="utf-8") as f:
        json.dump({"protocolo": "TEORIA_COGNIA3B.md Parte 3 §3.3 / DC-10",
                   "suites": registro}, f, indent=1, ensure_ascii=False)
    print(f"\nCongeladas {len(registro)} suites -> {FROZEN}")


if __name__ == "__main__":
    main()
