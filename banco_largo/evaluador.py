# -*- coding: utf-8 -*-
"""evaluador.py -- evaluacion MULTICAPA del producto que dejo el agente.

Ocho capas independientes; la nota global es una combinacion ponderada pero cada
capa se conserva entera. Prioridad declarada por el dueno:
    funcionalidad > completitud > robustez > calidad > velocidad

    A completitud   -- hizo TODO lo pedido? (requisitos con evidencia en disco)
    B funcionalidad -- funciona de verdad? (pruebas ejecutadas por motor.py)
    C calidad       -- la implementacion es razonable? (metricas estaticas, sin juez)
    D robustez      -- aguanta fuera del caso ideal? (pruebas de borde)
    E integridad    -- las piezas encajan entre si? (referencias, imports, assets)
    F entregabilidad-- existe un producto que se pueda entregar? (COPIA LIMPIA)
    G verificacion  -- el propio agente demostro que funciona? (telemetria de la corrida)
    H regresiones   -- una correccion rompio otra cosa? (dos pasadas / estabilidad)

REGLA DE ORO: la evidencia externa manda. Lo que el agente diga en su respuesta no
puntua en ninguna capa salvo G, y G mide ACCIONES (tool calls de verificacion), no
afirmaciones.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from . import motor

PESOS = {
    "funcionalidad": 0.30,
    "completitud": 0.22,
    "robustez": 0.12,
    "integridad": 0.10,
    "entregabilidad": 0.10,
    "verificacion": 0.08,
    "calidad": 0.05,
    "regresion": 0.03,
}

EXT_CODIGO = {".py", ".js", ".mjs", ".ts", ".html", ".css", ".json", ".md", ".txt",
              ".glsl", ".wgsl", ".jsx", ".sh", ".toml", ".yml", ".yaml"}

_PLACEHOLDER = [
    r"\bTODO\b", r"\bFIXME\b", r"\bXXX\b",
    r"not\s+implemented", r"no\s+implementado", r"por\s+implementar",
    r"pendiente\s+de\s+implementar", r"implementar\s+aqui", r"aqui\s+ira",
    r"lorem\s+ipsum", r"placeholder", r"\bstub\b",
    r"^\s*\.\.\.\s*$", r"raise\s+NotImplementedError",
    r"//\s*resto\s+del", r"#\s*resto\s+del", r"\[\.\.\.\]",
    r"//\s*\.\.\.\s*$", r"#\s*\.\.\.\s*$",
    r"el\s+resto\s+(del|de\s+la)\s+(codigo|implementacion)",
]


def _ficheros_producto(ws):
    ws = Path(ws)
    fuera = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".venv", "venv",
             ".cognia", "__banco__"}
    out = []
    for p in ws.rglob("*"):
        if not p.is_file():
            continue
        if any(parte in fuera for parte in p.parts):
            continue
        out.append(p)
    return out


def _texto(p, tope=300000):
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:tope]
    except Exception:
        return ""


# -- capa C: calidad estatica ------------------------------------------------

def capa_calidad(ws, tarea):
    ficheros = [p for p in _ficheros_producto(ws) if p.suffix.lower() in EXT_CODIGO]
    if not ficheros:
        return {"nota": 0.0, "detalle": "no hay ningun fichero de codigo", "metricas": {}}
    total_bytes = sum(p.stat().st_size for p in ficheros)
    lineas = 0
    huecos = []
    dup = {}
    for p in ficheros:
        t = _texto(p)
        ls = t.splitlines()
        lineas += len(ls)
        for pat in _PLACEHOLDER:
            for m in re.finditer(pat, t, re.I | re.M):
                huecos.append("%s: %s" % (p.name, m.group(0)[:60]))
                break
        for l in ls:
            s = l.strip()
            if len(s) > 45 and not s.startswith(("#", "//", "*", "<!--")):
                dup[s] = dup.get(s, 0) + 1
    repetidas = sum(1 for k, v in dup.items() if v >= 4)
    esperado = int((tarea.get("longitud_esperada_lineas") or 400))
    # tamano: 1.0 al alcanzar lo esperado, sin premiar el relleno por encima
    n_tam = min(1.0, lineas / max(80.0, esperado))
    # huecos: cada placeholder distinto resta; 8+ deja la sub-nota a cero
    n_huecos = max(0.0, 1.0 - len(set(huecos)) / 8.0)
    n_dup = max(0.0, 1.0 - repetidas / 25.0)
    nota = 0.5 * n_tam + 0.35 * n_huecos + 0.15 * n_dup
    return {
        "nota": round(nota, 4),
        "detalle": "%d ficheros, %d lineas, %d placeholders, %d bloques repetidos" % (
            len(ficheros), lineas, len(set(huecos)), repetidas),
        "metricas": {"ficheros": len(ficheros), "lineas": lineas, "bytes": total_bytes,
                     "placeholders": sorted(set(huecos))[:12], "repetidas": repetidas,
                     "n_tam": round(n_tam, 3), "n_huecos": round(n_huecos, 3),
                     "n_dup": round(n_dup, 3)},
    }


# -- capa F: entregabilidad (COPIA LIMPIA) -----------------------------------

def capa_entregabilidad(ws, tarea, resultados):
    """Un producto entregable arranca fuera de su cuna.

    Copia el workspace a un temporal y vuelve a correr ahi las pruebas marcadas
    `entregable`. Eso caza rutas absolutas, ficheros escritos fuera del workspace
    y dependencias del directorio de trabajo original.
    """
    partes = {}
    obligatorios = [a for a in (tarea.get("artefactos") or []) if a.get("obligatorio", True)]
    presentes = 0
    faltan = []
    for a in obligatorios:
        if motor.buscar(ws, a["glob"]) or motor.buscar(ws, "**/" + a["glob"]):
            presentes += 1
        else:
            faltan.append(a["glob"])
    partes["artefactos"] = presentes / len(obligatorios) if obligatorios else 0.0

    instrucciones = motor.buscar(ws, "**/*.md") + motor.buscar(ws, "README*")
    utiles = [p for p in instrucciones if p.stat().st_size >= 200]
    partes["instrucciones"] = 1.0 if utiles else 0.0

    pruebas_ent = [p for p in (tarea.get("pruebas") or []) if p.get("entregable")]
    detalle_copia = "sin pruebas marcadas entregable"
    if pruebas_ent:
        tmp = Path(tempfile.mkdtemp(prefix="entrega_"))
        destino = tmp / "producto"
        try:
            shutil.copytree(str(ws), str(destino),
                            ignore=shutil.ignore_patterns("__pycache__", ".git",
                                                          "node_modules", ".pytest_cache"))
            res = motor.correr_suite(pruebas_ent, destino)
            ok = sum(1 for r in res if r["ok"])
            partes["arranque_limpio"] = ok / len(res) if res else 0.0
            detalle_copia = "; ".join("%s:%s" % (r["nombre"], "OK" if r["ok"] else r["detalle"][:120])
                                      for r in res)
        except Exception as e:
            partes["arranque_limpio"] = 0.0
            detalle_copia = "la copia limpia rompio: %s" % e
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
    else:
        partes["arranque_limpio"] = 1.0 if partes["artefactos"] >= 1.0 else 0.0

    nota = 0.4 * partes["artefactos"] + 0.15 * partes["instrucciones"] + 0.45 * partes["arranque_limpio"]
    return {"nota": round(nota, 4),
            "detalle": "artefactos %d/%d%s | instrucciones %s | copia limpia: %s" % (
                presentes, len(obligatorios),
                (" (faltan: %s)" % ", ".join(faltan[:4])) if faltan else "",
                "si" if utiles else "NO", detalle_copia[:300]),
            "metricas": partes}


# -- capa G: verificacion hecha por el propio agente -------------------------

_TOOLS_VERIFICAN = re.compile(
    r"\b(tests?|pytest|ejecutar|ejecutar_python|ejecutar_comando|correr|shell|bash|"
    r"run_command|probar|verificar|abrir_navegador|captura|node)\b", re.I)


def capa_verificacion(telemetria):
    """Mide ACCIONES de verificacion del agente, no sus afirmaciones."""
    tools = telemetria.get("tool_calls_por_nombre") or {}
    verif = {k: v for k, v in tools.items() if _TOOLS_VERIFICAN.search(k)}
    n_verif = sum(verif.values())
    n_total = sum(tools.values()) or 1
    ejecuciones = telemetria.get("ejecuciones_ok", 0) + telemetria.get("ejecuciones_fallo", 0)
    # 3 ejecuciones reales ya es "probo lo que hizo"; 0 es cero.
    n_ejec = min(1.0, ejecuciones / 3.0) if ejecuciones else min(1.0, n_verif / 3.0)
    n_prop = min(1.0, (n_verif / n_total) / 0.25) if n_total else 0.0
    # que ademas encontrara y arreglara algo cuenta: errores vistos y luego ausentes
    n_repara = 1.0 if telemetria.get("errores_reparados", 0) > 0 else (
        0.5 if telemetria.get("errores_vistos", 0) > 0 else 0.0)
    nota = 0.55 * n_ejec + 0.25 * n_prop + 0.20 * n_repara
    return {"nota": round(nota, 4),
            "detalle": "%d tool calls de verificacion de %d totales; %d ejecuciones reales" % (
                n_verif, n_total, ejecuciones),
            "metricas": {"verif": verif, "n_ejec": round(n_ejec, 3),
                         "n_prop": round(n_prop, 3), "n_repara": n_repara}}


# -- agregacion --------------------------------------------------------------

def _nota_capa(resultados, capa):
    rs = [r for r in resultados if r.get("capa") == capa]
    if not rs:
        return None, []
    peso = sum(r["peso"] for r in rs) or 1.0
    ok = sum(r["peso"] for r in rs if r["ok"])
    return ok / peso, rs


def evaluar(tarea, ws, telemetria=None):
    """Corre la suite completa y devuelve las 8 capas + la nota global."""
    telemetria = telemetria or {}
    ws = Path(ws)
    resultados = motor.correr_suite(tarea.get("pruebas") or [], ws)

    capas = {}
    for capa in ("completitud", "funcionalidad", "robustez", "integridad", "regresion"):
        nota, rs = _nota_capa(resultados, capa)
        capas[capa] = {
            "nota": round(nota, 4) if nota is not None else None,
            "pruebas": len(rs),
            "pasadas": sum(1 for r in rs if r["ok"]),
            "fallos": [{"nombre": r["nombre"], "detalle": r["detalle"][:400]}
                       for r in rs if not r["ok"]],
        }
    capas["calidad"] = capa_calidad(ws, tarea)
    capas["entregabilidad"] = capa_entregabilidad(ws, tarea, resultados)
    capas["verificacion"] = capa_verificacion(telemetria)

    total, peso_total = 0.0, 0.0
    for nombre, peso in PESOS.items():
        n = capas.get(nombre, {}).get("nota")
        if n is None:
            continue
        total += peso * n
        peso_total += peso
    global_ = total / peso_total if peso_total else 0.0

    func = capas["funcionalidad"]["nota"]
    comp = capas["completitud"]["nota"]
    veredicto = "fallo"
    if func is not None and func >= 0.8 and (comp is None or comp >= 0.75):
        veredicto = "completado"
    elif func is not None and func >= 0.5:
        veredicto = "parcial"
    elif (func or 0) > 0 or (comp or 0) >= 0.5:
        veredicto = "esqueleto"
    if telemetria.get("truncado"):
        veredicto = veredicto if veredicto == "completado" else "truncado"

    return {
        "tarea": tarea.get("id"),
        "veredicto": veredicto,
        "global": round(global_, 4),
        "capas": capas,
        "resultados": resultados,
        "n_pruebas": len(resultados),
        "n_pasadas": sum(1 for r in resultados if r["ok"]),
    }
