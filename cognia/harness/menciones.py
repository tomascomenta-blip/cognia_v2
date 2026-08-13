# -*- coding: utf-8 -*-
"""
cognia/harness/menciones.py
===========================
@-menciones de ficheros: meter contexto EXACTO en el prompt sin copiar y pegar.

POR QUE EXISTE (2026-08-12): Cognia ya sabe donde esta cada cosa
(`cognia/mapa_proyecto.py`), pero nadie cablea esas rutas al prompt: el usuario
que quiere que el agente mire `cognia/agent/loop.py` tiene que pegar el fichero
a mano (gasta ventana, se corta, se desincroniza) o rezar para que el agente lo
abra solo (un `leer_archivo` mas de latencia, y a veces abre otro). La insignia
universal de los CLIs de coding resuelve justo eso: Claude Code y Cursor/Cline
usan `@ruta`, Gemini CLI `@path/to/file`, Aider `/add`. Aca se implementa la
variante `@ruta` porque se escribe DENTRO de la frase ("arregla el bug de
@cognia/agent/loop.py") y no rompe el turno como haria un comando aparte.

API publica (lo que el integrador cablea; este modulo no toca el CLI):

    detectar(texto, raiz=None) -> [{"token", "ruta", "inicio", "fin"}, ...]
        Menciones en orden de aparicion. `texto[inicio:fin] == token` siempre.
        `raiz` es opcional y solo desempata el caso decorador (regla 2 de abajo).

    expandir(texto, raiz, max_bytes_por_fichero=64*1024, max_total=256*1024)
        -> (texto_expandido, adjuntos, avisos)
        Para el turno del usuario: deja la mencion VISIBLE en la frase (el
        modelo tiene que ver de que fichero se habla) y anexa al final un bloque
        "--- @ruta ---\\n<contenido>" por mencion resuelta.

    completar_rutas(prefijo, raiz, limite=20) -> [ruta, ...]
        Para el autocompletado del REPL cuando el usuario teclea "@..." (los
        directorios vuelven con "/" al final para poder seguir tecleando).

COMO SE DISTINGUE UNA MENCION DE UN EMAIL O UN DECORADOR (la regla, explicita):
  1. EMAIL — el `@` de una mencion tiene que abrir token: solo se acepta si esta
     al principio del texto o precedido de espacio o de `([{<`. En
     `algo@algo.com` el `@` viene pegado a una letra, asi que no es mencion.
     Corolario honesto: `@algo.com` suelto SI es mencion (y quedara como "no
     existe" en avisos), pero eso es exactamente lo que el usuario tecleo.
  2. DECORADOR — la sospecha solo aparece con un token CRUDO (sin comillas) que
     es lo primero de su linea y NO lleva separador (`/` o `\\`); ahi
     `@dataclass` y `@app.route(...)` son codigo pegado y `@loop.py` es una
     mencion legitima (el usuario empieza el turno nombrando el fichero). Se
     desempata en dos pasos: (a) si se paso `raiz` y la ruta EXISTE en disco, es
     mencion — el disco decide, que es lo unico que no opina; (b) sin disco,
     `@nombre.ext` con UN punto y extension de 1-4 alfanumericos es fichero
     (`README.md`, `loop.py`), y el resto es decorador (`dataclass` no tiene
     punto, `app.route` tiene extension de 5, `pytest.mark.parametrize` tiene
     dos puntos). Limite declarado: `@src` (directorio, sin punto y sin barra) a
     principio de linea SOLO se detecta si se pasa `raiz`; escrito a mitad de
     frase, o como `@src/` o `@"src"`, se detecta siempre.

LIMITES DECLARADOS (lo que este modulo NO hace):
  - No hay sandbox de rutas: `@../otro/repo/x.py` y las rutas absolutas se
    resuelven tal cual. Es una accion EXPLICITA del usuario, igual que en
    Claude Code; si el integrador quiere confinar al proyecto, que filtre los
    adjuntos por `raiz` antes de mandarlos al modelo.
  - Ficheros de mas de 32 MiB no se anexan (solo nombre y tamano): trocear por
    el medio exige leerlos enteros y eso es un DoS autoinfligido.
  - Los binarios se detectan por NUL en los primeros 8 KiB (heuristica de
    git/grep). El resto se decodifica utf-8 con `errors="replace"` SOLO para
    mostrar; jamas se reescribe nada (leccion Latin-1 del repo).
  - El .gitignore se aplica "simple": patrones de la raiz, sin negaciones (`!`)
    y sin .gitignore anidados. Alcanza para el autocompletado, no pretende ser
    git.
  - `completar_rutas` deja de recorrer a las 20.000 entradas candidatas.

Solo stdlib. No escribe en disco. No toca BD.
"""

from __future__ import annotations

import os
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Tuple

# Directorios que nunca se ofrecen ni se listan: son dependencias o basura de
# build. Se excluyen SIEMPRE, este o no este el .gitignore.
_SIEMPRE_FUERA = {".git", "__pycache__", "node_modules", ".pytest_cache"}
_SIEMPRE_FUERA_GLOB = ("venv*",)

# Tope de lectura: por encima de esto solo se anexa nombre y tamano.
_MAX_LEER = 32 * 1024 * 1024
# Entradas de un directorio que se listan como mucho (lo pide el encargo).
_MAX_ENTRADAS_DIR = 200
# Corte del recorrido de completar_rutas: un arbol enorme no puede colgar el REPL.
_MAX_CANDIDATOS = 20_000
# Bytes que se le reservan a la marca "... [N lineas omitidas] ..." dentro del
# presupuesto del fichero: si no se descuenta, el cuerpo troceado se pasa de
# `max_bytes_por_fichero` justo por la marca que anuncia el troceo.
_RESERVA_MARCA = 48

# Caracteres que puede tener una ruta cruda. Se excluyen los que Windows prohibe
# en nombres (`" < > | * ?`), los parentesis/corchetes (asi `@app.route(...)`
# corta en el parentesis y se ve como decorador) y `,;` para poder escribir
# listas: "@a.py, @b.py".
_CHARS_RUTA = r"[^\s\"'()\[\]{}<>|*?,;]"
_RE_MENCION = re.compile(
    r"@(?:\"(?P<comilla2>[^\"\n]+)\""
    r"|'(?P<comilla1>[^'\n]+)'"
    r"|(?P<cruda>" + _CHARS_RUTA + r"+))"
)
# Un `@` solo abre mencion si viene tras esto (o al principio del texto).
_PRECEDE_OK = set(" \t\r\n([{<")
# Puntuacion de final de frase que se devuelve al texto: "mira @loop.py." no
# menciona el fichero "loop.py.".
_PUNTUACION_FINAL = ".:!"


def _es_ruta_de_verdad(ruta: str) -> bool:
    """Un token con separador es ruta si o si; sin separador puede ser decorador."""
    return "/" in ruta or "\\" in ruta


# Extension de fichero "de verdad" para el desempate sin disco: UN punto y de 1
# a 4 alfanumericos detras (py, md, txt, json, cfg). `app.route` (5) y
# `pytest.mark.parametrize` (dos puntos) caen fuera, que es el objetivo.
_RE_EXTENSION = re.compile(r"[^.]+\.[A-Za-z0-9]{1,4}$")


def _parece_fichero(ruta: str) -> bool:
    return ruta.count(".") == 1 and _RE_EXTENSION.match(ruta) is not None


def _existe(base: Path, ruta: str) -> bool:
    try:
        return _resolver(base, ruta).exists()
    except OSError:
        return False


def detectar(texto: str, raiz=None) -> List[Dict]:
    """
    Menciones `@ruta` del texto, en orden de aparicion.

    Cada mencion es {"token", "ruta", "inicio", "fin"} y cumple
    `texto[inicio:fin] == token`, para que el caller pueda reemplazar o resaltar
    sin volver a buscar. Emails y decoradores se descartan (ver el docstring del
    modulo).

    `raiz` es OPCIONAL y solo sirve para ese desempate: con ella, un token a
    principio de linea que existe en disco se acepta aunque no lleve barra
    (`@src`). Sin ella la deteccion es puramente sintactica; el resto de la
    funcion no mira el disco en ningun caso.
    """
    if not texto:
        return []

    base = Path(raiz) if raiz is not None else None
    menciones: List[Dict] = []
    for m in _RE_MENCION.finditer(texto):
        inicio = m.start()
        if inicio > 0 and texto[inicio - 1] not in _PRECEDE_OK:
            continue                                   # regla 1: email

        cruda = m.group("cruda")
        if cruda is not None:
            ruta = cruda.rstrip(_PUNTUACION_FINAL)
            if not ruta:
                # `@.` y `@..` son el directorio actual y el padre, no
                # puntuacion suelta: son lo unico que sobrevive al rstrip.
                if cruda not in (".", ".."):
                    continue
                ruta = cruda
            fin = inicio + 1 + len(ruta)
            arranque_linea = texto.rfind("\n", 0, inicio) + 1
            if (not texto[arranque_linea:inicio].strip()
                    and not _es_ruta_de_verdad(ruta)
                    and not (base is not None and _existe(base, ruta))
                    and not _parece_fichero(ruta)):
                continue                               # regla 2: decorador
        else:
            ruta = m.group("comilla2") or m.group("comilla1")
            fin = m.end()

        menciones.append({
            "token":  texto[inicio:fin],
            "ruta":   ruta,
            "inicio": inicio,
            "fin":    fin,
        })
    return menciones


def _excluido(nombre: str) -> bool:
    return (nombre in _SIEMPRE_FUERA
            or any(fnmatch(nombre, g) for g in _SIEMPRE_FUERA_GLOB))


def _resolver(base: Path, ruta: str) -> Path:
    """Ruta de la mencion a ruta real. `~` se expande; lo relativo cuelga de la raiz."""
    p = Path(ruta)
    try:
        p = p.expanduser()
    except (RuntimeError, OSError, ValueError):
        # `@~usuario_que_no_existe/x.py` levanta RuntimeError en POSIX (pathlib
        # no puede resolver el home). Una mencion mala NO puede tumbar el turno:
        # se deja el `~` literal y saldra por avisos como "no existe".
        pass
    return p if p.is_absolute() else base / p


def _clave(destino: Path) -> str:
    """Identidad de un destino para deduplicar: `@a.py` y `@./a.py` son el mismo."""
    return os.path.normcase(os.path.normpath(str(destino)))


def _bloque_directorio(destino: Path) -> Dict:
    """Listado de un nivel (no el contenido): lo util de un directorio es que hay."""
    entradas = sorted(
        (h.name + ("/" if h.is_dir() else "")
         for h in destino.iterdir() if not _excluido(h.name)),
        key=str.lower,
    )
    visibles = entradas[:_MAX_ENTRADAS_DIR]
    cuerpo = f"[directorio] {len(entradas)} entradas\n" + "\n".join(visibles)
    if len(entradas) > _MAX_ENTRADAS_DIR:
        cuerpo += f"\n... [{len(entradas) - _MAX_ENTRADAS_DIR} entradas mas omitidas]"
    return {"tipo": "directorio", "bytes": 0, "cuerpo": cuerpo, "lineas_omitidas": 0}


def _bloque_fichero(destino: Path, max_bytes: int) -> Dict:
    """Contenido del fichero, troceado POR EL MEDIO si no entra en el presupuesto."""
    tam = destino.stat().st_size
    if tam > _MAX_LEER:
        return {"tipo": "grande", "bytes": tam, "lineas_omitidas": 0,
                "cuerpo": f"[demasiado grande] {destino.name} — {tam} bytes"}

    crudo = destino.read_bytes()
    if b"\x00" in crudo[:8192]:
        # Heuristica de git/grep: volcar bytes de un binario al prompt es ruido.
        return {"tipo": "binario", "bytes": tam, "lineas_omitidas": 0,
                "cuerpo": f"[binario] {destino.name} — {tam} bytes"}

    texto = crudo.decode("utf-8", errors="replace")
    # Se mide el TEXTO, no el fichero: con errors="replace" cada byte invalido
    # se vuelve U+FFFD (3 bytes en utf-8), asi que un latin-1 que entra en el
    # presupuesto en disco puede salir hasta 3x mas gordo en el prompt.
    if len(crudo) <= max_bytes:
        medido = len(texto.encode("utf-8"))
        if medido <= max_bytes:
            return {"tipo": "fichero", "bytes": tam, "lineas_omitidas": 0,
                    "cuerpo": texto}

    # Cabeza y cola a mitad de presupuesto cada una: el principio de un fichero
    # (imports, firma) y el final (lo que se acaba de escribir) es lo que se
    # mira; el medio es lo prescindible. Se le descuenta antes la marca de corte.
    lineas = texto.splitlines()
    mitad = max(max_bytes - _RESERVA_MARCA, 0) // 2

    cabeza: List[str] = []
    usado = 0
    for ln in lineas:
        usado += len(ln.encode("utf-8")) + 1
        if usado > mitad:
            break
        cabeza.append(ln)

    # La cola arranca DONDE ACABA LA CABEZA. Sin ese tope se solapaban: al
    # reunir con "\n" cada linea pesa 1 byte menos que en un fichero CRLF (lo
    # normal en Windows), asi que cabeza+cola llegaban a cubrir el fichero
    # entero -> contenido DUPLICADO y `lineas_omitidas` NEGATIVO (-112 medido
    # con 400 lineas CRLF y max_bytes=1024).
    cola: List[str] = []
    usado = 0
    for ln in reversed(lineas[len(cabeza):]):
        usado += len(ln.encode("utf-8")) + 1
        if usado > mitad:
            break
        cola.append(ln)
    cola.reverse()

    omitidas = len(lineas) - len(cabeza) - len(cola)
    if omitidas <= 0:
        # Cabe entero al reunirlo con "\n" (caso CRLF): no hay nada que omitir
        # y anunciar un corte que no existe seria mentir.
        return {"tipo": "fichero", "bytes": tam, "lineas_omitidas": 0,
                "cuerpo": "\n".join(lineas)}

    cuerpo = "\n".join(
        cabeza + [f"... [{omitidas} lineas omitidas] ..."] + cola)
    return {"tipo": "fichero", "bytes": tam, "lineas_omitidas": omitidas,
            "cuerpo": cuerpo}


def expandir(texto: str,
             raiz,
             max_bytes_por_fichero: int = 64 * 1024,
             max_total: int = 256 * 1024) -> Tuple[str, List[Dict], List[str]]:
    """
    Resuelve las menciones del texto contra `raiz`.

    Devuelve (texto_expandido, adjuntos, avisos):
      - texto_expandido: el texto TAL CUAL (la mencion sigue visible en la
        frase) mas un bloque por mencion resuelta: "--- @ruta ---\\n<contenido>".
        Si no se resolvio ninguna, se devuelve el texto sin tocar.
      - adjuntos: [{"ruta", "absoluta", "tipo", "bytes", "lineas_omitidas",
        "contenido"}] con tipo en fichero/directorio/binario/grande.
      - avisos: strings para el usuario (no existe, truncado, presupuesto,
        ilegible). Nada de esto lanza: una mencion mala no puede tumbar el turno.

    Un mismo DESTINO mencionado dos veces se anexa UNA (`@a.py` y `@./a.py` son
    el mismo fichero): el modelo no gana nada leyendolo repetido y el
    presupuesto es finito.
    """
    base = Path(raiz)
    adjuntos: List[Dict] = []
    avisos: List[str] = []
    bloques: List[str] = []
    total = 0
    vistas = set()

    for mencion in detectar(texto, base):
        ruta = mencion["ruta"]
        # Se deduplica por DESTINO resuelto, no por el texto tecleado: `@a.py`,
        # `@./a.py` y (en Windows) `@A.py` son el mismo fichero y anexarlo dos
        # veces gasta presupuesto sin darle nada nuevo al modelo.
        destino = _resolver(base, ruta)
        clave = _clave(destino)
        if clave in vistas:
            continue
        vistas.add(clave)

        try:
            if not destino.exists():
                avisos.append(f"no existe: @{ruta}")
                continue
            info = (_bloque_directorio(destino) if destino.is_dir()
                    else _bloque_fichero(destino, max_bytes_por_fichero))
        except OSError as exc:
            avisos.append(f"no se pudo leer @{ruta}: {type(exc).__name__}: {exc}")
            continue

        coste = len(info["cuerpo"].encode("utf-8"))
        if total + coste > max_total:
            avisos.append(
                f"presupuesto de {max_total} bytes agotado: @{ruta} no se anexo")
            continue
        total += coste

        if info["lineas_omitidas"]:
            avisos.append(
                f"truncado por el medio: @{ruta} "
                f"({info['lineas_omitidas']} lineas omitidas)")

        bloques.append(f"--- @{ruta} ---\n{info['cuerpo']}")
        adjuntos.append({
            "ruta":            ruta,
            "absoluta":        str(destino),
            "tipo":            info["tipo"],
            "bytes":           info["bytes"],
            "lineas_omitidas": info["lineas_omitidas"],
            "contenido":       info["cuerpo"],
        })

    if not bloques:
        return texto, adjuntos, avisos
    return texto + "\n\n" + "\n\n".join(bloques), adjuntos, avisos


def _patrones_gitignore(base: Path) -> List[str]:
    """Patrones del .gitignore de la raiz, sin negaciones. utf-8-sig: el del repo lleva BOM."""
    fichero = base / ".gitignore"
    if not fichero.is_file():
        return []
    try:
        crudo = fichero.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []          # ilegible: se completa sin filtro, no se cae el REPL
    patrones = []
    for linea in crudo.splitlines():
        s = linea.strip()
        if not s or s.startswith("#") or s.startswith("!"):
            continue
        s = s.strip("/")
        if s:
            patrones.append(s)
    return patrones


def _ignorado(rel: str, patrones: List[str]) -> bool:
    """fnmatch simple: patron con `/` contra la ruta entera, sin `/` contra cada parte."""
    for p in patrones:
        if "/" in p:
            if fnmatch(rel, p) or fnmatch(rel, p + "/*"):
                return True
        elif any(fnmatch(parte, p) for parte in rel.split("/")):
            return True
    return False


def completar_rutas(prefijo: str, raiz, limite: int = 20) -> List[str]:
    """
    Candidatos para el autocompletado de `@` en el REPL.

    `prefijo` es lo que lleva tecleado el usuario tras la arroba; puede traer
    directorio ("cognia/ag") o ser solo un fragmento de nombre ("loop"). Las
    barras invertidas de Windows valen igual que las normales, y las rutas
    vuelven siempre en formato posix relativo a `raiz`, con "/" al final si son
    directorios (asi el usuario sigue tecleando dentro).

    Orden: (1) los que EMPIEZAN por el fragmento antes que los que solo lo
    contienen, (2) los menos profundos antes que los hondos, (3) alfabetico.
    """
    base = Path(raiz)
    if not base.is_dir():
        return []

    pref = str(prefijo).replace("\\", "/")
    if pref.startswith("./"):
        pref = pref[2:]
    corte = pref.rfind("/") + 1
    dirpart, frag = pref[:corte].lower(), pref[corte:].lower()

    patrones = _patrones_gitignore(base)
    candidatos: List[str] = []

    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(base).as_posix()
        prefijo_dir = "" if rel_dir == "." else rel_dir + "/"

        # Podar aca (y no al filtrar) evita recorrer venv/ y node_modules enteros.
        dirnames[:] = sorted(
            d for d in dirnames
            if not _excluido(d) and not _ignorado(prefijo_dir + d, patrones))

        for d in dirnames:
            candidatos.append(prefijo_dir + d + "/")
        for f in sorted(filenames):
            rel = prefijo_dir + f
            if not _excluido(f) and not _ignorado(rel, patrones):
                candidatos.append(rel)

        if len(candidatos) >= _MAX_CANDIDATOS:
            break

    elegidos = []
    for rel in candidatos:
        bajo = rel.lower()
        if not bajo.startswith(dirpart) or bajo == dirpart:
            continue                      # fuera del directorio, o el propio directorio
        nombre = bajo.rstrip("/").rsplit("/", 1)[-1]
        if frag and frag not in nombre:
            continue
        elegidos.append((0 if nombre.startswith(frag) else 1,
                         bajo.rstrip("/").count("/"),
                         bajo,
                         rel))

    elegidos.sort()
    return [rel for _, _, _, rel in elegidos[:limite]]
