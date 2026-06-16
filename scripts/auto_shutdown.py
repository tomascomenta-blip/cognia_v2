"""
scripts/auto_shutdown.py
========================
Programa (o cancela) un apagado automatico del equipo a una hora fija usando el
mecanismo NATIVO del sistema operativo detectado:

  - Windows : Task Scheduler via PowerShell (Register-ScheduledTask) + shutdown.exe
  - Linux   : `at` si existe, si no `systemd-run --on-calendar`
  - macOS   : `at` / `shutdown -h` (requiere sudo)

Por defecto programa UNA sola vez para la PROXIMA ocurrencia de la hora (no toca
las noches siguientes). El apagado es CON GRACIA: avisa 60 s antes y NO fuerza el
cierre de apps (un documento sin guardar cancela el apagado). Cancelable en
cualquier momento.

Uso:
  .\\venv312\\Scripts\\python.exe scripts\\auto_shutdown.py            # programa 04:30 (una vez)
  .\\venv312\\Scripts\\python.exe scripts\\auto_shutdown.py --at 04:30 # hora explicita HH:MM
  .\\venv312\\Scripts\\python.exe scripts\\auto_shutdown.py --daily    # repetir cada dia
  .\\venv312\\Scripts\\python.exe scripts\\auto_shutdown.py --verify   # solo verificar
  .\\venv312\\Scripts\\python.exe scripts\\auto_shutdown.py --cancel   # cancelar la tarea

Cancelacion manual de emergencia (Windows):
  - Si ya empezo la cuenta de 60 s:  shutdown /a
  - Para borrar la tarea:            schtasks /delete /tn CogniaAutoShutdown /f
"""

import argparse
import datetime as _dt
import platform
import shutil
import subprocess
import sys

TASK_NAME = "CogniaAutoShutdown"
GRACE_SECONDS = 60
SHUTDOWN_MSG = "Cognia: apagado automatico programado. Guarda tu trabajo (shutdown /a para cancelar)."


def _next_occurrence(hh: int, mm: int) -> _dt.datetime:
    """Proxima fecha/hora HH:MM en hora local (hoy si aun no paso, si no manana)."""
    now = _dt.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    return target


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def _ps(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True,
    )


def windows_schedule(target: _dt.datetime, daily: bool) -> None:
    # quotes reales alrededor del mensaje; van dentro de un string PS single-quoted
    # (literal), por lo que llegan intactas al campo Arguments de la tarea.
    shutdown_args = f'/s /t {GRACE_SECONDS} /c "{SHUTDOWN_MSG}"'
    if daily:
        trigger = f"New-ScheduledTaskTrigger -Daily -At '{target:%H:%M}'"
    else:
        # ISO local — locale-independiente (evita el formato de fecha de /sd en schtasks)
        trigger = f"New-ScheduledTaskTrigger -Once -At ([datetime]'{target:%Y-%m-%dT%H:%M:%S}')"
    cmd = (
        f"$a = New-ScheduledTaskAction -Execute 'shutdown.exe' -Argument '{shutdown_args}';"
        f"$t = {trigger};"
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable;"
        "try {"
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
        "-Description 'Cognia auto-shutdown (graceful)' -Force -ErrorAction Stop | Out-Null;"
        "Write-Output 'REGISTERED'"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
    )
    r = _ps(cmd)
    if "REGISTERED" not in r.stdout:
        raise RuntimeError(f"Register-ScheduledTask fallo:\n{r.stdout}\n{r.stderr}")


def windows_verify() -> str:
    cmd = (
        f"$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop;"
        f"$info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}';"
        "$tr = $task.Triggers[0];"
        "Write-Output ('State      : ' + $task.State);"
        "Write-Output ('Action     : ' + $task.Actions[0].Execute + ' ' + $task.Actions[0].Arguments);"
        "Write-Output ('NextRun    : ' + $info.NextRunTime);"
        "Write-Output ('Trigger    : ' + $tr.CimClass.CimClassName)"
    )
    r = _ps(cmd)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Tarea '{TASK_NAME}' no encontrada:\n{r.stderr or r.stdout}")
    return r.stdout.strip()


def windows_cancel() -> str:
    r = _ps(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false; Write-Output 'CANCELLED'")
    if "CANCELLED" not in r.stdout:
        raise RuntimeError(f"No se pudo cancelar:\n{r.stdout}\n{r.stderr}")
    return "Tarea cancelada."


# --------------------------------------------------------------------------- #
# POSIX (Linux / macOS) — best effort, puede requerir sudo
# --------------------------------------------------------------------------- #
def posix_schedule(target: _dt.datetime, daily: bool) -> None:
    if daily:
        raise NotImplementedError(
            "Repeticion diaria en POSIX: usar cron/systemd-timer manualmente. "
            "Este script solo programa una vez en POSIX."
        )
    when = f"{target:%H:%M %Y-%m-%d}"
    if shutil.which("at"):
        subprocess.run(["at", when], input="shutdown -h now\n", text=True, check=True)
        return
    if shutil.which("systemd-run"):
        subprocess.run(
            ["systemd-run", "--on-calendar", f"{target:%Y-%m-%d %H:%M:00}",
             "--unit", TASK_NAME, "/sbin/shutdown", "-h", "now"],
            check=True,
        )
        return
    raise RuntimeError("Ni 'at' ni 'systemd-run' disponibles; no se pudo programar.")


def posix_verify() -> str:
    if shutil.which("atq"):
        return subprocess.run(["atq"], capture_output=True, text=True).stdout.strip() or "(sin jobs en atq)"
    if shutil.which("systemctl"):
        return subprocess.run(
            ["systemctl", "status", f"{TASK_NAME}.timer"], capture_output=True, text=True
        ).stdout.strip()
    return "Verificacion no disponible en este sistema."


def posix_cancel() -> str:
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "stop", f"{TASK_NAME}.timer"], capture_output=True, text=True)
    return "Cancelacion POSIX: revisar `atrm`/`systemctl` manualmente segun el mecanismo usado."


# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description="Programa un apagado automatico nativo.")
    p.add_argument("--at", default="04:30", help="Hora HH:MM (default 04:30)")
    p.add_argument("--daily", action="store_true", help="Repetir cada dia (default: una vez)")
    p.add_argument("--verify", action="store_true", help="Solo verificar la programacion")
    p.add_argument("--cancel", action="store_true", help="Cancelar la programacion")
    args = p.parse_args()

    osname = platform.system()
    is_win = osname == "Windows"

    if args.cancel:
        print(windows_cancel() if is_win else posix_cancel())
        return 0

    if args.verify:
        print(windows_verify() if is_win else posix_verify())
        return 0

    try:
        hh, mm = (int(x) for x in args.at.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except (ValueError, AssertionError):
        print(f"Hora invalida: {args.at!r} (esperado HH:MM)", file=sys.stderr)
        return 2

    target = _next_occurrence(hh, mm)
    print(f"SO detectado : {osname}")
    print(f"Modo         : {'DIARIO' if args.daily else 'UNA VEZ'}")
    print(f"Apagado a    : {target:%Y-%m-%d %H:%M} (hora local)  [+{GRACE_SECONDS}s de gracia]")

    if is_win:
        windows_schedule(target, args.daily)
    else:
        posix_schedule(target, args.daily)

    print("\n--- VERIFICACION ---")
    print(windows_verify() if is_win else posix_verify())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
