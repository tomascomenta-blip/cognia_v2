"""
scripts/kg_maintenance.py
==========================
Script de mantenimiento del Knowledge Graph — aplica decaimiento de peso
a hechos poco referenciados.

Uso:
  python scripts/kg_maintenance.py [--dry-run] [--stats] [--stale-list]

  --stats       Muestra estadisticas del KG
  --stale-list  Lista los 20 hechos mas stale
  --dry-run     Muestra que decaeria sin aplicar cambios
  (sin flags)   Aplica decaimiento y muestra resumen
"""

import argparse
import sys
import os

# Asegurar que el directorio raiz del proyecto esta en sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from cognia.knowledge.staleness_detector import StalenessDetector


def cmd_stats(detector: StalenessDetector) -> None:
    stats = detector.get_stats()
    print("KG Statistics")
    print(f"  total_facts        : {stats['total_facts']}")
    print(f"  stale_facts        : {stats['stale_facts']}  (no access in {detector.STALE_DAYS} days)")
    print(f"  never_accessed     : {stats['never_accessed_facts']}")
    print(f"  avg_weight         : {stats['avg_weight']:.4f}")
    print(f"  at_min_weight      : {stats['min_weight_facts']}  (weight <= {detector.MIN_WEIGHT})")


def cmd_stale_list(detector: StalenessDetector, limit: int = 20) -> None:
    facts = detector.get_stale_facts(limit=limit)
    if not facts:
        print("No stale facts found.")
        return
    print(f"Stale facts (top {len(facts)}):")
    for f in facts:
        days = f["last_accessed_days_ago"]
        days_str = f"{days}d ago" if days is not None else "never accessed"
        print(
            f"  [{f['weight']:.3f}] {f['subject']} --{f['predicate']}--> {f['object']}"
            f"  ({days_str})"
        )


def cmd_apply_decay(detector: StalenessDetector, dry_run: bool = False) -> None:
    result = detector.apply_decay(dry_run=dry_run)
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Decay cycle complete:")
    print(f"  facts_decayed    : {result['facts_decayed']}  (weight *= {detector.DECAY_FACTOR})")
    print(f"  facts_already_min: {result['facts_already_min']}  (weight already <= {detector.MIN_WEIGHT})")
    if dry_run:
        print("  No changes written to DB.")


def main():
    parser = argparse.ArgumentParser(
        description="Cognia KG maintenance — staleness decay"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show KG statistics"
    )
    parser.add_argument(
        "--stale-list", action="store_true", help="List stale facts (limit 20)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would decay without applying changes"
    )
    args = parser.parse_args()

    detector = StalenessDetector()

    if args.stats:
        cmd_stats(detector)
    elif args.stale_list:
        cmd_stale_list(detector)
    elif args.dry_run:
        cmd_apply_decay(detector, dry_run=True)
    else:
        # Default: apply decay and show summary
        cmd_apply_decay(detector, dry_run=False)
        print()
        cmd_stats(detector)


if __name__ == "__main__":
    main()
