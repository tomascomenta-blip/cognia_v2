"""Descontaminación: verifica que ningún ítem de las suites aparezca en los
JSONL de entrenamiento del repo (P0-ii/DC-10, regla 7 del SPEC).

Método: shingles de 8 palabras foldeadas del prompt de cada ítem vs shingles
de todos los campos de texto de cada JSONL de training. Colisión = overlap.

Correr: .\\venv312\\Scripts\\python.exe cognia_v3\\eval\\suites\\decontaminar.py
Exit 0 = limpio; 1 = colisiones (listadas).
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from suite_oracle import fold  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUITES = glob.glob(os.path.join(HERE, "g*.jsonl"))
TRAIN_GLOBS = [
    os.path.join(REPO, "cognia_v3", "training", "**", "*.jsonl"),
]
K = 8  # tamaño del shingle en palabras


def shingles(texto: str) -> set:
    palabras = re.findall(r"[a-z0-9ñ]+", fold(texto))
    return {" ".join(palabras[i:i + K]) for i in range(len(palabras) - K + 1)}


def textos_de(registro) -> list:
    out = []
    if isinstance(registro, dict):
        for v in registro.values():
            out.extend(textos_de(v))
    elif isinstance(registro, list):
        for v in registro:
            out.extend(textos_de(v))
    elif isinstance(registro, str):
        out.append(registro)
    return out


def texto_item(it: dict) -> str:
    """Texto del ítem a descontaminar. Para G2A el prompt incluye por DISEÑO
    infraestructura idéntica a train/deploy (tools_doc + plantillas RESULTADO
    de las tools): eso no es contaminación de contenido. La unidad específica
    del ítem es su línea TAREA — sobre ella se aplica la regla estándar."""
    if it.get("gate") == "G2A":
        for ln in it["prompt"].splitlines():
            if ln.startswith("TAREA:"):
                return ln
        return ""
    return it["prompt"]


def main():
    suite_sh = {}
    for spath in SUITES:
        with open(spath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                it = json.loads(line)
                sh = shingles(texto_item(it))
                if sh:
                    suite_sh[it["id"]] = (os.path.basename(spath), sh)
    print(f"suites: {len(suite_sh)} ítems con shingles")

    # Copias exactas de las suites (p.ej. en _*_staging/ para subir el dataset
    # a Kaggle) no son datos de entrenamiento: excluir por sha256 idéntico.
    import hashlib
    hashes_suites = set()
    for spath in SUITES:
        with open(spath, "rb") as f:
            hashes_suites.add(hashlib.sha256(f.read()).hexdigest())

    def _es_copia_de_suite(p):
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() in hashes_suites

    train_files = sorted({p for g in TRAIN_GLOBS for p in glob.glob(g, recursive=True)
                          if os.sep + "suites" + os.sep not in p
                          and not _es_copia_de_suite(p)})
    print(f"training JSONLs a revisar: {len(train_files)}")

    colisiones = []
    for tpath in train_files:
        train_sh = set()
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    reg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for txt in textos_de(reg):
                    train_sh |= shingles(txt)
        if not train_sh:
            continue
        for iid, (suite, sh) in suite_sh.items():
            inter = sh & train_sh
            if inter:
                colisiones.append((iid, suite, os.path.relpath(tpath, REPO),
                                   sorted(inter)[0]))

    if colisiones:
        print(f"\nCOLISIONES: {len(colisiones)}")
        for iid, suite, tfile, ejemplo in colisiones:
            print(f"  {iid} ({suite}) vs {tfile}: '{ejemplo}'")
        sys.exit(1)
    print("\nLIMPIO: ningún ítem de suite aparece en los JSONL de training")


if __name__ == "__main__":
    main()
