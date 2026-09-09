# -*- coding: utf-8 -*-
"""
cognia/agent/pruebas_tools.py
=============================
La FAMILIA DE PRUEBAS del agente (2026-09-07). Pedido del dueno: "anade aun
mas herramientas para que Cognia pueda testear y probar sus propios resultados;
se queja mucho de cosas que no le dejan probar; que pueda ver y renderizar bien
todo".

Este modulo es el CONCENTRADOR: carga cada sub-familia (cada una en su propio
fichero, con su `register(tool)`) y registra dos puertas propias:

  probar <objetivo> [| pasos=...]   decide QUE prueba toca por el tipo del
                                    objetivo (extension, URL, comando, carpeta)
                                    y la corre; `probar ayuda [tema]` ensena
                                    las tools de la familia por tema.
  pruebas_estado                    que sub-familias cargaron, con que
                                    backend, y el ultimo error de cada una.

Sub-familias (fichero -> prefijos):
  pagina_tools     pagina_*          navegador persistente (Playwright)
  captura_tools    captura_*         imagenes: inspeccionar, diff, recortar, mosaico
  medios_tools     audio_* video_*   ffprobe/ffmpeg/soundfile
  formato_tools    formato_validar, diff_texto, sql_probar, pdf_*, docx_*, xlsx_*,
                   modelo3d_*, py_lint/importar/perfilar/cobertura, http_solicitud,
                   puerto_esperar, esperar_fichero, consola_sesion, tui_probar
  app_tools        app_*             apps graficas en el escritorio propio

Flag: COGNIA_PRUEBAS (default ENCENDIDO via config `pruebas_tools`; se apaga con
COGNIA_PRUEBAS=0 o /pruebas off). Punto de extension: SUBFAMILIAS (una entrada
por modulo) y DESPACHO (extension -> tool) en este fichero.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import time
from pathlib import Path

from cognia.agent import pruebas_comun as PC

# modulo -> (etiqueta, prefijos/nombres que aporta). El orden es el de carga.
SUBFAMILIAS = (
    ("cognia.agent.captura_tools", "imagenes", ("captura_",)),
    ("cognia.agent.medios_tools", "audio y video", ("audio_", "video_", "medios_estado")),
    ("cognia.agent.formato_tools", "formatos y documentos",
     ("formato_", "diff_texto", "sql_probar", "pdf_", "docx_", "xlsx_", "modelo3d_",
      "py_lint", "py_importar", "py_perfilar", "py_cobertura", "http_solicitud",
      "puerto_esperar", "esperar_fichero", "consola_sesion", "tui_probar")),
    ("cognia.agent.pagina_tools", "paginas web", ("pagina_",)),
    ("cognia.agent.app_tools", "apps graficas", ("app_",)),
    ("cognia.agent.mesa_tools", "segundo puesto (mesa)", ("mesa_",)),
)

# Estado de carga por modulo (puerta pruebas_estado / /pruebas estado)
_CARGA: dict = {}
_ULTIMO: dict = {"tool": "", "objetivo": "", "ruta": "", "ts": 0.0}


def _avisar(origen: str, motivo: str) -> None:
    """Degradacion VISIBLE: por _aviso_degradado del CLI si existe, si no stderr."""
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado(origen, motivo)
    except Exception:
        print("[degradado] %s: %s" % (origen, motivo), file=sys.stderr)


def cargar_subfamilias(tool) -> dict:
    """Importa y registra cada sub-familia. Devuelve {modulo: {ok, tools, error}}."""
    from cognia.agent import tools as _T
    for ruta, etiqueta, _pref in SUBFAMILIAS:
        antes = set(_T.TOOLS)
        try:
            mod = importlib.import_module(ruta)
            mod.register(tool)
            nuevas = sorted(set(_T.TOOLS) - antes)
            _CARGA[ruta] = {"ok": True, "etiqueta": etiqueta, "tools": nuevas, "error": ""}
        except Exception as exc:
            _CARGA[ruta] = {"ok": False, "etiqueta": etiqueta, "tools": [],
                            "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}
            _avisar("pruebas:" + ruta.rsplit(".", 1)[-1], _CARGA[ruta]["error"])
    return dict(_CARGA)


def estado() -> dict:
    return {"carga": {k: dict(v) for k, v in _CARGA.items()}, "ultimo": dict(_ULTIMO)}


# ---------------------------------------------------------------------------
# probar: despacho por tipo
# ---------------------------------------------------------------------------

# extension -> (tool, como armar los args). El punto de extension: una linea
# por tipo nuevo. `{r}` es la ruta resuelta, `{o}` las opciones extra.
DESPACHO = {
    ".html": "renderizar", ".htm": "renderizar", ".svg": "renderizar", ".md": "renderizar",
    ".markdown": "renderizar", ".css": "renderizar", ".js": "renderizar", ".mjs": "renderizar",
    ".png": "captura_inspeccionar", ".jpg": "captura_inspeccionar", ".jpeg": "captura_inspeccionar",
    ".gif": "captura_inspeccionar", ".webp": "captura_inspeccionar", ".bmp": "captura_inspeccionar",
    ".wav": "audio_inspeccionar", ".mp3": "audio_inspeccionar", ".ogg": "audio_inspeccionar",
    ".flac": "audio_inspeccionar", ".m4a": "audio_inspeccionar",
    ".mp4": "video_inspeccionar", ".webm": "video_inspeccionar", ".mkv": "video_inspeccionar",
    ".avi": "video_inspeccionar", ".mov": "video_inspeccionar",
    ".pdf": "pdf_inspeccionar", ".docx": "docx_texto", ".xlsx": "xlsx_leer",
    ".obj": "modelo3d_inspeccionar", ".stl": "modelo3d_inspeccionar", ".glb": "modelo3d_inspeccionar",
    ".gltf": "modelo3d_inspeccionar", ".ply": "modelo3d_inspeccionar",
    ".json": "formato_validar", ".yaml": "formato_validar", ".yml": "formato_validar",
    ".toml": "formato_validar", ".xml": "formato_validar", ".csv": "formato_validar",
    ".ini": "formato_validar", ".cfg": "formato_validar", ".sql": "formato_validar",
    ".txt": "formato_validar",
    ".exe": "app_probar",
}

_RE_GUI = re.compile(r"^\s*(import|from)\s+(pygame|tkinter|PyQt\d|PySide\d|wx|kivy|arcade|pyglet|customtkinter)\b", re.M)
_RE_INPUT = re.compile(r"\binput\s*\(")
_RE_SERVIDOR = re.compile(r"\b(app\.run\(|uvicorn|flask|fastapi|http\.server|serve_forever|socketserver)\b", re.I)
_RE_PYTEST = re.compile(r"^\s*def\s+test_\w+", re.M)


def _run(nombre: str, args: str, ctx) -> str:
    from cognia.agent.tools import run_tool
    return run_tool(nombre, args, ctx)


def _texto(ruta: Path, maximo: int = 200000) -> str:
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")[:maximo]
    except Exception:
        return ""


def _probar_python(ruta: Path, opciones: dict, ctx) -> str:
    """Un .py: sintaxis + lint siempre; luego segun lo que importa: GUI ->
    app_probar; input() -> ejecutar_guion; tests -> tests; servidor -> aviso;
    resto -> ejecutar con timeout corto."""
    src = _texto(ruta)
    partes = [_run("py_validar", str(ruta), ctx), _run("py_lint", str(ruta), ctx)]
    cwd = str(ruta.parent)
    pasos = opciones.get("pasos", "")
    if _RE_GUI.search(src):
        args = "python \"%s\" | cwd=%s" % (ruta, cwd)
        if pasos:
            args += " | pasos=%s" % pasos
        partes.append(_run("app_probar", args, ctx))
    elif _RE_PYTEST.search(src):
        partes.append(_run("tests", str(ruta), ctx))
    elif _RE_INPUT.search(src):
        entradas = opciones.get("entradas") or pasos or ""
        partes.append(_run("ejecutar_guion", "python \"%s\" | entradas=%s | cwd=%s" % (ruta, entradas, cwd), ctx))
    elif _RE_SERVIDOR.search(src):
        partes.append("es un SERVIDOR: arrancalo con ejecutar_fondo python \"%s\", espera el puerto con "
                      "puerto_esperar <puerto> y prueba con renderizar http://127.0.0.1:<puerto> o http_solicitud" % ruta)
    else:
        partes.append(_run("ejecutar", "python \"%s\" | timeout=%s | cwd=%s" % (ruta, opciones.get("timeout", "60"), cwd), ctx))
    return "\n".join(partes)


def _probar_directorio(ruta: Path, ctx) -> str:
    """Inventario de lo probable dentro de una carpeta (sin recursion profunda)."""
    conteo: dict = {}
    ejemplos: dict = {}
    for p in sorted(ruta.rglob("*"))[:3000]:
        if p.is_file() and not any(s in p.parts for s in ("node_modules", ".git", "__pycache__", "venv", "venv312", ".cognia_scratch")):
            ext = p.suffix.lower()
            if ext in DESPACHO or ext == ".py":
                conteo[ext] = conteo.get(ext, 0) + 1
                ejemplos.setdefault(ext, str(p.relative_to(ruta)))
    if not conteo:
        return "RESULTADO probar %s: carpeta sin ficheros probables (html, py, png, wav, pdf, json...)" % ruta
    lineas = ["carpeta %s: %d tipo(s) probables" % (ruta, len(conteo))]
    for ext, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
        lineas.append("  %s x%d -> probar %s  (%s)" % (ext, n, ejemplos[ext], DESPACHO.get(ext, "python: sintaxis+lint+ejecucion")))
    if (ruta / "index.html").exists():
        lineas.append("  hay index.html: probar index.html (o pagina_servir %s para modulos ES/fetch)" % ruta)
    if (ruta / "package.json").exists():
        lineas.append("  hay package.json: ejecutar npm test | cwd=%s" % ruta)
    if any((ruta / n).exists() for n in ("pytest.ini", "pyproject.toml", "tests")):
        lineas.append("  hay tests de Python: tests %s" % ruta)
    return "RESULTADO probar:\n" + "\n".join(lineas)


def probar(objetivo: str, opciones: dict, ctx) -> str:
    obj = (objetivo or "").strip().strip("\"'")
    if not obj:
        return ("RESULTADO probar ERROR: falta el objetivo. Uso: probar <ruta|URL|comando|carpeta> "
                "[| pasos=...] · probar ayuda [tema] · probar estado")
    bajo = obj.lower()
    if bajo in ("ayuda", "help", "?"):
        return ayuda(opciones.get("tema", ""))
    if bajo.startswith("ayuda "):
        return ayuda(obj.split(None, 1)[1])
    if bajo == "estado":
        return texto_estado()
    _ULTIMO.update({"tool": "probar", "objetivo": obj, "ts": time.time()})
    if re.match(r"^https?://", obj, re.I):
        args = obj
        if opciones.get("pasos"):
            args += " | guion=%s" % opciones["pasos"]
        r = _run("renderizar", args, ctx)
        if "ERROR" not in r.split("\n", 1)[0]:
            r += "\n" + _run("pagina_abrir", obj, ctx).split("\n", 1)[0]
            r += "\n" + _run("pagina_enlaces", "", ctx)
            r += "\n" + _run("pagina_red", "fallos=1", ctx)
        return r.replace("RESULTADO renderizar", "RESULTADO probar (renderizar)", 1)
    # ruta?
    try:
        ruta = PC.resolver_ruta(obj, ctx=ctx)
    except ValueError:
        ruta = None
    if ruta is None:
        # no es fichero: comando. Con ventana -> app_probar; si no -> ejecutar_guion/ejecutar
        primero = obj.split()[0].lower()
        if primero in ("python", "python3", "py") and len(obj.split()) > 1:
            cand = obj.split()[1].strip("\"'")
            try:
                ruta2 = PC.resolver_ruta(cand, ctx=ctx)
                if ruta2.suffix.lower() == ".py":
                    return _probar_python(ruta2, opciones, ctx).replace("RESULTADO", "RESULTADO probar ->", 1)
            except ValueError:
                pass
        args = obj
        if opciones.get("pasos"):
            args += " | pasos=%s" % opciones["pasos"]
        if opciones.get("cwd"):
            args += " | cwd=%s" % opciones["cwd"]
        r = _run("app_probar", args, ctx)
        if "sin abrir ventana" in r or "no aparecio ninguna ventana" in r:
            r += "\n(sin ventana: si pide teclado usa ejecutar_guion %s | entradas=...; si no, ejecutar %s)" % (obj, obj)
        return r.replace("RESULTADO app_probar", "RESULTADO probar (app_probar)", 1)
    _ULTIMO["ruta"] = str(ruta)
    if ruta.is_dir():
        return _probar_directorio(ruta, ctx)
    ext = ruta.suffix.lower()
    if ext == ".py":
        return _probar_python(ruta, opciones, ctx).replace("RESULTADO", "RESULTADO probar ->", 1)
    tool = DESPACHO.get(ext)
    if tool is None:
        return _run("formato_validar", str(ruta), ctx).replace("RESULTADO formato_validar", "RESULTADO probar (formato_validar)", 1)
    args = str(ruta)
    if tool == "renderizar":
        if opciones.get("pasos"):
            args += " | guion=%s" % opciones["pasos"]
        r = _run("renderizar", args, ctx)
        if ext in (".html", ".htm"):
            r += "\n" + _run("formato_validar", str(ruta), ctx)
        return r.replace("RESULTADO renderizar", "RESULTADO probar (renderizar)", 1)
    if tool == "app_probar":
        args = "\"%s\"" % ruta
        if opciones.get("pasos"):
            args += " | pasos=%s" % opciones["pasos"]
    r = _run(tool, args, ctx)
    return r.replace("RESULTADO " + tool, "RESULTADO probar (%s)" % tool, 1)


# ---------------------------------------------------------------------------
# ayuda: las tools de la familia por tema (para que el modelo las descubra
# sin pagar sus schemas en cada turno)
# ---------------------------------------------------------------------------

_TEMAS = {
    "web": ("pagina_", "renderizar"),
    "pagina": ("pagina_", "renderizar"),
    "imagen": ("captura_",), "imagenes": ("captura_",), "captura": ("captura_",),
    "audio": ("audio_", "medios_estado"), "video": ("video_", "medios_estado"), "medios": ("audio_", "video_", "medios_estado"),
    "app": ("app_",), "apps": ("app_",), "gui": ("app_",), "juego": ("app_", "renderizar", "ejecutar_guion"),
    "mesa": ("mesa_",), "puesto": ("mesa_",), "raton": ("mesa_",), "escritorio": ("mesa_", "app_"),
    "formato": ("formato_", "diff_texto", "sql_probar"), "formatos": ("formato_", "diff_texto", "sql_probar"),
    "documentos": ("pdf_", "docx_", "xlsx_"), "pdf": ("pdf_",), "3d": ("modelo3d_",),
    "python": ("py_", "tests"), "consola": ("ejecutar_guion", "consola_sesion", "tui_probar"),
    "red": ("http_solicitud", "puerto_esperar", "pagina_servir", "pagina_red"),
}


def ayuda(tema: str = "") -> str:
    from cognia.agent.tools import TOOLS
    t = (tema or "").strip().lower()
    if not t:
        lineas = ["RESULTADO probar ayuda: `probar <ruta|URL|comando>` elige la prueba por el tipo. Temas: "
                  + ", ".join(sorted(set(_TEMAS))) + ". Escribe `probar ayuda <tema>` para ver sus tools."]
        for ruta, etiqueta, _p in SUBFAMILIAS:
            c = _CARGA.get(ruta, {})
            lineas.append("  %s: %s" % (etiqueta, ", ".join(c.get("tools", [])) or ("NO CARGO: " + c.get("error", "?"))))
        lineas.append("  ya existian: renderizar (paginas con guion), ejecutar_guion (consola), tests, py_validar, json_validar")
        return "\n".join(lineas)
    patrones = _TEMAS.get(t)
    if not patrones:
        return "RESULTADO probar ayuda ERROR: tema %r desconocido. Temas: %s" % (t, ", ".join(sorted(set(_TEMAS))))
    docs = [spec["doc"] for n, spec in TOOLS.items()
            if any(n == p or (p.endswith("_") and n.startswith(p)) for p in patrones)]
    if not docs:
        return "RESULTADO probar ayuda %s: ninguna tool cargada para ese tema (ver pruebas_estado)" % t
    return "RESULTADO probar ayuda %s (%d tools):\n%s" % (t, len(docs), "\n".join("  " + d for d in docs))


def texto_estado() -> str:
    lineas = []
    for ruta, etiqueta, _p in SUBFAMILIAS:
        c = _CARGA.get(ruta)
        if c is None:
            lineas.append("  %s: no cargada (flag apagado)" % etiqueta)
        elif c["ok"]:
            lineas.append("  %s: %d tools" % (etiqueta, len(c["tools"])))
        else:
            lineas.append("  %s: ERROR %s" % (etiqueta, c["error"]))
    try:
        from cognia.agent import renderizador as _rz
        d = _rz.disponibilidad()
        lineas.append("  navegador: playwright %s · sistema %s" % ("si" if d["playwright"] else "no", d["sistema"] or "ninguno"))
    except Exception as exc:
        lineas.append("  navegador: %s" % exc)
    try:
        from cognia.agent import escritorio_propio as _ep
        e = _ep.estado()
        lineas.append("  escritorio propio: %s%s" % ("activo" if e["activo"] else "inactivo", (" (" + e["motivo"] + ")") if e.get("motivo") else ""))
    except Exception as exc:
        lineas.append("  escritorio propio: %s" % exc)
    for b in ("ffmpeg", "node"):
        try:
            PC.binario(b)
            lineas.append("  %s: si" % b)
        except ValueError:
            lineas.append("  %s: NO" % b)
    return "RESULTADO pruebas_estado (flag COGNIA_PRUEBAS=%s):\n%s" % (os.environ.get("COGNIA_PRUEBAS", "1"), "\n".join(lineas))


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def register(tool) -> None:
    cargar_subfamilias(tool)

    @tool("probar",
          "probar <ruta|URL|comando|carpeta> [| pasos=...] [| entradas=1|2|q]  -- PRUEBA lo que sea por su tipo: "
          "html/svg/md/css/js -> renderizar; png/jpg -> captura_inspeccionar; wav/mp3 -> audio_inspeccionar; "
          "mp4/gif -> video; pdf/docx/xlsx/obj -> lectores; json/yaml/csv/xml -> formato_validar; .py -> sintaxis+lint+"
          "ejecucion (GUI -> app_probar, input() -> ejecutar_guion); comando con ventana -> app_probar; carpeta -> inventario. "
          "`probar ayuda [tema]` lista las tools de prueba (web, imagen, audio, video, app, formato, documentos, python, consola, red)",
          desc="La puerta unica para COMPROBAR un resultado propio: dale una ruta, una URL, un comando o una carpeta "
               "y elige la prueba adecuada por el tipo (renderiza paginas, inspecciona imagenes/audio/video, valida "
               "formatos, lee PDF/DOCX/XLSX/3D, ejecuta .py con lint y, si abre ventana o pide teclado, lo prueba "
               "con pasos). Con pasos= (misma gramatica que renderizar guion / app_teclas) prueba interaccion. "
               "`probar ayuda <tema>` te ensena las tools especializadas de ese tema para usarlas directamente. "
               "Usala SIEMPRE antes de dar por terminado algo que se ve, suena o se ejecuta.",
          params=[{"nombre": "objetivo", "tipo": "string", "requerido": True,
                   "descripcion": "ruta, URL, comando, carpeta, o 'ayuda [tema]' / 'estado'"},
                  {"nombre": "pasos", "tipo": "string", "requerido": False, "clave": True,
                   "descripcion": "pasos interactivos separados por ';' (tecla derecha*3; clic #btn; captura; assert ...)"},
                  {"nombre": "entradas", "tipo": "string", "requerido": False, "clave": True,
                   "descripcion": "entradas de teclado para programas de consola (1|4|q)"},
                  {"nombre": "timeout", "tipo": "integer", "requerido": False, "clave": True,
                   "descripcion": "segundos para la ejecucion de un .py (default 60)"},
                  {"nombre": "tema", "tipo": "string", "requerido": False, "clave": True,
                   "descripcion": "tema de ayuda (web, imagen, audio, video, app, formato, documentos, python, consola, red)"}],
          timeout_s=420)
    def _probar(args, ctx):
        objetivo, o = PC.partir_args(args, ("pasos", "entradas", "timeout", "tema", "cwd"))
        try:
            return probar(objetivo, o, ctx)
        except Exception as exc:
            return "RESULTADO probar ERROR: %s: %s" % (type(exc).__name__, str(exc)[:300])

    @tool("pruebas_estado",
          "pruebas_estado  -- que familias de prueba cargaron (web, imagen, audio/video, formatos, apps), backends y errores",
          desc="Diagnostico de la familia de pruebas: sub-familias cargadas, tools por cada una, navegador headless, "
               "escritorio propio, ffmpeg/node, y el ultimo error de carga.",
          params=[], timeout_s=30)
    def _pruebas_estado(args, ctx):
        return texto_estado()


def ultimo() -> dict:
    return dict(_ULTIMO)
