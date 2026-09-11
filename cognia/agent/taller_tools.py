# -*- coding: utf-8 -*-
"""
cognia/agent/taller_tools.py
============================
El TALLER (2026-09-10): Blender y Godot para el agente, en la MESA (el
escritorio propio de Cognia), con referencias sacadas de internet.

Pedido del dueno: "que Cognia en su monitor pueda construir cosas en Blender
mediante imagenes de referencia que sacaria de internet, con diferentes
angulos del personaje; instala Blender y el MCP; y que pueda programar en
Godot".

Dos familias, `blender_*` y `godot_*`, mas `taller_estado`:

  blender_abrir [fichero.blend]       Blender en la mesa con el addon de
                                      blender-mcp encendido y el MCP conectado
  blender_referencias <personaje>     busca en internet frente/lado/atras/hoja
                                      de modelo, las baja y las coloca en la
                                      escena como planos de referencia
  blender_codigo <python bpy>         ejecuta codigo dentro de Blender
  blender_escena                      que hay en la escena
  blender_ver [angulo] [modo]         imagen del viewport o un render limpio
                                      (workbench) desde frente/lado/arriba/
                                      perspectiva para comparar con las refs
  blender_guardar [ruta.blend]        guarda el .blend
  blender_exportar <ruta.glb|.fbx|.obj|.stl>
  blender_cerrar                      cierra Blender (guardando antes)

  godot_proyecto <nombre|ruta> [tipo=2d|3d]   crea un proyecto minimo que corre
  godot_verificar <proyecto>          parsea todos los .gd y carga la escena
                                      principal sin ventana: los errores, listados
  godot_correr <proyecto> [segundos=] [ventana=1]  corre el proyecto y devuelve
                                      su salida (errores marcados)
  godot_abrir <proyecto>              el editor de Godot en la mesa
  godot_cerrar

COMO HABLA CON BLENDER. Por el MCP oficial (ahujasid/blender-mcp, instalado
con `uv tool install blender-mcp`; su addon vive en ~/.cognia/mcp/
blender_addon.py y se registra al arrancar Blender con --python, que abre el
socket 9876 solo). El cliente es el mismo de tools_mcp (`mcp blender | ...`
sigue valiendo para las 28 herramientas del servidor: PolyHaven, Sketchfab,
Hyper3D...). Estas tools son la CAPA CORTA: el modelo no tiene que armar JSON
ni acordarse de nombres, y las capturas vuelven como RUTA de fichero.

COMO HABLA CON GODOT. Godot 4.7 (winget) se maneja por su binario: `--headless
--check-only --script` parsea un .gd, `--headless --quit-after` carga la
escena principal, y el editor / el juego se lanzan en la mesa con app_tools.
El MCP de Godot (Coding-Solo/godot-mcp, ~/.cognia/mcp/godot-mcp) queda
disponible via `mcp godot | ...` (create_scene, add_node, load_sprite...).

OPT-IN: familia encendida por defecto (config `taller_tools`), se apaga con
COGNIA_TALLER=0 o `/taller off`. Rutas: config `taller_blender` /
`taller_godot` o env COGNIA_BLENDER_EXE / COGNIA_GODOT_EXE.

Todo fallo pasa por `_degradado` (nunca `except: pass` mudo).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from cognia.agent import pruebas_comun as PC

try:
    from cognia.agent import app_tools as AT
    from cognia.agent import escritorio_propio as EP
except Exception:      # sin escritorio propio (linux, sin pyvda): se dice
    AT = None
    EP = None
try:
    from cognia.agent import mesa as M
except Exception:
    M = None

CARPETA = Path.home() / ".cognia" / "taller"
ADDON = Path.home() / ".cognia" / "mcp" / "blender_addon.py"
ARRANQUE = CARPETA / "arranque_blender.py"
PUERTO_BLENDER = 9876
ESPERA_BLENDER_S = 90
ANGULOS = ("frente", "lado", "atras", "hoja")
# angulo -> (posicion, rotacion en grados) del plano de referencia en la escena
_POSES = {
    "frente": ((0.0, 3.0, 0.0), (90.0, 0.0, 0.0)),
    "atras": ((0.0, -3.0, 0.0), (90.0, 0.0, 180.0)),
    "lado": ((-3.0, 0.0, 0.0), (90.0, 0.0, 90.0)),
    "lado_der": ((3.0, 0.0, 0.0), (90.0, 0.0, -90.0)),
    "arriba": ((0.0, 0.0, -3.0), (0.0, 0.0, 0.0)),
    # la hoja de modelo mira hacia la vista por defecto del viewport (+X,-Y):
    # con Z=-45 quedaba de canto (cazado en el primer e2e, 2026-09-10)
    "hoja": ((3.5, 3.5, 1.5), (90.0, 0.0, 45.0)),
}
_CONSULTAS = {
    "frente": "{p} front view",
    "lado": "{p} side view",
    "atras": "{p} back view",
    "hoja": "{p} character turnaround reference sheet",
}

# estado vivo de la sesion: que abrio el taller y que paso la ultima vez
_ESTADO: dict = {
    "blender": {"app_id": "", "pid": 0, "hwnd": 0, "fichero": "", "conectado": False, "error": ""},
    "godot": {"app_id": "", "pid": 0, "proyecto": "", "error": ""},
}
_ULTIMO: dict = {"tool": "", "detalle": "", "ts": 0.0}


def _anotar(tool: str, detalle: str) -> None:
    _ULTIMO.update({"tool": tool, "detalle": str(detalle)[:300], "ts": time.time()})


def ultimo() -> dict:
    return dict(_ULTIMO)


def _degradado(motivo: str) -> None:
    """Todo fallo del taller pasa por aqui (regla del repo: nada calla)."""
    _ESTADO.setdefault("errores", []).append("%s %s" % (time.strftime("%H:%M:%S"), motivo[:200]))
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado("taller", motivo)
    except Exception:
        import sys
        print("[cognia] taller degradado: %s" % motivo, file=sys.stderr)


def _cfg() -> dict:
    try:
        ruta = Path.home() / ".cognia_config.json"
        if ruta.exists():
            with ruta.open(encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:
        _degradado("config ilegible: %s" % exc)
    return {}


def encendido() -> bool:
    """El env manda; si no esta puesto, la config `taller_tools` (default ON)."""
    crudo = os.environ.get("COGNIA_TALLER", "").strip().lower()
    if crudo:
        return crudo in ("1", "on", "true", "yes", "si")
    return bool(_cfg().get("taller_tools", True))


def _err(tool: str, msg) -> str:
    return "RESULTADO %s ERROR: %s" % (tool, str(msg)[:900])


# ---------------------------------------------------------------------------
# Binarios
# ---------------------------------------------------------------------------

def blender_exe() -> str:
    """Ruta a blender.exe: config > env > PATH > instalaciones conocidas."""
    candidatos = [_cfg().get("taller_blender", ""), os.environ.get("COGNIA_BLENDER_EXE", ""),
                  shutil.which("blender") or ""]
    home = str(Path.home())
    patrones = [
        os.path.join(home, "AppData", "Local", "Programs", "Blender", "*", "blender.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Blender", "blender.exe"),
        r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages", "BlenderFoundation*", "*", "blender.exe"),
        "/usr/bin/blender", "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for pat in patrones:
        candidatos.extend(sorted(glob.glob(pat), reverse=True))
    for c in candidatos:
        if c and Path(c).is_file():
            return str(c)
    return ""


def godot_exe(consola: bool = False) -> str:
    """Ruta a Godot 4 (la variante _console escribe stdout en Windows)."""
    candidatos = [_cfg().get("taller_godot", ""), os.environ.get("COGNIA_GODOT_EXE", ""),
                  shutil.which("godot") or ""]
    home = str(Path.home())
    patrones = [
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages", "GodotEngine*", "Godot_v*_win64.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Godot", "Godot*.exe"),
        r"C:\Program Files\Godot\Godot*.exe",
        "/usr/bin/godot4", "/usr/bin/godot",
    ]
    for pat in patrones:
        candidatos.extend(sorted(glob.glob(pat), reverse=True))
    hallado = ""
    for c in candidatos:
        if c and Path(c).is_file() and "console" not in Path(c).name.lower():
            hallado = str(c)
            break
    if not hallado:
        for c in candidatos:
            if c and Path(c).is_file():
                hallado = str(c)
                break
    if hallado and consola:
        p = Path(hallado)
        con = p.with_name(p.stem + "_console" + p.suffix)
        if con.is_file():
            return str(con)
    return hallado


def _version_binario(exe: str, timeout: int = 20) -> str:
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return (r.stdout or r.stderr or "").strip().splitlines()[0][:80]
    except Exception as exc:
        return "(%s)" % type(exc).__name__


# ---------------------------------------------------------------------------
# Blender: arranque, socket y MCP
# ---------------------------------------------------------------------------

_ARRANQUE_SRC = '''# Arranque de Blender para Cognia (lo escribe cognia/agent/taller_tools.py):
# registra el addon de blender-mcp, que abre el socket %(puerto)d el solo.
import bpy, sys, os, importlib.util
ADDON = %(addon)r
MOD = "blender_mcp_addon"

def _arrancar():
    try:
        spec = importlib.util.spec_from_file_location(MOD, ADDON)
        m = importlib.util.module_from_spec(spec)
        sys.modules[MOD] = m
        spec.loader.exec_module(m)
        m.register()
        print("[cognia] blender-mcp registrado (socket %(puerto)d)")
    except Exception as e:
        print("[cognia] no pude registrar blender-mcp:", repr(e))
    return None

bpy.app.timers.register(_arrancar, first_interval=1.0)
'''


def _escribir_arranque() -> Path:
    CARPETA.mkdir(parents=True, exist_ok=True)
    src = _ARRANQUE_SRC % {"puerto": PUERTO_BLENDER, "addon": str(ADDON)}
    if not ARRANQUE.exists() or ARRANQUE.read_text(encoding="utf-8") != src:
        ARRANQUE.write_text(src, encoding="utf-8")
    return ARRANQUE


def puerto_abierto(puerto: int = PUERTO_BLENDER, host: str = "localhost") -> bool:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((host, puerto))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _esperar_puerto(segundos: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < segundos:
        if puerto_abierto():
            return True
        time.sleep(0.5)
    return puerto_abierto()


def _mcp():
    """Cliente MCP 'blender' conectado (reusa el de tools_mcp)."""
    from cognia.agent import tools_mcp
    tools_mcp._CAIDOS.pop("blender", None)     # ahora Blender SI esta: reintentar
    return tools_mcp._conectar("blender")


def _bl(codigo: str, timeout: float = 120) -> str:
    """Ejecuta codigo en Blender y devuelve lo que imprimio (sin el prefijo del servidor)."""
    if not puerto_abierto():
        raise RuntimeError("Blender no esta abierto con el addon (usa blender_abrir)")
    cli = _mcp()
    salida = cli.llamar("execute_blender_code", {"code": codigo, "user_prompt": ""}, timeout=timeout)
    if salida.startswith("ERROR"):
        raise RuntimeError(salida[:800])
    salida = re.sub(r"^Code executed successfully:\s*", "", salida.strip())
    _ESTADO["blender"]["conectado"] = True
    return salida.strip()


def _bl_json(codigo: str, timeout: float = 120) -> dict:
    """Como _bl pero el codigo imprime UN json al final (`print(json.dumps(...))`)."""
    txt = _bl(codigo, timeout=timeout)
    for linea in reversed(txt.splitlines()):
        linea = linea.strip()
        if linea.startswith("{") and linea.endswith("}"):
            try:
                return json.loads(linea)
            except ValueError:
                continue
    return {"crudo": txt[:800]}


def blender_abrir(fichero: str = "", ctx=None, espera_s: int = ESPERA_BLENDER_S) -> dict:
    """Blender en la mesa con el addon; devuelve {app_id, pid, hwnd, mudada, version, conectado}."""
    if AT is None:
        raise RuntimeError("app_tools no disponible (sin escritorio propio)")
    exe = blender_exe()
    if not exe:
        raise RuntimeError("no encuentro blender.exe: instala Blender (winget install BlenderFoundation.Blender "
                           "o el zip portable en %LOCALAPPDATA%\\Programs\\Blender) o pon la ruta en "
                           "config taller_blender / env COGNIA_BLENDER_EXE")
    if not ADDON.is_file():
        raise RuntimeError("falta el addon %s (curl -sL -o %s https://raw.githubusercontent.com/"
                           "ahujasid/blender-mcp/main/addon.py)" % (ADDON, ADDON))
    if puerto_abierto():
        # ya hay un Blender con el addon (de esta sesion o del dueno): se reusa
        e = _ESTADO["blender"]
        e["conectado"] = True
        return {"app_id": e.get("app_id", ""), "pid": e.get("pid", 0), "hwnd": e.get("hwnd", 0),
                "mudada": True, "reusado": True, "version": _version_binario(exe), "conectado": True}
    arranque = _escribir_arranque()
    cmd = '"%s" --python "%s"' % (exe, arranque)
    if fichero:
        ruta = PC.resolver_ruta(fichero, debe_existir=True, ctx=ctx)
        cmd += ' "%s"' % ruta
    app_id, a = AT.lanzar(cmd, espera_ms=30000, titulo="Blender")
    e = _ESTADO["blender"]
    e.update({"app_id": app_id, "pid": a["pid"], "hwnd": a["hwnd"], "fichero": fichero, "error": ""})
    if M is not None and a.get("mudada"):
        try:
            M.fijar_activa(a["hwnd"])
            M.pantalla_abrir()
        except Exception as exc:
            _degradado("pantallita de la mesa: %s" % exc)
    ok = _esperar_puerto(espera_s)
    if not ok:
        e["error"] = "Blender abrio pero el addon no abrio el puerto %d en %ds" % (PUERTO_BLENDER, espera_s)
        raise RuntimeError(e["error"] + " (mira %s)" % a.get("log", ""))
    try:
        _bl("import bpy; print(bpy.app.version_string)", timeout=60)
    except Exception as exc:
        e["error"] = "puerto abierto pero el MCP no responde: %s" % exc
        raise RuntimeError(e["error"])
    e["conectado"] = True
    return {"app_id": app_id, "pid": a["pid"], "hwnd": a["hwnd"], "mudada": a.get("mudada", False),
            "reusado": False, "version": _version_binario(exe), "conectado": True}


# ---------------------------------------------------------------------------
# Referencias de internet
# ---------------------------------------------------------------------------

def _slug(texto: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", texto.strip().lower()).strip("_")
    return s[:48] or "personaje"


def _buscar_imagenes(consulta: str, n: int) -> list:
    """[{url, titulo, fuente}] por ddgs (DuckDuckGo) y, si falla, por
    busqueda_imagenes (Commons/Openverse). Nunca lanza: devuelve lo que haya."""
    fuera = []
    try:
        from ddgs import DDGS
        with DDGS() as d:
            for r in d.images(consulta, max_results=n):
                url = r.get("image") or ""
                if url:
                    fuera.append({"url": url, "titulo": r.get("title", ""), "fuente": r.get("source", ""),
                                  "pagina": r.get("url", "")})
    except Exception as exc:
        _degradado("ddgs '%s': %s: %s" % (consulta, type(exc).__name__, exc))
    if len(fuera) < n:
        try:
            from cognia.busqueda_imagenes import buscar
            for r in buscar(consulta, n=n):
                url = r.get("url_imagen") or ""
                if url and all(url != x["url"] for x in fuera):
                    fuera.append({"url": url, "titulo": r.get("titulo", ""), "fuente": r.get("fuente", ""),
                                  "pagina": r.get("url_pagina", ""), "licencia": r.get("licencia", "")})
        except Exception as exc:
            _degradado("busqueda_imagenes '%s': %s: %s" % (consulta, type(exc).__name__, exc))
    return fuera


def _bajar_imagen(url: str, destino_sin_ext: Path, minimo_px: int = 200) -> Path | None:
    """Descarga y valida con PIL; devuelve la ruta final (.png/.jpg) o None."""
    try:
        import requests
        r = requests.get(url, timeout=20, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (Cognia taller; referencias de modelado)"})
        r.raise_for_status()
        datos = b""
        for trozo in r.iter_content(65536):
            datos += trozo
            if len(datos) > 20 * 1024 * 1024:
                return None
    except Exception as exc:
        _degradado("descarga %s: %s" % (url[:80], type(exc).__name__))
        return None
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(datos))
        im.load()
        if min(im.size) < minimo_px:
            return None
        ext = ".png" if (im.mode in ("RGBA", "LA", "P") or im.format == "PNG") else ".jpg"
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if ext == ".png" else "RGB")
        if max(im.size) > 2048:
            im.thumbnail((2048, 2048))
        destino = destino_sin_ext.with_suffix(ext)
        im.save(destino)
        return destino
    except Exception as exc:
        _degradado("imagen invalida %s: %s" % (url[:80], type(exc).__name__))
        return None


def buscar_referencias(personaje: str, n_por_angulo: int = 2, angulos=ANGULOS, carpeta: Path = None) -> dict:
    """Busca y baja imagenes del personaje por angulo. {carpeta, imagenes: [{angulo, ruta, url}], fallos}."""
    personaje = (personaje or "").strip().strip("\"'")
    if not personaje:
        raise ValueError("falta el personaje/objeto a buscar")
    carpeta = Path(carpeta) if carpeta else CARPETA / "referencias" / _slug(personaje)
    carpeta.mkdir(parents=True, exist_ok=True)
    imagenes, fallos = [], []
    for ang in angulos:
        consulta = _CONSULTAS.get(ang, "{p} " + ang).format(p=personaje)
        candidatas = _buscar_imagenes(consulta, n_por_angulo * 3)
        k = 0
        for c in candidatas:
            if k >= n_por_angulo:
                break
            ruta = _bajar_imagen(c["url"], carpeta / ("%s_%d" % (ang, k + 1)))
            if ruta is None:
                continue
            k += 1
            imagenes.append({"angulo": ang, "ruta": str(ruta), "url": c["url"], "titulo": c.get("titulo", ""),
                             "fuente": c.get("fuente", ""), "pagina": c.get("pagina", "")})
        if k == 0:
            fallos.append("%s (%d candidatas, ninguna valida)" % (ang, len(candidatas)))
    with (carpeta / "fuentes.json").open("w", encoding="utf-8") as fh:
        json.dump({"personaje": personaje, "cuando": time.strftime("%Y-%m-%d %H:%M"), "imagenes": imagenes},
                  fh, ensure_ascii=False, indent=1)
    return {"carpeta": str(carpeta), "imagenes": imagenes, "fallos": fallos, "personaje": personaje}


def codigo_referencias(imagenes: list, tam: float = 4.0) -> str:
    """El bpy que coloca las imagenes como planos de referencia (coleccion 'Referencias')."""
    items = [(i["ruta"], i["angulo"]) for i in imagenes]
    return '''
import bpy, json, math
sc = bpy.context.scene
col = bpy.data.collections.get("Referencias")
if col is None:
    col = bpy.data.collections.new("Referencias")
    sc.collection.children.link(col)
POSES = %(poses)s
ITEMS = %(items)s
TAM = %(tam)r
vistos = {}
puestas = []
for ruta, ang in ITEMS:
    pos, rot = POSES.get(ang, POSES["hoja"])
    k = vistos.get(ang, 0)
    vistos[ang] = k + 1
    try:
        img = bpy.data.images.load(ruta, check_existing=True)
    except Exception as e:
        print("no cargo", ruta, e)
        continue
    nombre = "Ref_%%s_%%d" %% (ang, k + 1)
    ob = bpy.data.objects.get(nombre)
    if ob is None:
        ob = bpy.data.objects.new(nombre, None)
        col.objects.link(ob)
    ob.empty_display_type = 'IMAGE'
    ob.data = img
    ob.empty_display_size = TAM
    ob.empty_image_depth = 'BACK'
    ob.show_empty_image_perspective = True
    ob.show_empty_image_orthographic = True
    ob.hide_render = True
    # la segunda imagen del mismo angulo va un poco mas atras, para no solaparse
    n = 1.0 if ang in ("frente", "hoja", "lado_der") else -1.0
    dx = (0.6 * k) * (1 if ang in ("lado", "lado_der") else 0)
    dy = (0.6 * k) * (1 if ang in ("frente", "atras") else 0)
    ob.location = (pos[0] + dx * n, pos[1] + dy * n, pos[2] - 0.6 * k * (1 if ang == "arriba" else 0))
    ob.rotation_euler = tuple(math.radians(r) for r in rot)
    puestas.append(nombre)
print(json.dumps({"puestas": puestas, "coleccion": col.name}))
''' % {"poses": json.dumps(_POSES), "items": json.dumps(items), "tam": float(tam)}


# ---------------------------------------------------------------------------
# Blender: ver, guardar, exportar, cerrar
# ---------------------------------------------------------------------------

_CODIGO_RENDER = '''
import bpy, math, json, mathutils
sc = bpy.context.scene
ANG = %(angulo)r
RUTA = %(ruta)r
MOTOR = %(motor)r
objs = [o for o in sc.objects if o.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT') and o.visible_get()]
if objs:
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
    mn = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
else:
    mn, mx = mathutils.Vector((-1, -1, -1)), mathutils.Vector((1, 1, 1))
centro = (mn + mx) / 2
radio = max((mx - mn).length / 2, 0.5)
cam = bpy.data.objects.get("CogniaCam")
if cam is None:
    cd = bpy.data.cameras.new("CogniaCam")
    cam = bpy.data.objects.new("CogniaCam", cd)
    sc.collection.objects.link(cam)
cam.hide_render = True
dist = radio / math.tan(cam.data.angle / 2) * 1.2
dirs = {"perspectiva": mathutils.Vector((1, -1, 0.7)).normalized(), "frente": mathutils.Vector((0, -1, 0)),
        "lado": mathutils.Vector((1, 0, 0)), "atras": mathutils.Vector((0, 1, 0)),
        "arriba": mathutils.Vector((0, 0.0001, 1)).normalized()}
d = dirs.get(ANG, dirs["perspectiva"])
cam.location = centro + d * dist
cam.rotation_euler = (centro - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.clip_end = max(1000.0, dist * 4)
sc.camera = cam
if MOTOR == "eevee":
    for m in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            sc.render.engine = m
            break
        except TypeError:
            continue
    if not any(o.type == 'LIGHT' for o in sc.objects):
        ld = bpy.data.lights.new("CogniaSol", 'SUN'); ld.energy = 3
        lo = bpy.data.objects.new("CogniaSol", ld); sc.collection.objects.link(lo)
        lo.rotation_euler = (math.radians(50), 0, math.radians(30))
else:
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_cavity = True
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 800, 600, 100
sc.render.image_settings.file_format = 'PNG'
sc.render.filepath = RUTA
# las referencias (empties con imagen) no salen en el render; los demas objetos si
bpy.ops.render.render(write_still=True)
print(json.dumps({"ok": True, "ruta": RUTA, "objetos": len(objs), "angulo": ANG, "motor": sc.render.engine}))
'''


def ver(ctx, angulo: str = "viewport", motor: str = "workbench", salida: str = "") -> dict:
    """Imagen de lo que hay: el viewport (con las referencias) o un render limpio desde un angulo."""
    angulo = (angulo or "viewport").strip().lower()
    if angulo in ("viewport", "vista", ""):
        cli = _mcp()
        txt = cli.llamar("get_viewport_screenshot", {"max_size": 1000, "user_prompt": ""}, timeout=60)
        m = re.search(r"guardada en (.+?)\]", txt)
        if not m:
            raise RuntimeError("el viewport no devolvio imagen: %s" % txt[:300])
        origen = Path(m.group(1).strip())
        destino = PC.ruta_salida(ctx, "blender_viewport", ".png", salida)
        shutil.move(str(origen), str(destino))
        return {"ruta": str(destino), "angulo": "viewport", "motor": "viewport"}
    destino = PC.ruta_salida(ctx, "blender_%s" % angulo, ".png", salida)
    r = _bl_json(_CODIGO_RENDER % {"angulo": angulo, "ruta": str(destino), "motor": motor}, timeout=180)
    if not r.get("ok"):
        raise RuntimeError("render fallo: %s" % r)
    r["ruta"] = str(destino)
    return r


def guardar(ruta: str = "", ctx=None) -> dict:
    if ruta:
        p = PC.resolver_ruta(ruta, debe_existir=False, ctx=ctx)
        if p.suffix.lower() != ".blend":
            p = p.with_suffix(".blend")
        p.parent.mkdir(parents=True, exist_ok=True)
        codigo = "import bpy, json\nbpy.ops.wm.save_as_mainfile(filepath=%r)\nprint(json.dumps({'ruta': bpy.data.filepath}))" % str(p)
    else:
        codigo = ('import bpy, json, os, time\n'
                  'if bpy.data.filepath:\n    bpy.ops.wm.save_mainfile()\n'
                  'else:\n    d = %r\n    os.makedirs(d, exist_ok=True)\n'
                  '    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(d, "escena_%%s.blend" %% time.strftime("%%Y%%m%%d_%%H%%M%%S")))\n'
                  'print(json.dumps({"ruta": bpy.data.filepath}))' % str(CARPETA / "blend"))
    r = _bl_json(codigo, timeout=120)
    if not r.get("ruta"):
        raise RuntimeError("no se guardo: %s" % r)
    _ESTADO["blender"]["fichero"] = r["ruta"]
    return r


_EXPORTADORES = {
    ".glb": "bpy.ops.export_scene.gltf(filepath=RUTA, export_format='GLB')",
    ".gltf": "bpy.ops.export_scene.gltf(filepath=RUTA, export_format='GLTF_SEPARATE')",
    ".fbx": "bpy.ops.export_scene.fbx(filepath=RUTA)",
    ".obj": "bpy.ops.wm.obj_export(filepath=RUTA)",
    ".stl": "bpy.ops.wm.stl_export(filepath=RUTA)",
}


def exportar(ruta: str, ctx=None) -> dict:
    p = PC.resolver_ruta(ruta, debe_existir=False, ctx=ctx)
    ext = p.suffix.lower()
    if ext not in _EXPORTADORES:
        raise ValueError("formato %r no soportado; usa %s" % (ext, ", ".join(_EXPORTADORES)))
    p.parent.mkdir(parents=True, exist_ok=True)
    codigo = ('import bpy, json, os\nRUTA = %r\n'
              '# fuera las referencias y la camara del taller del export\n'
              'for o in bpy.context.scene.objects:\n'
              '    o.select_set(o.type != "EMPTY" and not o.name.startswith("Cognia"))\n'
              '%s\nprint(json.dumps({"ruta": RUTA, "bytes": os.path.getsize(RUTA) if os.path.exists(RUTA) else 0}))'
              % (str(p), _EXPORTADORES[ext]))
    r = _bl_json(codigo, timeout=300)
    if not r.get("bytes"):
        raise RuntimeError("el export no produjo fichero: %s" % r)
    return r


def escena() -> str:
    cli = _mcp()
    txt = cli.llamar("get_scene_info", {"user_prompt": ""}, timeout=60)
    try:
        d = json.loads(txt)
        lineas = ["escena %r: %d objeto(s)" % (d.get("name"), d.get("object_count", 0))]
        for o in d.get("objects", [])[:40]:
            loc = o.get("location") or []
            lineas.append("  %-24s %-8s en (%s)" % (o.get("name"), o.get("type"),
                                                     ", ".join("%.2f" % v for v in loc)))
        if d.get("materials_count") is not None:
            lineas.append("  materiales: %s" % d.get("materials_count"))
        return "\n".join(lineas)
    except ValueError:
        return txt[:1500]


def cerrar_blender(guardar_antes: bool = True) -> str:
    e = _ESTADO["blender"]
    detalle = []
    if guardar_antes and puerto_abierto():
        try:
            r = guardar()
            detalle.append("guardado en %s" % r.get("ruta"))
        except Exception as exc:
            detalle.append("no se pudo guardar antes de cerrar: %s" % str(exc)[:120])
            _degradado("guardar antes de cerrar: %s" % exc)
    try:
        from cognia.agent import tools_mcp
        cli = tools_mcp._VIVOS.pop("blender", None)
        if cli is not None:
            cli.cerrar()
    except Exception as exc:
        _degradado("cerrar cliente MCP blender: %s" % exc)
    if e.get("app_id") and AT is not None:
        detalle.append(AT.cerrar(e["app_id"]))
    elif e.get("pid") and EP is not None:
        detalle.append(EP.matar_arbol(e["pid"]))
    else:
        detalle.append("no habia Blender abierto por el taller")
    e.update({"app_id": "", "pid": 0, "hwnd": 0, "conectado": False})
    return "; ".join(detalle)


def guardar_antes_de_cerrar(app: dict) -> str:
    """Hook para cierre_programas: antes de cerrar un blender.exe, guardar."""
    if not puerto_abierto():
        return ""
    try:
        return "guardado en %s" % guardar().get("ruta")
    except Exception as exc:
        _degradado("autosave al cerrar Blender: %s" % exc)
        return "sin guardar (%s)" % str(exc)[:80]


# ---------------------------------------------------------------------------
# Godot
# ---------------------------------------------------------------------------

_PROJECT_GODOT = '''; Engine configuration file.
; Generado por Cognia (taller). Godot 4.
config_version=5

[application]

config/name="%(nombre)s"
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.4")

[rendering]

renderer/rendering_method="mobile"
'''

_MAIN_TSCN_2D = '''[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="Etiqueta" type="Label" parent="."]
offset_left = 40.0
offset_top = 40.0
offset_right = 400.0
offset_bottom = 80.0
text = "%(nombre)s"
'''

_MAIN_GD_2D = '''extends Node2D

# Escena principal generada por Cognia. Godot 4 / GDScript.

func _ready() -> void:
\tprint("Main listo: %(nombre)s")
'''

_MAIN_TSCN_3D = '''[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[sub_resource type="BoxMesh" id="BoxMesh_1"]

[node name="Main" type="Node3D"]
script = ExtResource("1")

[node name="Camara" type="Camera3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 0.866025, 0.5, 0, -0.5, 0.866025, 0, 2, 5)

[node name="Luz" type="DirectionalLight3D" parent="."]
transform = Transform3D(0.707107, -0.5, 0.5, 0, 0.707107, 0.707107, -0.707107, -0.5, 0.5, 0, 4, 0)

[node name="Caja" type="MeshInstance3D" parent="."]
mesh = SubResource("BoxMesh_1")
'''

_MAIN_GD_3D = '''extends Node3D

# Escena principal generada por Cognia. Godot 4 / GDScript.

func _ready() -> void:
\tprint("Main listo: %(nombre)s")

func _process(delta: float) -> void:
\tvar caja := get_node_or_null("Caja")
\tif caja:
\t\tcaja.rotate_y(delta)
'''


def _ruta_proyecto(nombre_o_ruta: str, ctx=None, crear: bool = False) -> Path:
    v = (nombre_o_ruta or "").strip().strip("\"'")
    if not v:
        raise ValueError("falta el proyecto (nombre o ruta con project.godot)")
    p = Path(v)
    if p.is_absolute() or os.sep in v or "/" in v:
        try:
            p = PC.resolver_ruta(v, debe_existir=not crear, ctx=ctx)
        except Exception:
            p = Path(v).expanduser()
    else:
        # un nombre pelado: el workspace del agente (bases_relativas: donde
        # van tambien los escribir_archivo relativos), luego la carpeta del
        # taller. Cazado en el primer e2e con modelo (2026-09-10): con solo
        # ctx["workspace"] (que el agente real NO pone) el proyecto se creaba
        # en ~/.cognia/taller y el modelo escribia main.gd en el workspace:
        # dos mitades de un proyecto en sitios distintos.
        ws = (ctx or {}).get("workspace") if isinstance(ctx, dict) else None
        cand = [Path(ws) / v] if ws else []
        cand += [b / v for b in PC.bases_relativas()]
        cand.append(CARPETA / "godot" / _slug(v))
        # al CREAR, un nombre pelado va al workspace (si lo hay); al buscar,
        # gana el que ya tenga project.godot y si no, la carpeta del taller
        p = next((c for c in cand if (c / "project.godot").is_file()), cand[0] if crear else cand[-1])
    if p.is_file() and p.name == "project.godot":
        p = p.parent
    if not crear and not (p / "project.godot").is_file():
        raise ValueError("no hay project.godot en %s (crea uno con godot_proyecto)" % p)
    return p


def crear_proyecto(nombre_o_ruta: str, tipo: str = "2d", nombre: str = "", ctx=None) -> dict:
    p = _ruta_proyecto(nombre_o_ruta, ctx=ctx, crear=True)
    if (p / "project.godot").is_file():
        return {"ruta": str(p), "existia": True, "ficheros": sorted(x.name for x in p.iterdir())[:20]}
    p.mkdir(parents=True, exist_ok=True)
    nombre = nombre or p.name.replace("_", " ").title()
    tres = (tipo or "2d").strip().lower() == "3d"
    (p / "project.godot").write_text(_PROJECT_GODOT % {"nombre": nombre}, encoding="utf-8")
    (p / "main.tscn").write_text((_MAIN_TSCN_3D if tres else _MAIN_TSCN_2D) % {"nombre": nombre}, encoding="utf-8")
    (p / "main.gd").write_text((_MAIN_GD_3D if tres else _MAIN_GD_2D) % {"nombre": nombre}, encoding="utf-8")
    (p / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">'
                                '<rect width="128" height="128" rx="24" fill="#478cbf"/></svg>', encoding="utf-8")
    return {"ruta": str(p), "existia": False, "tipo": "3d" if tres else "2d",
            "ficheros": ["project.godot", "main.tscn", "main.gd", "icon.svg"]}


_RE_ERROR_GD = re.compile(r"(SCRIPT ERROR|ERROR:|Parse Error|Parser Error|error\(|USER ERROR|Failed to load|"
                          r"Cannot open file|Invalid call|Identifier .* not declared)", re.I)


def _errores_de(salida: str, maximo: int = 12) -> list:
    lineas = salida.splitlines()
    fuera = []
    for i, ln in enumerate(lineas):
        if _RE_ERROR_GD.search(ln):
            trozo = ln.strip()
            # la linea "at: ..." siguiente dice donde
            if i + 1 < len(lineas) and lineas[i + 1].strip().lower().startswith("at:"):
                trozo += "  " + lineas[i + 1].strip()
            fuera.append(trozo[:240])
            if len(fuera) >= maximo:
                break
    return fuera


def _godot_run(args: list, cwd: Path, timeout: float) -> tuple:
    exe = godot_exe(consola=True)
    if not exe:
        raise RuntimeError("no encuentro Godot: winget install GodotEngine.GodotEngine, o pon la ruta en "
                           "config taller_godot / env COGNIA_GODOT_EXE")
    t0 = time.time()
    try:
        r = subprocess.run([exe] + args, cwd=str(cwd), capture_output=True, text=True, errors="replace",
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0, False
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"")
        err = (exc.stderr or b"")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return None, out + err, time.time() - t0, True


def verificar(proyecto: str, ctx=None) -> dict:
    """Parsea cada .gd (--check-only) y carga la escena principal sin ventana."""
    p = _ruta_proyecto(proyecto, ctx=ctx)
    scripts = sorted(x for x in p.rglob("*.gd") if ".godot" not in x.parts and "addons" not in x.parts)
    por_script = {}
    for s in scripts:
        rel = "res://" + s.relative_to(p).as_posix()
        rc, out, seg, corto = _godot_run(["--headless", "--path", str(p), "--check-only", "--script", rel], p, 60)
        errs = _errores_de(out)
        por_script[rel] = errs if (errs or (rc not in (0, None))) else []
        if rc not in (0, None) and not errs:
            por_script[rel] = ["exit %s: %s" % (rc, out.strip()[-200:])]
    rc, out, seg, corto = _godot_run(["--headless", "--path", str(p), "--quit-after", "3"], p, 90)
    escena_errs = _errores_de(out)
    total = sum(len(v) for v in por_script.values()) + len(escena_errs)
    return {"ruta": str(p), "scripts": len(scripts), "por_script": por_script, "escena": escena_errs,
            "errores": total, "salida": out.strip()[-1500:]}


def correr(proyecto: str, segundos: int = 8, escena: str = "", ventana: bool = False, ctx=None) -> dict:
    """Corre el proyecto: sin ventana (headless, salida capturada) o en la mesa."""
    p = _ruta_proyecto(proyecto, ctx=ctx)
    extra = [escena] if escena else []
    if not ventana:
        rc, out, seg, corto = _godot_run(["--headless", "--path", str(p), "--quit-after", str(max(1, segundos * 60))] + extra,
                                         p, segundos + 20)
        return {"ruta": str(p), "modo": "headless", "exit": rc, "segundos": round(seg, 1), "cortado": corto,
                "errores": _errores_de(out), "salida": out.strip()[-2500:]}
    if AT is None:
        raise RuntimeError("app_tools no disponible: sin escritorio propio no puedo abrir ventanas")
    exe = godot_exe(consola=False)
    if not exe:
        raise RuntimeError("no encuentro Godot")
    cmd = '"%s" --path "%s"' % (exe, p) + (" " + escena if escena else "")
    app_id, a = AT.lanzar(cmd, espera_ms=20000, titulo="")
    if M is not None and a.get("mudada"):
        try:
            M.fijar_activa(a["hwnd"])
            M.pantalla_abrir()
        except Exception as exc:
            _degradado("pantallita: %s" % exc)
    time.sleep(max(1, min(segundos, 120)))
    cola = ""
    try:
        cola = Path(a["log"]).read_text(encoding="utf-8", errors="replace")[-2500:]
    except Exception:
        pass
    captura = ""
    try:
        r = AT.capturar(app_id, ctx, nombre="godot_correr")
        captura = r.get("ruta", "") if isinstance(r, dict) else ""
    except Exception as exc:
        _degradado("captura de Godot: %s" % exc)
    vivo = a["proc"].poll() is None
    return {"ruta": str(p), "modo": "ventana", "app_id": app_id, "vivo": vivo, "captura": captura,
            "errores": _errores_de(cola), "salida": cola.strip()}


def abrir_editor(proyecto: str, ctx=None) -> dict:
    if AT is None:
        raise RuntimeError("app_tools no disponible: sin escritorio propio no puedo abrir ventanas")
    p = _ruta_proyecto(proyecto, ctx=ctx)
    exe = godot_exe(consola=False)
    if not exe:
        raise RuntimeError("no encuentro Godot")
    cmd = '"%s" --path "%s" -e' % (exe, p)
    app_id, a = AT.lanzar(cmd, espera_ms=30000, titulo="Godot")
    e = _ESTADO["godot"]
    e.update({"app_id": app_id, "pid": a["pid"], "proyecto": str(p), "error": ""})
    if M is not None and a.get("mudada"):
        try:
            M.fijar_activa(a["hwnd"])
            M.pantalla_abrir()
        except Exception as exc:
            _degradado("pantallita: %s" % exc)
    return {"app_id": app_id, "pid": a["pid"], "hwnd": a["hwnd"], "mudada": a.get("mudada", False),
            "titulo": a.get("titulo", ""), "ruta": str(p)}


def cerrar_godot() -> str:
    e = _ESTADO["godot"]
    if e.get("app_id") and AT is not None:
        r = AT.cerrar(e["app_id"])
    elif e.get("pid") and EP is not None:
        r = EP.matar_arbol(e["pid"])
    else:
        r = "no habia Godot abierto por el taller"
    e.update({"app_id": "", "pid": 0})
    return r


# ---------------------------------------------------------------------------
# Estado y guia
# ---------------------------------------------------------------------------

GUIA = """COMO MODELAR UN PERSONAJE CON REFERENCIAS (el flujo que funciona):
 1. blender_abrir                      -> Blender en la mesa, MCP conectado
 2. blender_referencias "<personaje>"  -> baja frente/lado/atras/hoja y las pone como planos
 3. blender_ver                        -> mira las referencias (viewport) y describe proporciones
 4. blender_codigo <bpy>               -> bloquea el volumen con primitivas (cabeza, tronco,
    extremidades), modificador Mirror en X y Subdivision; escala/posiciona comparando con
    las refs (el plano 'frente' esta en Y=+3 mirando a -Y, 'lado' en X=-3). Une piezas con
    bpy.ops.object.join o deja partes separadas. Colores: materiales simples por parte.
 5. blender_ver frente / lado / perspectiva  -> render workbench limpio; compara con las refs
    y corrige (blender_codigo) hasta que la silueta coincida
 6. blender_guardar <ruta.blend> y blender_exportar <ruta.glb>  -> entregable
 Godot: godot_proyecto <nombre> [tipo=3d] -> escribir_archivo los .gd/.tscn -> godot_verificar
 -> godot_correr (salida y errores) -> godot_abrir para verlo en la mesa. Al acabar, los
 programas que ya no hagan falta se cierran solos (programa_mantener para conservar uno)."""


def estado() -> dict:
    bl = blender_exe()
    gd = godot_exe()
    return {
        "encendido": encendido(),
        "blender_exe": bl, "blender_version": _version_binario(bl) if bl else "",
        "addon": str(ADDON) if ADDON.is_file() else "",
        "blender_puerto": puerto_abierto(),
        "blender": dict(_ESTADO["blender"]),
        "godot_exe": gd, "godot_version": _version_binario(gd) if gd else "",
        "godot": dict(_ESTADO["godot"]),
        "mcp_config": str(Path.home() / ".cognia" / "mcp.json"),
        "carpeta": str(CARPETA),
        "errores": list(_ESTADO.get("errores", []))[-5:],
        "ultimo": ultimo(),
    }


def texto_estado() -> str:
    e = estado()
    lineas = ["taller: %s" % ("ON" if e["encendido"] else "OFF (COGNIA_TALLER=0 o /taller off)")]
    lineas.append("  Blender: %s%s" % (e["blender_exe"] or "NO ENCONTRADO", (" (" + e["blender_version"] + ")") if e["blender_version"] else ""))
    lineas.append("  addon blender-mcp: %s · socket %d %s · MCP %s" % (
        "ok" if e["addon"] else "FALTA", PUERTO_BLENDER, "ABIERTO" if e["blender_puerto"] else "cerrado",
        "conectado" if e["blender"]["conectado"] else "sin conectar"))
    if e["blender"].get("app_id"):
        lineas.append("  Blender abierto por el taller: %s (pid %s) %s" % (e["blender"]["app_id"], e["blender"]["pid"], e["blender"].get("fichero") or ""))
    lineas.append("  Godot: %s%s" % (e["godot_exe"] or "NO ENCONTRADO", (" (" + e["godot_version"] + ")") if e["godot_version"] else ""))
    if e["godot"].get("app_id"):
        lineas.append("  editor Godot abierto: %s (%s)" % (e["godot"]["app_id"], e["godot"]["proyecto"]))
    lineas.append("  MCP: %s (blender, godot; tambien via `mcp blender | ...`)" % e["mcp_config"])
    lineas.append("  carpeta del taller: %s" % e["carpeta"])
    if e["errores"]:
        lineas.append("  ultimos fallos: " + " | ".join(e["errores"]))
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Registro de tools
# ---------------------------------------------------------------------------

_CL_ABRIR = ("fichero", "espera")
_CL_REF = ("n", "angulos", "importar", "tam", "carpeta")
_CL_VER = ("angulo", "motor", "salida")
_CL_PROY = ("tipo", "nombre")
_CL_CORRER = ("segundos", "escena", "ventana")


def _p(nombre, tipo, desc, requerido=False, clave=False):
    return {"nombre": nombre, "tipo": tipo, "requerido": requerido, "clave": clave, "descripcion": desc}


def register(tool) -> None:

    @tool("blender_abrir",
          "blender_abrir [fichero.blend] -- abre Blender en la mesa con el MCP conectado",
          desc="Abre Blender en la mesa de Cognia (su escritorio propio, sin molestar al usuario) con el "
               "addon blender-mcp encendido y deja el MCP conectado. Si ya hay un Blender con el addon, "
               "lo reusa. Primer paso para modelar; luego blender_referencias, blender_codigo, blender_ver.",
          params=[_p("fichero", "string", ".blend a abrir (opcional)")],
          danger=True, timeout_s=180)
    def _blender_abrir(args, ctx):
        fichero, o = PC.partir_args(args, _CL_ABRIR)
        fichero = o.get("fichero", "") or fichero
        try:
            r = blender_abrir(fichero, ctx=ctx, espera_s=PC.entero(o.get("espera"), ESPERA_BLENDER_S, 10, 300))
        except Exception as exc:
            _degradado("blender_abrir: %s" % exc)
            return _err("blender_abrir", exc)
        _anotar("blender_abrir", str(r))
        return ("RESULTADO blender_abrir: Blender %s %s (app %s, pid %s%s). MCP conectado en el puerto %d.\n%s"
                % (r.get("version", ""), "ya estaba abierto: lo reuso" if r.get("reusado") else "abierto en la mesa",
                   r.get("app_id") or "-", r.get("pid") or "-",
                   "" if r.get("mudada") else ", OJO: la ventana NO se mudo a la mesa", PUERTO_BLENDER, GUIA))

    @tool("blender_referencias",
          "blender_referencias <personaje> [| n=2] [| angulos=frente,lado,atras,hoja] [| importar=0]"
          " -- busca en internet imagenes de referencia por angulo y las pone en la escena",
          desc="Busca en internet imagenes del personaje/objeto desde varios angulos (frente, lado, atras y "
               "hoja de modelo/turnaround), las descarga a ~/.cognia/taller/referencias/<personaje>/ y, si "
               "Blender esta abierto, las coloca como planos de referencia (coleccion 'Referencias': frente "
               "en Y=+3, lado en X=-3, atras en Y=-3). Devuelve las rutas: miralas con blender_ver o "
               "captura_describir antes de modelar.",
          params=[_p("personaje", "string", "que buscar (ej. 'Pikachu', 'Iron Man armor', 'Vespa scooter')", True),
                  _p("n", "integer", "imagenes por angulo (def 2)", clave=True),
                  _p("angulos", "string", "lista separada por comas (def frente,lado,atras,hoja)", clave=True),
                  _p("importar", "integer", "0 = solo descargar, no meterlas en Blender", clave=True)],
          danger=False, timeout_s=300)
    def _blender_referencias(args, ctx):
        personaje, o = PC.partir_args(args, _CL_REF)
        angulos = tuple(a.strip().lower() for a in (o.get("angulos") or ",".join(ANGULOS)).split(",") if a.strip())
        try:
            r = buscar_referencias(personaje, n_por_angulo=PC.entero(o.get("n"), 2, 1, 6), angulos=angulos,
                                   carpeta=o.get("carpeta") or None)
        except Exception as exc:
            _degradado("blender_referencias: %s" % exc)
            return _err("blender_referencias", exc)
        lineas = ["RESULTADO blender_referencias: %d imagen(es) de %r en %s" % (len(r["imagenes"]), r["personaje"], r["carpeta"])]
        for i in r["imagenes"]:
            lineas.append("  %-7s %s  <- %s" % (i["angulo"], i["ruta"], (i.get("fuente") or i["url"])[:60]))
        if r["fallos"]:
            lineas.append("  sin imagen valida para: " + "; ".join(r["fallos"]))
        importar = PC.entero(o.get("importar"), 1, 0, 1)
        if r["imagenes"] and importar and puerto_abierto():
            try:
                rr = _bl_json(codigo_referencias(r["imagenes"], tam=float(o.get("tam") or 4.0)), timeout=120)
                lineas.append("  colocadas en Blender como planos: %s" % ", ".join(rr.get("puestas", [])) if rr.get("puestas")
                              else "  Blender no coloco ninguna: %s" % rr)
            except Exception as exc:
                _degradado("colocar referencias: %s" % exc)
                lineas.append("  no pude colocarlas en Blender: %s" % str(exc)[:200])
        elif r["imagenes"] and importar:
            lineas.append("  (Blender no esta abierto: abrelo con blender_abrir y repite para colocarlas, o usa importar=0)")
        _anotar("blender_referencias", lineas[0])
        return "\n".join(lineas)

    @tool("blender_codigo",
          "blender_codigo <codigo python con bpy> -- ejecuta codigo dentro de Blender y devuelve lo impreso",
          desc="Ejecuta codigo Python (bpy) dentro del Blender abierto: crear/editar mallas, modificadores, "
               "materiales, transformar objetos. Devuelve lo que el codigo imprime (usa print para reportar). "
               "Trabaja por pasos cortos y comprueba con blender_ver / blender_escena.",
          params=[_p("codigo", "string", "codigo Python con bpy", True)],
          danger=True, timeout_s=240)
    def _blender_codigo(args, ctx):
        codigo = (args or "").strip()
        if codigo.startswith("```"):
            codigo = re.sub(r"^```[a-zA-Z]*\n?", "", codigo).rstrip("`").rstrip()
        if not codigo:
            return _err("blender_codigo", "falta el codigo")
        try:
            out = _bl(codigo, timeout=200)
        except Exception as exc:
            return _err("blender_codigo", exc)
        _anotar("blender_codigo", codigo[:80])
        return "RESULTADO blender_codigo: " + (out[:3000] if out else "(ok, sin salida)")

    @tool("blender_escena",
          "blender_escena -- objetos de la escena de Blender con tipo y posicion",
          desc="Lista los objetos de la escena de Blender abierta (nombre, tipo, posicion) y materiales.",
          params=[], danger=False, timeout_s=60)
    def _blender_escena(args, ctx):
        try:
            return "RESULTADO blender_escena: " + escena()
        except Exception as exc:
            return _err("blender_escena", exc)

    @tool("blender_ver",
          "blender_ver [viewport|frente|lado|atras|arriba|perspectiva] [| motor=workbench|eevee] [| salida=RUTA]"
          " -- imagen del viewport o render limpio desde un angulo",
          desc="Una imagen de lo que hay en Blender: 'viewport' (lo que se ve en la ventana, con las "
               "referencias) o un render limpio (workbench, gris sombreado) desde frente/lado/atras/"
               "arriba/perspectiva con camara automatica que encuadra todo. Devuelve la ruta PNG: "
               "descríbela con captura_describir (VLM) y compárala con las referencias.",
          params=[_p("angulo", "string", "viewport (def) | frente | lado | atras | arriba | perspectiva"),
                  _p("motor", "string", "workbench (def) | eevee", clave=True),
                  _p("salida", "string", "ruta PNG de salida", clave=True)],
          danger=False, timeout_s=240)
    def _blender_ver(args, ctx):
        ang, o = PC.partir_args(args, _CL_VER)
        ang = o.get("angulo", "") or ang or "viewport"
        try:
            r = ver(ctx, angulo=ang, motor=(o.get("motor") or "workbench").lower(), salida=o.get("salida", ""))
        except Exception as exc:
            _degradado("blender_ver: %s" % exc)
            return _err("blender_ver", exc)
        try:
            info = PC.texto_resumen_imagen(PC.resumen_imagen(r["ruta"]))
        except Exception:
            info = ""
        _anotar("blender_ver", r["ruta"])
        return "RESULTADO blender_ver (%s): %s%s" % (r.get("angulo"), r["ruta"], (" · " + info) if info else "")

    @tool("blender_guardar",
          "blender_guardar [ruta.blend] -- guarda la escena",
          desc="Guarda el .blend (en la ruta dada, o en la que ya tenia, o en ~/.cognia/taller/blend/).",
          params=[_p("ruta", "string", "ruta del .blend (opcional)")],
          danger=True, timeout_s=120)
    def _blender_guardar(args, ctx):
        try:
            r = guardar((args or "").strip(), ctx=ctx)
        except Exception as exc:
            return _err("blender_guardar", exc)
        _anotar("blender_guardar", r["ruta"])
        return "RESULTADO blender_guardar: %s" % r["ruta"]

    @tool("blender_exportar",
          "blender_exportar <ruta.glb|.gltf|.fbx|.obj|.stl> -- exporta la escena (sin referencias)",
          desc="Exporta los objetos de la escena (sin los planos de referencia ni la camara del taller) a "
               "glb/gltf/fbx/obj/stl. Un .glb es lo que Godot importa directo.",
          params=[_p("ruta", "string", "fichero de salida con extension", True)],
          danger=True, timeout_s=300)
    def _blender_exportar(args, ctx):
        try:
            r = exportar((args or "").strip(), ctx=ctx)
        except Exception as exc:
            return _err("blender_exportar", exc)
        _anotar("blender_exportar", r["ruta"])
        return "RESULTADO blender_exportar: %s (%d bytes)" % (r["ruta"], r["bytes"])

    @tool("blender_cerrar",
          "blender_cerrar [| guardar=0] -- cierra Blender (guardando antes)",
          desc="Cierra el Blender que abrio el taller, guardando la escena antes (guardar=0 para no guardar).",
          params=[_p("guardar", "integer", "1 (def) guarda antes; 0 no", clave=True)],
          danger=True, timeout_s=120)
    def _blender_cerrar(args, ctx):
        _o, o = PC.partir_args(args, ("guardar",))
        try:
            return "RESULTADO blender_cerrar: " + cerrar_blender(guardar_antes=PC.entero(o.get("guardar"), 1, 0, 1) == 1)
        except Exception as exc:
            return _err("blender_cerrar", exc)

    # ---- Godot -----------------------------------------------------------

    @tool("godot_proyecto",
          "godot_proyecto <nombre|ruta> [| tipo=2d|3d] [| nombre=Titulo] -- crea un proyecto Godot 4 minimo",
          desc="Crea un proyecto de Godot 4 que ya corre (project.godot + main.tscn + main.gd) en el "
               "workspace (nombre pelado) o en la ruta dada. tipo=3d pone camara, luz y una caja que gira. "
               "Luego escribe tus escenas/scripts con escribir_archivo y comprueba con godot_verificar.",
          params=[_p("proyecto", "string", "nombre o ruta de la carpeta", True),
                  _p("tipo", "string", "2d (def) | 3d", clave=True),
                  _p("nombre", "string", "titulo del juego", clave=True)],
          danger=True, timeout_s=60)
    def _godot_proyecto(args, ctx):
        proy, o = PC.partir_args(args, _CL_PROY)
        try:
            r = crear_proyecto(proy, tipo=o.get("tipo", "2d"), nombre=o.get("nombre", ""), ctx=ctx)
        except Exception as exc:
            return _err("godot_proyecto", exc)
        _anotar("godot_proyecto", r["ruta"])
        if r.get("existia"):
            return "RESULTADO godot_proyecto: ya existia %s (%s)" % (r["ruta"], ", ".join(r["ficheros"]))
        return ("RESULTADO godot_proyecto: creado %s (%s): %s. Godot %s. Siguiente: godot_verificar %s"
                % (r["ruta"], r["tipo"], ", ".join(r["ficheros"]), _version_binario(godot_exe()) or "?", r["ruta"]))

    @tool("godot_verificar",
          "godot_verificar <proyecto> -- parsea todos los .gd y carga la escena principal sin ventana",
          desc="Comprueba un proyecto Godot sin abrir ventana: cada script .gd se parsea (--check-only) y la "
               "escena principal se carga en headless. Devuelve los errores con fichero y linea. Usalo tras "
               "cada cambio de codigo, antes de godot_correr.",
          params=[_p("proyecto", "string", "nombre o ruta del proyecto", True)],
          danger=False, timeout_s=300)
    def _godot_verificar(args, ctx):
        try:
            r = verificar((args or "").strip(), ctx=ctx)
        except Exception as exc:
            return _err("godot_verificar", exc)
        _anotar("godot_verificar", "%d errores" % r["errores"])
        lineas = ["RESULTADO godot_verificar: %s · %d script(s) · %d error(es)" % (r["ruta"], r["scripts"], r["errores"])]
        for s, errs in r["por_script"].items():
            lineas.append("  %s: %s" % (s, "ok" if not errs else "; ".join(errs)))
        if r["escena"]:
            lineas.append("  escena principal: " + "; ".join(r["escena"]))
        else:
            lineas.append("  escena principal: carga ok")
        return "\n".join(lineas)

    @tool("godot_correr",
          "godot_correr <proyecto> [| segundos=8] [| escena=res://x.tscn] [| ventana=1]"
          " -- corre el proyecto y devuelve su salida y errores",
          desc="Ejecuta el proyecto Godot: por defecto sin ventana (headless, corre N segundos de juego y "
               "captura print/errores); con ventana=1 lo abre en la mesa, espera y devuelve una captura "
               "mas la salida. Los errores de runtime (SCRIPT ERROR, at: ...) vienen listados.",
          params=[_p("proyecto", "string", "nombre o ruta del proyecto", True),
                  _p("segundos", "integer", "segundos de ejecucion (def 8)", clave=True),
                  _p("escena", "string", "escena a correr en vez de la principal", clave=True),
                  _p("ventana", "integer", "1 = con ventana en la mesa", clave=True)],
          danger=True, timeout_s=300)
    def _godot_correr(args, ctx):
        proy, o = PC.partir_args(args, _CL_CORRER)
        try:
            r = correr(proy, segundos=PC.entero(o.get("segundos"), 8, 1, 120), escena=o.get("escena", ""),
                       ventana=PC.entero(o.get("ventana"), 0, 0, 1) == 1, ctx=ctx)
        except Exception as exc:
            _degradado("godot_correr: %s" % exc)
            return _err("godot_correr", exc)
        _anotar("godot_correr", r["modo"])
        cab = "RESULTADO godot_correr (%s): %s" % (r["modo"], r["ruta"])
        if r["modo"] == "headless":
            cab += " · exit %s · %.1fs%s" % (r["exit"], r["segundos"], " (cortado por tiempo)" if r["cortado"] else "")
        else:
            cab += " · app %s %s%s" % (r["app_id"], "viva" if r["vivo"] else "TERMINO", (" · captura " + r["captura"]) if r["captura"] else "")
        lineas = [cab, "  errores: %s" % ("; ".join(r["errores"]) if r["errores"] else "ninguno")]
        if r["salida"]:
            lineas.append("  salida:\n" + "\n".join("    " + ln for ln in r["salida"].splitlines()[-30:]))
        return "\n".join(lineas)

    @tool("godot_abrir",
          "godot_abrir <proyecto> -- abre el editor de Godot con el proyecto en la mesa",
          desc="Abre el editor de Godot con ese proyecto en la mesa de Cognia (para verlo, capturarlo con "
               "mesa_ver o dejarlo abierto al usuario con programa_mantener).",
          params=[_p("proyecto", "string", "nombre o ruta del proyecto", True)],
          danger=True, timeout_s=120)
    def _godot_abrir(args, ctx):
        try:
            r = abrir_editor((args or "").strip(), ctx=ctx)
        except Exception as exc:
            _degradado("godot_abrir: %s" % exc)
            return _err("godot_abrir", exc)
        _anotar("godot_abrir", r["ruta"])
        return "RESULTADO godot_abrir: editor abierto (app %s, pid %s, %r)%s" % (
            r["app_id"], r["pid"], r["titulo"], "" if r["mudada"] else " OJO: no se mudo a la mesa")

    @tool("godot_cerrar",
          "godot_cerrar -- cierra el editor de Godot que abrio el taller",
          desc="Cierra el editor/juego de Godot abierto por el taller.",
          params=[], danger=True, timeout_s=60)
    def _godot_cerrar(args, ctx):
        try:
            return "RESULTADO godot_cerrar: " + cerrar_godot()
        except Exception as exc:
            return _err("godot_cerrar", exc)

    @tool("taller_estado",
          "taller_estado -- Blender/Godot: rutas, versiones, MCP conectado, ultimo fallo, y la guia",
          desc="Estado del taller (Blender, addon MCP, Godot, MCP) y la guia de como modelar con referencias.",
          params=[], danger=False, timeout_s=60)
    def _taller_estado(args, ctx):
        return "RESULTADO taller_estado:\n" + texto_estado() + "\n" + GUIA
