"""
b2_lazo_vs_replay.py — ¿el REPLAY representa al LAZO? Validez del
instrumento de las sondas. PREREG_LAZO_VS_REPLAY_20260729.md: leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_lazo_vs_replay.py
        [--replicas 6] [--reanudar] [--sufijo x] [--solo-resumen]
        [--tarea id]

Por celda (apareado PERFECTO, mismo prompt y mismo minuto):
  1. LAZO   = correr_sistema con COGNIA_DUMP_PROMPTS a un dir POR CELDA.
  2. REPLAY = el prompt capturado de ESA celda, por llm_local.generar con
     los args exactos del lazo. Del MISMO crudo salen DOS paginas:
       replay_real  = _parse_response(crudo, tarea, "html")  (parseo del lazo)
       replay_fence = el _parsear heredado de las sondas
  3. Los tres se juzgan estricto (original ∧ held-out), cada juzgado bajo
     su propio presupuesto de pared.

Primaria: neto (LAZO - replay_real). Secundaria decisiva: neto
(replay_real - replay_fence) = el coste del parseo de las sondas.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_lazo_vs_replay")
URL_BACKEND = "http://127.0.0.1:8080"
CTX_MINIMO = 16384
# el LAZO no pasa timeout -> llm_local.TIMEOUT_GEN = 120. El replay usa el
# MISMO (A1 de la revisión): con 400 tendría una ventaja que el lazo no
# tiene, y el corte a 120 es justo lo que dispara el fallback del lazo.
TIMEOUT_GEN_LAZO = 120
PRESUPUESTO_JUEZ = 300
BRAZOS = ["lazo", "replay_real", "replay_fence"]


def _cargar_b2():
    spec = importlib.util.spec_from_file_location(
        "b2_sistema_real", RAIZ / "scripts" / "b2_sistema_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verificar_backend() -> None:
    try:
        with urllib.request.urlopen(URL_BACKEND + "/props", timeout=10) as r:
            props = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        sys.exit(f"ABORTO: {URL_BACKEND}/props no responde ({exc})")
    slots = props.get("total_slots")
    ctx = (props.get("default_generation_settings") or {}).get("n_ctx") \
        or props.get("n_ctx")
    if slots != 1 or not ctx or int(ctx) < CTX_MINIMO:
        sys.exit(f"ABORTO: slots={slots} ctx={ctx} (se exige 1 y >={CTX_MINIMO})")
    if "gpt-oss" not in str(props.get("model_path") or "").lower():
        sys.exit(f"ABORTO: :8080 no sirve gpt-oss ({props.get('model_path')})")
    print(f"  backend OK: slots=1, n_ctx={ctx}", flush=True)


def _parsear_fence(crudo: str) -> str | None:
    """El parseo heredado de las sondas (fence crudo)."""
    from cognia.program_creator.generator import _parse_response
    html = None
    try:
        prog = _parse_response(crudo, lenguaje="html")   # TypeError real
        html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
    except Exception:
        html = None
    if not html:
        if "```" in crudo:
            trozo = crudo.split("```")[1]
            html = trozo[4:] if trozo.lstrip()[:4].lower() == "html" else trozo
        else:
            html = crudo
    return html if html and "<" in html else None


def _parsear_real(crudo: str, tarea: str) -> str | None:
    """El parseo del LAZO (firma correcta)."""
    from cognia.program_creator.generator import _parse_response
    buf = io.StringIO()
    with redirect_stdout(buf):
        prog = _parse_response(crudo, tarea, "html")
    return getattr(prog, "code", None) if prog is not None else None


def _salud_backend() -> bool:
    try:
        with urllib.request.urlopen(URL_BACKEND + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _prompt_del_lazo(dir_dump: Path) -> dict | None:
    """El prompt CON troceo de esta celda (si hubo fallback hay 2 dumps)."""
    f = dir_dump / "prompts.jsonl"
    if not f.is_file():
        return None
    filas = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    con_req = [p for p in filas if p.get("lenguaje") == "html"
               and "- REQUIRED component" in p["prompt"]]
    return con_req[0] if con_req else None


def _es_infra(c: dict) -> bool:
    b = c.get("backend") or {}
    # B1/B2 de la revisión: la EXCEPCIÓN del lazo vive en `como_lazo` (no en
    # `como`), y un juez crasheado en CUALQUIERA de los tres productos saca
    # el par (si no, el None del crash cuenta como reprobado y engorda el
    # neto en la dirección de la hipótesis).
    return ("EXCEPCION" in str(c.get("como", "")) + str(c.get("como_lazo", ""))
            or any("juez crasheo" in str(c.get(f"motivo_{b_}", ""))
                   for b_ in BRAZOS)
            or any(c.get(f"estricto_{b_}") is None for b_ in BRAZOS)
            or c.get("sin_prompt")
            or bool(b.get("degradado"))
            or (b.get("puerto") not in (None, 8080)))


def _resumir(res: dict) -> None:
    celdas = res["celdas"]
    validas = [c for c in celdas if not _es_infra(c)]
    def neto(a: str, b: str):
        ga = [c for c in validas if c.get(a) and not c.get(b)]
        gb = [c for c in validas if c.get(b) and not c.get(a)]
        return len(ga) - len(gb), ga, gb
    n_lr, g_l, g_r = neto("estricto_lazo", "estricto_replay_real")
    n_rf, g_rr, g_rf = neto("estricto_replay_real", "estricto_replay_fence")
    tasas = {b: sum(1 for c in validas if c.get(f"estricto_{b}"))
             for b in BRAZOS}
    fallback = [c for c in validas if c.get("como_lazo") == "create_program"]
    # A2: co-primaria SIN los fallbacks — el fallback es una SEGUNDA
    # generación (idea pelada) que el replay no tiene; declarar "el flujo
    # aporta" por tener dos tiros sería trampa.
    sin_fb = [c for c in validas if c.get("como_lazo") != "create_program"]
    n_lr_sfb = (sum(1 for c in sin_fb if c.get("estricto_lazo")
                    and not c.get("estricto_replay_real"))
                - sum(1 for c in sin_fb if c.get("estricto_replay_real")
                      and not c.get("estricto_lazo")))
    fb_ok = sum(1 for c in fallback if c.get("estricto_lazo"))
    rechaza_real = sum(1 for c in validas if c.get("real_rechazado"))
    concord = sum(1 for c in validas
                  if bool(c.get("estricto_lazo"))
                  == bool(c.get("estricto_replay_real")))
    print(f"\n{'=' * 72}")
    print(f"  LAZO vs REPLAY ({len(validas)} pares validos de {len(celdas)})")
    for b in BRAZOS:
        print(f"    {b:<14} {tasas[b]:>2}/{len(validas)} "
              f"= {tasas[b]/max(1,len(validas))*100:.0f}%")
    print(f"  PRIMARIA neto (lazo - replay_real): {n_lr}   "
          f"(prereg: >=+4 el FLUJO aporta; -1..+3 aporta poco; <=-2 roba)")
    print(f"  CO-PRIMARIA sin fallbacks ({len(sin_fb)} pares): {n_lr_sfb}   "
          f"(rige la MAS CONSERVADORA de las dos)")
    etiq = lambda xs: ", ".join(f"{c['tarea']}:r{c['rep']}" for c in xs) or "—"
    print(f"    gana lazo: {len(g_l)} ({etiq(g_l)})")
    print(f"    gana replay_real: {len(g_r)} ({etiq(g_r)})")
    print(f"  SECUNDARIA neto (replay_real - replay_fence): {n_rf}   "
          f"(>=+2 el parseo de las sondas DEPRIME el replay)")
    print(f"  fallback del lazo: {len(fallback)} celdas ({fb_ok} aprobadas) | "
          f"parse real rechaza el crudo del replay: {rechaza_real}")
    print(f"  concordancia lazo<->replay_real: {concord}/{len(validas)}")
    print(f"{'=' * 72}")
    res["resumen"] = {
        "pares": len(validas), "tasas": tasas,
        "neto_lazo_vs_replay_real": n_lr,
        "neto_sin_fallbacks": n_lr_sfb, "pares_sin_fallback": len(sin_fb),
        "gana_lazo": [f"{c['tarea']}:r{c['rep']}" for c in g_l],
        "gana_replay_real": [f"{c['tarea']}:r{c['rep']}" for c in g_r],
        "neto_real_vs_fence": n_rf,
        "gana_real": [f"{c['tarea']}:r{c['rep']}" for c in g_rr],
        "gana_fence": [f"{c['tarea']}:r{c['rep']}" for c in g_rf],
        "fallback_celdas": len(fallback), "fallback_aprobadas": fb_ok,
        "real_rechaza_crudo": rechaza_real,
        "concordancia": f"{concord}/{len(validas)}",
        "infra": [f"{c['tarea']}:r{c['rep']}" for c in celdas
                  if _es_infra(c)]}


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import (PresupuestoAgotado, con_presupuesto,
                                          presupuesto_celda)

    replicas = (int(argv[argv.index("--replicas") + 1])
                if "--replicas" in argv else 6)
    reanudar = "--reanudar" in argv
    solo_resumen = "--solo-resumen" in argv
    solo_tarea = (argv[argv.index("--tarea") + 1]
                  if "--tarea" in argv else None)
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])

    for v in ("COGNIA_IDEA_PELADA", "COGNIA_PROMPT_FIX2",
              "COGNIA_SIN_TROCEO", "COGNIA_MAX_RONDAS"):
        os.environ.pop(v, None)
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-LVR"
    b2 = _cargar_b2()
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-LVR"
    from cognia import backend_activo, llm_local
    from cognia.program_creator.generator import _SISTEMA_WEB
    from cognia.program_creator import diseno_a_codigo
    from cognia.colonia import feromona

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    if solo_tarea:
        tareas = [t for t in tareas if t["id"] == solo_tarea]
        if not tareas:
            sys.exit(f"ABORTO: --tarea {solo_tarea} no existe")
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}

    SALIDA.mkdir(parents=True, exist_ok=True)
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"
    feromona.RUTA_RASTRO = SALIDA / "feromona.json"
    fichero_res = SALIDA / "resultados.json"
    if solo_resumen:
        if not fichero_res.is_file():
            sys.exit(f"no existe {fichero_res}")
        _resumir(json.loads(fichero_res.read_text(encoding="utf-8")))
        return 0
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    hechas = {(c["tarea"], c["rep"]) for c in res["celdas"]}

    _verificar_backend()
    import subprocess
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=RAIZ, capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    commits = (res.get("config") or {}).get("commits") or []
    if commit not in commits:
        commits.append(commit)
    res["config"] = {
        "replicas": replicas, "commit": commit, "commits": commits,
        "timeout_gen_s": TIMEOUT_GEN_LAZO,
        "backend": backend_activo.estado(),
        "max_rondas_defecto": diseno_a_codigo.MAX_RONDAS_DEFECTO,
        "nota": "apareado perfecto: el replay usa el prompt capturado de LA "
                "MISMA celda del lazo; dos parseos del mismo crudo"}
    print(f"LAZO vs REPLAY — apareado por celda\n"
          f"config: replicas={replicas}, commit={commit}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    def _juzgar_estricto(ruta: Path, tarea: str):
        def _dos(r, o, h):
            v = juez_ejecutable.juzgar_web(r, o)
            vh = juez_ejecutable.juzgar_web(r, h)
            return v, vh
        try:
            contrato = next(t["contrato"] for t in tareas if t["id"] == tarea)
            v, vh = con_presupuesto(PRESUPUESTO_JUEZ, _dos, ruta, contrato,
                                    heldout[tarea])
            return (bool(v.aprobado and vh.aprobado), bool(v.aprobado),
                    ((v.motivo or "") if not v.aprobado
                     else (vh.motivo or ""))[:90])
        except PresupuestoAgotado:
            return False, False, "juez colgado (JS bloqueante)"
        except Exception as exc:
            return None, None, f"juez crasheo: {exc}"[:90]

    for rep in range(1, replicas + 1):
        for t in tareas:
            if (t["id"], rep) in hechas:
                continue
            base = SALIDA / f"{t['id']}__r{rep}"
            dump = base / "dump"
            base.mkdir(parents=True, exist_ok=True)
            # B3: el dump se abre en modo "a"; un dir sucio de un intento
            # cortado haria que el replay usara el prompt VIEJO (otro
            # extra_hint) y el apareado se rompe en silencio.
            import shutil
            shutil.rmtree(dump, ignore_errors=True)
            dump.mkdir(parents=True, exist_ok=True)
            print(f"  r{rep} {t['id']:<14} lazo ...", flush=True)
            celda = {"tarea": t["id"], "rep": rep}
            t0 = time.time()
            os.environ["COGNIA_DUMP_PROMPTS"] = str(dump)
            try:
                # B4: la pata del lazo TAMBIEN bajo presupuesto de pared —
                # dentro corre Playwright con page.evaluate sin timeout (la
                # firma del cuelgue de 595 s), y esto es una corrida
                # nocturna desatendida.
                html_l, segs, como, meta = con_presupuesto(
                    presupuesto_celda(), b2.correr_sistema,
                    t["idea"], base / "lazo")
            except PresupuestoAgotado:
                html_l, segs, como, meta = (None, time.time() - t0,
                                            "EXCEPCION presupuesto lazo", {})
            except Exception as exc:
                html_l, segs, como, meta = None, 0.0, f"EXCEPCION {exc}"[:80], {}
            finally:
                os.environ.pop("COGNIA_DUMP_PROMPTS", None)
            celda.update(segundos_lazo=round(segs, 1),
                         como_lazo=("create_program"
                                    if "create_program" in str(como)
                                    else str(como)[:40]),
                         backend=backend_activo.ultimo(), **meta)
            if html_l:
                (base / "lazo").mkdir(parents=True, exist_ok=True)
                p = base / "lazo" / "index.html"
                p.write_text(html_l, encoding="utf-8")
                e, o, m = _juzgar_estricto(p, t["id"])
                celda.update(estricto_lazo=e, orig_lazo=o, motivo_lazo=m)
            else:
                celda.update(estricto_lazo=False, orig_lazo=False,
                             motivo_lazo="sin HTML del lazo")

            fila_p = _prompt_del_lazo(dump)
            if fila_p is None:
                celda["sin_prompt"] = True
                res["celdas"].append(celda)
                _guardar()
                print("       -> SIN PROMPT capturado (par fuera)", flush=True)
                continue
            print(f"       lazo={'OK' if celda.get('estricto_lazo') else 'falla'}"
                  f" ({celda['segundos_lazo']:.0f}s, {celda['como_lazo']});"
                  f" replay ...", flush=True)

            t1 = time.time()
            crudo = None
            try:
                # A1: los args EXACTOS del lazo — incluido el timeout de 120
                # de llm_local (el lazo no pasa timeout). Con 400 el replay
                # tendría una ventaja que el lazo no tiene, y justamente el
                # corte a 120 es lo que dispara su fallback.
                crudo = con_presupuesto(
                    presupuesto_celda(), llm_local.generar,
                    fila_p["prompt"], system=fila_p.get("system")
                    or _SISTEMA_WEB,
                    temperature=float(fila_p["temperature"]),
                    max_tokens=12000, via="lazo_vs_replay",
                    timeout=TIMEOUT_GEN_LAZO)
            except PresupuestoAgotado:
                celda["como"] = "EXCEPCION presupuesto replay"
            except Exception as exc:
                celda["como"] = f"EXCEPCION {exc}"[:80]
            celda["segundos_replay"] = round(time.time() - t1, 1)
            if crudo:
                (base / "respuesta_cruda.txt").write_text(crudo,
                                                          encoding="utf-8")
            celda["crudo_chars"] = len(crudo or "")
            if not crudo and not _salud_backend():
                celda["backend"] = {"degradado": True,
                                    "detalle": "health post-fallo KO"}

            hr = _parsear_real(crudo, t["id"]) if crudo else None
            hf = _parsear_fence(crudo) if crudo else None
            celda["real_rechazado"] = bool(crudo) and hr is None
            celda["parseos_iguales"] = (hr or "").strip() == (hf or "").strip()
            for etiqueta, html in (("replay_real", hr), ("replay_fence", hf)):
                if html:
                    d = base / etiqueta
                    d.mkdir(parents=True, exist_ok=True)
                    p = d / "index.html"
                    p.write_text(html, encoding="utf-8")
                    e, o, m = _juzgar_estricto(p, t["id"])
                    celda.update(**{f"estricto_{etiqueta}": e,
                                    f"orig_{etiqueta}": o,
                                    f"motivo_{etiqueta}": m[:90]})
                else:
                    celda.update(**{f"estricto_{etiqueta}": False,
                                    f"orig_{etiqueta}": False,
                                    f"motivo_{etiqueta}": "sin HTML"})
            res["celdas"].append(celda)
            _guardar()
            print(f"       -> lazo={celda.get('estricto_lazo')} "
                  f"real={celda.get('estricto_replay_real')} "
                  f"fence={celda.get('estricto_replay_fence')} "
                  f"(iguales={celda['parseos_iguales']}, "
                  f"{celda['segundos_replay']:.0f}s)", flush=True)

    _resumir(res)
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
