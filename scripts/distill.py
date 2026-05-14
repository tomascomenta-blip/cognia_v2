"""
scripts/distill.py
==================
SRDN distillation pipeline CLI.

Steps:
  1. Query gold episodes from episodic memory (feedback_weight >= 1.0, access_count >= 3)
  2. Generate reasoning chains via Ollama teacher model
  3. Run curriculum distillation (logos -> techne -> rhetor)
  4. Save per-domain checkpoints to model_shards/checkpoints/

Usage:
    python scripts/distill.py [--db PATH] [--output PATH] [--model NAME] [--epochs N]
    python scripts/distill.py --dry-run   # just count gold episodes, skip training

Exit codes:
    0  Success or no training needed
    1  Fatal error (DB not found, etc.)
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DEFAULT_DB      = os.path.join(_ROOT, "cognia_memory.db")
_DEFAULT_OUTPUT  = os.path.join(_ROOT, "model_shards", "distillation_dataset.jsonl")
_DEFAULT_MODEL   = os.environ.get("COGNIA_OLLAMA_MODEL", "llama3.2")
_DEFAULT_OLLAMA  = (
    os.environ.get("COGNIA_OLLAMA_URL", "")
    or os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    + "/api/generate"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run SRDN self-distillation pipeline"
    )
    parser.add_argument("--db",      default=_DEFAULT_DB,
                        help="Path to cognia_memory.db")
    parser.add_argument("--output",  default=_DEFAULT_OUTPUT,
                        help="Path for distillation dataset JSONL output")
    parser.add_argument("--model",   default=_DEFAULT_MODEL,
                        help="Ollama teacher model name")
    parser.add_argument("--ollama",  default=_DEFAULT_OLLAMA,
                        help="Ollama API URL")
    parser.add_argument("--epochs",  type=int, default=1,
                        help="Training epochs per domain")
    parser.add_argument("--min-fw",  type=float, default=1.0,
                        help="Minimum feedback_weight for gold episodes")
    parser.add_argument("--min-access", type=int, default=3,
                        help="Minimum access_count for gold episodes")
    parser.add_argument("--limit",   type=int, default=5000,
                        help="Maximum number of episodes to query")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count gold episodes without running training")
    parser.add_argument("--checkpoint-dir", default="model_shards/checkpoints",
                        help="Directory for training checkpoints")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"[FAIL] Database not found: {args.db}")
        return 1

    from shattering.distillation.data_generator import (
        query_gold_episodes,
        build_training_dataset,
    )

    # Step 1: count/query gold episodes
    episodes = query_gold_episodes(
        args.db,
        min_fw=args.min_fw,
        min_access=args.min_access,
        limit=args.limit,
    )
    print(f"[DISTILL] Gold episodes found: {len(episodes)}")

    if args.dry_run:
        if episodes:
            fw_vals = [e["feedback_weight"] for e in episodes]
            print(f"[DISTILL] Mean feedback_weight: {sum(fw_vals)/len(fw_vals):.3f}")
            print(f"[DISTILL] Labels: {set(e['label'] for e in episodes[:20])}")
        print("[DRY-RUN] No training performed.")
        return 0

    if not episodes:
        print("[WARN] No gold episodes. Run the cognitive system and collect feedback first.")
        return 0

    # Step 2: build dataset with reasoning chains
    print(f"[DISTILL] Generating reasoning chains via Ollama ({args.model})...")
    dataset = build_training_dataset(
        args.db,
        output_path=args.output,
        ollama_url=args.ollama,
        model=args.model,
        min_fw=args.min_fw,
        min_access=args.min_access,
        limit=args.limit,
    )
    print(f"[DISTILL] Dataset: {len(dataset)} training examples")

    if not dataset:
        print("[WARN] No training examples generated. Is Ollama running?")
        print(f"       Run: ollama serve && ollama pull {args.model}")
        return 0

    # Step 3: curriculum distillation
    print(f"[DISTILL] Starting curriculum training ({args.epochs} epoch(s) per domain)...")
    from shattering.distillation.trainer import SRDNTrainer

    trainer = SRDNTrainer(
        orchestrator=None,
        curriculum_order=["logos", "techne", "rhetor"],
        n_epochs=args.epochs,
        checkpoint_dir=args.checkpoint_dir,
    )
    stats = trainer.train(dataset)

    print(f"\n[DISTILL] Training complete. {len(stats)} epoch(s) run.")
    for s in stats:
        print(
            f"  domain={s.domain:8s}  epoch={s.epoch}"
            f"  examples={s.n_examples:4d}  loss={s.mean_loss:.4f}"
            f"  elapsed={s.elapsed_s:.1f}s"
        )
        if s.checkpoint:
            print(f"    checkpoint -> {s.checkpoint}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
