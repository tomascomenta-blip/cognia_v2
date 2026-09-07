# -*- coding: utf-8 -*-
"""
cognia/fases/verificador.py — corre la Definicion de Hecho con las tools REALES.

Cero llamadas al modelo (el juez tiene que EJECUTAR, no opinar). Cada
requisito con verificacion ejecutable se corre por `run_tool` (tests,
ejecutar, probar, renderizar con guion, app_probar) y queda marcado OK /
FALLA con su evidencia literal. Los manuales conservan lo que el modelo
marco con `fases_dod marcar` (o quedan sin verificar).

Ademas de la DoD, mide senales del producto entero:
  consola_errores  errores de JS/consola que salieron en cualquier render
  tracebacks       tracebacks en ejecuciones y apps
  tests_ok/total   de las verificaciones tipo tests (pytest)
  capturas         PNG de cada version (para la comparacion visual entre
                   versiones: captura_diff contra la ultima aceptada)
  revision         el informe de cognia/harness/revision_profunda sobre los
                   ficheros cambiados (sintaxis, tests que los cubren, arranque)

Todo lo que corre el modelo en las verificaciones pasa por el mismo sentinel
que `ejecutar`; el ctx lleva `confirm` afirmativo porque el dueno ya
autorizo la obra, y los BLOCK duros siguen vigentes.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from cognia.fases import dod as _dod
from cognia.fases import estado as _est

TIMEOUT_EJECUTAR_S = 90
MAX_EVIDENCIA = 400

_RE_PASSED = re.compile(r"(\d+) passed")
_RE_FAILED = re.compile(r"(\d+) failed")
_RE_ERRORES_JS = re.compile(r"(\d+) error\(es\) de (?:JS|consola)")
_RE_ASSERTS = re.compile(r"asserts: (\d+)/(\d+) OK")
_RE_CAPTURA = re.compile(r"(?:captura(?: en| final)?|mosaico[^:]*):? ([A-Za-z]:\\[^\s·]+\.png|/[^\s·]+\.png|[^\s·]+\.png)")


def _run(nombre: str, args: str, ctx: dict) -> str:
    from cognia.agent.tools import run_tool
    try:
        return run_tool(nombre, args, ctx) or ""
    except Exception as exc:
        return "RESULTADO %s ERROR: %s: %s" % (nombre, type(exc).__name__, str(exc)[:200])


def _primera(texto: str) -> str:
    return (texto or "").strip().split("\n", 1)[0]


def _espera_ok(texto: str, espera: str) -> bool:
    if not espera:
        return True
    try:
        return re.search(espera, texto, re.M | re.S | re.I) is not None
    except re.error:
        return espera.lower() in texto.lower()


def _sustituir(args: str, est: dict) -> str:
    return (args or "").replace("{entrypoint}", est.get("entrypoint") or "").strip()


def ctx_verificacion(est: dict, version_dir: Path) -> dict:
    return {"workspace": est["workspace"], "_scratchpad": str(version_dir),
            "confirm": lambda *a, **k: True, "_fases": True}


def verificar_item(item: dict, est: dict, ctx: dict) -> dict:
    """Corre UNA verificacion. Devuelve {ok, evidencia, salida, consola, tracebacks, tests}."""
    v = item.get("verif") or {}
    tipo = v.get("tipo", "manual")
    args = _sustituir(v.get("args", ""), est)
    espera = v.get("espera", "")
    r = {"ok": item.get("ok"), "evidencia": item.get("evidencia", ""), "salida": "",
         "consola": 0, "tracebacks": 0, "tests": None, "capturas": []}
    if tipo == "manual" or not args:
        return r
    if tipo == "tests":
        out = _run("tests", args, ctx)
        p = sum(int(m) for m in _RE_PASSED.findall(out))
        f = sum(int(m) for m in _RE_FAILED.findall(out))
        r["tests"] = (p, p + f)
        r["ok"] = bool(p > 0 and f == 0 and "ERROR" not in _primera(out))
        r["evidencia"] = "%d passed, %d failed" % (p, f) if (p or f) else _primera(out)[:MAX_EVIDENCIA]
    elif tipo == "ejecutar":
        out = _run("ejecutar", args + ("" if "timeout=" in args else " | timeout=%d" % TIMEOUT_EJECUTAR_S), ctx)
        r["tracebacks"] = out.count("Traceback (most recent call last)")
        fallo = ("ERROR" in _primera(out) or "exit code" in out.lower() and re.search(r"exit(?: code)?[:=]? ?[1-9]", out, re.I)
                 or r["tracebacks"] > 0 or "requiere confirm" in out)
        r["ok"] = (not fallo) and _espera_ok(out, espera)
        r["evidencia"] = _resumir(out)
    elif tipo == "probar":
        out = _run("probar", args, ctx)
        r["consola"] = sum(int(m) for m in _RE_ERRORES_JS.findall(out))
        r["tracebacks"] = out.count("Traceback (most recent call last)")
        fallo = "ERROR" in _primera(out) or r["tracebacks"] > 0
        r["ok"] = (not fallo) and _espera_ok(out, espera)
        r["evidencia"] = _resumir(out)
        r["capturas"] = _RE_CAPTURA.findall(out)
    elif tipo == "guion":
        out = _run("renderizar", args, ctx)
        m = _RE_ASSERTS.search(out)
        asserts_ok = (int(m.group(1)) == int(m.group(2))) if m else ("FALLA" not in out)
        r["consola"] = sum(int(x) for x in _RE_ERRORES_JS.findall(out))
        fallo = "ERROR" in _primera(out)
        r["ok"] = (not fallo) and asserts_ok and _espera_ok(out, espera)
        r["evidencia"] = _resumir(out, prefer=("asserts:", "FALLAN", "error(es)"))
        r["capturas"] = _RE_CAPTURA.findall(out)
    elif tipo == "app":
        out = _run("app_probar", args, ctx)
        r["tracebacks"] = out.count("Traceback (most recent call last)") + ("VEREDICTO: la app lanzo un TRACEBACK" in out)
        abrio = "ventana '" in out
        fallo = "ERROR" in _primera(out) or not abrio or r["tracebacks"] > 0
        r["ok"] = (not fallo) and _espera_ok(out, espera)
        r["evidencia"] = _resumir(out, prefer=("ventana", "TRACEBACK", "ERROR", "pantalla"))
        r["capturas"] = _RE_CAPTURA.findall(out)
    r["salida"] = out[:4000]
    return r


def _resumir(out: str, prefer: tuple = ()) -> str:
    lineas = [l.strip() for l in (out or "").splitlines() if l.strip()]
    if prefer:
        pref = [l for l in lineas if any(p in l for p in prefer)]
        if pref:
            return " | ".join(pref[:3])[:MAX_EVIDENCIA]
    return " | ".join(lineas[:2])[:MAX_EVIDENCIA]


def verificar(est: dict, ficheros_cambiados: list = None, on_evento=None, version_n: int = 0) -> dict:
    """Corre toda la DoD y las senales. Actualiza `est['dod']` in place y devuelve
    las METRICAS de esta version: {req_ok, req_total, req_fallan, req_sin,
    tests_ok, tests_total, consola_errores, tracebacks, capturas, revision_ok,
    revision, visual_cambio, segundos, detalle[]}."""
    t0 = time.time()
    ws = Path(est["workspace"])
    vdir = _est.dir_fases(ws) / ("v%03d" % version_n)
    vdir.mkdir(parents=True, exist_ok=True)
    ctx = ctx_verificacion(est, vdir)
    cwd_previo = os.getcwd()
    try:
        os.chdir(str(ws))
    except OSError:
        pass
    m = {"req_ok": 0, "req_total": 0, "req_fallan": 0, "req_sin": 0, "tests_ok": 0, "tests_total": 0,
         "consola_errores": 0, "tracebacks": 0, "capturas": [], "revision_ok": None, "revision": "",
         "visual_cambio": None, "segundos": 0.0, "detalle": []}
    try:
        for item in _dod.items(est["dod"]):
            r = verificar_item(item, est, ctx)
            item["ok"] = r["ok"]
            if r["evidencia"]:
                item["evidencia"] = r["evidencia"]
            m["consola_errores"] += r["consola"]
            m["tracebacks"] += r["tracebacks"]
            if r["tests"]:
                m["tests_ok"] += r["tests"][0]
                m["tests_total"] += r["tests"][1]
            for c in r["capturas"]:
                if c not in m["capturas"] and Path(c).is_file():
                    m["capturas"].append(c)
            m["detalle"].append({"id": item["id"], "ok": r["ok"], "evidencia": (r["evidencia"] or "")[:200]})
            if on_evento:
                marca = {True: "OK", False: "FALLA", None: "sin verificar"}[r["ok"]]
                on_evento("  %s %s %s%s" % (item["id"], marca, item["texto"][:70],
                                            (" -- " + r["evidencia"][:120]) if r["ok"] is False and r["evidencia"] else ""))
        res = _dod.resumen(est["dod"])
        m.update({"req_ok": res["ok"], "req_total": res["total"], "req_fallan": res["fallan"], "req_sin": res["sin"],
                  "ok_ids": [i["id"] for i in _dod.items(est["dod"]) if i.get("ok") is True]})
        # Revision profunda del arnes sobre lo cambiado (sintaxis, tests, arranque)
        if ficheros_cambiados:
            try:
                from cognia.harness import revision_profunda as _rp
                inf = _rp.revisar({"ficheros_editados": [str(ws / f) for f in ficheros_cambiados],
                                   "workspace": str(ws), "pasos": 20, "superficie": "fases"})
                m["revision_ok"] = inf.get("ok")
                m["revision"] = (inf.get("footer") or inf.get("motivo") or "")[:300]
                for fallo in inf.get("fallos") or []:
                    if "Traceback" in str(fallo):
                        m["tracebacks"] += 1
            except Exception as exc:
                m["revision"] = "revision profunda no corrio: %s" % str(exc)[:120]
        # Captura de la version para la comparacion visual (si hay entrypoint y no salio ninguna)
        if not m["capturas"] and est.get("entrypoint"):
            cap = captura_del_producto(est, ctx)
            if cap:
                m["capturas"].append(cap)
        # copiar capturas a la carpeta de la version
        guardadas = []
        for i, c in enumerate(m["capturas"][:6]):
            try:
                dest = vdir / ("captura_%d.png" % i)
                if Path(c).resolve() != dest.resolve():
                    shutil.copyfile(c, dest)
                guardadas.append(str(dest))
            except Exception:
                pass
        m["capturas"] = guardadas
        m["visual_cambio"] = comparar_visual(est, guardadas)
    finally:
        try:
            os.chdir(cwd_previo)
        except OSError:
            pass
    m["segundos"] = round(time.time() - t0, 1)
    return m


def captura_del_producto(est: dict, ctx: dict) -> str:
    """Una captura del producto entero segun su tipo (para el diff visual)."""
    ep = est.get("entrypoint") or ""
    tp = est.get("tipo_producto") or ""
    if not ep:
        return ""
    if tp == "web" or ep.lower().endswith((".html", ".htm")):
        out = _run("renderizar", ep, ctx)
    elif tp == "python_gui":
        out = _run("app_probar", "python %s | pasos=espera 800; captura" % ep, ctx)
    else:
        return ""
    caps = [c for c in _RE_CAPTURA.findall(out) if Path(c).is_file()]
    return caps[-1] if caps else ""


def comparar_visual(est: dict, capturas: list):
    """Fraccion de pixeles distintos entre la primera captura de esta version y
    la de la ultima aceptada (None si no hay con que comparar)."""
    if not capturas:
        return None
    ua = _est.ultima_aceptada(est)
    if not ua:
        return None
    prev = (ua.get("metricas") or {}).get("capturas") or []
    if not prev or not Path(prev[0]).is_file():
        return None
    try:
        from cognia.agent import pruebas_comun as PC
        return PC.diff_imagenes(prev[0], capturas[0])["fraccion"]
    except Exception:
        return None


def texto_metricas(m: dict) -> str:
    partes = ["requisitos %d/%d OK (%d fallan, %d sin verificar)" % (m.get("req_ok", 0), m.get("req_total", 0),
                                                                     m.get("req_fallan", 0), m.get("req_sin", 0))]
    if m.get("tests_total"):
        partes.append("tests %d/%d" % (m["tests_ok"], m["tests_total"]))
    partes.append("errores de consola %d" % m.get("consola_errores", 0))
    if m.get("tracebacks"):
        partes.append("tracebacks %d" % m["tracebacks"])
    if m.get("revision_ok") is not None:
        partes.append("revision profunda %s" % ("OK" if m["revision_ok"] else "FALLA"))
    if m.get("visual_cambio") is not None:
        partes.append("cambio visual %.1f%%" % (m["visual_cambio"] * 100))
    if m.get("capturas"):
        partes.append("%d captura(s)" % len(m["capturas"]))
    return " · ".join(partes)
