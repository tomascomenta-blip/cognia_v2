"""
scripts/install_research_daemon.py
=================================
Install (or remove) the Cognia background researcher as a Windows Scheduled Task,
so it runs even when you never open the CLI -- without keeping anything heavy
resident (each run is one short, RAM-guarded tick).

The task runs cognia_research_daemon.py with --once on a repeating trigger, so
Windows -- not a long-lived Python process -- owns the scheduling and the process
exits between ticks (near-zero idle memory).

Usage:
    python scripts/install_research_daemon.py --install [--every-min 60]
    python scripts/install_research_daemon.py --remove
    python scripts/install_research_daemon.py --status

Windows only (uses schtasks). On other OSes it prints the equivalent cron line.
"""

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TASK_NAME = "CogniaBackgroundResearch"
_DAEMON = os.path.join(_ROOT, "scripts", "cognia_research_daemon.py")


def _python_exe() -> str:
    # Prefer the venv that is actually running this installer.
    return sys.executable


def _install(every_min: int) -> int:
    if os.name != "nt":
        py = _python_exe()
        print("No es Windows. Equivalente cron (crontab -e):")
        print(f"  */{every_min} * * * * {py} {_DAEMON} --once")
        return 0
    py = _python_exe()
    cmd = f'"{py}" "{_DAEMON}" --once'
    # /sc MINUTE /mo N -> every N minutes; runs whether or not the user is logged
    # on is NOT set (avoids storing a password); runs on the user's session.
    args = [
        "schtasks", "/Create", "/TN", _TASK_NAME, "/TR", cmd,
        "/SC", "MINUTE", "/MO", str(every_min), "/F",
    ]
    r = subprocess.run(args, capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    if r.returncode == 0:
        print(f"\nOK. Tarea '{_TASK_NAME}' creada: corre cada {every_min} min.")
        print("Ver/ejecutar:  schtasks /Run /TN " + _TASK_NAME)
    return r.returncode


def _remove() -> int:
    if os.name != "nt":
        print("No es Windows: edita tu crontab para quitar la linea.")
        return 0
    r = subprocess.run(["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
                       capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    return r.returncode


def _status() -> int:
    if os.name != "nt":
        print("No es Windows: revisa tu crontab (crontab -l).")
        return 0
    r = subprocess.run(["schtasks", "/Query", "/TN", _TASK_NAME],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Tarea '{_TASK_NAME}' no instalada. "
              "Instala con: python scripts/install_research_daemon.py --install")
        return 0
    print(r.stdout.strip())
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Instala el researcher de fondo de Cognia.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--install", action="store_true")
    g.add_argument("--remove", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--every-min", type=int, default=60,
                    help="Frecuencia en minutos (default 60).")
    args = ap.parse_args()

    if args.install:
        sys.exit(_install(args.every_min))
    elif args.remove:
        sys.exit(_remove())
    else:
        sys.exit(_status())


if __name__ == "__main__":
    main()
