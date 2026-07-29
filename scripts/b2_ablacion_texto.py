"""
b2_ablacion_texto.py — FASE 2 de la sonda del ladrón: ablación del troceo
REQUIRED. PREREG_ABLACION_TEXTO_20260729.md: leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ablacion_texto.py
        [--replicas 6] [--reanudar] [--sufijo x] [--solo-resumen]
        [--tarea id] [--verificar-cirugia]

Brazos apareados sobre el MISMO prompt capturado (los 24 de fase 1):
L = replay íntegro (ancla concurrente) vs L−REQ = el mismo prompt sin las
líneas `- REQUIRED component N:` ni `- Implement EVERY required...`.
Cirugía determinista por regex de línea (--verificar-cirugia la audita sin
GPU). Todo lo demás = fase 1: generar directo, juez estricto con
presupuesto, clasificación de la 1ª enmienda, crudos guardados.
"""

from __future__ import annotations

import json
import os
import re
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
          / "b2_ablacion_texto")
BRAZOS = ["lsinreq", "replay"]
URL_BACKEND = "http://127.0.0.1:8080"
CTX_MINIMO = 16384
TIMEOUT_GEN = 400
PRESUPUESTO_JUEZ = 300
MAX_DEGRADADOS_SEGUIDOS = 4

RE_REQ = re.compile(r"^- REQUIRED component \d+: ")
RE_IMPL = re.compile(r"^- Implement EVERY required component above")


def _sin_required(texto: str) -> tuple[str, int]:
    """Quita el bloque del troceo; devuelve (texto, líneas eliminadas)."""
    lineas = texto.split("\n")
    fuera = [l for l in lineas if not (RE_REQ.match(l) or RE_IMPL.match(l))]
    return "\n".join(fuera), len(lineas) - len(fuera)


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
    modelo = str(props.get("model_path") or "")
    if "gpt-oss" not in modelo.lower():
        sys.exit(f"ABORTO: :8080 sirve {modelo or '?'} (se exige gpt-oss)")
    print(f"  backend OK: slots=1, n_ctx={ctx}", flush=True)


def _materia_fresca(dir_materia: Path, ids_tarea: list) -> dict:
    """(tarea, rep) -> fila {prompt, temperature, s}, desde un prompts.jsonl
    capturado por COGNIA_DUMP_PROMPTS en una corrida del LAZO (sonda de la
    discrepancia). Solo entran los prompts CON troceo (brazo OFF: contienen
    '- REQUIRED component'); la tarea se atribuye por palabra clave del
    enunciado y se exige atribución única."""
    CLAVES = {"carrito_stock": "carrito", "kanban": "kanban",
              "hoja_calculo": "hoja", "buscaminas": "buscaminas"}
    lineas = [json.loads(l) for l in
              (dir_materia / "prompts.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
    lineas = [p for p in lineas if p.get("lenguaje") == "html"
              and "- REQUIRED component" in p["prompt"]]
    material: dict = {}
    conteo: dict = {}
    for p in lineas:
        # cortar ANTES del brief: un brief fresco que diga "hoja de..." en
        # el carrito daria atribucion ambigua espuria (revision)
        cab = p["prompt"].split("TARGET LOOK")[0][:900].lower()
        tareas_hit = [t for t, k in CLAVES.items() if k in cab]
        if len(tareas_hit) != 1:
            sys.exit(f"ABORTO: prompt con atribución ambigua ({tareas_hit})")
        tid = tareas_hit[0]
        if tid not in ids_tarea:
            continue
        conteo[tid] = conteo.get(tid, 0) + 1
        material[(tid, conteo[tid])] = {
            "prompt": p["prompt"], "temperature": float(p["temperature"]),
            "s": conteo[tid]}
    print(f"  materia fresca: {sum(conteo.values())} prompts OFF "
          f"({conteo})", flush=True)
    if sum(conteo.values()) < 8:
        sys.exit("ABORTO: materia fresca insuficiente (<8 prompts OFF)")
    return material


def _materia_prima() -> dict:
    res = json.loads((GATE / "resultados.json").read_text(encoding="utf-8"))
    lineas = [json.loads(l) for l in
              (GATE / "prompts" / "prompts.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lineas) != 4 * len(res["ensayos"]):
        sys.exit("ABORTO: prompts no alinean 4-por-ensayo")
    material: dict = {}
    i = 0
    for e in res["ensayos"]:
        filas = []
        for s in range(1, 5):
            p = lineas[i]
            i += 1
            filas.append({"prompt": p["prompt"],
                          "temperature": float(p["temperature"]), "s": s})
        material[(e["tarea"], int(e["rep"]))] = filas
    return material


def _parsear(crudo: str) -> str | None:
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
    va = {(c["tarea"], c["rep"]): bool(c.get("estricto"))
          for c in celdas if c["brazo"] == "lsinreq"}
    vl = {(c["tarea"], c["rep"]): bool(c.get("estricto"))
          for c in celdas if c["brazo"] == "replay"}
    comunes = sorted((set(va) & set(vl)) - infra)
    gana_a = [k for k in comunes if va[k] and not vl[k]]
    gana_l = [k for k in comunes if vl[k] and not va[k]]
    neto = len(gana_a) - len(gana_l)

    va_o = {(c["tarea"], c["rep"]): bool(c.get("aprobado_orig"))
            for c in celdas if c["brazo"] == "lsinreq"}
    vl_o = {(c["tarea"], c["rep"]): bool(c.get("aprobado_orig"))
            for c in celdas if c["brazo"] == "replay"}
    neto_orig = (sum(1 for k in comunes if va_o[k] and not vl_o[k])
                 - sum(1 for k in comunes if vl_o[k] and not va_o[k]))

    validas = [c for c in celdas if not _es_infra(c)]
    ap = {b: sum(1 for c in validas if c["brazo"] == b and c.get("estricto"))
          for b in BRAZOS}
    n = {b: sum(1 for c in validas if c["brazo"] == b) for b in BRAZOS}
    sin_html = {b: sum(1 for c in validas
                       if c["brazo"] == b and c.get("motivo") == "sin HTML")
                for b in BRAZOS}
    colgados = {b: sum(1 for c in validas if c["brazo"] == b
                       and c.get("motivo") == "juez colgado (JS bloqueante)")
                for b in BRAZOS}
    n_infra = {b: sum(1 for c in celdas if c["brazo"] == b and _es_infra(c))
               for b in BRAZOS}
    por_tarea = {}
    for tarea in sorted({c["tarea"] for c in celdas}):
        ga = sum(1 for t, r in gana_a if t == tarea)
        gl = sum(1 for t, r in gana_l if t == tarea)
        por_tarea[tarea] = f"sinREQ+{ga}/L+{gl}"

    print(f"\n{'=' * 70}")
    print(f"  ABLACION TROCEO ({len(comunes)} pares validos): "
          f"L-REQ {ap['lsinreq']}/{n['lsinreq']}  "
          f"L {ap['replay']}/{n['replay']} (estricto)")
    print(f"  gana L-REQ: {len(gana_a)} "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_a) or '—'})")
    print(f"  gana L:     {len(gana_l)} "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_l) or '—'})")
    print(f"  NETO (L-REQ)-L: {neto}   (prereg: >=+4 troceo ladron principal "
          f"[y >=2 tareas]; +2/+3 contribuye; -1..+1 NO es el grueso; "
          f"<=-2 la checklist ayuda)")
    print(f"  por tarea: {por_tarea}")
    print(f"  neto original solo: {neto_orig} (rama distinta => GRIS)")
    print(f"  sin_html: {sin_html}  juez_colgado: {colgados}  "
          f"infra: {n_infra}")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "pares": len(comunes), "neto": neto,
        "lsinreq": f"{ap['lsinreq']}/{n['lsinreq']}",
        "replay": f"{ap['replay']}/{n['replay']}",
        "gana_lsinreq": [f"{t}:r{r}" for t, r in gana_a],
        "gana_replay": [f"{t}:r{r}" for t, r in gana_l],
        "neto_por_tarea": por_tarea, "neto_original_solo": neto_orig,
        "sin_html": sin_html, "juez_colgado": colgados,
        "infra_por_brazo": n_infra,
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
    verificar_cirugia = "--verificar-cirugia" in argv
    solo_tarea = (argv[argv.index("--tarea") + 1]
                  if "--tarea" in argv else None)
    # --materia <dir>: sonda de la DISCREPANCIA (PREREG_DISCREPANCIA_TROCEO)
    # — la materia prima son prompts FRESCOS capturados del lazo, uno por
    # (tarea, rep), en vez de los 24 del gate.
    materia_dir = (Path(argv[argv.index("--materia") + 1])
                   if "--materia" in argv else None)
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])

    os.environ.pop("COGNIA_CONSTRUCTOR_URL", None)
    os.environ.pop("COGNIA_DUMP_PROMPTS", None)
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-ABLACION"
    from cognia.program_creator import generator as _generator
    _generator.OLLAMA_MODEL = "NO-EXISTE-ABLACION"
    from cognia import backend_activo, llm_local
    from cognia.program_creator.generator import _SISTEMA_WEB

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    if solo_tarea:
        tareas = [t for t in tareas if t["id"] == solo_tarea]
        if not tareas:
            sys.exit(f"ABORTO: --tarea {solo_tarea} no existe")
    heldout = {t["id"]: t["contrato"] for t in
               json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    ids_tarea = [t["id"] for t in tareas]
    if materia_dir is not None:
        material = _materia_fresca(materia_dir, ids_tarea)
        if not material:
            sys.exit("ABORTO: la materia fresca quedó vacía")
    else:
        material = _materia_prima()

    if verificar_cirugia:
        # auditar la cirugía sobre los prompts que la corrida usará
        malos = 0
        for rep in range(1, replicas + 1):
            for i_t, tid in enumerate(ids_tarea):
                if materia_dir is not None:
                    if (tid, rep) not in material:
                        continue
                    fila = material[(tid, rep)]
                else:
                    rep_gate = ((rep - 1) % 6) + 1
                    fila = material[(tid, rep_gate)][(rep - 1 + i_t) % 4]
                cortado, n_fuera = _sin_required(fila["prompt"])
                # chequeo NO tautológico (revisión): conteo esperado, cero
                # residuo del bloque, y cabecera (idea+brief) intacta.
                # En el gate el conteo es 11 exacto (96/96); en material
                # FRESCO los briefs cortos dan 6-10 componentes (2ª
                # revisión): esperado = líneas RE_REQ del original + 1.
                a = fila["prompt"].split("\n")
                esperado = (11 if materia_dir is None else
                            sum(1 for l in a if RE_REQ.match(l)) + 1)
                residuo = any("REQUIRED component" in l
                              or "Implement EVERY" in l
                              for l in cortado.split("\n"))
                ok = (n_fuera == esperado and n_fuera >= 3 and not residuo
                      and cortado.split("\n")[2] == a[2])
                malos += not ok
                print(f"  {tid:<14} r{rep} s{fila['s']}: -{n_fuera} lineas "
                      f"{'OK' if ok else 'MAL'}")
        print(f"\nCIRUGIA: {'OK 24/24' if malos == 0 else f'{malos} MAL'}")
        return 0 if malos == 0 else 1

    SALIDA.mkdir(parents=True, exist_ok=True)
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
        "commits": commits, "backend": backend_activo.estado(),
        "timeout_gen_s": TIMEOUT_GEN,
        "materia": str(materia_dir) if materia_dir else "gate_v2",
        "nota": "fase 2 del fork (neto -7): L vs L-sin-troceo-REQUIRED, "
                "apareados sobre el MISMO prompt capturado"}
    print(f"ABLACION TROCEO — L-REQ vs L, INTERCALADO\n"
          f"config: replicas={replicas}, commit={commit}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    def _generar_con_backend(texto: str, temp: float):
        crudo = llm_local.generar(
            texto, system=_SISTEMA_WEB, temperature=temp,
            max_tokens=12000, via="ablacion_texto", timeout=TIMEOUT_GEN)
        return crudo, backend_activo.ultimo()

    degradados_seguidos = 0
    for rep in range(1, replicas + 1):
        for i_t, t in enumerate(tareas):
            if materia_dir is not None:
                if (t["id"], rep) not in material:
                    continue
                fila = material[(t["id"], rep)]
                rep_gate = rep
            else:
                rep_gate = ((rep - 1) % 6) + 1
                fila = material[(t["id"], rep_gate)][(rep - 1 + i_t) % 4]
            orden = BRAZOS if (rep + i_t) % 2 == 0 else BRAZOS[::-1]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} {brazo:<8} ...", flush=True)
                t0 = time.time()
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep,
                         "rep_gate": rep_gate, "s_origen": fila["s"]}
                if brazo == "lsinreq":
                    texto, n_fuera = _sin_required(fila["prompt"])
                    celda["lineas_cortadas"] = n_fuera
                else:
                    texto = fila["prompt"]
                celda["prompt_chars"] = len(texto)
                temp = fila["temperature"]
                como, crudo, backend = brazo, None, None
                try:
                    crudo, backend = con_presupuesto(
                        presupuesto_celda(), _generar_con_backend, texto, temp)
                except PresupuestoAgotado as exc:
                    como = f"EXCEPCION presupuesto: {exc}"[:80]
                except Exception as exc:
                    como = f"EXCEPCION {exc}"[:80]
                html = _parsear(crudo) if crudo else None
                if crudo:
                    (d / "respuesta_cruda.txt").write_text(crudo,
                                                           encoding="utf-8")
                celda.update(segundos=round(time.time() - t0, 1),
                             como=str(como)[:90],
                             crudo_chars=len(crudo) if crudo else 0,
                             backend=backend if backend is not None
                             else backend_activo.ultimo())
                if not html:
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
                        print("ABORTO: infra seguida — parcial guardado",
                              flush=True)
                        _resumir(res)
                        _guardar()
                        return 2
                else:
                    degradados_seguidos = 0
                print(f"       -> {'ESTRICTO-OK' if celda.get('estricto') else 'FALLIDO'}"
                      f" ({celda['segundos']:.0f}s, "
                      f"{celda.get('motivo', '')[:40]})", flush=True)

    _resumir(res)
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
