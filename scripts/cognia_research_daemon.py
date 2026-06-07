"""
scripts/cognia_research_daemon.py
================================
Detached, low-memory background researcher. Run it standalone (or via a Windows
Scheduled Task -- see scripts/install_research_daemon.py) so Cognia keeps turning
queued tool-ideas into verified tools even when the CLI is closed.

It holds NO model and NO Cognia instance resident; each tick only touches the DB
and spins the LLM for a single short burst, and only when enough RAM is free.

Usage:
    python scripts/cognia_research_daemon.py [--interval 1800] [--min-free-mb 700]
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cognia background research daemon.")
    ap.add_argument("--interval", type=float, default=1800.0,
                    help="Segundos entre ticks (default 1800 = 30 min).")
    ap.add_argument("--min-free-mb", type=float, default=700.0,
                    help="No sintetizar si la RAM libre es menor a esto.")
    ap.add_argument("--once", action="store_true",
                    help="Hacer un solo tick y salir (util para probar / cron).")
    args = ap.parse_args()

    # Quiet the noisy init logs; this runs unattended.
    import logging
    logging.disable(logging.INFO)

    from cognia.agent.background_research import background_tick, run_forever, _now

    if args.once:
        print(f"[cognia-research] {_now()} {background_tick(min_free_mb=args.min_free_mb)}",
              flush=True)
        return

    print(f"[cognia-research] daemon iniciado (interval={args.interval}s, "
          f"min_free={args.min_free_mb}MB)", flush=True)
    try:
        run_forever(interval_sec=args.interval, min_free_mb=args.min_free_mb)
    except KeyboardInterrupt:
        print("[cognia-research] detenido", flush=True)


if __name__ == "__main__":
    main()
