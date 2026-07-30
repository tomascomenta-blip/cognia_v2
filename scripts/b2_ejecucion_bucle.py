"""
b2_ejecucion_bucle.py — Señal por EJECUCIÓN EN EL BUCLE, iteración 1.
PREREG_EJECUCION_BUCLE_20260729.md: leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ejecucion_bucle.py
        [--piloto] [--reanudar] [--sufijo x] [--solo-resumen]

Por página: SONDEO (el pensador propone acciones y qué observar, sin
aserciones) → EJECUCIÓN (Playwright corre las sondas y captura snapshots
antes/después) → JUICIO (el pensador dictamina lo observado contra el
ENUNCIADO). Veredicto del marco (regla del harness): REPRUEBA ⇔ ≥1 sonda
INCORRECTO. Control CONCURRENTE: contrato ciego clásico re-generado e
intercalado por página. Corpus: las 24 páginas de b2_sonda_prompt con
veredicto del banco (las de b2_ab_contrato). El pensador nunca ve contrato
original, held-out ni código.
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
SONDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_sonda_prompt")
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_ejecucion_bucle")
URL_BACKEND = "http://127.0.0.1:8080"
CTX_MINIMO = 16384
MAX_SONDAS = 6
MAX_ACCIONES_POR_SONDA = 25     # a 400ms/accion, sondas patologicas comen pared
MAX_ACCIONES_EFECTIVAS = 30     # tope tras expandir `veces` (it.2)
# tope del transcript en chars, cortado por SONDAS ENTERAS (la revision cazo
# que 16000 chars + max_tokens 12000 desbordaban ctx 16384 en silencio y el
# fallo golpeaba justo a las paginas complejas)
MAX_TRANSCRIPT = 9000
ACCIONES_SONDA = {"click", "escribir", "tecla", "esperar"}

_PROMPT_SONDEO = """\
Vas a PROBAR este producto interactuando con el. NO escribas aserciones ni
valores esperados: solo QUE HACER y QUE MIRAR.

IDEA PEDIDA: {idea}

SELECTORES QUE EXISTEN EN LA PAGINA (inventario del DOM, con cuantos hay):
{inventario}

Escribe hasta {max_sondas} SONDAS. Cada sonda ejercita UNA regla de la idea
con una secuencia de acciones y declara que selectores OBSERVAR (su estado
se capturara ANTES y DESPUES de las acciones). Cubre el estado inicial, las
interacciones que la idea exige, lo que NO debe pasar (topes, estados que
no retroceden) y las reglas de HISTORIA (secuencias largas, 6+ acciones).

IMPORTANTE: cada sonda parte de la pagina RECIEN CARGADA — ninguna hereda
el estado que dejo la anterior. Una regla que necesite historia (acumular,
deshacer, llegar a un tope) va ENTERA dentro de UNA sonda con todas sus
acciones encadenadas.

Acciones disponibles (solo estas):
  {{"accion":"click","selector":".x","indice":0,"veces":1}}
  {{"accion":"escribir","selector":"#x","texto":"..."}}
  {{"accion":"tecla","key":"ArrowRight","veces":1}}
  {{"accion":"esperar","ms":500}}

"veces" (opcional, por defecto 1) REPITE la accion. Una regla de tope o
de acumulacion NO se prueba con un solo click: si la regla dice "al
llegar a 2 unidades el boton se deshabilita", la sonda tiene que hacer
click las veces necesarias para LLEGAR al tope y una mas para probar que
no pasa de ahi.

"escribir" deja el campo enfocado: si el producto reacciona al salir del
campo, añade despues {{"accion":"tecla","key":"Tab"}}.

Responde SOLO este JSON (una linea por sonda):
{{"sondas": [{{"nombre":"que regla ejercita","acciones":[...],"observar":[".sel","#id"]}}, ...]}}
"""

_PROMPT_JUICIO = """\
Eres un QA que YA ejecuto sus pruebas sobre el producto. Dictamina SOLO con
lo observado y el enunciado.

IDEA PEDIDA: {idea}

LO OBSERVADO (por sonda: acciones ejecutadas y estado de los selectores
observados ANTES -> DESPUES; "n" = cuantos elementos hay, "muestra" = texto
visible o value de los primeros, "estado" = disabled/clases/data de los
primeros). CADA SONDA partio de la pagina RECIEN CARGADA: el estado NO
persiste de una sonda a la siguiente — no leas el "antes" de una sonda
como continuacion de la anterior:
{transcript}

Por CADA sonda, un dictamen:
- "INCORRECTO" SOLO si lo observado VIOLA una regla explicita del enunciado.
  Cita en "por_que" la regla violada y el dato observado que la viola.
- "CORRECTO" si lo observado cumple lo que el enunciado exige de esa regla.
- "NO_CONCLUYENTE" si lo observado no alcanza para decidir.

PROHIBIDO acusar por estetica, por formato que el enunciado no dicta, o por
expectativas que el enunciado no escribe. PROHIBIDO suponer comportamiento
no observado. Una accion fallida ("no hay elemento...") sobre un selector
que la idea EXIGE es evidencia real; una marcada "[selector NO consta en el
inventario...]" es un invento de la sonda: NO_CONCLUYENTE.

OBLIGATORIO — antes de escribir INCORRECTO, comprueba que las ACCIONES
EJECUTADAS de esa sonda ejercitan de verdad la regla que vas a citar. Si
la regla habla de llegar a un tope o de acumular y la sonda solo hizo UNA
accion, la evidencia NO cubre la regla: el dictamen es NO_CONCLUYENTE, no
INCORRECTO. Acusar al producto por algo que la prueba no ejercito es un
error TUYO, no un fallo del producto.

Responde SOLO este JSON:
{{"dictamenes": [{{"sonda":1,"dictamen":"CORRECTO|INCORRECTO|NO_CONCLUYENTE","por_que":"..."}}, ...]}}
"""

_JS_SNAPSHOT = """(sel) => {
  const els = [...document.querySelectorAll(sel)];
  return {n: els.length,
          muestra: els.slice(0, 5).map(e => {
            if (e.matches('input[type=checkbox],input[type=radio]'))
              return e.checked ? 'checked' : 'unchecked';
            return (e.matches('input,textarea,select')
               ? String(e.value) : (e.innerText || '').trim()).slice(0, 60);
          }),
          // C1 (it.2): el estado que las reglas exigen comprobar vive en
          // atributos y clases, no en el texto. La it.1 "verifico" un
          // boton deshabilitado leyendo su TEXTO (que no cambia) y fallo
          // el 100% de esas sondas.
          estado: els.slice(0, 5).map(e => ({
            disabled: !!(e.disabled || e.hasAttribute('disabled')),
            clases: (e.className || '').toString().slice(0, 60),
            data: Object.fromEntries(
              Object.entries(e.dataset || {}).slice(0, 6))}))};
}"""


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
        sys.exit(f"ABORTO: :8080 sirve {modelo or '?'} — este prereg mide a "
                 f"gpt-oss-20b (identidad del pensador, no solo salud)")
    print(f"  backend OK: slots=1, n_ctx={ctx}, modelo={Path(modelo).name}",
          flush=True)


def _sondas_validas(c) -> list:
    """Filtra a la forma ejecutable; una sonda sin acciones válidas se cae."""
    if not isinstance(c, dict) or not isinstance(c.get("sondas"), list):
        return []
    limpias = []
    for s in c["sondas"][:MAX_SONDAS]:
        if not isinstance(s, dict):
            continue
        acciones = [a for a in (s.get("acciones") or [])
                    if isinstance(a, dict)
                    and (a.get("accion") or "").strip() in ACCIONES_SONDA
                    ][:MAX_ACCIONES_POR_SONDA]
        # C2 (it.2): `veces` expande acciones — se acota el TOTAL efectivo
        # para que una sonda patologica no coma el presupuesto de pared
        # (a 400 ms por accion, 30 son ~12 s de interaccion).
        efectivas, recorte = 0, []
        for a in acciones:
            v = _veces(a)
            if efectivas + v > MAX_ACCIONES_EFECTIVAS:
                break
            efectivas += v
            recorte.append(a)
        acciones = recorte
        observar = [o for o in (s.get("observar") or [])
                    if isinstance(o, str) and o.strip()][:8]
        if acciones and observar:
            limpias.append({"nombre": str(s.get("nombre", ""))[:120],
                            "acciones": acciones, "observar": observar})
    return limpias


def _ejecutar_sondas(html: Path, sondas: list,
                     inv_selectores: set | None = None) -> list:
    """Corre las sondas sobre la página real; devuelve transcript por sonda.

    inv_selectores: selectores del inventario del DOM — las acciones sobre un
    selector que NO consta se anotan (observación del instrumento, sin fuga:
    el juicio necesita distinguir "feature ausente" de "la sonda lo inventó").
    """
    from playwright.sync_api import sync_playwright
    from cognia.program_creator.juez_ejecutable import (MS_ASENTAR,
                                                        MS_TIMEOUT_CARGA)
    resultado = []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_page(viewport={"width": 1280, "height": 900})
        errores_js: list = []
        page.on("pageerror", lambda e: errores_js.append(str(e)[:120]))
        for i, s in enumerate(sondas, 1):
            fila = {"sonda": i, "nombre": s["nombre"], "acciones_ok": [],
                    "observado": {}}
            n_err_pre = len(errores_js)      # ANTES del goto: los errores de
            try:                             # CARGA también son evidencia
                # página FRESCA por sonda: cada una mide desde el estado
                # inicial, como los pasos de un contrato tras la recarga
                page.goto(html.as_uri(), wait_until="load",
                          timeout=MS_TIMEOUT_CARGA)
                page.wait_for_timeout(MS_ASENTAR)
            except Exception as exc:
                fila["error"] = f"no carga: {exc}"[:100]
                resultado.append(fila)
                continue
            antes = {}
            for sel in s["observar"]:
                try:
                    antes[sel] = page.evaluate(_JS_SNAPSHOT, sel)
                except Exception as exc:
                    antes[sel] = {"error": str(exc)[:60]}
            for a in s["acciones"]:
                det = _accion(page, a)
                sel_a = a.get("selector")
                if (inv_selectores is not None and sel_a
                        and ("no hay elemento" in det
                             or "no existe" in det)
                        and sel_a not in inv_selectores):
                    det += " [selector NO consta en el inventario del DOM: " \
                           "puede ser invento de la sonda]"
                fila["acciones_ok"].append(det)
            page.wait_for_timeout(400)
            despues = {}
            for sel in s["observar"]:
                try:
                    despues[sel] = page.evaluate(_JS_SNAPSHOT, sel)
                except Exception as exc:
                    despues[sel] = {"error": str(exc)[:60]}
            fila["observado"] = {sel: {"antes": antes.get(sel),
                                       "despues": despues.get(sel)}
                                 for sel in s["observar"]}
            fila["errores_js_nuevos"] = errores_js[n_err_pre:][:3]
            resultado.append(fila)
        nav.close()
    return resultado


def _veces(a: dict) -> int:
    """C2 (it.2): repeticiones declaradas por la sonda, acotadas."""
    try:
        return max(1, min(int(a.get("veces", 1)), 12))
    except (TypeError, ValueError):
        return 1


def _accion(page, a: dict) -> str:
    acc = (a.get("accion") or "").strip()
    n_veces = _veces(a)
    suf = f" x{n_veces}" if n_veces > 1 else ""
    try:
        if acc == "click":
            sel = a.get("selector", "")
            i = int(a.get("indice", 0))
            hechos = 0
            for _ in range(n_veces):
                elems = page.query_selector_all(sel)     # el DOM cambia
                if len(elems) <= i:
                    if hechos == 0:
                        return (f"click '{sel}'[{i}]{suf}: no hay elemento "
                                f"(hay {len(elems)})")
                    break
                elems[i].click(timeout=5000)
                page.wait_for_timeout(400)
                hechos += 1
            return (f"click '{sel}'[{i}]{suf}: OK"
                    if hechos == n_veces else
                    f"click '{sel}'[{i}]{suf}: solo {hechos} de {n_veces} "
                    f"(el elemento dejo de estar disponible)")
        if acc == "escribir":
            sel = a.get("selector", "")
            el = page.query_selector(sel)
            if el is None:
                return f"escribir '{sel}': no existe el campo"
            el.fill(str(a.get("texto", "")))
            page.wait_for_timeout(400)
            return f"escribir {str(a.get('texto', ''))[:30]!r} en '{sel}': OK"
        if acc == "tecla":
            for _ in range(n_veces):
                page.keyboard.press(a.get("key", "Enter"))
                page.wait_for_timeout(400)
            return f"tecla {a.get('key')}{suf}: OK"
        if acc == "esperar":
            page.wait_for_timeout(min(int(a.get("ms", 500)), 5000))
            return f"esperar {a.get('ms', 500)}ms: OK"
        return f"accion desconocida {acc!r}"
    except Exception as exc:
        return f"{acc}: excepcion {type(exc).__name__}: {str(exc)[:60]}"


def _render_transcript(ejec: list) -> str:
    partes = []
    for fila in ejec:
        partes.append(f"SONDA {fila['sonda']}: {fila['nombre']}")
        if fila.get("error"):
            partes.append(f"  ERROR: {fila['error']}")
            continue
        for det in fila["acciones_ok"]:
            partes.append(f"  accion: {det}")
        for sel, od in fila["observado"].items():
            # el bloque `estado` solo se imprime cuando APORTA (algun
            # disabled, alguna clase, algun data): si no, infla el
            # transcript sin decir nada
            def _compacto(snap):
                if not isinstance(snap, dict):
                    return snap
                est = snap.get("estado") or []
                util = any(e.get("disabled") or e.get("clases")
                           or e.get("data") for e in est
                           if isinstance(e, dict))
                return snap if util else {k: v for k, v in snap.items()
                                          if k != "estado"}
            partes.append(
                f"  observar {sel!r}: "
                f"{json.dumps(_compacto(od.get('antes')), ensure_ascii=False)}"
                f" -> "
                f"{json.dumps(_compacto(od.get('despues')), ensure_ascii=False)}")
        if fila.get("errores_js_nuevos"):
            partes.append(f"  errores JS durante la sonda: "
                          f"{fila['errores_js_nuevos']}")
    return "\n".join(partes)


def _dictamenes_validos(c, n_sondas: int) -> list | None:
    if not isinstance(c, dict) or not isinstance(c.get("dictamenes"), list):
        return None
    por_sonda: dict = {}
    for d in c["dictamenes"]:
        if not isinstance(d, dict):
            continue
        v = str(d.get("dictamen", "")).strip().upper()
        if v not in ("CORRECTO", "INCORRECTO", "NO_CONCLUYENTE"):
            continue
        try:
            i = int(d.get("sonda", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= i <= n_sondas:
            # duplicados: el ULTIMO gana (dedupe; sin sesgo a REPRUEBA)
            por_sonda[i] = {"sonda": i, "dictamen": v,
                            "por_que": str(d.get("por_que", ""))[:200]}
    return sorted(por_sonda.values(), key=lambda d: d["sonda"]) or None


def _marco_por_pagina(idea: str, pagina: Path, llm_gen) -> dict:
    """SONDEO -> EJECUCIÓN -> JUICIO. Devuelve la fila completa (auditable)."""
    from cognia.program_creator.juez_ejecutable import (_json_de_respuesta,
                                                        inventario_dom)
    fila: dict = {}
    t0 = time.time()
    inv = inventario_dom(pagina)
    clases = sorted(inv.get("clases", {}).items(), key=lambda kv: -kv[1])[:25]
    texto_inv = "\n".join(f"  {sel}  x{n}" for sel, n in clases)
    texto_inv += "\n" + "\n".join(f"  {i}" for i in inv.get("ids", [])[:20])

    crudo_s = llm_gen(_PROMPT_SONDEO.format(
        idea=idea, inventario=texto_inv, max_sondas=MAX_SONDAS))
    fila["sondeo_crudo"] = (crudo_s or "")[:8000]
    sondas = _sondas_validas(_json_de_respuesta(crudo_s) if crudo_s else None)
    fila["n_sondas"] = len(sondas)
    if not sondas:
        fila.update(veredicto_marco=None, motivo="sin sondas ejecutables",
                    segundos=round(time.time() - t0, 1))
        return fila

    inv_sel = set(dict(clases)) | set(inv.get("ids", []))
    ejec = _ejecutar_sondas(pagina, sondas, inv_sel)
    fila["ejecucion"] = ejec

    def _observa_algo(f):
        # criterio real de "ejecutada": algún selector observado SIN error y
        # con elementos (n>0) antes o después — {"n":0} y {"error":...} no
        # cuentan (la revisión cazó que el any() sobre dicts truthy era vacuo)
        return any(
            (od.get(k) or {}).get("n", 0) > 0
            for od in f.get("observado", {}).values() if isinstance(od, dict)
            for k in ("antes", "despues")
            if isinstance(od.get(k), dict) and "error" not in od[k])

    ejecutadas = [f for f in ejec if not f.get("error") and _observa_algo(f)]
    fila["n_ejecutadas"] = len(ejecutadas)
    if not ejecutadas:
        fila.update(veredicto_marco=None, motivo="ninguna sonda ejecutada",
                    segundos=round(time.time() - t0, 1))
        return fila

    # transcript acotado por SONDAS ENTERAS (cortar por chars dejaba a las
    # sondas finales sin dictamen con sesgo a APRUEBA en páginas grandes)
    bloques, total = [], 0
    for f in ejec:
        b = _render_transcript([f])
        if total + len(b) > MAX_TRANSCRIPT and bloques:
            bloques.append(f"(sondas {f['sonda']}+ omitidas por tamaño)")
            break
        bloques.append(b)
        total += len(b)
    transcript = "\n".join(bloques)
    fila["transcript_chars"] = len(transcript)
    crudo_j = llm_gen(_PROMPT_JUICIO.format(idea=idea, transcript=transcript))
    fila["juicio_crudo"] = (crudo_j or "")[:8000]
    dict_ok = _dictamenes_validos(
        _json_de_respuesta(crudo_j) if crudo_j else None, len(sondas))
    if not dict_ok:
        fila.update(veredicto_marco=None, motivo="juicio no parseable",
                    segundos=round(time.time() - t0, 1))
        return fila
    fila["dictamenes"] = dict_ok
    n_inc = sum(1 for d in dict_ok if d["dictamen"] == "INCORRECTO")
    n_cor = sum(1 for d in dict_ok if d["dictamen"] == "CORRECTO")
    if n_inc == 0 and n_cor == 0:
        # juez que se abstiene en todo: no es un APRUEBA (la revisión cazó
        # que la abstención total puntuaría 19/24 gratis)
        fila.update(veredicto_marco=None, motivo="juicio no concluyente",
                    segundos=round(time.time() - t0, 1))
        return fila
    # regla del harness pre-registrada: REPRUEBA <=> >=1 INCORRECTO
    fila["veredicto_marco"] = n_inc == 0
    fila["segundos"] = round(time.time() - t0, 1)
    return fila


def _resumir(res: dict) -> None:
    filas = res["filas"]
    con_v = [f for f in filas if f.get("veredicto_marco") is not None]
    sin_v = [f for f in filas if f.get("veredicto_marco") is None]
    ac_m = sum(1 for f in con_v if f["veredicto_marco"] == f["banco"])
    fn_m = sum(1 for f in con_v if not f["veredicto_marco"] and f["banco"])
    fp_m = sum(1 for f in con_v if f["veredicto_marco"] and not f["banco"])
    n_ap = sum(1 for f in con_v if f["banco"])
    n_re = sum(1 for f in con_v if not f["banco"])
    compl = sum(1 for f in con_v if not f["banco"] and f["veredicto_marco"])

    ctrl = [f for f in filas if f.get("ctrl_veredicto") is not None]
    ac_c = sum(1 for f in ctrl if f["ctrl_veredicto"] == f["banco"])
    fn_c = sum(1 for f in ctrl if not f["ctrl_veredicto"] and f["banco"])
    fp_c = sum(1 for f in ctrl if f["ctrl_veredicto"] and not f["banco"])

    print(f"\n{'=' * 70}")
    print(f"  EJECUCION EN EL BUCLE it.1 — {len(filas)} paginas, "
          f"{len(con_v)} con veredicto del marco, {len(sin_v)} sin")
    print(f"  MARCO:   aciertos {ac_m}/{len(con_v)}  FN {fn_m}/{n_ap}  "
          f"FP {fp_m}/{n_re}  complacencia {compl}/{n_re}")
    print(f"  CONTROL: aciertos {ac_c}/{len(ctrl)}  FN {fn_c}  FP {fp_c} "
          f"(ciego clasico concurrente; rango historico 6-12/24)")
    print(f"  (prereg: VIVA >=16/24 y FP<=1/5; GRIS 12-15; KILL <=11; "
          f"sin_veredicto >4/24 => direccional)")
    print(f"{'=' * 70}")
    res["resumen"] = {
        "paginas": len(filas), "con_veredicto": len(con_v),
        "sin_veredicto": [f["pagina"] for f in sin_v],
        "marco_aciertos": ac_m, "marco_fn": f"{fn_m}/{n_ap}",
        "marco_fp": f"{fp_m}/{n_re}", "complacencia": f"{compl}/{n_re}",
        "control_aciertos": f"{ac_c}/{len(ctrl)}",
        "control_fn": fn_c, "control_fp": fp_c}


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable
    from cognia.presupuesto_pared import (PresupuestoAgotado, con_presupuesto,
                                          presupuesto_celda)

    piloto = "--piloto" in argv
    reanudar = "--reanudar" in argv
    solo_resumen = "--solo-resumen" in argv
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])

    os.environ.pop("COGNIA_CONSTRUCTOR_URL", None)
    os.environ["OLLAMA_MODEL"] = "NO-EXISTE-EJEC-BUCLE"
    from cognia import backend_activo, llm_local

    ideas = {t["id"]: t["idea"]
             for t in json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    sonda = json.loads((SONDA / "resultados.json").read_text(encoding="utf-8"))
    paginas = []
    for c in sonda["celdas"]:
        if c["brazo"] not in ("crudo", "full") or "aprobado" not in c:
            continue
        d = SONDA / f"{c['tarea']}__{c['brazo']}__r{c['rep']}"
        if (d / "index.html").is_file():
            paginas.append({"tarea": c["tarea"], "pagina": d.name,
                            "dir": d, "banco": bool(c["aprobado"])})
    if piloto:
        # el plan del piloto QA: segundas de cada tarea + terceras de hoja y
        # carrito (las primeras se quemaron en humos previos)
        plan = []
        for tid in sorted(ideas):
            de_t = sorted((p for p in paginas if p["tarea"] == tid),
                          key=lambda p: p["pagina"])
            if len(de_t) > 1:
                plan.append(de_t[1])
        for tid in ("hoja_calculo", "carrito_stock"):
            de_t = sorted((p for p in paginas if p["tarea"] == tid),
                          key=lambda p: p["pagina"])
            if len(de_t) > 2:
                plan.append(de_t[2])
        plan = plan[:6]
        # el plan lleva SIEMPRE >=2 páginas REPROBADAS (la revisión cazó que
        # con <2, un marco PERFECTO daría veredicto idéntico en todas las
        # aprobadas => falso KILL por "degenerado")
        en_plan = {p["pagina"] for p in plan}
        reprobadas_fuera = sorted(
            (p for p in paginas
             if not p["banco"] and p["pagina"] not in en_plan),
            key=lambda p: p["pagina"])
        faltan = 2 - sum(1 for p in plan if not p["banco"])
        plan.extend(reprobadas_fuera[:max(0, faltan)])
        paginas = plan
    if not paginas:
        sys.exit("no hay páginas del corpus en disco")

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
                 if reanudar and fichero_res.is_file() else {"filas": []})
    hechas = {f["pagina"] for f in res["filas"]}

    _verificar_backend()
    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    res["config"] = {
        "piloto": piloto, "commit": commit, "n_paginas": len(paginas),
        "backend": backend_activo.estado(),
        "nota": "marco = sondear-observar-juzgar (effort=low, temp 0.2, "
                "max_tokens 12000); control = contrato ciego clasico "
                "concurrente intercalado; REPRUEBA <=> >=1 INCORRECTO"}

    def _llm(prompt: str):
        return llm_local.generar(
            prompt, system="Eres un ingeniero de QA meticuloso. Respondes "
                           "SOLO con JSON valido, sin explicaciones ni "
                           "fences.",
            temperature=0.2, max_tokens=12000, via="ejecucion_bucle",
            timeout=400, reasoning_effort="low")

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    print(f"EJECUCION EN EL BUCLE it.1 — {len(paginas)} paginas "
          f"({'PILOTO' if piloto else 'bloque'}), commit={commit}, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    for i, p in enumerate(paginas):
        if p["pagina"] in hechas:
            continue
        print(f"  {p['pagina']:<36} banco={'AP' if p['banco'] else 'RE'} ...",
              flush=True)
        fila = {"tarea": p["tarea"], "pagina": p["pagina"],
                "banco": p["banco"]}
        idea = ideas[p["tarea"]]
        html = p["dir"] / "index.html"
        # intercalado marco/control con orden rotado por página
        orden = ("marco", "ctrl") if i % 2 == 0 else ("ctrl", "marco")
        for brazo in orden:
            try:
                if brazo == "marco":
                    fila.update(con_presupuesto(
                        presupuesto_celda(), _marco_por_pagina,
                        idea, html, _llm))
                else:
                    t0 = time.time()

                    def _ctrl():
                        c = juez_ejecutable.generar_contrato(idea, html,
                                                             modo="clasico")
                        if c is None:
                            return None, None
                        return c, juez_ejecutable.juzgar_web(html, c)

                    c, v = con_presupuesto(presupuesto_celda(), _ctrl)
                    if c is None:
                        # convención M3 del gate (QA-fuerte): sin contrato
                        # usable = REPRUEBA (None queda para infra)
                        fila.update(ctrl_veredicto=False,
                                    ctrl_motivo="sin contrato usable (M3)")
                    else:
                        fila.update(ctrl_veredicto=bool(v.aprobado),
                                    ctrl_pasos=len(c.get("pasos", [])))
                    fila["ctrl_segundos"] = round(time.time() - t0, 1)
            except PresupuestoAgotado:
                fila.update(**({"veredicto_marco": None,
                                "motivo": "presupuesto agotado"}
                               if brazo == "marco"
                               else {"ctrl_veredicto": None,
                                     "ctrl_motivo": "presupuesto agotado"}))
            except Exception as exc:
                err = f"EXCEPCION {type(exc).__name__}: {str(exc)[:80]}"
                fila.update(**({"veredicto_marco": None, "motivo": err}
                               if brazo == "marco"
                               else {"ctrl_veredicto": None,
                                     "ctrl_motivo": err}))
        fila["backend"] = backend_activo.ultimo()
        res["filas"].append(fila)
        _guardar()
        vm = fila.get("veredicto_marco")
        print(f"       -> marco={'AP' if vm else 'RE' if vm is not None else 'SIN'}"
              f" ({fila.get('n_sondas', 0)} sondas, "
              f"{fila.get('n_ejecutadas', 0)} ejec) "
              f"ctrl={'AP' if fila.get('ctrl_veredicto') else 'RE' if fila.get('ctrl_veredicto') is not None else 'SIN'}",
              flush=True)

    if piloto:
        n_plan = len(paginas)
        con_v = [f for f in res["filas"]
                 if f.get("veredicto_marco") is not None]
        ejecutables = sum(1 for f in res["filas"]
                          if f.get("n_ejecutadas", 0) >= 1)
        veredictos = {f["veredicto_marco"] for f in con_v}
        # con 2 reprobadas en el plan, un marco perfecto NO es "degenerado"
        degenerado = (len(con_v) >= n_plan - 1 and len(veredictos) == 1)
        # un marco que casi siempre se ABSTIENE tampoco sirve (sin esto, el
        # todo-NO_CONCLUYENTE pasaba el piloto y moria recien en el bloque)
        kill = ejecutables < 4 or degenerado or len(con_v) < 4
        res["piloto"] = {"n_plan": n_plan, "ejecutables": ejecutables,
                         "degenerado": degenerado,
                         "veredicto": ("KILL DE APTITUD" if kill
                                       else "SIGUE (bloque completo)")}
        print(f"\nPILOTO: {ejecutables}/{n_plan} con sondas ejecutadas, "
              f"degenerado={degenerado} -> {res['piloto']['veredicto']}",
              flush=True)
    _resumir(res)
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
