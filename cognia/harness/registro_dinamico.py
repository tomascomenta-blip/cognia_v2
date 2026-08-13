# -*- coding: utf-8 -*-
"""Registro DINAMICO de herramientas: catalogo chico + ``buscar_herramientas``.

POR QUE (2026-08-12). En este repo esta MEDIDO (A/B 2026-07-25, n=4+4) que un
catalogo de 46 herramientas baja el camino feliz de 4.25/5 a 2.5/5: mas tools no
es mas capacidad, es mas distraccion. La respuesta actual es recortar a mano a
12 ``CORE_TOOLS`` (tools.py:82) — barato, pero ESCONDE capacidad real: hay ~200
herramientas registradas que el modelo nunca ve, y las invisibles no existen.

La mecanica destilada de Anthropic tool-search / smolagents / MCP dinamico es la
tercera via: el modelo arranca con el catalogo CHICO mas una sola herramienta
``buscar_herramientas``; cuando le falta algo, busca por descripcion en lenguaje
natural y el harness le INYECTA los schemas de las 3-5 relevantes en el turno
siguiente. El catalogo CRECE BAJO DEMANDA en vez de nacer inflado.

TRADE-OFF (declarado, no escondido):
  - COSTE: una busqueda gasta UN PASO extra del presupuesto (turno de tool_call +
    turno de resultado) y agrega latencia; si el modelo no sabe QUE buscar, ese
    paso se pierde. El recall depende de que la descripcion de la tool y la
    consulta compartan vocabulario (BM25 lexico + una tabla de sinonimos
    es/en HECHA A MANO: lo que no esta en la tabla, no casa).
  - BENEFICIO: el catalogo anunciado se mantiene chico (base + <=MAX_ACTIVAS),
    que es justo la variable que el A/B mostro que manda.
  - EL CONTRAFACTUAL SE MIDE ANTES DE ADOPTAR: este modulo NO esta probado
    superior al catalogo completo. Antes de cablearlo al bucle hay que correr el
    A/B de tres brazos (CORE fijo / catalogo completo 46 / registro dinamico) con
    el camino feliz y n>=4 por brazo, contando el paso extra de la busqueda DENTRO
    del presupuesto. Sin ese numero esto es una hipotesis con codigo, nada mas.

Puro stdlib (re, math, json, hashlib, unicodedata). Determinista. No importa
``cognia.agent.tools``: el catalogo entra POR PARAMETRO como lista de dicts
``{nombre, descripcion, params, danger}`` (la forma exacta que ya devuelve
``catalogo_schemas()``), asi el indice se puede probar sin arrastrar el registry.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata

# Tope duro de herramientas activadas a la vez. El A/B dice que el tamano del
# catalogo anunciado es lo que degrada: si el modelo pudiera activar sin limite
# reconstruiria el catalogo inflado de a poco. 8 = margen sobre las 3-5 que
# devuelve una busqueda tipica, sin acercarse a las 46 del brazo malo.
MAX_ACTIVAS = 8

# BM25 clasico (Robertson/Sparck Jones). k1 satura el term-frequency (una tool
# que repite "archivo" 6 veces no vale 6 veces mas); b=0.75 normaliza por largo
# de descripcion, si no las tools con desc rica ganarian solo por ser largas.
K1 = 1.2
B = 0.75
# El nombre de la tool vale doble: "escribir_archivo" ES la mejor descripcion
# que tiene, y suele ser lo que el modelo tipea en la consulta.
PESO_NOMBRE = 2

_STOP = frozenset("""
a al algo ante antes bajo cada como con contra cual cuando de del desde donde dos
e el ella ellos en entre era es esa ese eso esta este esto ha hay la las le les lo
los mas me mi mucho muy no nos o os otra otro para pero poco por porque que quien
se sea si sin so sobre su sus tal te ti tu tus un una uno unos y ya
an and any are as at be but by can do does for from has have how in into is it its
of on or so than that the their then there these this to via was what when where
which who will with you your
""".split())

# Clases de equivalencia es/en + dominio. Se aplican tanto al INDEXAR como al
# CONSULTAR, asi "guardar texto en un fichero" alcanza a "escribir_archivo" y
# "ver que cambio en el repositorio" alcanza a "git_estado -- git status".
# LIMITE HONESTO: esta tabla es finita y hecha a mano (~20 clases); un par es/en
# que no este aca NO casa. Ampliarla es el mantenimiento previsible del modulo.
_CLASES = {
    "archivo": "archivo archivos fichero ficheros file files filename",
    "escribir": "escribir escribe escritura guardar guarda grabar volcar salvar "
                "sobrescribir sobrescribe write writes writing save saving",
    "texto": "texto textos text contenido contenidos content cadena string strings",
    "leer": "leer lee lectura read reads reading abrir abre open cargar",
    "buscar": "buscar busca busqueda busquedas search searching find finding grep "
              "encontrar localizar lookup query consulta",
    "ejecutar": "ejecutar ejecuta ejecucion correr corre run running execute exec "
                "comando comandos command commands shell terminal consola bash",
    "estado": "estado estados state status cambio cambios cambiado change changes "
              "changed modificado modificados modificacion pendiente pendientes "
              "untracked",
    "repositorio": "repositorio repositorios repo repos repository git versionado "
                   "commit commits rama branch",
    "diferencia": "diff diffs diferencia diferencias delta parche patch",
    "directorio": "directorio directorios carpeta carpetas folder folders dir dirs "
                  "directory ruta rutas path paths",
    "listar": "listar lista listado list listing enumerar mostrar muestra ls",
    "borrar": "borrar borra borrado eliminar elimina delete deleting remove rm "
              "suprimir",
    "test": "test tests testing pytest prueba pruebas testear suite unittest",
    "memoria": "memoria memorias memory recordar recuerda recuerdo remember episodica",
    "calcular": "calcular calcula calculo aritmetica aritmetico matematica math "
                "compute cuenta suma sumar restar multiplicar dividir division "
                "numero numeros number numbers expresion operacion",
    "web": "web internet navegador browser url urls http https online descargar red",
    "codigo": "codigo code funcion funciones function functions programa script "
              "programar implementar",
    "editar": "editar edita edicion edit editing modificar reemplazar reemplaza "
              "replace sustituir",
    "agregar": "agregar agrega anadir anade append apendar adjuntar final",
    "error": "error errores fallo fallos bug bugs excepcion exception traceback",
    "linea": "linea lineas line lines renglon",
    "fecha": "fecha fechas hora horas dia date time reloj",
}
# token -> canonico. Se construye una vez al importar.
_SINONIMO = {}
for _canonico, _palabras in _CLASES.items():
    for _p in _palabras.split():
        _SINONIMO[_p] = _canonico

# Divide camelCase/PascalCase ("gitEstado" -> git, Estado) y numeros.
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SEPARADOR = re.compile(r"[^0-9A-Za-z]+")


def _sin_acentos(s: str) -> str:
    """'descripción' -> 'descripcion' (el modelo tipea sin tildes la mitad de las veces)."""
    n = unicodedata.normalize("NFD", s)
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _stem(tok: str) -> str:
    """Stemming minimo de plural es/en. Deliberadamente tonto: solo plurales, y
    solo en tokens largos (recortar 'los'->'lo' o 'is'->'i' hace mas dano que bien)."""
    if len(tok) > 5 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) > 4 and tok.endswith("s"):
        return tok[:-1]
    return tok


def _canon(tok: str):
    """Token crudo -> forma canonica, o None si se descarta (stopword / muy corto).
    El sinonimo se consulta ANTES del stem (asi 'status' no se vuelve 'statu')
    y tambien DESPUES (asi 'cambios' -> 'cambio' -> 'estado')."""
    if len(tok) < 2 or tok in _STOP:
        return None
    if tok in _SINONIMO:
        return _SINONIMO[tok]
    s = _stem(tok)
    if s in _STOP:
        return None
    return _SINONIMO.get(s, s)


def tokenizar(texto: str) -> list:
    """Texto -> lista de tokens canonicos. Parte por no-alfanumerico (cubre el
    '_' de los nombres de tool), por camelCase, saca acentos, baja a minusculas,
    tira stopwords es/en y mapea sinonimos."""
    if not texto:
        return []
    fuera = []
    for trozo in _SEPARADOR.split(_sin_acentos(texto)):
        if not trozo:
            continue
        for pieza in _CAMEL.findall(trozo) or [trozo]:
            c = _canon(pieza.lower())
            if c:
                fuera.append(c)
    return fuera


def _entradas(catalogo) -> list:
    """Materializa el catalogo (acepta cualquier iterable, no solo listas) y tira
    lo que no sea dict.

    POR QUE materializar: ``indexar`` recorre el catalogo DOS veces (una para la
    huella y otra para indexar). Con un generador la segunda pasada salia vacia y
    el indice quedaba con 0 docs SIN error — el fallo silencioso exacto que este
    repo ya pago caro. Se consume una sola vez, aca.
    """
    return [e for e in (catalogo or ()) if isinstance(e, dict)]


def _estable(o):
    """Fallback de json.dumps para valores no serializables (un callable en el
    spec, p.ej.). Se rinde al NOMBRE DEL TIPO a proposito: ``str(funcion)`` trae
    la direccion de memoria y haria que la huella cambiara en cada proceso."""
    return f"<{type(o).__name__}>"


def huella_catalogo(catalogo) -> str:
    """Hash estable del catalogo ENTERO (todas las claves de cada entrada, no
    solo nombre+descripcion). Es la clave del cache: dos listas con el mismo
    contenido reusan el indice.

    POR QUE el spec entero: el indice guarda los specs y ``catalogo_efectivo``
    los INYECTA en el prompt. Hasheando solo nombre+descripcion, dos catalogos
    que difieren en ``params`` o en ``danger`` colisionaban y el cache devolvia
    el spec VIEJO — se le anunciaba al modelo una firma equivocada, y ``danger``
    es lo que decide si la tool pide confirmacion. Vale mas un cache miss que un
    schema mentido.
    """
    crudo = json.dumps(
        _entradas(catalogo),
        ensure_ascii=False, sort_keys=True, default=_estable,
    )
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()


# huella -> indice. Chico y acotado: el catalogo cambia poco (a lo sumo una
# variante por rol), no hace falta una LRU con maquinaria.
_CACHE: dict = {}
_CACHE_TOPE = 8


def indexar(catalogo) -> dict:
    """Construye (o recupera del cache) el indice BM25 del catalogo.

    ``catalogo``: iterable de dicts ``{nombre, descripcion, params, danger}``.
    Devuelve un dict plano: ``{"docs", "df", "n", "avgdl", "specs", "huella"}``.
    Entradas sin ``nombre`` (o que no sean dict) se ignoran; nombres repetidos,
    el ultimo gana. Los specs se guardan como COPIA PROFUNDA: el indice vive en
    un cache global y quien reciba un spec puede mutarlo sin envenenarlo.
    """
    catalogo = _entradas(catalogo)
    huella = huella_catalogo(catalogo)
    cacheado = _CACHE.get(huella)
    if cacheado is not None:
        return cacheado

    docs, df, specs = {}, {}, {}
    for entrada in catalogo:
        nombre = str(entrada.get("nombre") or "").strip()
        if not nombre:
            continue
        descripcion = str(entrada.get("descripcion") or "").strip()
        # El nombre entra PESO_NOMBRE veces y la descripcion una.
        toks = tokenizar(nombre) * PESO_NOMBRE + tokenizar(descripcion)
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        docs[nombre] = {"tf": tf, "dl": len(toks), "descripcion": descripcion}
        specs[nombre] = copy.deepcopy(entrada)
    for d in docs.values():
        for t in d["tf"]:
            df[t] = df.get(t, 0) + 1

    n = len(docs)
    total = sum(d["dl"] for d in docs.values())
    indice = {
        "docs": docs, "df": df, "n": n,
        "avgdl": (total / n) if n else 0.0,
        "specs": specs, "huella": huella,
    }
    if len(_CACHE) >= _CACHE_TOPE:
        _CACHE.clear()          # cache de tamano fijo: se vacia entero, sin politica
    _CACHE[huella] = indice
    return indice


def buscar(indice: dict, consulta: str, limite: int = 5, excluir=()) -> list:
    """Busca en el indice y devuelve ``[(nombre, score, descripcion), ...]``
    ordenado por score descendente (desempate alfabetico por nombre, para que la
    salida sea determinista y el prompt cachee).

    ``excluir``: nombres a saltar, para no gastar resultados en tools que el
    modelo YA tiene. Acepta un solo nombre como str (igual que ``activar``): sin
    eso, ``excluir="git_estado"`` se volvia ``set("git_estado")`` — un conjunto de
    LETRAS que no excluia nada y no se quejaba.
    OJO con el patron de llamada (medido sobre el registry real,
    50 tools): si se excluye el catalogo base A CIEGAS y la respuesta correcta
    ESTABA en la base, la busqueda devuelve los siguientes-mejores — ruido, justo
    lo que este modulo intenta evitar. Patron recomendado: buscar SIN excluir; si
    el mejor resultado ya esta en el catalogo anunciado, contestarle al modelo
    "ya la tenes: <nombre>" en vez de activar rellenos.
    Score 0 (ningun termino casa) NO se devuelve: es preferible decir "no hay"
    a inventar relevancia. ``limite=None`` devuelve todos los que puntuaron.
    """
    if not isinstance(indice, dict) or not indice.get("n"):
        return []
    terminos = tokenizar(consulta or "")
    if not terminos:
        return []
    if isinstance(excluir, str):
        excluir = [excluir]
    fuera = set(excluir or ())
    n, avgdl, df = indice["n"], indice["avgdl"] or 1.0, indice["df"]

    resultados = []
    for nombre, d in indice["docs"].items():
        if nombre in fuera:
            continue
        score = 0.0
        for t in set(terminos):
            f = d["tf"].get(t)
            if not f:
                continue
            # idf con suavizado: un termino en TODOS los docs aporta ~0.
            idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
            denom = f + K1 * (1.0 - B + B * (d["dl"] / avgdl))
            score += idf * (f * (K1 + 1.0)) / denom
        if score > 0.0:
            resultados.append((nombre, round(score, 4), d["descripcion"]))
    resultados.sort(key=lambda r: (-r[1], r[0]))
    if limite is None:
        return resultados
    return resultados[: max(0, int(limite))]


# ── sesion de catalogo activo ──────────────────────────────────────────
def nueva_sesion(indice: dict, max_activas: int = MAX_ACTIVAS) -> dict:
    """Sesion = dict plano ``{"indice", "activas": [nombres], "max"}``.
    ``activas`` esta en orden LRU: el PRIMERO es el mas viejo sin usar."""
    return {"indice": indice, "activas": [], "max": max(1, int(max_activas))}


def activas(sesion: dict) -> list:
    """Nombres activados, en orden LRU (mas viejo primero, mas reciente ultimo)."""
    return list(sesion.get("activas", []))


def activar(sesion: dict, nombres) -> dict:
    """Activa herramientas por nombre. Devuelve
    ``{"activadas", "desalojadas", "desconocidas"}``.

    POLITICA AL DESBORDAR (LRU, documentada): el tope es ``sesion["max"]``
    (MAX_ACTIVAS=8). Re-activar una ya activa la REFRESCA (pasa al final de la
    cola) sin ocupar cupo nuevo. Cuando entran mas de las que caben, se desaloja
    desde el frente — la menos recientemente activada — hasta respetar el tope.
    Si un solo lote trae mas de ``max`` nombres, se conservan los ULTIMOS ``max``
    del lote (los que el modelo pidio mas tarde) y el resto sale desalojado.
    Un nombre que no esta en el catalogo indexado NO se activa: vuelve en
    ``desconocidas`` (el harness debe decirselo al modelo, no fallar en silencio).
    """
    if isinstance(nombres, str):
        nombres = [nombres]
    # ``or {}`` y no ``get(..., {})``: una sesion creada con indice None (o con un
    # indice a medio construir) tiene que reportar 'desconocidas', no reventar.
    specs = (sesion.get("indice") or {}).get("specs") or {}
    cola = list(sesion.get("activas", []))
    tope = max(1, int(sesion.get("max", MAX_ACTIVAS)))
    activadas, desconocidas = [], []
    for nombre in nombres or ():
        nombre = str(nombre).strip()
        if not nombre:
            continue
        if nombre not in specs:
            desconocidas.append(nombre)
            continue
        if nombre in cola:
            cola.remove(nombre)          # refresco LRU: no consume cupo nuevo
        cola.append(nombre)
        if nombre not in activadas:
            activadas.append(nombre)
    desalojadas = []
    while len(cola) > tope:
        desalojadas.append(cola.pop(0))
    sesion["activas"] = cola
    return {"activadas": [a for a in activadas if a in cola],
            "desalojadas": desalojadas,
            "desconocidas": desconocidas}


def catalogo_efectivo(sesion: dict, base: list) -> list:
    """El catalogo que se le ANUNCIA al modelo = ``base`` + activadas.

    Devuelve lista de specs: primero las de ``base`` tal cual llegaron (el orden
    del prompt no debe bailar entre turnos: rompe el prefix-cache), despues las
    activadas en orden LRU. Una tool que ya esta en ``base`` no se duplica.
    Tamano maximo = len(base) + sesion["max"]. Las inyectadas son COPIAS
    PROFUNDAS: quien las toque no debe poder corromper el indice cacheado.
    """
    fuera = [t for t in (base or ()) if isinstance(t, dict)]
    ya = {str(t.get("nombre") or "") for t in fuera}
    specs = (sesion.get("indice") or {}).get("specs") or {}
    for nombre in sesion.get("activas", []):
        if nombre in ya:
            continue
        spec = specs.get(nombre)
        if spec is not None:
            fuera.append(copy.deepcopy(spec))
            ya.add(nombre)
    return fuera


# ── lo que se le devuelve al modelo ────────────────────────────────────
# La tool que va SIEMPRE en el catalogo base (misma forma que catalogo_schemas).
ESQUEMA_BUSCAR_HERRAMIENTAS = {
    "nombre": "buscar_herramientas",
    "descripcion": ("Busca herramientas que NO estan en tu catalogo actual, por "
                    "descripcion en lenguaje natural (ej: 'guardar texto en un "
                    "fichero'). Las mas relevantes quedan disponibles para el "
                    "paso siguiente. Usala cuando te falte una capacidad."),
    "params": [{"nombre": "consulta", "tipo": "string", "requerido": True,
                "descripcion": "que necesitas hacer, en tus palabras"}],
    "danger": False,
}


def texto_resultado_busqueda(resultados: list) -> str:
    """El RESULTADO que ve el modelo tras buscar. Sin adornos: una linea por
    tool (nombre + descripcion recortada a una linea) y la frase de que ya
    quedaron disponibles. Sin resultados, lo dice y sugiere reformular —
    el mensaje de error ES el prompt siguiente (misma idea que edit_block)."""
    if not resultados:
        return ("Sin herramientas que casen con esa busqueda. Reformula con otras "
                "palabras (que ACCION necesitas, no el nombre que imaginas) o "
                "resuelvelo con las que ya tenes.")
    lineas = []
    for nombre, _score, descripcion in resultados:
        una = " ".join(str(descripcion or "").split())
        if len(una) > 160:
            una = una[:157].rstrip() + "..."
        lineas.append(f"- {nombre}: {una}" if una else f"- {nombre}")
    cuerpo = "\n".join(lineas)
    cuantas = "1 herramienta" if len(resultados) == 1 else f"{len(resultados)} herramientas"
    return (f"{cuerpo}\n\nEsas {cuantas} YA quedaron disponibles: podes llamarlas "
            f"en el paso siguiente sin volver a buscar.")
