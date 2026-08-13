# -*- coding: utf-8 -*-
"""Cuanto contexto ENTRA de verdad en esta GPU, por modelo y por tipo de KV.

Uso:  venv312\\Scripts\\python.exe scripts\\ctx_maximo.py [ruta.gguf ...]

Lee los metadatos del GGUF (sin cargar los pesos: solo la cabecera) y calcula el
KV cache byte a byte con la formula real:

    bytes_por_token = n_layer * n_head_kv * head_dim * 2 (K y V) * bytes_elem

Despues reparte la VRAM disponible y dice cuantos tokens caben. El limite de
VRAM es DURO; el de velocidad no sale de aqui (el prefill crece con el cuadrado
del contexto: eso hay que medirlo con llama-bench).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

# Bytes por elemento del KV cache segun --cache-type-k/-v. q8_0 empaqueta 32
# valores en 34 bytes (32 int8 + escala fp16) -> 1.0625 B/elem.
TIPOS_KV = {"f16": 2.0, "q8_0": 34 / 32, "q5_1": 24 / 32, "q4_0": 18 / 32}

_LECTORES = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4),
    5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8),
    12: ("<d", 8),
}


def _cadena(fh) -> str:
    (n,) = struct.unpack("<Q", fh.read(8))
    return fh.read(n).decode("utf-8", "replace")


def _valor(fh, tipo: int):
    if tipo == 8:
        return _cadena(fh)
    if tipo == 9:
        (tipo_elem,) = struct.unpack("<I", fh.read(4))
        (n,) = struct.unpack("<Q", fh.read(8))
        return [_valor(fh, tipo_elem) for _ in range(n)]
    fmt, tam = _LECTORES[tipo]
    return struct.unpack(fmt, fh.read(tam))[0]


def metadatos(ruta: Path) -> dict:
    """Los pares clave/valor de la cabecera GGUF. No toca los tensores."""
    with open(ruta, "rb") as fh:
        if fh.read(4) != b"GGUF":
            raise ValueError("no es un GGUF")
        struct.unpack("<I", fh.read(4))          # version
        struct.unpack("<Q", fh.read(8))          # tensor_count
        (n_kv,) = struct.unpack("<Q", fh.read(8))
        meta = {}
        for _ in range(n_kv):
            clave = _cadena(fh)
            (tipo,) = struct.unpack("<I", fh.read(4))
            meta[clave] = _valor(fh, tipo)
        return meta


def _buscar(meta: dict, sufijo: str):
    for clave, valor in meta.items():
        if clave.endswith(sufijo):
            return valor
    return None


def perfil(ruta: Path) -> dict:
    meta = metadatos(ruta)
    n_layer = _buscar(meta, ".block_count")
    n_head = _buscar(meta, ".attention.head_count")
    n_head_kv = _buscar(meta, ".attention.head_count_kv") or n_head
    n_embd = _buscar(meta, ".embedding_length")
    head_dim = (_buscar(meta, ".attention.key_length")
                or (int(n_embd / n_head) if n_embd and n_head else None))
    ctx_train = _buscar(meta, ".context_length")
    return {
        "ruta": ruta, "arq": meta.get("general.architecture", "?"),
        "n_layer": n_layer, "n_head_kv": n_head_kv, "head_dim": head_dim,
        "ctx_train": ctx_train, "pesos_gb": ruta.stat().st_size / 1024**3,
    }


def bytes_por_token(p: dict, tipo_kv: str) -> float:
    return p["n_layer"] * p["n_head_kv"] * p["head_dim"] * 2 * TIPOS_KV[tipo_kv]


def main() -> int:
    vram_gb = 16311 / 1024          # RTX 5060 Ti medida con nvidia-smi
    reserva_gb = 1.2                # buffers de computo, CUDA graphs y el SO
    rutas = [Path(a) for a in sys.argv[1:]]
    if not rutas:
        base = Path.home() / ".cognia" / "models"
        rutas = sorted(base.glob("*.gguf"), key=lambda p: -p.stat().st_size)[:4]

    print(f"VRAM {vram_gb:.1f} GB  -  reserva de buffers {reserva_gb} GB\n")
    for ruta in rutas:
        try:
            p = perfil(ruta)
        except Exception as exc:
            print(f"{ruta.name}: no se pudo leer ({exc})")
            continue
        if not all((p["n_layer"], p["n_head_kv"], p["head_dim"])):
            print(f"{ruta.name}: metadatos incompletos {p}")
            continue
        print(f"== {ruta.name}")
        print(f"   {p['arq']} | {p['n_layer']} capas | {p['n_head_kv']} kv-heads "
              f"| head_dim {p['head_dim']} | ctx entrenado {p['ctx_train']:,}")
        print(f"   pesos {p['pesos_gb']:.2f} GB")
        libre = vram_gb - p["pesos_gb"] - reserva_gb
        if libre <= 0:
            print("   no entra en VRAM ni sin contexto\n")
            continue
        print(f"   VRAM para KV: {libre:.2f} GB")
        for tipo in ("f16", "q8_0", "q5_1", "q4_0"):
            bpt = bytes_por_token(p, tipo)
            tokens = int(libre * 1024**3 / bpt)
            tope = min(tokens, p["ctx_train"] or tokens)
            marca = "  (tope del modelo)" if tope < tokens else ""
            print(f"     KV {tipo:5} -> {bpt/1024:6.1f} KB/token -> "
                  f"{tope:>9,} tokens{marca}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
