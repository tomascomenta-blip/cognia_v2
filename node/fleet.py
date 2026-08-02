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
import re
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


# Roles conocidos para modelos detectados por escaneo (prefijo del archivo en
# minusculas -> rol). Lo que no matchee queda como "en disco (sin rol asignado)"
# en vez de desaparecer de /modelos y `cognia fleet` (desync cazada 2026-08-01:
# gpt-oss/UIGEN/OpenReasoning/VL estaban en disco pero la tabla no los listaba).
_ROLES_ESCANEO = [
    ("gpt-oss",            "pensador (razonamiento/codigo, MXFP4)"),
    ("uigen",              "constructor web (UI)"),
    ("openreasoning",      "razonador/math"),
    ("qwen2.5-vl",         "arbitro visual (VLM, usa su mmproj-*)"),
    ("qwen3-4b-thinking",  "agente thinking"),
]

# Sufijo de multiparte llama.cpp: modelo-00001-of-00002.gguf
_RE_PARTE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)

# Tamano de parametros en el nombre: "20b", "1.7B", "0.5b" (para la columna params)
_RE_PARAMS = re.compile(r"(\d+(?:\.\d+)?)[bB](?![a-zA-Z0-9])")


def _rol_por_nombre(nombre_lower: str) -> str:
    for prefijo, rol in _ROLES_ESCANEO:
        if nombre_lower.startswith(prefijo):
            return rol
    return "en disco (sin rol asignado)"


def _extras_en_disco(base: Path, cubiertos: set[str]) -> list[dict]:
    """GGUF de models_dir() que la tabla FLEET no lista, agrupando multipartes.

    Se saltean los mmproj-* (proyectores de vision, no modelos standalone) y
    cualquier archivo ya cubierto por FLEET. Asi la tabla nunca vuelve a
    desincronizarse del disco: lo que se instala aparece solo.
    """
    grupos: dict[str, dict] = {}
    if not base.is_dir():
        return []
    for p in sorted(base.glob("*.gguf")):
        nombre = p.name
        if nombre in cubiertos or nombre.lower().startswith("mmproj-"):
            continue
        m = _RE_PARTE.search(nombre)
        if m:
            clave, total = nombre[:m.start()], int(m.group(2))
        else:
            clave, total = nombre[:-len(".gguf")], 1
        g = grupos.setdefault(clave, {"files": [], "total": total})
        g["files"].append(nombre)
    out = []
    for clave, g in grupos.items():
        pm = _RE_PARAMS.search(clave)
        out.append({
            "key":    clave.lower(),
            "rol":    _rol_por_nombre(clave.lower()),
            "params": f"{pm.group(1).upper()}B" if pm else "?",
            "files":  sorted(g["files"]),
            "_total": g["total"],
        })
    return out


def fleet_status() -> list[dict]:
    """Estado vivo de cada modelo: presente (todas las partes) y tamano en GB.

    Lista la tabla FLEET curada y ADEMAS todo GGUF real de models_dir() que no
    este en ella (escaneo, como scripts/servir_modelo.py), para que la salida
    de /modelos y `cognia fleet` refleje siempre el disco.
    """
    base = models_dir()
    cubiertos = {f for m in FLEET for f in m["files"]}
    out = []
    entradas = [dict(m, _total=len(m["files"])) for m in FLEET]
    entradas += _extras_en_disco(base, cubiertos)
    for m in entradas:
        paths = [base / f for f in m["files"]]
        # Multiparte: presente solo si estan TODAS las partes declaradas.
        present = (len(paths) == m["_total"]
                   and all(p.is_file() and p.stat().st_size > 0 for p in paths))
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
