"""
scripts/shutdown_pc.py
Apaga el equipo Windows inmediatamente via PowerShell.
Uso: python scripts/shutdown_pc.py [--delay SEGUNDOS]
"""

import subprocess
import sys
import argparse


def shutdown(delay_seconds: int = 0) -> None:
    cmd = ["powershell", "-Command", f"Stop-Computer -Force"]
    if delay_seconds > 0:
        cmd = ["shutdown", "/s", "/t", str(delay_seconds)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apaga el equipo Windows.")
    parser.add_argument(
        "--delay", type=int, default=0,
        help="Segundos de espera antes de apagar (default: 0 = inmediato)"
    )
    args = parser.parse_args()
    shutdown(args.delay)
