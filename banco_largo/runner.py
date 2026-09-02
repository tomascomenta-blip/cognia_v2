# -*- coding: utf-8 -*-
"""runner.py -- ejecuta una tarea del banco contra un CLI de Cognia y la EVALUA.

Corre `cognia hacer` en un proceso aparte, con:
  - workspace limpio por tarea (y por ronda),
  - presupuesto de PARED por tarea (mata el arbol de procesos al agotarse),
  - captura entera de stdout/stderr a disco,
  - telemetria derivada de la corrida,
  - evaluacion multicapa del producto (evaluador.evaluar).

El CLI bajo prueba se elige con `--python`: el del repo (local) o el de un venv
donde se instalo la version publicada en PyPI. El runner NO importa cognia.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from banco_largo import evaluador  # noqa: E402
from banco_largo import tareas as _tareas_mod  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PY_REPO = str(RAIZ / "venv312" / "Scripts" / "python.exe")


# -- telemetria derivada de la corrida ---------------------------------------

_RE_PRESUPUESTO = re.compile(r"Presupuesto de pasos:\s*(\d+)\s*\(techo\s*(\d+)\)")
_RE_COMANDO = re.compile(r"^\[detail\]\$\s+(.+?)(?:\[/detail\])?$", re.M)
_RE_ESCRITURA = re.compile(r"^\[detail\]---\s+a/(.+?)(?:\[/detail\])?$", re.M)
_RE_SATISFIED = re.compile(r"SATISFIED:\s*(\d+)/(\d+)")
_RE_COMPLETE = re.compile(r"COMPLETE:\s*(yes|no)")
_RE_PASO = re.compile(r"\bpaso\s+(\d+)\b", re.I)

MARCAS_TRUNCADO = [
    ("presupuesto_pasos", r"\(presupuesto de\b"),
    ("tope_salida", r"se corto por el tope"),
    ("estancamiento", r"estancamiento|sin progreso verificado"),
    ("backend", r"no pudo hablar con el modelo"),
    ("respuesta_vacia", r"cerro con una respuesta vacia"),
    ("contexto", r"compactaci|no cabe|context.{0,12}(lleno|excedid)"),
    ("tool_call_cortado", r"Failed to parse tool call|tool call cortad"),
]

_RE_ERROR = re.compile(
    r"Traceback \(most recent call last\)|SyntaxError|NameError|TypeError|"
    r"ReferenceError|ModuleNotFoundError|AttributeError|exit=1\b|FAILED\b", re.I)


def telemetria_de(stderr, stdout_json, segundos, matado, ws):
    tel = {"segundos": round(segundos, 1), "matado_por_presupuesto": bool(matado)}
    m = _RE_PRESUPUESTO.search(stderr)
    tel["pasos_presupuestados"] = int(m.group(1)) if m else None
    tel["techo_pasos"] = int(m.group(2)) if m else None

    comandos = _RE_COMANDO.findall(stderr)
    escrituras = _RE_ESCRITURA.findall(stderr)
    tel["comandos"] = comandos[:60]
    tel["n_comandos"] = len(comandos)
    tel["ficheros_tocados"] = sorted(set(escrituras))[:80]
    tel["n_escrituras"] = len(escrituras)

    nombres = {}
    for c in comandos:
        base = (c.strip().split() or ["?"])[0]
        nombres["$" + os.path.basename(base)] = nombres.get("$" + os.path.basename(base), 0) + 1
    if escrituras:
        nombres["escribir_archivo"] = len(escrituras)
    tel["tool_calls_por_nombre"] = nombres
    tel["n_tool_calls"] = len(comandos) + len(escrituras)

    tel["errores_vistos"] = len(_RE_ERROR.findall(stderr))
    # "reparado": hubo un error y DESPUES una ejecucion que no lo repite
    ultimo_error = 0
    for m2 in _RE_ERROR.finditer(stderr):
        ultimo_error = m2.end()
    cola = stderr[ultimo_error:]
    tel["errores_reparados"] = 1 if (tel["errores_vistos"] and
                                     len(_RE_COMANDO.findall(cola)) >= 1) else 0
    tel["ejecuciones_ok"] = max(0, len(comandos) - tel["errores_vistos"])
    tel["ejecuciones_fallo"] = min(len(comandos), tel["errores_vistos"])

    m = _RE_SATISFIED.search(stderr)
    tel["criterios_propios"] = "%s/%s" % (m.group(1), m.group(2)) if m else None
    m = _RE_COMPLETE.search(stderr)
    tel["agente_dice_completo"] = (m.group(1) == "yes") if m else None

    pasos = [int(x) for x in _RE_PASO.findall(stderr)]
    tel["paso_max_visto"] = max(pasos) if pasos else None

    motivos = []
    respuesta = (stdout_json or {}).get("respuesta", "") or ""
    texto = stderr + "\n" + respuesta
    for nombre, pat in MARCAS_TRUNCADO:
        if re.search(pat, texto, re.I):
            motivos.append(nombre)
    if matado:
        motivos.append("presupuesto_pared")
    tel["motivos_truncado"] = motivos
    tel["truncado"] = bool(motivos)

    tel["longitud_respuesta"] = len(respuesta)
    tel["stderr_bytes"] = len(stderr)
    return tel


# -- ejecucion ---------------------------------------------------------------

def _matar_arbol(pr):
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pr.pid)],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        pr.kill()
    except Exception:
        pass


def correr_tarea(tarea, dir_ronda, python_cli, cwd_cli=None, extra_env=None,
                 factor_presupuesto=1.0, imprimir=print):
    """Ejecuta UNA tarea completa y devuelve el registro con evaluacion."""
    tid = tarea["id"]
    ws = Path(dir_ronda) / tid
    if ws.exists():
        shutil.rmtree(str(ws), ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in (tarea.get("semilla") or {}).items():
        p = ws / nombre
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")

    presupuesto = int(float(tarea.get("presupuesto_s") or 300) * factor_presupuesto)
    if os.environ.get("BANCO_PRESUPUESTO"):
        presupuesto = int(os.environ["BANCO_PRESUPUESTO"])
    pasos = int(tarea.get("pasos") or 40)
    cmd = [python_cli, "-m", "cognia", "hacer", tarea["prompt"],
           "--json", "--pasos", str(pasos), "--cwd", str(ws)]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["COGNIA_BANCO"] = "1"
    logdir = Path(dir_ronda) / "_logs"
    logdir.mkdir(parents=True, exist_ok=True)
    # El diario objetivo del bucle (tokens, tool calls, cortes, motivo de
    # cierre). Si el CLI bajo prueba es viejo y no lo conoce, la variable
    # sobra y el runner cae a la lectura de stderr sin perder la corrida.
    ruta_tel = logdir / ("%s.tel.jsonl" % tid)
    if ruta_tel.exists():
        ruta_tel.unlink()
    env["COGNIA_TELEMETRIA"] = str(ruta_tel)
    # El agente tiene que SABER cuanto reloj le queda: sin esto sus compuertas
    # deciden "sigue trabajando" cuando ya no hay pared para trabajar.
    env["COGNIA_PARED_S"] = str(presupuesto)
    if extra_env:
        env.update(extra_env)
    fo = open(logdir / ("%s.out.log" % tid), "w", encoding="utf-8", errors="replace")
    fe = open(logdir / ("%s.err.log" % tid), "w", encoding="utf-8", errors="replace")

    imprimir("  -> %s (presupuesto %ds, pasos %d)" % (tid, presupuesto, pasos))
    t0 = time.time()
    matado = False
    try:
        pr = subprocess.Popen(cmd, cwd=str(cwd_cli or RAIZ), stdout=fo, stderr=fe, env=env)
        try:
            codigo = pr.wait(timeout=presupuesto)
        except subprocess.TimeoutExpired:
            matado = True
            _matar_arbol(pr)
            try:
                codigo = pr.wait(timeout=20)
            except Exception:
                codigo = -9
    except Exception as e:
        codigo = -1
        fe.write("\n[runner] no pude lanzar el CLI: %s\n" % e)
    finally:
        fo.close()
        fe.close()
    segundos = time.time() - t0

    salida = (logdir / ("%s.out.log" % tid)).read_text(encoding="utf-8", errors="replace")
    errores = (logdir / ("%s.err.log" % tid)).read_text(encoding="utf-8", errors="replace")
    try:
        i = salida.index("{")
        stdout_json = json.loads(salida[i:])
    except Exception:
        stdout_json = None

    tel = telemetria_de(errores, stdout_json, segundos, matado, ws)
    tel["exit"] = codigo
    tel["hubo_json"] = stdout_json is not None
    # El diario del propio bucle MANDA sobre lo derivado de stderr: son los
    # numeros del bucle, no una estimacion de fuera.
    diario = {}
    if ruta_tel.exists():
        try:
            sys.path.insert(0, str(RAIZ))
            from cognia.harness import telemetria as _tel_mod
            diario = _tel_mod.resumir(str(ruta_tel))
        except Exception as e:
            diario = {"error": "%s: %s" % (type(e).__name__, e)}
    if diario and not diario.get("error"):
        tel["diario"] = diario
        tel["tokens_entrada"] = diario.get("tokens_entrada")
        tel["tokens_salida"] = diario.get("tokens_salida")
        tel["tokens_totales"] = diario.get("tokens_totales")
        tel["n_tool_calls"] = diario.get("tool_calls", tel["n_tool_calls"])
        tel["tool_calls_por_nombre"] = diario.get("tool_calls_por_nombre",
                                                  tel["tool_calls_por_nombre"])
        tel["pasos"] = diario.get("cierre_pasos") or diario.get("turnos")
        tel["pasos_presupuestados"] = diario.get("presupuesto_pasos",
                                                 tel["pasos_presupuestados"])
        tel["techo_pasos"] = diario.get("techo_pasos", tel["techo_pasos"])
        tel["cierre_razon"] = diario.get("cierre_razon")
        tel["ejecuciones_fallo"] = diario.get("tool_calls_fallidas", tel["ejecuciones_fallo"])
        tel["ejecuciones_ok"] = max(0, (diario.get("tool_calls") or 0)
                                    - (diario.get("tool_calls_fallidas") or 0))
        if diario.get("turnos_cortados_por_tope"):
            if "tope_salida" not in tel["motivos_truncado"]:
                tel["motivos_truncado"].append("tope_salida")
            tel["truncado"] = True
        if (diario.get("cierre_razon") or "") in ("presupuesto_agotado",
                                                  "estancado_sin_progreso",
                                                  "bucle_detectado", "error_backend"):
            if diario["cierre_razon"] not in tel["motivos_truncado"]:
                tel["motivos_truncado"].append(diario["cierre_razon"])
            tel["truncado"] = True

    imprimir("     evaluando el producto...")
    t1 = time.time()
    try:
        ev = evaluador.evaluar(tarea, ws, tel)
    except Exception as e:
        ev = {"tarea": tid, "veredicto": "error_evaluador", "global": 0.0,
              "capas": {}, "resultados": [], "n_pruebas": 0, "n_pasadas": 0,
              "error": "%s: %s" % (type(e).__name__, e)}
    ev["ms_evaluacion"] = int((time.time() - t1) * 1000)

    reg = {
        "id": tid, "familia": tarea.get("familia"), "dificultad": tarea.get("dificultad"),
        "presupuesto_s": presupuesto, "telemetria": tel, "evaluacion": ev,
        "respuesta": (stdout_json or {}).get("respuesta", "")[:4000],
        "workspace": str(ws),
    }
    (Path(dir_ronda) / ("%s.json" % tid)).write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    imprimir("     %s  global=%.2f  func=%s  comp=%s  %ds%s" % (
        ev["veredicto"], ev["global"],
        ev["capas"].get("funcionalidad", {}).get("nota"),
        ev["capas"].get("completitud", {}).get("nota"),
        int(segundos), "  TRUNCADO:%s" % ",".join(tel["motivos_truncado"]) if tel["truncado"] else ""))
    return reg


def otras_rondas_vivas():
    """Runners o agentes `cognia hacer` ya corriendo en esta maquina (no este).

    EL BANCO NO COMPARTE MAQUINA: una ronda que arranca encima de otra
    contamina las dos (medido: la misma version paso de 0,544 a 0,418 solo por
    compartir la GPU). Y paso dos veces hoy por cadenas de shell mal escritas.
    Mejor que el runner se niegue a arrancar que confiar en el script de turno.
    """
    try:
        pr = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.ProcessId -ne %d -and ($_.CommandLine -like '*banco_largo.runner*' "
             "-or $_.CommandLine -like '*-m cognia hacer*') } | "
             "ForEach-Object { $_.ProcessId }" % os.getpid()],
            capture_output=True, text=True, timeout=30)
        return [x.strip() for x in (pr.stdout or "").splitlines() if x.strip()]
    except Exception:
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(prog="banco_largo.runner")
    ap.add_argument("--forzar", action="store_true",
                    help="arranca aunque haya otra ronda o un agente corriendo (contamina)")
    ap.add_argument("--ronda", required=True, help="nombre de la ronda (directorio de salida)")
    ap.add_argument("--python", default=PY_REPO, help="interprete con el cognia bajo prueba")
    ap.add_argument("--cwd-cli", default=None, help="cwd del proceso del CLI (para elegir repo o instalado)")
    ap.add_argument("--tareas", default="", help="ids separados por coma (por defecto, todas)")
    ap.add_argument("--familia", default="", help="filtra por familia")
    ap.add_argument("--dificultad-max", type=int, default=9)
    ap.add_argument("--factor", type=float, default=1.0, help="multiplica el presupuesto de pared")
    ap.add_argument("--deadline", default="", help="HH:MM local; al pasarla, no se lanzan mas tareas")
    ap.add_argument("--vigilar", action="store_true",
                    help="relee el catalogo y corre las tareas nuevas hasta el deadline")
    ap.add_argument("--salida", default=str(RAIZ / "banco_largo" / "corridas"))
    args = ap.parse_args(argv)

    # Primero se ESPERA (hasta 3 min): en la costura entre dos rondas
    # encadenadas el runner anterior sigue vivo un par de segundos y abortar
    # ahi rompia la cadena entera (paso 2026-09-01 19:41). Solo si siguen
    # vivos pasado ese margen es que hay otra ronda de verdad.
    vivas = otras_rondas_vivas()
    t_espera = time.time()
    while vivas and not args.forzar and time.time() - t_espera < 180:
        print("[banco] esperando a que terminen %d proceso(s) de otra ronda (pids %s)"
              % (len(vivas), ", ".join(vivas[:6])), flush=True)
        time.sleep(15)
        vivas = otras_rondas_vivas()
    if vivas and not args.forzar:
        print("[banco] NO ARRANCO: sigue habiendo %d proceso(s) de runner o de `cognia hacer` "
              "corriendo (pids %s). Una ronda encima de otra contamina las dos. "
              "Espera a que terminen o pasa --forzar." % (len(vivas), ", ".join(vivas[:6])),
              flush=True)
        return 3

    todas = _tareas_mod.cargar(estricto=False)
    ids = [x.strip() for x in args.tareas.split(",") if x.strip()]
    sel = [t for t in todas
           if (not ids or t["id"] in ids)
           and (not args.familia or t.get("familia") == args.familia)
           and int(t.get("dificultad", 3)) <= args.dificultad_max]

    dir_ronda = Path(args.salida) / args.ronda
    dir_ronda.mkdir(parents=True, exist_ok=True)

    limite = None
    if args.deadline:
        hh, mm = args.deadline.split(":")
        ahora = time.localtime()
        limite = time.mktime((ahora.tm_year, ahora.tm_mon, ahora.tm_mday,
                              int(hh), int(mm), 0, 0, 0, -1))
        if limite < time.time():
            limite += 86400

    print("[banco] ronda=%s  tareas=%d  cli=%s" % (args.ronda, len(sel), args.python), flush=True)
    registros = []
    saltadas = []
    vueltas = 0
    while True:
        vueltas += 1
        # En modo vigilar se relee el catalogo en cada vuelta: las tareas que
        # aparecen mientras la ronda corre entran solas. Lo que ya tiene su
        # JSON en el directorio de la ronda no se repite.
        if args.vigilar and vueltas > 1:
            try:
                todas = _tareas_mod.cargar(estricto=False)
            except Exception as e:
                print("[banco] catalogo ilegible en esta vuelta: %s" % e, flush=True)
            sel = [t for t in todas
                   if (not ids or t["id"] in ids)
                   and (not args.familia or t.get("familia") == args.familia)
                   and int(t.get("dificultad", 3)) <= args.dificultad_max]
        pendientes = [t for t in sel if not (dir_ronda / ("%s.json" % t["id"])).exists()]
        if not pendientes:
            if not args.vigilar:
                break
            if limite and time.time() > limite - 60:
                break
            print("[banco] sin pendientes; espero catalogo nuevo (%d listas)"
                  % len(sel), flush=True)
            time.sleep(45)
            continue
        for t in pendientes:
            if limite and time.time() + float(t.get("presupuesto_s") or 300) * args.factor > limite:
                if t["id"] not in saltadas:
                    saltadas.append(t["id"])
                    print("[banco] SALTADA por deadline: %s" % t["id"], flush=True)
                continue
            print("[banco] %s (d%s, %s) -- hechas %d" % (t["id"], t.get("dificultad"),
                                                         t.get("familia"), len(registros)),
                  flush=True)
            registros.append(correr_tarea(t, dir_ronda, args.python, args.cwd_cli,
                                          factor_presupuesto=args.factor))
            resumen = {"ronda": args.ronda, "cli": args.python, "registros": registros,
                       "saltadas": saltadas, "factor": args.factor,
                       "sello": time.strftime("%Y-%m-%d %H:%M:%S")}
            (dir_ronda / "corrida.json").write_text(
                json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.vigilar:
            break
        if limite and time.time() > limite - 60:
            break
    print("[banco] fin. %d ejecutadas, %d saltadas" % (len(registros), len(saltadas)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
