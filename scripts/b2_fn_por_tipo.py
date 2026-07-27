"""
b2_fn_por_tipo.py — ¿QUÉ tipo de paso del contrato autogenerado acusa a
páginas sanas? PREREG_SENAL_CONTRATO_20260727.md (con su PRIMERA ENMIENDA):
leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_fn_por_tipo.py
        [--reanudar]

Cero GPU: (1) re-juzga cada página con su contrato del BANCO (juzgar_web
completo, como la sonda) para re-medir la verdad de suelo — las celdas cuyo
veredicto no se reproduce se excluyen de los denominadores; (2) re-ejecuta
los 48 contratos YA GUARDADOS sub-acción por sub-acción con la misma
semántica que juzgar_web (un paso compuesto corta en su primer fallo; el
paso siguiente corre igual), y además ejecuta las aserciones posteriores al
fallo en modo observación (post_fallo, fuera del veredicto — las
interacciones NO, para no tocar el estado). La tabla PRIMARIA es la de
PRIMERA CULPA (una observación por página×modo); la incondicionada es
descriptiva. Tablas por modo y agregadas; la regla de entrada al fix lee
SOLO la partición clásico.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cognia.program_creator.juez_ejecutable import (  # noqa: E402
    MS_ASENTAR, MS_TIMEOUT_CARGA, _ejecutar_paso, juzgar_web)

SONDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_sonda_prompt")
AB = (RAIZ / "cognia" / "program_creator" / "generated_programs"
      / "b2_ab_contrato")
TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
SALIDA = SONDA / "fn_por_tipo.json"
MODOS = ["clasico", "amplio"]

INTERACCIONES = {"click", "tecla", "escribir", "esperar"}
ASERCIONES = {"contar", "contar_visible", "texto", "existe", "no_existe", "js"}
RE_ESCRITURA = re.compile(r"ingres|escrib|tipe|teclea|introduc|rellen|llen",
                          re.IGNORECASE)


def _comparador(sub: dict) -> str:
    """Cómo compara la sub-acción: la dimensión de H3."""
    if sub.get("accion") in INTERACCIONES:
        return "-"
    if "esperado" in sub:
        return ("exacto-str" if isinstance(sub["esperado"], str)
                else "exacto-num")
    if "min" in sub or "max" in sub:
        return "min/max"
    if "contiene" in sub:
        return "contiene"
    if sub.get("accion") == "js":
        return "truthy"
    return "existencia"


def _subacciones(paso: dict) -> list:
    """Aplana la forma anidada; un paso simple es su única sub-acción."""
    if isinstance(paso.get("acciones"), list):
        return [s for s in paso["acciones"] if isinstance(s, dict)]
    return [paso]


def _es_input(tag) -> bool:
    return bool(tag) and (tag.split("[")[0] in ("INPUT", "TEXTAREA", "SELECT")
                          or "[ce]" in tag)


def _tipo(sub: dict) -> str:
    t = sub["accion"]
    if t in ("texto", "contar_visible") and _es_input(sub.get("tag")):
        t += "@input"
    return f"{t}/{sub['comparador']}" if sub["comparador"] != "-" else t


def main(argv: list) -> int:
    reanudar = "--reanudar" in argv
    from playwright.sync_api import sync_playwright

    sonda = json.loads((SONDA / "resultados.json").read_text(encoding="utf-8"))
    banco_contratos = {t["id"]: t["contrato"] for t in
                       json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    paginas = []
    for c in sonda["celdas"]:
        if c["brazo"] not in ("crudo", "full") or "aprobado" not in c:
            continue
        d = SONDA / f"{c['tarea']}__{c['brazo']}__r{c['rep']}"
        if (d / "index.html").is_file():
            paginas.append({"tarea": c["tarea"], "brazo": c["brazo"],
                            "rep": c["rep"], "dir": d,
                            "banco": bool(c["aprobado"])})
    esperadas = sum(1 for p in paginas for m in MODOS
                    if (p["dir"] / f"contrato_{m}.json").is_file())
    print(f"FN POR TIPO — {len(paginas)} páginas ({esperadas} contratos); "
          f"banco aprueba {sum(1 for p in paginas if p['banco'])}", flush=True)

    res: dict = (json.loads(SALIDA.read_text(encoding="utf-8"))
                 if reanudar and SALIDA.is_file()
                 else {"filas": [], "banco_replay": {}})
    hechas = {(f["tarea"], f["brazo"], f["rep"], f["modo"])
              for f in res["filas"]}

    def _guardar():
        tmp = SALIDA.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, SALIDA)

    # ── fase 1: re-medir la verdad de suelo (contrato del BANCO) ─────────
    for pag in paginas:
        clave = f"{pag['tarea']}__{pag['brazo']}__r{pag['rep']}"
        if clave in res["banco_replay"]:
            continue
        v = juzgar_web(pag["dir"] / "index.html",
                       banco_contratos[pag["tarea"]])
        res["banco_replay"][clave] = {"aprobado": bool(v.aprobado),
                                      "guardado": pag["banco"]}
        _guardar()
        marca = "==" if bool(v.aprobado) == pag["banco"] else "≠≠ DISCORDA"
        print(f"  banco {clave:<28} replay "
              f"{'APRUEBA' if v.aprobado else 'reprueba'} vs guardado "
              f"{'APRUEBA' if pag['banco'] else 'reprueba'}  {marca}",
              flush=True)

    inestables = {k for k, v in res["banco_replay"].items()
                  if v["aprobado"] != v["guardado"]}

    # ── fase 2: replay de los contratos generados, sub a sub ─────────────
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        for pag in paginas:
            contratos = {}
            for modo in MODOS:
                f = pag["dir"] / f"contrato_{modo}.json"
                clave = (pag["tarea"], pag["brazo"], pag["rep"], modo)
                if not f.is_file() or clave in hechas:
                    continue
                try:
                    contratos[modo] = json.loads(f.read_text(encoding="utf-8"))
                except Exception as exc:
                    res["filas"].append({
                        "tarea": pag["tarea"], "brazo": pag["brazo"],
                        "rep": pag["rep"], "modo": modo,
                        "banco": pag["banco"], "error": f"ilegible: {exc}"[:80],
                        "pasos": [], "aprobado_replay": None})
                    _guardar()
            if not contratos:
                continue

            uri = (pag["dir"] / "index.html").resolve().as_uri()
            # tag real de cada selector usado (H2), sobre el DOM inicial
            # (aproximación declarada: elementos post-interacción → None)
            tags = {}
            try:
                page = nav.new_page(viewport={"width": 1280, "height": 900})
                page.goto(uri, wait_until="load", timeout=MS_TIMEOUT_CARGA)
                page.wait_for_timeout(MS_ASENTAR)
                selectores = {s.get("selector") for c in contratos.values()
                              for paso in c.get("pasos", [])
                              for s in _subacciones(paso) if s.get("selector")}
                for sel in selectores:
                    try:
                        tags[sel] = page.evaluate(
                            "(s) => { const el = document.querySelector(s); "
                            "return el ? el.tagName + "
                            "(el.isContentEditable ? '[ce]' : '') : null }",
                            sel)
                    except Exception:
                        tags[sel] = "SELECTOR_INVALIDO"
                page.close()
            except Exception as exc:
                for modo in contratos:
                    res["filas"].append({
                        "tarea": pag["tarea"], "brazo": pag["brazo"],
                        "rep": pag["rep"], "modo": modo,
                        "banco": pag["banco"],
                        "error": f"carga_fallida: {exc}"[:80],
                        "pasos": [], "aprobado_replay": None})
                _guardar()
                continue

            for modo, contrato in contratos.items():
                fila = {"tarea": pag["tarea"], "brazo": pag["brazo"],
                        "rep": pag["rep"], "modo": modo,
                        "banco": pag["banco"], "pasos": []}
                t0 = time.time()
                page = nav.new_page(viewport={"width": 1280, "height": 900})
                try:
                    page.goto(uri, wait_until="load",
                              timeout=MS_TIMEOUT_CARGA)
                    page.wait_for_timeout(MS_ASENTAR)
                except Exception as exc:
                    fila.update(error=f"carga_fallida: {exc}"[:80],
                                aprobado_replay=None)
                    res["filas"].append(fila)
                    _guardar()
                    page.close()
                    continue
                traza: list = []
                for i, paso in enumerate(contrato.get("pasos", [])):
                    reg = {"i": i, "nombre": paso.get("nombre", ""),
                           "critico": bool(paso.get("critico")),
                           "quiere_escribir": bool(RE_ESCRITURA.search(
                               paso.get("nombre", "") or "")),
                           "subs": []}
                    fallo = False
                    for j, sub in enumerate(_subacciones(paso)):
                        accion = (sub.get("accion") or "?").strip()
                        if fallo and accion not in ASERCIONES:
                            reg["subs"].append({
                                "j": j, "accion": accion,
                                "comparador": _comparador(sub),
                                "selector": sub.get("selector", ""),
                                "tag": tags.get(sub.get("selector", "")),
                                "ok": None, "post_fallo": True,
                                "detalle": "interaccion omitida tras fallo"})
                            continue
                        chk = _ejecutar_paso(
                            page, {**sub, "nombre": f"p{i}.{j}",
                                   "critico": False}, traza)
                        reg["subs"].append({
                            "j": j, "accion": accion,
                            "comparador": _comparador(sub),
                            "selector": sub.get("selector", ""),
                            "tag": tags.get(sub.get("selector", "")),
                            "ok": bool(chk.ok), "post_fallo": fallo,
                            "detalle": chk.detalle[:120]})
                        if not chk.ok and not fallo:
                            fallo = True    # misma semántica que juzgar_web:
                            # el paso ya falló; lo que sigue es observación
                    reg["ok"] = not fallo
                    fila["pasos"].append(reg)
                fila["n_criticos"] = sum(
                    1 for r in fila["pasos"] if r["critico"])
                fila["aprobado_replay"] = all(
                    r["ok"] for r in fila["pasos"] if r["critico"])
                fila["usa_escribir"] = any(
                    s["accion"] == "escribir"
                    for r in fila["pasos"] for s in r["subs"])
                fila["segundos"] = round(time.time() - t0, 1)
                res["filas"].append(fila)
                _guardar()
                print(f"  {pag['tarea']:<14} {pag['brazo']:<6} r{pag['rep']} "
                      f"{modo:<8} replay "
                      f"{'APRUEBA' if fila['aprobado_replay'] else 'reprueba'}"
                      f"  banco {'APRUEBA' if pag['banco'] else 'reprueba'}"
                      f"  ({len(fila['pasos'])} pasos, "
                      f"{fila['n_criticos']} críticos, "
                      f"{fila['segundos']}s)", flush=True)
                page.close()
        nav.close()

    # ── sanidad ANTES de las tablas (orden del prereg enmendado) ─────────
    print(f"\n{'=' * 78}\nSANIDAD")
    n_err = sum(1 for f in res["filas"] if f.get("error"))
    print(f"  celdas esperadas {esperadas}, procesadas {len(res['filas'])} "
          f"(con error: {n_err})")
    print(f"  banco replay: concordantes "
          f"{len(res['banco_replay']) - len(inestables)}/"
          f"{len(res['banco_replay'])}; INESTABLES (se excluyen): "
          f"{sorted(inestables) if inestables else 'ninguna'}")

    concordancia = None
    discordantes = []
    ab_res = AB / "resultados.json"
    if ab_res.is_file():
        manana = {(f["tarea"], f["brazo"], f["rep"], f["modo"]): f["interno"]
                  for f in json.loads(ab_res.read_text(
                      encoding="utf-8"))["filas"]
                  if f.get("interno") is not None}
        pares = [(f, manana[(f["tarea"], f["brazo"], f["rep"], f["modo"])])
                 for f in res["filas"] if not f.get("error")
                 and (f["tarea"], f["brazo"], f["rep"], f["modo"]) in manana]
        discordantes = [
            f"{f['tarea']}__{f['brazo']}__r{f['rep']}/{f['modo']}"
            for f, m in pares if f["aprobado_replay"] != m]
        concordancia = (len(pares) - len(discordantes), len(pares))
        print(f"  replay vs juzgado de la mañana: {concordancia[0]}/"
              f"{concordancia[1]} concuerdan"
              + (f"; DISCORDANTES: {discordantes}" if discordantes else ""))
        if len(discordantes) > 3:
            print("  ¡GATE!: >3 discordantes — investigar los pares antes de "
                  "leer las tablas (el replay omite universales; una "
                  "discrepancia por esa vía no es carrera de animaciones)")

    # ── agregación ───────────────────────────────────────────────────────
    filas_ok = [f for f in res["filas"] if not f.get("error")
                and f"{f['tarea']}__{f['brazo']}__r{f['rep']}"
                not in inestables]

    def _tablas(filas: list, titulo: str):
        stats: dict = {}
        primera: dict = {}
        for fila in filas:
            subs_planos = [s for r in fila["pasos"] for s in r["subs"]]
            for sub in subs_planos:
                if sub["ok"] is None or sub["post_fallo"]:
                    continue
                s = stats.setdefault(_tipo(sub), {
                    "sanas_n": 0, "sanas_falla": 0,
                    "rotas_n": 0, "rotas_ok": 0})
                if fila["banco"]:
                    s["sanas_n"] += 1
                    s["sanas_falla"] += 0 if sub["ok"] else 1
                else:
                    s["rotas_n"] += 1
                    s["rotas_ok"] += 1 if sub["ok"] else 0
            if fila["banco"]:
                for r in fila["pasos"]:
                    culpa = next((s for s in r["subs"]
                                  if s["ok"] is False and not s["post_fallo"]),
                                 None)
                    if culpa:
                        p = primera.setdefault(_tipo(culpa), [])
                        p.append({
                            "celda": f"{fila['tarea']}__{fila['brazo']}__"
                                     f"r{fila['rep']}/{fila['modo']}",
                            "paso": r["nombre"][:60],
                            "quiere_escribir": r["quiere_escribir"],
                            "usa_escribir": fila.get("usa_escribir", False),
                            "detalle": culpa["detalle"]})
                        break
        print(f"\n── {titulo} ──")
        print(f"{'PRIMERA CULPA (1 por celda sana)':<34}{'celdas':>7}"
              f"  de_escritura")
        for clave, casos in sorted(primera.items(),
                                   key=lambda kv: -len(kv[1])):
            esc = sum(1 for c in casos
                      if c["quiere_escribir"] and not c["usa_escribir"])
            print(f"  {clave:<32}{len(casos):>7}{esc:>10}")
        print(f"{'DESCRIPTIVA (sub-acciones)':<30}{'FN falla/sanas':>16}"
              f"{'%':>6}{'FP ok/rotas':>13}{'%':>6}")
        for clave, s in sorted(stats.items(),
                               key=lambda kv: -(kv[1]["sanas_falla"] /
                                                max(1, kv[1]["sanas_n"]))):
            pfn = 100 * s["sanas_falla"] / s["sanas_n"] if s["sanas_n"] else 0
            pfp = 100 * s["rotas_ok"] / s["rotas_n"] if s["rotas_n"] else 0
            fn_txt = f"{s['sanas_falla']}/{s['sanas_n']}"
            fp_txt = f"{s['rotas_ok']}/{s['rotas_n']}"
            print(f"  {clave:<28}{fn_txt:>16}{pfn:>5.0f}%{fp_txt:>13}"
                  f"{pfp:>5.0f}%")
        return {"primera": primera, "stats": stats}

    res["tablas"] = {}
    for modo in MODOS:
        res["tablas"][modo] = _tablas(
            [f for f in filas_ok if f["modo"] == modo], f"MODO {modo}")
    res["tablas"]["agregada"] = _tablas(filas_ok, "AGREGADA (descriptiva)")

    # atribución del veredicto (páginas sanas que el replay reprueba)
    print("\nATRIBUCIÓN de veredictos FN (modo clásico):")
    for fila in filas_ok:
        if fila["modo"] != "clasico" or not fila["banco"] \
                or fila["aprobado_replay"]:
            continue
        crit = next((r for r in fila["pasos"]
                     if r["critico"] and not r["ok"]), None)
        cualq = next((r for r in fila["pasos"] if not r["ok"]), None)
        etiqueta = f"{fila['tarea']}__{fila['brazo']}__r{fila['rep']}"
        div = (" [¡no-crítico falló antes: "
               f"'{cualq['nombre'][:40]}'!]"
               if cualq and crit and cualq["i"] < crit["i"] else "")
        if crit:
            sub = next((s for s in crit["subs"] if s["ok"] is False), None)
            print(f"  {etiqueta:<30} {_tipo(sub) if sub else '?':<24} "
                  f"'{crit['nombre'][:45]}'{div}")

    # resumen para el veredicto del banco por celda estable
    res["inestables"] = sorted(inestables)
    res["concordancia_manana"] = concordancia
    res["discordantes_manana"] = discordantes
    _guardar()
    print(f"\nJSON: {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
