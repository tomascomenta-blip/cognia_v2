"""
cognia/agent/tool_schemas.py
============================
Schemas OpenAI de las tools del registry, para el tool-calling NATIVO (A2).

POR QUE EXISTE: el marco texto "ACCION: <tool> <args>" obligaba al modelo a
serializar argumentos en un string con separador '|' y al loop a parsearlo
por regex — con todo el andamiaje compensatorio (GBNF, structure_action,
few-shots) que eso exigio. Con tool-calling nativo el modelo emite JSON
tipado y el server lo parsea; este modulo traduce en las DOS direcciones:

  - ``schemas_para(allowed)``: registry TOOLS -> lista de schemas OpenAI
    (las tools mas usadas con parametros TIPADOS; el resto con un unico
    parametro ``args`` cuyo formato documenta la linea de ayuda de siempre).
  - ``args_legacy(nombre, argumentos)``: argumentos JSON del tool call ->
    el string de args que ``run_tool`` espera desde siempre. Asi las tools
    de cognia/agent/tools.py NO se tocan (WP2 es su dueno) y el camino
    legacy sigue funcionando identico.

'responder' NO es un schema: en regimen nativo el cierre es una respuesta
SIN tool calls (fin natural del bucle), no una pseudo-tool.
"""
from __future__ import annotations

import re

# Firmas de las tools que el registry NO declara (A4): mismo formato que
# _TIPADAS, en su propio modulo porque esas tools viven en archivos de otro
# paquete de trabajo y no se les puede tocar el decorador. Import directo (no
# perezoso): firmas.py es datos puros, no importa nada de aca -> sin ciclo.
from cognia.agent.firmas import FIRMAS


def _p(desc: str, tipo: str = "string") -> dict:
    return {"type": tipo, "description": desc}


# Tools con parametros tipados: (propiedades, requeridos, armador del string
# legacy). El armador reconstruye EXACTAMENTE el formato "a | b" que la tool
# parsea con re.split(r"\s*\|\s*", args, maxsplit=1) — por eso el contenido
# (que puede contener '|') siempre va ULTIMO.
_TIPADAS: dict = {
    "leer_archivo": (
        {"path": _p("ruta del archivo a leer")}, ["path"],
        lambda a: str(a.get("path", "")).strip(),
    ),
    "escribir_archivo": (
        {"path": _p("ruta del archivo (se crean los directorios)"),
         "contenido": _p("contenido COMPLETO del archivo, codigo pelado sin "
                         "fences ```")},
        ["path", "contenido"],
        lambda a: f"{str(a.get('path', '')).strip()} | {a.get('contenido', '')}",
    ),
    "editar_archivo": (
        {"path": _p("ruta del archivo existente"),
         "buscar": _p("bloque EXACTO a buscar (copialo literal del archivo)"),
         "reemplazar": _p("bloque que lo reemplaza")},
        ["path", "buscar", "reemplazar"],
        lambda a: (f"{str(a.get('path', '')).strip()} | <<<<<<< SEARCH\n"
                   f"{a.get('buscar', '')}\n=======\n"
                   f"{a.get('reemplazar', '')}\n>>>>>>> REPLACE"),
    ),
    "apendar_archivo": (
        {"path": _p("ruta del archivo"),
         "texto": _p("texto a agregar al final")},
        ["path", "texto"],
        lambda a: f"{str(a.get('path', '')).strip()} | {a.get('texto', '')}",
    ),
    "copiar_archivo": (
        {"origen": _p("ruta origen"), "destino": _p("ruta destino")},
        ["origen", "destino"],
        lambda a: (f"{str(a.get('origen', '')).strip()} | "
                   f"{str(a.get('destino', '')).strip()}"),
    ),
    "listar": (
        {"directorio": _p("directorio a listar ('.' por defecto)")}, [],
        lambda a: str(a.get("directorio", ".")).strip(),
    ),
    "arbol": (
        {"directorio": _p("directorio raiz ('.' por defecto)")}, [],
        lambda a: str(a.get("directorio", ".")).strip(),
    ),
    "contar_lineas": (
        {"path": _p("ruta del archivo")}, ["path"],
        lambda a: str(a.get("path", "")).strip(),
    ),
    "buscar": (
        {"patron": _p("texto o patron a buscar"),
         "directorio": _p("directorio donde buscar ('.' por defecto)")},
        ["patron"],
        lambda a: (f"{a.get('patron', '')} | "
                   f"{str(a.get('directorio', '.')).strip()}"),
    ),
    "ejecutar": (
        {"comando": _p("comando de shell a correr")}, ["comando"],
        lambda a: str(a.get("comando", "")),
    ),
    "tests": (
        {"ruta": _p("archivo o directorio de tests (especifico, no la "
                    "suite entera)")}, ["ruta"],
        lambda a: str(a.get("ruta", "")).strip(),
    ),
    "py_validar": (
        {"path": _p("ruta del .py")}, ["path"],
        lambda a: str(a.get("path", "")).strip(),
    ),
    "json_validar": (
        {"path": _p("ruta del .json")}, ["path"],
        lambda a: str(a.get("path", "")).strip(),
    ),
    "git_diff": (
        {"ruta": _p("ruta a diffear (opcional)")}, [],
        lambda a: str(a.get("ruta", "")).strip(),
    ),
    "calcular": (
        {"expresion": _p("expresion aritmetica (+ - * / // % **)")},
        ["expresion"],
        lambda a: str(a.get("expresion", "")),
    ),
    "http_get": (
        {"url": _p("URL http/https")}, ["url"],
        lambda a: str(a.get("url", "")).strip(),
    ),
    "recordar": (
        {"consulta": _p("que buscar en la memoria episodica")}, ["consulta"],
        lambda a: str(a.get("consulta", "")),
    ),
    "memorizar": (
        {"texto": _p("texto a guardar en memoria episodica")}, ["texto"],
        lambda a: str(a.get("texto", "")),
    ),
    "anotar": (
        {"clave": _p("clave de la nota"), "valor": _p("valor a guardar")},
        ["clave", "valor"],
        lambda a: f"{str(a.get('clave', '')).strip()} | {a.get('valor', '')}",
    ),
    "resumir": (
        {"texto": _p("texto a resumir")}, ["texto"],
        lambda a: str(a.get("texto", "")),
    ),
    "bitacora_buscar": (
        {"patron": _p("regex a buscar en la bitacora de la tarea"),
         "n": _p("ultimas n coincidencias (default 20)", "integer")},
        ["patron"],
        # El patron es un regex y puede contener '|': va ULTIMO (regla de este
        # modulo, lineas de arriba) con n adelante — 'n | patron' o solo patron.
        lambda a: (f"{a.get('n')} | {a.get('patron', '')}"
                   if a.get("n") else str(a.get("patron", ""))),
    ),
    # ── Flota multimodal (ola 2, 2026-08-09): armadores verificados contra
    # el parseo REAL de cada tool de la ola 1 (voz_tools/musica_tools/
    # tresd_tools/vlm_tools). Regla del modulo: contenido con '|' ULTIMO.
    "voz_decir": (
        {"texto": _p("texto a decir en voz alta"),
         "guardar": _p("ruta WAV de salida (opcional; si se da, no reproduce)")},
        ["texto"],
        # voz_tools parsea 'guardar=<ruta> | <texto>' o solo '<texto>':
        # la opcion PRIMERO, el texto (que puede contener '|') ULTIMO.
        lambda a: ((f"guardar={str(a.get('guardar', '')).strip()} | "
                    if str(a.get('guardar', '')).strip() else "")
                   + str(a.get("texto", ""))),
    ),
    "voz_escuchar": (
        {"path": _p("ruta del WAV a transcribir"),
         "idioma": _p("codigo de idioma (default 'es')")},
        ["path"],
        lambda a: (str(a.get("path", "")).strip()
                   + (f" | idioma={str(a['idioma']).strip()}"
                      if a.get("idioma") else "")),
    ),
    "voz_clonar": (
        {"referencia": _p("WAV con la voz de referencia (>=6 s)"),
         "texto": _p("texto a sintetizar con esa voz")},
        ["referencia", "texto"],
        lambda a: f"{str(a.get('referencia', '')).strip()} | {a.get('texto', '')}",
    ),
    "musica_orquestar": (
        {"midi": _p("MIDI de condicion armonica (opcional; sin el, inventa "
                    "la armonia)"),
         "grupo": _p("variaciones por condicion (default 2)", "integer"),
         "wav": _p("1 = renderizar tambien a WAV", "integer")},
        [],
        # musica_tools parsea SOLO pares k=v separados por '|', orden libre.
        lambda a: " | ".join(p for p in (
            (f"midi={str(a['midi']).strip()}" if a.get("midi") else ""),
            (f"grupo={a['grupo']}" if a.get("grupo") else ""),
            (f"wav={a['wav']}" if a.get("wav") else "")) if p),
    ),
    "tresd_generar": (
        {"imagen": _p("ruta de la imagen del objeto (ideal PNG RGBA sin fondo)"),
         "formato": _p("obj o glb (default glb)"),
         "resolucion": _p("resolucion de marching cubes (default 256)",
                          "integer")},
        ["imagen"],
        # tresd_tools parsea 'ruta | k=v...' (rutas Windows no llevan '|').
        lambda a: " | ".join(p for p in (
            str(a.get("imagen", "")).strip(),
            (f"formato={str(a['formato']).strip()}" if a.get("formato") else ""),
            (f"resolucion={a['resolucion']}" if a.get("resolucion") else ""))
            if p),
    ),
    "vlm_mirar": (
        {"imagen": _p("ruta de la imagen a mirar"),
         "pregunta": _p("pregunta sobre la imagen (opcional; sin ella, "
                        "describe)")},
        ["imagen"],
        # vlm_tools parsea 'ruta | pregunta' con maxsplit=1: la pregunta es
        # contenido libre (puede contener '|') y va ULTIMA.
        lambda a: (str(a.get("imagen", "")).strip()
                   + (f" | {a['pregunta']}" if a.get("pregunta") else "")),
    ),
    # ── Modo RLM (contexto largo por tools, 2026-08-11): armadores contra el
    # parseo de cognia/agent/rlm.py. Regla del modulo: contenido con '|' ULTIMO.
    "ctx_ver": (
        {"desde": _p("primera linea a ver (1-index, inclusive)", "integer"),
         "hasta": _p("ultima linea a ver (inclusive)", "integer")},
        ["desde", "hasta"],
        lambda a: f"{a.get('desde', '')} | {a.get('hasta', '')}",
    ),
    "ctx_grep": (
        # El patron es un regex y puede contener '|' (alternacion): es el
        # UNICO argumento, va tal cual sin separador.
        {"patron": _p("regex a buscar en el contexto RLM")}, ["patron"],
        lambda a: str(a.get("patron", "")),
    ),
    "ctx_partir": (
        {"n": _p("cantidad de trozos contiguos (entre 2 y 64)", "integer")},
        ["n"],
        lambda a: str(a.get("n", "")),
    ),
    "rlm_llamar": (
        {"desde": _p("primera linea del fragmento (1-index, inclusive)",
                     "integer"),
         "hasta": _p("ultima linea del fragmento (inclusive)", "integer"),
         "pregunta": _p("pregunta que responde la subllamada sobre ese "
                        "fragmento")},
        ["desde", "hasta", "pregunta"],
        # rlm.py parsea 'desde | hasta | pregunta' con maxsplit=2: la
        # pregunta es contenido libre (puede contener '|') y va ULTIMA.
        lambda a: (f"{a.get('desde', '')} | {a.get('hasta', '')} | "
                   f"{a.get('pregunta', '')}"),
    ),
}

# Tools sin argumentos: schema de objeto vacio y string legacy vacio.
_SIN_ARGS = ("fecha", "notas", "git_estado", "git_log", "tarea_estado",
             "ctx_info", "procesos")


def _descripcion_de(doc: str) -> str:
    """La parte descriptiva de la linea de ayuda ('tool <args> -- desc')."""
    partes = re.split(r"\s+--\s+", doc or "", maxsplit=1)
    return partes[1].strip() if len(partes) == 2 else (doc or "").strip()


_TIPOS_JSON = {"string": "string", "str": "string", "entero": "integer",
               "int": "integer", "integer": "integer", "numero": "number",
               "number": "number", "bool": "boolean", "boolean": "boolean"}


def _desde_params(params: list) -> dict:
    """La lista ``params`` del decorador @tool -> el objeto JSON Schema.

    Formato de entrada (ver el docstring de ``tool`` en agent/tools.py):
    {"nombre", "tipo", "requerido", "descripcion", "clave"}. Un param sin tipo
    reconocible cae a string, que es lo que el protocolo texto transporta de
    todas formas.
    """
    props, requeridos = {}, []
    for p in params or []:
        if not isinstance(p, dict):
            continue
        nombre = str(p.get("nombre") or "").strip()
        if not nombre:
            continue
        tipo = _TIPOS_JSON.get(str(p.get("tipo") or "string").lower(), "string")
        props[nombre] = {"type": tipo,
                         "description": str(p.get("descripcion") or "")}
        if p.get("requerido"):
            requeridos.append(nombre)
    if not props:
        return {"type": "object", "properties": {}, "required": []}
    return {"type": "object", "properties": props, "required": requeridos}


def schemas_para(allowed: set = None) -> list:
    """Lista de schemas OpenAI para las tools visibles del registry.

    ``allowed`` con la misma semantica que build_tools_doc: None = todas.
    Import perezoso del registry para no pagar tools.py al importar esto.
    """
    from cognia.agent.tools import TOOLS
    schemas = []
    for nombre, spec in TOOLS.items():
        if allowed is not None and nombre not in allowed:
            continue
        desc = _descripcion_de(spec.get("doc", ""))
        if nombre in _TIPADAS:
            props, req, _ = _TIPADAS[nombre]
            params = {"type": "object", "properties": props, "required": req}
        elif nombre in FIRMAS:
            # Mismo rango que _TIPADAS: firma verificada A MANO contra el
            # parseo real de la tool (ver cognia/agent/firmas.py). Va ANTES
            # que el generico y que _desde_params porque estas tools no
            # declaran params — si algun dia los declaran, hay que borrar su
            # entrada de FIRMAS (lo vigila tests/test_firmas_tipadas.py).
            props, req, _ = FIRMAS[nombre]
            params = {"type": "object", "properties": props, "required": req}
        elif nombre in _SIN_ARGS:
            params = {"type": "object", "properties": {}, "required": []}
        elif spec.get("params"):
            # El registry DECLARA la firma (decorador @tool con params=[...]):
            # esa es la fuente de verdad y gana al generico. Sin esto, una tool
            # con params ricos igual salia como un unico string 'args' con su
            # linea de ayuda dentro — o sea, el modelo recibia una INSTRUCCION
            # en prosa donde tenia que recibir una firma tipada. Las _TIPADAS
            # siguen mandando: son las medidas contra el modelo real.
            params = _desde_params(spec["params"])
        else:
            # Generico: un solo string con el formato historico documentado
            # en la linea de ayuda (WP2 esta enriqueciendo esas lineas).
            params = {"type": "object",
                      "properties": {"args": _p(
                          f"argumentos en el formato: {spec.get('doc', '')}")},
                      "required": []}
        schemas.append({"type": "function",
                        "function": {"name": nombre, "description": desc,
                                     "parameters": params}})
    return schemas


def args_legacy(nombre: str, argumentos: dict) -> str:
    """Argumentos JSON del tool call -> el string que run_tool espera.

    Tolerante por diseno: un dict raro no lanza — devuelve lo mas util
    posible y deja que la tool misma reporte su error de formato (ese error
    vuelve al modelo como turno tool, que es la señal correcta)."""
    if not isinstance(argumentos, dict):
        return str(argumentos or "")
    if nombre in _TIPADAS:
        try:
            return _TIPADAS[nombre][2](argumentos)
        except Exception:
            pass
    if nombre in FIRMAS:
        # El armador de la firma es el inverso EXACTO del schema que
        # schemas_para acaba de publicar: mismo orden de consulta en las dos
        # direcciones o el puente se descuadra.
        # EXCEPCION medida: un modelo que no leyo el schema (o un llamador
        # legacy) manda {"args": "<el string de siempre>"}. Si no vino NINGUNA
        # de las propiedades declaradas, el armador devolveria vacio y la tool
        # se quedaria sin argumentos — perdiendo un string que ya era valido.
        # En ese caso gana el passthrough de abajo.
        props = FIRMAS[nombre][0]
        if not ("args" in argumentos
                and not any(k in argumentos for k in props)):
            try:
                armado = FIRMAS[nombre][2](argumentos)
                # MISMA guarda que la rama de params (linea 394), por el MISMO
                # motivo: si el modelo improviso los nombres de las claves, el
                # armador solo encuentra defaults vacios y devuelve el
                # ESQUELETO del formato (' |  | ') o directamente ''. Eso deja
                # a la tool sin argumentos — peor que equivocarse. Medido el
                # 2026-08-13: kg_agregar con {'subject','relation','object'}
                # daba 'a | usa | b' por el join final y paso a ' |  | ';
                # code_grafo con {'modulo': 'cognia.cli'} daba 'cognia.cli' y
                # paso a ''. Solo el armado CON contenido gana; si sale vacio
                # cae al passthrough/join de abajo, que al menos le entrega
                # algo con lo que fallar explicando que falto.
                # El ``not argumentos`` deja pasar el vacio LEGITIMO: repo_map
                # o ejecutar_flujo sin argumentos arman '' a proposito.
                if armado.strip(" |") or not argumentos:
                    return armado
            except Exception:
                pass
    if nombre in _SIN_ARGS:
        return ""
    if "args" in argumentos:
        return str(argumentos.get("args") or "")
    # La tool declara su firma en el registry: ``armar_args`` sabe reconstruir
    # el string del protocolo texto respetando el orden posicional y los
    # tokens 'clave=valor'. Es el puente inverso exacto del schema que
    # ``_desde_params`` acaba de publicar.
    try:
        from cognia.agent.tools import TOOLS, armar_args
        if (TOOLS.get(nombre) or {}).get("params"):
            armado = armar_args(nombre, argumentos)
            # Si el modelo nombró los argumentos de otra forma (le pasa cuando
            # improvisa sobre un schema que no leyó del todo), armar_args
            # devuelve vacío y la llamada quedaría SIN argumentos — peor que
            # equivocarse, porque la tool no puede ni explicar qué faltó. En
            # ese caso cae al join de abajo, que al menos le da algo que fallar
            # con un mensaje útil de vuelta al modelo.
            if armado or not argumentos:
                return armado
    except Exception:
        pass
    # Ultimo recurso: valores en orden de insercion unidos con ' | ' (el
    # separador historico de las tools multi-argumento).
    return " | ".join(str(v) for v in argumentos.values())
