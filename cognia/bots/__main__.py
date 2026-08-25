# -*- coding: utf-8 -*-
"""
python -m cognia.bots — el daemon del modo BOTS y su estado.

    python -m cognia.bots daemon [--intervalo 60] [--once] [--forzar]
    python -m cognia.bots estado
    python -m cognia.bots instalar [--cada-min 1]
    python -m cognia.bots desinstalar

POR QUE UN DAEMON APARTE: el carril de rutinas del REPL (cli._arrancar_
carril_rutinas) solo vive mientras el REPL esta abierto y solo conoce las
rutinas GLOBALES. Hermes Bot Mode (docs/user-guide/bot-mode) corre las
rutinas de cada bot y entrega los mensajes entre bots desde un scheduler con
tick de 60 s que no depende de ninguna sesion abierta. Aqui es este proceso:
por cada bot, dentro de su contexto, rutinas.tick(...) + procesar_inbox(...).

LIVENESS (mismo patron que hermes/rutinas y que el daemon de investigacion,
scripts/cognia_research_daemon.py): <dir_bots>/daemon.pid con el pid y
<dir_bots>/daemon.latido con el epoch de la ultima vuelta. Dos ficheros a
proposito: el pid dice "hay un proceso", el latido dice "y esta dando
vueltas". Un pid vivo con latido viejo es un daemon colgado y `estado` lo
dice asi.

UNA INSTANCIA: si daemon.pid apunta a un proceso vivo no se arranca otro
(dos daemons sobre el mismo inbox entregarian el mismo mensaje dos veces).
Un pid que NO se puede probar muerto (rutinas._pid_existe -> None) se trata
como vivo salvo que el latido tenga mas de LATIDO_RANCIO_S: un fichero
rancio no puede bloquear las rutinas para siempre.

SCHEDULED TASK (Windows): `instalar` crea la tarea CogniaBots que corre
`daemon --once` cada N minutos, copiando scripts/install_research_daemon.py
(Windows es el dueno del reloj y el proceso muere entre vueltas: cero
memoria en reposo). En otros SO imprime la linea de cron equivalente.
La tarea NO corre `python -m cognia.bots` a pelo: schtasks arranca desde
System32, sin cwd, sin PYTHONUTF8 ni COGNIA_BOTS_DIR, y en esta maquina
`cognia` resolvia al paquete instalado en el venv (sin cognia/bots): fallaba
cada minuto sin dejar rastro (revision adversarial 2026-08-25). Corre un
LANZADOR <dir_bots>/daemon_tarea.cmd que hace cd a raiz_repo(), fija el
entorno y manda la salida a <dir_bots>/daemon.log; `estado` ensena la cola
de ese log.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("cognia.bots.daemon")

TAREA_WINDOWS = "CogniaBots"
LATIDO_RANCIO_S = 15 * 60


# ---------------------------------------------------------------------------
# pid + latido
# ---------------------------------------------------------------------------

def _dir() -> Path:
    from cognia.bots import registro as R
    d = R.dir_bots()
    d.mkdir(parents=True, exist_ok=True)
    return d


def fichero_pid() -> Path:
    return _dir() / "daemon.pid"


def fichero_latido() -> Path:
    return _dir() / "daemon.latido"


def fichero_log() -> Path:
    """Salida del daemon cuando nadie lo mira (/bots daemon arrancar y la
    Scheduled Task escriben aqui)."""
    return _dir() / "daemon.log"


def fichero_lanzador() -> Path:
    return _dir() / "daemon_tarea.cmd"


def raiz_repo() -> Path:
    """Directorio que contiene el paquete `cognia` que corre AHORA (el
    worktree en desarrollo; site-packages si esta instalado). Es el cwd y el
    PYTHONPATH que necesita `python -m cognia.bots` lanzado desde otro
    sitio: sin esto resolvia a otro `cognia` (el instalado) sin este
    paquete."""
    import cognia
    return Path(cognia.__file__).resolve().parent.parent


def cola_log(n: int = 6) -> list:
    """Ultimas `n` lineas no vacias de daemon.log ([] si no hay)."""
    try:
        texto = fichero_log().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lineas = [l.rstrip() for l in texto.splitlines() if l.strip()]
    return lineas[-n:]


def escribir_latido() -> None:
    try:
        fichero_latido().write_text("%d\n" % int(time.time()), encoding="utf-8")
    except OSError as exc:
        logger.warning("bots: no pude escribir el latido: %s", exc)


def edad_latido():
    """Segundos desde la ultima vuelta, o None si nunca hubo."""
    try:
        return time.time() - int(fichero_latido().read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return None


def daemon_vivo():
    """(pid, vivo). vivo=None cuando el pid existe pero no se pudo probar."""
    try:
        pid = int(fichero_pid().read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return None, False
    if pid <= 0:
        return None, False
    from cognia.hermes.rutinas import _pid_existe
    return pid, _pid_existe(pid)


def _puedo_arrancar() -> str | None:
    """None si se puede arrancar; si no, el motivo (visible)."""
    pid, vivo = daemon_vivo()
    if pid is None or vivo is False:
        return None
    edad = edad_latido()
    if vivo is None and (edad is None or edad > LATIDO_RANCIO_S):
        print("[bots] daemon.pid=%d no se pudo comprobar y el latido es rancio "
              "(%s s): lo doy por muerto y sigo." % (pid, int(edad) if edad else "?"),
              flush=True)
        return None
    return ("ya hay un daemon de bots (pid %d, latido hace %s s); no arranco "
            "otro. Si es un pid rancio borra %s" % (
                pid, int(edad) if edad is not None else "?", fichero_pid()))


# ---------------------------------------------------------------------------
# la vuelta
# ---------------------------------------------------------------------------

def una_vuelta(forzar: bool = False, imprimir=print) -> dict:
    """Por cada bot: rutinas (tick, o TODAS forzadas) y luego el inbox. Un
    bot que rompe no para a los demas, pero se IMPRIME y se loguea: el daemon
    no muere y tampoco calla."""
    from cognia.bots import registro as R, mensajeria as M, ejecutor as E
    resumen = {"bots": 0, "corridas": 0, "mensajes": 0, "errores": []}
    for bot in R.listar():
        resumen["bots"] += 1
        try:
            if forzar:
                from cognia.hermes import rutinas
                with E.entorno_rutinas(bot, lectura=True):
                    nombres = [r["nombre"] for r in rutinas.listar() if r.get("activa", True)]
                for nombre in nombres:
                    inf = E.correr_rutina_ahora(bot, nombre)
                    resumen["corridas"] += 1
                    for linea in inf.get("lineas", []):
                        imprimir(linea)
            else:
                inf = E.tick_bot(bot)
                if inf.get("error"):
                    resumen["errores"].append("%s/rutinas: %s" % (bot.nombre, inf["error"]))
                    imprimir("[bots] %s: tick con error: %s" % (bot.nombre, inf["error"]))
                resumen["corridas"] += len(inf.get("corridas", []))
                for linea in inf.get("lineas", []):
                    imprimir(linea)
            n = E.procesar_inbox(bot)
            resumen["mensajes"] += n
            if n:
                imprimir("[bots] %s: %d mensaje(s) del inbox procesados" % (bot.nombre, n))
        except Exception as exc:                # noqa: BLE001 - visible, no mata la vuelta
            logger.exception("bots: la vuelta de %s rompio", bot.nombre)
            resumen["errores"].append("%s: %s: %s" % (bot.nombre, type(exc).__name__, exc))
            imprimir("[bots] %s: ERROR %s: %s" % (bot.nombre, type(exc).__name__, exc))
    escribir_latido()
    return resumen


def daemon(intervalo: float = 60.0, once: bool = False, forzar: bool = False) -> int:
    motivo = _puedo_arrancar()
    if motivo:
        print("[bots] " + motivo, flush=True)
        return 2
    try:
        fichero_pid().write_text("%d\n" % os.getpid(), encoding="utf-8")
    except OSError as exc:
        print("[bots] no pude escribir %s: %s" % (fichero_pid(), exc), flush=True)
        return 2
    from cognia.bots import registro as R
    print("[bots] daemon pid %d sobre %s (%s bots, intervalo %ss%s)" % (
        os.getpid(), R.dir_bots(), len(R.listar()), int(intervalo),
        ", una vuelta" if once else ""), flush=True)
    try:
        while True:
            t0 = time.time()
            resumen = una_vuelta(forzar=forzar)
            print("[bots] vuelta %s: %s" % (
                time.strftime("%H:%M:%S"), json.dumps(resumen, ensure_ascii=False)),
                flush=True)
            if once:
                return 1 if resumen["errores"] else 0
            forzar = False                   # --forzar solo aplica a la primera
            time.sleep(max(1.0, intervalo - (time.time() - t0)))
    except KeyboardInterrupt:
        print("[bots] detenido", flush=True)
        return 0
    finally:
        try:
            fichero_pid().unlink()
        except OSError:
            logger.warning("bots: no pude borrar %s", fichero_pid())


# ---------------------------------------------------------------------------
# estado
# ---------------------------------------------------------------------------

def estado_texto() -> str:
    from cognia.bots import registro as R, mensajeria as M, ejecutor as E
    from cognia.hermes import rutinas
    lineas = ["Bots en %s" % R.dir_bots()]
    bots = R.listar()
    if not bots:
        lineas.append("  (ninguno; crea uno con /bots crear <nombre>)")
    for b in bots:
        with E.entorno_rutinas(b, lectura=True):
            todas = rutinas.listar()
            debidas = len(rutinas.pendientes())
        proxima = next((r.get("proxima_en") for r in todas if r.get("proxima_en")), None)
        act = R.ultima_actividad(b)
        lineas.append("  %s %s (%s)%s: rutinas %d (%d debidas, proxima %s), inbox %d, "
                      "ultimo mensaje %s" % (
                          b.glifo, b.nombre, b.titulo or "sin titulo",
                          " [oculto]" if b.oculto else "",
                          len(todas), debidas, proxima or "-", len(M.pendientes(b)),
                          time.strftime("%Y-%m-%d %H:%M", time.localtime(act)) if act else "nunca"))
    pid, vivo = daemon_vivo()
    edad = edad_latido()
    if pid is None:
        lineas.append("Daemon: no corre (python -m cognia.bots daemon)")
    else:
        estado_pid = {True: "vivo", False: "MUERTO (pid rancio)", None: "no comprobable"}[vivo]
        lineas.append("Daemon: pid %d %s; latido %s" % (
            pid, estado_pid, ("hace %d s" % edad) if edad is not None else "nunca"))
        if vivo and edad is not None and edad > LATIDO_RANCIO_S:
            lineas.append("  AVISO: el proceso vive pero lleva %d s sin dar vuelta (colgado?)" % edad)
    if os.name == "nt":
        r = subprocess.run(["schtasks", "/Query", "/TN", TAREA_WINDOWS],
                           capture_output=True, text=True)
        lineas.append("Tarea programada %s: %s" % (
            TAREA_WINDOWS, ("instalada (%s)" % fichero_lanzador()) if r.returncode == 0
            else "no instalada"))
    cola = cola_log(3)
    if cola:
        # El unico rastro de un daemon sin consola: si la tarea o el hijo de
        # /bots daemon arrancar fallan, se ve AQUI y no en ningun otro sitio.
        lineas.append("daemon.log (%s), ultimas lineas:" % fichero_log())
        lineas.extend("  " + l for l in cola)
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Scheduled Task (copia de scripts/install_research_daemon.py)
# ---------------------------------------------------------------------------

def texto_lanzador() -> str:
    """El .cmd que corre la Scheduled Task: cd a la raiz del repo, PYTHONUTF8,
    PYTHONPATH, COGNIA_BOTS_DIR y la salida a daemon.log (la tarea no tiene
    consola). CRLF: es un fichero de cmd.exe."""
    raiz = raiz_repo()
    return ("@echo off\r\n"
            'cd /d "%s"\r\n' % raiz +
            "set PYTHONUTF8=1\r\n"
            "set PYTHONPATH=%s;%%PYTHONPATH%%\r\n" % raiz +
            "set COGNIA_BOTS_DIR=%s\r\n" % _dir() +
            '"%s" -m cognia.bots daemon --once >> "%s" 2>&1\r\n' % (
                sys.executable, fichero_log()))


def _comando_tarea() -> str:
    """Lo que corre la tarea: el lanzador, no el interprete a pelo (ver
    docstring del modulo)."""
    return '"%s"' % fichero_lanzador()


def entorno_hijo() -> dict:
    """La env con la que arranca cualquier hijo del daemon (Popen o tarea):
    PYTHONUTF8, PYTHONPATH a la raiz del paquete que corre AHORA y
    COGNIA_BOTS_DIR heredado. Es lo mismo que fija el lanzador .cmd."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    raiz = str(raiz_repo())
    previo = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = raiz if not previo else raiz + os.pathsep + previo
    env["COGNIA_BOTS_DIR"] = str(_dir())
    return env


def arrancar_en_fondo(espera_s: float = 2.0, intervalo: float = 60.0) -> dict:
    """Lanza `python -m cognia.bots daemon` DESACOPLADO (cwd = raiz del
    paquete, env de entorno_hijo(), salida a daemon.log) y COMPRUEBA que siga
    vivo pasados `espera_s`: '/bots daemon arrancar' decia 'lanzado' aunque
    el hijo muriera al instante por 'No module named cognia.bots' (revision
    adversarial 2026-08-25). Devuelve {"ok", "pid", "motivo", "log"}; con
    ok=False el motivo lleva la cola del log."""
    motivo = _puedo_arrancar()
    if motivo:
        return {"ok": False, "pid": None, "motivo": motivo, "log": str(fichero_log())}
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        log = open(fichero_log(), "a", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "pid": None, "log": str(fichero_log()),
                "motivo": "no pude abrir %s: %s" % (fichero_log(), exc)}
    try:
        p = subprocess.Popen(
            [sys.executable, "-m", "cognia.bots", "daemon", "--intervalo", str(intervalo)],
            cwd=str(raiz_repo()), env=entorno_hijo(), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except OSError as exc:
        log.close()
        return {"ok": False, "pid": None, "log": str(fichero_log()),
                "motivo": "no pude lanzar el daemon: %s" % exc}
    log.close()
    time.sleep(max(0.0, espera_s))
    if p.poll() is not None:
        cola = " | ".join(cola_log(3)) or "(daemon.log vacio)"
        return {"ok": False, "pid": p.pid, "log": str(fichero_log()),
                "motivo": "el daemon murio al arrancar (exit %s): %s" % (p.returncode, cola)}
    return {"ok": True, "pid": p.pid, "log": str(fichero_log()),
            "motivo": "daemon pid %d lanzado (cwd %s)" % (p.pid, raiz_repo())}


def escribir_lanzador() -> Path:
    f = fichero_lanzador()
    f.write_text(texto_lanzador(), encoding="utf-8", newline="")
    return f


def instalar(cada_min: int = 1) -> int:
    lanzador = escribir_lanzador()
    if os.name != "nt":
        print("No es Windows. Equivalente cron (crontab -e), usando el lanzador %s "
              "(cd al repo + PYTHONPATH + log):" % lanzador)
        print("  */%d * * * * cd '%s' && PYTHONUTF8=1 PYTHONPATH='%s' COGNIA_BOTS_DIR='%s' "
              "'%s' -m cognia.bots daemon --once >> '%s' 2>&1" % (
                  cada_min, raiz_repo(), raiz_repo(), _dir(), sys.executable, fichero_log()))
        return 0
    args = ["schtasks", "/Create", "/TN", TAREA_WINDOWS, "/TR", _comando_tarea(),
            "/SC", "MINUTE", "/MO", str(max(1, int(cada_min))), "/F"]
    r = subprocess.run(args, capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    if r.returncode == 0:
        print("OK. Tarea '%s' creada: corre %s cada %d min (cd %s; log en %s). "
              "Ver: schtasks /Query /TN %s" % (
                  TAREA_WINDOWS, lanzador, cada_min, raiz_repo(), fichero_log(),
                  TAREA_WINDOWS))
    return r.returncode


def desinstalar() -> int:
    if os.name != "nt":
        print("No es Windows: quita la linea de tu crontab.")
        return 0
    r = subprocess.run(["schtasks", "/Delete", "/TN", TAREA_WINDOWS, "/F"],
                       capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    return r.returncode


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cognia.bots",
                                 description="Daemon y estado del modo BOTS de Cognia.")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("daemon", help="tick de rutinas + inbox de cada bot")
    d.add_argument("--intervalo", type=float, default=60.0, help="segundos entre vueltas")
    d.add_argument("--once", action="store_true", help="una vuelta y salir")
    d.add_argument("--forzar", action="store_true",
                   help="correr YA todas las rutinas activas en la primera vuelta")
    sub.add_parser("estado", help="bots, rutinas, inbox y daemon")
    i = sub.add_parser("instalar", help="Scheduled Task de Windows (daemon --once)")
    i.add_argument("--cada-min", type=int, default=1)
    sub.add_parser("desinstalar", help="quita la Scheduled Task")
    args = ap.parse_args(argv)

    if os.environ.get("COGNIA_BOTS", "").strip().lower() in ("0", "off", "false"):
        print("[bots] COGNIA_BOTS=0: modo bots apagado.", flush=True)
        return 2

    if args.cmd == "daemon":
        logging.disable(logging.INFO)        # corre sin nadie delante
        return daemon(args.intervalo, once=args.once, forzar=args.forzar)
    if args.cmd == "estado":
        print(estado_texto())
        return 0
    if args.cmd == "instalar":
        return instalar(args.cada_min)
    if args.cmd == "desinstalar":
        return desinstalar()
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
