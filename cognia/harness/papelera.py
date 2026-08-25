# -*- coding: utf-8 -*-
"""
cognia/harness/papelera.py
==========================
PAPELERA del agente: un borrado autorizado es REVERSIBLE y AUDITABLE.

POR QUE EXISTE (2026-08-25, con perdida de datos REAL). El unico freno a un
borrado era el clasificador de comandos (agent/sentinel.clasificar_shell), y
ese dia se le escaparon TRES formas seguidas -- `cd <carpeta> && del *.png`
(el cwd no viajaba entre segmentos), `python -c "...rmtree(...)"` (el peligro
vivia en el ARGUMENTO de un prefijo conocido-seguro) y el `cwd=` de la propia
tool. Con COGNIA_ACCESO_TOTAL=1 (el default de las sesiones del control
remoto) un veredicto CONFIRM procede solo, asi que el clasificador era la
UNICA red y las capturas del dueno se perdieron: `del` no pasa por la
papelera de Windows y no habia instantanea.

La leccion no es "otro parche al clasificador" (van cuatro tandas y cada
parche abrio un hueco nuevo): es que la reversibilidad no puede depender de
acertar el juicio. Esta pieza es la segunda red, INDEPENDIENTE del juicio:

  1. lo que la tool de borrado quita se MUEVE, no se destruye;
  2. antes de mover, se escribe la LISTA de lo que se va a quitar
     (ruta + bytes + mtime + sha256) en un indice jsonl -- si el proceso
     muere a mitad, el indice ya dice que habia;
  3. mas de N ficheros (config 'borrado_max_ficheros', default 10) exige
     confirmacion HUMANA aunque haya acceso total (eso lo aplica el
     llamador con `necesita_confirmacion`; aqui vive el numero).

LO QUE ESTA PIEZA NO PUEDE HACER (limite declarado, no descuido):
- No intercepta `del` / `rm` / `Remove-Item` ejecutados por el SHELL. Un
  borrado que corre dentro de cmd.exe o PowerShell no pasa por Python: no
  hay forma de darle una papelera desde aqui. Por eso el centinela, cuando
  frena un borrado de shell, DICE que existe `borrar_archivo` y que esa si
  va a la papelera (agent/sentinel._pista_papelera).
- El modo 'sistema' (papelera de Windows via send2trash o SHFileOperationW)
  se puede pedir, pero entonces la restauracion la hace el dueno desde la
  papelera de Windows: no se puede deshacer desde `/deshacer-borrado`. Por
  eso el DEFAULT es 'cognia' (papelera propia), que es la unica que este
  proceso puede devolver byte a byte.

Almacen (override por COGNIA_PAPELERA_DIR, leido a call-time para que los
tests aislen con tmp_path):

    ~/.cognia/papelera/<YYYY-MM-DD>/indice.jsonl      append-only, un JSON/linea
    ~/.cognia/papelera/<YYYY-MM-DD>/<lote>/C/Users/... el fichero movido, con
                                                       su ruta ORIGINAL debajo

El indice es append-only de verdad (nadie reescribe ni reordena lineas): el
estado de una ruta es su ULTIMO evento. Eventos: 'lote' (cabecera),
'inventario' (lo que se va a mover, escrito ANTES de tocar nada), 'movido',
'fallo', 'restaurado'.

API (la usan agent/tools.borrar_archivo y cli./deshacer-borrado):

    tope_ficheros()                  -> int (config 'borrado_max_ficheros')
    necesita_confirmacion(n)         -> bool
    inventario(rutas)                -> [{ruta, bytes, mtime, sha256}]
    enviar(rutas, motivo=...)        -> {lote, dia, dir, indice, movidos, ...}
    lotes(limite=...)                -> lotes, el mas nuevo primero
    restaurar(lote=None)             -> {lote, restaurados, conflictos, fallos}
    podar(dias=...)                  -> dias borrados de la papelera
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path

# Mismo append con lock entre procesos que usan el audit del centinela y
# backend_activo: dos Cognias borrando a la vez no entrelazan lineas.
from cognia.backend_activo import escribir_linea_jsonl

# Tope de rotacion del indice. Enorme A PROPOSITO: rotar renombra a .1 y eso
# dejaria lineas 'movido' fuera del alcance de restaurar(). El indice es POR
# DIA y guarda ~200 bytes por fichero, asi que 256 MB son ~1,3M de ficheros
# borrados en un dia; antes de eso el problema es otro.
_ROTAR_BYTES = 256 * 1024 * 1024

# Ficheros mas grandes que esto no se hashean (el sha es para auditar y
# verificar la restauracion, no vale un minuto de CPU).
_MAX_SHA_BYTES = 32 * 1024 * 1024

_TOPE_DEFECTO = 10
_DIAS_DEFECTO = 30


# ── configuracion ────────────────────────────────────────────────────────

def dir_papelera() -> Path:
    """Raiz de la papelera. COGNIA_PAPELERA_DIR la mueve (tests, sandbox)."""
    env = os.environ.get("COGNIA_PAPELERA_DIR", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".cognia" / "papelera"


def _config(clave: str) -> str:
    """Valor de una clave: entorno primero, luego ~/.cognia/config.env.

    Se acepta la clave a secas ('borrado_max_ficheros', que es como la pide
    el dueno) y su forma COGNIA_ (la del resto del arnes)."""
    variantes = (clave, clave.upper(), "COGNIA_" + clave.upper())
    for k in variantes:
        v = os.environ.get(k, "").strip()
        if v:
            return v
    try:
        from cognia import first_run
        cfg = first_run._load_config()
    except Exception:
        return ""
    for k in variantes:
        v = str(cfg.get(k, "")).strip()
        if v:
            return v
    return ""


def tope_ficheros() -> int:
    """Cuantos ficheros puede quitar UNA operacion sin preguntarle a un humano.

    Config 'borrado_max_ficheros' (default 10). Un valor invalido o <=0 cae al
    default: un tope de 0 apagaria el freno, y un tope negativo lo volveria
    absurdo; degradar hacia la seguridad."""
    crudo = _config("borrado_max_ficheros")
    try:
        n = int(crudo)
    except (TypeError, ValueError):
        return _TOPE_DEFECTO
    return n if n > 0 else _TOPE_DEFECTO


def necesita_confirmacion(n_ficheros: int) -> bool:
    """True si N ficheros pasan del tope. El llamador DEBE preguntar aunque
    haya COGNIA_ACCESO_TOTAL=1: el tope es el freno que no depende del juicio
    del clasificador."""
    return int(n_ficheros or 0) > tope_ficheros()


def modo() -> str:
    """'cognia' (papelera propia, restaurable desde aqui) o 'sistema'
    (papelera de Windows; la restauracion la hace el dueno a mano)."""
    v = _config("borrado_papelera").lower()
    return "sistema" if v in ("sistema", "system", "windows", "so") else "cognia"


# ── inventario ───────────────────────────────────────────────────────────

def _sha256(p: Path) -> str | None:
    try:
        if p.stat().st_size > _MAX_SHA_BYTES:
            return None
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for bloque in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(bloque)
        return h.hexdigest()
    except OSError:
        return None


def inventario(rutas) -> list:
    """[{ruta, bytes, mtime, sha256}] de lo que se va a borrar, en orden.

    Nunca lanza por un fichero raro: lo que no se puede medir sale con
    bytes=None y el motivo en 'error' (el borrado no se detiene por no poder
    hashear, pero la linea del indice lo deja escrito)."""
    filas = []
    for r in rutas:
        p = Path(r)
        fila = {"ruta": str(p), "bytes": None, "mtime": None, "sha256": None}
        try:
            st = p.stat()
            fila["bytes"] = st.st_size
            fila["mtime"] = st.st_mtime
            fila["sha256"] = _sha256(p)
        except OSError as exc:
            fila["error"] = f"{type(exc).__name__}: {exc}"
        filas.append(fila)
    return filas


# ── almacen ──────────────────────────────────────────────────────────────

def _dia() -> str:
    return date.today().isoformat()


def _indice(dia: str) -> Path:
    return dir_papelera() / dia / "indice.jsonl"


def _append(dia: str, fila: dict) -> None:
    fila.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    linea = (json.dumps(fila, ensure_ascii=False) + "\n").encode("utf-8")
    escribir_linea_jsonl(_indice(dia), linea, _ROTAR_BYTES)


def _clave_ruta(p: Path) -> Path:
    r"""Ruta RELATIVA que conserva la original bajo el directorio del lote.

    C:\Users\u\Pictures\a.png  ->  C/Users/u/Pictures/a.png
    /home/u/a.png              ->  _raiz_/home/u/a.png

    Asi el dueno ve de un vistazo de donde salio cada fichero, y restaurar es
    volver a pegar el prefijo."""
    p = Path(os.path.abspath(str(p)))
    drive = p.drive                      # 'C:' en Windows, '' en POSIX
    partes = [x for x in p.parts if x not in ("\\", "/", drive, drive + "\\")]
    raiz = re.sub(r"[^A-Za-z0-9]", "", drive) or "_raiz_"
    return Path(raiz, *partes)


def _leer_indice(dia: str) -> list:
    ruta = _indice(dia)
    if not ruta.is_file():
        return []
    filas = []
    try:
        crudo = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            filas.append(json.loads(linea))
        except ValueError:
            continue                     # linea a medias: se ignora, no rompe
    return filas


def _dias() -> list:
    """Dias con papelera, el mas nuevo primero."""
    raiz = dir_papelera()
    if not raiz.is_dir():
        return []
    out = []
    for d in raiz.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            out.append(d.name)
    return sorted(out, reverse=True)


# ── enviar a la papelera ─────────────────────────────────────────────────

def _a_sistema(p: Path) -> str:
    """Manda UN fichero a la papelera del SO. Devuelve '' si fue, o el motivo.

    send2trash si esta instalado; si no, la API del shell de Windows por
    ctypes (SHFileOperationW con FOF_ALLOWUNDO), que no pide dependencia."""
    try:
        from send2trash import send2trash        # type: ignore
        send2trash(str(p))
        return ""
    except ImportError:
        pass
    except Exception as exc:
        return f"send2trash: {type(exc).__name__}: {exc}"
    if os.name != "nt":
        return "sin send2trash y el SO no es Windows"
    try:
        import ctypes
        from ctypes import wintypes

        class _SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND),
                        ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16),
                        ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT = 0x3, 0x40, 0x10, 0x4
        op = _SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        # pFrom es una lista terminada en DOBLE nul.
        op.pFrom = str(Path(os.path.abspath(str(p)))) + "\0\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc != 0:
            return f"SHFileOperationW rc={rc}"
        return ""
    except Exception as exc:
        return f"SHFileOperationW: {type(exc).__name__}: {exc}"


def enviar(rutas, motivo: str = "", tool: str = "", forzar_modo: str = "") -> dict:
    """Mueve `rutas` a la papelera. Devuelve el parte, nunca lanza por un
    fichero suelto.

    Orden NO negociable: se escribe el inventario ANTES de tocar nada. Si el
    proceso muere a mitad, el indice ya dice que habia y donde estaba.

    Un fichero que no se puede mover se queda DONDE ESTA y sale en 'fallos':
    esta pieza jamas convierte un fallo de papelera en un borrado duro."""
    rutas = [Path(os.path.abspath(str(r))) for r in rutas]
    dia = _dia()
    lote = f"{time.strftime('%H%M%S')}-{os.urandom(2).hex()}"
    base = dir_papelera() / dia / lote
    filas = inventario(rutas)
    total_bytes = sum(f["bytes"] or 0 for f in filas)
    _modo = (forzar_modo or modo())

    _append(dia, {"evento": "lote", "lote": lote, "n": len(filas),
                  "bytes": total_bytes, "motivo": motivo, "tool": tool,
                  "modo": _modo, "pid": os.getpid(),
                  "cwd": os.getcwd() if _cwd_ok() else ""})
    for f in filas:
        _append(dia, dict(f, evento="inventario", lote=lote))

    movidos, fallos = [], []
    for f in filas:
        origen = Path(f["ruta"])
        if _modo == "sistema":
            err = _a_sistema(origen)
            if err:
                fallos.append({"ruta": str(origen), "error": err})
                _append(dia, {"evento": "fallo", "lote": lote,
                              "ruta": str(origen), "error": err})
            else:
                movidos.append({"ruta": str(origen), "destino": None})
                _append(dia, {"evento": "movido", "lote": lote,
                              "ruta": str(origen), "destino": None,
                              "restaurable": False, "modo": "sistema",
                              "bytes": f["bytes"], "sha256": f["sha256"]})
            continue
        destino = base / _clave_ruta(origen)
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
        except (OSError, shutil.Error) as exc:
            err = f"{type(exc).__name__}: {exc}"
            fallos.append({"ruta": str(origen), "error": err})
            _append(dia, {"evento": "fallo", "lote": lote,
                          "ruta": str(origen), "error": err})
            continue
        movidos.append({"ruta": str(origen), "destino": str(destino)})
        _append(dia, {"evento": "movido", "lote": lote, "ruta": str(origen),
                      "destino": str(destino), "restaurable": True,
                      "modo": "cognia", "bytes": f["bytes"],
                      "sha256": f["sha256"]})

    try:
        podar()
    except Exception:
        pass                              # la poda jamas rompe un borrado

    return {"lote": lote, "dia": dia, "dir": str(base),
            "indice": str(_indice(dia)), "modo": _modo,
            "n": len(filas), "bytes": total_bytes,
            "movidos": movidos, "fallos": fallos,
            "inventario": filas}


def _cwd_ok() -> bool:
    try:
        os.getcwd()
        return True
    except OSError:
        return False


# ── listar / restaurar ───────────────────────────────────────────────────

def lotes(limite: int = 20) -> list:
    """Lotes de la papelera, el mas nuevo primero.

    Cada uno: {lote, dia, ts, n, bytes, motivo, tool, modo, movidos,
    restaurables, restaurados}."""
    out = []
    for dia in _dias():
        filas = _leer_indice(dia)
        cab, por_lote = {}, {}
        for fila in filas:
            lid = fila.get("lote")
            if not lid:
                continue
            if fila.get("evento") == "lote":
                cab[lid] = fila
            por_lote.setdefault(lid, []).append(fila)
        # orden de aparicion invertido: dentro de un dia, el ultimo primero
        for lid in list(por_lote)[::-1]:
            movidos = [f for f in por_lote[lid] if f.get("evento") == "movido"]
            restaurados = {f.get("ruta") for f in por_lote[lid]
                           if f.get("evento") == "restaurado"}
            c = cab.get(lid, {})
            out.append({
                "lote": lid, "dia": dia, "ts": c.get("ts", ""),
                "n": c.get("n", len(movidos)), "bytes": c.get("bytes", 0),
                "motivo": c.get("motivo", ""), "tool": c.get("tool", ""),
                "modo": c.get("modo", "cognia"),
                "movidos": movidos,
                "restaurables": [f for f in movidos
                                 if f.get("restaurable")
                                 and f.get("ruta") not in restaurados],
                "restaurados": sorted(restaurados),
            })
            if len(out) >= limite:
                return out
    return out


def _destino_libre(ruta: Path) -> tuple:
    """(destino, conflicto). Si la ruta original esta OCUPADA no se pisa: se
    restaura al lado con sufijo. Restaurar jamas destruye lo que hay ahora."""
    if not ruta.exists():
        return ruta, False
    for i in range(1, 1000):
        alt = ruta.with_name(f"{ruta.stem}.restaurado-{i}{ruta.suffix}")
        if not alt.exists():
            return alt, True
    return ruta.with_name(ruta.name + ".restaurado"), True


def restaurar(lote: str = None) -> dict:
    """Devuelve a su sitio lo del lote dado (o el ULTIMO restaurable).

    Byte-exacto por construccion: los ficheros se MOVIERON, no se copiaron ni
    se reescribieron. Un destino ocupado no se pisa (sale en 'conflictos')."""
    candidatos = lotes(limite=200)
    elegido = None
    for l in candidatos:
        if lote and l["lote"] != lote:
            continue
        if lote or l["restaurables"]:
            elegido = l
            break
    if elegido is None:
        if lote:
            err = f"lote {lote} no encontrado"
        elif any(f for l in candidatos for f in l["movidos"]
                 if not f.get("restaurable")):
            # Hay borrados registrados, pero fueron a la papelera del SO: decir
            # DONDE estan es lo unico util aqui ("no hay nada" seria mentira).
            err = ("lo ultimo que se borro fue a la papelera de Windows "
                   "(borrado_papelera=sistema): restauralo desde ahi")
        else:
            err = "no hay nada que restaurar en la papelera"
        return {"ok": False, "error": err,
                "restaurados": [], "conflictos": [], "fallos": []}

    restaurados, conflictos, fallos = [], [], []
    pendientes = elegido["restaurables"]
    if not pendientes:
        no_rest = [f for f in elegido["movidos"] if not f.get("restaurable")]
        return {"ok": False, "lote": elegido["lote"], "dia": elegido["dia"],
                "error": ("ese lote ya se restauro" if not no_rest else
                          "ese lote fue a la papelera del SISTEMA: "
                          "restauralo desde la papelera de Windows"),
                "restaurados": [], "conflictos": [], "fallos": []}

    for f in pendientes:
        origen = Path(f.get("destino") or "")
        ruta = Path(f.get("ruta") or "")
        if not origen.is_file():
            fallos.append({"ruta": str(ruta),
                           "error": f"no esta en la papelera: {origen}"})
            continue
        destino, choque = _destino_libre(ruta)
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
        except (OSError, shutil.Error) as exc:
            fallos.append({"ruta": str(ruta),
                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        _append(elegido["dia"], {"evento": "restaurado", "lote": elegido["lote"],
                                 "ruta": str(ruta), "destino": str(destino),
                                 "conflicto": choque})
        if choque:
            conflictos.append({"ruta": str(ruta), "destino": str(destino)})
        restaurados.append(str(destino))
    return {"ok": bool(restaurados), "lote": elegido["lote"],
            "dia": elegido["dia"], "motivo": elegido.get("motivo", ""),
            "restaurados": restaurados, "conflictos": conflictos,
            "fallos": fallos}


def podar(dias: int = None) -> list:
    """Borra de la papelera los DIAS mas viejos que el tope (default 30, config
    'borrado_papelera_dias'). Devuelve los dias eliminados.

    Es el unico sitio de este modulo que destruye algo, y solo cosas que ya
    estaban borradas hace semanas. Un valor <=0 apaga la poda."""
    if dias is None:
        try:
            dias = int(_config("borrado_papelera_dias") or _DIAS_DEFECTO)
        except ValueError:
            dias = _DIAS_DEFECTO
    if dias <= 0:
        return []
    limite = date.today().toordinal() - dias
    fuera = []
    for d in _dias():
        try:
            y, m, dd = (int(x) for x in d.split("-"))
            if date(y, m, dd).toordinal() < limite:
                shutil.rmtree(dir_papelera() / d, ignore_errors=True)
                fuera.append(d)
        except (ValueError, OSError):
            continue
    return fuera


def resumen(parte: dict) -> str:
    """Una linea para el modelo/el dueno a partir de lo que devolvio enviar()."""
    n = len(parte.get("movidos") or [])
    b = parte.get("bytes") or 0
    tam = f"{b} bytes" if b < 1024 else f"{b / 1024.0:.1f} KB"
    txt = (f"{n} fichero(s), {tam} -> papelera "
           f"{parte.get('dia')}/{parte.get('lote')}")
    if parte.get("modo") == "sistema":
        txt += " (papelera de Windows: restaura desde ahi)"
    else:
        txt += " (/deshacer-borrado restaura)"
    if parte.get("fallos"):
        txt += f"; {len(parte['fallos'])} NO se pudo mover"
    return txt
