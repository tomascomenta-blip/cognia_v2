"""
b2_bon_heldout.py — ¿el muestreo de réplicas independientes + un verificador
CON señal real alcanza el nivel 8/8 del banco brutal?
PREREG_BON_HELDOUT_20260728.md: leerlo ANTES; umbrales y reglas de infra
viven allí, no aquí.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_bon_heldout.py
        [--replicas 6] [--muestras 4] [--reanudar] [--sufijo x]

Cada ENSAYO (tarea x réplica) genera K muestras INDEPENDIENTES de primgen
(max_rondas=1, temp de producción; la diversidad viene de rehacer el pipeline
entero, no de subir la temperatura) y juzga CADA muestra con los DOS
contratos: el original de la tarea y el held-out a mano. El control es la
muestra s=1 del propio ensayo (misma corrida, mismo reloj). El selector
held-out elige sin mirar el contrato original. Guardado incremental,
reanudable; PARCIAL se declara si el corte llega.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_heldout")

# --banco duro|facil|brutal: el goal se define sobre el banco DURO (8
# tareas) y el modo BoN solo se habia medido en brutal. El held-out puede
# faltar al generar (fase 1) y aplicarse despues (fase 2, --solo-juzgar):
# asi la GPU no espera a que los contratos a mano esten escritos.
BANCOS = {
    "brutal": ("b1_tareas_brutales.json", "b1_contratos_heldout.json"),
    "facil": ("b1_tareas.json", "b1_contratos_heldout_facil.json"),
    "duro": ("b1_tareas_duras.json", "b1_contratos_heldout_duras.json"),
    # cabecera nueva: se CALIBRA (pass@1 por tarea) antes de usarse para
    # medir progreso — PREREG_CABECERA_NUEVA_20260730.md
    "cabecera": ("b1_tareas_cabecera.json", "b1_contratos_heldout_cabecera.json"),
    # 2a tanda: test de la hipotesis "invariante global re-evaluado"
    "cabecera2": ("b1_tareas_cabecera2.json", "b1_contratos_heldout_cabecera2.json"),
}


def _cargar_b2():
    spec = importlib.util.spec_from_file_location(
        "b2_sistema_real", RAIZ / "scripts" / "b2_sistema_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _es_infra(m: dict) -> bool:
    # PRIMERA ENMIENDA del prereg (revisión pre-lanzamiento): "sin HTML" con
    # backend sano es un fallo LEGITIMO del modelo (cuenta como reprobado,
    # no como infra — excluirlo sesgaba anti-BoN y comía ensayos enteros).
    # Infra = EXCEPCION del harness, juez crasheado, o backend
    # degradado/≠8080. La degradación del árbitro visual (:8081 apagado) está
    # PREVISTA en esta corrida (la GPU la ocupa el cerebro) y no invalida.
    if "EXCEPCION" in m.get("como", ""):
        return True
    if "juez crasheo" in m.get("motivo", "") or m.get("heldout_crasheo"):
        return True
    b = m.get("backend") or {}
    if not b:
        return False
    if b.get("via") == "arbitro_visual":
        return False
    return bool(b.get("degradado") or b.get("puerto") not in (8080, None))


def _elegir(muestras: list) -> dict | None:
    """Selector held-out: aprobado_heldout > checks_ok_heldout > s menor.
    NO mira el contrato original (eso lo convertiría en oráculo)."""
    pool = [m for m in muestras if not _es_infra(m)]
    if not pool:
        return None
    return sorted(pool, key=lambda m: (not m.get("aprobado_heldout"),
                                       -m.get("heldout_checks_ok", 0),
                                       m["s"]))[0]


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import con_presupuesto

    replicas = (int(argv[argv.index("--replicas") + 1])
                if "--replicas" in argv else 6)
    muestras_k = (int(argv[argv.index("--muestras") + 1])
                  if "--muestras" in argv else 4)
    reanudar = "--reanudar" in argv
    # --solo-resumen: si el corte de la sesión mató el proceso, el veredicto
    # pre-registrado tiene que poder leerse de lo ya guardado SIN gastar GPU.
    solo_resumen = "--solo-resumen" in argv
    if solo_resumen:
        reanudar = True
    global SALIDA, TAREAS, HELDOUT
    banco = (argv[argv.index("--banco") + 1]
             if "--banco" in argv else "brutal")
    if banco not in BANCOS:
        sys.exit(f"--banco {banco}: usa uno de {sorted(BANCOS)}")
    if banco != "brutal":
        f_t, f_h = BANCOS[banco]
        TAREAS = RAIZ / "scripts" / f_t
        HELDOUT = RAIZ / "scripts" / f_h
        SALIDA = SALIDA.with_name(SALIDA.name + "_" + banco)
    # --sin-heldout: fase 1 (generar) sin exigir los contratos a mano; el
    # juez estricto se aplica despues con --solo-juzgar.
    sin_heldout = "--sin-heldout" in argv
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])

    # Flags residuales del shell cambiarían el sistema medido sin dejar
    # rastro; la corrida mide el código de main tal cual.
    os.environ.pop("COGNIA_IDEA_PELADA", None)
    os.environ.pop("COGNIA_PROMPT_FIX2", None)
    os.environ.pop("COGNIA_MAX_RONDAS", None)
    b2 = _cargar_b2()
    from cognia.program_creator import diseno_a_codigo
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"
    from cognia.colonia import feromona
    feromona.RUTA_RASTRO = SALIDA / "feromona.json"
    # La degradación tiene que ser RUIDOSA, no una celda envenenada por el
    # 3B de Ollama (patrón b2_ab_gap). Revisión: el patch del módulo NO
    # basta — llm_local.generar tiene su PROPIO fallback que lee el env en
    # cada llamada; se neutralizan los dos.
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-BON-HELDOUT"
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-BON-HELDOUT"
    from cognia import backend_activo

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    heldout = ({t["id"]: t["contrato"] for t in
                json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
               if HELDOUT.is_file() else {})
    faltan = [t["id"] for t in tareas if t["id"] not in heldout]
    if faltan and not sin_heldout:
        sys.exit(f"sin held-out para {faltan}: el juez estricto no existe")
    if faltan:
        print(f"[fase 1] SIN held-out para {len(faltan)} tareas: se GENERA y "
              f"se juzga con el contrato original; el juez estricto se "
              f"aplica despues con --solo-juzgar\n", flush=True)

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo (correr sin "
                 f"el flag lo SOBRESCRIBIRIA en silencio)")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"muestras": []})
    hechas = {(m["tarea"], m["rep"], m["s"]) for m in res["muestras"]}

    import inspect
    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    # Reanudar tras un cambio de código o de plan mezclaría dos sistemas
    # sin dejar rastro (revisión pre-lanzamiento): se aborta ruidosamente.
    # --acepta-commit: si el que reanuda VERIFICÓ que los commits nuevos no
    # tocan cognia/ ni el runner (docs/datos), puede seguir — y la config
    # registra TODOS los commits bajo los que corrió, no finge uno solo.
    previa = res.get("config")
    if reanudar and previa:
        for campo, ahora in (("replicas", replicas),
                             ("muestras_por_ensayo", muestras_k)):
            if previa.get(campo) != ahora:
                sys.exit(f"--reanudar con {campo} distinto "
                         f"({previa.get(campo)} -> {ahora}): la corrida "
                         f"mezclaría dos sistemas; usa --sufijo nuevo")
        commits_previos = previa.get("commits", [previa.get("commit")])
        if commit not in commits_previos:
            if "--acepta-commit" not in argv:
                sys.exit(f"--reanudar con commit distinto "
                         f"({commits_previos} -> {commit}): si los commits "
                         f"nuevos no tocan el sistema medido, relanza con "
                         f"--acepta-commit; si lo tocan, --sufijo nuevo")
            print(f"  REANUDACION ACEPTADA entre commits: "
                  f"{commits_previos} + {commit}", flush=True)
            commits_previos = commits_previos + [commit]
        res_commits = commits_previos
    else:
        res_commits = [commit]
    # Sondas en runtime, no copias muertas del env (patrón b2_ab_lazo).
    from cognia.program_creator.generator import _componentes_de_idea
    sonda_fix2 = _componentes_de_idea(
        "una grilla con datos exactos de prueba. TARGET LOOK, match it: "
        "paleta oscura con acentos vivos")
    res["config"] = {
        "replicas": replicas, "muestras_por_ensayo": muestras_k,
        "commit": commit, "commits": res_commits, "max_rondas": 1,
        "max_rondas_defecto": diseno_a_codigo.MAX_RONDAS_DEFECTO,
        "fix2_activo_sonda": not any("paleta" in p or "TARGET" in p
                                     for p in sonda_fix2),
        "modo_contrato_default": inspect.signature(
            juez_ejecutable.generar_contrato).parameters["modo"].default,
        "backend": backend_activo.estado(),
        "ollama_fallback_neutralizado": _generator.OLLAMA_MODEL,
        "nota": "primgen de main tal cual; juez estricto = original ∧ "
                "held-out; selector = held-out solo"}

    print(f"BoN HELD-OUT — {len(tareas)} tareas x {replicas} réplicas x "
          f"{muestras_k} muestras (primgen, brutal)\n"
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    for rep in (range(1, replicas + 1) if not solo_resumen else []):
        rot = rep % len(tareas)
        for t in tareas[rot:] + tareas[:rot]:
            for s in range(1, muestras_k + 1):
                if (t["id"], rep, s) in hechas:
                    continue
                # Semilla por MUESTRA (no por par): aquí la diversidad de
                # hints es deseada, es la fuente del margen que se mide.
                random.seed(f"{t['id']}:r{rep}:s{s}")
                d = SALIDA / f"{t['id']}__r{rep}__s{s}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} s{s} ...", flush=True)
                try:
                    html, segs, como, meta = b2.correr_sistema(
                        t["idea"], d, max_rondas=1)
                except Exception as exc:
                    html, segs, como, meta = (None, 0.0,
                                              f"EXCEPCION {exc}"[:80], {})
                m = {"tarea": t["id"], "rep": rep, "s": s,
                     "segundos": round(segs, 1), "como": como[:90],
                     "backend": backend_activo.ultimo(), **meta}
                if not html:
                    m.update(aprobado=False, motivo="sin HTML")
                else:
                    (d / "index.html").write_text(html, encoding="utf-8")
                    try:
                        # PRESUPUESTO DE PARED en el juzgado (2026-07-30):
                        # una pagina con JS bloqueante cuelga page.evaluate
                        # PARA SIEMPRE — medido dos veces (595 s y 719 s de
                        # CPU de chromium). Este runner es anterior a esa
                        # leccion y colgaba la corrida entera.
                        # [[juez-colgado-js-bloqueante]]
                        v = con_presupuesto(300, juez_ejecutable.juzgar_web,
                                            d / "index.html", t["contrato"])
                        m.update(aprobado=v.aprobado, motivo=v.motivo[:100],
                                 checks_ok=sum(1 for c in v.checks if c.ok),
                                 checks=len(v.checks))
                    except Exception as exc:
                        m.update(aprobado=False,
                                 motivo=f"juez crasheo: {exc}"[:100])
                    # El held-out corre sobre TODAS las muestras con HTML
                    # (no solo las aprobadas): el selector necesita su
                    # ranking completo y la métrica D necesita los dos lados.
                    try:
                        if t["id"] not in heldout:
                            raise KeyError("sin held-out (fase 1)")
                        vh = con_presupuesto(
                            300, juez_ejecutable.juzgar_web,
                            d / "index.html", heldout[t["id"]])
                        m.update(aprobado_heldout=vh.aprobado,
                                 heldout_checks_ok=sum(
                                     1 for c in vh.checks if c.ok),
                                 heldout_checks=len(vh.checks))
                    except Exception as exc:
                        m.update(aprobado_heldout=None, heldout_crasheo=True,
                                 heldout_motivo=f"{exc}"[:100])
                m["estricto"] = bool(m.get("aprobado")
                                     and m.get("aprobado_heldout"))
                res["muestras"].append(m)
                _guardar()
                print(f"       -> orig={'OK' if m.get('aprobado') else 'no'} "
                      f"heldout={'OK' if m.get('aprobado_heldout') else 'no'} "
                      f"estricto={'OK' if m['estricto'] else 'no'} "
                      f"({segs:.0f}s)", flush=True)

    # ── resumen apareado (métricas A/B/C/D del prereg) ───────────────────
    ensayos: dict = {}
    for m in res["muestras"]:
        ensayos.setdefault((m["tarea"], m["rep"]), []).append(m)
    validos, excl_infra, incompletos = [], [], []
    for clave, ms in sorted(ensayos.items()):
        ms.sort(key=lambda m: m["s"])
        # Un ensayo con menos de K muestras (corte a mitad) computaría un
        # pass@2 disfrazado de pass@4 y podría fabricar un KILL (revisión
        # pre-lanzamiento): fuera del apareado, reportado aparte.
        if {m["s"] for m in ms} != set(range(1, muestras_k + 1)):
            incompletos.append(clave)
            continue
        s1 = next((m for m in ms if m["s"] == 1), None)
        no_infra = [m for m in ms if not _es_infra(m)]
        if s1 is None or _es_infra(s1) or not no_infra:
            excl_infra.append(clave)
            continue
        validos.append((clave, ms, s1, no_infra))

    neto_a = neto_b = 0
    gana_a, gana_b, pierde_selector = [], [], []
    for clave, ms, s1, no_infra in validos:
        control = bool(s1["estricto"])
        techo = any(m["estricto"] for m in no_infra)
        eleg = _elegir(ms)
        elegido = bool(eleg and eleg["estricto"])
        neto_a += (techo and not control) - (control and not techo)
        neto_b += (elegido and not control) - (control and not elegido)
        if techo and not control:
            gana_a.append(clave)
        if elegido and not control:
            gana_b.append(clave)
        if techo and not elegido:
            pierde_selector.append(clave)

    # D: FP del contrato original (aprueba el examen, no la materia).
    fp_orig: dict = {}
    for m in res["muestras"]:
        if (not _es_infra(m) and m.get("aprobado")
                and m.get("aprobado_heldout") is False):
            fp_orig[m["tarea"]] = fp_orig.get(m["tarea"], 0) + 1

    n_v = len(validos)
    ctrl_ok = sum(1 for _, _, s1, _ in validos if s1["estricto"])
    techo_ok = sum(1 for _, _, _, ni in validos
                   if any(m["estricto"] for m in ni))
    eleg_ok = sum(1 for _, ms, _, _ in validos
                  if (lambda e: bool(e and e["estricto"]))(_elegir(ms)))
    print(f"\n{'=' * 70}")
    print(f"  BoN HELD-OUT ({n_v} ensayos válidos, {len(excl_infra)} "
          f"excluidos por infra, {len(incompletos)} incompletos)")
    print(f"  control (s=1 estricto) : {ctrl_ok}/{n_v}")
    print(f"  A techo pass@{muestras_k}      : {techo_ok}/{n_v}   neto A = "
          f"{neto_a:+d}  (prereg: >=+5 MARGEN GRANDE, +3..+4 moderado, "
          f"<=+2 KILL)")
    print(f"  B selector held-out    : {eleg_ok}/{n_v}   neto B = {neto_b:+d}"
          f"  (prereg: B>=A-1 captura, <=A-3 pierde)")
    print(f"  C ensayos que el selector pierde: {len(pierde_selector)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in pierde_selector) or '—'})")
    print(f"  D FP del contrato original por tarea: {fp_orig or '—'}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "ensayos_validos": n_v, "excluidos_infra": [f"{t}:r{r}"
                                                    for t, r in excl_infra],
        "ensayos_incompletos": [f"{t}:r{r}" for t, r in incompletos],
        "control_estricto": f"{ctrl_ok}/{n_v}",
        "techo_pass_k": f"{techo_ok}/{n_v}", "neto_a": neto_a,
        "selector": f"{eleg_ok}/{n_v}", "neto_b": neto_b,
        "gana_a": [f"{t}:r{r}" for t, r in gana_a],
        "gana_b": [f"{t}:r{r}" for t, r in gana_b],
        "pierde_selector": [f"{t}:r{r}" for t, r in pierde_selector],
        "fp_contrato_original": fp_orig}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
