# -*- coding: utf-8 -*-
"""
cognia/fases/estado.py — el PROJECT STATE de una obra por fases.

Vive en <workspace>/.cognia_fases/estado.json (fuente de verdad, escritura
atomica) y se renderiza a ESTADO_PROYECTO.md para que el modelo lo lea al
empezar cada iteracion sin cargar la historia entera al contexto.

Lo que guarda (todo plano, dicts y listas):
  encargo, tipo_producto, entrypoint, fase_actual, fases{id: {estado,
  iteraciones[]}}, dod (ver dod.py), issues[] (P0..P4), versiones[]
  (snapshot git + metricas + decision del juez), estables[] (ficheros o
  sistemas que NO se tocan salvo razon concreta), hipotesis (la de la
  iteracion en curso), notas[].
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

DIR_NOMBRE = ".cognia_fases"
PRIORIDADES = ("P0", "P1", "P2", "P3", "P4")
PRIORIDAD_TEXTO = {"P0": "BLOQUEANTE", "P1": "CRITICO", "P2": "ALTO", "P3": "MEDIO", "P4": "BAJO"}


def dir_fases(workspace) -> Path:
    return Path(str(workspace)).resolve() / DIR_NOMBRE


def ruta_estado(workspace) -> Path:
    return dir_fases(workspace) / "estado.json"


def existe(workspace) -> bool:
    return ruta_estado(workspace).is_file()


def nuevo(workspace, encargo: str, fases_ids: list) -> dict:
    d = dir_fases(workspace)
    d.mkdir(parents=True, exist_ok=True)
    est = {
        "version_formato": 1,
        "id": time.strftime("%Y%m%d-%H%M%S"),
        "workspace": str(Path(str(workspace)).resolve()),
        "encargo": (encargo or "").strip(),
        "creado": time.time(),
        "tipo_producto": "",
        "entrypoint": "",
        "fase_actual": fases_ids[0] if fases_ids else "",
        "fases": {f: {"estado": "pendiente", "iteraciones": []} for f in fases_ids},
        "dod": {"funcionales": [], "visuales": [], "calidad": []},
        "issues": [],
        "versiones": [],
        "estables": [],
        "hipotesis": {},
        "notas": [],
        "terminado": False,
        "veredicto": "",
    }
    guardar(est)
    return est


def guardar(est: dict) -> None:
    ruta = ruta_estado(est["workspace"])
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)
    try:
        (ruta.parent / "ESTADO_PROYECTO.md").write_text(render_md(est), encoding="utf-8")
    except Exception:
        pass    # el .md es una vista; la verdad es el json y ya esta escrito


def cargar(workspace) -> dict | None:
    ruta = ruta_estado(workspace)
    if not ruta.is_file():
        return None
    try:
        est = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None
    est["workspace"] = str(Path(str(workspace)).resolve())
    return est


# ---------------------------------------------------------------------------
# Issues (P0..P4)
# ---------------------------------------------------------------------------

def issue_agregar(est: dict, prioridad: str, titulo: str, pasos: str = "", esperado: str = "",
                  actual: str = "", evidencia: str = "", causa: str = "", fase: str = "") -> dict:
    p = (prioridad or "P3").upper().strip()
    if p not in PRIORIDADES:
        p = "P3"
    n = 1 + max([0] + [int(i["id"][1:]) for i in est["issues"] if re.match(r"^#\d+$", i["id"])])
    it = {"id": "#%03d" % n, "prioridad": p, "titulo": (titulo or "").strip()[:200],
          "pasos": (pasos or "").strip()[:800], "esperado": (esperado or "").strip()[:400],
          "actual": (actual or "").strip()[:400], "evidencia": (evidencia or "").strip()[:400],
          "causa": (causa or "").strip()[:400], "fix": "", "estado": "abierto",
          "fase": fase or est.get("fase_actual", ""), "ts": time.time()}
    est["issues"].append(it)
    return it


def issue_cerrar(est: dict, issue_id: str, causa: str = "", fix: str = "") -> dict | None:
    iid = issue_id.strip()
    if not iid.startswith("#"):
        iid = "#" + iid.lstrip("#").zfill(3)
    for it in est["issues"]:
        if it["id"] == iid:
            it["estado"] = "cerrado"
            if causa:
                it["causa"] = causa.strip()[:400]
            if fix:
                it["fix"] = fix.strip()[:400]
            it["cerrado_ts"] = time.time()
            return it
    return None


def issues_abiertos(est: dict) -> list:
    orden = {p: i for i, p in enumerate(PRIORIDADES)}
    return sorted([i for i in est["issues"] if i["estado"] == "abierto"],
                  key=lambda i: (orden.get(i["prioridad"], 9), i["id"]))


def conteo_issues(est: dict) -> dict:
    c = {p: 0 for p in PRIORIDADES}
    for i in issues_abiertos(est):
        c[i["prioridad"]] += 1
    return c


# ---------------------------------------------------------------------------
# Versiones aceptadas / rechazadas
# ---------------------------------------------------------------------------

def version_registrar(est: dict, commit: str, fase: str, iteracion: int, metricas: dict,
                      decision: str, motivos: list, hipotesis: dict = None) -> dict:
    n = 1 + max([0] + [v["n"] for v in est["versiones"]])
    v = {"n": n, "commit": commit, "fase": fase, "iteracion": iteracion,
         "metricas": dict(metricas or {}), "decision": decision, "motivos": list(motivos or []),
         "hipotesis": dict(hipotesis or {}), "ts": time.time()}
    est["versiones"].append(v)
    return v


def ultima_aceptada(est: dict) -> dict | None:
    for v in reversed(est["versiones"]):
        if v["decision"] == "aceptar":
            return v
    return None


# ---------------------------------------------------------------------------
# Estables / no tocar
# ---------------------------------------------------------------------------

def estable_agregar(est: dict, que: str, motivo: str = "") -> None:
    q = (que or "").strip()
    if q and all(e["que"] != q for e in est["estables"]):
        est["estables"].append({"que": q, "motivo": motivo.strip()[:200], "ts": time.time()})


def estable_quitar(est: dict, que: str) -> bool:
    antes = len(est["estables"])
    est["estables"] = [e for e in est["estables"] if e["que"] != (que or "").strip()]
    return len(est["estables"]) < antes


# ---------------------------------------------------------------------------
# Render para el modelo y para el dueno
# ---------------------------------------------------------------------------

def _linea_req(r: dict) -> str:
    marca = {True: "[x]", False: "[!]", None: "[ ]"}[r.get("ok")]
    v = r.get("verif") or {}
    tipo = v.get("tipo", "manual")
    ev = (" -- " + str(r.get("evidencia", ""))[:90]) if r.get("evidencia") and r.get("ok") is False else ""
    return "%s %s %s (%s)%s" % (marca, r.get("id", "?"), r.get("texto", "")[:110], tipo, ev)


def render_md(est: dict, para_modelo: bool = False, tope_chars: int = 6000) -> str:
    from cognia.fases import dod as _dod
    lineas = []
    lineas.append("# ESTADO DEL PROYECTO (obra por fases)")
    lineas.append("Encargo: %s" % est.get("encargo", "")[:400])
    if est.get("tipo_producto"):
        lineas.append("Tipo: %s · entrypoint: %s" % (est["tipo_producto"], est.get("entrypoint") or "?"))
    lineas.append("Fase actual: %s" % est.get("fase_actual", ""))
    hechas = [f for f, d in est["fases"].items() if d["estado"] == "completa"]
    saltadas = [f for f, d in est["fases"].items() if d["estado"] == "saltada"]
    if hechas:
        lineas.append("Fases completas: " + ", ".join(hechas))
    if saltadas:
        lineas.append("Fases saltadas: " + ", ".join(saltadas))
    ua = ultima_aceptada(est)
    if ua:
        m = ua.get("metricas", {})
        lineas.append("Ultima version aceptada: v%d (%s) · requisitos %s/%s · tests %s/%s · errores consola %s"
                      % (ua["n"], ua["commit"][:8], m.get("req_ok", "?"), m.get("req_total", "?"),
                         m.get("tests_ok", "?"), m.get("tests_total", "?"), m.get("consola_errores", "?")))
    res = _dod.resumen(est["dod"])
    lineas.append("")
    lineas.append("## Definicion de Hecho: %d/%d OK, %d fallan, %d sin verificar" % (
        res["ok"], res["total"], res["fallan"], res["sin"]))
    for grupo, titulo in (("funcionales", "FUNCIONALES"), ("visuales", "VISUALES"), ("calidad", "CALIDAD")):
        items = est["dod"].get(grupo) or []
        if not items:
            continue
        lineas.append("### %s" % titulo)
        for r in items:
            lineas.append("- " + _linea_req(r))
    ab = issues_abiertos(est)
    lineas.append("")
    lineas.append("## Issues abiertos: %d (%s)" % (len(ab), ", ".join("%s=%d" % kv for kv in conteo_issues(est).items() if kv[1])))
    for i in ab[:25]:
        lineas.append("- %s %s %s" % (i["id"], i["prioridad"], i["titulo"]))
        if i.get("pasos") and not para_modelo:
            lineas.append("    pasos: %s" % i["pasos"][:200])
    if est.get("estables"):
        lineas.append("")
        lineas.append("## NO TOCAR (estables): " + "; ".join(e["que"] for e in est["estables"]))
    h = est.get("hipotesis") or {}
    if h.get("texto"):
        lineas.append("")
        lineas.append("## Hipotesis de la iteracion: %s" % h["texto"][:300])
        if h.get("plan"):
            lineas.append("Plan: %s" % h["plan"][:300])
    if not para_modelo and est.get("versiones"):
        lineas.append("")
        lineas.append("## Versiones")
        for v in est["versiones"][-12:]:
            m = v.get("metricas", {})
            lineas.append("- v%d %s fase %s it %d: %s · req %s/%s · tests %s/%s · consola %s%s" % (
                v["n"], v["commit"][:8], v["fase"], v["iteracion"], v["decision"].upper(),
                m.get("req_ok", "?"), m.get("req_total", "?"), m.get("tests_ok", "?"), m.get("tests_total", "?"),
                m.get("consola_errores", "?"), (" · " + "; ".join(v["motivos"])[:160]) if v.get("motivos") else ""))
    if est.get("veredicto"):
        lineas.append("")
        lineas.append("VEREDICTO: " + est["veredicto"])
    texto = "\n".join(lineas)
    if len(texto) > tope_chars:
        texto = texto[:tope_chars] + "\n... (estado truncado; usa fases_estado para el detalle)"
    return texto


def resumen_para_prompt(est: dict) -> str:
    return render_md(est, para_modelo=True, tope_chars=4500)
