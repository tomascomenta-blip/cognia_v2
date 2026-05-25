"""
shattering/manifest.py
======================
Fragment manifest schema and loader for the Shattering architecture.

A manifest declares which model fragments an app bundles at install time,
which it downloads on-demand at first use, and which it optionally contributes
to the swarm when the device is idle.

Fragment ID format: "{sub_model}/{shard_index}/{quantization}"
  e.g. "logos/0/q4_k_m", "techne/2/q4_k_m"

Coordinator URL in JSON may contain "${VAR}" references resolved via os.environ.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

MANIFESTS_DIR = Path(__file__).parent / "manifests"


@dataclass
class FragmentSpec:
    """Describes one model shard fragment."""
    fragment_id:  str        # canonical: "{sub_model}/{shard_index}/{quantization}"
    sub_model:    str        # "logos" | "techne" | "rhetor"
    shard_index:  int        # 0-based position in the inference pipeline
    quantization: str        # "q4_k_m" | "q8_0" | "f16"
    layer_range:  List[int]  # [first_layer, last_layer] inclusive
    size_bytes:   int
    sha256:       str        # hex string; "" means skip integrity check
    hf_repo:      str        # HuggingFace repo for download
    hf_filename:  str        # filename within the repo
    trigger:      Optional[str] = None  # on_demand only: what query type triggers download


@dataclass
class AppManifest:
    """Full fragment manifest for one Cognia app variant."""
    app_id:             str
    version:            str
    shattering_version: str
    base_model:         str   # e.g. "3.2-3b-q4" — appended to sub_model for coordinator key
    coordinator_url:    str
    bundled:            List[FragmentSpec]                          # installed with the app
    on_demand:          List[FragmentSpec] = field(default_factory=list)  # downloaded on first use
    optional:           List[FragmentSpec] = field(default_factory=list)  # swarm participation only

    def all_fragments(self) -> List[FragmentSpec]:
        return self.bundled + self.on_demand + self.optional

    def primary_sub_model(self) -> str:
        """The sub-model with the most bundled fragments (drives main inference path)."""
        counts: Dict[str, int] = {}
        for f in self.bundled:
            counts[f.sub_model] = counts.get(f.sub_model, 0) + 1
        return max(counts, key=counts.get) if counts else "logos"

    def fragments_for_sub_model(self, sub_model: str) -> List[FragmentSpec]:
        return [f for f in self.all_fragments() if f.sub_model == sub_model]

    def coordinator_model_name(self, sub_model: str) -> str:
        """Returns the coordinator registry key for the given sub-model."""
        return f"{sub_model}-{self.base_model}"


class ManifestLoader:
    """Loads and caches AppManifest objects from JSON files in shattering/manifests/."""

    _cache: Dict[str, AppManifest] = {}

    @classmethod
    def load(cls, app_id: str) -> AppManifest:
        """Load manifest for app_id, using cache."""
        if app_id in cls._cache:
            return cls._cache[app_id]
        path = MANIFESTS_DIR / f"{app_id}.json"
        manifest = cls.load_from_file(path)
        cls._cache[app_id] = manifest
        return manifest

    @classmethod
    def load_from_file(cls, path) -> AppManifest:
        """Load and parse a manifest JSON file."""
        with open(path) as f:
            data = json.load(f)

        coordinator_url = data.get("coordinator_url", "")
        # Resolve ${ENV_VAR} references
        if coordinator_url.startswith("${") and coordinator_url.endswith("}"):
            var_name = coordinator_url[2:-1]
            coordinator_url = os.environ.get(var_name, "")
        # Also allow env var override regardless
        coordinator_url = os.environ.get("COGNIA_COORDINATOR_URL", coordinator_url)

        return AppManifest(
            app_id=data["app_id"],
            version=data["version"],
            shattering_version=data["shattering_version"],
            base_model=data["base_model"],
            coordinator_url=coordinator_url,
            bundled=cls._parse_specs(data.get("bundled", [])),
            on_demand=cls._parse_specs(data.get("on_demand", [])),
            optional=cls._parse_specs(data.get("optional", [])),
        )

    @classmethod
    def _parse_specs(cls, items: list) -> List[FragmentSpec]:
        return [
            FragmentSpec(
                fragment_id=item["fragment_id"],
                sub_model=item["sub_model"],
                shard_index=item["shard_index"],
                quantization=item["quantization"],
                layer_range=item["layer_range"],
                size_bytes=item["size_bytes"],
                sha256=item.get("sha256", ""),
                hf_repo=item.get("hf_repo") or item.get("hf_dataset", ""),
                hf_filename=item["hf_filename"],
                trigger=item.get("trigger"),
            )
            for item in items
        ]

    @classmethod
    def available_apps(cls) -> List[str]:
        """List app IDs that have a manifest file."""
        if not MANIFESTS_DIR.exists():
            return []
        return [p.stem for p in MANIFESTS_DIR.glob("*.json")]

    @classmethod
    def invalidate_cache(cls):
        cls._cache.clear()
