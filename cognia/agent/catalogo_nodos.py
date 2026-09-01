# -*- coding: utf-8 -*-
"""
cognia/agent/catalogo_nodos.py
==============================
La PALETA del editor visual de flujos: en que cajon cae cada tool de Cognia,
de que color se pinta y que parametros pide.

POR QUE EXISTE (2026-08-29)
---------------------------
El editor de flujos necesita ofrecer nodos para arrastrar. Las tools de
Cognia son 70 por defecto y 133 con TODAS las familias encendidas (medido
hoy: 126 con las 14 familias de `harness/familias.py` + 7 mas con
COGNIA_TX=1), y llegan de `tools.catalogo_schemas()` como una lista plana
ordenada alfabeticamente: `abrir`, `anotar`, `arbol`, ... Una paleta plana
de 133 elementos es inservible.

Este modulo es UNA SOLA TABLA DE DATOS (`CATEGORIAS`) y todo lo demas
derivado de ella. Ni logica de UI, ni HTML, ni fetch: solo la clasificacion
y los colores, para que el servidor (`flujoteca_editor`) los sirva por
`/api/catalogo` y el HTML (`editor_html`) los pinte.

POR QUE PYTHON Y NO UNA TABLA EMBEBIDA EN EL HTML
-------------------------------------------------
Las tools disponibles dependen de `familias.estado()` y de la identidad
activa: congelar el catalogo dentro de un HTML estatico deja la paleta
desincronizada en cuanto el dueno activa una familia. Se sirve en vivo.

LAS REGLAS DE CLASIFICACION (las mismas que harness/ayuda.py)
-------------------------------------------------------------
El patron mas largo gana; un nombre exacto le gana a un prefijo de la misma
longitud; el empate lo rompe el orden de `CATEGORIAS`; y NINGUNA tool se
pierde: la que no encaje cae en `otros`. Es literalmente el peso
`(len(patron), exacto, -orden)` de `ayuda.clasificar`, para que el repo
tenga UNA regla de clasificacion y no dos parecidas.

QUE SE COMPROBO CONTRA EL REGISTRO REAL (no se adivino ni un nombre)
--------------------------------------------------------------------
La tabla se verifico volcando `tools.TOOLS` con las 14 familias activadas y
COGNIA_TX=1: 133 nombres, 0 en `otros`. Los tres unicos huerfanos de la
tabla del plan eran `render_aprox`, `atribuir_fallo` y `reejecutar_etapa`,
que son LCD sin el prefijo `escena_` (viven en `_OPTIN_NOMBRES` con flag
COGNIA_LCD): estan dados de alta a mano en la categoria `escena`.

DOS CATEGORIAS MAS QUE EN EL PLAN, Y POR QUE
---------------------------------------------
El plan metia `escena_*` (37 tools), `pantalla_*` (7) e imagen/voz/musica/3D
(8) en un solo cajon `medios` de 52 entradas. Un cajon de 52 es exactamente
el problema que esta paleta viene a resolver -- el mismo tope de 25 por cajon
que se impuso `harness/ayuda.py` con los 240 comandos -- y ademas mezcla tres
cosas que el dueno no confunde: mover el raton no es generar una imagen.
Se separan `escena` ("Escenas 3D") y `pantalla` ("Pantalla y raton");
`medios` se queda con imagen, voz, musica y 3D. Ningun id del plan cambia
de nombre ni de color.

POR QUE `mensaje_bot` VA EN `ia` Y NO EN UN CAJON "BOTS" PROPIO
---------------------------------------------------------------
Los bots son un subsistema entero de la casa (/bots con perfiles aislados,
ALMA, chat canonico, rutinas y mensajeria), pero de todo eso solo UNA cosa es
una tool: `mensaje_bot`. Un cajon propio seria un cajon de uno, y ademas
VACIO casi siempre: `paleta()` no esconde las categorias sin nodos (eso lo
decide el cliente), y `mensaje_bot` solo existe mientras el proceso corre
dentro del turno de un bot. Es literalmente el "cajon muerto" que prohibe
`test_ninguna_categoria_esta_vacia_contra_el_registro_real`. Encima obligaria
a un `icono` nuevo, y `editor_html.ICONOS` solo dibuja los que conoce: uno
que no este cae a la caja gris, o sea el mismo aspecto de "Otros" que se
venia a quitar.

Mandar un mensaje a otro bot es hablarle a OTRO AGENTE, que es lo que ya hace
`delegar_subtarea` en este mismo cajon. El nombre pasa de "IA y agente" a
"IA, agentes y bots" para que el dueno que acaba de hacer `/bots chat <bot>`
sepa donde mirar: los nombres de categoria son para humanos.

LO QUE SE ESCAPA DE LA TABLA POR DISENO (y por que no se tapa)
--------------------------------------------------------------
Las tools que el propio agente fabrica con `crear_herramienta` entran en
`TOOLS` con un nombre ARBITRARIO (`tool_synthesis._NAME_RE` solo exige
[a-z][a-z0-9_]{2,40}) y `cli` las carga al arrancar
(`load_generated_tools()`). Ninguna tabla por nombre puede clasificarlas:
caen en `otros`, que es exactamente para lo que existe `OTROS` -- ninguna
tool se pierde. Hoy hay CERO en esta maquina. Darles cajon propio exigiria
que `categoria_de` mirara la spec del registry (llevan `tier`) y no solo el
nombre, o sea cambiar la firma publica; hasta que haya una sola tool
generada que lo justifique, se deja dicho en vez de inventado.

LA FORMA DEL NODO NO SALE DE LA CATEGORIA
-----------------------------------------
Sale de tres banderas de render que dependen del GRAFO, no del catalogo:

  - `trigger`: el nodo no tiene padres. Cognia no tiene tools disparadoras
    y seria deshonesto inventarlas, asi que la bandera es una propiedad
    topologica. 96x96, sin puerto de entrada, rayo a la izquierda.
  - `configurable`: el nodo tiene >= 2 hijos (`len(wires) >= 2`). 256x96,
    icono a la izquierda, etiquetas de salida.
  - `default`: el resto. 96x96, radius 12.

Y el CONTROL DE FLUJO en Cognia no son tools: son campos del nodo
(`saltar_si`, `reintentos`, `timeout_s`, `{{id}}`). Se pintan como badges y
se editan en el panel de propiedades; la seccion "Control" de la paleta NO
anade nodos, anade esos campos al nodo seleccionado.

Color SOLO en el icono; fondo y borde neutros (regla de n8n). Cada categoria
lleva `color` (tema claro) y `color_osc` (tema oscuro), ambos hex de 7 chars,
tomados de los 26 tokens `--node--icon--color--*` de n8n.

`danger` SALE DEL REGISTRO, NO DE UNA LISTA A MANO
---------------------------------------------------
Son las 12 tools que llevan `danger=True` en su decorador `@tool(...)`:
borrar_archivo, mover_archivo, ejecutar_fondo, matar_proceso, mcp,
crear_herramienta, revertir_herramienta, deshacer_edicion y los cuatro
git_ que escriben. `ejecutar` NO esta marcada aunque parezca la mas
peligrosa: su compuerta es otra (la lista de comandos peligrosos dentro de
la propia tool). Copiar aqui una lista a mano se desincronizaria en la
primera tool nueva; se lee `spec["danger"]` y punto.

CONTRATO (plan, FASE 0 y PEDIDO 3.4)
-------------------------------------
Firmas publicas:

    CATEGORIAS: tuple[dict, ...]
    categoria_de(tool: str) -> str
    catalogo(allowed=None) -> list[dict]
    paleta() -> dict

Forma de cada entrada de `CATEGORIAS`:

    {"id", "nombre", "color", "color_osc", "icono",
     "tools": (...nombres exactos...), "prefijos": (...opcional...)}

Forma de cada nodo de `catalogo()`:

    {"nombre", "descripcion", "categoria", "color", "color_osc", "icono",
     "danger", "familia", "flag", "activa", "modelo", "modelo_color",
     "params": [{"nombre", "tipo", "requerido", "descripcion", "clave"}]}

`allowed` (iterable de nombres o None) FILTRA la lista, con la misma
semantica que `tools.catalogo_schemas(allowed)` -- una sola convencion en el
repo para la misma palabra. `activa` es cosa aparte: dice si la familia de
esa tool esta encendida, para que el editor la pinte apagada con su flag al
lado en vez de esconderla (ocultar no es desactivar).

NADA DE AQUI EXPLOTA
---------------------
`familias.estado()` importa modulos opcionales y `oficina.identidad` puede
no estar: los dos cruces van envueltos y caen a un default honesto (`activa`
por la variable de entorno, `modelo` vacio). Un catalogo que revienta deja
al editor sin paleta y sin motivo visible, que es el modo de fallo de la
casa.
"""
from __future__ import annotations

import os
import re

__all__ = ["CATEGORIAS", "OTROS", "categoria_de", "catalogo", "paleta"]


# ---------------------------------------------------------------------------
# LA TABLA. Todo lo demas es derivado.
# ---------------------------------------------------------------------------
# Nombres pensados para el DUENO, no para el programador: "Archivos: leer"
# antes que "io", "Decisiones y bitacora" antes que "TX". `icono` es solo un
# NOMBRE corto; los SVG los dibuja editor_html.
CATEGORIAS: tuple = (
    # PRIMERA a proposito: es por donde EMPIEZA un flujo. Son las dos tools
    # de ENTRADA (PLAN2, PEDIDO 3): `prompt` es la variable -- el argumento de
    # `/flujoteca ejecutar <nombre> [prompt]` la pisa -- y `prompt_fijo` es la
    # constante, que ignora ese argumento y lo avisa. El MODO vive en el
    # nombre de la tool y no en un campo nuevo del nodo porque `tool` esta en
    # la whitelist de `flujo_ia.sanear_flujo` y en la tupla de 7 campos de
    # `flujoteca.comparar`: un `prompt_modo` desapareceria en silencio en la
    # primera edicion conversacional (medido) y no saldria nunca en el diff.
    # Las registra `flows.register()` (agente B); hasta entonces el cajon sale
    # vacio, que es exactamente lo que ya le pasa a las familias apagadas.
    # `icono` REUSA "sparkles" (que ya dibuja editor_html.ICONOS) para no
    # tener que tocar el HTML: los tests exigen id y nombre unicos, no icono.
    {"id": "entrada", "nombre": "Entrada del flujo",
     "color": "#e6a700", "color_osc": "#ffc933", "icono": "sparkles",
     "tools": ("prompt", "prompt_fijo")},

    {"id": "lectura", "nombre": "Archivos: leer",
     "color": "#3a42e9", "color_osc": "#898fff", "icono": "file",
     "tools": ("leer_archivo", "leer_lote", "listar", "arbol",
               "contar_lineas", "buscar", "buscar_ficheros",
               "json_validar", "py_validar")},

    {"id": "escritura", "nombre": "Archivos: escribir",
     "color": "#2fb67c", "color_osc": "#4fd39a", "icono": "pen",
     "tools": ("escribir_archivo", "editar_archivo", "apendar_archivo",
               "copiar_archivo", "mover_archivo", "crear_directorio",
               "borrar_archivo"),
     # La familia `documento` (agent/documento_tools.py) entro al registro sin
     # entrada aqui y sus siete tools caian al cajon "Otros" en cuanto se
     # encendia (lo caza el test de huerfanas). Van con la escritura de
     # ficheros, que es lo que hacen, y no en una categoria propia: una
     # categoria cuya familia viene apagada es un cajon muerto, que es
     # justo lo que prohibe test_ninguna_categoria_esta_vacia.
     "prefijos": ("doc_",)},

    {"id": "codigo", "nombre": "Codigo y repositorio",
     "color": "#ff9922", "color_osc": "#ffb966", "icono": "code",
     "tools": ("generar_codigo", "repo_map", "code_grafo", "contratos",
               "tests", "docs_repo", "preguntar_repo", "docs_libreria",
               "buscar_en_repo", "repo_a_prompt", "crear_herramienta",
               "revertir_herramienta"),
     "prefijos": ("git_",)},

    {"id": "ejecucion", "nombre": "Ejecutar y procesos",
     "color": "#e44d26", "color_osc": "#ff7755", "icono": "terminal",
     "tools": ("ejecutar", "ejecutar_fondo", "ver_salida", "matar_proceso",
               "procesos", "abrir")},

    {"id": "pantalla", "nombre": "Pantalla y raton",
     "color": "#772244", "color_osc": "#d4718f", "icono": "monitor",
     "tools": (),
     "prefijos": ("pantalla_",)},

    {"id": "web", "nombre": "Web e investigacion",
     "color": "#5699ff", "color_osc": "#7ab4ff", "icono": "globe",
     "tools": ("http_get", "web_buscar", "web_abrir", "consultar_oraculo")},

    {"id": "memoria", "nombre": "Memoria y notas",
     "color": "#9b6dd5", "color_osc": "#b48ce4", "icono": "brain",
     "tools": ("recordar", "memorizar", "cuaderno", "anotar", "notas",
               "resumir", "kg_buscar", "kg_agregar")},

    {"id": "ia", "nombre": "IA, agentes y bots",
     "color": "#ea4b71", "color_osc": "#f85d82", "icono": "sparkles",
     # `mensaje_bot` NO llega por flag: la registra en caliente
     # `tools.sincronizar_mensaje_bot()` cuando hay bot activo (COGNIA_BOT), y
     # `cli._run_agent_task` la llama al arrancar CADA corrida. Por eso se
     # escapo de esta tabla: en un pytest en frio la tool no existe. El cajon
     # es este y no uno propio -- ver "POR QUE `mensaje_bot` VA EN `ia`".
     "tools": ("delegar_subtarea", "plan", "crear_flujo", "ejecutar_flujo",
               "workflow", "buscar_herramientas", "vlm_mirar", "skill_leer",
               "tarea_estado", "bitacora_buscar", "mensaje_bot")},

    {"id": "contexto", "nombre": "Contexto largo",
     "color": "#00b7bc", "color_osc": "#3fd0d4", "icono": "layers",
     "tools": ("recuperar",),
     "prefijos": ("ctx_", "rlm_")},

    {"id": "medios", "nombre": "Imagen, sonido y 3D",
     "color": "#e91e63", "color_osc": "#ff4d80", "icono": "image",
     "tools": (),
     "prefijos": ("imagen_", "voz_", "musica_", "tresd_")},

    {"id": "escena", "nombre": "Escenas 3D",
     "color": "#8287eb", "color_osc": "#a9adf5", "icono": "cube",
     # render_aprox / atribuir_fallo / reejecutar_etapa son LCD sin prefijo:
     # viven en tools._OPTIN_NOMBRES con flag COGNIA_LCD.
     "tools": ("render_aprox", "atribuir_fallo", "reejecutar_etapa"),
     "prefijos": ("escena_",)},

    {"id": "horizonte", "nombre": "Decisiones y bitacora",
     "color": "#7d7d87", "color_osc": "#a5a5ad", "icono": "book",
     "tools": ("decidir", "afirmar", "pendiente", "resolver", "leccion"),
     "prefijos": ("libro_",)},

    {"id": "util", "nombre": "Utilidades",
     "color": "#54b8c9", "color_osc": "#79cbd9", "icono": "tool",
     "tools": ("calcular", "fecha", "mcp", "mcp_herramientas",
               "deshacer_edicion")},
)

# Cajon de respaldo: ninguna tool se pierde.
OTROS: dict = {"id": "otros", "nombre": "Otros",
               "color": "#7d7d87", "color_osc": "#a5a5ad", "icono": "box",
               "tools": (), "prefijos": ()}

_ENCENDIDO = ("1", "on", "true", "yes")


# ---------------------------------------------------------------------------
# Clasificacion
# ---------------------------------------------------------------------------
def _compilar_patrones() -> list:
    """[(patron, es_prefijo, id_categoria, orden)] listo para _clasificar()."""
    fuera = []
    for orden, cat in enumerate(CATEGORIAS):
        for nombre in cat.get("tools") or ():
            fuera.append((nombre, False, cat["id"], orden))
        for pref in cat.get("prefijos") or ():
            fuera.append((pref, True, cat["id"], orden))
    return fuera


_PATRONES = _compilar_patrones()


def _clasificar(nombre: str, patrones) -> str:
    """El nucleo de la regla, aislado para poder probarlo con patrones falsos.

    Peso `(len(patron), exacto, -orden)`: el patron mas LARGO gana; a igual
    longitud el exacto le gana al prefijo; a igual todo, la categoria que
    aparece antes en CATEGORIAS.
    """
    n = (nombre or "").strip()
    if not n:
        return OTROS["id"]
    mejor_peso, mejor_cat = None, None
    for pat, es_pref, cat, orden in patrones:
        casa = n.startswith(pat) if es_pref else (n == pat)
        if not casa:
            continue
        peso = (len(pat), 0 if es_pref else 1, -orden)
        if mejor_peso is None or peso > mejor_peso:
            mejor_peso, mejor_cat = peso, cat
    return mejor_cat if mejor_cat is not None else OTROS["id"]


def categoria_de(tool: str) -> str:
    """El id de categoria de una tool. Nunca vacio: cae en "otros".

    El patron mas largo gana y el nombre exacto le gana al prefijo, para que
    `ctx_grep` acabe en `contexto` y `buscar_en_repo` en `codigo` aunque
    `buscar` sea de `lectura`.
    """
    return _clasificar(tool, _PATRONES)


_POR_ID = {c["id"]: c for c in CATEGORIAS}
_POR_ID[OTROS["id"]] = OTROS


def _cat(cat_id: str) -> dict:
    return _POR_ID.get(cat_id, OTROS)


# ---------------------------------------------------------------------------
# Descripcion de UNA linea
# ---------------------------------------------------------------------------
# Dos formas conviven en el registro: la `desc` rica (varias frases) y el
# `doc` de una linea con la plantilla de uso delante:
#     "arbol <directorio>            -- arbol de archivos (2 niveles)"
# De la segunda interesa lo que va DESPUES del guion doble.
_RX_DOC = re.compile(r"^\S+.*?\s--\s+(.+)$")
_ANCHO = 150


def _primera_frase(texto: str) -> str:
    """La primera frase, sin cortar dentro de un parentesis ni un corchete."""
    hondo = 0
    for i, ch in enumerate(texto):
        if ch in "([":
            hondo += 1
        elif ch in ")]":
            hondo = max(0, hondo - 1)
        elif ch == "." and hondo == 0:
            if i + 1 >= len(texto):
                return texto[:i + 1]
            if texto[i + 1] == " ":
                return texto[:i + 1]
    return texto


def _una_linea(nombre: str, descripcion: str) -> str:
    """Una sola linea util para la tarjeta de la paleta."""
    d = " ".join(str(descripcion or "").split())
    if not d:
        return ""
    if nombre and d.startswith(nombre):
        m = _RX_DOC.match(d)
        if m:
            d = m.group(1).strip()
    frase = _primera_frase(d)
    # Una frase de tres palabras no dice nada: se le pega la siguiente.
    if len(frase) < 40 and len(frase) < len(d):
        resto = _primera_frase(d[len(frase):].lstrip())
        frase = (frase + " " + resto).strip()
    if len(frase) > _ANCHO:
        corte = frase.rfind(" ", 0, _ANCHO)
        frase = frase[:corte] if corte > 40 else frase[:_ANCHO]
        frase = frase.rstrip(" ,;:.") + "..."
    return frase


# ---------------------------------------------------------------------------
# Cruces con el resto del repo (ninguno puede tumbar el catalogo)
# ---------------------------------------------------------------------------
def _flag_activo(flag: str) -> bool:
    return os.environ.get(flag, "").strip().lower() in _ENCENDIDO


# Flags opt-in que NO son de ninguna familia de `harness/familias.py` pero SI
# tienen comando propio en el REPL. Sin esto, la paleta le diria al dueno
# "pon COGNIA_TX=1 y reinicia" cuando la casa tiene `/tx on`, que ademas
# GUARDA el flag en la config (ver el final de cognia/agent/tools.py).
_COMANDO_DE_FLAG = {"COGNIA_TX": "/tx on"}
# Y que es cada uno, para el tooltip del cajon: las familias lo traen en su
# campo `que`, estos no tienen quien se lo cuente.
_QUE_DE_FLAG = {
    "COGNIA_TX": "agente de horizonte largo: decisiones, afirmaciones, "
                 "pendientes, lecciones y el libro",
    "COGNIA_MCP": "las herramientas de los servidores MCP que ya tienes "
                  "configurados en otros clientes de IA",
}


def _flag_encendido(flag: str) -> bool:
    """Si ese flag esta puesto, preguntandoselo a quien tiene la verdad.

    Para COGNIA_TX la verdad NO esta en el entorno: `/tx on` lo guarda en la
    config y `tools.py` decide con `cognia.tx.flag.activo()`. Mirar solo
    `os.environ` haria que la paleta dijera "apagada" mientras el REPL dice
    ACTIVO -- exactamente la contradiccion que este encargo viene a quitar.
    """
    if flag == "COGNIA_TX":
        try:
            from cognia.tx.flag import activo as _activo_tx
            return bool(_activo_tx())
        except Exception:
            pass
    return _flag_activo(flag)


def _casa_con(cat: dict, prefijo: str) -> bool:
    """True si las tools con ese prefijo caen en ese cajon de `CATEGORIAS`.

    Se mira la tabla, no un mapa a mano: el prefijo de una familia
    (`familias.FAMILIAS[...]["prefijo"]`) casa con un cajon o porque el cajon
    declara ese mismo prefijo (`pantalla_`, `escena_`, `imagen_`...) o porque
    alguna de sus tools declaradas empieza por el (`web_buscar` para la
    familia `navegador`, `vlm_mirar` para `vlm`). Asi una familia nueva cae
    sola en su sitio y esta funcion no hay que tocarla.
    """
    for pref in cat.get("prefijos") or ():
        if pref.startswith(prefijo) or prefijo.startswith(pref):
            return True
    for nombre in cat.get("tools") or ():
        if nombre.startswith(prefijo):
            return True
    return False


def _fuentes_por_categoria() -> dict:
    """{id_categoria: [fuente, ...]} -- QUE enciende cada cajon de la paleta.

    POR QUE EXISTE (2026-08-29, prueba e2e del editor). Con la instalacion
    por defecto, 4 de los 13 cajones (`pantalla`, `medios`, `escena`,
    `horizonte`) salen VACIOS porque sus familias son opt-in y estan
    apagadas: el editor sirve 70 tools de las ~96 posibles. La paleta los
    pintaba vacios, o sea un cajon mudo que no dice ni que existe algo mas ni
    como conseguirlo. Con esto, cada categoria sabe que familia le falta, con
    que flag se enciende y con que COMANDO de la casa (`/activar <familia>`,
    `/tx on`), y el cliente puede pintarla plegada y atenuada con el texto.

    Cada fuente: {"familia", "flag", "que", "comando", "encendida",
    "instalada"}. `familia` va vacia en los opt-in que no son familia.

    NADA DE AQUI EXPLOTA: si `harness.familias` o `agent.tools` no importan,
    se devuelve lo que se haya podido reunir (o {}) y la paleta se pinta como
    siempre. Un catalogo que revienta deja al editor sin paleta, que es peor
    que un cajon sin explicacion.
    """
    fuera: dict = {}

    def _apunta(cat_id: str, fuente: dict) -> None:
        filas = fuera.setdefault(cat_id, [])
        # Una familia y un opt-in pueden compartir flag (COGNIA_LCD llega por
        # la familia `escena` y por `render_aprox`): manda el primero, que es
        # el que trae nombre de familia.
        if any(f["flag"] == fuente["flag"] for f in filas):
            return
        filas.append(fuente)

    # 1) Las familias de verdad, con su nombre y su flag reales.
    try:
        from cognia.harness import familias as _familias
        tabla = dict(_familias.FAMILIAS)
        por_nombre = {f.get("familia"): f for f in (_familias.estado() or ())}
    except Exception:
        tabla, por_nombre = {}, {}
    for nombre, fam in tabla.items():
        try:
            flag = fam.get("flag", "")
            if not flag:
                continue
            fila = por_nombre.get(nombre) or {}
            fuente = {
                "familia": nombre,
                "flag": flag,
                "que": fam.get("que", ""),
                "comando": "/activar " + nombre,
                "encendida": bool(fila.get("encendida", _flag_encendido(flag))),
                "instalada": bool(fila.get("instalada", True)),
            }
            destinos = set()
            pref = fam.get("prefijo")
            if pref:
                for cat in CATEGORIAS:
                    if _casa_con(cat, pref):
                        destinos.add(cat["id"])
            for t in fam.get("nombres") or ():
                destinos.add(categoria_de(t))
            for cid in destinos:
                if cid != OTROS["id"]:
                    _apunta(cid, fuente)
        except Exception:
            continue

    # 2) Los opt-in que NO son familia (COGNIA_TX, COGNIA_MCP): salen de los
    #    nombres que la propia tabla de arriba declara, preguntandole a
    #    `tools.flag_de_optin` -- la misma fuente que usa `catalogo()`.
    try:
        from cognia.agent import tools as _tools
        flag_de = _tools.flag_de_optin
    except Exception:
        flag_de = None
    if flag_de is not None:
        for cat in CATEGORIAS:
            for nombre in cat.get("tools") or ():
                try:
                    flag = flag_de(nombre) or ""
                except Exception:
                    flag = ""
                if not flag:
                    continue
                _apunta(cat["id"], {
                    "familia": "", "flag": flag,
                    "que": _QUE_DE_FLAG.get(flag, ""),
                    "comando": _COMANDO_DE_FLAG.get(flag, ""),
                    "encendida": _flag_encendido(flag),
                    "instalada": True,
                })
    return fuera


def _como_encender(apagadas: list) -> str:
    """La linea que ve el dueno: el comando de la casa, no el flag pelado."""
    if not apagadas:
        return ""
    if len(apagadas) == 1:
        f = apagadas[0]
        if f.get("comando") and f.get("flag"):
            return ("apagada: se enciende con %s (o %s=1 antes de arrancar)"
                    % (f["comando"], f["flag"]))
        return "apagada: se enciende con %s" % (
            f.get("comando") or ((f.get("flag") or "?") + "=1"))
    # Varias familias en el mismo cajon (imagen, voz, musica y 3D caen todas
    # en "Imagen, sonido y 3D"): solo los comandos, o la linea no cabe en un
    # panel de 320 px.
    trozos = [f.get("comando") or ((f.get("flag") or "?") + "=1")
              for f in apagadas]
    return ("apagadas: se encienden con " + ", ".join(trozos[:-1]) +
            " o " + trozos[-1])


def _mapa_familias() -> dict:
    """{tool: {"familia", "flag", "encendida"}} desde `familias.estado()`.

    Si el modulo no importa o `estado()` revienta se devuelve {} y cada tool
    resuelve `activa` por su variable de entorno: el editor sigue teniendo
    paleta, que es lo que importa.
    """
    fuera: dict = {}
    try:
        from cognia.harness import familias as _familias
        filas = _familias.estado()
    except Exception:
        return fuera
    try:
        for fila in filas or ():
            fam = fila.get("familia", "")
            flag = fila.get("flag", "")
            encendida = bool(fila.get("encendida"))
            for t in fila.get("tools") or ():
                fuera[t] = {"familia": fam, "flag": flag,
                            "encendida": encendida}
    except Exception:
        return {}
    return fuera


def _colores_de_modelo() -> dict:
    """{key: color} de la oficina, o {} si no esta. Solo decora el borde."""
    try:
        from cognia.oficina import identidad as _ident
        return {m["key"]: m.get("color", "") for m in _ident.roster()}
    except Exception:
        return {}


def _modelo_de(nombre: str) -> str:
    try:
        from cognia.oficina import identidad as _ident
        return _ident.recomendar_modelo(nombre) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def catalogo(allowed=None) -> list[dict]:
    """Las tools registradas como nodos pintables, con categoria y params.

    `allowed` (iterable de nombres o None) filtra, igual que en
    `tools.catalogo_schemas`. `activa` dice si la familia de la tool esta
    encendida: el editor pinta las apagadas en gris con su flag al lado en
    vez de esconderlas, porque ocultar no es desactivar.
    """
    from cognia.agent import tools as _tools

    permitidos = None if allowed is None else set(allowed)
    try:
        esquemas = _tools.catalogo_schemas(permitidos)
    except Exception:
        esquemas = []

    fam = _mapa_familias()
    colores = _colores_de_modelo()

    nodos = []
    for esq in esquemas:
        nombre = esq.get("nombre", "")
        cat_id = categoria_de(nombre)
        cat = _cat(cat_id)
        info = fam.get(nombre)
        try:
            flag = _tools.flag_de_optin(nombre) or ""
        except Exception:
            flag = ""
        if not flag and info:
            flag = info.get("flag", "")
        if info is not None:
            activa = bool(info.get("encendida"))
        elif flag:
            activa = _flag_activo(flag)
        else:
            activa = True
        modelo = _modelo_de(nombre)
        nodos.append({
            "nombre": nombre,
            "descripcion": _una_linea(nombre, esq.get("descripcion", "")),
            "categoria": cat_id,
            "categoria_nombre": cat["nombre"],
            "color": cat["color"],
            "color_osc": cat["color_osc"],
            "icono": cat["icono"],
            "danger": bool(esq.get("danger")),
            "familia": (info or {}).get("familia", ""),
            "flag": flag,
            "activa": activa,
            "modelo": modelo,
            "modelo_color": colores.get(modelo, ""),
            "params": [dict(p) for p in esq.get("params") or ()],
        })
    nodos.sort(key=lambda n: n["nombre"])
    return nodos


def paleta() -> dict:
    """Las categorias con sus nodos ya agrupados, en orden de `CATEGORIAS`.

    Es lo que consume `/api/catalogo`. Las categorias sin ningun nodo activo
    NO se ocultan aqui: eso lo decide el cliente, que es quien sabe si el
    dueno pidio ver solo lo encendido. `otros` solo aparece si de verdad
    cayo algo dentro.

    Cada categoria trae ademas de que depende (2026-08-29):

        "fuentes":      [{"familia","flag","que","comando","encendida",
                          "instalada"}]  -- que familias la llenan
        "apagada":      True si esta VACIA y ademas su(s) familia(s) estan
                        apagadas. Vacia y sin fuentes apagadas no es
                        "apagada": es que no hay nada que encender.
        "como_encender": la linea lista para pintar ("apagada: se enciende
                        con /activar pantalla (o COGNIA_SCREEN=1 antes de
                        arrancar)"), vacia si no hay nada apagado.

    Con la instalacion por defecto eso son 4 cajones de 13. El cliente los
    pinta plegados y atenuados con esa linea: el dueno ve QUE MAS PODRIA
    TENER en vez de un cajon mudo.
    """
    nodos = catalogo()
    por_cat: dict = {}
    for n in nodos:
        por_cat.setdefault(n["categoria"], []).append(n)
    try:
        fuentes_de = _fuentes_por_categoria()
    except Exception:
        fuentes_de = {}

    cats = []
    orden = list(CATEGORIAS) + [OTROS]
    for cat in orden:
        propios = por_cat.get(cat["id"], [])
        if cat["id"] == OTROS["id"] and not propios:
            continue
        fuentes = fuentes_de.get(cat["id"], [])
        apagadas = [f for f in fuentes if not f.get("encendida")]
        # Un cajon con tools dentro NO se marca apagado aunque le falte una
        # familia: `ia` tiene 11 nodos vivos y `vlm` apagada, y taparlo de
        # "apagada" seria mentir. La marca es para el cajon VACIO.
        apagada = bool(apagadas) and not propios
        cats.append({
            "id": cat["id"],
            "nombre": cat["nombre"],
            "color": cat["color"],
            "color_osc": cat["color_osc"],
            "icono": cat["icono"],
            "n": len(propios),
            "n_activas": sum(1 for n in propios if n["activa"]),
            "fuentes": fuentes,
            "apagada": apagada,
            "como_encender": _como_encender(apagadas) if apagada else "",
            "nodos": propios,
        })
    return {"total": len(nodos),
            "activas": sum(1 for n in nodos if n["activa"]),
            "categorias": cats,
            "nodos": nodos}


if __name__ == "__main__":  # pragma: no cover - inspeccion a mano
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = paleta()
    print("%d tools, %d activas, %d cajones"
          % (p["total"], p["activas"], len(p["categorias"])))
    for c in p["categorias"]:
        print("  %-22s %-24s %2d  %s"
              % (c["id"], c["nombre"], c["n"],
                 ", ".join(n["nombre"] for n in c["nodos"][:6])))
