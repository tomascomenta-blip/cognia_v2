# -*- coding: utf-8 -*-
"""Genera d5_espanol.jsonl — corpus de ESPAÑOL GENERAL para E2/E-MIX
(TEORIA Parte 4 §4.2 D5; sube el replay es que G5 pide: 60→56% en E1/E2A).

Fuentes (pre-registradas en la teoría):
  (i)  Aya (CohereForAI/aya_dataset, Apache-2.0): subset español, filtrado
       determinista de calidad + dedup.
  (ii) cognia_dataset.jsonl (KG+episodios): filtrado AGRESIVO.
       [PREDICCIÓN E-D5 pre-registrada: <30% sobrevive — se registra la tasa
       REAL en el reporte, pase lo que pase.]
  (iii) replay on-policy (respuestas del propio base): NO se genera acá
       (necesita GPU batched); el kernel E-MIX/E2 lo genera in-situ.

Filtros deterministas (sin LLM-juez):
  - idioma: es_espanol (heurística de stopwords de suite_oracle) sobre la
    completion; prompt no tiene que estar en inglés dominante.
  - longitud: completion 20..2000 chars; prompt 8..600 chars.
  - limpieza: sin U+200B/U+FFFD, sin plantillas vacuas "X and Y are related",
    sin HTML pesado, sin URLs crudas dominantes.
  - dedup: hash exacto de completion normalizada + prompt.
  - descontaminación: shingles K=8 vs TODAS las suites congeladas (mismo
    método que decontaminar.py) — colisión => ejemplo fuera.

Salida: data/d5_espanol.jsonl ({prompt, completion, source}) + reporte
data/d5_espanol.report.json con tasas por filtro.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.cognia3b.data.gen_d5_espanol [--max-aya 9000]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SUITES_DIR = REPO / "cognia_v3" / "eval" / "suites"
OUT = HERE / "d5_espanol.jsonl"
REPORT = HERE / "d5_espanol.report.json"

sys.path.insert(0, str(SUITES_DIR))
from suite_oracle import fold, es_espanol  # noqa: E402

K = 8


def shingles(texto: str) -> set:
    palabras = re.findall(r"[a-z0-9ñ]+", fold(texto))
    return {" ".join(palabras[i:i + K]) for i in range(len(palabras) - K + 1)}


def shingles_suites() -> set:
    todo = set()
    for p in SUITES_DIR.glob("g*.jsonl"):
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                it = json.loads(line)
                # para G2A la unidad específica es la línea TAREA (ver decontaminar.py)
                if it.get("gate") == "G2A":
                    for ln in it["prompt"].splitlines():
                        if ln.startswith("TAREA:"):
                            todo |= shingles(ln)
                else:
                    todo |= shingles(it["prompt"])
                    o = it.get("oracle") or {}
                    for kk in ("must_all", "must_any"):
                        for v in (o.get(kk) or []):
                            todo |= shingles(v)
    return todo


_VACUAS = (
    re.compile(r"\b\w+ and \w+ are related\b", re.IGNORECASE),
    re.compile(r"\bhas the property of being\b", re.IGNORECASE),
    re.compile(r"\bis related to\b", re.IGNORECASE),
)
_MAL_CHARS = ("​", "�")


def limpio(texto: str) -> bool:
    if any(c in texto for c in _MAL_CHARS):
        return False
    if any(rx.search(texto) for rx in _VACUAS):
        return False
    if texto.count("<") > 3 or texto.count("http") > 2:
        return False
    return True


def norm_key(prompt: str, completion: str) -> str:
    base = fold(re.sub(r"\s+", " ", prompt + " || " + completion)).strip()
    return hashlib.sha256(base.encode()).hexdigest()


def filtra_par(prompt: str, completion: str) -> str | None:
    """None si pasa; si no, el nombre del filtro que lo mató."""
    if not (8 <= len(prompt) <= 600):
        return "len_prompt"
    if not (20 <= len(completion) <= 2000):
        return "len_completion"
    if not limpio(prompt) or not limpio(completion):
        return "sucio"
    if not es_espanol(completion):
        return "no_espanol"
    return None


def carga_aya(max_n: int, rep: dict) -> list:
    from datasets import load_dataset
    print("[d5] descargando Aya (subset es)...", flush=True)
    ds = load_dataset("CohereForAI/aya_dataset", split="train")
    rep["aya_total"] = len(ds)
    pares, drops = [], {}
    for r in ds:
        if r.get("language_code") != "spa":
            continue
        rep["aya_es"] = rep.get("aya_es", 0) + 1
        p, c = (r.get("inputs") or "").strip(), (r.get("targets") or "").strip()
        f = filtra_par(p, c)
        if f:
            drops[f] = drops.get(f, 0) + 1
            continue
        pares.append({"prompt": p, "completion": c, "source": "aya_es"})
        if len(pares) >= max_n:
            break
    rep["aya_drops"] = drops
    rep["aya_aceptados"] = len(pares)
    return pares


def carga_oasst2(max_n: int, rep: dict) -> list:
    """oasst2 (Apache-2.0): pares (prompt RAÍZ es → mejor respuesta es).
    Solo raíces (parent_id null) = instrucciones autocontenidas; la mejor
    respuesta = rank 0 (ranking humano del proyecto OA)."""
    from datasets import load_dataset
    print("[d5] descargando oasst2 (subset es)...", flush=True)
    ds = load_dataset("OpenAssistant/oasst2", split="train")
    raices = {}
    for r in ds:
        if r.get("lang") == "es" and r["role"] == "prompter" and not r.get("parent_id"):
            raices[r["message_id"]] = r["text"]
    rep["oasst2_raices_es"] = len(raices)
    mejores = {}
    for r in ds:
        pid = r.get("parent_id")
        if r["role"] != "assistant" or pid not in raices or r.get("lang") != "es":
            continue
        rank = r.get("rank")
        rank = 999 if rank is None else rank
        if pid not in mejores or rank < mejores[pid][0]:
            mejores[pid] = (rank, r["text"])
    pares, drops = [], {}
    for pid, (rank, texto) in mejores.items():
        p, c = raices[pid].strip(), (texto or "").strip()
        f = filtra_par(p, c)
        if f:
            drops[f] = drops.get(f, 0) + 1
            continue
        pares.append({"prompt": p, "completion": c, "source": "oasst2_es"})
        if len(pares) >= max_n:
            break
    rep["oasst2_drops"] = drops
    rep["oasst2_aceptados"] = len(pares)
    return pares


def carga_cognia_dataset(rep: dict) -> list:
    path = REPO / "cognia_v3" / "training" / "cognia_dataset.jsonl"
    pares, drops, total = [], {}, 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            r = json.loads(line)
            p, c = (r.get("prompt") or "").strip(), (r.get("completion") or "").strip()
            fl = filtra_par(p, c)
            if fl:
                drops[fl] = drops.get(fl, 0) + 1
                continue
            # plantillas en inglés sobre contenido es: prompt inglés + completion corta
            pares.append({"prompt": p, "completion": c,
                          "source": f"cognia_ds_{r.get('source', '?')}"})
    rep["cognia_ds_total"] = total
    rep["cognia_ds_drops"] = drops
    rep["cognia_ds_aceptados"] = len(pares)
    rep["cognia_ds_tasa"] = round(len(pares) / max(1, total), 4)
    rep["cognia_ds_prediccion_e_d5"] = "<30% sobrevive [PRE-REGISTRADA]"
    return pares


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-aya", type=int, default=9000)
    ap.add_argument("--max-oasst", type=int, default=6000)
    args = ap.parse_args()

    t0 = time.time()
    rep = {"generado_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}

    pares = (carga_aya(args.max_aya, rep) + carga_oasst2(args.max_oasst, rep)
             + carga_cognia_dataset(rep))

    # dedup exacto normalizado
    vistos, unicos = set(), []
    for r in pares:
        k = norm_key(r["prompt"], r["completion"])
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(r)
    rep["dedup_dropped"] = len(pares) - len(unicos)

    # descontaminación contra las suites congeladas
    sh_suites = shingles_suites()
    limpios, contaminados = [], 0
    for r in unicos:
        if (shingles(r["prompt"]) | shingles(r["completion"])) & sh_suites:
            contaminados += 1
            continue
        limpios.append(r)
    rep["descontaminacion_dropped"] = contaminados
    rep["total_final"] = len(limpios)
    rep["wall_s"] = round(time.time() - t0, 1)

    with OUT.open("w", encoding="utf-8") as f:
        for r in limpios:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    REPORT.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    print(f"[d5] {len(limpios)} pares -> {OUT}")


if __name__ == "__main__":
    main()
