# -*- coding: utf-8 -*-
"""Genera shattering/manifests/fleet30.json desde model_shards/fleet30/.

Escanea los GGUF descargados por fleet30_download.py y escribe el manifest
que consume node/fleet_registry.py (key, rol, puerto fijo, ctx, ram_gb =
tamaño de archivo + margen KV, template). Idempotente; correr tras cada
descarga nueva. Uso:
    venv312\\Scripts\\python.exe scripts\\fleet30_manifest.py
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "model_shards" / "fleet30"
DEST = REPO / "shattering" / "manifests" / "fleet30.json"

# key -> (rol, puerto, ctx, template). Puertos fijos 8093+ (evitar adopcion
# cruzada); ctx chico en especialistas (KV barato), grande solo si el rol lo pide.
CONFIG = {
    "nextcoder7b": ("repair", 8093, 4096, "chatml"),
    "qwen3_4b": ("agente_v2", 8094, 8192, "chatml"),
    "coder15b": ("fim", 8095, 4096, "chatml"),
    "vibethinker15b": ("math", 8096, 4096, "chatml"),
    "qwen35_4b": ("codigo_top", 8097, 8192, "chatml"),
    "lfm25_12b": ("generalista", 8098, 4096, "chatml"),
    "qwen3_embed": ("embedder", 8099, 2048, "chatml"),
    "bge_reranker": ("reranker", 8100, 2048, "chatml"),
}


def main():
    members = []
    for key, (rol, port, ctx, template) in CONFIG.items():
        d = SRC / key
        ggufs = sorted(d.glob("*.gguf")) if d.is_dir() else []
        if not ggufs:
            print(f"[{key}] sin GGUF aun (se omite)")
            continue
        # LoRA estática del miembro (patrón portero): cognia_*_f16.gguf junto
        # al GGUF base (p.ej. cognia_id4b_f16.gguf = identidad del 4B, K1).
        loras = [x for x in ggufs if x.name.startswith("cognia_")]
        ggufs = [x for x in ggufs if not x.name.startswith("cognia_")]
        if not ggufs:
            print(f"[{key}] solo LoRA sin base (se omite)")
            continue
        g = ggufs[0]
        # RAM estimada = archivo mmap + ~25% de KV/overhead (medido: 3B Q4
        # 1.93GB archivo ~ 2.4GB proceso con ctx 4-8k)
        ram_gb = round(g.stat().st_size / (1 << 30) * 1.25, 2)
        entry = {
            "key": key, "role": rol,
            "gguf": str(Path("..") / ".." / "model_shards" / "fleet30" / key / g.name),
            "port": port, "ctx": ctx, "ram_gb": ram_gb, "template": template,
        }
        if loras:
            entry["lora"] = str(Path("..") / ".." / "model_shards" / "fleet30"
                                / key / loras[0].name)
        members.append(entry)
        print(f"[{key}] {g.name} ram_est={ram_gb}GB :{port}"
              + (f" +lora {loras[0].name}" if loras else ""))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps({"members": members}, indent=1),
                    encoding="utf-8")
    print(f"\nOK -> {DEST} ({len(members)} miembros)")


if __name__ == "__main__":
    main()
