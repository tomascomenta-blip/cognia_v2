"""Programa el apagado del SO en una hora límite (deadline del modo manager).

Uso:
    python apagado_deadline.py 05:30          # apaga a las 05:30 (hoy si falta, si no mañana)
    python apagado_deadline.py 05:30 --dry    # solo calcula y muestra, no arma nada
    python apagado_deadline.py --cancel        # cancela un apagado ya armado

En Windows arma `shutdown /s /t <segundos>`; es idempotente (cancela con `shutdown /a`
antes de re-armar). El bucle del manager debe dejar todo commiteado+pusheado en cada
ciclo para que el corte a deadline sea seguro en cualquier momento.
"""
import argparse
import datetime as dt
import platform
import subprocess
import sys


def seconds_until(hh: int, mm: int, now: dt.datetime | None = None) -> tuple[int, dt.datetime]:
    now = now or dt.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return int((target - now).total_seconds()), target


def cancel() -> int:
    if platform.system() != "Windows":
        print("cancel solo aplica a Windows (shutdown /a)")
        return 0
    r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
    print(r.stdout or r.stderr or "apagado cancelado")
    return r.returncode


def arm(secs: int, target: dt.datetime, dry: bool) -> int:
    msg = f"Cognia manager: apagado programado a deadline {target:%H:%M}"
    if dry:
        print(f"[DRY] armaria: shutdown /s /t {secs}  -> {target.isoformat()}")
        return 0
    if platform.system() != "Windows":
        print(f"[no-Windows] simularia apagado en {secs}s ({target.isoformat()})")
        return 0
    subprocess.run(["shutdown", "/a"], capture_output=True, text=True)  # idempotencia
    r = subprocess.run(
        ["shutdown", "/s", "/t", str(secs), "/c", msg], capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"ERROR armando shutdown: {r.stderr.strip()}")
        return r.returncode
    print(f"OK apagado armado: {target.isoformat()} (en {secs}s = {secs/3600:.2f} h)")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Programa apagado del SO a una hora HH:MM")
    p.add_argument("hora", nargs="?", help="HH:MM (24h)")
    p.add_argument("--dry", action="store_true", help="no arma, solo calcula")
    p.add_argument("--cancel", action="store_true", help="cancela apagado armado")
    a = p.parse_args(argv)

    if a.cancel:
        return cancel()
    if not a.hora:
        p.error("falta HH:MM (o usa --cancel)")
    try:
        hh, mm = (int(x) for x in a.hora.split(":"))
    except ValueError:
        p.error(f"hora invalida: {a.hora!r} (esperado HH:MM)")
    secs, target = seconds_until(hh, mm)
    return arm(secs, target, a.dry)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
