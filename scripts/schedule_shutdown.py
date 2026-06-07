"""Programa un apagado de Windows a las 04:30 (próxima ocurrencia).

Uso:
    python scripts/schedule_shutdown.py            # programa apagado a las 04:30
    python scripts/schedule_shutdown.py --abort    # cancela un apagado pendiente
    python scripts/schedule_shutdown.py --at 03:15  # hora personalizada HH:MM

El apagado se cancela en cualquier momento con:  shutdown /a
"""
import argparse
import datetime as dt
import subprocess
import sys


def seconds_until(target_hhmm: str) -> int:
    hh, mm = (int(x) for x in target_hhmm.split(":"))
    now = dt.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return int((target - now).total_seconds()), target


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--at", default="04:30", help="hora objetivo HH:MM (default 04:30)")
    p.add_argument("--abort", action="store_true", help="cancela apagado pendiente")
    args = p.parse_args()

    if args.abort:
        subprocess.run(["shutdown", "/a"], check=False)
        print("Apagado pendiente cancelado (shutdown /a).")
        return 0

    secs, target = seconds_until(args.at)
    # /a primero por si ya hay uno programado, luego reprograma limpio
    subprocess.run(["shutdown", "/a"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run(
        ["shutdown", "/s", "/f", "/t", str(secs),
         "/c", f"Cognia manager: apagado programado {args.at}"],
        check=False, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR shutdown rc={r.returncode}: {r.stderr.strip()}", file=sys.stderr)
        return r.returncode
    print(f"Apagado programado para {target:%Y-%m-%d %H:%M} "
          f"(en {secs} s ~ {secs/3600:.2f} h). Cancelar con: shutdown /a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
