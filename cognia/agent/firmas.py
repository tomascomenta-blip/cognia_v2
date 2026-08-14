"""
cognia/agent/firmas.py
======================
Firmas TIPADAS de las tools que el registry no declara (A4, 2026-08-13).

POR QUE EXISTE: ``tool_schemas.schemas_para`` tenia un caso generico para
toda tool sin ``params`` en el decorador — publicaba un unico parametro
string ``args`` con la LINEA DE AYUDA metida adentro como descripcion. O sea:
al modelo, en tool-calling NATIVO, le llegaba una INSTRUCCION EN PROSA
("argumentos en el formato: kg_agregar <sujeto> | <relacion> | <objeto>")
donde el protocolo le prometia una firma tipada. Medido en el venv el
2026-08-13: de 55 tools, 16 caian ahi.

POR QUE UN MODULO DE DATOS Y NO LOS DECORADORES: las 16 viven en
``cognia/agent/tools.py`` (y en ``plan_artifact.py`` / ``flows.py``), que son
propiedad de otro paquete de trabajo. Tocar sus decoradores para agregarles
``params=[...]`` seria editar codigo ajeno; ademas varias parsean su string
de formas que ``armar_args`` no sabe reconstruir (subcomandos, separadores
por espacio en vez de '|', partes opcionales). Asi que la firma va aca, en
el MISMO formato que ``_TIPADAS``:

    FIRMAS = {nombre: (properties, required, armador)}

REGLA DEL MODULO (heredada de tool_schemas): el armador reconstruye EXACTA-
MENTE el string que ``run_tool`` le pasa a la tool, y el contenido que puede
contener '|' va SIEMPRE ULTIMO — porque el parseo real usa ``maxsplit`` y
solo el ultimo campo sobrevive a un '|' interno. Cada entrada de abajo lleva
en comentario el parseo REAL contra el que se verifico.
"""
from __future__ import annotations


def _p(desc: str, tipo: str = "string") -> dict:
    # Igual que tool_schemas._p, duplicado a proposito: tool_schemas importa
    # ESTE modulo, asi que importar al reves seria un ciclo por dos lineas.
    return {"type": tipo, "description": desc}


def _armar_plan(a: dict) -> str:
    """plan_artifact.py:138 parsea ``args.strip().split(None, 1)``: el
    subcomando primero y el resto crudo. 'crear' se come una lista numerada
    (multilinea, la parsea ``parse_pasos`` por regex por linea) y 'marcar'
    se come '<n> <estado>' con otro ``split(None, 1)``."""
    sub = str(a.get("subcomando") or "ver").strip().lower()
    if sub == "crear":
        return f"crear {a.get('pasos', '')}"
    if sub == "marcar":
        return f"marcar {a.get('n', '')} {str(a.get('estado', '')).strip()}"
    return sub


def _armar_cuaderno(a: dict) -> str:
    """tools.py:1513 parsea ``re.split(r"\\s*\\|\\s*", args, maxsplit=1)``:
    subcomando | resto. 'ver' no lleva resto — y mandar un '|' pelado ahi
    dejaria ``resto=''`` igual, pero el string queda mas sucio de lo que la
    linea de ayuda documenta, asi que se omite."""
    sub = str(a.get("subcomando") or "").strip()
    texto = a.get("texto", "")
    return f"{sub} | {texto}" if texto else sub


FIRMAS: dict = {
    # ── Sistema ─────────────────────────────────────────────────────────
    "abrir": (
        # tools.py:1194 -> args.strip().strip('"\''): UN solo campo libre.
        {"objetivo": _p("URL, ruta de archivo o nombre de app a abrir "
                        "(p.ej. 'https://youtube.com', 'C:/notas.txt', "
                        "'notepad')")},
        ["objetivo"],
        lambda a: str(a.get("objetivo", "")).strip(),
    ),

    # ── MCP libre / conocimiento del repo ───────────────────────────────
    # Las cuatro de abajo parsean con tools.py:1360 ``_partir(args, n)`` =
    # ``args.strip().split(None, n - 1)``: separador ESPACIO (no '|') y el
    # ULTIMO campo se queda con todo lo que sobre.
    "docs_repo": (
        {"owner": _p("dueno del repo en GitHub (p.ej. 'anthropics')"),
         "repo": _p("nombre del repo (p.ej. 'anthropic-sdk-python')")},
        ["owner", "repo"],
        lambda a: (f"{str(a.get('owner', '')).strip()} "
                   f"{str(a.get('repo', '')).strip()}"),
    ),
    "preguntar_repo": (
        {"repo": _p("repo en formato 'owner/repo' (el '/' es obligatorio)"),
         "pregunta": _p("pregunta en lenguaje natural sobre ese repo")},
        ["repo", "pregunta"],
        # La pregunta es texto libre: va ULTIMA (se come el resto de la linea).
        lambda a: (f"{str(a.get('repo', '')).strip()} "
                   f"{str(a.get('pregunta', '')).strip()}"),
    ),
    "docs_libreria": (
        {"nombre": _p("nombre de la libreria (p.ej. 'fastapi', 'polars')"),
         "tema": _p("tema concreto a consultar (opcional; sin el, consulta "
                    "por el nombre)")},
        ["nombre"],
        lambda a: (str(a.get("nombre", "")).strip()
                   + (f" {str(a['tema']).strip()}"
                      if str(a.get("tema", "")).strip() else "")),
    ),
    "buscar_en_repo": (
        {"owner": _p("dueno del repo en GitHub"),
         "repo": _p("nombre del repo"),
         "query": _p("que buscar en el codigo de ese repo")},
        ["owner", "repo", "query"],
        lambda a: (f"{str(a.get('owner', '')).strip()} "
                   f"{str(a.get('repo', '')).strip()} "
                   f"{str(a.get('query', '')).strip()}"),
    ),
    "repo_map": (
        # tools.py:1424 -> args.strip(), vacio = mapa sin sesgo.
        {"terminos": _p("terminos que sesgan el ranking (opcional; sin ellos "
                        "devuelve el mapa global del repo)")},
        [],
        lambda a: str(a.get("terminos", "")).strip(),
    ),
    "code_grafo": (
        # tools.py:1446 -> args.strip(), UN campo obligatorio.
        {"objeto": _p("modulo (p.ej. 'cognia.agent.loop') o simbolo (funcion "
                      "o clase) cuya vecindad se quiere")},
        ["objeto"],
        lambda a: str(a.get("objeto", "")).strip(),
    ),

    # ── Cuaderno / grafo de conocimiento ────────────────────────────────
    "cuaderno": (
        {"subcomando": _p("nota | fuente | consultar | ver"),
         "texto": _p("texto de la nota, ruta de la fuente, o la pregunta a "
                     "consultar (vacio para 'ver')")},
        ["subcomando"],
        _armar_cuaderno,
    ),
    "kg_buscar": (
        # tools.py:1576 -> args.strip(), UN campo.
        {"concepto": _p("concepto cuyos hechos se buscan en el grafo")},
        ["concepto"],
        lambda a: str(a.get("concepto", "")).strip(),
    ),
    "kg_agregar": (
        # tools.py:1585 -> re.split(r"\s*\|\s*", args) SIN maxsplit: exige
        # EXACTAMENTE 3 partes, asi que ningun campo puede contener '|'.
        {"sujeto": _p("sujeto del hecho"),
         "relacion": _p("relacion (debe estar en KnowledgeGraph.VALID_"
                        "RELATIONS; se normaliza a minusculas)"),
         "objeto": _p("objeto del hecho")},
        ["sujeto", "relacion", "objeto"],
        lambda a: (f"{str(a.get('sujeto', '')).strip()} | "
                   f"{str(a.get('relacion', '')).strip()} | "
                   f"{str(a.get('objeto', '')).strip()}"),
    ),

    # ── Contratos y self-tooling ────────────────────────────────────────
    "contratos": (
        # tools.py:2093 -> re.split(r"\s*\|\s*", args, maxsplit=3): exige 4
        # partes y solo la 4a (asserts) sobrevive a un '|' interno.
        {"plan": _p("el plan de la tarea, en texto"),
         "design": _p("firmas del design, separadas por ';' o saltos de "
                      "linea"),
         "codigo": _p("ruta a un .py (relativa al workspace) o el codigo en "
                      "linea"),
         "asserts": _p("los asserts del test que debe pasar el codigo")},
        ["plan", "design", "codigo", "asserts"],
        lambda a: (f"{str(a.get('plan', '')).strip()} | "
                   f"{str(a.get('design', '')).strip()} | "
                   f"{str(a.get('codigo', '')).strip()} | "
                   f"{a.get('asserts', '')}"),
    ),
    "crear_herramienta": (
        # tools.py:2146 -> re.split(r"\s*\|\s*", args, maxsplit=3): 4 partes,
        # TODAS no vacias; solo la 4a tolera un '|' interno.
        {"nombre": _p("nombre de la tool nueva (identificador)"),
         "proposito": _p("que debe hacer la tool (sus primeros 60 chars "
                         "quedan como linea de ayuda)"),
         "test_input": _p("entrada con la que se verifica en sandbox"),
         "resultado_esperado": _p("substring que debe aparecer en la salida "
                                  "para dar la tool por verificada")},
        ["nombre", "proposito", "test_input", "resultado_esperado"],
        lambda a: (f"{str(a.get('nombre', '')).strip()} | "
                   f"{str(a.get('proposito', '')).strip()} | "
                   f"{str(a.get('test_input', '')).strip()} | "
                   f"{a.get('resultado_esperado', '')}"),
    ),
    "revertir_herramienta": (
        # tools.py:2177 -> re.split(r"\s*\|\s*", args, maxsplit=1): 2 partes.
        {"nombre": _p("nombre de la tool creada con crear_herramienta"),
         "version": _p("version guardada en _history a restaurar "
                       "(p.ej. '0.1.0')")},
        ["nombre", "version"],
        lambda a: (f"{str(a.get('nombre', '')).strip()} | "
                   f"{str(a.get('version', '')).strip()}"),
    ),

    # ── Plan y flujos ───────────────────────────────────────────────────
    "plan": (
        {"subcomando": _p("ver | crear | marcar"),
         "pasos": _p("solo para 'crear': la lista numerada de pasos (una por "
                     "linea, '1. ...' o '- ...')"),
         "n": _p("solo para 'marcar': numero de paso, 1-index", "integer"),
         "estado": _p("solo para 'marcar': hecho | en_curso")},
        ["subcomando"],
        _armar_plan,
    ),
    "crear_flujo": (
        # flows.py:317 -> (args or "").strip(), UN campo libre.
        {"descripcion": _p("la tarea en lenguaje natural, que se organiza en "
                           "un DAG de pasos")},
        ["descripcion"],
        lambda a: str(a.get("descripcion", "")).strip(),
    ),
    "ejecutar_flujo": (
        # flows.py:284 -> (args or "").strip(); vacio = el .flujo.json del
        # workspace (el que acaba de dejar crear_flujo).
        {"flujo": _p("nombre o ruta del .flujo.json (opcional; sin el usa el "
                     ".flujo.json del workspace)")},
        [],
        lambda a: str(a.get("flujo", "")).strip(),
    ),
}
