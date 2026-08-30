# -*- coding: utf-8 -*-
"""
cognia/agent/flujoteca.py
=========================
La BIBLIOTECA de flujos: cada flujo es una entidad con nombre, historial de
versiones y restauracion.

POR QUE EXISTE (2026-08-28)
---------------------------
Cognia ya sabia representar un flujo como DAG de nodos (`agent/flows.py`:
{id, tool, args, wires}, validacion de ciclos, orden topologico, ejecucion
por niveles) y ya sabia dibujarlo (`agent/flow_view.py`, lienzo estilo n8n).
Lo que NO tenia era donde GUARDARLO: `flows.py` persiste en UN solo fichero
`.flujo.json` del workspace, que se pisa cada vez. O sea: se podia crear un
flujo, pero no tener dos, ni volver al de ayer, ni saber que cambio.

Este modulo pone las tres cosas que faltaban: biblioteca (muchos flujos con
nombre), versionado (cada guardado es una version, con nota y fecha) y
restauracion. No toca el formato de nodos: guarda EXACTAMENTE el dict que
`flows.validar()` acepta, para que la ejecucion y el lienzo sigan
funcionando sin cambiar una linea.

LA DECISION IMPORTANTE: RESTAURAR NO BORRA
------------------------------------------
`restaurar(nombre, 2)` no tira las versiones 3 y 4: crea la version 5 con el
contenido de la 2. El historial es append-only.

No es purismo. Es que la restauracion la va a pedir muchas veces el MODELO,
conversando ("vuelve a como estaba antes"), y un modelo que puede truncar el
historial puede destruir trabajo del dueno con una frase ambigua. Con
append-only, la peor consecuencia de una restauracion equivocada es otra
restauracion. Borrar de verdad existe, pero pasa por `POLITICA_BORRADO`, que
el dueno controla y que por defecto es "nunca".

DISPOSICION EN DISCO
--------------------
    ~/.cognia/flujoteca/<slug>/
        meta.json      nombre, descripcion, fechas, version actual, historial
        v1.json        el flujo (formato de flows.py, tal cual)
        v2.json
        ...
Un directorio por flujo y un fichero por version: se puede mirar, copiar y
versionar con git sin herramientas. Y una version corrupta no se lleva por
delante a las demas, que es lo que pasa con un unico JSON grande.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

__all__ = ["dir_base", "slugificar", "guardar", "listar", "cargar",
           "cargar_con_aviso",
           "versiones", "restaurar", "comparar", "borrar_version", "borrar",
           "describir", "existe", "guardar_ui", "leer_ui",
           "POLITICAS_BORRADO", "FlujotecaError"]


class FlujotecaError(ValueError):
    pass


# Que puede hacer la IA con las versiones. Lo elige el dueno (clave de config
# 'flujoteca_borrado'); el default es el conservador.
POLITICAS_BORRADO = ("nunca", "preguntar", "permitido")

_VERSION_FORMATO = 1


def dir_base() -> Path:
    """Raiz de la biblioteca. COGNIA_FLUJOTECA_DIR la mueve (tests, perfiles
    aislados), igual que COGNIA_WORKFLOWS_DIR mueve las corridas."""
    crudo = os.environ.get("COGNIA_FLUJOTECA_DIR")
    base = Path(crudo) if crudo else (Path.home() / ".cognia" / "flujoteca")
    return base


def slugificar(nombre: str) -> str:
    """Nombre de directorio seguro a partir del nombre del flujo.

    Ojo con lo que NO hace: no garantiza unicidad. Dos flujos que
    slugifiquen igual son EL MISMO flujo con dos nombres, y guardar el
    segundo crea una version del primero. Es deliberado: el dueno que
    escribe "Investigacion IA" y luego "investigacion ia" quiere el mismo
    flujo, no dos que se le dupliquen sin avisar.
    """
    s = (nombre or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or "flujo"


def _dir_flujo(nombre: str) -> Path:
    return dir_base() / slugificar(nombre)


def _ruta_meta(nombre: str) -> Path:
    return _dir_flujo(nombre) / "meta.json"


def _ruta_version(nombre: str, v: int) -> Path:
    return _dir_flujo(nombre) / f"v{int(v)}.json"


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _escribir_atomico(ruta: Path, datos: dict) -> None:
    """tmp + os.replace, como guardar_flujo de flujos/generalizador.py.

    Sin esto, un corte de luz a mitad de escritura deja un JSON truncado y el
    flujo se pierde entero. Con replace atomico, o esta el viejo o esta el
    nuevo."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, ruta)


def _leer_json(ruta: Path):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None


def existe(nombre: str) -> bool:
    return _ruta_meta(nombre).exists()


# ---------------------------------------------------------------------------
# Guardar y leer
# ---------------------------------------------------------------------------

def guardar(flujo: dict, *, nombre: str = "", nota: str = "",
            descripcion: str = "", validar: bool = True,
            tool_existe=None) -> dict:
    """Guarda `flujo` como una version NUEVA. Devuelve la meta actualizada.

    `nombre` manda sobre flujo['nombre']; si no hay ninguno, es un error (un
    flujo sin nombre no se puede volver a encontrar, que es el punto entero
    de tener biblioteca).

    `tool_existe` es OPCIONAL a proposito. Cuando se pasa (el editor visual
    pasa `lambda n: n in TOOLS`), un flujo con una tool inventada se rechaza
    ANTES de escribir nada, que es donde el error se entiende. Cuando no se
    pasa, el comportamiento es el de siempre: se valida la forma del grafo y
    no el registro de tools. El default tiene que seguir siendo None porque
    hay flujos legitimos que se guardan con tools que este proceso no tiene
    cargadas (una familia opt-in apagada, un flujo tecleado a mano, los
    tests) y convertir eso en un error dejaria al dueno sin poder guardar lo
    que ya tenia.
    """
    if not isinstance(flujo, dict):
        raise FlujotecaError("el flujo tiene que ser un dict")
    nombre_final = (nombre or flujo.get("nombre") or "").strip()
    if not nombre_final:
        raise FlujotecaError("hace falta un nombre para guardar el flujo")
    # EL NODO DE ENTRADA SE ASEGURA EN EL BORDE DE GUARDADO, y solo aqui.
    # Cubre de un golpe /flujoteca nuevo, /flujoteca editar, /sesion-a-workflow,
    # el editor visual, duplicar() y restaurar(); y deja la LECTURA permisiva,
    # que es lo que hace que los flujos ya guardados sigan abriendose.
    # (Medido: exigirlo en `flows.validar` rompe 126 de 293 tests y vuelve
    # inabribles los flujos del dueno; aqui rompe 18, todos de n_nodos/diff.)
    # Va ANTES de validar para que el nodo nuevo pase por la misma validacion
    # que el resto: un asegurar_prompt que produjera un grafo invalido tiene
    # que salir por el mismo error, no colarse por detras.
    from cognia.agent import flows as _flows
    flujo = _flows.asegurar_prompt(flujo)
    if validar:
        # Se valida ANTES de escribir. Guardar un flujo con un ciclo o un
        # wire colgado y descubrirlo al ejecutarlo convierte un error de
        # edicion en un error de ejecucion, que se diagnostica mucho peor.
        # levanta FlowError con el motivo exacto
        _flows.validar(flujo, tool_existe=tool_existe)

    flujo = dict(flujo)
    flujo["nombre"] = nombre_final
    meta = _leer_json(_ruta_meta(nombre_final)) or {}
    if not meta:
        meta = {"version_formato": _VERSION_FORMATO, "nombre": nombre_final,
                "slug": slugificar(nombre_final),
                "descripcion": descripcion or flujo.get("descripcion", ""),
                "creado": _ahora(), "version_actual": 0, "versiones": []}
    if descripcion:
        meta["descripcion"] = descripcion

    nueva = int(meta.get("version_actual") or 0) + 1
    _escribir_atomico(_ruta_version(nombre_final, nueva), flujo)
    meta["version_actual"] = nueva
    meta["modificado"] = _ahora()
    meta["versiones"].append({
        "v": nueva, "ts": _ahora(), "nota": (nota or "")[:200],
        "n_nodos": len(flujo.get("nodos") or []),
    })
    _escribir_atomico(_ruta_meta(nombre_final), meta)
    return meta


def listar() -> list:
    """[{nombre, slug, descripcion, version_actual, n_versiones, n_nodos,
    creado, modificado, ruta}] ordenado por modificacion, el mas nuevo
    primero. Nunca lanza: una biblioteca inexistente son cero flujos."""
    out = []
    base = dir_base()
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        meta = _leer_json(d / "meta.json")
        if not meta:
            continue
        ultima = (meta.get("versiones") or [{}])[-1]
        out.append({
            "nombre": meta.get("nombre", d.name),
            "slug": meta.get("slug", d.name),
            "descripcion": meta.get("descripcion", ""),
            "version_actual": meta.get("version_actual", 0),
            "n_versiones": len(meta.get("versiones") or []),
            "n_nodos": ultima.get("n_nodos", 0),
            "creado": meta.get("creado", ""),
            "modificado": meta.get("modificado", ""),
            "ruta": str(d),
        })
    out.sort(key=lambda f: f.get("modificado") or "", reverse=True)
    return out


def cargar(nombre: str, version=None) -> dict:
    r"""El flujo en esa version (o en la actual). Levanta si no existe.

    CONTRATO PENDIENTE (PLAN2, 5.1 "El separador de args") — F1/agente B:
      `cargar` va a NORMALIZAR LOS ARGS al leer, llamando a
      `flows.normalizar_args(flujo) -> (flujo, [ids_arreglados])`. Para los
      nodos legacy cuya tool tiene >=2 params posicionales y cuyo `args` usa
      "\n" en vez de " | ", el separador se arregla EN MEMORIA.
      Explicitamente NO se reescribe la version en disco: las versiones del
      dueno son historial, no cache; el arreglo se REPORTA al llamador
      ("arregle el separador de N nodos; guardalo con /flujoteca editar para
      dejarlo fijo").

    `cargar` devuelve SOLO el flujo (firma intacta: la usan el editor, el CLI,
    comparar(), restaurar() y duplicar()). Quien quiera el aviso llama a
    `cargar_con_aviso`, que devuelve `(flujo, aviso)`.
    """
    return cargar_con_aviso(nombre, version)[0]


def cargar_con_aviso(nombre: str, version=None) -> tuple:
    r"""`(flujo, aviso)`. Igual que `cargar`, pero devuelve ademas el texto
    que hay que ensenarle al dueno si al leer se arreglo el separador de
    argumentos de algun nodo legacy ("" si no se toco nada).

    La normalizacion es EN MEMORIA: la version en disco no se reescribe. Las
    versiones del dueno son historial, no cache -- si se reescribieran, un
    `comparar(v3, v4)` empezaria a mentir sobre lo que el cambio."""
    meta = _leer_json(_ruta_meta(nombre))
    if not meta:
        raise FlujotecaError(f"no hay ningun flujo llamado '{nombre}'")
    v = int(version) if version else int(meta.get("version_actual") or 0)
    flujo = _leer_json(_ruta_version(nombre, v))
    if flujo is None:
        # Se filtra por lo que HAY EN DISCO, no por lo que cuenta el
        # historial: el historial conserva a proposito las entradas de las
        # versiones borradas (marcadas 'borrada'), asi que listarlas aqui
        # producia el mensaje contradictorio "no tiene version 2 (hay: v1,
        # v2, v3)" -- y quien lo leia volvia a pedir la v2. La comprobacion
        # en disco cubre ademas el borrado hecho por fuera del modulo.
        disponibles = [e["v"] for e in (meta.get("versiones") or [])
                       if _ruta_version(nombre, e.get("v", 0)).exists()]
        raise FlujotecaError(
            f"'{nombre}' no tiene version {v} (hay: "
            f"{', '.join('v' + str(x) for x in disponibles) or 'ninguna'})")
    from cognia.agent import flows as _flows
    flujo, arreglados = _flows.normalizar_args(flujo)
    return flujo, _flows.aviso_normalizacion(arreglados)


def versiones(nombre: str) -> list:
    """[{v, ts, nota, n_nodos, actual}] de la mas nueva a la mas vieja."""
    meta = _leer_json(_ruta_meta(nombre))
    if not meta:
        return []
    actual = int(meta.get("version_actual") or 0)
    out = []
    for e in reversed(meta.get("versiones") or []):
        fila = dict(e)
        fila["actual"] = (int(e.get("v", 0)) == actual)
        fila["existe"] = _ruta_version(nombre, e.get("v", 0)).exists()
        out.append(fila)
    return out


def descripcion(nombre: str) -> str:
    meta = _leer_json(_ruta_meta(nombre)) or {}
    return str(meta.get("descripcion") or "")


# ---------------------------------------------------------------------------
# El estado del EDITOR (posiciones): en la meta, no en el flujo
# ---------------------------------------------------------------------------
# Donde viven las posiciones de los nodos es una decision, no un detalle:
#
#   1. `flujo_ia.sanear_flujo` reconstruye cada nodo con una whitelist cerrada
#      ({id, tool, args, wires} + 4 opcionales). Una x/y metida en el nodo se
#      perderia en la PRIMERA edicion conversacional, en silencio.
#   2. `comparar()` compara una tupla fija de 7 campos. Si las posiciones
#      fueran parte del flujo, cada arrastre del raton contaria como un
#      cambio y el historial se llenaria de versiones que no cambian nada.
#
# Por eso el estado visual vive en meta["ui"] y NO crea version, NO toca
# 'modificado' y NO entra en el diff. Mover un nodo no es editar el flujo.

def _sanear_ui(ui: dict) -> dict:
    """El ui que llega del navegador, con las posiciones ya en enteros.

    Lo que entra por HTTP no es de fiar ni siquiera en localhost: una x de
    tipo lista o un pos que no es un dict romperia la vista al leerla, mucho
    despues de escribirla."""
    if not isinstance(ui, dict):
        raise FlujotecaError("el 'ui' tiene que ser un dict")
    limpio = {}
    for clave, valor in ui.items():
        if clave != "pos":
            limpio[str(clave)] = valor
            continue
        pos = {}
        for nid, xy in (valor or {}).items():
            if not isinstance(xy, dict):
                continue
            try:
                pos[str(nid)] = {"x": int(round(float(xy.get("x")))),
                                 "y": int(round(float(xy.get("y"))))}
            except (TypeError, ValueError):
                continue
        limpio["pos"] = pos
    try:
        json.dumps(limpio)
    except (TypeError, ValueError) as exc:
        raise FlujotecaError(f"el 'ui' no es serializable a JSON: {exc}")
    return limpio


def guardar_ui(nombre: str, ui: dict) -> dict:
    """Escribe el estado visual del flujo en meta['ui']. Devuelve el ui.

    Fusiona por CLAVE DE PRIMER NIVEL: `guardar_ui(n, {"pos": {...}})` no
    borra un `meta["ui"]["zoom"]` que hubiera guardado otra pantalla. Dentro
    de "pos" no fusiona: el editor manda siempre el mapa entero, y fusionar
    ahi dejaria para siempre las posiciones de nodos ya borrados.

    Misma escritura atomica que el resto del modulo (tmp + os.replace): la
    meta es el fichero que sabe cuantas versiones hay, y dejarla truncada
    por un corte a mitad de un arrastre perderia el flujo entero.
    """
    ruta = _ruta_meta(nombre)
    meta = _leer_json(ruta)
    if not meta:
        raise FlujotecaError(f"no hay ningun flujo llamado '{nombre}'")
    nuevo = _sanear_ui(ui)
    previo = meta.get("ui")
    fusion = dict(previo) if isinstance(previo, dict) else {}
    fusion.update(nuevo)
    meta["ui"] = fusion
    _escribir_atomico(ruta, meta)
    return fusion


def leer_ui(nombre: str) -> dict:
    """El estado visual guardado, o {} si no hay. NUNCA lanza.

    Un flujo sin posiciones es el caso normal (todos los de antes del editor)
    y tiene respuesta buena: el layout topologico. Lanzar aqui obligaria a
    cada llamador a envolverlo en un try para nada."""
    meta = _leer_json(_ruta_meta(nombre)) or {}
    ui = meta.get("ui")
    return dict(ui) if isinstance(ui, dict) else {}


# ---------------------------------------------------------------------------
# Restaurar y comparar
# ---------------------------------------------------------------------------

def restaurar(nombre: str, version: int, *, nota: str = "") -> dict:
    """Vuelve a `version` creando una version NUEVA con ese contenido.

    No trunca el historial (ver la cabecera del modulo). Devuelve la meta.
    """
    flujo = cargar(nombre, version)
    texto = nota or f"restaurada la v{int(version)}"
    return guardar(flujo, nombre=nombre, nota=texto)


def comparar(nombre: str, v1: int, v2: int) -> dict:
    """Diferencias entre dos versiones, POR NODO.

    Un diff de texto sobre el JSON seria inutil aqui: reordenar la lista de
    nodos no cambia el flujo (el orden lo da el grafo, no el fichero) y sin
    embargo saldria como que cambio todo. Comparando por id, lo que sale es
    lo que de verdad cambio.
    """
    a, b = cargar(nombre, v1), cargar(nombre, v2)
    na = {n.get("id"): n for n in (a.get("nodos") or [])}
    nb = {n.get("id"): n for n in (b.get("nodos") or [])}
    campos = ("tool", "args", "wires", "reintentos", "timeout_s",
              "saltar_si", "modelo")
    cambios = []
    for nid in sorted(set(na) & set(nb)):
        diffs = []
        for c in campos:
            va, vb = na[nid].get(c), nb[nid].get(c)
            if va != vb:
                diffs.append({"campo": c, "antes": va, "despues": vb})
        if diffs:
            cambios.append({"id": nid, "campos": diffs})
    return {
        "nombre": nombre, "v1": int(v1), "v2": int(v2),
        "anadidos": [nb[i] for i in sorted(set(nb) - set(na))],
        "quitados": [na[i] for i in sorted(set(na) - set(nb))],
        "cambiados": cambios,
        "iguales": sorted(i for i in set(na) & set(nb)
                          if not any(c["id"] == i for c in cambios)),
        "sin_cambios": (set(na) == set(nb) and not cambios),
    }


# ---------------------------------------------------------------------------
# Borrado. Todo pasa por la politica: la IA no borra sin permiso explicito.
# ---------------------------------------------------------------------------

def _autoriza(politica: str, quien: str) -> tuple:
    """(puede, motivo). `quien` es 'usuario' o 'ia'.

    El usuario siempre puede borrar lo suyo; la politica gobierna a la IA.
    Confundir los dos sujetos convertiria "la IA nunca borra" en "el dueno
    tampoco puede", que no es lo que nadie pidio.
    """
    if quien == "usuario":
        return True, ""
    pol = (politica or "nunca").strip().lower()
    if pol not in POLITICAS_BORRADO:
        return False, (f"politica de borrado desconocida ('{politica}'): "
                       f"por seguridad se trata como 'nunca'")
    if pol == "permitido":
        return True, ""
    if pol == "preguntar":
        return False, ("la politica es 'preguntar': hace falta que el usuario "
                       "confirme este borrado")
    return False, "la politica es 'nunca': la IA no puede borrar versiones"


def borrar_version(nombre: str, version: int, *, quien: str = "ia",
                   politica: str = "nunca") -> dict:
    """Borra UNA version. Nunca la actual (eso dejaria el flujo sin cuerpo)."""
    puede, motivo = _autoriza(politica, quien)
    if not puede:
        return {"ok": False, "motivo": motivo}
    meta = _leer_json(_ruta_meta(nombre))
    if not meta:
        return {"ok": False, "motivo": f"no hay ningun flujo llamado '{nombre}'"}
    v = int(version)
    if v == int(meta.get("version_actual") or 0):
        return {"ok": False,
                "motivo": (f"la v{v} es la version ACTUAL: restaura otra "
                           f"antes de borrar esta, o el flujo se queda sin "
                           f"cuerpo")}
    ruta = _ruta_version(nombre, v)
    if not ruta.exists():
        return {"ok": False, "motivo": f"'{nombre}' no tiene version {v}"}
    try:
        ruta.unlink()
    except Exception as exc:
        return {"ok": False, "motivo": f"{type(exc).__name__}: {exc}"}
    # La entrada del historial se MARCA borrada en vez de quitarse: si
    # desapareciera, el historial mentiria diciendo que la v3 nunca existio.
    for e in meta.get("versiones") or []:
        if int(e.get("v", 0)) == v:
            e["borrada"] = True
            e["borrada_ts"] = _ahora()
            e["borrada_por"] = quien
    meta["modificado"] = _ahora()
    _escribir_atomico(_ruta_meta(nombre), meta)
    return {"ok": True, "motivo": f"v{v} borrada"}


def borrar(nombre: str, *, quien: str = "ia", politica: str = "nunca") -> dict:
    """Borra el flujo ENTERO con todas sus versiones."""
    puede, motivo = _autoriza(politica, quien)
    if not puede:
        return {"ok": False, "motivo": motivo}
    d = _dir_flujo(nombre)
    if not d.is_dir():
        return {"ok": False, "motivo": f"no hay ningun flujo llamado '{nombre}'"}
    try:
        shutil.rmtree(d)
    except Exception as exc:
        return {"ok": False, "motivo": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "motivo": f"'{nombre}' borrado entero"}


def renombrar(nombre: str, nuevo: str) -> dict:
    """Cambia el nombre (y por tanto el directorio) conservando el historial."""
    if not (nuevo or "").strip():
        return {"ok": False, "motivo": "el nombre nuevo esta vacio"}
    origen, destino = _dir_flujo(nombre), _dir_flujo(nuevo)
    if not origen.is_dir():
        return {"ok": False, "motivo": f"no hay ningun flujo llamado '{nombre}'"}
    if destino.exists() and destino != origen:
        return {"ok": False, "motivo": f"ya hay un flujo llamado '{nuevo}'"}
    meta = _leer_json(origen / "meta.json") or {}
    meta["nombre"] = nuevo.strip()
    meta["slug"] = slugificar(nuevo)
    meta["modificado"] = _ahora()
    if destino != origen:
        os.replace(origen, destino)
    _escribir_atomico(destino / "meta.json", meta)
    # El nombre vive tambien DENTRO de cada version (flows.py lo lee de ahi):
    # dejarlo viejo haria que el lienzo y la ejecucion mostraran el anterior.
    for e in meta.get("versiones") or []:
        ruta = destino / f"v{int(e.get('v', 0))}.json"
        flujo = _leer_json(ruta)
        if flujo is not None:
            flujo["nombre"] = nuevo.strip()
            _escribir_atomico(ruta, flujo)
    return {"ok": True, "motivo": f"'{nombre}' -> '{nuevo}'"}


def duplicar(nombre: str, nuevo: str) -> dict:
    """Copia el flujo actual bajo otro nombre, empezando en v1.

    Se copia SOLO la version actual y no el historial entero: el historial de
    un flujo cuenta como se llego a EL, y arrastrarlo a la copia haria que el
    duplicado dijera cosas que no le pasaron."""
    try:
        flujo = cargar(nombre)
    except FlujotecaError as exc:
        return {"ok": False, "motivo": str(exc)}
    if existe(nuevo):
        return {"ok": False, "motivo": f"ya hay un flujo llamado '{nuevo}'"}
    guardar(flujo, nombre=nuevo,
            nota=f"duplicado de '{nombre}' v{_leer_json(_ruta_meta(nombre)).get('version_actual')}",
            descripcion=descripcion(nombre))
    return {"ok": True, "motivo": f"'{nuevo}' creado desde '{nombre}'"}


# ---------------------------------------------------------------------------
# Descripcion legible
# ---------------------------------------------------------------------------

def describir(flujo: dict) -> str:
    """El flujo en texto plano, en orden topologico. Es lo que se le ensena
    al MODELO cuando el usuario quiere editarlo conversando: un JSON crudo
    gasta el triple de tokens y se lee peor."""
    nodos = flujo.get("nodos") or []
    if not nodos:
        return "(flujo vacio)"
    try:
        from cognia.agent import flows as _flows
        orden = _flows.validar(flujo)
    except Exception:
        orden = [n.get("id") for n in nodos]
    por_id = {n.get("id"): n for n in nodos}
    lineas = [f"Flujo: {flujo.get('nombre', '(sin nombre)')}"]
    for nid in orden:
        n = por_id.get(nid) or {}
        wires = n.get("wires") or []
        linea = f"  {nid}: {n.get('tool', '?')}"
        args = str(n.get("args") or "")
        if args:
            linea += f"  args={args[:90]}"
        if wires:
            linea += f"  -> {', '.join(wires)}"
        else:
            linea += "  -> (fin)"
        extras = []
        if n.get("saltar_si"):
            extras.append(f"saltar_si={n['saltar_si']}")
        if n.get("reintentos"):
            extras.append(f"reintentos={n['reintentos']}")
        if n.get("modelo"):
            extras.append(f"modelo={n['modelo']}")
        if extras:
            linea += "  [" + " ".join(extras) + "]"
        lineas.append(linea)
    return "\n".join(lineas)
