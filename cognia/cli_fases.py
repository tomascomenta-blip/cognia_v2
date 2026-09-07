# -*- coding: utf-8 -*-
"""
cognia/cli_fases.py — `cognia fases "<encargo>"` y el puente que usa `/fases`.

La obra por fases (cognia/fases) necesita un EJECUTOR del agente: aqui se
arma sobre cli._run_agent_task (el MISMO camino que /hacer, con scratchpad,
revision profunda y permisos), con el rol como pista y las tools acotadas
por fase (el red team y el planificador no escriben ficheros).

Salida (como cognia hacer): stdout = el informe final; stderr = progreso.
Codigo 0 si la obra quedo LISTA, 1 si no, 2 uso incorrecto, 130 Ctrl-C.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import time


def armar_ejecutor(ai, progreso, pasos_por_iteracion: int = None):
    """ejecutor(prompt, rol, allowed_tools) -> texto, sobre cli._run_agent_task."""
    from cognia import cli as _cli

    def ejecutor(prompt: str, rol: str, allowed_tools):
        hint = {"planificador": "Fase de planificacion: no escribas ficheros del producto.",
                "redteam": "Sos el red team: NO modifiques ficheros; registra issues con fases_issue."}.get(rol, "")
        kw = {"allowed_tools": allowed_tools} if allowed_tools else {}
        if pasos_por_iteracion:
            kw["max_steps"] = pasos_por_iteracion
        return _cli._run_agent_task(ai, prompt, progreso, hint=hint, proactividad=False, **kw)
    return ejecutor


def correr_obra(ai, workspace: str, encargo: str, progreso, iteraciones: int = None,
                minutos: float = None, fases_ids: list = None, pasos: int = None) -> dict:
    """Arranca o reanuda la obra en `workspace`. Devuelve el informe final."""
    from cognia.fases.pipeline import Obra
    try:
        from cognia import cli as _cli
        visibles = _cli._filtro_tools_agente(None)
    except Exception:
        visibles = None
    obra = Obra(workspace, encargo=encargo, ejecutor=armar_ejecutor(ai, progreso, pasos), imprimir=progreso,
                iteraciones=iteraciones, minutos=minutos, fases_ids=fases_ids,
                tools_visibles=set(visibles) if visibles else None)
    return obra.correr()


def main(argv: list = None) -> int:
    argv = list(sys.argv[2:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="cognia fases",
                                 description="Construye un producto por FASES con puertas de salida, juez y revert (sin REPL).")
    ap.add_argument("encargo", nargs="*", help="que construir (o vacio con --reanudar)")
    ap.add_argument("--reanudar", action="store_true", help="continuar la obra de este directorio")
    ap.add_argument("--iteraciones", type=int, default=None, help="tope de iteraciones por fase")
    ap.add_argument("--minutos", type=float, default=None, help="presupuesto de pared; la obra queda reanudable")
    ap.add_argument("--fases", default="", help="solo estas fases, separadas por coma (planificar,prototipo,...)")
    ap.add_argument("--pasos", type=int, default=None, help="tope de pasos del agente por iteracion")
    ap.add_argument("--cwd", default=None, help="workspace del producto (por defecto, este directorio)")
    ap.add_argument("--silencioso", "-s", action="store_true")
    args = ap.parse_args(argv)
    encargo = " ".join(args.encargo).strip()
    if not encargo and not args.reanudar:
        print('Uso: cognia fases "<encargo>"  (o --reanudar)', file=sys.stderr)
        return 2
    ws = os.path.abspath(args.cwd or os.getcwd())
    if not os.path.isdir(ws):
        print("[fases] no existe %s" % ws, file=sys.stderr)
        return 2

    def progreso(linea) -> None:
        if not args.silencioso:
            print(str(linea), file=sys.stderr, flush=True)

    t0 = time.time()
    try:
        from cognia.first_run import apply_config
        apply_config()
        from cognia.cognia import Cognia
        from cognia import cli as _cli
        _cli._aplicar_config_memoria_larga()
    except Exception as exc:
        print("[fases] no pude cargar el agente: %s" % exc, file=sys.stderr)
        return 1
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai = Cognia()
    for l in buf.getvalue().splitlines():
        progreso(l)
    fases_ids = [f.strip() for f in args.fases.split(",") if f.strip()] or None
    cwd_previo = os.getcwd()
    try:
        os.chdir(ws)
        with contextlib.redirect_stdout(sys.stderr):
            inf = correr_obra(ai, ws, encargo, progreso, iteraciones=args.iteraciones, minutos=args.minutos,
                              fases_ids=fases_ids, pasos=args.pasos)
    except KeyboardInterrupt:
        print("[fases] interrumpido (la obra queda reanudable con --reanudar)", file=sys.stderr)
        return 130
    finally:
        os.chdir(cwd_previo)
    print(inf["texto"])
    progreso("[fases] %.0fs" % (time.time() - t0))
    return 0 if inf.get("listo") else 1


if __name__ == "__main__":
    sys.exit(main())
