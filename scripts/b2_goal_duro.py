"""
b2_goal_duro.py — EL NÚMERO DEL GOAL. PREREG_GOAL_DURO_20260730.md.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_goal_duro.py
        [--rejuzgar]

Lee las muestras del banco DURO (b2_bon_heldout_duro), aplica el juez
estricto (contrato original ∧ held-out a mano) y computa las tres métricas
pre-registradas por tarea:

  CONTROL  estricto de s=1            (lo que el sistema entrega sin BoN)
  MODO     estricto de la ELEGIDA     (el número del goal)
  TECHO    ¿alguna de las K es estricta?  (pass@K)

El selector es el held-out SOLO (no mira el contrato original): aprobado >
checks_ok > s menor — el mismo criterio confirmado en el gate.

Por cada tarea fallida clasifica el fallo, que es la lectura que manda:
  TECHO     pass@K = 0  -> el muestreo no la compra (KILL de META)
  SELECCION pass@K = 1 pero la elegida falla -> el verificador no distingue

--rejuzgar: re-juzga las muestras con el held-out ACTUAL (necesario si la
fase 1 corrió sin held-out o si los contratos se corrigieron después).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_duras.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout_duras.json"
CORPUS = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_heldout_duro")


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

    rejuzgar = "--rejuzgar" in argv
    global CORPUS
    if "--corpus" in argv:      # la replica vive en su propio directorio
        CORPUS = CORPUS.with_name(argv[argv.index("--corpus") + 1])
    tareas = {t["id"]: t for t in
              json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    res = json.loads((CORPUS / "resultados.json").read_text(encoding="utf-8"))

    muestras = []
    for m in res["muestras"]:
        d = CORPUS / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
        p = d / "index.html"
        fila = dict(m)
        if rejuzgar and p.is_file():
            def _dos(ruta, o, h):
                return (juez_ejecutable.juzgar_web(ruta, o),
                        juez_ejecutable.juzgar_web(ruta, h))
            try:
                v, vh = con_presupuesto(300, _dos, p,
                                        tareas[m["tarea"]]["contrato"],
                                        heldout[m["tarea"]])
                fila.update(
                    aprobado=bool(v.aprobado),
                    checks_ok=sum(1 for c in v.checks if c.ok),
                    aprobado_heldout=bool(vh.aprobado),
                    heldout_checks_ok=sum(1 for c in vh.checks if c.ok),
                    motivo=(v.motivo or "")[:90],
                    heldout_motivo=(vh.motivo or "")[:90])
            except PresupuestoAgotado:
                fila.update(aprobado=False, aprobado_heldout=False,
                            motivo="juez colgado (JS bloqueante)")
            except Exception as exc:
                fila.update(infra_juez=f"{exc}"[:80])
        fila["estricto"] = bool(fila.get("aprobado")
                                and fila.get("aprobado_heldout"))
        muestras.append(fila)
        if rejuzgar:
            print(f"  {m['tarea']:<18} s{m['s']} "
                  f"orig={'OK' if fila.get('aprobado') else 'no':<3} "
                  f"held={'OK' if fila.get('aprobado_heldout') else 'no':<3} "
                  f"estricto={'OK' if fila['estricto'] else 'no'}", flush=True)

    por_tarea: dict = {}
    for m in muestras:
        por_tarea.setdefault(m["tarea"], []).append(m)

    filas, n_ctrl, n_modo, n_techo = [], 0, 0, 0
    for tarea in [t["id"] for t in
                  json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]]:
        ms = sorted(por_tarea.get(tarea, []), key=lambda m: int(m["s"]))
        if not ms:
            filas.append({"tarea": tarea, "estado": "SIN MUESTRAS"})
            continue
        con_html = [m for m in ms if m.get("checks_ok") is not None
                    or m.get("aprobado") is not None]
        # selector: SOLO el held-out (aprobado > checks_ok > s menor)
        elegible = [m for m in ms if m.get("aprobado_heldout") is not None]
        elegida = (sorted(elegible,
                          key=lambda m: (not m.get("aprobado_heldout"),
                                         -(m.get("heldout_checks_ok") or 0),
                                         int(m["s"])))[0]
                   if elegible else ms[0])
        control = next((m for m in ms if int(m["s"]) == 1), ms[0])
        techo = any(m["estricto"] for m in ms)
        n_ctrl += bool(control["estricto"])
        n_modo += bool(elegida["estricto"])
        n_techo += techo
        if elegida["estricto"]:
            clase = "OK"
        elif techo:
            clase = "SELECCION (habia buena y no la eligio)"
        else:
            clase = "TECHO (ninguna de las K sirve)"
        filas.append({
            "tarea": tarea, "k": len(ms),
            "control": bool(control["estricto"]),
            "elegida_s": int(elegida["s"]),
            "modo": bool(elegida["estricto"]), "techo": techo,
            "clase": clase,
            "estrictos": [int(m["s"]) for m in ms if m["estricto"]],
            "motivo_elegida": (elegida.get("motivo") or "")[:80]})

    n = len([f for f in filas if f.get("k")])
    print(f"\n{'=' * 74}")
    print(f"  EL GOAL — banco DURO, {n} tareas, K={filas[0].get('k','?')} "
          f"[{CORPUS.name}]")
    print(f"  {'tarea':<18}{'ctrl':>6}{'MODO':>6}{'techo':>7}  eleg  "
          f"estrictos  clase")
    for f in filas:
        if not f.get("k"):
            print(f"  {f['tarea']:<18}  {f['estado']}")
            continue
        print(f"  {f['tarea']:<18}{'OK' if f['control'] else '--':>6}"
              f"{'OK' if f['modo'] else '--':>6}"
              f"{'OK' if f['techo'] else '--':>7}"
              f"   s{f['elegida_s']}  {str(f['estrictos']):<10} {f['clase']}")
    print(f"\n  CONTROL (s1):        {n_ctrl}/{n}")
    print(f"  MODO (el goal):      {n_modo}/{n}   "
          f"(prereg: 8/8 GOAL ALCANZADO; 6-7 cerca; <=5 no)")
    print(f"  TECHO pass@K:        {n_techo}/{n}")
    print(f"  perdida del selector: {n_techo - n_modo}")
    fallos_techo = [f["tarea"] for f in filas if f.get("k")
                    and f["clase"].startswith("TECHO")]
    fallos_sel = [f["tarea"] for f in filas if f.get("k")
                  and f["clase"].startswith("SELECCION")]
    print(f"  fallos por TECHO:     {fallos_techo or '—'}")
    print(f"  fallos por SELECCION: {fallos_sel or '—'}")
    print(f"{'=' * 74}")
    salida = CORPUS / "goal.json"
    salida.write_text(json.dumps(
        {"tareas": n, "control": n_ctrl, "modo": n_modo, "techo": n_techo,
         "perdida_selector": n_techo - n_modo,
         "fallos_techo": fallos_techo, "fallos_seleccion": fallos_sel,
         "filas": filas}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
