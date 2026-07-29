"""
b2_bon_gate.py — A/B de CONFIRMACIÓN del modo BoN cableado (bon.py).
PREREG_BON_GATE_20260728.md: leerlo ANTES; umbrales y reglas viven allí.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_bon_gate.py
        [--replicas 6] [--muestras 4] [--reanudar] [--acepta-commit]
        [--solo-resumen] [--sufijo x]

Cada ENSAYO llama a cognia.program_creator.bon.construir_bon (el módulo de
PRODUCCIÓN) con el held-out como selector, guarda las K muestras, las juzga
con el contrato ORIGINAL y lee el veredicto held-out del meta del modo.
Control = muestra s=1 del propio ensayo; resultado del modo = estricto de la
ELEGIDA. Guardado incremental por ensayo, reanudable.
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
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_gate")


def _es_infra(e: dict) -> bool:
    # Nivel ENSAYO: EXCEPCION del harness o juez original crasheado.
    if "EXCEPCION" in e.get("como", ""):
        return True
    return bool(e.get("juez_crasheo"))


def _infra_muestra(m: dict) -> bool:
    # Nivel MUESTRA (mismas reglas que b2_bon_heldout): excepcion de la
    # replica, juez held-out caido, o backend degradado/≠8080. Nota de la
    # 2ª enmienda: sin fallback, el fallo contenido-vacio termina con
    # registro degradado (el ultimo intento es el Ollama neutralizado)
    # aunque el server este sano — cuenta como infra de MUESTRA (pool mas
    # chico), igual que habria contado en el experimento.
    if "error" in m or m.get("sel_crasheo"):
        return True
    b = m.get("backend") or {}
    if not b or b.get("via") == "arbitro_visual":
        return False
    return bool(b.get("degradado") or b.get("puerto") not in (8080, None))


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    replicas = (int(argv[argv.index("--replicas") + 1])
                if "--replicas" in argv else 6)
    muestras_k = (int(argv[argv.index("--muestras") + 1])
                  if "--muestras" in argv else 4)
    reanudar = "--reanudar" in argv
    solo_resumen = "--solo-resumen" in argv
    if solo_resumen:
        reanudar = True
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])

    # Flags residuales del shell cambiarían el sistema medido sin dejar rastro.
    for flag in ("COGNIA_IDEA_PELADA", "COGNIA_PROMPT_FIX2",
                 "COGNIA_MAX_RONDAS", "COGNIA_BON_K", "COGNIA_BON_SELECTOR"):
        os.environ.pop(flag, None)
    from cognia.program_creator import diseno_a_codigo, bon
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"
    from cognia.colonia import feromona
    feromona.RUTA_RASTRO = SALIDA / "feromona.json"
    # Degradación RUIDOSA, no celda envenenada por el 3B de Ollama (patrón
    # b2_bon_heldout: módulo Y env, llm_local relee el env en cada llamada).
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-BON-GATE"
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-BON-GATE"
    # Volcado PASIVO del prompt que el lazo arma (para la sonda futura del
    # ladron de ~17 pts: dos sondas del prompt directo no transfirieron).
    # No altera los prompts; solo los registra.
    os.environ["COGNIA_DUMP_PROMPTS"] = str(SALIDA / "prompts")
    from cognia import backend_activo

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    if "--tareas" in argv:      # para humos; la corrida del prereg va sin el
        pedidas = argv[argv.index("--tareas") + 1].split(",")
        tareas = [t for t in tareas if t["id"] in pedidas]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    faltan = [t["id"] for t in tareas if t["id"] not in heldout]
    if faltan:
        sys.exit(f"sin held-out para {faltan}: no hay selector ni estricto")

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"ensayos": []})
    hechos = {(e["tarea"], e["rep"]) for e in res["ensayos"]}

    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    previa = res.get("config")
    if reanudar and previa:
        for campo, ahora in (("replicas", replicas),
                             ("muestras_por_ensayo", muestras_k)):
            if previa.get(campo) != ahora:
                sys.exit(f"--reanudar con {campo} distinto: usa --sufijo")
        commits_previos = previa.get("commits", [previa.get("commit")])
        if commit not in commits_previos:
            if "--acepta-commit" not in argv:
                sys.exit(f"--reanudar con commit distinto "
                         f"({commits_previos} -> {commit}): --acepta-commit "
                         f"si no tocan el sistema medido; si lo tocan, "
                         f"--sufijo nuevo")
            print(f"  REANUDACION ACEPTADA: {commits_previos} + {commit}",
                  flush=True)
            commits_previos = commits_previos + [commit]
        res_commits = commits_previos
    else:
        res_commits = [commit]
    res["config"] = {
        "replicas": replicas, "muestras_por_ensayo": muestras_k,
        "commit": commit, "commits": res_commits,
        "max_rondas_defecto": diseno_a_codigo.MAX_RONDAS_DEFECTO,
        "backend": backend_activo.estado(),
        "ollama_fallback_neutralizado": _generator.OLLAMA_MODEL,
        "nota": "modo de PRODUCCION bon.construir_bon; selector=held-out; "
                "estricto=original∧held-out; control=s1 del ensayo; sin "
                "fallback create_program ni semillas (prereg BON_GATE)"}

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    print(f"BoN GATE — {len(tareas)} tareas x {replicas} réplicas x "
          f"K={muestras_k} (modo de producción)\n"
          f"reanudar={reanudar} (hechos: {len(hechos)})\n", flush=True)

    for rep in (range(1, replicas + 1) if not solo_resumen else []):
        rot = rep % len(tareas)
        for t in tareas[rot:] + tareas[:rot]:
            if (t["id"], rep) in hechos:
                continue
            d = SALIDA / f"{t['id']}__r{rep}"
            d.mkdir(parents=True, exist_ok=True)
            print(f"  r{rep} {t['id']:<14} ...", flush=True)
            t0 = time.time()
            backend_activo.resetear_cache()
            fila = {"tarea": t["id"], "rep": rep}
            try:
                # Presupuesto de PARED duro por ensayo (K celdas): el goteo
                # lento de tokens no dispara el timeout por chunk y una celda
                # colgo >45 min en b2_ab_gap. PresupuestoAgotado cae al
                # except -> como=EXCEPCION -> infra (pre-declarado).
                from cognia.presupuesto_pared import (con_presupuesto,
                                                      presupuesto_celda)
                r = con_presupuesto(
                    muestras_k * presupuesto_celda(), bon.construir_bon,
                    t["idea"], k=muestras_k,
                    contrato_selector=heldout[t["id"]],
                    guardar_muestras=d, llm=None,
                    usar_mockup_imagen=False, verbose=False)
                fila.update(bon=r.bon, como="bon.construir_bon",
                            elegida_s=r.bon["elegida_s"])
            except Exception as exc:
                fila.update(como=f"EXCEPCION {exc}"[:90], bon=None,
                            elegida_s=None)
            fila["backend"] = backend_activo.ultimo()
            # Juzgado ORIGINAL de cada muestra guardada (el held-out ya está
            # en el meta del modo, mismo juez y commit: no se duplica).
            juicios = {}
            for s in range(1, muestras_k + 1):
                h = d / f"s{s}" / "index.html"
                if not h.is_file():
                    juicios[str(s)] = {"aprobado": False, "motivo": "sin HTML"}
                    continue
                try:
                    v = juez_ejecutable.juzgar_web(h, t["contrato"])
                    juicios[str(s)] = {
                        "aprobado": bool(v.aprobado),
                        "checks_ok": sum(1 for c in v.checks if c.ok),
                        "checks": len(v.checks), "motivo": v.motivo[:80]}
                except Exception as exc:
                    juicios[str(s)] = {"aprobado": False, "juez_crasheo": True,
                                       "motivo": f"{exc}"[:80]}
                    fila["juez_crasheo"] = True
            fila["orig"] = juicios
            fila["segundos"] = round(time.time() - t0, 1)
            res["ensayos"].append(fila)
            _guardar()
            print(f"       -> elegida s{fila.get('elegida_s')} "
                  f"({fila['segundos']}s)", flush=True)

    # ── resumen apareado (métricas del prereg) ───────────────────────────────
    def _sel_de(fila, s):
        for m in (fila.get("bon") or {}).get("muestras", []):
            if m.get("s") == s:
                return m
        return {}

    def _estricto(fila, s):
        o = fila["orig"].get(str(s), {})
        m = _sel_de(fila, s)
        return bool(o.get("aprobado")) and bool(m.get("aprobado_sel"))

    validos, excl_infra, incompletos = [], [], []
    for fila in res["ensayos"]:
        k = fila.get("bon", {}).get("k") if fila.get("bon") else None
        # Infra POR MUESTRA (revision pre-lanzamiento h.1-2 + 2ª enmienda,
        # humo): s1 o la ELEGIDA infra -> ensayo fuera del apareado; una
        # muestra infra en s2-s4 solo achica el pool del techo.
        s1m = _sel_de(fila, 1)
        eleg = fila.get("elegida_s")
        elegm = _sel_de(fila, eleg) if eleg else {}
        if _es_infra(fila) or _infra_muestra(s1m) or (eleg and
                                                      _infra_muestra(elegm)):
            excl_infra.append((fila["tarea"], fila["rep"]))
            continue
        if k != muestras_k or len(fila.get("orig", {})) != muestras_k:
            incompletos.append((fila["tarea"], fila["rep"]))
            continue
        validos.append(fila)

    neto_b = neto_a = 0
    gana_b, pierde_b, gana_a = [], [], []
    sin_html = crashes_replica = 0
    fp_orig: dict = {}
    for fila in validos:
        control = _estricto(fila, 1)
        elegida = fila.get("elegida_s")
        modo = _estricto(fila, elegida) if elegida else False
        # El techo cuenta solo muestras NO infra (pool del heldout).
        techo = any(_estricto(fila, s) for s in range(1, muestras_k + 1)
                    if not _infra_muestra(_sel_de(fila, s)))
        neto_b += (modo and not control) - (control and not modo)
        neto_a += (techo and not control) - (control and not techo)
        clave = f"{fila['tarea']}:r{fila['rep']}"
        if modo and not control:
            gana_b.append(clave)
        if control and not modo:
            pierde_b.append(clave)
        if techo and not control:
            gana_a.append(clave)
        for s in range(1, muestras_k + 1):
            o = fila["orig"].get(str(s), {})
            m = _sel_de(fila, s)
            # la muestra infra (crash, backend degradado, sel caido) no es
            # "no devolvio HTML" legitimo (revision h.4 + 2ª enmienda)
            if _infra_muestra(m):
                crashes_replica += 1
            elif o.get("motivo") == "sin HTML":
                sin_html += 1
            if o.get("aprobado") and m.get("aprobado_sel") is False:
                fp_orig[fila["tarea"]] = fp_orig.get(fila["tarea"], 0) + 1

    n_v = len(validos)
    ctrl_ok = sum(1 for f in validos if _estricto(f, 1))
    modo_ok = sum(1 for f in validos
                  if f.get("elegida_s") and _estricto(f, f["elegida_s"]))
    techo_ok = sum(1 for f in validos
                   if any(_estricto(f, s) for s in range(1, muestras_k + 1)))
    print(f"\n{'=' * 70}")
    print(f"  BoN GATE ({n_v} ensayos válidos, {len(excl_infra)} infra, "
          f"{len(incompletos)} incompletos)")
    print(f"  control (s=1 estricto) : {ctrl_ok}/{n_v}")
    print(f"  modo BoN (elegida)     : {modo_ok}/{n_v}   neto B = {neto_b:+d}"
          f"  (prereg: >=+4 CONFIRMADO, +2..+3 GRIS, <=+1 NO confirma)")
    print(f"  techo pass@{muestras_k}          : {techo_ok}/{n_v}   neto A = "
          f"{neto_a:+d}   pérdida C = {neto_a - neto_b}")
    fallos_control = n_v - ctrl_ok
    # Lectura condicional al headroom (revision, h. 3): neto B <= fallos del
    # control por construccion; con deriva a control alto, +4 seria
    # inalcanzable con cableado perfecto.
    if fallos_control < 5:
        confirmado = neto_b >= fallos_control - 1 and not pierde_b
        print(f"  headroom bajo ({fallos_control} fallos de control): "
              f"CONFIRMADO = B >= {fallos_control - 1} y pierde=0 -> "
              f"{'SI' if confirmado else 'no'}")
    print(f"  gana: {', '.join(gana_b) or '—'}   "
          f"pierde: {', '.join(pierde_b) or '—'}")
    print(f"  muestras sin HTML: {sin_html}/{n_v * muestras_k}   "
          f"muestras infra: {crashes_replica}   "
          f"FP original: {fp_orig or '—'}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "ensayos_validos": n_v,
        "excluidos_infra": [f"{t}:r{r}" for t, r in excl_infra],
        "incompletos": [f"{t}:r{r}" for t, r in incompletos],
        "control": f"{ctrl_ok}/{n_v}", "modo": f"{modo_ok}/{n_v}",
        "neto_b": neto_b, "fallos_control": fallos_control,
        "techo": f"{techo_ok}/{n_v}", "neto_a": neto_a,
        "perdida_c": neto_a - neto_b, "gana": gana_b, "pierde": pierde_b,
        "muestras_sin_html": sin_html, "muestras_infra": crashes_replica,
        "fp_contrato_original": fp_orig}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
