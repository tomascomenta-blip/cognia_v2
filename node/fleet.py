"""
node/fleet.py
=============
Registro de la flota LOCAL de modelos GGUF (llama.cpp) de esta maquina.

La flota vive fuera del repo, en ~/.cognia/models (override: COGNIA_MODELS_DIR).
Los GGUF multiparte se consideran presentes solo si TODAS las partes estan
(llama.cpp carga la parte 1 y resuelve el resto en el mismo directorio).

Uso:
    from node.fleet import fleet_status
    for m in fleet_status():
        print(m["key"], m["presente"], m["gb"])
"""

from __future__ import annotations

import os
from pathlib import Path

# Flota objetivo de esta maquina (RTX 5060 Ti 16GB): el 14B Q4_K_M entra entero
# en VRAM; el 0.5B va en Q8_0 porque Q4_K_M le hunde la calidad (medido en fleet
# anterior); el 7B es el generalista de chat.
FLEET = [
    {
        "key":    "coder-0.5b",
        "rol":    "portero/draft (speculative)",
        "params": "0.5B",
        "files":  ["qwen2.5-coder-0.5b-instruct-q8_0.gguf"],
    },
    {
        "key":    "chat-7b",
        "rol":    "chat general (default LLAMA_GGUF_PATH)",
        "params": "7B",
        "files":  [
            "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
            "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
        ],
    },
    {
        "key":    "coder-14b",
        "rol":    "codigo de calidad (cabe entero en 16GB VRAM)",
        "params": "14B",
        "files":  [
            "qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf",
            "qwen2.5-coder-14b-instruct-q4_k_m-00002-of-00002.gguf",
        ],
    },
]


def models_dir() -> Path:
    """Directorio de la flota; COGNIA_MODELS_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_MODELS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "models"


def fleet_status() -> list[dict]:
    """Estado vivo de cada modelo: presente (todas las partes) y tamano en GB."""
    base = models_dir()
    out = []
    for m in FLEET:
        paths = [base / f for f in m["files"]]
        present = all(p.is_file() and p.stat().st_size > 0 for p in paths)
        size = sum(p.stat().st_size for p in paths if p.is_file())
        out.append({
            "key":      m["key"],
            "rol":      m["rol"],
            "params":   m["params"],
            "presente": present,
            "gb":       round(size / 1e9, 2),
            "path":     str(paths[0]),
        })
    return out
