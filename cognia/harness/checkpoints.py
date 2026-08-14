# -*- coding: utf-8 -*-
"""
cognia/harness/checkpoints.py
=============================
DESHACER de ficheros: snapshots por SESION del agente.

POR QUE EXISTE (2026-08-12): el agente escribe SIN red. `escribir_archivo`
sobrescribe el fichero entero (`agent/tools.py`, `wpath.write_text` sin backup)
y `editar_archivo` aplica el REPLACE encima del original; si el modelo pequeno
"acorta" lo que no repite, el trabajo previo del dueno se pierde y NO hay forma
de volver: el unico rastro es `agent_state['files_touched']`, una lista de
nombres capada a 15 que no guarda contenido. Todos los harnesses punteros
tienen la red (Claude Code checkpoints + Esc-Esc, Cline/Roo checkpoints por
tarea, Aider auto-commits). Esta pieza la da sin depender de git: el workspace
del agente suele NO ser un repo.

Como se usa (el cableado lo hace el integrador; este modulo es autocontenido):

    from cognia.harness import checkpoints as ck

    # en tools.py, ANTES de escribir (nunca despues: el previo ya no existiria)
    previo = wpath.read_text(encoding="utf-8") if wpath.exists() else None
    ck.registrar(wpath, previo, "escribir_archivo", contenido_nuevo=content)
    wpath.write_text(content, encoding="utf-8")

    # en el CLI, para /deshacer y /deshacer <n>
    ck.listar()             -> entradas, la mas nueva primero
    ck.deshacer()           -> revierte la ultima; ck.deshacer(3) la #3
    ck.restaurar_hasta(3)   -> revierte en bloque de la ultima hasta la #3
    ck.diff_sesion()        -> que toco la sesion y cuantas lineas (+/-)

Almacen (override por COGNIA_CHECKPOINTS_DIR, leido a call-time para que los
tests aislen con tmp_path):

    ~/.cognia/checkpoints/<sesion>/indice.jsonl     una entrada JSON por linea
    ~/.cognia/checkpoints/<sesion>/blobs/NNNN.bak   contenido PREVIO de la #NNNN

El indice es append-only en su semantica (las entradas nunca se borran ni se
reordenan; deshacer solo marca `deshecho`) y se persiste con tmp + os.replace,
asi que un corte a mitad de escritura deja el indice anterior legible y jamas
un JSON truncado. Trade-off: cada registro reescribe el indice entero en vez de
appendear una linea — con decenas/cientos de entradas por sesion el coste es
irrelevante y a cambio la escritura es atomica de verdad en Windows.

LIMITES DECLARADOS (lo que esta pieza NO hace):
- Solo TEXTO utf-8. Un fichero binario o ilegible se registra como
  'no_versionado': deshacer lo AVISA y no lo toca (mejor no restaurar que
  restaurar basura). Idem los ficheros de mas de 2 MB (_MAX_BYTES_VERSIONADO).
- No versiona directorios, ni renombrados, ni borrados hechos por otras tools:
  cubre exactamente el punto donde el agente sobrescribe/crea un fichero.
- El respaldo y la restauracion son BYTE-EXACTOS en los saltos de linea: el
  blob se toma del disco con `newline=""` y se reescribe con `newline=""`. NO
  se restaura "como lo escribiria el agente" (`write_text` sin newline, que en
  Windows traduce cada \\n a \\r\\n): eso convertia un fichero LF del dueno —
  lo normal en un repo — en un fichero CRLF ENTERO al deshacer, o sea que
  /deshacer dejaba el fichero modificado en TODAS sus lineas. Las comparaciones
  de hash si normalizan (\\r\\n -> \\n) para que la traduccion que hace el
  propio agente al escribir no dispare el falso "el fichero CAMBIO".
- Un proceso por sesion. No hay lock entre procesos: dos Cognias escribiendo la
  MISMA sesion a la vez pueden pisarse el indice (por defecto no ocurre: la
  sesion lleva el PID).
- La sesion vive en memoria del proceso; al reiniciar el CLI empieza una nueva.
  Las anteriores siguen en disco y son accesibles pasando `sesion=` (ver
  `sesiones()`), pero /deshacer opera sobre la sesion en curso.
- Poda: se conservan las _MAX_SESIONES (20) mas recientes; el resto se borra al
  crear una sesion nueva.
- FALTA CABLEAR (el integrador): la llamada a `registrar()` en
  `agent/tools.py` (escribir_archivo / editar_archivo / apendar_archivo) y el
  comando /deshacer en `cognia/cli.py`. Sin eso el modulo corre pero nadie lo
  alimenta.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

# Por encima de esto NO se guarda copia (un backup de 50 MB por escritura
# llenaria el disco del dueno sin avisar). La entrada se registra igual, como
# 'no_versionado', para que el historial no mienta sobre lo que se toco.
_MAX_BYTES_VERSIONADO = 2 * 1024 * 1024

# Sesiones retenidas en disco (misma politica que estado_tarea.podar_viejas).
_MAX_SESIONES = 20

_NOMBRE_INDICE = "indice.jsonl"

# Id de la sesion en curso: se fija en el primer uso del proceso.
_SESION: str | None = None


# ── Ubicacion y sesiones ──────────────────────────────────────────────────────

def dir_checkpoints() -> Path:
    """Raiz del almacen; COGNIA_CHECKPOINTS_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_CHECKPOINTS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cognia" / "checkpoints"


def _nuevo_id() -> str:
    """'YYYYmmdd-HHMMSS-ffffff-<pid>': ordenable por nombre = ordenable en el
    tiempo, y el pid separa dos Cognias abiertos a la vez."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f") + f"-{os.getpid()}"


def sesion_actual() -> str:
    """Id de la sesion en curso, creandolo en el primer uso del proceso."""
    global _SESION
    if _SESION is None:
        _SESION = _nuevo_id()
    return _SESION


def nueva_sesion() -> str:
    """Abre una sesion nueva (el CLI puede llamarla al arrancar una tarea) y
    devuelve su id. Las entradas anteriores quedan en su propia sesion."""
    global _SESION
    nuevo = _nuevo_id()
    while nuevo == _SESION:      # dos llamadas dentro del mismo microsegundo
        nuevo = _nuevo_id()
    _SESION = nuevo
    return _SESION


def sesiones() -> list:
    """Ids de las sesiones con almacen en disco, la mas nueva primero."""
    try:
        dirs = [d.name for d in dir_checkpoints().iterdir() if d.is_dir()]
    except OSError:
        return []
    return sorted(dirs, reverse=True)


def _dir_sesion(sesion: str) -> Path:
    return dir_checkpoints() / sesion


def _dir_blobs(sesion: str) -> Path:
    return _dir_sesion(sesion) / "blobs"


# ── Indice (append-only, escritura atomica) ───────────────────────────────────

def _leer_indice(sesion: str) -> list:
    """Entradas de la sesion en orden de registro. Una linea corrupta se salta:
    perder una entrada es malo, perder el historial entero es peor.

    Se decode con errors='replace' A PROPOSITO: `read_text(encoding='utf-8')`
    lanza UnicodeDecodeError ante UN byte invalido y eso mataba el historial
    ENTERO (listar/deshacer/diff), justo lo contrario de lo que promete el
    parrafo de arriba. Con replace, el byte malo solo rompe el json.loads de SU
    linea y las demas entradas siguen deshaciendose.
    """
    ruta = _dir_sesion(sesion) / _NOMBRE_INDICE
    try:
        crudo = ruta.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    entradas = []
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            dato = json.loads(linea)
        except ValueError:
            continue
        if isinstance(dato, dict) and isinstance(dato.get("n"), int):
            entradas.append(dato)
    return entradas


def _guardar_indice(sesion: str, entradas: list) -> None:
    """tmp + os.replace: un corte deja el indice anterior intacto."""
    destino = _dir_sesion(sesion) / _NOMBRE_INDICE
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".jsonl.tmp")
    texto = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entradas)
    tmp.write_text(texto, encoding="utf-8", newline="")
    os.replace(tmp, destino)


def _siguiente_n(sesion: str, entradas: list) -> int:
    """Numero libre para la proxima entrada.

    No basta `entradas[-1]['n'] + 1`: `_leer_indice` SALTA las lineas corruptas,
    asi que el ultimo n del indice legible puede ser menor que el ultimo que se
    uso de verdad, y entonces el blob NNNN.bak de una entrada anterior se
    sobrescribe en silencio (deshacer restauraria contenido de OTRA escritura).
    Por eso el maximo sale del indice Y de los blobs que hay en disco.
    """
    n = 0
    for e in entradas:
        try:
            n = max(n, int(e.get("n", 0)))
        except (TypeError, ValueError):
            continue
    try:
        for blob in _dir_blobs(sesion).iterdir():
            cifras = blob.name.split("-")[0].split(".")[0]
            if cifras.isdigit():
                n = max(n, int(cifras))
    except OSError:
        pass
    return n + 1


def _norm(texto: str) -> str:
    """Saltos de linea normalizados a \\n. SOLO para comparar/medir, nunca para
    guardar ni para restaurar: el agente escribe con `write_text` (que en
    Windows traduce \\n -> \\r\\n), asi que comparar en crudo haria que TODO
    fichero pareciera "cambiado por fuera" al deshacer."""
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def _sha(texto: str) -> str:
    """Hash del texto NORMALIZADO (ver `_norm`): el mismo contenido escrito con
    LF o con CRLF da el mismo hash."""
    return hashlib.sha256(_norm(texto).encode("utf-8", errors="replace")).hexdigest()


def _escribir_exacto(ruta: Path, contenido: str) -> None:
    """newline='' : guarda el string EXACTO, sin traduccion de saltos. Sirve
    para los blobs y tambien para RESTAURAR el fichero del workspace."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as fh:
        fh.write(contenido)


def _leer_blob(ruta: Path) -> str | None:
    try:
        with open(ruta, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _leer_exacto(ruta: Path) -> str | None:
    """Lee un fichero del workspace TAL CUAL esta en disco (utf-8, newline=''),
    sin traducir los saltos de linea: es lo que hay que respaldar para poder
    devolverlo identico. None si no es texto utf-8 o no se puede leer."""
    try:
        with open(ruta, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _degradar(donde: str, exc: Exception, accion: str) -> None:
    """La degradacion SILENCIOSA es el modo de fallo historico del repo: si el
    almacen falla, el turno del usuario sigue pero el bus se entera."""
    try:
        from cognia.ux import events as _ev
        _ev.emitir(_ev.Degradado(donde=donde,
                                 motivo=f"{type(exc).__name__}: {exc}",
                                 accion_sugerida=accion))
    except Exception:
        pass


# ── Registro ──────────────────────────────────────────────────────────────────

def registrar(ruta, contenido_previo: str | None, motivo: str = "",
              contenido_nuevo: str | None = None,
              sesion: str | None = None) -> dict:
    """Guarda el estado PREVIO de `ruta` antes de que el agente la escriba.

    `contenido_previo=None` significa "el fichero no existia". Quien manda es
    el DISCO, no el argumento: si el fichero existe y llega None (o el ""
    que usa `tools.py` como 'no existia': `read_text() if exists() else ""`),
    se lee el contenido real. Creerle al argumento haria que deshacer BORRARA
    (None) o VACIARA ("") un fichero que si estaba, que es exactamente el
    desastre que esta pieza viene a evitar. Un fichero de verdad vacio da ""
    al releerlo, asi que la defensa no cuesta nada. Un `contenido_previo` no
    vacio SI se cree tal cual (es el unico modo de registrar lo que el llamador
    ya tenia en memoria sin releer el disco).

    `contenido_nuevo` es lo que el agente esta a punto de escribir: se guarda
    solo su hash, para que deshacer pueda AVISAR si despues alguien mas toco el
    fichero. Es opcional; sin el, el aviso no se puede emitir.

    Devuelve la entrada registrada, o {} si el almacen fallo (nunca lanza: un
    disco lleno no debe abortar la escritura del agente).
    """
    ses = sesion or sesion_actual()
    try:
        destino = Path(ruta).expanduser()
        try:
            destino = destino.resolve()
        except OSError:
            destino = destino.absolute()

        primera_vez = not _dir_sesion(ses).exists()

        existia = destino.exists()
        estado = "guardado"
        tam_previo = 0
        if not existia:
            # El fichero no esta: cualquier "previo" que manden es ruido.
            contenido_previo = None
        else:
            # Chequear el TAMAÑO antes de leer: un fichero que no se va a
            # versionar igual no debe cargarse entero en RAM (leer 500 MB para
            # despues descartarlos es exactamente lo que _MAX_BYTES_VERSIONADO
            # viene a evitar), y asi la entrada lleva su tamaño REAL en vez del
            # 0 que quedaba cuando la lectura fallaba.
            try:
                tam_disco = destino.stat().st_size
            except OSError:
                tam_disco = 0
            if tam_disco > _MAX_BYTES_VERSIONADO:
                estado = "no_versionado"
                tam_previo = tam_disco
                contenido_previo = None
            else:
                en_disco = _leer_exacto(destino)
                if en_disco is None:
                    # El fichero EXISTE pero no es utf-8 legible (latin-1,
                    # binario, sin permiso). Manda el disco SIEMPRE, tambien
                    # cuando el llamador mando texto: si leyo con
                    # errors='replace' lo que trae son U+FFFD, y guardarlos como
                    # respaldo 'guardado' hacia que /deshacer los escribiera
                    # ENCIMA del original y contestara "restaurado" — o sea,
                    # la red de seguridad destruyendo el fichero que venia a
                    # salvar. 'no_versionado' hace que /deshacer AVISE.
                    estado = "no_versionado"
                    tam_previo = tam_disco
                    contenido_previo = None
                elif not contenido_previo:
                    # None o "": el llamador dice "no habia nada" pero el
                    # fichero SI esta. Manda el disco (ver docstring).
                    contenido_previo = en_disco
                elif _norm(en_disco) == _norm(contenido_previo):
                    # El llamador ya leyo el fichero (con read_text, o sea con
                    # los saltos normalizados). Es el MISMO contenido, asi que
                    # se respalda la copia del DISCO: conserva los saltos de
                    # linea originales y deshacer devuelve el fichero identico.
                    contenido_previo = en_disco

        hash_previo = ""
        if contenido_previo is not None and estado == "guardado":
            tam_previo = len(_norm(contenido_previo).encode("utf-8", errors="replace"))
            if tam_previo > _MAX_BYTES_VERSIONADO:
                estado = "no_versionado"
            else:
                hash_previo = _sha(contenido_previo)

        entradas = _leer_indice(ses)
        n = _siguiente_n(ses, entradas)

        blob = ""
        if estado == "guardado" and contenido_previo is not None:
            blob = f"{n:04d}.bak"
            _escribir_exacto(_dir_blobs(ses) / blob, contenido_previo)

        entrada = {
            "n": n,
            "ruta": str(destino),
            "motivo": motivo or "",
            "cuando": datetime.now().isoformat(timespec="seconds"),
            "existia_antes": existia,
            "tam_previo": tam_previo,
            "estado": estado,
            "blob": blob,
            "hash_previo": hash_previo,
            "hash_escrito": (_sha(contenido_nuevo)
                             if contenido_nuevo is not None else ""),
            "deshecho": False,
            "cuando_deshecho": "",
        }
        entradas.append(entrada)
        _guardar_indice(ses, entradas)
        if primera_vez:
            podar_sesiones(proteger=ses)
        return entrada
    except Exception as exc:
        # A proposito NO es `except OSError`: el contrato es "nunca lanza" y un
        # motivo no serializable o una ruta invalida (TypeError/ValueError) le
        # abortaba la escritura al agente. Nada de esto es silencioso: va al bus.
        _degradar("harness.checkpoints.registrar", exc,
                  "revisar permisos/espacio de ~/.cognia/checkpoints")
        return {}


def listar(sesion: str | None = None, incluir_deshechos: bool = True) -> list:
    """Entradas de la sesion, la mas NUEVA primero (que es como se deshacen)."""
    entradas = _leer_indice(sesion or sesion_actual())
    if not incluir_deshechos:
        entradas = [e for e in entradas if not e.get("deshecho")]
    return [{
        "n": e["n"],
        "ruta": e.get("ruta", ""),
        "motivo": e.get("motivo", ""),
        "cuando": e.get("cuando", ""),
        "tam_previo": e.get("tam_previo", 0),
        "existia_antes": bool(e.get("existia_antes")),
        "estado": e.get("estado", "guardado"),
        "deshecho": bool(e.get("deshecho")),
    } for e in reversed(entradas)]


# ── Deshacer ──────────────────────────────────────────────────────────────────

def _revertir(sesion: str, e: dict) -> tuple:
    """Revierte UNA entrada. Devuelve (consumida, resumen). No toca el indice.

    `consumida=False` significa que la reversion FALLO (respaldo ausente,
    fichero bloqueado, permisos) y que la entrada debe seguir pendiente para
    poder reintentarla: marcarla igual la quemaba y el segundo /deshacer
    contestaba "ya estaba deshecho" con el fichero SIN restaurar.
    Una entrada 'no_versionado' si se consume: no hay nada que reintentar.
    """
    destino = Path(e.get("ruta", ""))
    n = e["n"]
    if e.get("estado") == "no_versionado":
        return True, (f"#{n} {destino}: NO restaurado -- el contenido previo no "
                      f"se versiono ({e.get('tam_previo', 0)} bytes; limite "
                      f"{_MAX_BYTES_VERSIONADO} o fichero no textual)")

    existe_ahora = destino.exists()
    actual = _leer_exacto(destino) if existe_ahora else None

    avisos = ""
    if existe_ahora and actual is None:
        avisos = (" | AVISO: el fichero actual no es texto utf-8 legible; se "
                  "revirtio igual y NO se pudo resguardar lo descartado")
    elif actual is not None and e.get("hash_escrito") and \
            _sha(actual) != e["hash_escrito"]:
        resguardo = _dir_blobs(sesion) / f"{n:04d}-descartado.bak"
        try:
            _escribir_exacto(resguardo, actual)
            avisos = (f" | AVISO: el fichero CAMBIO despues de la escritura del "
                      f"agente; lo que se descarta quedo en {resguardo}")
        except OSError as exc:
            _degradar("harness.checkpoints.deshacer", exc,
                      "revisar permisos de ~/.cognia/checkpoints")
            avisos = (" | AVISO: el fichero CAMBIO despues de la escritura del "
                      "agente y no se pudo resguardar lo descartado")

    if e.get("existia_antes"):
        previo = _leer_blob(_dir_blobs(sesion) / e.get("blob", ""))
        if previo is None:
            return False, (f"#{n} {destino}: ERROR -- falta el respaldo "
                           f"{e.get('blob', '(sin blob)')}, no se restauro nada")
        try:
            # newline='': se devuelve el fichero EXACTO, sin CRLF-izar un
            # fichero que estaba en LF (ver LIMITES DECLARADOS).
            _escribir_exacto(destino, previo)
        except OSError as exc:
            return False, f"#{n} {destino}: ERROR al restaurar ({exc})"
        return True, (f"#{n} {destino}: restaurado al estado previo "
                      f"({len(previo)} chars)" + avisos)

    if existe_ahora:
        try:
            destino.unlink()
        except OSError as exc:
            return False, f"#{n} {destino}: ERROR al borrar ({exc})"
        return True, (f"#{n} {destino}: BORRADO (no existia antes de la sesion)"
                      + avisos)
    return True, f"#{n} {destino}: ya no existia, nada que borrar"


def deshacer(n: int | None = None, sesion: str | None = None) -> str:
    """Revierte la ultima escritura registrada (o la #n) y devuelve un resumen.

    Idempotente: deshacer una entrada ya deshecha no toca el disco, lo dice y
    ya. Una entrada 'no_versionado' se marca como deshecha igual (avisando que
    no se restauro nada) para que el historial avance en vez de trabarse; una
    que FALLA al restaurar NO se marca, para poder reintentarla.
    """
    ses = sesion or sesion_actual()
    entradas = _leer_indice(ses)
    if not entradas:
        return f"no hay checkpoints en la sesion {ses}: nada que deshacer"

    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return f"numero de checkpoint invalido: {n!r}"

    if n is None:
        pendientes = [e for e in entradas if not e.get("deshecho")]
        if not pendientes:
            return (f"las {len(entradas)} entradas de la sesion {ses} ya estan "
                    f"deshechas: nada que deshacer")
        objetivo = pendientes[-1]
    else:
        objetivo = next((e for e in entradas if e["n"] == int(n)), None)
        if objetivo is None:
            return f"no existe el checkpoint #{n} en la sesion {ses}"
        if objetivo.get("deshecho"):
            return (f"#{objetivo['n']} ya estaba deshecho ({objetivo.get('ruta')}): "
                    f"no se toco nada")

    consumida, resumen = _revertir(ses, objetivo)
    if not consumida:
        return ("deshacer " + resumen +
                " | la entrada sigue PENDIENTE: se puede reintentar")
    objetivo["deshecho"] = True
    objetivo["cuando_deshecho"] = datetime.now().isoformat(timespec="seconds")
    try:
        _guardar_indice(ses, entradas)
    except OSError as exc:
        _degradar("harness.checkpoints.deshacer", exc,
                  "revisar permisos de ~/.cognia/checkpoints")
        resumen += " | AVISO: no se pudo persistir el indice (se repetiria)"
    return "deshacer " + resumen


def restaurar_hasta(n: int, sesion: str | None = None) -> str:
    """Deshace EN BLOQUE de la ultima entrada hasta la #n inclusive.

    En orden inverso (lo ultimo primero): un fichero escrito varias veces en la
    sesion queda en el estado que tenia ANTES de la entrada #n, que es lo que
    espera quien pide "volve a como estaba".
    """
    ses = sesion or sesion_actual()
    entradas = _leer_indice(ses)
    if not entradas:
        return f"no hay checkpoints en la sesion {ses}: nada que restaurar"
    try:
        tope = int(n)
    except (TypeError, ValueError):
        return f"numero de checkpoint invalido: {n!r}"

    aplicables = [e for e in entradas
                  if e["n"] >= tope and not e.get("deshecho")]
    if not aplicables:
        return (f"nada que restaurar hasta #{tope} en la sesion {ses} "
                f"(fuera de rango o ya deshecho)")

    lineas = []
    revertidas = fallidas = 0
    for e in sorted(aplicables, key=lambda x: x["n"], reverse=True):
        consumida, linea = _revertir(ses, e)
        lineas.append(linea)
        if not consumida:
            # Igual que en deshacer(): lo que fallo queda pendiente, no quemado.
            fallidas += 1
            continue
        revertidas += 1
        e["deshecho"] = True
        e["cuando_deshecho"] = datetime.now().isoformat(timespec="seconds")
    try:
        _guardar_indice(ses, entradas)
    except OSError as exc:
        _degradar("harness.checkpoints.restaurar_hasta", exc,
                  "revisar permisos de ~/.cognia/checkpoints")
        lineas.append("AVISO: no se pudo persistir el indice (se repetiria)")
    cabeza = f"restaurar_hasta #{tope}: {revertidas} entrada(s) revertida(s)"
    if fallidas:
        cabeza += f", {fallidas} FALLIDA(s) (siguen pendientes)"
    return "\n".join([cabeza] + ["  " + l for l in lineas])


# ── Que toco la sesion ────────────────────────────────────────────────────────

def _contar_lineas(antes: str, ahora: str) -> tuple:
    """(+lineas, -lineas) entre dos textos, con difflib. n=0: solo los cambios."""
    mas = menos = 0
    for linea in difflib.unified_diff(antes.splitlines(), ahora.splitlines(),
                                      lineterm="", n=0):
        if linea.startswith("+") and not linea.startswith("+++"):
            mas += 1
        elif linea.startswith("-") and not linea.startswith("---"):
            menos += 1
    return mas, menos


def diff_sesion(sesion: str | None = None) -> dict:
    """Que ficheros toco la sesion y cuantas lineas (+/-) respecto al estado
    que tenian ANTES de la primera escritura registrada.

    Devuelve {'sesion', 'ficheros': [{ruta, mas, menos, escrituras,
    existia_antes, nota}], 'texto'} — 'texto' es el render listo para el CLI.
    """
    ses = sesion or sesion_actual()
    entradas = _leer_indice(ses)
    primeras: dict = {}
    escrituras: dict = {}
    for e in entradas:
        ruta = e.get("ruta", "")
        primeras.setdefault(ruta, e)
        escrituras[ruta] = escrituras.get(ruta, 0) + 1

    ficheros = []
    for ruta, prim in primeras.items():
        destino = Path(ruta)
        nota = ""
        if prim.get("estado") == "no_versionado":
            ficheros.append({"ruta": ruta, "mas": 0, "menos": 0,
                             "escrituras": escrituras[ruta],
                             "existia_antes": bool(prim.get("existia_antes")),
                             "nota": "no versionado: sin base para comparar"})
            continue
        ahora = ""
        if destino.exists():
            leido = _leer_exacto(destino)
            if leido is None:
                nota = "ilegible ahora"
            else:
                ahora = leido
        else:
            nota = "no existe ahora"
        antes = ""
        if prim.get("existia_antes"):
            base = _leer_blob(_dir_blobs(ses) / prim.get("blob", ""))
            if base is None:
                nota = "falta el respaldo del estado previo"
            else:
                antes = base
        else:
            nota = nota or "creado en esta sesion"
        mas, menos = _contar_lineas(antes, ahora)
        ficheros.append({"ruta": ruta, "mas": mas, "menos": menos,
                         "escrituras": escrituras[ruta],
                         "existia_antes": bool(prim.get("existia_antes")),
                         "nota": nota})

    ficheros.sort(key=lambda f: (f["mas"] + f["menos"]), reverse=True)
    if not ficheros:
        texto = f"sesion {ses}: ningun fichero tocado"
    else:
        lineas = [f"sesion {ses}: {len(ficheros)} fichero(s) tocado(s)"]
        for f in ficheros:
            lineas.append(f"  +{f['mas']:<5} -{f['menos']:<5} {f['ruta']}"
                          + (f"  ({f['nota']})" if f["nota"] else ""))
        texto = "\n".join(lineas)
    return {"sesion": ses, "ficheros": ficheros, "texto": texto}


# ── Poda ──────────────────────────────────────────────────────────────────────

def podar_sesiones(max_sesiones: int = _MAX_SESIONES,
                   proteger: str | None = None) -> list:
    """Retiene las `max_sesiones` mas recientes y borra el resto; devuelve los
    ids borrados. Nunca borra la sesion en curso (ni la de `proteger`, que es
    la sesion en la que se esta escribiendo cuando `registrar` recibe un
    `sesion=` viejo) ni lanza."""
    borradas = []
    intocables = {sesion_actual(), proteger}
    for ses in sesiones()[max_sesiones:]:
        if ses in intocables:
            continue
        try:
            shutil.rmtree(_dir_sesion(ses))
            borradas.append(ses)
        except OSError as exc:
            _degradar("harness.checkpoints.podar_sesiones", exc,
                      "revisar permisos de ~/.cognia/checkpoints")
    return borradas
