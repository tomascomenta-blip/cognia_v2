# -*- coding: utf-8 -*-
"""A/B intercalado: ¿sirve que las herramientas se ofrezcan solas?

Contrato en PREREG_TOOLS_PROACTIVAS_20260813.md (escrito ANTES de medir).

  Brazo A (control)   : catalogo CORE, como corre hoy.
  Brazo B (proactivo) : CORE + hasta 2 herramientas ofrecidas segun el
                        reasoning_content del propio turno.

INTERCALADO A,B,A,B... a proposito: si el sistema se degrada durante la corrida
(termica, otro proceso, cache), afecta a los dos brazos por igual. Correr un
brazo entero y luego el otro es el error clasico que convierte deriva en efecto.

El banco son tareas cuya solucion NATURAL es una tool fuera de CORE, pero que el
modelo puede resolver igual dando un rodeo con `ejecutar`. Si solo midieramos
tareas imposibles sin la tool, el resultado estaria cocinado.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\ab_tools_proactivas.py [reps]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPS = 3


def _lee(ws: Path, nombre: str) -> str:
    hits = list(ws.rglob(nombre))
    return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""


# (id, tarea, postcondicion, preparacion, tool_natural_fuera_de_CORE)
TAREAS = [
    ("contar",
     "cuenta cuantas lineas tiene datos.txt y escribi ese numero solo en total.txt",
     lambda ws: _lee(ws, "total.txt").strip() == "40",
     lambda ws: (ws / "datos.txt").write_text(
         "\n".join(f"linea {i}" for i in range(40)) + "\n", encoding="utf-8"),
     "contar_lineas"),
    ("json_ok",
     "comproba si config.json es JSON valido y escribi 'valido' o 'roto' en veredicto.txt",
     lambda ws: _lee(ws, "veredicto.txt").strip().lower().startswith("roto"),
     lambda ws: (ws / "config.json").write_text('{"modo": "rapido",}', encoding="utf-8"),
     "json_validar"),
    ("py_ok",
     "comproba si modulo.py tiene errores de sintaxis y escribi 'ok' o 'error' en sintaxis.txt",
     lambda ws: _lee(ws, "sintaxis.txt").strip().lower().startswith("error"),
     lambda ws: (ws / "modulo.py").write_text("def f(:\n    return 1\n", encoding="utf-8"),
     "py_validar"),
    ("copiar",
     "copia el archivo origen.txt a una copia llamada respaldo.txt sin modificar el original",
     lambda ws: (_lee(ws, "respaldo.txt").strip() == "contenido importante"
                 and _lee(ws, "origen.txt").strip() == "contenido importante"),
     lambda ws: (ws / "origen.txt").write_text("contenido importante\n", encoding="utf-8"),
     "copiar_archivo"),
    ("arbol",
     "escribi en estructura.txt los nombres de las carpetas que hay dentro de proyecto",
     lambda ws: all(x in _lee(ws, "estructura.txt") for x in ("src", "docs", "tests")),
     lambda ws: [(ws / "proyecto" / d).mkdir(parents=True, exist_ok=True)
                 for d in ("src", "docs", "tests")],
     "arbol"),
]


def main() -> int:
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else REPS

    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def corrida(tarea, verificar, preparar, proactivo: bool):
        ws = Path(tempfile.mkdtemp(prefix="ab_prov_")).resolve()
        if preparar:
            preparar(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        if proactivo:
            os.environ["COGNIA_TOOLS_PROACTIVAS"] = "1"
        else:
            os.environ.pop("COGNIA_TOOLS_PROACTIVAS", None)
        t0 = time.time()
        pasos = 0
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: None, max_steps=6)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
            os.environ.pop("COGNIA_TOOLS_PROACTIVAS", None)
        try:
            ok = bool(verificar(ws))
        except Exception:
            ok = False
        return ok, time.time() - t0, str(resp)[:120], pasos

    resultados = {"A": [], "B": []}
    print(f"A/B intercalado — {len(TAREAS)} tareas x {reps} reps x 2 brazos "
          f"= {len(TAREAS) * reps * 2} corridas\n")
    print(f"{'tarea':>10} {'rep':>4} {'A ctrl':>8} {'B proa':>8} "
          f"{'segA':>6} {'segB':>6}")
    print("-" * 48)

    for rep in range(1, reps + 1):
        for tid, tarea, verificar, preparar, _tool in TAREAS:
            # INTERCALADO de verdad: A y B de la misma tarea, seguidos.
            ok_a, seg_a, _, _ = corrida(tarea, verificar, preparar, False)
            ok_b, seg_b, _, _ = corrida(tarea, verificar, preparar, True)
            resultados["A"].append((tid, ok_a))
            resultados["B"].append((tid, ok_b))
            print(f"{tid:>10} {rep:>4} {'OK' if ok_a else 'fallo':>8} "
                  f"{'OK' if ok_b else 'fallo':>8} {seg_a:>6.0f} {seg_b:>6.0f}",
                  flush=True)

    print("\n" + "=" * 48)
    for brazo in ("A", "B"):
        ok = sum(1 for _, o in resultados[brazo] if o)
        total = len(resultados[brazo])
        etiqueta = "control" if brazo == "A" else "proactivo"
        print(f"  brazo {brazo} ({etiqueta:9}): {ok}/{total} tareas resueltas")
    a = sum(1 for _, o in resultados["A"] if o)
    b = sum(1 for _, o in resultados["B"] if o)
    print(f"\n  neto B-A: {b - a:+d} tareas")
    por_tarea = {}
    for (tid, oa), (_, ob) in zip(resultados["A"], resultados["B"]):
        d = por_tarea.setdefault(tid, [0, 0])
        d[0] += 1 if oa else 0
        d[1] += 1 if ob else 0
    print("\n  desglose por tarea (A vs B):")
    for tid, (ca, cb) in por_tarea.items():
        print(f"    {tid:>10}  {ca}/{reps}  vs  {cb}/{reps}")
    Path("ab_tools_proactivas.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
