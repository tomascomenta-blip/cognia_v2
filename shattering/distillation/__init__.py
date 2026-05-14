"""
shattering/distillation
========================
Self-distillation pipeline for the SRDN (Sparse-Recursive Distillation Network).

Uses the Ollama teacher (text-only API) and gold episodes from the consolidation
REINFORCE phase as training data.

Loss composition:
  total = 0.7 * sequence_level_loss + 0.3 * consistency_loss

sequence_level_loss: cross-entropy against teacher-generated token sequences.
consistency_loss:    disagreement between LOGOS/TECHNE/RHETOR on boundary prompts.
"""

from .data_generator import query_gold_episodes, generate_reasoning_chains, build_training_dataset
from .losses import sequence_level_loss, consistency_loss
from .trainer import SRDNTrainer

__all__ = [
    "query_gold_episodes",
    "generate_reasoning_chains",
    "build_training_dataset",
    "sequence_level_loss",
    "consistency_loss",
    "SRDNTrainer",
]
