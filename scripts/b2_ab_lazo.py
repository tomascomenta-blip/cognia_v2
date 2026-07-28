"""
b2_ab_lazo.py — ¿el LAZO de reparación suma o resta? A/B intercalado
lazo (max_rondas=3, producción) vs primgen (max_rondas=1, primera
generación juzgada). PREREG_SENAL_CONTRATO_20260727.md, TERCERA ENMIENDA:
leerla ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ab_lazo.py
        [--replicas 6] [--reanudar] [--sufijo x]

Banco brutal, sistema completo, brazos intercalados a nivel tarea con orden
rotado por celda ([[gate-e2e-flaky]]: el control vive en la MISMA corrida).
Ambos brazos heredan el estado vigente del código (descarte de contratos
vacuos, fix2 según el veredicto del A/B v3, modo de contrato del lazo) — el
JSON registra ese estado en "config". Veredicto por pares apareados:
lazo gana >=3 netas = SUMA; [-2,+2] = ruido; primgen >=3 = RESTA.
Guardado incremental; reanudable; PARCIAL se declara si el corte llega.
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
          / "b2_ab_lazo")
BRAZOS = ["lazo", "primgen"]        # lazo=produccion (rondas 3); primgen=1


def _cargar_b2():
    spec = importlib.util.spec_from_file_location(
        "b2_sistema_real", RAIZ / "scripts" / "b2_sistema_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    replicas = (int(argv[argv.index("--replicas") + 1])
                if "--replicas" in argv else 6)
    reanudar = "--reanudar" in argv
    global SALIDA, TAREAS
    # --banco facil: la confirmación de la QUINTA enmienda corre sobre
    # b1_tareas.json (6 tareas); el default sigue siendo el brutal.
    banco = (argv[argv.index("--banco") + 1]
             if "--banco" in argv else "brutal")
    if banco == "facil":
        TAREAS = RAIZ / "scripts" / "b1_tareas.json"
        SALIDA = SALIDA.with_name(SALIDA.name + "_facil")
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])
    # Flags residuales del shell cambiarian el sistema medido sin dejar
    # rastro; ambos brazos corren con el codigo TAL CUAL esta en main.
    # (Gate de lanzamiento de la revision: si el A/B v3 dio "cobra", el flip
    # del default de fix2 se commitea en generator.py ANTES de lanzar esto —
    # el estado real se registra abajo con una SONDA en runtime, no con el
    # env ya popeado.)
    os.environ.pop("COGNIA_IDEA_PELADA", None)
    os.environ.pop("COGNIA_PROMPT_FIX2", None)
    b2 = _cargar_b2()
    from cognia.program_creator import diseno_a_codigo
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"
    # La corrida no ensucia el rastro de feromona de produccion (revision:
    # cada celda appendea discrepancias del idea_router con ideas del banco).
    from cognia.colonia import feromona
    feromona.RUTA_RASTRO = SALIDA / "feromona.json"

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo (correr sin "
                 f"el flag lo SOBRESCRIBIRIA en silencio)")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    hechas = {(c["tarea"], c["brazo"], c["rep"]) for c in res["celdas"]}

    # El estado heredado se declara con SONDAS en runtime (revision: un
    # campo copiado del env ya popeado siempre diria False y no declara
    # nada). fix2 activo = el troceo corta el adorno TARGET LOOK.
    import inspect
    import subprocess
    from cognia.program_creator.generator import _componentes_de_idea
    sonda_fix2 = _componentes_de_idea(
        "una grilla con datos exactos de prueba. TARGET LOOK, match it: "
        "paleta oscura con acentos vivos")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    res["config"] = {
        "brazos": BRAZOS, "replicas": replicas, "commit": commit,
        "fix2_activo_sonda": not any("paleta" in p or "TARGET" in p
                                     for p in sonda_fix2),
        "modo_contrato_default": inspect.signature(
            juez_ejecutable.generar_contrato).parameters["modo"].default,
        "max_rondas_defecto": diseno_a_codigo.MAX_RONDAS_DEFECTO,
        "nota": "ambos brazos con el codigo de main tal cual"}

    print(f"A/B LAZO vs PRIMGEN — sistema completo x banco brutal, "
          f"INTERCALADO\nconfig: brazos={BRAZOS}, replicas={replicas}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    for rep in range(1, replicas + 1):
        for i_t, t in enumerate(tareas):
            orden = BRAZOS if (rep + i_t) % 2 == 0 else BRAZOS[::-1]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                # Mismo extra_hint para el par (menos varianza apareada).
                random.seed(f"{t['id']}:{rep}")
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} {brazo:<8} ...", flush=True)
                kwargs = {} if brazo == "lazo" else {"max_rondas": 1}
                try:
                    html, segs, como, meta = b2.correr_sistema(
                        t["idea"], d, **kwargs)
                except Exception as exc:
                    html, segs, como, meta = (None, 0.0,
                                              f"EXCEPCION {exc}"[:80], {})
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep,
                         "segundos": round(segs, 1), "como": como[:90], **meta}
                if not html:
                    celda.update(aprobado=False, motivo="sin HTML")
                else:
                    (d / "index.html").write_text(html, encoding="utf-8")
                    try:
                        v = juez_ejecutable.juzgar_web(d / "index.html",
                                                       t["contrato"])
                        celda.update(
                            aprobado=v.aprobado, motivo=v.motivo[:100],
                            checks_ok=sum(1 for c in v.checks if c.ok),
                            checks=len(v.checks))
                    except Exception as exc:
                        celda.update(aprobado=False,
                                     motivo=f"juez crasheo: {exc}"[:100])
                    # try PROPIO (revision): un crash del held-out no puede
                    # pisar el APROBADO primario — solo castigaria al brazo
                    # que aprobo, y ±1-2 flakes mueven el veredicto.
                    if celda.get("aprobado") and t["id"] in heldout:
                        try:
                            vh = juez_ejecutable.juzgar_web(
                                d / "index.html", heldout[t["id"]])
                            celda["aprobado_heldout"] = vh.aprobado
                        except Exception:
                            celda["aprobado_heldout"] = None
                res["celdas"].append(celda)
                _guardar()
                print(f"       -> {'APROBADO' if celda['aprobado'] else 'FALLIDO'}"
                      f" ({celda.get('checks_ok', '?')}/"
                      f"{celda.get('checks', '?')}, {segs:.0f}s, "
                      f"sello={celda.get('sello_lazo')})", flush=True)

    # ── resumen apareado ─────────────────────────────────────────────────
    # Pares con celda de INFRA (excepcion del harness / backend caido) se
    # excluyen del neto y se reportan (pre-declarado en la cuarta enmienda:
    # una caida del server cae asimetrica sobre el brazo lazo, que ocupa
    # ~3x mas reloj, y ±3 celdas de infra fabrican un veredicto).
    def _es_infra(c):
        return ("EXCEPCION" in c.get("como", "")
                or c.get("motivo") == "sin HTML"
                or "juez crasheo" in c.get("motivo", ""))

    infra = {(c["tarea"], c["rep"]) for c in res["celdas"] if _es_infra(c)}
    vl = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
          for c in res["celdas"] if c["brazo"] == "lazo"}
    vp = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
          for c in res["celdas"] if c["brazo"] == "primgen"}
    comunes = sorted((set(vl) & set(vp)) - infra)
    gana_lazo = [k for k in comunes if vl[k] and not vp[k]]
    gana_prim = [k for k in comunes if vp[k] and not vl[k]]
    n_infra = {b: sum(1 for c in res["celdas"]
                      if c["brazo"] == b and _es_infra(c)) for b in BRAZOS}
    n_fallback = {b: sum(1 for c in res["celdas"]
                         if c["brazo"] == b and "create_program"
                         in c.get("como", "")) for b in BRAZOS}
    ap_l = sum(1 for c in res["celdas"]
               if c["brazo"] == "lazo" and c.get("aprobado"))
    n_l = sum(1 for c in res["celdas"] if c["brazo"] == "lazo")
    ap_p = sum(1 for c in res["celdas"]
               if c["brazo"] == "primgen" and c.get("aprobado"))
    n_p = sum(1 for c in res["celdas"] if c["brazo"] == "primgen")
    print(f"\n{'=' * 70}")
    print(f"  A/B LAZO (apareado, {len(comunes)} pares): "
          f"lazo {ap_l}/{n_l}  primgen {ap_p}/{n_p}")
    print(f"  lazo gana:    {len(gana_lazo)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_lazo) or '—'})")
    print(f"  primgen gana: {len(gana_prim)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_prim) or '—'})")
    tareas_l = {t for t, _ in gana_lazo}
    tareas_p = {t for t, _ in gana_prim}
    print(f"  NETO LAZO: {len(gana_lazo) - len(gana_prim)}  "
          f"(prereg: >=3 SUMA, [-2,+2] ruido, <=-3 RESTA; el veredicto "
          f"ademas exige reparto en >=2 tareas y n=24 pares completos)")
    print(f"  reparto: lazo gana en {len(tareas_l)} tareas, primgen en "
          f"{len(tareas_p)}")
    print(f"  infra excluida: {n_infra}; via create_program: {n_fallback}")
    print(f"{'=' * 70}")
    res["resumen"] = {"lazo": f"{ap_l}/{n_l}", "primgen": f"{ap_p}/{n_p}",
                      "pares": len(comunes),
                      "gana_lazo": [f"{t}:r{r}" for t, r in gana_lazo],
                      "gana_primgen": [f"{t}:r{r}" for t, r in gana_prim],
                      "neto_lazo": len(gana_lazo) - len(gana_prim),
                      "tareas_gana_lazo": sorted(tareas_l),
                      "tareas_gana_primgen": sorted(tareas_p),
                      "pares_infra_excluidos": sorted(
                          f"{t}:r{r}" for t, r in infra),
                      "infra_por_brazo": n_infra,
                      "create_program_por_brazo": n_fallback}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
