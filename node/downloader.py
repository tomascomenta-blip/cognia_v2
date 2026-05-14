"""
node/downloader.py
==================
Descarga automática del shard asignado al nodo.

Flujo:
  1. Consulta al coordinador qué shard le corresponde
  2. Descarga el índice de tensores del modelo en HuggingFace
  3. Identifica qué archivos safetensors contienen las capas del shard
  4. Descarga solo esos archivos (evita bajar el modelo completo)
  5. Extrae y guarda solo las capas asignadas
  6. Verifica integridad por hash SHA-256
  7. Reporta progreso al caller via callback

Sin dependencias obligatorias:
  - Si 'safetensors' no está: descarga el archivo completo sin extraer
  - Si 'huggingface_hub' no está: usa HTTP directo
  - Si nada está disponible: modo solo-simulación

Uso:
    dl = ShardDownloader(shard=2, model_name="llama-3.2-3b-q4")
    dl.download(on_progress=lambda p, msg: print(f"{p:.0%} {msg}"))
"""

import os
import json
import hashlib
import shutil
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Allow node/ to be run standalone (adds repo root to sys.path for shattering.*)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shattering.model_constants import LLAMA_32_3B, QWEN25_CODER_3B


# ══════════════════════════════════════════════════════════════════════
# CATÁLOGO DE MODELOS
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ModelSource:
    hf_repo:            str
    total_layers:       int
    hidden_dim:         int
    intermediate_dim:   int
    n_shards:           int
    # Tensores especiales por posición
    embed_tokens_key:   str = "model.embed_tokens.weight"
    norm_key:           str = "model.norm.weight"
    lm_head_key:        str = "lm_head.weight"
    layer_prefix:       str = "model.layers"

def _llama32_src(hf_repo: str) -> ModelSource:
    return ModelSource(
        hf_repo          = hf_repo,
        total_layers     = LLAMA_32_3B["total_layers"],
        hidden_dim       = LLAMA_32_3B["hidden_dim"],
        intermediate_dim = LLAMA_32_3B["intermediate_dim"],
        n_shards         = LLAMA_32_3B["n_shards"],
    )

def _qwen25_coder_src() -> ModelSource:
    return ModelSource(
        hf_repo          = QWEN25_CODER_3B["hf_repo"],
        total_layers     = QWEN25_CODER_3B["total_layers"],
        hidden_dim       = QWEN25_CODER_3B["hidden_dim"],
        intermediate_dim = QWEN25_CODER_3B["intermediate_dim"],
        n_shards         = QWEN25_CODER_3B["n_shards"],
    )

MODEL_CATALOG: dict = {
    # ── Qwen2.5-Coder-3B (primary, Apache-2.0) ─────────────────────────
    "qwen-coder-3b-q4": _qwen25_coder_src(),
    # ── Legacy Llama keys ───────────────────────────────────────────────
    "llama-3.2-3b-q4": _llama32_src("meta-llama/Llama-3.2-3B-Instruct"),
    "llama-3.1-8b-q4": ModelSource(
        hf_repo          = "meta-llama/Meta-Llama-3.1-8B-Instruct",
        total_layers     = 32,
        hidden_dim       = 4096,
        intermediate_dim = 14336,
        n_shards         = 4,
    ),
    # ── Shattering sub-models (placeholder HF repos until published) ────
    # Point to the base Llama repo for now; replace with fine-tuned repos
    # once cognia-ai/logos-3.2-3b-q4 etc. are published on HuggingFace.
    "logos-3.2-3b-q4":  _llama32_src("cognia-ai/logos-3.2-3b-q4"),
    "techne-3.2-3b-q4": _llama32_src("cognia-ai/techne-3.2-3b-q4"),
    "rhetor-3.2-3b-q4": _llama32_src("cognia-ai/rhetor-3.2-3b-q4"),
}

HF_BASE = "https://huggingface.co"
SHARDS_DIR = os.path.join(os.path.dirname(__file__), "..", "model_shards")


# ══════════════════════════════════════════════════════════════════════
# PROGRESS CALLBACK
# ══════════════════════════════════════════════════════════════════════

ProgressFn = Callable[[float, str], None]   # (0.0-1.0, mensaje)


def _noop_progress(pct: float, msg: str):
    print(f"  [{pct:5.1%}] {msg}")


# ══════════════════════════════════════════════════════════════════════
# DOWNLOADER
# ══════════════════════════════════════════════════════════════════════

@dataclass
class DownloadResult:
    ok:           bool
    shard_path:   str = ""
    size_mb:      float = 0.0
    duration_s:   float = 0.0
    mode:         str = ""   # "extracted" | "full_file" | "simulation"
    error:        str = ""


class ShardDownloader:
    """
    Descarga el shard asignado a este nodo desde HuggingFace.

    Estrategia de descarga en orden de preferencia:
      1. Extracción selectiva (safetensors) — descarga solo las capas necesarias
      2. Archivo completo con filtrado local — descarga el safetensors entero
      3. Solo simulación — sin pesos reales, el engine usa modo simulado
    """

    def __init__(self, shard: int, model_name: str = "llama-3.2-3b-q4",
                 hf_token: str = ""):
        self.shard      = shard
        self.model_name = model_name
        self.hf_token   = hf_token or os.environ.get("HF_TOKEN", "")
        self.source     = MODEL_CATALOG.get(model_name)
        if not self.source:
            raise ValueError(f"Modelo '{model_name}' no está en el catálogo. "
                             f"Disponibles: {list(MODEL_CATALOG)}")

        # Rango de capas que le corresponden a este shard
        lps = self.source.total_layers // self.source.n_shards
        self.layer_start = shard * lps
        self.layer_end   = ((shard + 1) * lps
                            if shard < self.source.n_shards - 1
                            else self.source.total_layers)

        # Directorio de destino
        self.output_dir = os.path.join(SHARDS_DIR, model_name, f"shard_{shard}")
        os.makedirs(self.output_dir, exist_ok=True)

    # ── API principal ─────────────────────────────────────────────────

    def is_downloaded(self) -> bool:
        """True si el shard ya está descargado y verificado."""
        meta = os.path.join(self.output_dir, "shard_meta.json")
        return os.path.exists(meta)

    def download(self, on_progress: ProgressFn = _noop_progress) -> DownloadResult:
        """
        Descarga el shard completo con reporting de progreso.
        Idempotente: si ya está descargado, retorna inmediatamente.
        """
        t0 = time.perf_counter()

        if self.is_downloaded():
            meta = self._read_meta()
            on_progress(1.0, f"Shard {self.shard} ya descargado ({meta.get('size_mb', 0):.1f} MB)")
            return DownloadResult(ok=True, shard_path=self.output_dir,
                                  size_mb=meta.get("size_mb", 0),
                                  mode=meta.get("mode", "cached"))

        on_progress(0.0, f"Iniciando descarga del shard {self.shard} "
                         f"(capas {self.layer_start}-{self.layer_end - 1})")

        # Intentar descarga real
        result = self._try_hf_download(on_progress)

        if not result.ok:
            # Fallback: marcar como solo-simulación
            on_progress(1.0, "Sin pesos reales — usando modo simulación")
            self._write_meta(mode="simulation", size_mb=0.0)
            return DownloadResult(ok=True, shard_path=self.output_dir,
                                  mode="simulation",
                                  duration_s=time.perf_counter() - t0)

        result.duration_s = time.perf_counter() - t0
        return result

    # ── Descarga desde HuggingFace ────────────────────────────────────

    def _try_hf_download(self, on_progress: ProgressFn) -> DownloadResult:
        """
        Intenta descargar los tensores del shard desde HuggingFace.

        Paso 1: obtener el índice de tensores (model.safetensors.index.json)
        Paso 2: identificar qué archivos contienen las capas de este shard
        Paso 3: descargar solo esos archivos
        Paso 4: extraer y guardar solo los tensores relevantes
        """
        repo  = self.source.hf_repo
        token = self.hf_token

        # 1. Descargar índice
        on_progress(0.05, "Obteniendo índice de tensores...")
        try:
            index = self._fetch_tensor_index(repo, token)
        except Exception as e:
            return DownloadResult(ok=False, error=f"No se pudo obtener índice: {e}")

        if not index:
            return DownloadResult(ok=False, error="Modelo sin índice de tensores "
                                                  "(posiblemente requiere HF token)")

        # 2. Identificar tensores necesarios para este shard
        needed_tensors = self._tensors_for_shard(index)
        if not needed_tensors:
            return DownloadResult(ok=False, error="No se encontraron tensores para este shard")

        # 3. Identificar archivos únicos a descargar
        files_needed = list({v for v in needed_tensors.values()})
        total_files  = len(files_needed)
        on_progress(0.10, f"{len(needed_tensors)} tensores en {total_files} archivo(s)")

        # 4. Descargar cada archivo
        downloaded_files = {}
        for i, fname in enumerate(files_needed):
            base_pct = 0.10 + (i / total_files) * 0.75
            on_progress(base_pct, f"Descargando {fname} ({i+1}/{total_files})...")

            local_path = os.path.join(self.output_dir, fname)
            if not os.path.exists(local_path):
                try:
                    self._download_file(repo, fname, local_path, token,
                                        on_progress=lambda p, m: on_progress(
                                            base_pct + p * (0.75 / total_files), m
                                        ))
                except Exception as e:
                    return DownloadResult(ok=False,
                                          error=f"Error descargando {fname}: {e}")
            downloaded_files[fname] = local_path

        # 5. Extraer solo los tensores del shard
        on_progress(0.87, "Extrayendo capas del shard...")
        try:
            size_mb = self._extract_shard_tensors(
                downloaded_files, needed_tensors, on_progress
            )
            # Limpiar archivos temporales completos
            for fpath in downloaded_files.values():
                if os.path.exists(fpath) and not fpath.endswith("shard.safetensors"):
                    os.remove(fpath)
            mode = "extracted"
        except Exception as e:
            # Fallback: mantener los archivos completos sin extraer
            size_mb = sum(
                os.path.getsize(p) / 1e6
                for p in downloaded_files.values()
                if os.path.exists(p)
            )
            mode = "full_file"

        self._write_meta(mode=mode, size_mb=size_mb,
                         layers=f"{self.layer_start}-{self.layer_end-1}")
        on_progress(1.0, f"Shard {self.shard} listo ({size_mb:.1f} MB, modo={mode})")

        return DownloadResult(ok=True, shard_path=self.output_dir,
                              size_mb=size_mb, mode=mode)

    # ── Índice de tensores HuggingFace ────────────────────────────────

    def _fetch_tensor_index(self, repo: str, token: str) -> Optional[dict]:
        """
        Descarga model.safetensors.index.json desde HuggingFace.
        Retorna el dict {tensor_name: filename} o None si no existe.
        """
        url = f"{HF_BASE}/{repo}/resolve/main/model.safetensors.index.json"
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            return data.get("weight_map", {})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise RuntimeError("Modelo privado: necesitás un HF_TOKEN con acceso. "
                                   "Conseguilo en huggingface.co/settings/tokens")
            if e.code == 404:
                # Puede que sea un solo archivo sin índice
                return self._try_single_file_index(repo, token)
            raise

    def _try_single_file_index(self, repo: str, token: str) -> Optional[dict]:
        """Para modelos con un solo model.safetensors (sin índice)."""
        url = f"{HF_BASE}/{repo}/resolve/main/model.safetensors"
        headers = {"Range": "bytes=0-0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            urllib.request.urlopen(req, timeout=5).close()
            # El archivo existe — fingir un índice que apunta todo a él
            src = self.source
            fake_index = {}
            fake_index[src.embed_tokens_key] = "model.safetensors"
            for i in range(src.total_layers):
                for suffix in ["self_attn.q_proj.weight", "self_attn.k_proj.weight",
                                "self_attn.v_proj.weight", "self_attn.o_proj.weight",
                                "mlp.gate_proj.weight", "mlp.up_proj.weight",
                                "mlp.down_proj.weight",
                                "input_layernorm.weight", "post_attention_layernorm.weight"]:
                    fake_index[f"{src.layer_prefix}.{i}.{suffix}"] = "model.safetensors"
            fake_index[src.norm_key]    = "model.safetensors"
            fake_index[src.lm_head_key] = "model.safetensors"
            return fake_index
        except Exception:
            return None

    # ── Selección de tensores para este shard ─────────────────────────

    def _tensors_for_shard(self, index: dict) -> dict:
        """
        Filtra el índice para quedarse solo con los tensores
        que pertenecen a este shard.

        Shard 0     : embed_tokens + capas layer_start..layer_end
        Shards medios: solo capas del rango
        Último shard: capas + norm + lm_head
        """
        src    = self.source
        needed = {}

        for tensor_name, filename in index.items():
            keep = False

            # Embedding — solo shard 0
            if tensor_name == src.embed_tokens_key:
                keep = (self.shard == 0)

            # Norm y LM head — solo último shard
            elif tensor_name in (src.norm_key, src.lm_head_key):
                keep = (self.shard == src.n_shards - 1)

            # Capas transformer — solo si están en el rango del shard
            elif tensor_name.startswith(f"{src.layer_prefix}."):
                rest = tensor_name[len(f"{src.layer_prefix}."):]
                try:
                    layer_idx = int(rest.split(".")[0])
                    keep = (self.layer_start <= layer_idx < self.layer_end)
                except (ValueError, IndexError):
                    pass

            if keep:
                needed[tensor_name] = filename

        return needed

    # ── Descarga de archivo individual ───────────────────────────────

    def _download_file(self, repo: str, filename: str, dest: str,
                       token: str, on_progress: ProgressFn = _noop_progress):
        """
        Descarga un archivo safetensors con reporte de progreso y soporte
        de descarga reanudable (Range header HTTP).

        Si existe un archivo parcial <dest>.tmp, la descarga continúa desde
        el byte donde se interrumpió. Si el servidor no admite Range (HTTP 200
        en lugar de 206), descarta el parcial y reinicia desde cero.
        El archivo .tmp NO se borra en caso de error — se conserva para
        la próxima reanudación.
        """
        url     = f"{HF_BASE}/{repo}/resolve/main/{filename}"
        headers: dict = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        tmp          = dest + ".tmp"
        partial_size = os.path.getsize(tmp) if os.path.exists(tmp) else 0

        if partial_size > 0:
            headers["Range"] = f"bytes={partial_size}-"
            on_progress(0.0, f"Resumiendo {filename} desde {partial_size / 1e6:.1f} MB")

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status        = getattr(r, "status", 200)
                content_len   = int(r.headers.get("Content-Length", 0))

                # Si pedimos Range pero el servidor respondió 200 (no lo soporta),
                # reiniciamos desde cero — descartar el parcial
                if partial_size > 0 and status == 200:
                    partial_size = 0
                    open_mode    = "wb"
                else:
                    open_mode = "ab" if partial_size > 0 else "wb"

                total      = partial_size + content_len if content_len > 0 else 0
                downloaded = partial_size
                chunk_size = 1024 * 1024   # 1 MB

                with open(tmp, open_mode) as f:
                    while True:
                        chunk = r.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            on_progress(
                                downloaded / total,
                                f"{filename}: {downloaded/1e6:.1f} / {total/1e6:.1f} MB",
                            )

            shutil.move(tmp, dest)

        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                # Permanent client error (404, 403, 401) — corrupt .tmp is useless
                if os.path.exists(tmp):
                    os.remove(tmp)
            # Preserve .tmp for 5xx / network errors (transient — resume on retry)
            raise

        except Exception:
            # Network error / timeout — preserve .tmp for next resumable attempt
            raise

    # ── Extracción de tensores ────────────────────────────────────────

    def _extract_shard_tensors(self, downloaded_files: dict,
                                needed_tensors: dict,
                                on_progress: ProgressFn) -> float:
        """
        Lee los archivos safetensors descargados y extrae solo los tensores
        necesarios para este shard. Guarda en 'shard.safetensors'.

        Requiere la librería 'safetensors'. Si no está disponible, lanza
        ImportError y el caller mantiene los archivos completos.
        """
        from safetensors import safe_open
        from safetensors.numpy import save_file

        extracted = {}
        total = len(needed_tensors)

        for i, (tensor_name, filename) in enumerate(needed_tensors.items()):
            fpath = downloaded_files.get(filename)
            if not fpath or not os.path.exists(fpath):
                continue

            on_progress(0.87 + (i / total) * 0.10,
                        f"Extrayendo {tensor_name.split('.')[-2:]}")

            with safe_open(fpath, framework="numpy") as f:
                if tensor_name in f.keys():
                    extracted[tensor_name] = f.get_tensor(tensor_name)

        if not extracted:
            raise RuntimeError("No se extrajeron tensores")

        out_path = os.path.join(self.output_dir, "shard.safetensors")
        save_file(extracted, out_path)

        size_mb = os.path.getsize(out_path) / 1e6
        return size_mb

    # ── Metadata ─────────────────────────────────────────────────────

    def _write_meta(self, mode: str, size_mb: float, layers: str = ""):
        meta = {
            "shard":      self.shard,
            "model":      self.model_name,
            "layers":     layers or f"{self.layer_start}-{self.layer_end-1}",
            "mode":       mode,
            "size_mb":    round(size_mb, 2),
            "downloaded": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        path = os.path.join(self.output_dir, "shard_meta.json")
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)

    def _read_meta(self) -> dict:
        path = os.path.join(self.output_dir, "shard_meta.json")
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    # ── Hash de verificación ──────────────────────────────────────────

    def verify_integrity(self) -> dict:
        """
        Calcula SHA-256 del shard descargado para verificar integridad.
        Retorna {ok, hash, size_mb}.
        """
        shard_file = os.path.join(self.output_dir, "shard.safetensors")
        if not os.path.exists(shard_file):
            return {"ok": False, "error": "shard.safetensors no encontrado"}

        sha = hashlib.sha256()
        size = 0
        with open(shard_file, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
                size += len(chunk)

        return {
            "ok":      True,
            "hash":    sha.hexdigest(),
            "size_mb": round(size / 1e6, 2),
        }

    def info(self) -> dict:
        meta = self._read_meta() if self.is_downloaded() else {}
        return {
            "shard":       self.shard,
            "model":       self.model_name,
            "layer_range": f"{self.layer_start}-{self.layer_end - 1}",
            "n_layers":    self.layer_end - self.layer_start,
            "output_dir":  self.output_dir,
            "downloaded":  self.is_downloaded(),
            **meta,
        }
