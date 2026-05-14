"""
cognia_code.py
==============
Cognia Code — terminal entry point for the code/tech Shattering variant.

Loads the cognia_code manifest (TECHNE shards bundled, LOGOS on-demand)
and runs an interactive REPL routed by GlobalRouter.

Usage:
    python cognia_code.py                   # interactive REPL
    python cognia_code.py "sort a list"     # one-shot query
    python cognia_code.py --status          # swarm / fragment status
    python cognia_code.py --coordinator URL # use distributed mode
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# Ensure repo root is on sys.path when run directly
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shattering.orchestrator import ShatteringOrchestrator

_MANIFEST = str(_ROOT / "shattering" / "manifests" / "cognia_code.json")

_BANNER = """\
+------------------------------------------------------+
|  Cognia Code  -  Shattering v1  (TECHNE + LOGOS)    |
|  Type /help for commands, Ctrl+C or /exit to quit   |
+------------------------------------------------------+"""

_HELP = """\
Commands:
  /help          — show this message
  /status        — fragment & swarm status
  /preload       — load all bundled shards into RAM now
  /mode          — show current inference mode (local/distributed/simulation)
  /route <text>  — show routing decision without running inference
  /clear         — clear the screen
  /exit          — quit

Anything else is sent to the AI.
Sub-model is shown after each response: [TECHNE|LOGOS|RHETOR conf%]"""


def _build_orch(coordinator_url: str | None) -> ShatteringOrchestrator:
    return ShatteringOrchestrator(
        manifest_path=_MANIFEST,
        coordinator_url=coordinator_url,
        mode="auto",
    )


def _print_result(orch: ShatteringOrchestrator, prompt: str) -> None:
    result = orch.infer(prompt)
    width  = min(os.get_terminal_size().columns - 4, 88) if sys.stdout.isatty() else 84
    wrapped = textwrap.fill(result.text, width=width)
    print(f"\n{wrapped}")
    print(
        f"  [{result.sub_model.upper()}  {result.confidence:.0%}  "
        f"{result.mode}  {result.latency_ms:.0f}ms]\n"
    )


def _cmd_status(orch: ShatteringOrchestrator) -> None:
    import json
    s = orch.status()
    print(f"\nManifest : {s['manifest']}")
    print(f"Mode     : {s['mode']}")
    frags = s["fragments"]
    print(f"Loaded   : {frags['loaded_sub_models']}  ({len(frags['loaded_fragments'])} shards)")
    print(f"LRU      : {frags['lru_order']}")
    print(f"Bundles  :")
    for sm, ids in s["bundles"].items():
        print(f"  {sm:8s} -> {ids}")
    print()


def _repl(orch: ShatteringOrchestrator) -> None:
    print(_BANNER)
    print()
    while True:
        try:
            raw = input("cognia_code> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            return

        if not raw:
            continue

        if raw in ("/exit", "/quit", "exit", "quit"):
            print("Bye.")
            return
        elif raw == "/help":
            print(_HELP)
        elif raw == "/status":
            _cmd_status(orch)
        elif raw == "/preload":
            print("Preloading bundled shards...")
            orch.preload()
            print("Done.")
        elif raw == "/mode":
            print(f"Mode: {orch._mode}")
        elif raw == "/clear":
            os.system("cls" if sys.platform == "win32" else "clear")
        elif raw.startswith("/route "):
            prompt = raw[7:].strip()
            if prompt:
                d = orch.route_only(prompt)
                print(
                    f"  sub_model={d.sub_model}  conf={d.confidence:.0%}  "
                    f"scores={d.scores}\n  reason: {d.reason}\n"
                )
        elif raw.startswith("/"):
            print(f"Unknown command '{raw}'. Type /help.")
        else:
            try:
                _print_result(orch, raw)
            except Exception as exc:
                print(f"Error: {exc}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cognia_code",
        description="Cognia Code — code-focused Shattering AI CLI",
    )
    parser.add_argument("query", nargs="?", help="One-shot query (skip REPL)")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--route", metavar="TEXT", help="Show routing decision and exit")
    parser.add_argument(
        "--coordinator", metavar="URL",
        default=os.environ.get("COGNIA_COORDINATOR_URL"),
        help="Swarm coordinator URL (default: $COGNIA_COORDINATOR_URL)",
    )
    args = parser.parse_args()

    orch = _build_orch(args.coordinator)

    if args.status:
        _cmd_status(orch)
        return

    if args.route:
        d = orch.route_only(args.route)
        print(
            f"sub_model={d.sub_model}  conf={d.confidence:.0%}  "
            f"scores={d.scores}\nreason: {d.reason}"
        )
        return

    if args.query:
        _print_result(orch, args.query)
        return

    _repl(orch)


if __name__ == "__main__":
    main()
