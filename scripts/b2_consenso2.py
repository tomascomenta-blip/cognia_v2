"""
b2_consenso2.py — consenso cruzado, iteración 2: voto sobre selectores
OBLIGATORIOS del enunciado y mayoría-de-fracción como criterios del ranker.
PREREG_CONSENSO2_20260728.md (+ PRIMERA ENMIENDA): leerlo ANTES; umbrales,
variantes y fixes de la revisión adversarial viven allí.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_consenso2.py
        [--reanudar] [--solo-resumen] [--solo-auditoria]

Fase A (solo Playwright, SIN LLM): re-juzga los 255 votos congelados de
b2_consenso_selector guardando el detalle POR CHECK (el baseline solo guardó
agregados). Fase B (resumen): anclas de validez + variantes pre-registradas.
--solo-auditoria: emite la tabla de clasificación oblig/no-oblig por tarea y
los contratos sin checks obligatorios, sin juzgar nada (para la enmienda).
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

BON = (RAIZ / "cognia" / "program_creator" / "generated_programs"
       / "b2_bon_heldout")
BASE = (RAIZ / "cognia" / "program_creator" / "generated_programs"
        / "b2_consenso_selector")
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_consenso2")

# Nombres (y orden) de los checks universales que juzgar_web antepone al
# contrato (juez_ejecutable.py:317-383). Todo lo que venga después va 1:1
# en orden con `pasos`.
UNIVERSALES = ("carga", "sin_errores_js", "contenido", "interactivo")

# ── Clasificador de checks OBLIGATORIOS (PRIMERA ENMIENDA: all-match) ────────
# Un paso es OBLIGATORIO si (a) sus selectores/exprs contienen AL MENOS UN
# token de la interfaz obligatoria del enunciado y (b) NINGÚN token de
# selector fuera de ella (la revisión midió que el any-match dejaba 93% de
# checks como "obligatorios": no discriminaba nada — la aserción
# idiosincrática viajaba gratis junto al selector obligatorio del paso).
# Tokens extraídos A MANO de b1_tareas_brutales.json; ver tabla del prereg.
CLASES = {
    "hoja_calculo": ["celda"],
    "carrito_stock": ["prod", "add", "linea", "cant", "quitar", "total"],
    "kanban": ["col", "card", "mas", "menos",
               "cont-todo", "cont-doing", "cont-done"],
    "buscaminas": ["c", "abierta", "bandera", "estado"],
}
DATAS = {
    "hoja_calculo": ["ref"],
    "carrito_stock": ["id", "precio", "stock"],
    "kanban": ["col", "id"],
    "buscaminas": ["i"],
}

# Fuentes CSS (campo selector + strings citadas del js): sin lookbehind, un
# compuesto ".c.abierta" tiene que rendir {c, abierta}. El expr CRUDO no se
# escanea para clases (".c" ahí suele ser acceso a propiedad js): del js solo
# cuentan dataset.X, getElementById y las strings citadas.
_RE_CLASE_CSS = re.compile(r"\.([A-Za-z_][\w-]*)")
_RE_ID_CSS = re.compile(r"#([A-Za-z_][\w-]*)")
_RE_DATA_CSS = re.compile(r"\[\s*data-([\w-]+)")
_RE_DATASET = re.compile(r"dataset\.([A-Za-z_]\w*)")
_RE_GETID = re.compile(r"getElementById\(\s*['\"]([\w-]+)")
# classList.contains('mina') lleva la clase como PALABRA PELADA, sin sintaxis
# CSS: es el vehículo típico de la expectativa inventada (la clase 'mina' de
# buscaminas que ninguna página sana tiene) y hay que extraerla como token.
_RE_CLASSLIST = re.compile(r"classList\.\w+\(\s*['\"]([\w-]+)")
_RE_GETATTR = re.compile(r"getAttribute\(\s*['\"]data-([\w-]+)")
_RE_QUOTED = re.compile(r"['\"]([^'\"]*)['\"]")


def _tokens_de(selector: str, expr: str) -> tuple[set, set]:
    """(nombres, datas) con SINTAXIS de selector. Una string citada sin
    sintaxis CSS (texto esperado, p.ej. 'perdiste') no es candidata: no
    cuenta ni a favor ni en contra."""
    nombres, datas = set(), set()
    fuentes_css = [selector or ""]
    if expr:
        fuentes_css += _RE_QUOTED.findall(expr)
        datas |= set(_RE_DATASET.findall(expr))
        datas |= set(_RE_GETATTR.findall(expr))
        nombres |= set(_RE_GETID.findall(expr))
        nombres |= set(_RE_CLASSLIST.findall(expr))
    for f in fuentes_css:
        nombres |= set(_RE_CLASE_CSS.findall(f))
        nombres |= set(_RE_ID_CSS.findall(f))
        datas |= set(_RE_DATA_CSS.findall(f))
    return nombres, datas


def _planos(paso: dict):
    """El paso y todas sus sub-acciones. coder-14b anida bajo 'pasos' además
    de 'acciones' (hallazgo BLOQUEA de la auditoría: 24 pasos de kanban
    quedaban invisibles y 3 ensayos salían del apareado)."""
    yield paso
    for sub in (paso.get("acciones") or []) + (paso.get("pasos") or []):
        yield from _planos(sub)


def paso_es_oblig(tarea: str, paso: dict) -> bool:
    nombres_ok = set(CLASES[tarea])     # KeyError ruidoso si tarea desconocida
    datas_ok = set(DATAS[tarea])
    nombres, datas = set(), set()
    for p in _planos(paso):
        n, d = _tokens_de(str(p.get("selector") or ""),
                          str(p.get("expr") or ""))
        nombres |= n
        datas |= d
    if not (nombres | datas):
        return False        # no toca la interfaz: paso sin selectores
    return nombres <= nombres_ok and datas <= datas_ok


def _contrato_de(tarea, rep, s):
    f = BASE / f"{tarea}__r{rep}__s{s}__contrato.json"
    return (json.loads(f.read_text(encoding="utf-8"))
            if f.is_file() else None)


def _auditoria_clasificador(claves_contratos) -> dict:
    """Conteos oblig/no-oblig por tarea + contratos sin ningún oblig, desde
    los contratos ESTÁTICOS (la elegibilidad no depende del re-juzgado —
    hallazgo de la revisión)."""
    por_tarea: dict = {}
    sin_oblig = []
    ob_n_contrato: dict = {}
    for (tarea, rep, s) in sorted(claves_contratos):
        c = _contrato_de(tarea, rep, s)
        if not c:
            continue
        obligs = [paso_es_oblig(tarea, p) for p in c["pasos"]]
        d = por_tarea.setdefault(tarea, [0, 0])
        d[0] += sum(obligs)
        d[1] += len(obligs)
        ob_n_contrato[(tarea, rep, s)] = sum(obligs)
        if not any(obligs):
            sin_oblig.append(f"{tarea}:r{rep}:s{s}")
    return {"por_tarea": {t: f"{a}/{b}" for t, (a, b)
                          in sorted(por_tarea.items())},
            "sin_oblig": sin_oblig, "ob_n_contrato": ob_n_contrato}


# ── Ranking apareado (todas las variantes usan la misma resta vs s1) ─────────

def _resumir_variante(nombre, ensayos, votos_por_clave, outcome, heldout_de,
                      criterio, normalizar):
    """
    votos_por_clave: {(tarea,rep,s_muestra): [voto,...]} ajenos sin crasheo,
    ya filtrados por elegibilidad si la variante lo pide.
    criterio(voto) -> (aprueba, frac). Ranking: criterio 1 = nº de votos que
    aprueban (normalizar=False, fiel al baseline para el ancla 2) o FRACCIÓN
    de votos que aprueban (normalizar=True, V1-V3: los denominadores por
    muestra difieren cuando un contrato hermano falta o es inelegible y el
    conteo crudo premiaba a la muestra sin contrato propio — revisión).
    Criterio 2 = media de frac dividiendo por len(vs) (votos sin checks
    cuentan 0, mismo trato que el baseline congelado). Criterio 3 = -s.
    """
    neto, validos, sin_voto, gana, pierde = 0, [], [], [], []
    pares = {}
    coincide_heldout = 0
    aprueban = total_votos = 0
    for (tarea, rep), enes in sorted(ensayos.items()):
        votos_x = {s: votos_por_clave.get((tarea, rep, s), []) for s in enes}
        for vs in votos_x.values():
            total_votos += len(vs)
            aprueban += sum(1 for v in vs if criterio(v)[0])
        if any(len(vs) < 2 for vs in votos_x.values()) \
                or (tarea, rep, 1) not in outcome:
            sin_voto.append(f"{tarea}:r{rep}")
            continue

        def puntaje(s):
            vs = votos_x[s]
            aps = sum(1 for v in vs if criterio(v)[0])
            frac = sum(criterio(v)[1] for v in vs) / len(vs)
            return ((aps / len(vs)) if normalizar else aps, frac, -s)
        elegido = max(enes, key=puntaje)
        control = outcome[(tarea, rep, 1)]
        exito = outcome[(tarea, rep, elegido)]
        neto += (exito and not control) - (control and not exito)
        clave = f"{tarea}:r{rep}"
        validos.append(clave)
        pares[clave] = {"elegido": elegido, "exito": bool(exito),
                        "control": bool(control)}
        if exito and not control:
            gana.append(clave)
        if control and not exito:
            pierde.append(clave)
        coincide_heldout += (heldout_de(tarea, rep, enes) == elegido)
    n_v = len(validos)
    return {
        "variante": nombre, "ensayos": n_v, "sin_voto": sin_voto,
        "control": sum(1 for c in pares.values() if c["control"]),
        "selector": sum(1 for c in pares.values() if c["exito"]),
        "neto": neto, "gana": gana, "pierde": pierde, "pares": pares,
        "coincide_heldout": coincide_heldout,
        "votos_aprueban": f"{aprueban}/{total_votos}",
    }


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    reanudar = "--reanudar" in argv
    solo_resumen = "--solo-resumen" in argv
    solo_auditoria = "--solo-auditoria" in argv
    if solo_resumen or solo_auditoria:
        reanudar = True

    bon = json.loads((BON / "resultados.json").read_text(encoding="utf-8"))
    muestras = [m for m in bon["muestras"]
                if (BON / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
                    / "index.html").is_file()]
    ensayos: dict = {}
    for m in muestras:
        ensayos.setdefault((m["tarea"], m["rep"]), []).append(m["s"])
    for k in ensayos:
        ensayos[k] = sorted(ensayos[k])
    base = json.loads((BASE / "resultados.json").read_text(encoding="utf-8"))
    votos_base = [v for v in base["votos"] if "crasheo" not in v]
    claves_contratos = {(c["tarea"], c["rep"], c["s"])
                        for c in base["contratos"] if c["generado"]}

    audit = _auditoria_clasificador(claves_contratos)
    ob_n_estatico = audit.pop("ob_n_contrato")
    if solo_auditoria:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
        return 0

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"votos": []})

    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    if "config" not in res:        # no pisar la procedencia al reanudar
        res["config"] = {
            "commit": commit, "fuente_bon": bon["config"],
            "fuente_consenso": base["config"],
            "auditoria_clasificador": audit,
            "nota": "re-juzgado de los 255 votos congelados con detalle por "
                    "check; clasificador all-match de la PRIMERA ENMIENDA "
                    "(tokens con sintaxis de selector; ningún token fuera "
                    "del set obligatorio)"}

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    # ── Fase A: re-juzgar cada voto congelado guardando detalle por check ────
    hechos = {(v["tarea"], v["rep"], v["s_contrato"], v["s_muestra"])
              for v in res["votos"]}
    pendientes = [v for v in base["votos"]
                  if (v["tarea"], v["rep"], v["s_contrato"], v["s_muestra"])
                  not in hechos]
    if not solo_resumen and pendientes:
        print(f"FASE A — re-juzgado por check ({len(base['votos'])} votos, "
              f"hechos {len(hechos)})", flush=True)
        for vb in pendientes:
            tarea, rep = vb["tarea"], vb["rep"]
            s_c, s_x = vb["s_contrato"], vb["s_muestra"]
            c = _contrato_de(tarea, rep, s_c)
            if not c:
                continue    # el baseline no tuvo votos de contratos None
            oblig_pasos = [paso_es_oblig(tarea, p) for p in c["pasos"]]
            html = BON / f"{tarea}__r{rep}__s{s_x}" / "index.html"
            fila = {"tarea": tarea, "rep": rep,
                    "s_contrato": s_c, "s_muestra": s_x}
            t0 = time.time()
            try:
                v = juez_ejecutable.juzgar_web(html, c)
                checks = [ch if isinstance(ch, dict) else
                          {"nombre": ch.nombre, "ok": ch.ok,
                           "critico": ch.critico} for ch in v.checks]
                # los universales van SIEMPRE delante; el resto es 1:1 con pasos
                i = 0
                while i < len(checks) and i < 4 \
                        and checks[i]["nombre"] in UNIVERSALES:
                    i += 1
                del_c = checks[i:]
                det = [{"n": ch["nombre"][:60], "ok": bool(ch["ok"]),
                        "critico": bool(ch.get("critico")),
                        "oblig": (oblig_pasos[j] if j < len(oblig_pasos)
                                  else False)}
                       for j, ch in enumerate(del_c)]
                fila.update(
                    aprueba=bool(v.aprobado),
                    c_ok=sum(1 for d in det if d["ok"]), c_n=len(det),
                    aprueba_contrato=bool(det) and all(d["ok"] for d in det),
                    ob_ok=sum(1 for d in det if d["oblig"] and d["ok"]),
                    ob_n=sum(1 for d in det if d["oblig"]),
                    # desalineación REAL, no corte temprano por carga (la
                    # revisión cazó el falso positivo con del_c vacío)
                    desalineado=bool(del_c) and len(del_c) != len(c["pasos"]),
                    detalle=det, segundos=round(time.time() - t0, 1))
            except Exception as exc:
                fila.update(crasheo=f"{exc}"[:80])
            res["votos"].append(fila)
            _guardar()
            print(f"  {tarea:<14} r{rep} c{s_c}->s{s_x} "
                  f"{'ok' if 'crasheo' not in fila else 'CRASH'} "
                  f"({fila.get('segundos', '?')}s)", flush=True)

    # ── Fase B: anclas + variantes ───────────────────────────────────────────
    votos_re = [v for v in res["votos"] if "crasheo" not in v]
    estricto = {(m["tarea"], m["rep"], m["s"]): bool(m["estricto"])
                for m in muestras}
    solo_orig = {(m["tarea"], m["rep"], m["s"]): bool(m.get("aprobado"))
                 for m in muestras}
    solo_held = {(m["tarea"], m["rep"], m["s"]):
                 bool(m.get("aprobado_heldout")) for m in muestras}
    ms_por_clave = {(m["tarea"], m["rep"], m["s"]): m for m in muestras}

    def heldout_de(tarea, rep, enes):
        return sorted(enes, key=lambda s: (
            not ms_por_clave[(tarea, rep, s)].get("aprobado_heldout"),
            -ms_por_clave[(tarea, rep, s)].get("heldout_checks_ok", 0), s))[0]

    # Ancla 1: reproducción por voto (aprueba_contrato re-juzgado vs congelado)
    base_por_clave = {(v["tarea"], v["rep"], v["s_contrato"], v["s_muestra"]):
                      v for v in votos_base}
    comparables = [(v, base_por_clave[k]) for v in votos_re
                   if (k := (v["tarea"], v["rep"], v["s_contrato"],
                             v["s_muestra"])) in base_por_clave]
    iguales = sum(1 for v, vb in comparables
                  if v["aprueba_contrato"] == vb.get("aprueba_contrato"))
    repro = iguales / len(comparables) if comparables else 0.0

    def _mapa(votos, elegible=lambda v: True):
        d: dict = {}
        for v in votos:
            if v["s_contrato"] == v["s_muestra"] or not elegible(v):
                continue
            d.setdefault((v["tarea"], v["rep"], v["s_muestra"]),
                         []).append(v)
        return d

    def crit_base(v):
        return (bool(v.get("aprueba_contrato")),
                v["c_ok"] / v["c_n"] if v.get("c_n") else 0.0)

    def crit_frac(v):
        return (bool(v.get("c_n")) and v["c_ok"] / v["c_n"] >= 0.5,
                v["c_ok"] / v["c_n"] if v.get("c_n") else 0.0)

    def crit_oblig(v):
        return (bool(v.get("ob_n")) and v["ob_ok"] == v["ob_n"],
                v["ob_ok"] / v["ob_n"] if v.get("ob_n") else 0.0)

    def crit_combo(v):
        return (bool(v.get("ob_n")) and v["ob_ok"] / v["ob_n"] >= 0.5,
                v["ob_ok"] / v["ob_n"] if v.get("ob_n") else 0.0)

    # Elegibilidad V1/V3: propiedad ESTÁTICA del contrato votante (>=1 paso
    # obligatorio según el clasificador), no del re-juzgado (revisión).
    def eleg_oblig(v):
        return ob_n_estatico.get(
            (v["tarea"], v["rep"], v["s_contrato"]), 0) > 0

    def _v(nombre, votos, criterio, *, elegible=lambda v: True,
           outcome=estricto, normalizar=True):
        return _resumir_variante(nombre, ensayos, _mapa(votos, elegible),
                                 outcome, heldout_de, criterio, normalizar)

    variantes = [
        _v("ancla2_baseline_repro", votos_re, crit_base, normalizar=False),
        _v("V1_oblig", votos_re, crit_oblig, elegible=eleg_oblig),
        _v("V2_frac_congelados", votos_base, crit_frac),
        _v("V3_combo", votos_re, crit_combo, elegible=eleg_oblig),
        # Robustez de V2 sobre el instrumento re-juzgado (revisión):
        _v("V2r_frac_rejuzgados", votos_re, crit_frac),
    ]
    # Secundarias partidas por conjuncto del outcome (fuga de superficie del
    # held-out, revisión): ¿la ganancia vive solo en el conjuncto held-out?
    partidas = [
        _v("V1_solo_original", votos_re, crit_oblig, elegible=eleg_oblig,
           outcome=solo_orig),
        _v("V1_solo_heldout", votos_re, crit_oblig, elegible=eleg_oblig,
           outcome=solo_held),
    ]

    # Sensibilidad peor-caso (revisión): un ensayo excluido de V1/V3 cuyo
    # control es estricto=True solo podía empatar o restar — cuenta −1.
    base_sin_voto = set(variantes[0]["sin_voto"])
    for r in variantes:
        if r["variante"] not in ("V1_oblig", "V3_combo"):
            r["neto_peor_caso"] = r["neto"]
            continue
        extra = [sv for sv in r["sin_voto"] if sv not in base_sin_voto]
        castigo = sum(1 for sv in extra
                      if estricto.get((sv.split(":r")[0],
                                       int(sv.split(":r")[1]), 1)))
        r["neto_peor_caso"] = r["neto"] - castigo
        r["excluidos_extra"] = extra

    # Comparación entre variantes SOLO sobre la intersección de ensayos
    # válidos (revisión: netos sobre n distinto no se comparan).
    inter = set.intersection(*(set(r["pares"]) for r in variantes))
    for r in variantes + partidas:
        r["neto_interseccion"] = sum(
            (p["exito"] and not p["control"]) - (p["control"] and not p["exito"])
            for cl, p in r["pares"].items() if cl in inter)

    desalineados = sum(1 for v in votos_re if v.get("desalineado"))
    cortes_carga = sum(1 for v in votos_re if v.get("c_n") == 0)
    esperados = len(base["votos"])
    parcial = len(votos_re) < esperados
    ancla2 = variantes[0]
    ancla2_ok = 0 <= ancla2["neto"] <= 4
    print(f"\n{'=' * 72}")
    print(f"  CONSENSO 2 — anclas de validez")
    print(f"  ancla 1 (reproducción por voto): {iguales}/{len(comparables)}"
          f" = {repro:.0%}  (umbral >=90%)  ancla 2 (baseline en [0,+4]): "
          f"neto {ancla2['neto']:+d} -> {'OK' if ancla2_ok else 'FALLA'}")
    print(f"  votos re-juzgados: {len(votos_re)}/{esperados}"
          f"{' PARCIAL' if parcial else ''}; crasheados "
          f"{len(res['votos']) - len(votos_re)}; desalineados: {desalineados};"
          f" cortes de carga (c_n=0): {cortes_carga}")
    print(f"  clasificador (estático): " + ", ".join(
        f"{t} {v}" for t, v in audit["por_tarea"].items()))
    print(f"  contratos sin ningún check obligatorio: "
          f"{len(audit['sin_oblig'])} {audit['sin_oblig']}")
    for r in variantes + partidas:
        extra = (f"  peor caso: {r['neto_peor_caso']:+d}"
                 if r.get("excluidos_extra") else "")
        print(f"\n  [{r['variante']}]  n={r['ensayos']} "
              f"(sin voto: {len(r['sin_voto'])})")
        print(f"    control s1: {r['control']}/{r['ensayos']}   "
              f"selector: {r['selector']}/{r['ensayos']}   "
              f"neto = {r['neto']:+d}{extra}   "
              f"interseccion({len(inter)}): {r['neto_interseccion']:+d}")
        print(f"    gana: {', '.join(r['gana']) or '—'}   "
              f"pierde: {', '.join(r['pierde']) or '—'}")
        print(f"    coincide held-out: {r['coincide_heldout']}/{r['ensayos']}"
              f"   votos que aprueban: {r['votos_aprueban']}")
    print(f"\n  (prereg: neto >=+5 Y peor caso >=+5 -> VIVA; +3..+4 moderada;"
          f" [-2,+2] KILL; V2 es EXPLORATORIA — su vida exige validación "
          f"FÁCIL sí o sí)")
    print(f"{'=' * 72}")
    res["resumen"] = {
        "ancla1_repro": f"{iguales}/{len(comparables)}", "ancla1_ok":
            repro >= 0.9, "ancla2_neto": ancla2["neto"],
        "ancla2_ok": ancla2_ok,
        "votos_hechos": f"{len(votos_re)}/{esperados}", "parcial": parcial,
        "votos_crasheados": len(res["votos"]) - len(votos_re),
        "desalineados": desalineados, "cortes_carga": cortes_carga,
        "auditoria_clasificador": audit,
        "interseccion": sorted(inter),
        "variantes": variantes, "partidas": partidas}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
