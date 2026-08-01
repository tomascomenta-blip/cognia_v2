# -*- coding: utf-8 -*-
"""
b4_lora_f0_gate.py — FASE 0 del PREREG_LORAS_20260801 (enmienda 1): gate de
ACTIVIDAD del pipeline GGUF-LoRA contra el no-op silencioso.

UN solo proceso de llama-server arrancado con
    --lora <adapter> --lora-init-without-apply --parallel 1
(sin draft: se lanza directo, no via servir_modelo.py). Tres condiciones por
el endpoint de runtime, en este orden:
    A = estado inicial (adapter cargado, NO aplicado)
    C = POST /lora-adapters scale 0.0   (debe ser = A token a token)
    B = POST /lora-adapters scale 1.0   (debe diferir de A en >=1 prompt)
`cache_prompt: false` en toda peticion (el KV bajo la escala anterior
contaminaria en silencio). Decodificacion determinista (temp 0, top_k 1).

PASS = B!=A en >=1 prompt  Y  C==A en los 3  Y  B coherente  Y  sin errores
de carga. Rescate pre-registrado: si C!=A, se vuelcan los logprobs de la
primera divergencia; margen de argmax <1e-3 = limite del instrumento (el
gate PASA con B!=A y B!=C y C~=A), no KILL.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b4_loras"
URL = "http://127.0.0.1:8090"   # se puede pisar con --url (F2: 8092)

PROMPTS = [
    "If a train travels 60 km in 40 minutes, how far does it travel in 2 "
    "hours at the same speed? Think step by step and give the answer.",
    "Write a Python function that returns the n-th Fibonacci number "
    "iteratively.",
    "Describe in two sentences what a hash table is.",
]


def _post(ruta: str, cuerpo: dict) -> dict:
    req = urllib.request.Request(
        f"{URL}{ruta}", data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _escala(s: float) -> None:
    _post("/lora-adapters", [{"id": 0, "scale": s}])


def _completa(prompt: str) -> dict:
    return _post("/completion", {
        "prompt": prompt, "n_predict": 128, "temperature": 0.0, "top_k": 1,
        "seed": 20260801, "cache_prompt": False, "n_probs": 5})


def _corre(nombre: str) -> list:
    out = []
    for p in PROMPTS:
        r = _completa(p)
        out.append({"prompt": p[:40], "texto": r.get("content", ""),
                    "tokens": [t.get("id") for t in
                               (r.get("completion_probabilities") or [])]})
        print(f"  [{nombre}] {p[:40]!r} -> {len(out[-1]['texto'])} chars")
    return out


def _coherente(texto: str) -> bool:
    if not texto.strip():
        return False
    palabras = texto.split()
    tri = Counter(tuple(palabras[i:i + 3]) for i in range(len(palabras) - 2))
    return not tri or tri.most_common(1)[0][1] <= 8


def main():
    global URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--salida", default="f0_gate.json")
    ap.add_argument("--etiqueta", default="F0 Deepthink/qwen2.5-7b")
    args = ap.parse_args()
    URL = args.url

    # estado del adapter: debe estar cargado (id 0) y sin aplicar
    ad = json.loads(urllib.request.urlopen(
        f"{URL}/lora-adapters", timeout=10).read().decode("utf-8"))
    print(f"adapters del server: {ad}")
    if not ad:
        print("FALLA: el server no tiene adapters cargados"); sys.exit(2)

    # ENMIENDA 2: en b10066 el estado inicial ya esta a escala 1.0 aunque se
    # arranque con --lora-init-without-apply (medido: A==B byte-exacto en la
    # corrida 1). Protocolo corregido: S0 -> S1 -> S0 (ida y vuelta).
    print("\n== S0_1: escala 0.0 (base) ==")
    _escala(0.0)
    A = _corre("S0_1")
    print("\n== S1: escala 1.0 (adapter) ==")
    _escala(1.0)
    B = _corre("S1")
    print("\n== S0_2: escala 0.0 otra vez (ida y vuelta) ==")
    _escala(0.0)
    C = _corre("S0_2")

    c_igual_a = [a["texto"] == c["texto"] for a, c in zip(A, C)]
    b_difiere = [a["texto"] != b["texto"] for a, b in zip(A, B)]
    b_coherente = [_coherente(b["texto"]) for b in B]

    print(f"\nS0_2==S0_1 por prompt : {c_igual_a}")
    print(f"S1!=S0_1 por prompt   : {b_difiere}")
    print(f"S1 coherente          : {b_coherente}")

    gate = all(c_igual_a) and any(b_difiere) and all(b_coherente)
    veredicto = "PASS" if gate else "FALLA"
    if not all(c_igual_a) and any(b_difiere) and all(b_coherente):
        veredicto = "REVISAR_LOGPROBS"   # rescate pre-registrado
    print(f"\nGATE F0: {veredicto}")

    SALIDA.mkdir(exist_ok=True)
    (SALIDA / args.salida).write_text(json.dumps(
        {"prereg": "PREREG_LORAS_20260801.md (enmiendas 1-3)",
         "etiqueta": args.etiqueta,
         "server": "b10066, un proceso, --lora-init-without-apply, sin draft",
         "veredicto": veredicto, "c_igual_a": c_igual_a,
         "b_difiere": b_difiere, "b_coherente": b_coherente,
         "A": A, "B": B, "C": C}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"-> {SALIDA / args.salida}")
    sys.exit(0 if veredicto == "PASS" else 1)


if __name__ == "__main__":
    main()
