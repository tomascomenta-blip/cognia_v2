# -*- coding: utf-8 -*-
"""Mide la FIDELIDAD ground-truth de cada oráculo del superorganismo.

Fidelidad = % de spec_asserts del cartógrafo que PASAN sobre una solución
CORRECTA (validada contra tests ocultos). Un assert que falla en la solución
correcta es FALSO (anti-solución); pasar todos = oráculo fiel.

Referencia correcta por tarea:
- ganadoras (NEWX3, ALG3, SPEC3): su propio 'code' del results (pasó ocultos).
- perdedoras: implementación de referencia en scratchpad/refimpl/<TID>.py
  (del workflow), re-validada aquí contra los ocultos antes de usarla.

(2026-07-16) Flujo bajo guard __main__ y REPO derivado de __file__: el módulo
viaja en el wheel y antes hardcodeaba el path absoluto del repo de la máquina
de desarrollo + ejecutaba el análisis completo al importarse (FileNotFoundError
garantizado en cualquier instalación ajena).
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REFDIR = Path(__file__).resolve().parent / "refimpl"

GANADORAS = {"NEWX3", "ALG3", "SPEC3"}


def main():
    from cognia_v3.eval.benchmark_code import run_task_tests
    from cognia.agent.superorganismo import _run_asserts

    res = json.load(open(REPO / "cognia_v3/eval/results_superorganismo_v2.json",
                         encoding="utf-8"))
    tareas = {json.loads(l)["id"]: json.loads(l)
              for l in open(REPO / "cognia_v3/eval/tasks_hard_v2.jsonl",
                            encoding="utf-8") if l.strip()}

    filas = []
    for tid, td in res["tareas"].items():
        carto = (td.get("carto") or {})
        asserts = carto.get("spec_asserts") or []
        if not asserts:
            continue
        t = tareas[tid]
        entry = t["entry_point"]
        # obtener una solución CORRECTA
        ref, origen = None, None
        if tid in GANADORAS and td.get("final"):
            ref, origen = td.get("code", ""), "propia (pasó ocultos)"
        else:
            f = REFDIR / f"{tid}.py"
            if f.is_file():
                cand = f.read_text(encoding="utf-8")
                ok, _, _ = run_task_tests(cand, t["tests"], entry)
                if ok:
                    ref, origen = cand, "refimpl validada"
                else:
                    origen = "refimpl NO pasa ocultos (descartada)"
        if not ref:
            filas.append((tid, len(asserts), None, None, origen or "sin ref"))
            continue
        n_pass, fallos = _run_asserts(ref, asserts)
        fidelidad = round(100 * n_pass / len(asserts))
        filas.append((tid, len(asserts), n_pass, fidelidad, origen))

    print(f"{'TAREA':7} {'ASSERTS':7} {'PASAN':6} {'FIDELIDAD':9} FUENTE")
    for tid, na, npass, fid, origen in filas:
        pas = "?" if npass is None else str(npass)
        fids = "s/d" if fid is None else f"{fid}%"
        win = " <-- PASS oculto" if tid in GANADORAS else ""
        print(f"{tid:7} {na:<7} {pas:6} {fids:9} {origen}{win}")

    # resumen: correlación fidelidad vs PASS
    med = [(tid, fid, tid in GANADORAS) for tid, _, _, fid, _ in filas
           if fid is not None]
    if med:
        gan_fid = [f for _, f, g in med if g]
        per_fid = [f for _, f, g in med if not g]
        print()
        if gan_fid:
            print(f"Fidelidad media GANADORAS: {round(sum(gan_fid)/len(gan_fid))}% "
                  f"(n={len(gan_fid)})")
        if per_fid:
            print(f"Fidelidad media PERDEDORAS medidas: "
                  f"{round(sum(per_fid)/len(per_fid))}% (n={len(per_fid)})")
        open(Path(__file__).resolve().parent / "fidelidad.json", "w",
             encoding="utf-8").write(json.dumps(
                 [{"tarea": tid, "asserts": na, "pasan": np, "fidelidad": fid,
                   "fuente": org, "gano": tid in GANADORAS}
                  for tid, na, np, fid, org in filas], indent=1, ensure_ascii=False))
        print("\n-> fidelidad.json escrito")


if __name__ == "__main__":
    main()
