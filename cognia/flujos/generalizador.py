"""
cognia/flujos/generalizador.py
==============================
De una TRAYECTORIA grabada (cognia/flujos/grabador.py) a un FLUJO
PARAMETRIZADO reutilizable.

QUE RESUELVE
    Una grabacion cruda no se puede reejecutar: lleva pasos fallidos, lecturas
    exploratorias que no influyeron en nada, repeticiones, y valores literales
    (el nombre del proyecto, la ruta del modulo, el puerto) incrustados en los
    args. Este modulo la CONVIERTE en un flujo con huecos ({param}), con
    postcondiciones VERIFICABLES y con un registro auditable de que se podo.

POR QUE EXISTE (y por que DETERMINISTA)
    Los productos existentes fallan justo aqui: Cursor delega la
    generalizacion en que un LLM escriba markdown (no reejecutable, no
    verificable) y Hermes persiste "salio bien" sin contrafactual. Y este repo
    ya pago el precio de lo contrario: las skills AUTO-CAPTURADAS envenenaron
    tareas ajenas — una traza de ATASCO se ascendio a "procedimiento
    verificado" y bajo el camino feliz de 5/5 a 2-4/5. De ahi las dos reglas
    duras de este modulo:

      1. Todo lo que DECIDE (poda, huecos, plantilla, postcondiciones) es
         DETERMINISTA y auditable. El LLM (completar_fn) solo puede pulir
         COSMETICA: nombre y descripcion. Jamas toca pasos ni postcondiciones.
      2. Un flujo del que no se derivan postcondiciones ejecutables sale con
         estado 'no_examinable' — NO se le inventan chequeos. Sin examen
         ejecutable nada auto-aprendido puede quedar activo.

    El estado de salida es SIEMPRE 'borrador' o 'no_examinable': quien lo
    promueve a activo es el examen (otro modulo), nunca este.

ESTRUCTURA DE ENTRADA (grabador.py)
    {id, titulo, tarea, workspace,
     pasos: [{n, tool, args, ok, resumen_resultado, duracion_s,
              ficheros_tocados, comando, exit_code}],
     resultado, ok}

ESTRUCTURA DE SALIDA (Flujo)
    {version_formato, nombre, descripcion,
     params: [{nombre, tipo, ejemplo, obligatorio}],
     pasos:  [{tool, args_plantilla, comando_plantilla, paso_origen}],
     postcondiciones: [...],
     origen: {grabacion_id, ts, tarea, workspace, pasos_podados},
     estado: 'borrador' | 'no_examinable'}

Solo stdlib. Sin dependencias del CLI ni del backend: se prueba entero en
seco. El LLM entra SIEMPRE inyectado como callable (completar_fn), nunca
importado aqui. NADA en este modulo lanza en el camino caliente: las
funciones devuelven valores (listas vacias, None, dicts con '_aviso').
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

__all__ = [
    "FORMATO_VERSION",
    "limpiar", "podas_de", "detectar_huecos", "parametrizar",
    "postcondiciones_de", "describir", "generalizar", "instanciar",
    "desde_grabacion",
    "dir_flujos", "guardar_flujo", "cargar_flujo", "listar_flujos",
]

# Version del formato en disco. Sube SOLO si cambia la forma del Flujo; cargar
# no rompe con una version distinta, deja '_aviso' (politica devuelve valores).
FORMATO_VERSION = 1


# ---------------------------------------------------------------------------
# Vocabulario de tools. No se importa cognia.agent.tools a proposito: este
# modulo tiene que poder probarse sin arrastrar el registry entero (y el
# registry cambia con flags opt-in, lo que haria la poda NO determinista).
# ---------------------------------------------------------------------------

_TOOLS_LECTURA = {
    "leer_archivo", "leer_lote", "listar", "arbol", "buscar",
    "buscar_ficheros", "repo_map", "code_grafo", "contar_lineas",
    "git_estado", "git_diff", "git_log", "recordar", "kg_buscar",
    "ver_salida", "notas",
}

_TOOLS_ESCRITURA = {
    "escribir_archivo", "editar_archivo", "apendar_archivo",
    "crear_directorio", "copiar_archivo", "mover_archivo", "generar_codigo",
}

_TOOLS_BORRADO = {"borrar_archivo"}

_TOOLS_COMANDO = {"ejecutar", "ejecutar_fondo", "tests"}


# ---------------------------------------------------------------------------
# Helpers de texto sobre el protocolo de args ('ruta | contenido', 'k=v').
# ---------------------------------------------------------------------------

def _s(x) -> str:
    return "" if x is None else str(x)


def _como_dict(traj):
    """Acepta un dict o el objeto Grabacion del grabador (pato: tiene a_dict).
    NO se importa grabador aqui — este modulo no debe arrastrarlo al import, y
    asi el generalizador se prueba sin el."""
    if traj is None:
        return {}
    if isinstance(traj, dict):
        return traj
    a_dict = getattr(traj, "a_dict", None)
    if callable(a_dict):
        try:
            d = a_dict()
            if isinstance(d, dict):
                return d
        except Exception:
            return {}
    return {}


def _normalizar_espacios(texto) -> str:
    return " ".join(_s(texto).split())


def _cabeza_args(args) -> str:
    """La parte de los args ANTES del primer '|': la ruta/objetivo. El cuerpo
    (contenido de fichero) se excluye del DESCUBRIMIENTO de candidatos porque
    esta lleno de palabras del lenguaje ('def', 'import') que repiten entre
    pasos y se colarian como parametros. Una vez aceptado un hueco, sus
    ocurrencias SI se buscan en el args completo (contenido incluido)."""
    return _s(args).split("|", 1)[0].strip()


def _cuerpo_args(args) -> str:
    partes = _s(args).split("|", 1)
    return partes[1].strip() if len(partes) > 1 else ""


_RE_CLAVE = re.compile(r"^[a-z_]{2,20}=")


def _objetivo(paso: dict) -> str:
    """Sobre que actua el paso: la cabeza de los args, o el comando."""
    cab = _cabeza_args(paso.get("args"))
    if _RE_CLAVE.match(cab):
        cab = cab.split("=", 1)[1].strip()
    if cab:
        return cab
    return _normalizar_espacios(paso.get("comando"))


def _texto_paso(paso: dict) -> str:
    """Todo el texto donde puede MENCIONARSE un fichero (para la regla de
    lecturas no influyentes)."""
    trozos = [_s(paso.get("args")), _s(paso.get("comando")),
              _s(paso.get("resumen_resultado"))]
    tocados = paso.get("ficheros_tocados") or []
    if isinstance(tocados, (list, tuple)):
        trozos.extend(_s(t) for t in tocados)
    return " ".join(trozos)


def _es_palabra(c: str) -> bool:
    return bool(c) and (c.isalnum() or c == "_")


def _buscar_literal(texto: str, valor: str) -> list:
    """Posiciones de `valor` en `texto` con frontera de palabra (para que
    '8080' no case dentro de '18080' ni 'ropa' dentro de 'tienda_ropa')."""
    out = []
    if not valor:
        return out
    i = texto.find(valor)
    while i != -1:
        pre = texto[i - 1] if i > 0 else ""
        fin = i + len(valor)
        post = texto[fin] if fin < len(texto) else ""
        if not _es_palabra(pre) and not _es_palabra(post):
            out.append(i)
        i = texto.find(valor, i + 1)
    return out


def _slug(texto, maximo: int = 48) -> str:
    limpio = re.sub(r"[^a-zA-Z0-9]+", "_", _s(texto)).strip("_").lower()
    limpio = re.sub(r"_+", "_", limpio)
    return limpio[:maximo] or "flujo"


# ---------------------------------------------------------------------------
# 1) LIMPIAR — poda determinista con registro auditable.
#
# Tres reglas, en este orden (el orden importa: un paso fallido no debe
# "sostener" la influencia de una lectura):
#
#   R1 'fallido' /            paso con ok=False. Si antes hubo un fallo con la
#      'reintento_fallido'    misma tool y el mismo objetivo, se marca como
#                             reintento (mismo efecto, motivo distinto para que
#                             el usuario entienda la cadena). El reintento que
#                             SI salio bien sobrevive: es el que hizo el
#                             trabajo.
#   R2 'repeticion'           paso identico (misma tool, mismos args
#                             normalizados) a otro anterior vivo: se queda el
#                             PRIMERO. Un efecto identico repetido no aporta.
#   R3 'lectura_no_influyente' lectura cuyo objetivo no se vuelve a mencionar
#                             en ningun paso vivo POSTERIOR ni en el resultado.
#                             Punto fijo: podar una lectura puede dejar
#                             huerfana a la anterior.
#
# Guarda: si R3 dejaria la trayectoria VACIA, se revierte entera. Una
# trayectoria puramente exploratoria no se poda a la nada; saldra
# 'no_examinable' y decide el usuario.
#
# El registro (traj['_poda']) existe porque el usuario TIENE que poder ver por
# que su paso desaparecio: sin eso la poda es magia y nadie confia en ella.
# ---------------------------------------------------------------------------

def _entrada_poda(paso: dict, regla: str, motivo: str) -> dict:
    return {
        "n": paso.get("n"),
        "tool": _s(paso.get("tool")),
        "args": _s(paso.get("args"))[:120],
        "regla": regla,
        "motivo": motivo,
    }


def _mencionado_despues(objetivo: str, pasos: list, i: int, vivos: dict,
                        traj: dict) -> bool:
    for j in range(i + 1, len(pasos)):
        if not vivos.get(j):
            continue
        if objetivo in _texto_paso(pasos[j]):
            return True
    return objetivo in _s(traj.get("resultado"))


def limpiar(traj: dict) -> dict:
    """Trayectoria podada. Devuelve una COPIA con 'pasos' filtrado y '_poda'
    con una entrada por paso eliminado (regla + motivo legible)."""
    traj = _como_dict(traj)
    pasos = list(traj.get("pasos") or [])
    vivos = {i: True for i in range(len(pasos))}
    podas = []

    # R1: fallidos y sus reintentos.
    fallos_previos = []
    for i, p in enumerate(pasos):
        if p.get("ok", True) is not False:
            continue
        tool = _s(p.get("tool"))
        obj = _objetivo(p)
        reintento = any(t == tool and o == obj for (t, o) in fallos_previos)
        vivos[i] = False
        if reintento:
            podas.append(_entrada_poda(
                p, "reintento_fallido",
                "reintento fallido de '%s' sobre '%s'" % (tool, obj[:60])))
        else:
            podas.append(_entrada_poda(
                p, "fallido",
                "el paso fallo (ok=False, exit_code=%s)" % (p.get("exit_code"),)))
        fallos_previos.append((tool, obj))

    # R2: repeticiones exactas.
    vistos = {}
    for i, p in enumerate(pasos):
        if not vivos[i]:
            continue
        clave = (_s(p.get("tool")), _normalizar_espacios(p.get("args")),
                 _normalizar_espacios(p.get("comando")))
        if clave in vistos:
            primero = pasos[vistos[clave]]
            vivos[i] = False
            podas.append(_entrada_poda(
                p, "repeticion",
                "identico al paso %s (misma tool y mismos args)"
                % (primero.get("n"),)))
        else:
            vistos[clave] = i

    # R3: lecturas exploratorias que no influyeron (punto fijo).
    podas_r3 = []
    for _ in range(10):
        cambio = False
        for i, p in enumerate(pasos):
            if not vivos[i]:
                continue
            if _s(p.get("tool")) not in _TOOLS_LECTURA:
                continue
            obj = _objetivo(p)
            # Sin objetivo legible (o de 1 caracter, tipo '.') no hay como
            # juzgar influencia: se CONSERVA. La poda solo elimina lo que
            # puede justificar.
            if len(obj) < 2:
                continue
            if _mencionado_despues(obj, pasos, i, vivos, traj):
                continue
            vivos[i] = False
            cambio = True
            podas_r3.append(_entrada_poda(
                p, "lectura_no_influyente",
                "lectura de '%s' que no se vuelve a mencionar despues"
                % (obj[:60],)))
        if not cambio:
            break

    if podas_r3 and not any(vivos.values()):
        # La trayectoria era pura exploracion: revertir R3 entera.
        for entrada in podas_r3:
            for i, p in enumerate(pasos):
                if p.get("n") == entrada["n"]:
                    vivos[i] = True
        podas.append({
            "n": None, "tool": "", "args": "", "regla": "poda_revertida",
            "motivo": ("la regla lectura_no_influyente dejaba la trayectoria "
                       "vacia: se conservan las lecturas"),
        })
    else:
        podas.extend(podas_r3)

    nueva = dict(traj)
    nueva["pasos"] = [p for i, p in enumerate(pasos) if vivos[i]]
    nueva["_poda"] = podas
    return nueva


def podas_de(traj: dict) -> list:
    """Registro de poda de una trayectoria ya limpiada (vacio si no se limpio)."""
    return list((traj or {}).get("_poda") or [])


# ---------------------------------------------------------------------------
# 2) DETECTAR HUECOS — que valores deberian ser parametros.
#
# Cuatro senales:
#   (a) subcadenas de los args que tambien salen en el texto de la tarea
#   (b) rutas de fichero
#   (c) numeros y fechas
#   (d) valores que se repiten en varios pasos (p.ej. el nombre del proyecto)
#
# Descubrimiento en DOS fuentes para no envenenarse con el contenido de los
# ficheros: (i) tokens de la TAREA, (ii) tokens de la CABEZA de los args y del
# comando. Las OCURRENCIAS de un hueco ya aceptado si se buscan en el args
# completo — asi el nombre del proyecto tambien se sustituye dentro del codigo
# que se escribio.
# ---------------------------------------------------------------------------

_RE_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_RE_RUTA = re.compile(
    r"[A-Za-z0-9_.\-]*(?:[/\\][A-Za-z0-9_.\-]+)+"
    r"|[A-Za-z0-9_\-]+\.[A-Za-z]{1,5}\b")
_RE_NUMERO = re.compile(r"\b\d+(?:\.\d+)?\b")
_RE_PALABRA = re.compile(r"\b[A-Za-z_][A-Za-z0-9_\-]{2,}\b")
_RE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

# Tres listas con TRES trabajos distintos (mezclarlas fue el primer bug del
# modulo: 'modulo' no puede ser un VALOR pero es el mejor NOMBRE posible para
# el hueco de 'el modulo de flujos').
#
# _ARTICULOS   conectores: ni valor ni nombre ni parte del nombre del flujo.
# _VERBOS      la accion: no nombra un parametro, pero SI el flujo entero
#              ('crea_proyecto_python').
# _TECNICAS    tecnologias y vocabulario estructural: no son parametro (nadie
#              quiere rellenar {tests} en 'proyecto/{tests}/x.py') ni nombran.
_ARTICULOS = {
    "llamado", "llamada", "llamados", "nombre", "nombrado", "titulado",
    "un", "una", "uno", "unos", "unas", "el", "la", "lo", "los", "las",
    "de", "del", "en", "a", "al", "y", "o", "se", "su", "sus", "mi",
    "nuevo", "nueva", "otro", "otra", "dentro", "usando", "usa",
    "que", "por", "con", "para", "como", "esta", "este", "todo", "toda",
    "mas", "pero", "sin", "sobre", "hasta", "desde", "cada", "entre",
    "luego", "tambien", "the", "this", "and", "not", "for", "with", "from",
}
_VERBOS = {
    "crea", "crear", "haz", "hacer", "genera", "generar", "escribe",
    "escribir", "agrega", "agregar", "anade", "anadir", "corre", "correr",
    "ejecuta", "ejecutar", "mueve", "borra", "elimina", "actualiza", "lista",
    "busca", "arregla", "implementa", "refactoriza", "refactorizar",
    "explica", "explicame", "revisa", "verifica", "extraer", "extrae",
}
_TECNICAS = {
    "src", "test", "tests", "lib", "app", "bin", "doc", "docs", "build",
    "dist", "python", "python3", "pytest", "pip", "npm", "node", "git",
    "bash", "sh", "venv", "readme", "json", "yaml", "yml", "toml", "txt",
    "md", "py", "js", "ts", "html", "css", "exe", "log", "tmp", "temp",
    "utf", "utf8", "encoding", "main", "init", "setup", "config",
    "def", "class", "import", "return", "self", "print", "none",
    "true", "false", "null",
}
# Sustantivos genericos: no son un VALOR razonable, pero si el mejor NOMBRE.
_GENERICOS = {"funcion", "modulo", "fichero", "archivo", "carpeta",
              "directorio", "proyecto", "clase", "metodo", "variable"}

# Palabras que NUNCA son un parametro aunque cumplan las senales.
_STOP_VALORES = _ARTICULOS | _VERBOS | _TECNICAS | _GENERICOS

# Palabras que no sirven para NOMBRAR un parametro (pero si pueden ser el
# valor): sin esto 'crea un proyecto python llamado X' nombraria el hueco
# 'python' en vez de 'proyecto'.
_NO_NOMBRAN = _ARTICULOS | _VERBOS | _TECNICAS


def _limpia_token(valor: str) -> str:
    return valor.strip().strip(".,;:'\"()[]{}")


def _candidato_valido(valor: str, tipo: str) -> bool:
    if not valor or len(valor) < 2:
        return False
    if valor.lower() in _STOP_VALORES:
        return False
    if tipo == "ruta":
        if not any(c in valor for c in "/\\."):
            return False
        if valor.endswith(("/", "\\", ".")):
            return False
    return True


def _tokens(texto) -> list:
    """[(valor, tipo)] candidatos de un texto. El desempate real (cuando dos
    candidatos pisan los mismos caracteres) lo hace la resolucion de solapes."""
    texto = _s(texto)
    out = []
    for rx, tipo in ((_RE_FECHA, "fecha"), (_RE_RUTA, "ruta"),
                     (_RE_NUMERO, "numero"), (_RE_PALABRA, "texto")):
        for m in rx.finditer(texto):
            v = _limpia_token(m.group(0))
            if _candidato_valido(v, tipo):
                out.append((v, tipo))
    return out


def _tipo_de(valor: str) -> str:
    if _RE_FECHA.fullmatch(valor):
        return "fecha"
    if any(c in valor for c in "/\\") or re.fullmatch(
            r"[A-Za-z0-9_\-]+\.[A-Za-z]{1,5}", valor):
        return "ruta"
    if _RE_NUMERO.fullmatch(valor):
        return "numero"
    return "texto"


def _nombre_desde_tarea(tarea: str, valor: str) -> str:
    """El sustantivo que PRECEDE al valor en la tarea ('un proyecto llamado
    tienda_ropa' -> 'proyecto'). Heuristica barata y sorprendentemente buena:
    el humano casi siempre dice que ES el valor justo antes de decirlo."""
    low = _s(tarea).lower()
    i = -1
    # Una ocurrencia DENTRO de una ruta no sirve para nombrar: en
    # 'cognia/analytics/informe.py' la palabra previa a 'informe' es
    # 'analytics', que no describe nada. Se busca la primera ocurrencia suelta.
    for pos in _buscar_literal(low, valor.lower()):
        pre = low[pos - 1] if pos > 0 else " "
        post = low[pos + len(valor)] if pos + len(valor) < len(low) else " "
        if pre in "/\\." or post in "/\\.":
            continue
        i = pos
        break
    if i <= 0:
        return ""
    previas = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", low[:i])[-4:]
    for palabra in reversed(previas):
        if palabra in _NO_NOMBRAN or len(palabra) < 3:
            continue
        return _slug(palabra, 24)
    return ""


def _nombre_sugerido(valor: str, tipo: str, tarea: str) -> str:
    if tipo == "ruta":
        # El stem es mas informativo que el path entero:
        # 'cognia/analytics/informe.py' -> 'ruta_informe'
        base = re.split(r"[/\\]", valor)[-1]
        stem = base.split(".")[0]
        return _slug("ruta_" + stem, 32) if stem else "ruta"
    desde_tarea = _nombre_desde_tarea(tarea, valor)
    if desde_tarea:
        return desde_tarea
    if tipo == "texto" and _RE_IDENT.match(valor):
        # Sin contexto en la tarea, el propio valor es el nombre menos malo:
        # '{resumen}' se entiende, '{texto_1}' no.
        return _slug(valor, 24)
    return {"numero": "numero", "fecha": "fecha"}.get(tipo, "texto")


def _solapa(ini: int, fin: int, tomados: list) -> bool:
    return any(not (fin <= a or ini >= b) for a, b in tomados)


def detectar_huecos(traj: dict) -> list:
    """[Hueco] — Hueco es un dict {nombre_sugerido, ejemplo, ocurrencias, tipo}
    con ocurrencias = [(paso, campo, (ini, fin))]. Estilo del repo: dicts."""
    traj = _como_dict(traj)
    tarea = _s(traj.get("tarea"))
    pasos = list(traj.get("pasos") or [])

    candidatos = {}
    for v, t in _tokens(tarea):
        candidatos.setdefault(v, t)
    for p in pasos:
        fuente = _cabeza_args(p.get("args")) + " " + _s(p.get("comando"))
        for v, t in _tokens(fuente):
            candidatos.setdefault(v, t)

    tarea_low = tarea.lower()
    brutos = []
    for valor in candidatos:
        tipo = _tipo_de(valor)
        ocurr = []
        for idx, p in enumerate(pasos):
            n = p.get("n", idx + 1)
            for campo in ("args", "comando"):
                texto = _s(p.get(campo))
                for ini in _buscar_literal(texto, valor):
                    ocurr.append((n, campo, (ini, ini + len(valor)), idx))
        if not ocurr:
            continue
        en_tarea = valor.lower() in tarea_low
        n_pasos = len(set(o[0] for o in ocurr))
        # Aceptacion: (a) sale en la tarea, (b) es una ruta, o (d) se repite en
        # >=2 pasos. Numeros y fechas (c) entran por (a) o (d): un numero
        # suelto en un solo paso suele ser ruido (un timeout, un ancho).
        if not (en_tarea or tipo == "ruta" or n_pasos >= 2):
            continue
        primera = min((o[3], o[2][0]) for o in ocurr)
        brutos.append({
            "valor": valor, "tipo": tipo, "ocurrencias": ocurr,
            "en_tarea": en_tarea, "n_pasos": n_pasos, "primera": primera,
        })

    # Resolucion de solapes: 'src/tienda_ropa/main.py' y 'tienda_ropa' compiten
    # por los mismos caracteres. Gana el que sale en la TAREA, luego el que se
    # repite en mas pasos, luego el mas largo. POR QUE ese orden: el valor que
    # el usuario nombro en la tarea es el que va a querer cambiar, y dejar
    # 'src/{proyecto}/main.py' generaliza mejor que un unico hueco opaco.
    brutos.sort(key=lambda h: (not h["en_tarea"], -h["n_pasos"],
                               -len(h["valor"]), h["primera"]))

    tomados = {}
    usados = set()
    huecos = []
    for h in brutos:
        libres = []
        for (n, campo, span, _idx) in h["ocurrencias"]:
            if _solapa(span[0], span[1], tomados.get((n, campo), [])):
                continue
            libres.append((n, campo, span))
        if not libres:
            continue
        for (n, campo, span) in libres:
            tomados.setdefault((n, campo), []).append(span)
        nombre = _nombre_sugerido(h["valor"], h["tipo"], tarea)
        base, k = nombre, 2
        while nombre in usados:
            nombre = "%s_%d" % (base, k)
            k += 1
        usados.add(nombre)
        huecos.append({
            "nombre_sugerido": nombre,
            "ejemplo": h["valor"],
            "ocurrencias": libres,
            "tipo": h["tipo"],
            "en_tarea": h["en_tarea"],
        })

    huecos.sort(key=lambda h: (h["ocurrencias"][0][0], h["ocurrencias"][0][2][0]))
    return huecos


# ---------------------------------------------------------------------------
# 3) POSTCONDICIONES — el examen posterior. Solo del EFECTO OBSERVADO.
#
# Sin postcondiciones un flujo NO se puede verificar: en ese caso sale
# 'no_examinable'. Jamas se inventan — esa es exactamente la enfermedad de las
# skills auto-capturadas: prosa que afirma exito sin nada que lo pruebe.
# ---------------------------------------------------------------------------

def _rutas_del_paso(paso: dict) -> list:
    tocados = paso.get("ficheros_tocados") or []
    rutas = [_s(t).strip() for t in tocados if _s(t).strip()]
    if not rutas:
        cab = _objetivo(paso)
        if cab and any(c in cab for c in "/\\."):
            rutas = [cab]
    return rutas


_MARCAS_EDICION = ("<<<<<<<", "=======", ">>>>>>>")


def _linea_distintiva(args) -> str:
    """Una linea corta y reconocible del contenido que QUEDA en el fichero,
    para el chequeo 'fichero_contiene'.

    En editar_archivo (SEARCH/REPLACE, estilo Aider) el cuerpo trae las DOS
    versiones: la vieja arriba y la nueva debajo del '======='. Quedarse con
    la de arriba produce un chequeo que verifica lo que se acaba de BORRAR — un
    examen que reprueba precisamente cuando el flujo funciono. Por eso se toma
    la mitad de abajo y se descartan los marcadores."""
    cuerpo = _cuerpo_args(args)
    if "=======" in cuerpo:
        cuerpo = cuerpo.split("=======")[-1]
    for linea in cuerpo.splitlines():
        l = linea.strip()
        if len(l) < 4 or l.startswith("```"):
            continue
        if any(l.startswith(m) for m in _MARCAS_EDICION):
            continue
        return l[:60]
    return ""


def postcondiciones_de(traj: dict) -> list:
    """Chequeos VERIFICABLES derivados del efecto observado. Lista (posiblemente
    vacia) de dicts: {tipo: 'fichero_existe' | 'fichero_contiene' |
    'fichero_no_existe' | 'comando_exit0', ...}."""
    traj = _como_dict(traj)
    out = []
    vistos = set()

    def _add(post: dict) -> None:
        # 'de_paso' es trazabilidad, no semantica: queda FUERA de la clave para
        # que dos pasos que dejan el mismo efecto no produzcan dos chequeos
        # identicos (un examen con chequeos repetidos infla el 'pasa' sin
        # verificar nada nuevo).
        clave = tuple(sorted((k, _s(v)) for k, v in post.items()
                             if k != "de_paso"))
        if clave not in vistos:
            vistos.add(clave)
            out.append(post)

    for p in traj.get("pasos") or []:
        if p.get("ok", True) is False:
            continue
        tool = _s(p.get("tool"))
        if tool in _TOOLS_ESCRITURA:
            rutas = _rutas_del_paso(p)
            for ruta in rutas:
                _add({"tipo": "fichero_existe", "ruta": ruta,
                      "de_paso": p.get("n")})
            texto = _linea_distintiva(p.get("args"))
            if texto and rutas and tool != "crear_directorio":
                _add({"tipo": "fichero_contiene", "ruta": rutas[0],
                      "texto": texto, "de_paso": p.get("n")})
        elif tool in _TOOLS_BORRADO:
            # NO se emite 'fichero_no_existe' aunque sea trivialmente
            # verificable. examen.py YA lo traduce (TIPOS_ALIAS), pero
            # reproductor.verificar_postcondiciones solo entiende
            # fichero_existe / fichero_contiene / comando_exit0 y REPRUEBA todo
            # tipo desconocido ("no se aprueba lo que no se entiende"). Con uno
            # de los dos verificadores en contra, emitirlo convertiria un flujo
            # correcto en uno que suspende su propio examen. En cuanto el
            # reproductor soporte el tipo, esto son tres lineas; mientras tanto
            # un flujo que solo borra sale 'no_examinable', que es la etiqueta
            # honesta y no una condena.
            continue
        elif tool in _TOOLS_COMANDO:
            comando = (_normalizar_espacios(p.get("comando"))
                       or _normalizar_espacios(p.get("args")))
            # Solo un exit 0 OBSERVADO es postcondicion. Si no se grabo el
            # codigo de salida no se afirma nada: mejor menos chequeos que un
            # chequeo falso — un flujo que "pasa" sin haber probado nada es
            # peor que uno marcado no_examinable.
            if comando and p.get("exit_code") == 0:
                _add({"tipo": "comando_exit0", "comando": comando,
                      "de_paso": p.get("n")})
    return out


# ---------------------------------------------------------------------------
# 4) PARAMETRIZAR — trayectoria + huecos -> Flujo.
# ---------------------------------------------------------------------------

def _sustituir_spans(texto: str, spans: list) -> str:
    """spans: [(ini, fin, nombre)] sobre el texto ORIGINAL; se aplican de
    derecha a izquierda para que los indices no se muevan."""
    texto = _s(texto)
    for ini, fin, nombre in sorted(spans, key=lambda s: -s[0]):
        texto = texto[:ini] + "{" + nombre + "}" + texto[fin:]
    return texto


def _plantillar_texto(texto, huecos: list) -> str:
    """Plantilla por VALOR (sin spans): para postcondiciones, donde no se
    guardaron indices. Del valor mas largo al mas corto para que 'a/b/c.py' no
    quede a medio sustituir por 'c.py'."""
    texto = _s(texto)
    for h in sorted(huecos, key=lambda h: -len(h["ejemplo"])):
        pos = _buscar_literal(texto, h["ejemplo"])
        if pos:
            texto = _sustituir_spans(
                texto, [(i, i + len(h["ejemplo"]), h["nombre_sugerido"])
                        for i in pos])
    return texto


def parametrizar(traj: dict, huecos: list) -> dict:
    """Flujo (dict) con los valores de `huecos` sustituidos por marcadores
    {nombre}. El estado sale 'borrador', o 'no_examinable' si no se derivo
    ninguna postcondicion verificable."""
    traj = _como_dict(traj)
    huecos = list(huecos or [])

    por_paso = {}
    for h in huecos:
        for (n, campo, span) in h["ocurrencias"]:
            por_paso.setdefault((n, campo), []).append(
                (span[0], span[1], h["nombre_sugerido"]))

    pasos_out = []
    for idx, p in enumerate(traj.get("pasos") or []):
        n = p.get("n", idx + 1)
        comando = _s(p.get("comando"))
        paso = {
            "tool": _s(p.get("tool")),
            "args_plantilla": _sustituir_spans(
                p.get("args"), por_paso.get((n, "args"), [])),
            "paso_origen": n,
        }
        if comando:
            paso["comando_plantilla"] = _sustituir_spans(
                comando, por_paso.get((n, "comando"), []))
        pasos_out.append(paso)

    posts = []
    for post in postcondiciones_de(traj):
        nuevo = dict(post)
        for campo in ("ruta", "texto", "comando"):
            if campo in nuevo:
                nuevo[campo] = _plantillar_texto(nuevo[campo], huecos)
        posts.append(nuevo)

    params = [{
        "nombre": h["nombre_sugerido"],
        "tipo": h["tipo"],
        "ejemplo": h["ejemplo"],
        # Obligatorio solo lo que el usuario NOMBRO en la tarea: lo demas tiene
        # el ejemplo como valor por defecto y no estorba al reusar el flujo.
        "obligatorio": bool(h.get("en_tarea")),
        # 'default' es REDUNDANTE con 'ejemplo' a proposito: es el campo que lee
        # reproductor.params_declarados. Sin el, un param no obligatorio no
        # entra en los valores efectivos, su marcador queda sin ligar y
        # reproductor.ligar() devuelve ok=False — un flujo perfecto que no
        # corre por un nombre de campo. Lo cubre
        # test_el_flujo_generado_liga_en_el_reproductor.
        "default": None if h.get("en_tarea") else h["ejemplo"],
    } for h in huecos]

    flujo = {
        "version_formato": FORMATO_VERSION,
        "nombre": "",
        "descripcion": "",
        "params": params,
        "pasos": pasos_out,
        "postcondiciones": posts,
        "origen": {
            "grabacion_id": traj.get("id"),
            "ts": time.time(),
            "tarea": _s(traj.get("tarea")),
            "titulo": _s(traj.get("titulo")),
            "workspace": _s(traj.get("workspace")),
            "pasos_podados": podas_de(traj),
        },
        # 'no_examinable' NO es un error: es la senal de que este flujo no
        # puede pasar un examen ejecutable y por tanto no debe activarse solo.
        "estado": "borrador" if posts else "no_examinable",
        "avisos": _avisos_de(traj),
    }
    return describir(flujo, None)


def _avisos_de(traj: dict) -> list:
    """Lo que el flujo NO puede prometer, dicho en voz alta. Hoy solo uno: el
    grabador que engancha del bus recibe `args` RECORTADO a 120 chars
    (loop.py:711), asi que el contenido de escribir_archivo y los comandos
    largos NO estan enteros. Callarlo produciria plantillas que parecen
    completas y reproducen a medias — el fallo silencioso de siempre."""
    if any(p.get("via_bus") for p in traj.get("pasos") or []):
        return ["hay pasos grabados desde el bus: sus args llegan recortados a "
                "120 chars y la plantilla puede estar incompleta"]
    return []


# ---------------------------------------------------------------------------
# 5) DESCRIBIR — nombre y descripcion legibles. Con o SIN LLM.
# ---------------------------------------------------------------------------

def _nombre_determinista(flujo: dict) -> str:
    origen = flujo.get("origen") or {}
    fuente = _s(origen.get("tarea")) or _s(origen.get("titulo"))
    ejemplos = [_s(p.get("ejemplo")).lower() for p in flujo.get("params") or []]
    palabras = []
    for w in re.findall(r"[A-Za-z0-9_]+", fuente):
        wl = w.lower()
        # Aqui SI entran los verbos: 'crea_proyecto_python' nombra mejor un
        # flujo que 'proyecto_python'. Solo se van los conectores.
        if len(wl) < 3 or wl in _ARTICULOS:
            continue
        # Los VALORES no van en el nombre: el flujo sirve para cualquier valor.
        if any(wl == ej or wl in ej for ej in ejemplos):
            continue
        palabras.append(wl)
        if len(palabras) >= 4:
            break
    if not palabras:
        tools = [_s(p.get("tool")) for p in flujo.get("pasos") or []]
        palabras = ["flujo"] + [t for t in tools[:2] if t]
    return _slug("_".join(palabras), 48)


def _descripcion_determinista(flujo: dict) -> str:
    pasos = flujo.get("pasos") or []
    tools = []
    for p in pasos:
        t = _s(p.get("tool"))
        if t and t not in tools:
            tools.append(t)
    params = [_s(p.get("nombre")) for p in flujo.get("params") or []]
    posts = flujo.get("postcondiciones") or []
    partes = ["%d pasos (%s)" % (len(pasos), ", ".join(tools[:5]) or "sin tools")]
    partes.append("%d parametros (%s)"
                  % (len(params), ", ".join(params[:6]) or "ninguno"))
    if posts:
        partes.append("%d postcondiciones verificables" % len(posts))
    else:
        partes.append("SIN postcondiciones verificables (no_examinable)")
    tarea = _s((flujo.get("origen") or {}).get("tarea"))[:120]
    cabecera = ("Derivado de: %s. " % tarea) if tarea else ""
    return cabecera + "; ".join(partes) + "."


def _parsear_respuesta_llm(texto) -> tuple:
    """(nombre, descripcion) de la respuesta del LLM. Tolerante: acepta
    'NOMBRE:/DESCRIPCION:' o un JSON {nombre, descripcion}."""
    texto = _s(texto).strip()
    nombre = desc = ""
    if texto.startswith("{"):
        try:
            d = json.loads(texto)
            nombre = _s(d.get("nombre"))
            desc = _s(d.get("descripcion"))
        except Exception:
            nombre = desc = ""
    if not nombre and not desc:
        for linea in texto.splitlines():
            l = linea.strip()
            low = l.lower()
            if low.startswith("nombre:"):
                nombre = l.split(":", 1)[1].strip()
            elif low.startswith("descripcion:") or low.startswith("descripción:"):
                desc = l.split(":", 1)[1].strip()
    return nombre, desc


def describir(flujo: dict, completar_fn=None) -> dict:
    """Rellena 'nombre' y 'descripcion'. Sin completar_fn produce algo usable
    igual (deterministico). Con completar_fn (LLM inyectado) los PULE — y solo
    eso: el LLM no puede tocar pasos, params, postcondiciones ni estado, y si
    falla o devuelve basura se conserva la version determinista."""
    flujo = flujo or {}
    nombre = _nombre_determinista(flujo)
    desc = _descripcion_determinista(flujo)

    if completar_fn is not None:
        prompt = (
            "Da un nombre corto en snake_case y una descripcion de UNA linea "
            "para este flujo reutilizable. Responde exactamente en dos lineas:\n"
            "NOMBRE: <snake_case>\nDESCRIPCION: <una linea>\n\n"
            "Tarea original: %s\nPasos: %s\nParametros: %s\n"
            "Postcondiciones: %d\n" % (
                _s((flujo.get("origen") or {}).get("tarea")),
                [_s(p.get("tool")) for p in flujo.get("pasos") or []],
                [_s(p.get("nombre")) for p in flujo.get("params") or []],
                len(flujo.get("postcondiciones") or []),
            )
        )
        try:
            n2, d2 = _parsear_respuesta_llm(completar_fn(prompt))
            n2 = _slug(n2, 48) if n2 else ""
            if n2 and n2 != "flujo":
                nombre = n2
            if d2:
                desc = d2.strip()[:300]
        except Exception:
            pass        # el adorno jamas rompe la sustancia (regla del bus)

    flujo["nombre"] = nombre
    flujo["descripcion"] = desc
    return flujo


# ---------------------------------------------------------------------------
# 6) API de conveniencia + instanciacion (el camino de vuelta).
# ---------------------------------------------------------------------------

def generalizar(traj: dict, completar_fn=None) -> dict:
    """Trayectoria cruda -> Flujo: limpiar + detectar_huecos + parametrizar +
    describir. Es el unico punto que necesita el orquestador."""
    limpia = limpiar(traj)
    huecos = detectar_huecos(limpia)
    flujo = parametrizar(limpia, huecos)
    return describir(flujo, completar_fn)


def desde_grabacion(grabacion_id: str, completar_fn=None):
    """Carga una grabacion del disco por id y la generaliza. Devuelve el Flujo
    o None si la grabacion no existe. El import de grabador va DENTRO a
    proposito: al importar este modulo no se arrastra el grabador (ni su
    suscripcion al bus), y el generalizador se prueba sin el."""
    try:
        from cognia.flujos import grabador
    except Exception:
        return None
    g = grabador.cargar(grabacion_id)
    if g is None:
        return None
    return generalizar(g, completar_fn)


_RE_MARCADOR = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _rellenar(texto, valores: dict) -> str:
    """Sustituye {nombre} SOLO para los nombres conocidos. No se usa
    str.format a proposito: el contenido de un fichero lleva llaves (JSON,
    f-strings, CSS) y format explotaria o se comeria caracteres."""
    def _rep(m):
        k = m.group(1)
        return valores[k] if k in valores else m.group(0)
    return _RE_MARCADOR.sub(_rep, _s(texto))


def instanciar(flujo: dict, valores: dict = None) -> dict:
    """{ok, faltantes, valores, pasos, postcondiciones} con los marcadores
    rellenos. Los params no obligatorios caen a su 'ejemplo'. NO lanza: un
    parametro obligatorio ausente sale en 'faltantes' con ok=False y decide el
    llamador (politica devuelve valores, no excepciones)."""
    flujo = flujo or {}
    dados = dict(valores or {})
    finales = {}
    faltantes = []
    for p in flujo.get("params") or []:
        nombre = _s(p.get("nombre"))
        if nombre in dados and _s(dados[nombre]) != "":
            finales[nombre] = _s(dados[nombre])
        elif not p.get("obligatorio"):
            finales[nombre] = _s(p.get("ejemplo"))
        else:
            faltantes.append(nombre)

    pasos = []
    for p in flujo.get("pasos") or []:
        paso = {"tool": _s(p.get("tool")),
                "args": _rellenar(p.get("args_plantilla"), finales),
                "paso_origen": p.get("paso_origen")}
        if p.get("comando_plantilla"):
            paso["comando"] = _rellenar(p.get("comando_plantilla"), finales)
        pasos.append(paso)

    posts = []
    for post in flujo.get("postcondiciones") or []:
        nuevo = dict(post)
        for campo in ("ruta", "texto", "comando"):
            if campo in nuevo:
                nuevo[campo] = _rellenar(nuevo[campo], finales)
        posts.append(nuevo)

    return {"ok": not faltantes, "faltantes": faltantes, "valores": finales,
            "pasos": pasos, "postcondiciones": posts}


# ---------------------------------------------------------------------------
# 7) Persistencia: ~/.cognia/flujos/<nombre>.json (COGNIA_FLUJOS_DIR en tests).
# ---------------------------------------------------------------------------

def dir_flujos() -> Path:
    base = os.environ.get("COGNIA_FLUJOS_DIR", "").strip()
    return Path(base) if base else (Path.home() / ".cognia" / "flujos")


def guardar_flujo(flujo: dict, nombre: str = None) -> str:
    """Escribe el flujo y devuelve la ruta (o '' si no se pudo). Escritura
    ATOMICA (tmp + os.replace): un flujo a medio escribir es un flujo que al
    cargar PARECE valido y no lo es."""
    flujo = dict(flujo or {})
    flujo.setdefault("version_formato", FORMATO_VERSION)
    slug = _slug(nombre or flujo.get("nombre") or "flujo")
    flujo["nombre"] = _s(flujo.get("nombre")) or slug
    destino = dir_flujos() / (slug + ".json")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(flujo, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(str(tmp), str(destino))
        return str(destino)
    except Exception:
        return ""


def cargar_flujo(nombre: str):
    """El flujo, o None si no existe / esta corrupto. Si la version de formato
    no coincide se devuelve igualmente con '_aviso': que hacer con el es
    politica del llamador, no de esta funcion."""
    ruta = dir_flujos() / (_slug(nombre) + ".json")
    try:
        flujo = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(flujo, dict):
        return None
    if flujo.get("version_formato") != FORMATO_VERSION:
        flujo["_aviso"] = ("formato %s != %s de este Cognia"
                           % (flujo.get("version_formato"), FORMATO_VERSION))
    return flujo


def listar_flujos() -> list:
    """[{nombre, descripcion, estado, n_pasos, n_params, ruta}] ordenado por
    nombre de fichero. Nunca lanza: un directorio inexistente son cero flujos."""
    out = []
    try:
        ficheros = sorted(dir_flujos().glob("*.json"))
    except Exception:
        return out
    for f in ficheros:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if not isinstance(d.get("pasos"), list):
            # cognia/flujos/examen.py guarda su indice (indice.json) en el MISMO
            # directorio, y el glob de *.json lo listaba como si fuera una
            # receta: "/receta lista" mostraba una fila fantasma llamada
            # 'indice' con 0 pasos. Un flujo SIN lista de pasos no es un flujo.
            continue
        out.append({
            "nombre": _s(d.get("nombre")) or f.stem,
            "descripcion": _s(d.get("descripcion")),
            "estado": _s(d.get("estado")),
            "n_pasos": len(d.get("pasos") or []),
            "n_params": len(d.get("params") or []),
            "ruta": str(f),
        })
    return out
