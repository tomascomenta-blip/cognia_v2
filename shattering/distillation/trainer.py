"""
shattering/distillation/trainer.py
=====================================
SRDNTrainer — orchestrates curriculum distillation across LOGOS, TECHNE, RHETOR.

Curriculum order:
  1. LOGOS  — general reasoning/knowledge baseline
  2. TECHNE — code/technical (benefits from LOGOS reasoning)
  3. RHETOR — writing quality (benefits from LOGOS + TECHNE context)

Each domain's training data is the subset of gold episodes whose label matches
the domain, plus boundary prompts for consistency loss computation.

This trainer operates in simulation mode: it exercises the full loss pipeline
without requiring real model weights. When real weights are available, the
student_logits would come from ShardEngine.forward() via the orchestrator.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .losses import combined_loss

logger = logging.getLogger(__name__)

_DEFAULT_CURRICULUM = ["logos", "techne", "rhetor"]
_DEFAULT_EPOCHS     = 1
_BATCH_SIZE         = 32
_VOCAB_SIZE         = 32000
_HIDDEN_DIM         = 3072


@dataclass
class TrainingStats:
    domain:       str
    epoch:        int
    n_examples:   int
    mean_loss:    float
    elapsed_s:    float
    checkpoint:   Optional[str] = None


@dataclass
class SRDNTrainer:
    """
    Self-distillation trainer for the Shattering sub-models.

    Args:
        orchestrator:       ShatteringOrchestrator instance (for inference)
        curriculum_order:   domain names in training order
        n_epochs:           epochs per domain
        checkpoint_dir:     directory for saving per-domain checkpoints
    """
    orchestrator:     Any
    curriculum_order: List[str]               = field(default_factory=lambda: list(_DEFAULT_CURRICULUM))
    n_epochs:         int                     = _DEFAULT_EPOCHS
    checkpoint_dir:   str                     = "model_shards/checkpoints"
    _stats_history:   List[TrainingStats]     = field(default_factory=list, init=False)

    def train(self, dataset: List[Dict[str, Any]]) -> List[TrainingStats]:
        """
        Run curriculum distillation across all domains.

        Args:
            dataset: list of training examples from build_training_dataset()

        Returns:
            List of TrainingStats — one per (domain, epoch) pair
        """
        os.makedirs(self.checkpoint_dir, exist_ok=True)

        for domain in self.curriculum_order:
            domain_data = self._filter_domain(dataset, domain)
            logger.info(
                "[Trainer] domain=%s  examples=%d  epochs=%d",
                domain, len(domain_data), self.n_epochs,
            )
            if not domain_data:
                logger.warning("[Trainer] No data for domain '%s' — skipping", domain)
                continue

            for epoch in range(1, self.n_epochs + 1):
                stats = self.train_epoch(domain, domain_data, epoch)
                self._stats_history.append(stats)

        return list(self._stats_history)

    def train_epoch(
        self,
        domain: str,
        domain_data: List[Dict[str, Any]],
        epoch: int = 1,
    ) -> TrainingStats:
        """
        Train one epoch for a single domain.

        Returns:
            TrainingStats for this epoch.
        """
        t0          = time.time()
        total_loss  = 0.0
        n_processed = 0

        batches = _batch(domain_data, _BATCH_SIZE)
        for batch in batches:
            for example in batch:
                loss = self._compute_example_loss(example, domain)
                total_loss  += loss
                n_processed += 1

        mean_loss = total_loss / max(n_processed, 1)
        elapsed   = time.time() - t0

        checkpoint = self.save_checkpoint(domain, epoch)

        stats = TrainingStats(
            domain     = domain,
            epoch      = epoch,
            n_examples = n_processed,
            mean_loss  = round(mean_loss, 4),
            elapsed_s  = round(elapsed, 2),
            checkpoint = checkpoint,
        )
        logger.info(
            "[Trainer] domain=%s epoch=%d loss=%.4f examples=%d elapsed=%.1fs",
            domain, epoch, mean_loss, n_processed, elapsed,
        )
        return stats

    def save_checkpoint(self, domain: str, epoch: int) -> str:
        """
        Save a checkpoint manifest for the current domain/epoch.
        In simulation mode this writes a JSON metadata file (no real weights).
        """
        path = os.path.join(self.checkpoint_dir, f"{domain}_epoch{epoch:03d}.json")
        meta = {
            "domain": domain,
            "epoch":  epoch,
            "mode":   "simulation",
            "stats":  [
                s.__dict__ for s in self._stats_history
                if s.domain == domain and s.epoch <= epoch
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as exc:
            logger.warning("[Trainer] save_checkpoint failed: %s", exc)
            return ""
        return path

    @property
    def stats_history(self) -> List[TrainingStats]:
        return list(self._stats_history)

    # ── Internal ─────────────────────────────────────────────────────

    def _compute_example_loss(self, example: Dict[str, Any], domain: str) -> float:
        """
        Compute the combined loss for a single training example.

        In simulation mode: student_logits are random (domain-seeded), teacher_tokens
        are derived from the reasoning_chain text, outputs_dict is simulated for all
        three sub-models. This exercises the full loss pipeline without real weights.
        """
        obs   = example.get("observation", "")
        chain = example.get("reasoning_chain", obs)
        fw    = float(example.get("training_weight", 1.0))

        # Simulation: deterministic logits seeded by domain + observation hash
        seed = abs(hash(domain + obs)) % (2 ** 31)
        rng  = np.random.default_rng(seed)

        seq_len        = min(len(obs.split()) + 1, 64)
        student_logits = rng.standard_normal((seq_len, _VOCAB_SIZE)).astype(np.float32)

        # Teacher tokens: hash each word to a token id
        teacher_tokens = [abs(hash(w)) % _VOCAB_SIZE for w in chain.split()[:seq_len]]

        # Simulated outputs for all three domains (consistency loss)
        outputs_dict: Dict[str, np.ndarray] = {}
        for dm in _DEFAULT_CURRICULUM:
            dm_seed = abs(hash(dm + obs)) % (2 ** 31)
            dm_rng  = np.random.default_rng(dm_seed)
            outputs_dict[dm] = dm_rng.standard_normal((seq_len, _VOCAB_SIZE)).astype(np.float32)

        return combined_loss(student_logits, teacher_tokens, outputs_dict, obs, fw)

    @staticmethod
    def _filter_domain(
        dataset: List[Dict[str, Any]], domain: str
    ) -> List[Dict[str, Any]]:
        """Return examples whose label matches domain, or all if none match."""
        domain_data = [ex for ex in dataset if domain in ex.get("label", "").lower()]
        return domain_data if domain_data else dataset


def _batch(data: List[Any], size: int) -> List[List[Any]]:
    return [data[i:i + size] for i in range(0, len(data), size)]
