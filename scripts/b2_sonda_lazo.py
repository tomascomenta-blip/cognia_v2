"""
b2_sonda_lazo.py — FASE 1 de la sonda del ladrón: ¿el texto del prompt que
el lazo arma roba, o roba el flujo del lazo? PREREG_SONDA_LAZO_20260729.md
(con su PRIMERA ENMIENDA): leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_sonda_lazo.py
        [--replicas 6] [--reanudar] [--sufijo x] [--solo-resumen]
        [--tarea id]

Brazo L = replay ÍNTEGRO de un prompt capturado del lazo (b2_bon_gate_v2;
regla fija: ensayo rep=((r-1)%6)+1, muestra s=((r-1+i_tarea)%4)+1). Brazo
C = la idea pelada. AMBOS por llm_local.generar con los argumentos exactos
que emitió el lazo (system=_SISTEMA_WEB, max_tokens=12000, effort None) —
la única diferencia entre brazos es el TEXTO. Timeout 400 s (desviación
declarada del 120 de la captura: no censurar espirales lentas, simétrico).
Juez estricto = contrato original ∧ held-out, SIEMPRE ambos.

Clasificación de fallos (1ª enmienda — la espiral es SEÑAL, no infra):
  contenido "" con server sano        -> sin HTML, reprobado LEGÍTIMO
  respuesta None con server sano      -> reprobado LEGÍTIMO (se reporta)
  server caído / degradado / ≠8080    -> INFRA (par excluido)
Intercalado a nivel tarea, guardado incremental, PARCIAL direccional.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
GATE = (RAIZ / "cognia" / "program_creator" / "generated_programs"
        / "b2_bon_gate_v2")
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_sonda_lazo")
BRAZOS = ["replay", "crudo"]
URL_BACKEND = "http://127.0.0.1:8080"
CTX_MINIMO = 16384      # prompts L ~2.2k tok + 12k de generacion (v1 del gate)
TIMEOUT_GEN = 400       # 3/96 celdas del gate rozaron los 120 s del default
MAX_DEGRADADOS_SEGUIDOS = 4     # backend muerto a mitad de corrida: abortar
# 2a enmienda: una pagina cuyo JS bloquea el hilo principal cuelga a
# page.evaluate PARA SIEMPRE (medido en esta corrida: chromium con 595 s de
# CPU clavado en kanban__crudo__r1). El juzgado lleva SU presupuesto; el
# cuelgue es propiedad de la PAGINA -> reprobado legitimo, no infra.
PRESUPUESTO_JUEZ = 300


def _verificar_backend() -> None:
    """slots=1 Y ctx suficiente, o no se corre (lecciones de la v1 del gate)."""
    try:
        with urllib.request.urlopen(URL_BACKEND + "/props", timeout=10) as r:
            props = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        sys.exit(f"ABORTO: {URL_BACKEND}/props no responde ({exc}) — arranca "
                 f"servir_modelo.py --modelo gpt-oss --ctx 16384")
    slots = props.get("total_slots")
    ctx = (props.get("default_generation_settings") or {}).get("n_ctx") \
        or props.get("n_ctx")
    if slots != 1:
        sys.exit(f"ABORTO: total_slots={slots} (se exige 1; "
                 f"servir_modelo.py pasa --parallel 1)")
    if not ctx or int(ctx) < CTX_MINIMO:
        sys.exit(f"ABORTO: n_ctx={ctx} < {CTX_MINIMO} — context-shift "
                 f"silencioso asimétrico contra L (la contaminación de v1)")
    print(f"  backend OK: slots=1, n_ctx={ctx}", flush=True)


def _materia_prima() -> dict:
    """(tarea, rep_gate) -> lista de 4 dicts {prompt, temperature, s,
    estricto_gate}. Alineación verificada en el prereg: prompts.jsonl va en
    el orden de los ensayos de resultados.json, 4 prompts (s=1..4) por
    ensayo."""
    res = json.loads((GATE / "resultados.json").read_text(encoding="utf-8"))
    lineas = [json.loads(l) for l in
              (GATE / "prompts" / "prompts.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lineas) != 4 * len(res["ensayos"]):
        sys.exit(f"ABORTO: {len(lineas)} prompts para "
                 f"{len(res['ensayos'])} ensayos (esperaba 4 por ensayo)")
    material: dict = {}
    i = 0
    for e in res["ensayos"]:
        filas = []
        muestras = {m.get("s"): m for m in e["bon"].get("muestras", [])}
        for s in range(1, 5):
            p = lineas[i]
            i += 1
            orig = (e.get("orig") or {}).get(str(s)) or {}
            sel = muestras.get(s, {}).get("aprobado_sel")
            estricto = (bool(orig.get("aprobado")) and bool(sel)
                        if orig and sel is not None else None)
            filas.append({"prompt": p["prompt"],
                          "temperature": float(p["temperature"]),
                          "s": s, "estricto_gate": estricto})
        material[(e["tarea"], int(e["rep"]))] = filas
    return material


def _parsear(crudo: str) -> str | None:
    """Mismo parseo para ambos brazos (el helper histórico del crudo).
    Nota declarada: _parse_response TypeError-ea con html y siempre cae al
    fallback de fence — igual que en b1_router_oraculo, así que la simetría
    con el crudo histórico se conserva."""
    from cognia.program_creator.generator import _parse_response
    html = None
    try:
        prog = _parse_response(crudo, lenguaje="html")
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


def _salud_backend() -> bool:
    try:
        with urllib.request.urlopen(URL_BACKEND + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _es_infra(c: dict) -> bool:
    b = c.get("backend") or {}
    return ("EXCEPCION" in c.get("como", "")
            or "juez crasheo" in c.get("motivo", "")
            or bool(b.get("degradado"))
            or (b.get("puerto") not in (None, 8080)))


def _resumir(res: dict) -> None:
    celdas = res["celdas"]
    infra = {(c["tarea"], c["rep"]) for c in celdas if _es_infra(c)}
    vr = {(c["tarea"], c["rep"]): bool(c.get("estricto"))
          for c in celdas if c["brazo"] == "replay"}
    vc = {(c["tarea"], c["rep"]): bool(c.get("estricto"))
          for c in celdas if c["brazo"] == "crudo"}
    comunes = sorted((set(vr) & set(vc)) - infra)
    gana_l = [k for k in comunes if vr[k] and not vc[k]]
    gana_c = [k for k in comunes if vc[k] and not vr[k]]
    neto = len(gana_l) - len(gana_c)

    # secundaria: neto por contrato ORIGINAL solo (comparabilidad con el GAP)
    vr_o = {(c["tarea"], c["rep"]): bool(c.get("aprobado_orig"))
            for c in celdas if c["brazo"] == "replay"}
    vc_o = {(c["tarea"], c["rep"]): bool(c.get("aprobado_orig"))
            for c in celdas if c["brazo"] == "crudo"}
    neto_orig = (sum(1 for k in comunes if vr_o[k] and not vc_o[k])
                 - sum(1 for k in comunes if vc_o[k] and not vr_o[k]))

    # secundaria: concordancia del replay con el gate (denominador: filas con
    # estricto_gate conocido; leer la ASIMETRIA direccional, deriva ~20pts/12h)
    conc = [(bool(c.get("estricto")), c["estricto_gate"])
            for c in celdas
            if c["brazo"] == "replay" and not _es_infra(c)
            and c.get("estricto_gate") is not None]
    n_conc = sum(1 for a, b in conc if a == b)
    gate_si_replay_no = sum(1 for a, b in conc if b and not a)
    gate_no_replay_si = sum(1 for a, b in conc if a and not b)

    validas = [c for c in celdas if not _es_infra(c)]
    ap = {b: sum(1 for c in validas if c["brazo"] == b and c.get("estricto"))
          for b in BRAZOS}
    n = {b: sum(1 for c in validas if c["brazo"] == b) for b in BRAZOS}
    sin_html = {b: sum(1 for c in validas
                       if c["brazo"] == b and c.get("motivo") == "sin HTML")
                for b in BRAZOS}
    sin_resp = {b: sum(1 for c in validas
                       if c["brazo"] == b
                       and c.get("motivo") == "sin respuesta (server sano)")
                for b in BRAZOS}
    colgados = {b: sum(1 for c in validas
                       if c["brazo"] == b
                       and c.get("motivo") == "juez colgado (JS bloqueante)")
                for b in BRAZOS}
    n_infra = {b: sum(1 for c in celdas if c["brazo"] == b and _es_infra(c))
               for b in BRAZOS}
    por_tarea = {}
    for tarea in sorted({c["tarea"] for c in celdas}):
        gl = sum(1 for t, r in gana_l if t == tarea)
        gc = sum(1 for t, r in gana_c if t == tarea)
        por_tarea[tarea] = f"L+{gl}/C+{gc}"

    print(f"\n{'=' * 70}")
    print(f"  FORK texto-vs-flujo ({len(comunes)} pares validos): "
          f"replay {ap['replay']}/{n['replay']}  "
          f"crudo {ap['crudo']}/{n['crudo']} (estricto)")
    print(f"  gana replay: {len(gana_l)} "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_l) or '—'})")
    print(f"  gana crudo:  {len(gana_c)} "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_c) or '—'})")
    print(f"  NETO L-C: {neto}   (prereg 1a enmienda: >=0 flujo; -1 prioriza "
          f"flujo; -2/-3 SIN VEREDICTO -> extension a 8 replicas; <=-4 el "
          f"TEXTO roba si C gana en >=2 tareas; >=+3 sorpresa)")
    print(f"  por tarea: {por_tarea}")
    print(f"  neto por contrato original solo: {neto_orig} "
          f"(rama distinta que el estricto => gris)")
    print(f"  concordancia replay-gate: {n_conc}/{len(conc)} "
          f"(gate-si->replay-no: {gate_si_replay_no}, "
          f"inversa: {gate_no_replay_si})")
    print(f"  sin_html: {sin_html}  sin_respuesta: {sin_resp}  "
          f"juez_colgado: {colgados}  infra: {n_infra}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "pares": len(comunes), "neto": neto,
        "replay": f"{ap['replay']}/{n['replay']}",
        "crudo": f"{ap['crudo']}/{n['crudo']}",
        "gana_replay": [f"{t}:r{r}" for t, r in gana_l],
        "gana_crudo": [f"{t}:r{r}" for t, r in gana_c],
        "neto_por_tarea": por_tarea,
        "neto_original_solo": neto_orig,
        "concordancia_replay_gate": f"{n_conc}/{len(conc)}",
        "conc_gate_si_replay_no": gate_si_replay_no,
        "conc_gate_no_replay_si": gate_no_replay_si,
        "sin_html": sin_html, "sin_respuesta_server_sano": sin_resp,
        "juez_colgado": colgados, "infra_por_brazo": n_infra,
        "pares_infra_excluidos": sorted(f"{t}:r{r}" for t, r in infra)}


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

    # el replay es del TEXTO: nada de constructor aparte ni re-captura; y si
    # :8080 muere, detectar_backend caeria a Ollama (VIVO en esta maquina) —
    # se neutraliza el modelo para que degrade RUIDOSO (404 -> None) y el
    # puerto 11434 registrado marque infra.
    os.environ.pop("COGNIA_CONSTRUCTOR_URL", None)
    os.environ.pop("COGNIA_DUMP_PROMPTS", None)
    os.environ.pop("COGNIA_IDEA_PELADA", None)
    os.environ.pop("COGNIA_PROMPT_FIX2", None)
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-SONDA-LAZO"
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-SONDA-LAZO"
    from cognia import backend_activo, llm_local
    from cognia.program_creator.generator import _SISTEMA_WEB

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    if solo_tarea:
        tareas = [t for t in tareas if t["id"] == solo_tarea]
        if not tareas:
            sys.exit(f"ABORTO: --tarea {solo_tarea} no existe en el banco")
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    material = _materia_prima()

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if solo_resumen:
        if not fichero_res.is_file():
            sys.exit(f"no existe {fichero_res}")
        res = json.loads(fichero_res.read_text(encoding="utf-8"))
        _resumir(res)
        return 0
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    hechas = {(c["tarea"], c["brazo"], c["rep"]) for c in res["celdas"]}

    _verificar_backend()
    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    commits = (res.get("config") or {}).get("commits") or []
    if commit not in commits:
        commits.append(commit)
    res["config"] = {
        "brazos": BRAZOS, "replicas": replicas, "commit": commit,
        "commits": commits, "gate_origen": str(GATE),
        "backend": backend_activo.estado(),
        "presupuesto_celda_s": presupuesto_celda(),
        "timeout_gen_s": TIMEOUT_GEN,
        "ollama_neutralizado": "NO-EXISTE-SONDA-LAZO",
        "nota": "ambos brazos por llm_local.generar con los args exactos del "
                "lazo (system=_SISTEMA_WEB, max_tokens=12000, effort=None); "
                "replay = prompt capturado integro, rep_gate=((r-1)%6)+1, "
                "s=((r-1+i_tarea)%4)+1; crudo = idea pelada; timeout 400 "
                "(desviacion declarada del 120 de la captura)"}
    print(f"SONDA DEL LAZO fase 1 — replay vs crudo, INTERCALADO\n"
          f"config: replicas={replicas}, commit={commit}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    def _generar_con_backend(texto: str, temp: float):
        """Corre dentro del presupuesto; captura el backend en el mismo hilo
        (un hilo huerfano posterior no puede pisarlo)."""
        crudo = llm_local.generar(
            texto, system=_SISTEMA_WEB, temperature=temp,
            max_tokens=12000, via="sonda_lazo", timeout=TIMEOUT_GEN)
        return crudo, backend_activo.ultimo()

    degradados_seguidos = 0
    for rep in range(1, replicas + 1):
        for i_t, t in enumerate(tareas):
            orden = BRAZOS if (rep + i_t) % 2 == 0 else BRAZOS[::-1]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} {brazo:<7} ...", flush=True)
                t0 = time.time()
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep}
                if brazo == "replay":
                    rep_gate = ((rep - 1) % 6) + 1
                    s_idx = (rep - 1 + i_t) % 4
                    fila = material[(t["id"], rep_gate)][s_idx]
                    texto, temp = fila["prompt"], fila["temperature"]
                    celda.update(rep_gate=rep_gate, s_origen=fila["s"],
                                 estricto_gate=fila["estricto_gate"])
                else:
                    texto, temp = t["idea"], 0.2
                como, crudo, backend = brazo, None, None
                try:
                    crudo, backend = con_presupuesto(
                        presupuesto_celda(), _generar_con_backend, texto, temp)
                except PresupuestoAgotado as exc:
                    como = f"EXCEPCION presupuesto: {exc}"[:80]
                except Exception as exc:
                    como = f"EXCEPCION {exc}"[:80]
                html = _parsear(crudo) if crudo else None
                # Volcado PASIVO de la respuesta CRUDA (3a enmienda): permite
                # re-correr el PARSE DEL LAZO (fence estricto, <html>,
                # truncado->regenerar) sobre estas mismas respuestas SIN GPU
                # si el fork manda la fase 2 al flujo. No altera lo medido.
                if crudo:
                    (d / "respuesta_cruda.txt").write_text(crudo,
                                                           encoding="utf-8")
                celda.update(segundos=round(time.time() - t0, 1),
                             como=str(como)[:90],
                             crudo_chars=len(crudo) if crudo else 0,
                             backend=backend if backend is not None
                             else backend_activo.ultimo())
                if not html:
                    # 1a enmienda: la espiral ("" o respuesta perdida con
                    # server sano) es reprobado LEGITIMO; infra solo si el
                    # server esta caido/degradado de verdad.
                    celda.update(estricto=False, aprobado_orig=False)
                    if "EXCEPCION" in str(como):
                        celda["motivo"] = "excepcion"
                    elif crudo is None and not _salud_backend():
                        celda["motivo"] = "backend caido"
                        celda["backend"] = {"degradado": True,
                                            "detalle": "health post-fallo KO"}
                    elif crudo is None:
                        celda["motivo"] = "sin respuesta (server sano)"
                    else:
                        celda["motivo"] = "sin HTML"
                else:
                    (d / "index.html").write_text(html, encoding="utf-8")

                    def _juzgar_ambos(ruta, contrato, contrato_h):
                        v = juez_ejecutable.juzgar_web(ruta, contrato)
                        vh = juez_ejecutable.juzgar_web(ruta, contrato_h)
                        return v, vh

                    try:
                        v, vh = con_presupuesto(
                            PRESUPUESTO_JUEZ, _juzgar_ambos,
                            d / "index.html", t["contrato"], heldout[t["id"]])
                        celda.update(
                            aprobado_orig=v.aprobado,
                            checks_ok=sum(1 for c in v.checks if c.ok),
                            checks=len(v.checks),
                            aprobado_heldout=vh.aprobado,
                            estricto=v.aprobado and vh.aprobado,
                            motivo=(v.motivo if not v.aprobado
                                    else vh.motivo or "")[:100])
                    except PresupuestoAgotado:
                        # el hilo huerfano deja SU chromium clavado a 100% de
                        # un core hasta el fin del proceso: coste declarado
                        celda.update(estricto=False, aprobado_orig=False,
                                     motivo="juez colgado (JS bloqueante)")
                    except Exception as exc:
                        celda.update(estricto=False, aprobado_orig=False,
                                     motivo=f"juez crasheo: {exc}"[:100])
                res["celdas"].append(celda)
                _guardar()
                if _es_infra(celda):
                    degradados_seguidos += 1
                    if degradados_seguidos >= MAX_DEGRADADOS_SEGUIDOS:
                        print(f"ABORTO: {degradados_seguidos} celdas infra "
                              f"seguidas — backend muerto; el parcial esta "
                              f"guardado, reanuda con --reanudar", flush=True)
                        _resumir(res)
                        _guardar()
                        return 2
                else:
                    degradados_seguidos = 0
                print(f"       -> {'ESTRICTO-OK' if celda.get('estricto') else 'FALLIDO'}"
                      f" (orig={celda.get('aprobado_orig')}, "
                      f"held={celda.get('aprobado_heldout', '—')}, "
                      f"{celda['segundos']:.0f}s, {celda.get('motivo', '')[:40]})",
                      flush=True)

    _resumir(res)
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
