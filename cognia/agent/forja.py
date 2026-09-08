# -*- coding: utf-8 -*-
"""
cognia/agent/forja.py
=====================
LA FORJA (2026-09-08). Pedido del dueno: "que el harness de Cognia pueda
construir sus propias herramientas, que verifique su funcionamiento end to end,
y que las use; es decir, que evolucione conforme el uso".

Lo que habia antes (agent/tool_synthesis.py, `crear_herramienta`): funciones
PURAS `run(args) -> str` con un allowlist de 18 modulos de la stdlib, sin
ficheros, sin procesos, sin red. Verificables, si; utiles para el trabajo real
del agente (leer un CSV, llamar a una API, convertir un fichero, mover
ventanas), no. Y no estaba en el catalogo core: el modelo nunca la veia.

La forja es el segundo escalon, y no lo sustituye:

  1. El AGENTE escribe la herramienta como un fichero .py normal (con
     escribir_archivo), siguiendo un contrato chico (ver PLANTILLA): `DOC`,
     opcionalmente `DESC`/`PARAMS`/`PELIGRO`, una lista `PRUEBAS` con al menos
     una prueba de punta a punta (args, lo que se espera en la salida, ficheros
     que hay que preparar antes, ficheros que deben existir despues), y
     `run(args, ctx) -> str`.
  2. `forjar <ruta.py>` la EXAMINA: sintaxis, contrato, scan estatico (imports
     y patrones prohibidos: nada que pueda borrar el disco, apagar la maquina o
     tocar el registro), y despues CORRE CADA PRUEBA en un subproceso con
     timeout, dentro de un directorio temporal limpio, comprobando la salida.
     O pasan todas, o la herramienta no existe.
  3. Si pasa, se guarda en ~/.cognia/forja/<nombre>.py (con historial de
     versiones), entra en el manifiesto como `staged` y se REGISTRA en caliente
     en el catalogo del agente: se puede llamar en el paso siguiente, y en todas
     las sesiones futuras (se cargan al importar tools.py).
  4. EVOLUCION CON EL USO. Cada llamada real cuenta: 3 usos buenos ascienden
     staged -> verificada; dos fallos seguidos disparan una RE-PRUEBA con sus
     propias PRUEBAS (si siguen pasando, el fallo fue del input y se sigue; si
     ya no pasan, la herramienta queda `rota`, deja de anunciarse y el modelo
     recibe la ruta para corregirla y volver a forjarla). Solo se ANUNCIAN al
     modelo las MAX_ANUNCIADAS mejores (verificadas primero, luego por usos);
     el resto siguen registradas y se encuentran con buscar_herramientas.
     Y la forja OBSERVA lo que el agente repite: cuando ejecuta el mismo
     script/comando por tercera vez en una tarea, le anexa una sugerencia al
     resultado ("esto podria ser una herramienta") y lo apunta en candidatas.

Todo lo que corre aqui corre en el equipo del dueno con sus permisos, como
cualquier otra tool del agente: la forja no es un sandbox de seguridad contra
un modelo hostil, es el examen que impide registrar algo que no funciona. Por
eso el scan estatico es un BLOCKLIST corto (lo catastrofico), no un allowlist,
y por eso `PELIGRO = True` (o el uso de subprocess/red/borrado detectado en el
scan) marca la tool como `danger` y pasa por la confirmacion de siempre.

Config: `forja` (on/off, default on), env COGNIA_FORJA=0 la apaga; el
directorio se puede aislar con COGNIA_FORJA_DIR (tests). Puerta: /forja.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MAX_ANUNCIADAS = 8          # tope de tools forjadas en el catalogo anunciado
ASCENSO_USOS_OK = 3         # staged -> verificada
FALLOS_PARA_REPROBAR = 2    # fallos seguidos que disparan la re-prueba
TIMEOUT_PRUEBA_DEF_S = 30
TIMEOUT_PRUEBA_MAX_S = 180
MAX_PRUEBAS = 12
REPETICIONES_SUGERIR = 3    # veces que se repite un comando antes de sugerir forjarlo

_NOMBRE_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")

# Imports que ninguna herramienta forjada necesita y que abren caminos que el
# examen no puede probar (registro, memoria cruda, ejecucion de codigo ajeno).
_IMPORTS_PROHIBIDOS = {"ctypes", "winreg", "pickle", "marshal", "shelve", "importlib",
                       "runpy", "code", "codeop", "pty", "msvcrt", "_winapi"}
_NOMBRES_PROHIBIDOS = {"eval", "exec", "__import__", "compile", "breakpoint", "__builtins__"}
# Patrones en el TEXTO del fichero: lo catastrofico que un scan de imports no ve.
_PATRONES_PROHIBIDOS = (
    (r"\brmdir\s+/s", "rmdir /s"),
    (r"\bformat\s+[a-z]:", "format de disco"),
    (r"\bshutdown\b", "shutdown"),
    (r"\btaskkill\b", "taskkill"),
    (r"\brm\s+-rf\s+[/~]", "rm -rf de raiz o home"),
    (r"\bdel\s+/[sq]", "del /s o /q"),
    (r"\breg\s+(delete|add)\b", "reg delete/add"),
    (r"\bdiskpart\b", "diskpart"),
    (r"\bshutil\.rmtree\s*\(\s*(Path\.home\(\)|['\"][A-Za-z]:\\\\?['\"]|['\"]/['\"])", "rmtree de raiz o home"),
    (r"os\.system\s*\(", "os.system (usa subprocess.run con lista)"),
)
# Lo que hace que una tool forjada sea `danger` aunque no lo declare.
_MARCAS_PELIGRO = (r"\bsubprocess\b", r"\bshutil\.rmtree\b", r"\bos\.remove\b", r"\bos\.unlink\b",
                   r"\bsocket\b", r"\burllib\.request\b", r"\brequests\.", r"\bsmtplib\b",
                   r"\bwin32com\b", r"\bpyautogui\b", r"\bos\.rename\b", r"\bshutil\.move\b")

PLANTILLA = '''# -*- coding: utf-8 -*-
"""Herramienta forjada por Cognia. Se registra con: forjar <esta ruta>"""
# Una linea que el modelo ve en su catalogo: <nombre> <args>  -- que hace
DOC = "contar_palabras <ruta>  -- cuenta las palabras y lineas de un fichero de texto"
# Opcional: descripcion larga (cuando usarla) y parametros para el tool-calling nativo
DESC = "Cuenta palabras y lineas de un fichero de texto. Util para informes y resumenes."
PARAMS = [{"nombre": "ruta", "tipo": "string", "requerido": True, "descripcion": "fichero a contar"}]
# Opcional: True si toca cosas fuera del workspace (borra, manda, instala)
PELIGRO = False
# OBLIGATORIO: al menos una prueba de punta a punta. Cada prueba corre en un
# directorio temporal LIMPIO; `prepara` escribe ficheros antes, `espera` es un
# texto que debe aparecer en la salida (o `espera_re`, una regex), `no_espera`
# no debe aparecer, `espera_fichero` debe existir despues. `timeout` en segundos.
PRUEBAS = [
    {"args": "poema.txt", "prepara": {"poema.txt": "uno dos tres\\ncuatro\\n"}, "espera": "4 palabras"},
    {"args": "no_existe.txt", "espera": "ERROR"},
]


def run(args, ctx):
    """args: el texto tal cual lo manda el modelo. ctx: dict con 'workspace',
    'cwd', '_scratchpad'. Devuelve SIEMPRE un str; los errores como
    'RESULTADO <nombre> ERROR: <motivo>' (no lances excepciones por lo previsible)."""
    from pathlib import Path
    ruta = (args or "").strip().strip('"')
    base = Path(ctx.get("workspace") or ctx.get("cwd") or ".")
    p = Path(ruta) if Path(ruta).is_absolute() else base / ruta
    if not p.exists():
        return "RESULTADO contar_palabras ERROR: no existe %s" % p
    texto = p.read_text(encoding="utf-8", errors="replace")
    return "RESULTADO contar_palabras: %d palabras, %d lineas en %s" % (
        len(texto.split()), texto.count("\\n"), p.name)
'''

# Ultimo evento (puerta /forja estado)
_ULTIMO: dict = {"accion": "", "detalle": "", "error": "", "ts": 0.0}
# Modulos cargados: nombre -> (sha, namespace)
_CARGADAS: dict = {}
# Observacion de repeticiones por sesion: {clave_sesion: {huella: [veces, comando]}}
_REPETIDOS: dict = {}


def _anotar(accion: str, detalle: str = "", error: str = "") -> None:
    _ULTIMO.update({"accion": accion, "detalle": str(detalle)[:400], "error": str(error)[:400],
                    "ts": time.time()})


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE (regla del repo): por _aviso_degradado si el CLI esta, si no stderr."""
    try:
        from cognia.cli import _aviso_degradado
        _aviso_degradado("forja", motivo)
    except Exception:
        print("[degradado] forja: %s" % motivo, file=sys.stderr)


# ---------------------------------------------------------------------------
# Config y rutas
# ---------------------------------------------------------------------------

def encendida() -> bool:
    crudo = os.environ.get("COGNIA_FORJA", "").strip().lower()
    if crudo:
        return crudo in ("1", "on", "true", "yes", "si")
    try:
        ruta = Path.home() / ".cognia_config.json"
        if ruta.exists():
            v = json.loads(ruta.read_text(encoding="utf-8")).get("forja", "on")
            return str(v).strip().lower() in ("1", "on", "true", "yes", "si")
    except Exception:
        pass
    return True


def directorio() -> Path:
    crudo = os.environ.get("COGNIA_FORJA_DIR", "").strip()
    d = Path(crudo) if crudo else Path.home() / ".cognia" / "forja"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifiesto_ruta() -> Path:
    return directorio() / "manifiesto.json"


def manifiesto() -> list:
    try:
        r = _manifiesto_ruta()
        if r.exists():
            datos = json.loads(r.read_text(encoding="utf-8"))
            return [e for e in datos if isinstance(e, dict)] if isinstance(datos, list) else []
    except Exception as exc:
        _avisar("manifiesto ilegible: %s" % exc)
    return []


def _guardar_manifiesto(entradas: list) -> None:
    r = _manifiesto_ruta()
    tmp = r.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entradas, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, r)


def entrada(nombre: str):
    for e in manifiesto():
        if e.get("nombre") == nombre:
            return e
    return None


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Examen estatico: sintaxis, contrato, scan
# ---------------------------------------------------------------------------

def _literal(nodo):
    try:
        return ast.literal_eval(nodo)
    except Exception:
        return None


def leer_contrato(codigo: str, nombre_fichero: str = "") -> dict:
    """{nombre, doc, desc, params, peligro, pruebas, run_args} o ValueError con el motivo.
    Lee las constantes por ast.literal_eval: NO ejecuta el modulo para leerlo."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as exc:
        raise ValueError("sintaxis: linea %s: %s" % (exc.lineno, exc.msg))
    consts: dict = {}
    run_fn = None
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            consts[nodo.targets[0].id] = _literal(nodo.value)
        elif isinstance(nodo, ast.FunctionDef) and nodo.name == "run":
            run_fn = nodo
    if run_fn is None:
        raise ValueError("no define `def run(args, ctx)` a nivel de modulo")
    n_args = len(run_fn.args.args)
    if n_args < 1:
        raise ValueError("run() debe aceptar al menos `args` (y preferiblemente `ctx`)")
    doc = consts.get("DOC")
    if not isinstance(doc, str) or not doc.strip():
        raise ValueError("falta DOC = \"<nombre> <args>  -- que hace\" (una linea, es lo que ve el modelo)")
    doc = " ".join(doc.split())
    nombre = consts.get("NOMBRE")
    if not isinstance(nombre, str) or not nombre.strip():
        nombre = doc.split()[0] if doc.split() else Path(nombre_fichero).stem
    nombre = nombre.strip()
    if not _NOMBRE_RE.match(nombre):
        raise ValueError("nombre invalido %r: minusculas, digitos y _ (3-41 chars); ponlo en NOMBRE o al principio de DOC" % nombre)
    pruebas = consts.get("PRUEBAS")
    if not isinstance(pruebas, list) or not pruebas:
        raise ValueError("falta PRUEBAS = [ {\"args\": ..., \"espera\": ...}, ... ] con al menos una prueba: "
                         "sin prueba de punta a punta no se forja nada")
    if len(pruebas) > MAX_PRUEBAS:
        raise ValueError("demasiadas pruebas (%d, tope %d)" % (len(pruebas), MAX_PRUEBAS))
    limpias = []
    for i, p in enumerate(pruebas, 1):
        if not isinstance(p, dict):
            raise ValueError("prueba %d: debe ser un dict" % i)
        if "args" not in p:
            raise ValueError("prueba %d: falta 'args'" % i)
        if not any(k in p for k in ("espera", "espera_re", "no_espera", "espera_fichero")):
            raise ValueError("prueba %d: necesita espera / espera_re / no_espera / espera_fichero" % i)
        prep = p.get("prepara") or {}
        if not isinstance(prep, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in prep.items()):
            raise ValueError("prueba %d: 'prepara' debe ser {ruta_relativa: contenido}" % i)
        if any(Path(k).is_absolute() or ".." in Path(k).parts for k in prep):
            raise ValueError("prueba %d: 'prepara' solo admite rutas relativas dentro del directorio de prueba" % i)
        limpias.append(p)
    params = consts.get("PARAMS")
    if not isinstance(params, list):
        params = []
    params = [dict(x) for x in params if isinstance(x, dict) and x.get("nombre")]
    desc = consts.get("DESC")
    return {"nombre": nombre, "doc": doc, "desc": desc if isinstance(desc, str) else "",
            "params": params, "peligro": bool(consts.get("PELIGRO", False)),
            "pruebas": limpias, "run_args": n_args, "arbol": arbol}


def scan_estatico(codigo: str, arbol=None) -> str:
    """'' si pasa, si no el motivo. Blocklist corto: lo catastrofico."""
    arbol = arbol or ast.parse(codigo)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                if a.name.split(".")[0] in _IMPORTS_PROHIBIDOS:
                    return "import prohibido: %s" % a.name
        elif isinstance(nodo, ast.ImportFrom):
            if (nodo.module or "").split(".")[0] in _IMPORTS_PROHIBIDOS:
                return "import prohibido: from %s" % nodo.module
        elif isinstance(nodo, ast.Name) and nodo.id in _NOMBRES_PROHIBIDOS:
            return "nombre prohibido: %s" % nodo.id
        elif isinstance(nodo, ast.Attribute) and nodo.attr in ("__subclasses__", "__globals__", "__code__"):
            return "acceso prohibido: .%s" % nodo.attr
    for patron, etiqueta in _PATRONES_PROHIBIDOS:
        if re.search(patron, codigo, re.I):
            return "patron prohibido: %s" % etiqueta
    return ""


def es_peligrosa(codigo: str, declarado: bool) -> bool:
    if declarado:
        return True
    return any(re.search(m, codigo) for m in _MARCAS_PELIGRO)


# ---------------------------------------------------------------------------
# Examen dinamico: cada prueba en un subproceso, en un directorio limpio
# ---------------------------------------------------------------------------

_ARNES = r'''
import sys, io, traceback, inspect
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ruta, args, ws = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import importlib.util as _iu
    spec = _iu.spec_from_file_location("herramienta_forjada", ruta)
    mod = _iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ctx = {"workspace": ws, "cwd": ws, "_scratchpad": ws, "forja_prueba": True,
           "print_fn": (lambda *a, **k: None)}
    fn = mod.run
    n = len(inspect.signature(fn).parameters)
    out = fn(args, ctx) if n >= 2 else fn(args)
    sys.stdout.write("@@FORJA_OK@@\n" + ("" if out is None else str(out)))
except SystemExit as exc:
    sys.stdout.write("@@FORJA_EXC@@\nSystemExit(%r): la herramienta no debe llamar a sys.exit" % (exc.code,))
except BaseException:
    sys.stdout.write("@@FORJA_EXC@@\n" + traceback.format_exc())
'''


def _timeout_de(prueba: dict) -> int:
    try:
        t = int(prueba.get("timeout", TIMEOUT_PRUEBA_DEF_S))
    except Exception:
        t = TIMEOUT_PRUEBA_DEF_S
    return max(3, min(TIMEOUT_PRUEBA_MAX_S, t))


def correr_prueba(ruta_py: Path, prueba: dict) -> dict:
    """{ok, motivo, salida, ms} de UNA prueba, en un temp limpio y un subproceso."""
    ws = Path(tempfile.mkdtemp(prefix="cognia_forja_"))
    t0 = time.time()
    try:
        for rel, contenido in (prueba.get("prepara") or {}).items():
            destino = ws / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["COGNIA_EFIMERO"] = "1"
        raiz = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = raiz + os.pathsep + env.get("PYTHONPATH", "")
        args = prueba.get("args")
        args = "" if args is None else str(args)
        try:
            r = subprocess.run([sys.executable, "-c", _ARNES, str(ruta_py), args, str(ws)],
                               cwd=str(ws), env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=_timeout_de(prueba))
        except subprocess.TimeoutExpired:
            return {"ok": False, "motivo": "timeout (%ds)" % _timeout_de(prueba), "salida": "",
                    "ms": int((time.time() - t0) * 1000)}
        crudo = r.stdout or ""
        if "@@FORJA_EXC@@" in crudo:
            tb = crudo.split("@@FORJA_EXC@@", 1)[1].strip()
            return {"ok": False, "motivo": "excepcion: " + tb[-600:], "salida": crudo,
                    "ms": int((time.time() - t0) * 1000)}
        if "@@FORJA_OK@@" not in crudo:
            return {"ok": False, "motivo": "el subproceso no llego a run() (exit %s): %s"
                    % (r.returncode, (r.stderr or crudo)[-600:].strip()), "salida": crudo,
                    "ms": int((time.time() - t0) * 1000)}
        salida = crudo.split("@@FORJA_OK@@", 1)[1].lstrip("\n")
        esp = prueba.get("espera")
        if esp is not None and str(esp) not in salida:
            return {"ok": False, "motivo": "la salida no contiene %r; salio: %r" % (str(esp), salida[:200]),
                    "salida": salida, "ms": int((time.time() - t0) * 1000)}
        esp_re = prueba.get("espera_re")
        if esp_re and not re.search(str(esp_re), salida, re.S):
            return {"ok": False, "motivo": "la salida no casa con /%s/; salio: %r" % (esp_re, salida[:200]),
                    "salida": salida, "ms": int((time.time() - t0) * 1000)}
        no = prueba.get("no_espera")
        if no is not None and str(no) in salida:
            return {"ok": False, "motivo": "la salida contiene %r y no debia" % str(no),
                    "salida": salida, "ms": int((time.time() - t0) * 1000)}
        fich = prueba.get("espera_fichero")
        if fich:
            for f in ([fich] if isinstance(fich, str) else list(fich)):
                if not (ws / f).exists():
                    return {"ok": False, "motivo": "no dejo el fichero %s (hay: %s)"
                            % (f, ", ".join(p.name for p in ws.iterdir()) or "nada"),
                            "salida": salida, "ms": int((time.time() - t0) * 1000)}
        return {"ok": True, "motivo": "ok", "salida": salida, "ms": int((time.time() - t0) * 1000)}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def examinar(ruta_py: Path) -> dict:
    """Examen COMPLETO de un fichero: {ok, motivo, contrato, resultados}."""
    try:
        codigo = Path(ruta_py).read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "motivo": "no se pudo leer %s: %s" % (ruta_py, exc), "resultados": []}
    try:
        c = leer_contrato(codigo, Path(ruta_py).name)
    except ValueError as exc:
        return {"ok": False, "motivo": "contrato: %s" % exc, "resultados": []}
    mal = scan_estatico(codigo, c["arbol"])
    if mal:
        return {"ok": False, "motivo": "scan estatico: %s" % mal, "contrato": c, "resultados": []}
    resultados = []
    for i, p in enumerate(c["pruebas"], 1):
        r = correr_prueba(Path(ruta_py), p)
        r["n"] = i
        r["args"] = str(p.get("args", ""))
        resultados.append(r)
        if not r["ok"]:
            return {"ok": False, "motivo": "prueba %d (args=%r) fallo: %s" % (i, r["args"], r["motivo"]),
                    "contrato": c, "resultados": resultados}
    c.pop("arbol", None)
    return {"ok": True, "motivo": "%d/%d pruebas ok" % (len(resultados), len(resultados)),
            "contrato": c, "resultados": resultados, "codigo": codigo}


# ---------------------------------------------------------------------------
# Forjar: examinar + guardar + registrar
# ---------------------------------------------------------------------------

def forjar(ruta: str, ctx=None, origen: str = "") -> dict:
    """Examina el fichero y, si pasa, lo instala y registra. {ok, nombre, motivo, ...}."""
    if not encendida():
        return {"ok": False, "motivo": "la forja esta apagada (/forja on o COGNIA_FORJA=1)"}
    try:
        from cognia.agent import pruebas_comun as PC
        p = PC.resolver_ruta(ruta, debe_existir=True, ctx=ctx)
    except Exception as exc:
        return {"ok": False, "motivo": str(exc)}
    if p.suffix.lower() != ".py":
        return {"ok": False, "motivo": "la herramienta tiene que ser un .py (%s)" % p.name}
    ex = examinar(p)
    if not ex["ok"]:
        _anotar("forjar", str(p), ex["motivo"])
        return {"ok": False, "motivo": ex["motivo"], "resultados": ex.get("resultados", [])}
    c = ex["contrato"]
    nombre = c["nombre"]
    # No pisar una tool nativa del agente: el nombre es el contrato con el modelo.
    try:
        from cognia.agent.tools import TOOLS
        if nombre in TOOLS and not TOOLS[nombre].get("forjada"):
            return {"ok": False, "motivo": "ya existe una herramienta nativa llamada %r: elige otro nombre" % nombre}
    except Exception:
        pass
    d = directorio()
    destino = d / ("%s.py" % nombre)
    entradas = manifiesto()
    prev = next((e for e in entradas if e.get("nombre") == nombre), None)
    version = 1
    if prev is not None:
        version = int(prev.get("version", 1)) + 1
        if destino.exists():
            hist = d / "_historial"
            hist.mkdir(exist_ok=True)
            shutil.copyfile(destino, hist / ("%s_v%d.py" % (nombre, int(prev.get("version", 1)))))
    if p.resolve() != destino.resolve():
        shutil.copyfile(p, destino)
    codigo = ex["codigo"]
    nueva = {
        "nombre": nombre, "doc": c["doc"], "desc": c["desc"], "params": c["params"],
        "danger": es_peligrosa(codigo, c["peligro"]), "version": version,
        "tier": "staged", "usos_ok": 0, "usos_fail": 0, "fallos_seguidos": 0,
        "pruebas": len(c["pruebas"]), "sha": _sha(codigo), "creada": time.time(),
        "ultimo_uso": 0.0, "ultimo_error": "", "origen": (origen or "")[:200],
        "fichero": str(destino), "usos_ok_total": (prev or {}).get("usos_ok_total", 0),
    }
    entradas = [e for e in entradas if e.get("nombre") != nombre] + [nueva]
    _guardar_manifiesto(entradas)
    _CARGADAS.pop(nombre, None)
    n = cargar(solo=nombre)
    _anotar("forjar", "%s v%d (%d pruebas ok)" % (nombre, version, len(c["pruebas"])))
    return {"ok": True, "nombre": nombre, "version": version, "pruebas": len(c["pruebas"]),
            "danger": nueva["danger"], "fichero": str(destino), "registrada": n > 0,
            "resultados": ex["resultados"]}


# ---------------------------------------------------------------------------
# Carga y registro en el catalogo vivo
# ---------------------------------------------------------------------------

def _modulo(e: dict):
    """Namespace del fichero (cacheado por sha)."""
    nombre = e["nombre"]
    ruta = Path(e.get("fichero") or (directorio() / ("%s.py" % nombre)))
    codigo = ruta.read_text(encoding="utf-8")
    sha = _sha(codigo)
    hit = _CARGADAS.get(nombre)
    if hit and hit[0] == sha:
        return hit[1]
    mal = scan_estatico(codigo)
    if mal:
        raise ValueError("el fichero cambio y ya no pasa el scan: %s" % mal)
    ns: dict = {"__name__": "cognia_forja_" + nombre, "__file__": str(ruta)}
    exec(compile(codigo, str(ruta), "exec"), ns)
    if not callable(ns.get("run")):
        raise ValueError("el fichero ya no define run()")
    _CARGADAS[nombre] = (sha, ns)
    return ns


def _registrar_uso(nombre: str, ok: bool, error: str = "") -> str:
    """Contadores y transiciones de tier. Devuelve una nota para el modelo ('' si nada)."""
    entradas = manifiesto()
    e = next((x for x in entradas if x.get("nombre") == nombre), None)
    if e is None:
        return ""
    nota = ""
    e["ultimo_uso"] = time.time()
    if ok:
        e["usos_ok"] = int(e.get("usos_ok", 0)) + 1
        e["usos_ok_total"] = int(e.get("usos_ok_total", 0)) + 1
        e["fallos_seguidos"] = 0
        if e.get("tier") == "staged" and e["usos_ok"] >= ASCENSO_USOS_OK:
            e["tier"] = "verificada"
    else:
        e["usos_fail"] = int(e.get("usos_fail", 0)) + 1
        e["fallos_seguidos"] = int(e.get("fallos_seguidos", 0)) + 1
        e["ultimo_error"] = (error or "")[:300]
        if e["fallos_seguidos"] >= FALLOS_PARA_REPROBAR and e.get("tier") != "rota":
            ex = examinar(Path(e["fichero"]))
            if ex["ok"]:
                nota = ("[forja] %s fallo %d veces seguidas pero sus %d pruebas siguen pasando: "
                        "revisa los args que le pasas." % (nombre, e["fallos_seguidos"], len(ex["resultados"])))
                e["fallos_seguidos"] = 0
            else:
                e["tier"] = "rota"
                e["motivo_rota"] = ex["motivo"][:300]
                nota = ("[forja] %s queda ROTA: sus propias pruebas ya no pasan (%s). Corrigela en %s y "
                        "vuelve a `forjar %s`." % (nombre, ex["motivo"][:160], e["fichero"], e["fichero"]))
    _guardar_manifiesto(entradas)
    return nota


def _envolver(e: dict):
    nombre = e["nombre"]

    def _tool(args, ctx):
        try:
            ns = _modulo(entrada(nombre) or e)
        except Exception as exc:
            _registrar_uso(nombre, False, str(exc))
            return ("RESULTADO %s ERROR: la herramienta forjada no carga (%s). Corrigela en %s y vuelve a "
                    "`forjar` esa ruta." % (nombre, exc, e.get("fichero")))
        fn = ns["run"]
        try:
            import inspect
            n = len(inspect.signature(fn).parameters)
        except Exception:
            n = 2
        try:
            out = fn(args, ctx if isinstance(ctx, dict) else {}) if n >= 2 else fn(args)
            out = "" if out is None else str(out)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc().strip().splitlines()
            detalle = "%s: %s" % (type(exc).__name__, exc)
            nota = _registrar_uso(nombre, False, detalle)
            return ("RESULTADO %s ERROR: %s\n  %s\n(herramienta forjada: si el fallo es suyo, corrigela en %s y "
                    "vuelve a `forjar` esa ruta)%s" % (nombre, detalle, tb[-2] if len(tb) >= 2 else "",
                                                       e.get("fichero"), ("\n" + nota) if nota else ""))
        if not out.lstrip().startswith("RESULTADO"):
            out = "RESULTADO %s: %s" % (nombre, out)
        ok = " ERROR" not in out[:120]
        nota = _registrar_uso(nombre, ok, out[:300] if not ok else "")
        return out + (("\n" + nota) if nota else "")
    return _tool


def cargar(registry: dict = None, solo: str = "") -> int:
    """Registra en TOOLS las forjadas no rotas. Devuelve cuantas registro."""
    if not encendida():
        return 0
    try:
        from cognia.agent import tools as _T
    except Exception:
        return 0
    reg = registry if registry is not None else _T.TOOLS
    n = 0
    for e in manifiesto():
        nombre = e.get("nombre", "")
        if solo and nombre != solo:
            continue
        if e.get("tier") in ("rota", "retirada"):
            continue
        if not _NOMBRE_RE.match(nombre) or not Path(e.get("fichero", "")).exists():
            continue
        if nombre in reg and not reg[nombre].get("forjada"):
            _avisar("la forjada %r choca con una tool nativa; no se registra" % nombre)
            continue
        reg[nombre] = {"fn": _envolver(e), "doc": "%s  [forjada v%s, %s]" % (e["doc"], e.get("version", 1), e.get("tier", "staged")),
                       "danger": bool(e.get("danger")), "desc": e.get("desc") or "",
                       "params": list(e.get("params") or []), "timeout_s": None, "timeout_interno": None,
                       "forjada": True, "tier": e.get("tier", "staged")}
        try:
            for rol in ("implementador",):
                _T.ROLE_TOOLS[rol].add(nombre)
        except Exception:
            pass
        n += 1
    return n


def anunciadas() -> set:
    """Las MAX_ANUNCIADAS mejores: verificadas primero, luego por usos y por fecha."""
    if not encendida():
        return set()
    vivas = [e for e in manifiesto() if e.get("tier") in ("staged", "verificada")]
    vivas.sort(key=lambda e: (e.get("tier") != "verificada", -int(e.get("usos_ok_total", 0)),
                              -float(e.get("creada", 0))))
    return {e["nombre"] for e in vivas[:MAX_ANUNCIADAS]}


def retirar(nombre: str) -> dict:
    entradas = manifiesto()
    e = next((x for x in entradas if x.get("nombre") == nombre), None)
    if e is None:
        return {"ok": False, "motivo": "no hay una forjada llamada %r" % nombre}
    e["tier"] = "retirada"
    _guardar_manifiesto(entradas)
    try:
        from cognia.agent.tools import TOOLS
        if TOOLS.get(nombre, {}).get("forjada"):
            del TOOLS[nombre]
    except Exception:
        pass
    _anotar("retirar", nombre)
    return {"ok": True, "nombre": nombre}


def reprobar(nombre: str) -> dict:
    """Vuelve a correr las PRUEBAS de una forjada; repara el tier segun el resultado."""
    entradas = manifiesto()
    e = next((x for x in entradas if x.get("nombre") == nombre), None)
    if e is None:
        return {"ok": False, "motivo": "no hay una forjada llamada %r" % nombre}
    ex = examinar(Path(e["fichero"]))
    if ex["ok"]:
        if e.get("tier") == "rota":
            e["tier"] = "staged"
            e["fallos_seguidos"] = 0
            e.pop("motivo_rota", None)
        _guardar_manifiesto(entradas)
        _CARGADAS.pop(nombre, None)
        cargar(solo=nombre)
    else:
        e["tier"] = "rota"
        e["motivo_rota"] = ex["motivo"][:300]
        _guardar_manifiesto(entradas)
    _anotar("reprobar", "%s: %s" % (nombre, ex["motivo"]))
    return {"ok": ex["ok"], "motivo": ex["motivo"], "resultados": ex.get("resultados", []), "tier": e["tier"]}


# ---------------------------------------------------------------------------
# Observar el uso: repeticiones -> sugerencia de forjar (y candidatas)
# ---------------------------------------------------------------------------

def _huella_comando(name: str, args: str) -> tuple:
    """(huella, texto) de un comando repetible, o (None, '') si no aplica."""
    if name not in ("ejecutar", "ejecutar_fondo", "ejecutar_guion"):
        return None, ""
    s = " ".join((args or "").split())
    if not s:
        return None, ""
    # el comando sin sus valores numericos / rutas largas: `python informe.py 2024` ~ `python informe.py 2025`
    partes = s.split(" ")
    base = " ".join(partes[:3])
    base = re.sub(r"\d+", "N", base)
    if len(partes) < 2 or base.startswith(("pip ", "git ", "cd ", "dir", "ls", "type ", "cat ", "echo ")):
        return None, ""
    return _sha(base), base


def observar(name: str, args: str, ctx) -> str:
    """Cuenta repeticiones dentro de la sesion; devuelve la sugerencia cuando toca ('' si no)."""
    if not encendida():
        return ""
    huella, base = _huella_comando(name, args)
    if not huella:
        return ""
    # La clave de sesion: el ctx de la tarea es el MISMO dict durante toda la
    # corrida del agente (cli._ctx_agente), asi que su id sirve de sesion.
    if isinstance(ctx, dict):
        clave = str(ctx.get("_sesion_tools") or ctx.get("_task_id") or id(ctx))
    else:
        clave = "global"
    ses = _REPETIDOS.setdefault(clave, {})
    veces, _ = ses.get(huella, (0, base))
    veces += 1
    ses[huella] = (veces, base)
    if veces == REPETICIONES_SUGERIR:
        _apuntar_candidata(huella, base)
        return ("[forja] Ya van %d veces ejecutando `%s ...`. Si lo vas a repetir mas, conviertelo en una "
                "herramienta: escribe un .py con el contrato de `forjar plantilla` y llama a `forjar <ruta>`; "
                "quedara verificada y disponible en todas las tareas." % (veces, base))
    return ""


def _candidatas_ruta() -> Path:
    return directorio() / "candidatas.json"


def candidatas() -> dict:
    try:
        r = _candidatas_ruta()
        if r.exists():
            return json.loads(r.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _apuntar_candidata(huella: str, base: str) -> None:
    try:
        c = candidatas()
        e = c.setdefault(huella, {"comando": base, "veces": 0, "ultima": 0.0})
        e["veces"] = int(e.get("veces", 0)) + 1
        e["ultima"] = time.time()
        r = _candidatas_ruta()
        tmp = r.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, r)
    except Exception as exc:
        _avisar("no se pudo apuntar la candidata: %s" % exc)


def anexar_sugerencia(name: str, args: str, out: str, ctx) -> str:
    """run_tool lo llama tras cada tool: anexa la sugerencia de forja si toca. Nunca lanza."""
    try:
        s = observar(name, args, ctx)
    except Exception as exc:
        _avisar("observar: %s" % exc)
        return out
    return (out + "\n" + s) if s else out


def nota_capacidades(limite: int = MAX_ANUNCIADAS) -> str:
    """Una linea para el prompt: lo que Cognia se forjo (y lo que repite sin forjar)."""
    if not encendida():
        return ""
    vivas = [e for e in manifiesto() if e.get("tier") in ("staged", "verificada")]
    partes = []
    if vivas:
        vivas.sort(key=lambda e: -int(e.get("usos_ok_total", 0)))
        partes.append("Herramientas que forjaste tu misma y estan verificadas (usalas): "
                      + ", ".join(e["nombre"] for e in vivas[:limite]) + ".")
    cand = [c for c in candidatas().values() if int(c.get("veces", 0)) >= 2]
    if cand:
        cand.sort(key=lambda c: -int(c.get("veces", 0)))
        partes.append("Comandos que repites tarea tras tarea y aun no forjaste: "
                      + "; ".join("`%s`" % c["comando"] for c in cand[:3]) + ".")
    return " ".join(partes)


def estado() -> dict:
    vivas = manifiesto()
    return {"encendida": encendida(), "directorio": str(directorio()), "total": len(vivas),
            "por_tier": {t: sum(1 for e in vivas if e.get("tier") == t)
                         for t in ("staged", "verificada", "rota", "retirada")},
            "anunciadas": sorted(anunciadas()), "candidatas": len(candidatas()), "ultimo": dict(_ULTIMO)}


def texto_lista() -> str:
    vivas = manifiesto()
    if not vivas:
        return "(ninguna herramienta forjada todavia: `forjar plantilla` ensena el contrato)"
    anun = anunciadas()
    lineas = []
    for e in sorted(vivas, key=lambda x: (x.get("tier") != "verificada", x.get("nombre", ""))):
        lineas.append("  %-24s v%-2s %-10s usos ok %-3d fallos %-2d %s%s" % (
            e.get("nombre"), e.get("version", 1), e.get("tier", "?"), int(e.get("usos_ok_total", 0)),
            int(e.get("usos_fail", 0)), "anunciada" if e.get("nombre") in anun else "buscable",
            (" · rota: " + e.get("motivo_rota", "")[:80]) if e.get("tier") == "rota" else ""))
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# La tool `forjar` (entra en CORE_TOOLS: una linea del catalogo)
# ---------------------------------------------------------------------------

def _texto_resultados(res: list) -> str:
    return "\n".join("  prueba %d (args=%r): %s%s" % (r.get("n", i + 1), r.get("args", ""),
                                                      "OK" if r["ok"] else "FALLO", "" if r["ok"] else " · " + r["motivo"][:300])
                     for i, r in enumerate(res))


def register(tool) -> None:
    @tool("forjar",
          "forjar <ruta.py> | plantilla | lista | probar <nombre> | retirar <nombre>  -- FORJA una herramienta propia: "
          "escribe un .py con DOC, PRUEBAS y run(args, ctx), y `forjar <ruta>` lo examina (scan + cada prueba "
          "de punta a punta en un subproceso) y lo registra para esta y todas las tareas futuras",
          desc="Convierte un .py tuyo en una HERRAMIENTA nueva del catalogo, verificada de punta a punta. "
               "Cuando repitas un script o un comando (ejecutar python x.py ...) mas de dos veces, o cuando "
               "una capacidad te falte, escribe un fichero con el contrato (`forjar plantilla` te lo da: "
               "DOC de una linea, PRUEBAS con args/espera/prepara/espera_fichero, run(args, ctx) -> str) y "
               "llama a `forjar <ruta>`. Se rechaza si falla la sintaxis, el scan o cualquier prueba, y te "
               "dice cual. Si pasa, queda registrada YA (llamala por su nombre en el paso siguiente) y en "
               "todas las sesiones; con el uso asciende a verificada, y si se rompe te lo dice. "
               "`forjar lista` muestra las tuyas; `forjar probar <nombre>` repite sus pruebas; "
               "`forjar retirar <nombre>` la quita.",
          params=[{"nombre": "objetivo", "tipo": "string", "requerido": True,
                   "descripcion": "ruta del .py a forjar, o 'plantilla' / 'lista' / 'probar <nombre>' / 'retirar <nombre>'"}],
          danger=True, timeout_s=600)
    def _forjar(args, ctx):
        s = (args or "").strip().strip("\"'")
        bajo = s.lower()
        if not encendida():
            return "RESULTADO forjar ERROR: la forja esta DESHABILITADA (/forja on o COGNIA_FORJA=1)"
        if not s or bajo in ("plantilla", "ayuda", "help", "contrato"):
            return ("RESULTADO forjar plantilla: escribe un .py con este contrato y luego `forjar <ruta>`\n"
                    "```python\n" + PLANTILLA + "```")
        if bajo == "lista":
            return "RESULTADO forjar lista:\n" + texto_lista()
        if bajo.startswith("probar "):
            r = reprobar(s.split(None, 1)[1].strip())
            return "RESULTADO forjar probar %s: %s (tier %s)\n%s" % (
                "OK" if r["ok"] else "FALLO", r["motivo"], r.get("tier", "?"), _texto_resultados(r.get("resultados", [])))
        if bajo.startswith("retirar "):
            r = retirar(s.split(None, 1)[1].strip())
            return "RESULTADO forjar retirar: %s" % (r.get("nombre") + " retirada" if r["ok"] else "ERROR " + r["motivo"])
        r = forjar(s, ctx=ctx, origen=str((ctx or {}).get("_tarea", ""))[:200] if isinstance(ctx, dict) else "")
        if not r["ok"]:
            return ("RESULTADO forjar ERROR: %s\n%s\nCorrige el fichero y vuelve a llamar a `forjar %s`."
                    % (r["motivo"], _texto_resultados(r.get("resultados", [])), s))
        return ("RESULTADO forjar: '%s' v%d forjada y registrada (%d/%d pruebas de punta a punta OK%s). "
                "Ya puedes llamarla como `%s <args>` en el paso siguiente; queda en %s y estara en todas las "
                "tareas futuras.\n%s" % (r["nombre"], r["version"], r["pruebas"], r["pruebas"],
                                         ", marcada como peligrosa" if r["danger"] else "", r["nombre"],
                                         r["fichero"], _texto_resultados(r["resultados"])))


def ultimo() -> dict:
    return dict(_ULTIMO)
