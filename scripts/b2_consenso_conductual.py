"""
b2_consenso_conductual.py — ¿la MAYORÍA conductual entre las muestras del
BoN es señal, sin ningún contrato? PREREG_CONSENSO_CONDUCTUAL_20260730.md:
leerlo ANTES. Cero generación de páginas.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_consenso_conductual.py
        [--solo-sondeo] [--reanudar] [--sufijo x] [--solo-resumen]

Fase 1 (GPU liviana): una secuencia de acciones POR TAREA, generada desde
el ENUNCIADO (sin ver ninguna página, sin inventario de DOM) y congelada.
Fase 2 (sin GPU): esa secuencia se ejecuta en las 96 muestras congeladas
de b2_bon_heldout; la FIRMA conductual de cada muestra es la tupla de
estados observados; dentro de cada ensayo gana el grupo de firmas más
grande (desempate: s menor). El resultado del elegido es su `estricto`
CONGELADO. No hay aserciones, ni contratos, ni LLM decidiendo.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
FUENTE = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_bon_heldout")
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_consenso_conductual")
URL_BACKEND = "http://127.0.0.1:8080"
MAX_PASOS = 8
MAX_ACCIONES_EFECTIVAS = 30
ACCIONES = {"click", "escribir", "tecla", "esperar"}

_PROMPT_SONDEO = """\
Vas a escribir una SECUENCIA DE PRUEBA para este producto. NO escribas
aserciones ni valores esperados: solo QUE HACER y QUE MIRAR.

IDEA PEDIDA: {idea}

La secuencia se ejecutara sobre VARIAS implementaciones distintas de esta
misma idea, asi que usa UNICAMENTE los selectores que el enunciado declara
obligatorios (los que toda implementacion correcta debe tener). No inventes
clases ni ids que el enunciado no nombre.

Escribe hasta {max_pasos} pasos que ejerciten las reglas centrales del
enunciado (estado inicial, interacciones, topes, acumulacion) y declara que
selectores OBSERVAR: su estado se capturara tras CADA paso.

Acciones disponibles (solo estas):
  {{"accion":"click","selector":".x","indice":0,"veces":1}}
  {{"accion":"escribir","selector":"#x","texto":"..."}}
  {{"accion":"tecla","key":"ArrowRight","veces":1}}
  {{"accion":"esperar","ms":400}}

"veces" repite la accion: una regla de tope o de acumulacion necesita
llegar al tope, no un solo click.

Responde SOLO este JSON:
{{"pasos": [ ... ], "observar": [".sel", "#id"]}}
"""

# La firma tiene que ser CONDUCTUAL, no de markup. La revisión midió que
# la versión literal agrupaba por formato de moneda ("€0.00" vs "0,00 €") y
# por el nombre de las tarjetas ("Tarea 1" vs "t1") — dos muestras con
# veredicto OPUESTO colisionaban y dos correctas se separaban. Normalización:
#   numérico (tras quitar moneda y unificar , y .)  -> el número canónico
#   texto corto (<=10 chars: "perdiste", "CIRC", "8") -> minúsculas sin espacios
#   texto largo (nombres, descripciones)             -> "T"  (colapsa el ruido)
# Y se observan hasta 25 elementos (con 6, las celdas discriminantes de un
# buscaminas 5x5 quedaban FUERA de la ventana: firma idéntica en las 4).
_JS_SNAPSHOT = """(sel) => {
  const canon = (t) => {
    const s = String(t).trim();
    if (s === '') return '';
    const num = s.replace(/[€$\\s]/g, '').replace(/\\.(?=\\d{3}\\b)/g, '')
                 .replace(',', '.');
    if (/^-?\\d+(\\.\\d+)?$/.test(num)) return String(parseFloat(num));
    const c = s.toLowerCase().replace(/\\s+/g, ' ').trim();
    return c.length <= 10 ? c : 'T';
  };
  const els = [...document.querySelectorAll(sel)];
  return {n: els.length,
          v: els.slice(0, 25).map(e => {
            if (e.matches('input[type=checkbox],input[type=radio]'))
              return e.checked ? 'C' : 'U';
            return canon(e.matches('input,textarea,select')
               ? e.value : (e.innerText || ''));
          }),
          d: els.slice(0, 25).map(e =>
            (e.disabled || e.hasAttribute('disabled') ? 'D' : '-'))};
}"""


def _verificar_backend() -> None:
    try:
        with urllib.request.urlopen(URL_BACKEND + "/props", timeout=10) as r:
            props = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        sys.exit(f"ABORTO: {URL_BACKEND}/props no responde ({exc})")
    if props.get("total_slots") != 1:
        sys.exit(f"ABORTO: total_slots={props.get('total_slots')}")


def _pasos_validos(c) -> tuple[list, list]:
    if not isinstance(c, dict):
        return [], []
    pasos, efectivas = [], 0
    for p in (c.get("pasos") or []):
        if not isinstance(p, dict):
            continue
        if (p.get("accion") or "").strip() not in ACCIONES:
            continue
        try:
            v = max(1, min(int(p.get("veces", 1)), 12))
        except (TypeError, ValueError):
            v = 1
        if efectivas + v > MAX_ACCIONES_EFECTIVAS:
            break
        efectivas += v
        p["veces"] = v
        pasos.append(p)
    observar = [o for o in (c.get("observar") or [])
                if isinstance(o, str) and o.strip()][:8]
    return pasos[:MAX_PASOS], observar


def _accion(page, a: dict) -> bool:
    """Ejecuta una acción; True si tuvo efecto ejecutable."""
    acc = (a.get("accion") or "").strip()
    veces = int(a.get("veces", 1))
    hecho = False
    try:
        for _ in range(veces):
            if acc == "click":
                els = page.query_selector_all(a.get("selector", ""))
                i = int(a.get("indice", 0))
                if len(els) <= i:
                    break
                els[i].click(timeout=4000)
                hecho = True
            elif acc == "escribir":
                el = page.query_selector(a.get("selector", ""))
                if el is None:
                    break
                el.fill(str(a.get("texto", "")))
                hecho = True
            elif acc == "tecla":
                page.keyboard.press(a.get("key", "Enter"))
                hecho = True
            elif acc == "esperar":
                page.wait_for_timeout(min(int(a.get("ms", 400)), 3000))
                continue
            page.wait_for_timeout(350)
    except Exception:
        pass
    return hecho


def _firma(html: Path, pasos: list, observar: list) -> tuple:
    """Ejecuta la secuencia y devuelve (firma, n_acciones_efectivas)."""
    from playwright.sync_api import sync_playwright
    from cognia.program_creator.juez_ejecutable import (MS_ASENTAR,
                                                        MS_TIMEOUT_CARGA)
    estados, efectivas = [], 0
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(html.resolve().as_uri(), wait_until="load",
                      timeout=MS_TIMEOUT_CARGA)
            page.wait_for_timeout(MS_ASENTAR)
        except Exception as exc:
            nav.close()
            return (f"NO_CARGA:{type(exc).__name__}",), 0

        def _snap():
            fila = []
            for sel in observar:
                try:
                    fila.append(page.evaluate(_JS_SNAPSHOT, sel))
                except Exception:
                    fila.append({"err": 1})
            return json.dumps(fila, ensure_ascii=False, sort_keys=True)

        estados.append(_snap())                 # estado inicial
        hechos = []
        for a in pasos:
            h = bool(_accion(page, a))
            hechos.append("1" if h else "0")
            efectivas += h
            estados.append(_snap())
        nav.close()
    # el vector de acciones que ATERRIZARON entra en la firma: sin él, una
    # muestra que ejecutó 4 de 8 pasos y otra que ejecutó los 8 podían
    # quedar en el mismo grupo (medido por la revisión en kanban:r3)
    estados.append("acciones:" + "".join(hechos))
    return tuple(estados), efectivas


def _resumir(res: dict) -> None:
    ensayos = res["ensayos"]
    validos = [e for e in ensayos if e.get("elegida_s") and e.get("control")
               is not None]
    gana = [e for e in validos if e["estricto_elegida"]
            and not e["control"]]
    pierde = [e for e in validos if e["control"]
              and not e["estricto_elegida"]]
    neto = len(gana) - len(pierde)
    sin_mayoria = [e for e in validos if e["tam_mayoria"] == 1]
    cofail = [e for e in validos if e.get("mayoria_con_reprobada")]
    # ancla RE-FIJADA (revisión): poder DISCRIMINANTE, no "hubo un click"
    ancla = sum(1 for e in ensayos if e.get("firmas_distintas", 1) >= 2)
    tam_medio = (sum(e["tam_mayoria"] for e in validos) / len(validos)
                 if validos else 0)
    techo = sum(1 for e in validos if e.get("techo"))
    ctrl = sum(1 for e in validos if e["control"])
    eleg = sum(1 for e in validos if e["estricto_elegida"])
    print(f"\n{'=' * 72}")
    print(f"  CONSENSO CONDUCTUAL ({len(validos)} ensayos validos)")
    print(f"    control s1: {ctrl}/{len(validos)} | elegida por mayoria: "
          f"{eleg}/{len(validos)} | techo pass@4: {techo}/{len(validos)}")
    print(f"  NETO: {neto}  (gana {len(gana)}, pierde {len(pierde)})   "
          f"prereg 1a enmienda: >=+4 VIVA; +2/+3 moderada; <=+1 KILL "
          f"(techo de la REGLA: +5 estructural)")
    print(f"  ancla de validez: {ancla}/{len(ensayos)} ensayos con >=2 "
          f"firmas distintas (exige >=18)")
    print(f"  sin mayoria (4 firmas distintas): {len(sin_mayoria)} | "
          f"co-failure (mayoria con reprobada): {len(cofail)} | "
          f"tam. medio del grupo: {tam_medio:.2f}")
    print(f"{'=' * 72}")
    res["resumen"] = {
        "ensayos_validos": len(validos), "neto": neto,
        "control": f"{ctrl}/{len(validos)}",
        "elegida": f"{eleg}/{len(validos)}",
        "techo": f"{techo}/{len(validos)}",
        "gana": [e["ensayo"] for e in gana],
        "pierde": [e["ensayo"] for e in pierde],
        "ancla_firmas_distintas": f"{ancla}/{len(ensayos)}",
        "sin_mayoria": len(sin_mayoria), "co_failure": len(cofail),
        "tam_medio_mayoria": round(tam_medio, 2)}


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()

    solo_sondeo = "--solo-sondeo" in argv
    solo_resumen = "--solo-resumen" in argv
    reanudar = "--reanudar" in argv
    global SALIDA
    if "--sufijo" in argv:
        SALIDA = SALIDA.with_name(
            SALIDA.name + "_" + argv[argv.index("--sufijo") + 1])
    SALIDA.mkdir(parents=True, exist_ok=True)
    # A4: las sondas viven SIEMPRE en el dir base — con --sufijo, buscarlas
    # en el dir nuevo las re-generaba con el LLM y rompía el congelado.
    f_sondas = (RAIZ / "cognia" / "program_creator" / "generated_programs"
                / "b2_consenso_conductual" / "sondas_por_tarea.json")
    f_sondas.parent.mkdir(parents=True, exist_ok=True)
    f_res = SALIDA / "resultados.json"

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]

    # ── FASE 1: la secuencia por tarea (desde el ENUNCIADO, sin páginas) ──
    if not f_sondas.is_file():
        os.environ["OLLAMA_MODEL"] = "NO-EXISTE-CC"
        from cognia import llm_local
        from cognia.program_creator.juez_ejecutable import _json_de_respuesta
        _verificar_backend()
        sondas = {}
        for t in tareas:
            print(f"  sondeo de {t['id']} ...", flush=True)
            crudo = llm_local.generar(
                _PROMPT_SONDEO.format(idea=t["idea"], max_pasos=MAX_PASOS),
                system="Eres un ingeniero de QA. Respondes SOLO con JSON "
                       "valido, sin explicaciones ni fences.",
                temperature=0.2, max_tokens=12000, via="consenso_conductual",
                timeout=400, reasoning_effort="low")
            pasos, observar = _pasos_validos(
                _json_de_respuesta(crudo) if crudo else None)
            sondas[t["id"]] = {"pasos": pasos, "observar": observar,
                               "crudo": (crudo or "")[:6000]}
            print(f"     -> {len(pasos)} pasos, {len(observar)} selectores",
                  flush=True)
        f_sondas.write_text(json.dumps(sondas, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"  sondas CONGELADAS en {f_sondas}", flush=True)
    sondas = json.loads(f_sondas.read_text(encoding="utf-8"))
    if solo_sondeo:
        return 0

    # ── FASE 2: firmas y mayoría sobre las 96 congeladas (sin GPU) ────────
    fuente = json.loads((FUENTE / "resultados.json").read_text(encoding="utf-8"))
    por_ensayo: dict = {}
    for m in fuente["muestras"]:
        por_ensayo.setdefault((m["tarea"], int(m["rep"])), []).append(m)

    if solo_resumen:
        _resumir(json.loads(f_res.read_text(encoding="utf-8")))
        return 0
    res: dict = (json.loads(f_res.read_text(encoding="utf-8"))
                 if reanudar and f_res.is_file() else {"ensayos": []})
    hechos = {e["ensayo"] for e in res["ensayos"]}
    huella_sondas = hashlib.sha1(
        f_sondas.read_bytes()).hexdigest()[:12]          # A5: trazabilidad
    previa = (res.get("config") or {}).get("huella_sondas")
    if previa and previa != huella_sondas:
        sys.exit(f"ABORTO: las sondas cambiaron ({previa} -> "
                 f"{huella_sondas}): no se mezclan corridas")
    res["config"] = {"fuente": str(FUENTE), "sondas": str(f_sondas),
                     "huella_sondas": huella_sondas, "max_pasos": MAX_PASOS}

    # PASO 0 (revisión): reproducibilidad de la FIRMA. Sin esto, un neto ~0
    # no se puede leer — "sin señal" e "instrumento inestable" se confunden.
    if not hechos:
        print("  paso 0: reproducibilidad de la firma ...", flush=True)
        estables = 0
        for (tarea, rep), muestras in sorted(por_ensayo.items())[:3]:
            for m in sorted(muestras, key=lambda x: int(x["s"]))[:2]:
                d = FUENTE / f"{tarea}__r{rep}__s{m['s']}" / "index.html"
                if not d.is_file():
                    continue
                h = {hashlib.sha1(json.dumps(
                        _firma(d, sondas[tarea]["pasos"],
                               sondas[tarea]["observar"])[0],
                        ensure_ascii=False).encode()).hexdigest()[:12]
                     for _ in range(2)}
                estables += len(h) == 1
        res["config"]["firmas_estables"] = estables
        print(f"     -> {estables} muestras con firma estable en 2 corridas",
              flush=True)
        if estables < 4:
            sys.exit("ABORTO: la firma no es reproducible; medir seria "
                     "confundir 'sin señal' con 'instrumento roto'")

    def _guardar():
        tmp = f_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, f_res)

    for (tarea, rep), muestras in sorted(por_ensayo.items()):
        etiqueta = f"{tarea}:r{rep}"
        if etiqueta in hechos:
            continue
        pasos = sondas[tarea]["pasos"]
        observar = sondas[tarea]["observar"]
        t0 = time.time()
        filas, faltantes = [], []
        for m in sorted(muestras, key=lambda x: int(x["s"])):
            d = FUENTE / f"{tarea}__r{rep}__s{m['s']}" / "index.html"
            if not d.is_file():
                faltantes.append(int(m["s"]))     # N2: no en silencio
                continue
            firma, efec = _firma(d, pasos, observar)
            filas.append({
                "s": int(m["s"]),
                "hash": hashlib.sha1(
                    json.dumps(firma, ensure_ascii=False).encode()
                ).hexdigest()[:12],
                "efectivas": efec, "estricto": bool(m.get("estricto"))})
        if not filas:
            continue
        # N5: una muestra que no ejecutó NADA no vota (dos páginas rotas por
        # la misma excepción formarían mayoría con hash idéntico)
        votantes = [f for f in filas if f["efectivas"] > 0] or filas
        grupos = Counter(f["hash"] for f in votantes)
        mejor_hash, tam = grupos.most_common(1)[0]
        empate = sum(1 for h, n in grupos.items() if n == tam) > 1
        if tam == 1 or empate:
            elegida = min(filas, key=lambda f: f["s"])      # = control
        else:
            elegida = min((f for f in votantes if f["hash"] == mejor_hash),
                          key=lambda f: f["s"])
        control = next((f["estricto"] for f in filas if f["s"] == 1), None)
        e = {"ensayo": etiqueta, "tarea": tarea, "rep": rep,
             "elegida_s": elegida["s"],
             "estricto_elegida": elegida["estricto"],
             "control": control,
             "techo": any(f["estricto"] for f in filas),
             "tam_mayoria": tam, "empate": empate,
             "n_muestras": len(filas), "faltantes": faltantes,
             "firmas_distintas": len(grupos),
             "muestras_ejecutadas": sum(1 for f in filas
                                        if f["efectivas"] > 0),
             "mayoria_con_reprobada": any(
                 not f["estricto"] for f in filas
                 if f["hash"] == mejor_hash) if tam > 1 else False,
             "firmas": filas, "segundos": round(time.time() - t0, 1)}
        res["ensayos"].append(e)
        _guardar()
        print(f"  {etiqueta:<20} mayoria={tam}/4 elegida=s{e['elegida_s']} "
              f"({'OK' if e['estricto_elegida'] else 'falla'}) "
              f"ctrl={'OK' if control else 'falla'} "
              f"ejec={e['muestras_ejecutadas']}/4 {e['segundos']:.0f}s",
              flush=True)

    _resumir(res)
    _guardar()
    print(f"\nJSON: {f_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
