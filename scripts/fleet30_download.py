# -*- coding: utf-8 -*-
"""Descarga los GGUF del FLEET-30 (corrida nocturna 2026-07-11).

Baja cada modelo del shortlist (FLEET30_RESEARCH.md) a
model_shards/fleet30/<key>/ buscando el archivo por regex en el repo HF
(los nombres exactos varian por quantizador). Idempotente: salta lo que ya
esta. Uso:
    venv312\\Scripts\\python.exe scripts\\fleet30_download.py [key ...]
Sin args baja TODOS los prioritarios de esta noche.
"""
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEST_BASE = REPO / "model_shards" / "fleet30"

# key -> (repo_hf, regex del archivo, nota)
MODELOS = {
    "nextcoder7b": ("Mungert/NextCoder-7B-GGUF",
                    r"(?i)q4_k_m\.gguf$", "repair 7B (MIT)"),
    "qwen3_4b": ("unsloth/Qwen3-4B-Instruct-2507-GGUF",
                 r"(?i)^(?!.*UD)(?!.*BF16).*q4_k_m\.gguf$", "agente/FC 4B"),
    "coder15b": ("QuantFactory/Qwen2.5-Coder-1.5B-GGUF",
                 r"(?i)q8_0\.gguf$", "FIM rapido (base, Q8 leccion portero)"),
    "vibethinker15b": ("mradermacher/VibeThinker-1.5B-GGUF",
                       r"(?i)q4_k_m\.gguf$", "math barata (MIT)"),
    "qwen3_embed": ("Qwen/Qwen3-Embedding-0.6B-GGUF",
                    r"(?i)q8_0\.gguf$", "embedder RAG"),
    "qwen35_4b": ("unsloth/Qwen3.5-4B-GGUF",
                  r"(?i)^(?!.*UD)(?!.*BF16).*q4_k_m\.gguf$",
                  "GATED: smoke b9391 obligatorio"),
    "lfm25_12b": ("unsloth/LFM2.5-1.2B-Instruct-GGUF",
                  r"(?i)^(?!.*UD)(?!.*BF16).*q4_k_m\.gguf$",
                  "generalista rapido; smoke arch"),
    "bge_reranker": ("gpustack/bge-reranker-v2-m3-GGUF",
                     r"(?i)q8_0\.gguf$", "reranker RAG"),
}

PRIORITARIOS = ["nextcoder7b", "qwen3_4b", "coder15b", "vibethinker15b",
                "qwen3_embed", "qwen35_4b", "lfm25_12b"]


def descargar(key: str) -> bool:
    from huggingface_hub import hf_hub_download, list_repo_files
    repo, patron, nota = MODELOS[key]
    dest = DEST_BASE / key
    ya = list(dest.glob("*.gguf")) if dest.is_dir() else []
    if ya:
        print(f"[{key}] ya presente: {ya[0].name}", flush=True)
        return True
    try:
        files = list_repo_files(repo)
    except Exception as exc:
        print(f"[{key}] ERROR listando {repo}: {exc}", flush=True)
        return False
    candidatos = sorted(f for f in files if re.search(patron, f))
    if not candidatos:
        print(f"[{key}] ERROR: ningun archivo matchea {patron} en {repo}; "
              f"ggufs disponibles: {[f for f in files if f.endswith('.gguf')][:8]}",
              flush=True)
        return False
    fname = candidatos[0]
    print(f"[{key}] bajando {repo}/{fname} ({nota})...", flush=True)
    t0 = time.time()
    try:
        path = hf_hub_download(repo_id=repo, filename=fname,
                               local_dir=str(dest))
    except Exception as exc:
        print(f"[{key}] ERROR descarga: {exc}", flush=True)
        return False
    mb = Path(path).stat().st_size / (1 << 20)
    print(f"[{key}] OK {mb:.0f}MB en {time.time() - t0:.0f}s -> {path}",
          flush=True)
    return True


def main():
    keys = sys.argv[1:] or PRIORITARIOS
    malos = [k for k in keys if k not in MODELOS]
    if malos:
        print(f"keys desconocidas: {malos}; validas: {list(MODELOS)}")
        return 1
    resultados = {k: descargar(k) for k in keys}
    ok = sum(resultados.values())
    print(f"\nRESUMEN: {ok}/{len(keys)} OK -> "
          f"{ {k: ('OK' if v else 'FALLO') for k, v in resultados.items()} }",
          flush=True)
    return 0 if ok == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main())
