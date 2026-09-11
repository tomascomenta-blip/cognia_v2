# -*- coding: utf-8 -*-
"""
cognia/agent/cierre_programas.py
================================
Al terminar una tarea, Cognia CIERRA los programas que abrio y ya no necesita,
y MANTIENE los que el usuario si quiere (2026-09-10).

Pedido del dueno: "siempre que acabe una tarea, que cierre los programas si
ELLA ya no los necesita; pero si el usuario si, entonces que los mantenga".

Que se cierra y que no (politica `auto`, la de defecto):
  * Solo lo que Cognia LANZO en esta tarea (app_tools: app_lanzar, mesa_lanzar,
    blender_abrir, godot_abrir, abrir_en_escritorio...). Jamas una ventana del
    usuario: las suyas no estan en el registro.
  * Se MANTIENE si:
      - el agente lo marco con `programa_mantener <app_id|nombre>` (lo decidio
        ella: p.ej. el usuario le pidio dejarlo abierto a mitad de tarea);
      - la PETICION del usuario era abrir/mostrar/dejar abierto algo ("abreme
        la calculadora", "dejalo abierto", "quiero ver..."): el entregable ES
        el programa abierto;
      - la ventana ya NO esta en la mesa (el usuario la movio a su escritorio:
        la esta usando).
  * Antes de cerrar, cada programa con HOOK guarda lo suyo (Blender guarda el
    .blend). Los hooks son el punto de extension: HOOKS_ANTES[exe] = fn(app).
Politicas: `auto` (lo de arriba), `siempre` (cierra todo lo lanzado, salvo lo
marcado), `nunca` (no cierra nada). Config `cierre_programas`, `/cierre`.
Todo fallo pasa por `_degradado`; el cierre nunca rompe la respuesta.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

try:
    from cognia.agent import app_tools as AT
    from cognia.agent import escritorio_propio as EP
except Exception:
    AT = None
    EP = None

POLITICAS = ("auto", "siempre", "nunca")

# app_id -> motivo por el que se mantiene (lo marco el agente en esta tarea)
_MANTENER: dict = {}
# instante en que empezo la tarea en curso (solo se tocan apps lanzadas despues)
_INICIO: dict = {"ts": 0.0, "tarea": ""}
_ULTIMO: dict = {"cerradas": [], "mantenidas": [], "motivos": {}, "ts": 0.0}

# exe (minusculas) -> fn(app: dict) -> str  (que hacer ANTES de cerrarlo)
HOOKS_ANTES: dict = {}

# la peticion pide que algo QUEDE abierto / a la vista del usuario
_RE_QUIERE_ABIERTO = re.compile(
    r"\b(abr[eií]me|ábreme|abre(me)?|abrir|abrí|abra|muestra(me)?|muéstrame|mostrar|"
    r"d[eé]ja(me|lo|la)?\s+abiert[oa]s?|dejalo|déjalo|mant[eé]n(lo|la)?|quiero\s+ver(lo|la)?|"
    r"para\s+que\s+(yo\s+)?(lo|la)?\s*(vea|use|revise|siga)|no\s+(lo|la)?\s*cierres|"
    r"lanza(me)?|ejecuta(me)?\s+\S+\.exe|pon(me)?\s+(la|el)\s+\w+\s+(en|abiert))", re.I)


def _degradado(motivo: str) -> None:
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado("cierre_programas", motivo)
    except Exception:
        import sys
        print("[cognia] cierre_programas degradado: %s" % motivo, file=sys.stderr)


def politica() -> str:
    import os
    crudo = os.environ.get("COGNIA_CIERRE_PROGRAMAS", "").strip().lower()
    if crudo in POLITICAS:
        return crudo
    try:
        ruta = Path.home() / ".cognia_config.json"
        if ruta.exists():
            with ruta.open(encoding="utf-8") as fh:
                v = str(json.load(fh).get("cierre_programas", "auto")).lower()
                if v in POLITICAS:
                    return v
    except Exception as exc:
        _degradado("config ilegible: %s" % exc)
    return "auto"


def empezar_tarea(tarea: str = "") -> None:
    """Marca el inicio: solo lo lanzado a partir de ahora entra en el cierre."""
    _INICIO["ts"] = time.time()
    _INICIO["tarea"] = (tarea or "")[:500]
    _MANTENER.clear()


def marcar(quien: str, motivo: str = "") -> dict:
    """El agente pide conservar un programa: por app_id (a3) o por trozo de
    titulo/comando/exe. Devuelve {ok, app_ids, detalle}."""
    q = (quien or "").strip().strip("\"'").lower()
    if not q:
        return {"ok": False, "app_ids": [], "detalle": "falta a quien mantener (app_id, titulo o exe)"}
    ids = []
    for app_id, a in _lanzadas().items():
        if q == app_id or q in (a.get("titulo") or "").lower() or q in (a.get("cmd") or "").lower() \
                or q in _exe(a):
            ids.append(app_id)
    if not ids and q in ("todo", "todos", "todas", "*"):
        ids = list(_lanzadas())
    if not ids:
        # se acepta igual: quiza lo lanza despues (se resuelve al terminar)
        _MANTENER[q] = motivo or "pedido por el agente"
        return {"ok": True, "app_ids": [], "detalle": "no hay ninguna app lanzada que coincida con %r; "
                                                       "queda anotado por nombre" % q}
    for i in ids:
        _MANTENER[i] = motivo or "pedido por el agente"
    return {"ok": True, "app_ids": ids, "detalle": "se mantendran: " + ", ".join(ids)}


def usuario_lo_quiere_abierto(tarea: str) -> bool:
    return bool(_RE_QUIERE_ABIERTO.search(tarea or ""))


def _lanzadas() -> dict:
    """app_id -> app de las lanzadas por Cognia (vivas) en ESTA tarea."""
    if AT is None:
        return {}
    fuera = {}
    for app_id, a in list(AT._APPS.items()):
        if float(a.get("ts") or 0) < _INICIO["ts"]:
            continue
        fuera[app_id] = a
    return fuera


def _exe(a: dict) -> str:
    try:
        return AT._exe_de(a.get("pid", 0)) if AT is not None else ""
    except Exception:
        return ""


def _en_la_mesa(a: dict) -> bool:
    """True si la ventana sigue en el escritorio de Cognia (o no se puede saber)."""
    if EP is None or not a.get("mudada"):
        return True
    try:
        hw = {h for h, _p, _t in EP.ventanas_en_escritorio()}
        return a.get("hwnd", 0) in hw or not EP.ventana_viva(a.get("hwnd", 0))
    except Exception as exc:
        _degradado("ventanas_en_escritorio: %s" % exc)
        return True


def decidir(tarea: str, pol: str = None) -> dict:
    """Que se cierra y que se mantiene, con motivo. No toca nada."""
    pol = pol or politica()
    cerrar, mantener, motivos = [], [], {}
    apps = _lanzadas()
    quiere = usuario_lo_quiere_abierto(tarea)
    for app_id, a in apps.items():
        exe = _exe(a)
        titulo = (a.get("titulo") or "").lower()
        marcado = app_id in _MANTENER or any(
            (k not in apps) and (k in titulo or k in (a.get("cmd") or "").lower() or k in exe)
            for k in _MANTENER)
        if pol == "nunca":
            mantener.append(app_id); motivos[app_id] = "politica 'nunca'"
        elif marcado:
            mantener.append(app_id); motivos[app_id] = "marcado por el agente (%s)" % _MANTENER.get(app_id, "por nombre")
        elif pol == "auto" and quiere:
            mantener.append(app_id); motivos[app_id] = "el usuario pidio abrirlo/verlo"
        elif pol == "auto" and not _en_la_mesa(a):
            mantener.append(app_id); motivos[app_id] = "el usuario se lo llevo a su escritorio"
        else:
            cerrar.append(app_id); motivos[app_id] = "Cognia ya no lo necesita"
    return {"cerrar": cerrar, "mantener": mantener, "motivos": motivos, "politica": pol, "apps": apps}


def al_terminar(tarea: str, resultado: str = "") -> dict:
    """Cierra lo sobrante segun la politica. {cerradas: [(id, titulo, detalle)], mantenidas: [...]}."""
    out = {"cerradas": [], "mantenidas": [], "motivos": {}, "politica": politica()}
    if AT is None or not _INICIO["ts"]:
        return out
    try:
        d = decidir(tarea)
    except Exception as exc:
        _degradado("decidir: %s" % exc)
        return out
    out["motivos"] = d["motivos"]
    for app_id in d["mantener"]:
        a = d["apps"][app_id]
        out["mantenidas"].append((app_id, a.get("titulo") or a.get("cmd", ""), d["motivos"][app_id]))
    for app_id in d["cerrar"]:
        a = d["apps"][app_id]
        exe = _exe(a)
        antes = ""
        hook = HOOKS_ANTES.get(exe)
        if hook is not None:
            try:
                antes = hook(a) or ""
            except Exception as exc:
                _degradado("hook antes de cerrar %s: %s" % (exe, exc))
                antes = "hook fallo: %s" % str(exc)[:80]
        try:
            det = AT.cerrar(app_id)
        except Exception as exc:
            _degradado("cerrar %s: %s" % (app_id, exc))
            det = "no se pudo cerrar: %s" % str(exc)[:80]
        out["cerradas"].append((app_id, a.get("titulo") or a.get("cmd", ""), (antes + "; " if antes else "") + det))
    _ULTIMO.update({"cerradas": out["cerradas"], "mantenidas": out["mantenidas"], "motivos": out["motivos"],
                    "ts": time.time()})
    return out


def texto(out: dict) -> str:
    """Una linea legible para el usuario ('' si no paso nada)."""
    partes = []
    if out.get("cerradas"):
        partes.append("cerré " + ", ".join("%s (%s)" % (t[:30] or i, i) for i, t, _d in out["cerradas"]))
    if out.get("mantenidas"):
        partes.append("dejé abierto " + ", ".join("%s: %s" % (t[:30] or i, m) for i, t, m in out["mantenidas"]))
    return "; ".join(partes)


def ultimo() -> dict:
    return dict(_ULTIMO)


def _instalar_hooks() -> None:
    try:
        from cognia.agent import taller_tools as TT
        HOOKS_ANTES["blender.exe"] = TT.guardar_antes_de_cerrar
    except Exception as exc:
        _degradado("hook de Blender no instalado: %s" % exc)


def register(tool) -> None:
    _instalar_hooks()

    @tool("programa_mantener",
          "programa_mantener <app_id|titulo|exe> [| motivo=...] -- no cerrar ese programa al acabar la tarea",
          desc="Al terminar la tarea Cognia cierra sola los programas que abrio (Blender, Godot, apps de la "
               "mesa) si ya no los necesita. Llama a esto para CONSERVAR uno que el usuario quiere seguir "
               "usando (p.ej. te pidio dejarlo abierto, o el resultado es el programa abierto). Acepta el "
               "app_id (a3), un trozo del titulo o el exe; 'todos' los mantiene todos.",
          params=[{"nombre": "quien", "tipo": "string", "requerido": True,
                   "descripcion": "app_id, trozo del titulo, exe, o 'todos'"},
                  {"nombre": "motivo", "tipo": "string", "requerido": False, "clave": True,
                   "descripcion": "por que se mantiene"}],
          danger=False, timeout_s=10)
    def _programa_mantener(args, ctx):
        from cognia.agent import pruebas_comun as PC
        quien, o = PC.partir_args(args, ("motivo",))
        r = marcar(quien, o.get("motivo", ""))
        return "RESULTADO programa_mantener%s: %s" % ("" if r["ok"] else " ERROR", r["detalle"])
