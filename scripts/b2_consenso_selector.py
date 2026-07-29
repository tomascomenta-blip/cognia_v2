"""
b2_consenso_selector.py — ¿el contrato ciego sirve como RANKER (consenso
cruzado entre muestras) aunque sea ruido como juez absoluto?
PREREG_CONSENSO_20260728.md: leerlo ANTES; umbrales y reglas viven allí.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_consenso_selector.py
        [--reanudar] [--solo-resumen]

Fase 1 (GPU, coder-14b servido): un contrato clasico por MUESTRA del BoN
(idea + inventario del DOM propio, 2 intentos). Fase 2 (solo Playwright):
cada contrato juzga a las muestras AJENAS de su ensayo. Selector-consenso =
argmax (votos ajenos que aprueban, fraccion media de checks, indice menor).
El resultado del elegido es el `estricto` YA guardado del BoN (congelado).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
BON = (RAIZ / "cognia" / "program_creator" / "generated_programs"
       / "b2_bon_heldout")
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_consenso_selector")


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia import backend_activo

    reanudar = "--reanudar" in argv
    solo_resumen = "--solo-resumen" in argv
    if solo_resumen:
        reanudar = True

    ideas = {t["id"]: t["idea"]
             for t in json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    bon = json.loads((BON / "resultados.json").read_text(encoding="utf-8"))
    muestras = [m for m in bon["muestras"]
                if (BON / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
                    / "index.html").is_file()]
    ensayos: dict = {}
    for m in muestras:
        ensayos.setdefault((m["tarea"], m["rep"]), []).append(m)

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file()
                 else {"contratos": [], "votos": []})

    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    # La config NO se pisa al reanudar/resumir: registra la procedencia de
    # los datos, no el estado del ultimo proceso (revision, hallazgo #2).
    if "config" not in res:
        res["config"] = {
            "commit": commit, "backend": backend_activo.estado(),
            "fuente_bon": bon["config"],
            "nota": "contratos coder-14b modo clasico; selector solo ve "
                    "votos ajenos POR CHECKS DEL CONTRATO (los universales "
                    "comparten instrumento con el juez que definio estricto "
                    "y no votan — revision, hallazgo #1)"}

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    # ── Fase 1: un contrato por muestra (GPU liviana) ────────────────────
    hechos = {(c["tarea"], c["rep"], c["s"]) for c in res["contratos"]}
    if not solo_resumen:
        print(f"FASE 1 — contratos por muestra ({len(muestras)} muestras, "
              f"hechos {len(hechos)})", flush=True)
        for clave, ms in sorted(ensayos.items()):
            for m in sorted(ms, key=lambda m: m["s"]):
                k = (m["tarea"], m["rep"], m["s"])
                if k in hechos:
                    continue
                html = (BON / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
                        / "index.html")
                t0 = time.time()
                c = None
                for _ in (1, 2):
                    c = juez_ejecutable.generar_contrato(
                        ideas[m["tarea"]], html, modo="clasico")
                    if c:
                        break
                fila = {"tarea": m["tarea"], "rep": m["rep"], "s": m["s"],
                        "generado": c is not None,
                        "pasos": len(c["pasos"]) if c else 0,
                        "segundos": round(time.time() - t0, 1),
                        "backend": backend_activo.ultimo()}
                if c:
                    (SALIDA / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
                     "__contrato.json").write_text(
                        json.dumps(c, indent=2, ensure_ascii=False),
                        encoding="utf-8")
                res["contratos"].append(fila)
                _guardar()
                print(f"  {m['tarea']:<14} r{m['rep']} s{m['s']} "
                      f"{'OK' if c else 'None'} ({fila['segundos']}s)",
                      flush=True)

    # ── Fase 2: votos cruzados (solo Playwright) ─────────────────────────
    def _contrato_de(tarea, rep, s):
        f = SALIDA / f"{tarea}__r{rep}__s{s}__contrato.json"
        return (json.loads(f.read_text(encoding="utf-8"))
                if f.is_file() else None)

    votados = {(v["tarea"], v["rep"], v["s_contrato"], v["s_muestra"])
               for v in res["votos"]}
    if not solo_resumen:
        print(f"\nFASE 2 — votos cruzados (hechos {len(votados)})",
              flush=True)
        for (tarea, rep), ms in sorted(ensayos.items()):
            enes = sorted(m["s"] for m in ms)
            for s_c in enes:
                c = _contrato_de(tarea, rep, s_c)
                if not c:
                    continue
                for s_x in enes:
                    if s_x == s_c:
                        continue        # nadie se auto-examina
                    k = (tarea, rep, s_c, s_x)
                    if k in votados:
                        continue
                    html = BON / f"{tarea}__r{rep}__s{s_x}" / "index.html"
                    fila = {"tarea": tarea, "rep": rep,
                            "s_contrato": s_c, "s_muestra": s_x}
                    try:
                        v = juez_ejecutable.juzgar_web(html, c)
                        # Solo los checks DEL CONTRATO votan: los universales
                        # (carga/contenido/...) son la misma bateria que
                        # fabrico `estricto` — compartir instrumento haria
                        # ininterpretable el veredicto (revision, #1).
                        univ = ("carga", "sin_errores_js", "contenido",
                                "interactivo")
                        del_c = [ch for ch in v.checks
                                 if ch.nombre not in univ]
                        fila.update(aprueba=v.aprobado,
                                    checks_ok=sum(1 for ch in v.checks
                                                  if ch.ok),
                                    checks=len(v.checks),
                                    c_ok=sum(1 for ch in del_c if ch.ok),
                                    c_n=len(del_c),
                                    aprueba_contrato=bool(del_c) and all(
                                        ch.ok for ch in del_c))
                    except Exception as exc:
                        fila.update(crasheo=f"{exc}"[:80])
                    res["votos"].append(fila)
                    _guardar()
            print(f"  {tarea} r{rep} votado", flush=True)

    # ── Resumen apareado (metricas del prereg) ───────────────────────────
    estricto = {(m["tarea"], m["rep"], m["s"]): bool(m["estricto"])
                for m in muestras}
    neto = 0
    validos, sin_voto, gana, pierde = [], [], [], []
    coincide_heldout = 0
    heldout_sel = {}    # replica del selector held-out del BoN, para comparar
    for (tarea, rep), ms in sorted(ensayos.items()):
        enes = sorted(m["s"] for m in ms)
        votos_x = {}
        for s_x in enes:
            vs = [v for v in res["votos"]
                  if (v["tarea"], v["rep"], v["s_muestra"]) == (tarea, rep,
                                                                s_x)
                  and v["s_contrato"] != s_x and "crasheo" not in v]
            votos_x[s_x] = vs
        if any(len(vs) < 2 for vs in votos_x.values()):
            sin_voto.append((tarea, rep))
            continue
        if (tarea, rep, 1) not in estricto:
            sin_voto.append((tarea, rep))     # sin control s1 no hay par
            continue

        def puntaje(s_x):
            vs = votos_x[s_x]
            frac = (sum(v["c_ok"] / v["c_n"] for v in vs
                        if v.get("c_n")) / len(vs))
            return (sum(1 for v in vs if v.get("aprueba_contrato")), frac,
                    -s_x)
        elegido = max(enes, key=puntaje)
        control = estricto[(tarea, rep, 1)]
        exito = estricto[(tarea, rep, elegido)]
        neto += (exito and not control) - (control and not exito)
        validos.append((tarea, rep, elegido, exito, control))
        if exito and not control:
            gana.append(f"{tarea}:r{rep}")
        if control and not exito:
            pierde.append(f"{tarea}:r{rep}")
        # el selector held-out elegia por (aprobado_heldout, checks held-out)
        ms_por_s = {m["s"]: m for m in ms}
        h = sorted(enes, key=lambda s: (
            not ms_por_s[s].get("aprobado_heldout"),
            -ms_por_s[s].get("heldout_checks_ok", 0), s))[0]
        coincide_heldout += (h == elegido)

    n_v = len(validos)
    ctrl_ok = sum(1 for *_, c in validos if c)
    sel_ok = sum(1 for _, _, _, ex, _ in validos if ex)
    votos_validos = [v for v in res["votos"] if "crasheo" not in v]
    crasheados = len(res["votos"]) - len(votos_validos)
    aprueban = sum(1 for v in votos_validos if v.get("aprueba_contrato"))
    con_contrato = {(c["tarea"], c["rep"], c["s"]) for c in res["contratos"]
                    if c["generado"]}
    esperados = sum(
        (len([m for m in ms]) - 1)
        for (tarea, rep), ms in ensayos.items()
        for s in sorted(m["s"] for m in ms) if (tarea, rep, s) in con_contrato)
    parcial = len(votos_validos) < esperados
    print(f"\n{'=' * 70}")
    print(f"  CONSENSO CRUZADO ({n_v} ensayos con voto suficiente, "
          f"{len(sin_voto)} sin voto)")
    print(f"  control s1 estricto     : {ctrl_ok}/{n_v}")
    print(f"  selector-consenso       : {sel_ok}/{n_v}   neto B' = {neto:+d}"
          f"  (prereg: >=+5 MARCO VIVO, +3..+4 moderado, [-2,+2] KILL, "
          f"<=-3 elige mal)")
    print(f"  gana: {', '.join(gana) or '—'}")
    print(f"  pierde: {', '.join(pierde) or '—'}")
    print(f"  coincide con selector held-out: {coincide_heldout}/{n_v}")
    print(f"  votos (por contrato) que aprueban: {aprueban}/"
          f"{len(votos_validos)} (¿condenan todo?); crasheados "
          f"{crasheados}; hechos {len(votos_validos)}/{esperados}"
          f"{' PARCIAL' if parcial else ''}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "ensayos": n_v, "sin_voto": [f"{t}:r{r}" for t, r in sin_voto],
        "control": f"{ctrl_ok}/{n_v}", "consenso": f"{sel_ok}/{n_v}",
        "neto_bprima": neto, "gana": gana, "pierde": pierde,
        "coincide_heldout": f"{coincide_heldout}/{n_v}",
        "votos_aprueban_contrato": f"{aprueban}/{len(votos_validos)}",
        "votos_crasheados": crasheados,
        "votos_hechos": f"{len(votos_validos)}/{esperados}",
        "parcial": parcial}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
