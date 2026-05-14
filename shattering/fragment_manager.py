"""
shattering/fragment_manager.py
==============================
Fragment lifecycle manager: download, integrity checking, loading, LRU eviction.

Maintains at most `max_loaded_submodels` sub-model sets in RAM simultaneously
to prevent OOM on memory-constrained devices (Android ≤6 GB, entry PC ≤8 GB).

LRU policy operates at the sub-model level (not per-shard), so eviction drops
all loaded shards of the least-recently-used sub-model at once.

Fragment directory layout on disk:
    {base_dir}/{sub_model}-{base_model}/shard_{index}/
        shard_meta.json          — always present after download
        shard.safetensors        — present when real weights downloaded
        layers.safetensors       — alternate name from downloader
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional

from shattering.manifest import FragmentSpec
from shattering.model_constants import LLAMA_32_3B, SHARD_PRECISION

_TOTAL_LAYERS = LLAMA_32_3B["total_layers"]
_HIDDEN_DIM   = LLAMA_32_3B["hidden_dim"]
_INTERMEDIATE = LLAMA_32_3B["intermediate_dim"]
_N_SHARDS     = LLAMA_32_3B["n_shards"]


class FragmentManager:

    def __init__(
        self,
        base_dir: str = "model_shards",
        base_model: str = "3.2-3b-q4",
        max_loaded_submodels: int = 2,
    ):
        self.base_dir   = Path(base_dir)
        self.base_model = base_model
        self._max_sm    = max_loaded_submodels
        self._engines: Dict[str, object] = {}            # "logos/0" → ShardEngine
        self._lru: OrderedDict[str, None] = OrderedDict()  # LRU order (oldest first)
        self._lock = threading.Lock()

    # ── Path helpers ──────────────────────────────────────────────────

    def fragment_dir(self, spec: FragmentSpec) -> Path:
        model_name = f"{spec.sub_model}-{self.base_model}"
        return self.base_dir / model_name / f"shard_{spec.shard_index}"

    @staticmethod
    def _key(sub_model: str, shard_index: int) -> str:
        return f"{sub_model}/{shard_index}"

    # ── Disk presence ─────────────────────────────────────────────────

    def is_on_disk(self, spec: FragmentSpec) -> bool:
        """True if a shard_meta.json exists for this fragment (simulation or real)."""
        return (self.fragment_dir(spec) / "shard_meta.json").exists()

    # ── Loading ───────────────────────────────────────────────────────

    def load(self, spec: FragmentSpec, precision: Optional[str] = None):
        """
        Load a fragment into memory as a ShardEngine.

        If not on disk, writes a simulation meta so the engine runs in
        SIMULATION mode without error. Returns the ShardEngine instance.

        Args:
            spec:      fragment to load
            precision: "fp32" | "int8" | "ternary"; None = auto from SHARD_PRECISION
        """
        key = self._key(spec.sub_model, spec.shard_index)

        # Fast path: already loaded
        with self._lock:
            if key in self._engines:
                self._touch(spec.sub_model)
                return self._engines[key]

        # Prepare the engine outside the lock (disk I/O may be slow)
        if not self.is_on_disk(spec):
            self._write_simulation_meta(spec)

        from node.shard_engine import ShardConfig, ShardEngine

        frag_dir = self.fragment_dir(spec)
        has_weights = any(
            (frag_dir / name).exists()
            for name in ("shard.safetensors", "layers.safetensors")
        )
        weights_path = str(frag_dir) if has_weights else None

        resolved_precision = precision or SHARD_PRECISION.get(spec.shard_index, "fp32")

        config = ShardConfig(
            model_name=f"{spec.sub_model}-{self.base_model}",
            shard_index=spec.shard_index,
            n_shards=_N_SHARDS,
            total_layers=_TOTAL_LAYERS,
            hidden_dim=_HIDDEN_DIM,
            intermediate_dim=_INTERMEDIATE,
            precision=resolved_precision,
        )
        engine = ShardEngine(config, weights_path=weights_path)

        # Insert under the lock, evicting if needed — both ops in a single critical section
        with self._lock:
            # Another thread may have loaded the same key while we were building
            if key in self._engines:
                self._touch(spec.sub_model)
                return self._engines[key]

            loaded = {k.split("/")[0] for k in self._engines}
            if spec.sub_model not in loaded and len(loaded) >= self._max_sm:
                victim = next(
                    (sm for sm in self._lru if sm in loaded and sm != spec.sub_model),
                    None,
                )
                if victim:
                    for k in [k for k in self._engines if k.startswith(f"{victim}/")]:
                        del self._engines[k]
                    self._lru.pop(victim, None)

            self._engines[key] = engine
            self._touch(spec.sub_model)

        return engine

    def load_all(self, specs: List[FragmentSpec], precision: Optional[str] = None) -> List:
        """Load all fragments for a sub-model, sorted by shard index."""
        return [self.load(s, precision=precision) for s in sorted(specs, key=lambda s: s.shard_index)]

    # ── Eviction ──────────────────────────────────────────────────────

    def evict(self, sub_model: str):
        """Explicitly release all loaded engines for a sub-model from RAM."""
        with self._lock:
            for k in [k for k in self._engines if k.startswith(f"{sub_model}/")]:
                del self._engines[k]
            self._lru.pop(sub_model, None)

    def _touch(self, sub_model: str):
        self._lru.pop(sub_model, None)
        self._lru[sub_model] = None  # move to MRU end

    # ── Query ─────────────────────────────────────────────────────────

    def is_loaded(self, sub_model: str, shard_index: int = -1) -> bool:
        with self._lock:
            if shard_index == -1:
                return any(k.startswith(f"{sub_model}/") for k in self._engines)
            return self._key(sub_model, shard_index) in self._engines

    def get_engine(self, sub_model: str, shard_index: int):
        with self._lock:
            return self._engines.get(self._key(sub_model, shard_index))

    # ── Download ──────────────────────────────────────────────────────

    def download(
        self,
        spec: FragmentSpec,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """
        Download a fragment shard from HuggingFace via ShardDownloader.
        Falls back to writing a simulation meta on failure so the app
        still loads (in simulation mode) without crashing.
        Returns True if the fragment is now usable (real or simulation).
        """
        if self.is_on_disk(spec):
            return True

        cb = progress_cb or _log_progress
        model_name = f"{spec.sub_model}-{self.base_model}"

        try:
            from node.downloader import ShardDownloader
            dl = ShardDownloader(shard=spec.shard_index, model_name=model_name)
            result = dl.download(on_progress=cb)
            return result.ok
        except Exception as exc:
            cb(1.0, f"Download failed ({exc}), switching to simulation mode")
            self._write_simulation_meta(spec)
            return True  # simulation mode is still usable

    def download_all(
        self,
        specs: List[FragmentSpec],
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> Dict[str, bool]:
        """Download multiple fragments sequentially. Returns {fragment_id: ok}."""
        results: Dict[str, bool] = {}
        total = len(specs)
        for i, spec in enumerate(specs):
            def _cb(pct: float, msg: str, _i=i, _t=total):
                if progress_cb:
                    progress_cb((_i + pct) / _t, f"[{_i+1}/{_t}] {msg}")
            results[spec.fragment_id] = self.download(spec, _cb)
        return results

    def _write_simulation_meta(self, spec: FragmentSpec):
        frag_dir = self.fragment_dir(spec)
        frag_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "shard":   spec.shard_index,
            "model":   f"{spec.sub_model}-{self.base_model}",
            "layers":  f"{spec.layer_range[0]}-{spec.layer_range[1]}",
            "mode":    "simulation",
            "size_mb": 0.0,
        }
        (frag_dir / "shard_meta.json").write_text(json.dumps(meta, indent=2))

    # ── Integrity ─────────────────────────────────────────────────────

    def verify_bundle(self, specs: List[FragmentSpec]) -> Dict[str, bool]:
        """
        Verify on-disk integrity of a list of fragments.
        Specs with empty sha256 are treated as valid (simulation mode).
        """
        results: Dict[str, bool] = {}
        for spec in specs:
            if not self.is_on_disk(spec):
                results[spec.fragment_id] = False
                continue
            if not spec.sha256:
                results[spec.fragment_id] = True
                continue
            weights = next(
                (
                    self.fragment_dir(spec) / name
                    for name in ("shard.safetensors", "layers.safetensors")
                    if (self.fragment_dir(spec) / name).exists()
                ),
                None,
            )
            if weights is None:
                results[spec.fragment_id] = True  # simulation, no weights file
            else:
                results[spec.fragment_id] = self._sha256(weights) == spec.sha256
        return results

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            loaded    = list(self._engines.keys())
            lru_order = list(self._lru.keys())
        return {
            "loaded_fragments":  loaded,
            "loaded_sub_models": list({k.split("/")[0] for k in loaded}),
            "lru_order":         lru_order,
            "max_sub_models":    self._max_sm,
        }


def _log_progress(pct: float, msg: str):
    print(f"  [{pct:5.1%}] {msg}")
