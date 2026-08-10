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
}

# Tools sin argumentos: schema de objeto vacio y string legacy vacio.
_SIN_ARGS = ("fecha", "notas", "git_estado", "git_log", "tarea_estado")


def _descripcion_de(doc: str) -> str:
    """La parte descriptiva de la linea de ayuda ('tool <args> -- desc')."""
    partes = re.split(r"\s+--\s+", doc or "", maxsplit=1)
    return partes[1].strip() if len(partes) == 2 else (doc or "").strip()


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
        elif nombre in _SIN_ARGS:
            params = {"type": "object", "properties": {}, "required": []}
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
    if nombre in _SIN_ARGS:
        return ""
    if "args" in argumentos:
        return str(argumentos.get("args") or "")
    # Ultimo recurso: valores en orden de insercion unidos con ' | ' (el
    # separador historico de las tools multi-argumento).
    return " | ".join(str(v) for v in argumentos.values())
