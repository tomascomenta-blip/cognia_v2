"""
b2_ab_gap.py — ¿queda gap entre el SISTEMA (defaults vigentes) y el modelo
CRUDO? Medido con control concurrente en la MISMA corrida.
PREREG_SENAL_CONTRATO_20260727.md, SEXTA ENMIENDA: leerla ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ab_gap.py
        [--replicas 6] [--reanudar] [--sufijo x]

Banco brutal, intercalado a nivel tarea, semilla compartida por par.
Brazo `sistema` = correr_sistema con los defaults del código tal cual
(rondas=1 adoptado 2026-07-28, descarte de vacuos; sondas en config).
Brazo `crudo` = b1_router_oraculo.generar_html(idea) — la idea pelada por
la vía directa, el mismo generador del confound y la sonda. MEDICIÓN de
estado, no A/B de política. Guardado incremental; PARCIAL direccional.
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
          / "b2_ab_gap")
BRAZOS = ["sistema", "crudo"]


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(
        nombre, RAIZ / "scripts" / f"{nombre}.py")
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
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])
    os.environ.pop("COGNIA_IDEA_PELADA", None)
    os.environ.pop("COGNIA_PROMPT_FIX2", None)
    os.environ.pop("COGNIA_MAX_RONDAS", None)
    b2 = _cargar("b2_sistema_real")
    oraculo = _cargar("b1_router_oraculo")
    from cognia.program_creator import diseno_a_codigo
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"
    from cognia.colonia import feromona
    feromona.RUTA_RASTRO = SALIDA / "feromona.json"
    # Revision pre-lanzamiento: _call_llm cae en silencio a Ollama :11434
    # (llama3.2:1b) si :8080 hipa — y Ollama SI esta instalado en esta
    # maquina. Una celda degradada devolveria HTML basura del 1B que el
    # juez reprueba como si fuera fallo legitimo: victoria fantasma del
    # otro brazo. En esta MEDICION la degradacion tiene que ser RUIDOSA
    # (sin HTML -> infra excluida), no silenciosa: se neutraliza el
    # fallback apuntandolo a un modelo inexistente. OLLAMA_MODEL se lee al
    # importar, por eso se pisa el atributo del modulo, no el env.
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-AB-GAP"
    from cognia import backend_activo

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    hechas = {(c["tarea"], c["brazo"], c["rep"]) for c in res["celdas"]}

    import inspect
    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    res["config"] = {
        "brazos": BRAZOS, "replicas": replicas, "commit": commit,
        "modo_contrato_default": inspect.signature(
            juez_ejecutable.generar_contrato).parameters["modo"].default,
        "max_rondas_defecto": diseno_a_codigo.MAX_RONDAS_DEFECTO,
        # que sirve :8080 AHORA (la equivalencia con la sonda depende de
        # que sea el mismo combo de servir_flota)
        "backend": backend_activo.estado(),
        "ollama_fallback_neutralizado": _generator.OLLAMA_MODEL,
        "nota": "sistema = defaults del codigo tal cual; "
                "crudo = b1_router_oraculo.generar_html (idea pelada)"}

    print(f"A/B GAP sistema vs crudo — banco brutal, INTERCALADO\n"
          f"config: brazos={BRAZOS}, replicas={replicas}, commit={commit}, "
          f"max_rondas_defecto={res['config']['max_rondas_defecto']}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    import time
    for rep in range(1, replicas + 1):
        for i_t, t in enumerate(tareas):
            orden = BRAZOS if (rep + i_t) % 2 == 0 else BRAZOS[::-1]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                random.seed(f"{t['id']}:{rep}")
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} {brazo:<8} ...", flush=True)
                t0 = time.time()
                como, meta = brazo, {}
                try:
                    if brazo == "sistema":
                        html, segs, como, meta = b2.correr_sistema(
                            t["idea"], d)
                    else:
                        html = oraculo.generar_html(t["idea"])
                        segs = time.time() - t0
                except Exception as exc:
                    html, segs = None, time.time() - t0
                    como = f"EXCEPCION {exc}"[:80]
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep,
                         "segundos": round(segs, 1), "como": str(como)[:90],
                         # aproximacion declarada: el ultimo backend que
                         # registro ESTE proceso (en el brazo sistema hay
                         # varias llamadas por celda; una degradacion
                         # intermedia pudo ser pisada por una posterior)
                         "backend": backend_activo.ultimo(), **meta}
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
                      f"{celda.get('checks', '?')}, {segs:.0f}s)", flush=True)

    # ── resumen apareado (misma mecánica que b2_ab_lazo) ─────────────────
    def _es_infra(c):
        b = c.get("backend") or {}
        return ("EXCEPCION" in c.get("como", "")
                or c.get("motivo") == "sin HTML"
                or "juez crasheo" in c.get("motivo", "")
                # celda servida por un backend degradado o fuera de :8080:
                # mide otra cosa (revision pre-lanzamiento)
                or bool(b.get("degradado"))
                or (b.get("puerto") not in (None, 8080)))

    infra = {(c["tarea"], c["rep"]) for c in res["celdas"] if _es_infra(c)}
    vs = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
          for c in res["celdas"] if c["brazo"] == "sistema"}
    vc = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
          for c in res["celdas"] if c["brazo"] == "crudo"}
    comunes = sorted((set(vs) & set(vc)) - infra)
    gana_sis = [k for k in comunes if vs[k] and not vc[k]]
    gana_cru = [k for k in comunes if vc[k] and not vs[k]]
    ap_s = sum(1 for c in res["celdas"]
               if c["brazo"] == "sistema" and c.get("aprobado"))
    n_s = sum(1 for c in res["celdas"] if c["brazo"] == "sistema")
    ap_c = sum(1 for c in res["celdas"]
               if c["brazo"] == "crudo" and c.get("aprobado"))
    n_c = sum(1 for c in res["celdas"] if c["brazo"] == "crudo")
    n_infra = {b: sum(1 for c in res["celdas"]
                      if c["brazo"] == b and _es_infra(c)) for b in BRAZOS}
    print(f"\n{'=' * 70}")
    print(f"  A/B GAP (apareado, {len(comunes)} pares): "
          f"sistema {ap_s}/{n_s}  crudo {ap_c}/{n_c}")
    print(f"  sistema gana: {len(gana_sis)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_sis) or '—'})")
    print(f"  crudo gana:   {len(gana_cru)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_cru) or '—'})")
    print(f"  NETO SISTEMA: {len(gana_sis) - len(gana_cru)}  "
          f"(prereg: crudo>=+3 aun roba; [-2,+2] gap cerrado; "
          f"sistema>=+3 supera)")
    print(f"  infra excluida: {n_infra}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "sistema": f"{ap_s}/{n_s}", "crudo": f"{ap_c}/{n_c}",
        "pares": len(comunes),
        "gana_sistema": [f"{t}:r{r}" for t, r in gana_sis],
        "gana_crudo": [f"{t}:r{r}" for t, r in gana_cru],
        "neto_sistema": len(gana_sis) - len(gana_cru),
        "tareas_gana_sistema": sorted({t for t, _ in gana_sis}),
        "tareas_gana_crudo": sorted({t for t, _ in gana_cru}),
        "pares_infra_excluidos": sorted(f"{t}:r{r}" for t, r in infra),
        "infra_por_brazo": n_infra}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
