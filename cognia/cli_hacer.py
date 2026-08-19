# -*- coding: utf-8 -*-
"""
cognia/cli_hacer.py — `cognia hacer "<tarea>"`: el agente SIN el REPL.

POR QUE EXISTE (2026-08-18). Hasta hoy la unica forma de darle una tarea al
agente era entrar al REPL y escribir /hacer. Eso deja fuera todo lo que no es
una persona tecleando:

  - automatizar (un script, un cron, un hook de git, CI),
  - encadenar con otras herramientas por tuberia,
  - MEDIR el propio CLI de forma reproducible.

Lo delata el gate de pre-release del repo: `scripts/e2e_happy_path.py` no puede
usar el CLI y llama a `cli._run_agent_task()` por dentro. Un gate que no puede
pasar por la puerta del producto no esta midiendo el producto.

CONTRATO DE LA SALIDA (lo que hace que sirva en una tuberia):
  stdout  = SOLO el resultado final de la tarea. Nada mas.
  stderr  = progreso, avisos y diagnostico.
  codigo  = 0 la tarea termino, 1 fallo, 2 uso incorrecto, 130 Ctrl-C.
Con --json, stdout lleva UN objeto JSON con el resultado y los metadatos.

Es el MISMO camino que /hacer (cli._run_agent_task): no hay una segunda
implementacion del agente que se pueda desincronizar de la primera.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time


def _leer_tarea(args_tarea: list) -> str:
    """La tarea, de los argumentos o de stdin (tuberia)."""
    if args_tarea:
        return " ".join(args_tarea).strip()
    # `echo "arregla el bug" | cognia hacer` tiene que funcionar: es la forma
    # natural de encadenar. Solo se lee stdin si NO es una terminal (si lo es,
    # quedarse esperando input parece un cuelgue).
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def main(argv: list = None) -> int:
    argv = list(sys.argv[2:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="cognia hacer",
        description="Ejecuta una tarea con el agente y sale (sin REPL).")
    ap.add_argument("tarea", nargs="*",
                    help='que hacer, p.ej. "crea index.html con un saludo". '
                         "Si se omite, se lee de stdin.")
    ap.add_argument("--pasos", type=int, default=None,
                    help="tope de pasos del agente (por defecto lo estima el "
                         "presupuesto dinamico)")
    ap.add_argument("--json", action="store_true",
                    help="stdout = un objeto JSON con resultado y metadatos")
    ap.add_argument("--silencioso", "-s", action="store_true",
                    help="sin progreso en stderr")
    ap.add_argument("--cwd", default=None,
                    help="directorio de trabajo del agente (por defecto, este)")
    args = ap.parse_args(argv)

    tarea = _leer_tarea(args.tarea)
    if not tarea:
        print('Uso: cognia hacer "<tarea>"   (o pasarla por stdin)',
              file=sys.stderr)
        return 2

    # El cwd se RESTAURA al salir (2026-08-18). Cambiarlo y dejarlo cambiado
    # es invisible cuando el proceso termina justo despues, pero convierte a
    # esta funcion en una bomba para cualquiera que la llame en proceso: la
    # suite del repo la cazo en el acto -- once tests posteriores reventaron
    # con FileNotFoundError sobre rutas RELATIVAS porque el directorio ya no
    # era el que ellos creian.
    _cwd_previo = os.getcwd()
    if args.cwd:
        try:
            os.chdir(args.cwd)
        except OSError as exc:
            print(f"[cognia] no puedo entrar en {args.cwd}: {exc}",
                  file=sys.stderr)
            return 2

    def progreso(linea) -> None:
        # A stderr SIEMPRE: stdout es del resultado. Sin esto, `cognia hacer
        # ... > salida.txt` mezcla el razonamiento con la respuesta y la
        # tuberia deja de servir para nada.
        if not args.silencioso:
            print(str(linea), file=sys.stderr, flush=True)

    try:
        return _hacer(args, tarea, progreso)
    finally:
        try:
            os.chdir(_cwd_previo)
        except OSError:
            pass


def _hacer(args, tarea: str, progreso) -> int:
    """El trabajo en si. Separado para que main() garantice el cwd con finally."""
    t0 = time.time()
    try:
        from cognia.first_run import apply_config
        apply_config()
        from cognia.cognia import Cognia
        from cognia import cli as _cli
    except Exception as exc:
        print(f"[cognia] no pude cargar el agente: {exc}", file=sys.stderr)
        return 1

    # Cognia() escribe su arranque por stdout (memoria, grafo, backend). En el
    # REPL eso se muestra; aca contaminaria la salida util, asi que se captura
    # y se manda a stderr como progreso.
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            ai = Cognia()
    except Exception as exc:
        print(f"[cognia] no pude iniciar: {exc}", file=sys.stderr)
        return 1
    for linea in buf.getvalue().splitlines():
        progreso(linea)

    codigo = 0
    respuesta = ""
    try:
        with contextlib.redirect_stdout(sys.stderr):
            # Doble cinturon: cualquier print() suelto del camino del agente
            # (los hay) va a stderr y NO ensucia el resultado.
            respuesta = _cli._run_agent_task(ai, tarea, progreso,
                                             max_steps=args.pasos)
    except KeyboardInterrupt:
        print("[cognia] interrumpido", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[cognia] la tarea fallo: {exc}", file=sys.stderr)
        respuesta, codigo = f"ERROR: {exc}", 1

    segundos = round(time.time() - t0, 1)
    texto = str(respuesta or "").strip()
    if args.json:
        json.dump({"tarea": tarea, "respuesta": texto, "segundos": segundos,
                   "cwd": os.getcwd(), "ok": codigo == 0},
                  sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(texto)
    if not args.silencioso:
        print(f"[cognia] {segundos}s", file=sys.stderr)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
