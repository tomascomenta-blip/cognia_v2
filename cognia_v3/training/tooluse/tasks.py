"""
cognia_v3/training/tooluse/tasks.py
===================================
Banco de tareas VERIFICABLES para generar trayectorias de tool-use.

Cada tarea es un dict:
    id      -> slug único
    prompt  -> lo que se le pide al agente (español, como en el deploy)
    tools   -> herramientas que se esperan (solo para el reporte de cobertura)
    verify  -> fn(ws: Path, transcript: str, answer: str) -> bool
               chequea la POSTCONDICIÓN (estado final), no el camino: hay muchas
               formas válidas de resolverla. transcript = todos los RESULTADO
               concatenados; answer = el texto del `responder` final.

Fase A (de-risk): solo herramientas DETERMINISTAS y verificables por ejecución
(archivos, búsqueda, shell echo/python, aritmética, fecha). Las herramientas de
memoria/KG (recordar/kg_*) necesitan el cerebro Cognia completo y verificación
difusa -> quedan para Fase B.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


# ── helpers de verificación ──────────────────────────────────────────────

def _read(ws: Path, name: str) -> str:
    p = ws / name
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _lines(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _has(transcript: str, needle: str) -> bool:
    return needle.lower() in transcript.lower()


def _calc_equals(transcript: str, answer: str, value) -> bool:
    """El número aparece como resultado (calcular imprime 'expr = val') o en la
    respuesta final como token aislado. Evita falsos positivos de substring."""
    v = str(value)
    if re.search(rf"=\s*{re.escape(v)}(?:\.0+)?\b", transcript):
        return True
    return bool(re.search(rf"\b{re.escape(v)}\b", answer or ""))


# ── banco de tareas ──────────────────────────────────────────────────────

TASKS = [
    {
        "id": "file_write_basic",
        "prompt": "Crea un archivo llamado saludo.txt con exactamente este contenido: hola mundo",
        "tools": ["escribir_archivo"],
        "answer": "Listo, cree saludo.txt con el texto 'hola mundo'.",
        "verify": lambda ws, t, a: _read(ws, "saludo.txt").strip().lower() == "hola mundo",
    },
    {
        "id": "file_write_multiline",
        "prompt": "Crea un archivo frutas.txt con estas tres lineas, una por linea: manzana, pera, uva.",
        "tools": ["escribir_archivo"],
        "answer": "Listo, cree frutas.txt con las tres lineas.",
        "verify": lambda ws, t, a: [x.lower() for x in _lines(_read(ws, "frutas.txt"))] == ["manzana", "pera", "uva"],
    },
    {
        "id": "append_two_lines",
        "prompt": "Crea diario.txt con la linea 'dia 1', y despues agrega al final la linea 'dia 2'.",
        "tools": ["escribir_archivo", "apendar_archivo"],
        "answer": "Listo, diario.txt tiene 'dia 1' y 'dia 2'.",
        "verify": lambda ws, t, a: (lambda L: len(L) >= 2 and L[0].lower() == "dia 1" and L[-1].lower() == "dia 2")(_lines(_read(ws, "diario.txt"))),
    },
    {
        "id": "count_lines_4",
        "prompt": "Crea lista.txt con exactamente 4 lineas: rojo, verde, azul, negro (una por linea). Despues conta cuantas lineas tiene.",
        "tools": ["escribir_archivo", "contar_lineas"],
        "answer": "lista.txt tiene 4 lineas.",
        "verify": lambda ws, t, a: len(_lines(_read(ws, "lista.txt"))) == 4 and _has(t, "4 lineas"),
    },
    {
        "id": "json_make_key",
        "prompt": "Crea un archivo config.json con un JSON valido que tenga la clave \"puerto\" con valor 8080. Despues validalo.",
        "tools": ["escribir_archivo", "json_validar"],
        "answer": "Listo, config.json es valido y tiene puerto=8080.",
        "verify": lambda ws, t, a: _json_key(ws, "config.json", "puerto") == 8080 and _has(t, "json valido"),
    },
    {
        "id": "json_make_list",
        "prompt": "Crea datos.json con un JSON valido que sea una lista con los numeros 1, 2 y 3. Despues validalo.",
        "tools": ["escribir_archivo", "json_validar"],
        "answer": "Listo, datos.json es valido y contiene [1, 2, 3].",
        "verify": lambda ws, t, a: _json_load(ws, "datos.json") == [1, 2, 3] and _has(t, "json valido"),
    },
    {
        "id": "py_write_validate",
        "prompt": "Escribi un archivo hola.py que defina una funcion saludar() que retorne la cadena 'hola'. Despues valida su sintaxis.",
        "tools": ["escribir_archivo", "py_validar"],
        "answer": "Listo, hola.py define saludar() y su sintaxis es correcta.",
        "verify": lambda ws, t, a: _py_ok(ws, "hola.py") and "def saludar" in _read(ws, "hola.py") and _has(t, "sintaxis ok"),
    },
    {
        "id": "py_write_run",
        "prompt": "Escribi calc.py que imprima el resultado de 6*7. Validá su sintaxis y despues ejecutalo con: python calc.py",
        "tools": ["escribir_archivo", "py_validar", "ejecutar"],
        "answer": "Listo, calc.py imprime 42.",
        "verify": lambda ws, t, a: _py_ok(ws, "calc.py") and _has(t, "42"),
    },
    {
        "id": "math_mul",
        "prompt": "Cuanto es 23 por 19? Usa la herramienta de calculo y responde el numero.",
        "tools": ["calcular"],
        "answer": "437",
        "verify": lambda ws, t, a: _calc_equals(t, a, 437),
    },
    {
        "id": "math_expr",
        "prompt": "Calcula (144 / 12) + 8 y responde el resultado.",
        "tools": ["calcular"],
        "answer": "20",
        "verify": lambda ws, t, a: _calc_equals(t, a, 20),
    },
    {
        "id": "math_pow",
        "prompt": "Cuanto es 2 elevado a la 10? Calculalo y responde.",
        "tools": ["calcular"],
        "answer": "1024",
        "verify": lambda ws, t, a: _calc_equals(t, a, 1024),
    },
    {
        "id": "math_sub",
        "prompt": "Calcula 1000 menos 333 y responde el numero.",
        "tools": ["calcular"],
        "answer": "667",
        "verify": lambda ws, t, a: _calc_equals(t, a, 667),
    },
    {
        "id": "math_to_file",
        "prompt": "Calcula 15 por 4 y guarda el resultado (solo el numero) en un archivo resultado.txt.",
        "tools": ["calcular", "escribir_archivo"],
        "answer": "Listo, guarde 60 en resultado.txt.",
        "verify": lambda ws, t, a: "60" in _read(ws, "resultado.txt"),
    },
    {
        "id": "read_after_write",
        "prompt": "Crea un archivo mensaje.txt con el texto secreto42, y despues leelo para confirmar su contenido.",
        "tools": ["escribir_archivo", "leer_archivo"],
        "answer": "Confirmado, mensaje.txt contiene 'secreto42'.",
        "verify": lambda ws, t, a: "secreto42" in _read(ws, "mensaje.txt") and _has(t, "secreto42"),
    },
    {
        "id": "copy_file",
        "prompt": "Crea origen.txt con el texto copiame. Despues copialo a un archivo destino.txt.",
        "tools": ["escribir_archivo", "copiar_archivo"],
        "answer": "Listo, copie origen.txt a destino.txt.",
        "verify": lambda ws, t, a: _read(ws, "destino.txt").strip().lower() == "copiame",
    },
    {
        "id": "search_word",
        "prompt": "Crea texto.txt cuyo contenido incluya la palabra ZANAHORIA. Despues busca 'ZANAHORIA' en el directorio actual.",
        "tools": ["escribir_archivo", "buscar"],
        "answer": "Encontre 'ZANAHORIA' en texto.txt.",
        "verify": lambda ws, t, a: "zanahoria" in _read(ws, "texto.txt").lower() and _has(t, "zanahoria") and not _has(t, "sin resultados"),
    },
    {
        "id": "listar_dir",
        "prompt": "Crea tres archivos a.txt, b.txt y c.txt (con cualquier contenido). Despues lista el directorio actual.",
        "tools": ["escribir_archivo", "listar"],
        "answer": "Listo, cree a.txt, b.txt y c.txt y liste el directorio.",
        "verify": lambda ws, t, a: all((ws / f).is_file() for f in ("a.txt", "b.txt", "c.txt")) and _has(t, "resultado listar"),
    },
    {
        "id": "arbol_subdir",
        "prompt": "Crea un archivo dentro de una subcarpeta: sub/dato.txt con el texto x. Despues muestra el arbol del directorio actual.",
        "tools": ["escribir_archivo", "arbol"],
        "answer": "Listo, cree sub/dato.txt y mostre el arbol.",
        "verify": lambda ws, t, a: (ws / "sub" / "dato.txt").is_file() and _has(t, "resultado arbol"),
    },
    {
        "id": "count_5_lines",
        "prompt": "Crea poema.txt con exactamente 5 lineas de texto (cualquiera). Despues conta cuantas lineas tiene.",
        "tools": ["escribir_archivo", "contar_lineas"],
        "answer": "poema.txt tiene 5 lineas.",
        "verify": lambda ws, t, a: len(_lines(_read(ws, "poema.txt"))) == 5 and _has(t, "5 lineas"),
    },
    {
        "id": "shell_echo",
        "prompt": "Ejecuta el comando de shell: echo cognia_ok",
        "tools": ["ejecutar"],
        "answer": "El comando imprimio 'cognia_ok'.",
        # Exige EXITO real: el formato de exito es 'RESULTADO ejecutar: <out>'
        # (sin '(exit N)'); un comando fallido da 'RESULTADO ejecutar (exit 1):'
        # y NO debe contar aunque 'cognia_ok' aparezca en el eco del error.
        "verify": lambda ws, t, a: bool(re.search(r"resultado ejecutar:\s*[^\n]*cognia_ok", t, re.IGNORECASE)),
    },
    {
        "id": "fecha_hoy",
        "prompt": "Decime la fecha y hora actual usando la herramienta correspondiente.",
        "tools": ["fecha"],
        "answer": "Esa es la fecha y hora actual.",
        "verify": lambda ws, t, a: bool(re.search(r"\d{4}-\d{2}-\d{2}", t)),
    },
    {
        "id": "append_then_count",
        "prompt": "Crea tareas.txt con la linea 'comprar pan'. Agrega al final otra linea 'lavar ropa'. Despues conta cuantas lineas tiene.",
        "tools": ["escribir_archivo", "apendar_archivo", "contar_lineas"],
        "answer": "tareas.txt tiene 2 lineas.",
        "verify": lambda ws, t, a: len(_lines(_read(ws, "tareas.txt"))) == 2 and _has(t, "2 lineas"),
    },
    # ── ampliacion de cobertura (2026-07-01): mas apendar/contar/buscar/copiar/mates ──
    {
        "id": "append_tres",
        "prompt": "Crea agenda.txt con la linea 'lunes'. Agrega al final 'martes' y despues 'miercoles' (cada una en su linea).",
        "tools": ["escribir_archivo", "apendar_archivo"],
        "answer": "agenda.txt tiene lunes, martes y miercoles.",
        "verify": lambda ws, t, a: [x.lower() for x in _lines(_read(ws, "agenda.txt"))] == ["lunes", "martes", "miercoles"],
    },
    {
        "id": "contar_seis",
        "prompt": "Crea colores.txt con estas seis lineas: rojo, verde, azul, negro, blanco, gris. Despues conta cuantas lineas tiene.",
        "tools": ["escribir_archivo", "contar_lineas"],
        "answer": "colores.txt tiene 6 lineas.",
        "verify": lambda ws, t, a: len(_lines(_read(ws, "colores.txt"))) == 6 and _has(t, "6 lineas"),
    },
    {
        "id": "buscar_en_inventario",
        "prompt": "Crea inventario.txt con varias lineas de productos, una de ellas con la palabra MANZANA. Despues busca 'MANZANA' en el directorio actual.",
        "tools": ["escribir_archivo", "buscar"],
        "answer": "Encontre 'MANZANA' en inventario.txt.",
        "verify": lambda ws, t, a: "manzana" in _read(ws, "inventario.txt").lower() and _has(t, "manzana") and not _has(t, "sin resultados"),
    },
    {
        "id": "copiar_dos_veces",
        "prompt": "Crea plantilla.txt con el texto contenido_base. Copialo a copia1.txt y despues a copia2.txt.",
        "tools": ["escribir_archivo", "copiar_archivo"],
        "answer": "Copie plantilla.txt a copia1.txt y copia2.txt.",
        "verify": lambda ws, t, a: _read(ws, "copia1.txt").strip() == "contenido_base" and _read(ws, "copia2.txt").strip() == "contenido_base",
    },
    {
        "id": "math_div",
        "prompt": "Cuanto es 840 dividido 8? Usa la herramienta de calculo y responde.",
        "tools": ["calcular"],
        "answer": "105",
        "verify": lambda ws, t, a: _calc_equals(t, a, 105),
    },
    {
        "id": "math_combo",
        "prompt": "Calcula 7 por 8 mas 100 y responde el numero.",
        "tools": ["calcular"],
        "answer": "156",
        "verify": lambda ws, t, a: _calc_equals(t, a, 156),
    },
    {
        "id": "math_pow16",
        "prompt": "Cuanto es 2 elevado a la 16? Calculalo y responde.",
        "tools": ["calcular"],
        "answer": "65536",
        "verify": lambda ws, t, a: _calc_equals(t, a, 65536),
    },
    {
        "id": "math_mod",
        "prompt": "Cual es el resto de dividir 1000 entre 7? Calculalo (usa %) y responde.",
        "tools": ["calcular"],
        "answer": "6",
        "verify": lambda ws, t, a: _calc_equals(t, a, 6),
    },
    {
        "id": "json_anidado",
        "prompt": "Crea cfg.json con un JSON valido que tenga la clave \"db\" con un objeto adentro que tenga \"host\" igual a \"local\" y \"port\" igual a 5432. Despues validalo.",
        "tools": ["escribir_archivo", "json_validar"],
        "answer": "cfg.json es valido con db.host=local y db.port=5432.",
        "verify": lambda ws, t, a: (_json_load(ws, "cfg.json") or {}).get("db", {}).get("port") == 5432 and _has(t, "json valido"),
    },
    {
        "id": "py_sumar",
        "prompt": "Escribi un archivo suma.py que defina una funcion sumar(a, b) que retorne a + b. Despues valida su sintaxis.",
        "tools": ["escribir_archivo", "py_validar"],
        "answer": "suma.py define sumar(a,b) y su sintaxis es correcta.",
        "verify": lambda ws, t, a: _py_ok(ws, "suma.py") and "def sumar" in _read(ws, "suma.py") and _has(t, "sintaxis ok"),
    },
    {
        "id": "leer_clave",
        "prompt": "Crea clave.txt con el texto valor_xyz_99. Despues leelo para confirmar su contenido.",
        "tools": ["escribir_archivo", "leer_archivo"],
        "answer": "Confirmado, clave.txt contiene 'valor_xyz_99'.",
        "verify": lambda ws, t, a: "valor_xyz_99" in _read(ws, "clave.txt") and _has(t, "valor_xyz_99"),
    },
    {
        "id": "math_to_file2",
        "prompt": "Calcula 12 por 12 y guarda solo el numero en un archivo cuadrado.txt.",
        "tools": ["calcular", "escribir_archivo"],
        "answer": "Guarde 144 en cuadrado.txt.",
        "verify": lambda ws, t, a: "144" in _read(ws, "cuadrado.txt"),
    },
    # ══ FASE B (2026-07-01): memoria de trabajo, KG, y mas multi-paso ══
    # Cubren tools que el dataset Fase A no tocaba (anotar/notas/kg_*) o que el
    # 3B base falla (multi-paso). Se generan con trayectorias EXPERTAS (gen_expert.py,
    # ver EXPERT_STEPS abajo), no con el 3B, porque el base no las resuelve.
    # ── memoria de trabajo (anotar/notas): estado en ctx["working_memory"], aislado ──
    {
        "id": "anotar_recuperar",
        "prompt": "Anota en tu memoria de trabajo que la clave 'color' vale 'azul'. Despues consulta tus notas para confirmarlo.",
        "tools": ["anotar", "notas"],
        "answer": "En mis notas quedo: color = azul.",
        "verify": lambda ws, t, a: "color: azul" in t.lower(),
    },
    {
        "id": "anotar_dos",
        "prompt": "Anota dos cosas en tu memoria de trabajo: 'tarea1' es 'comprar' y 'tarea2' es 'vender'. Despues lee tus notas.",
        "tools": ["anotar", "notas"],
        "answer": "Mis notas: tarea1=comprar, tarea2=vender.",
        "verify": lambda ws, t, a: _has(t, "comprar") and _has(t, "vender") and _has(t, "tarea1"),
    },
    {
        "id": "anotar_eval",
        "prompt": "Guarda en tu memoria de trabajo que la clave 'ciudad' vale 'lima'. Despues revisa tus notas.",
        "tools": ["anotar", "notas"],
        "answer": "En mis notas quedo: ciudad = lima.",
        "verify": lambda ws, t, a: "ciudad: lima" in t.lower(),
    },
    # ── grafo de conocimiento (kg_agregar/kg_buscar): KG en DB temporal aislada ──
    {
        "id": "kg_agregar_buscar",
        "prompt": "Agrega al grafo de conocimiento el hecho: Python is_a lenguaje. Despues busca en el grafo que sabe sobre Python.",
        "tools": ["kg_agregar", "kg_buscar"],
        "answer": "El grafo ahora sabe que Python is_a lenguaje.",
        "verify": lambda ws, t, a: _has(t, "python") and _has(t, "lenguaje") and not _has(t, "sin hechos"),
    },
    {
        "id": "kg_dos_hechos",
        "prompt": "Agrega dos hechos al grafo de conocimiento: 'perro is_a animal' y 'perro has_property leal'. Despues busca en el grafo sobre perro.",
        "tools": ["kg_agregar", "kg_buscar"],
        "answer": "El grafo sabe que perro is_a animal y tiene la propiedad leal.",
        "verify": lambda ws, t, a: _has(t, "animal") and not _has(t, "sin hechos"),
    },
    {
        "id": "kg_eval",
        "prompt": "Agrega al grafo de conocimiento el hecho: Paris located_in Francia. Despues busca en el grafo sobre Paris.",
        "tools": ["kg_agregar", "kg_buscar"],
        "answer": "El grafo sabe que Paris located_in Francia.",
        "verify": lambda ws, t, a: _has(t, "paris") and _has(t, "francia") and not _has(t, "sin hechos"),
    },
    # ── multi-paso held-out para EVAL (miden generalizacion; NO van a train) ──
    {
        "id": "json_eval",
        "prompt": "Crea ajustes.json con un JSON valido que tenga la clave \"activo\" con valor true. Despues validalo.",
        "tools": ["escribir_archivo", "json_validar"],
        "answer": "ajustes.json es valido con activo=true.",
        "verify": lambda ws, t, a: (_json_load(ws, "ajustes.json") or {}).get("activo") is True and _has(t, "json valido"),
    },
    {
        "id": "append_eval",
        "prompt": "Crea registro.txt con la linea 'inicio'. Agrega al final la linea 'fin'. Despues conta cuantas lineas tiene.",
        "tools": ["escribir_archivo", "apendar_archivo", "contar_lineas"],
        "answer": "registro.txt tiene 2 lineas.",
        "verify": lambda ws, t, a: len(_lines(_read(ws, "registro.txt"))) == 2 and _has(t, "2 lineas"),
    },
]


# ── verificadores auxiliares que necesitan try/except ────────────────────

def _json_load(ws: Path, name: str):
    try:
        return json.loads(_read(ws, name))
    except Exception:
        return None


def _json_key(ws: Path, name: str, key: str):
    d = _json_load(ws, name)
    if isinstance(d, dict):
        return d.get(key)
    return None


def _py_ok(ws: Path, name: str) -> bool:
    src = _read(ws, name)
    if not src:
        return False
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def by_id(task_id: str):
    for t in TASKS:
        if t["id"] == task_id:
            return t
    return None


# ══════════════════════════════════════════════════════════════════════
# TRAYECTORIAS EXPERTAS (scripted) — para gen_expert.py
# ══════════════════════════════════════════════════════════════════════
# La secuencia CORRECTA de (tool, args) para cada tarea. gen_expert.py las
# EJECUTA contra las tools reales (mismo run_tool del deploy) y solo conserva
# la trayectoria si la postcondicion (verify) pasa. Se usa donde el 3B base
# falla (multi-paso: 0% accept en el report) o donde la tool necesita estado
# aislado (memoria de trabajo / KG). '\n' en el contenido = varias lineas.
EXPERT_STEPS = {
    # multi-paso de archivos / json / py (el 3B base no las resolvia)
    "file_write_multiline": [("escribir_archivo", "frutas.txt | manzana\npera\nuva")],
    "append_two_lines": [("escribir_archivo", "diario.txt | dia 1"),
                         ("apendar_archivo", "diario.txt | dia 2")],
    "count_lines_4": [("escribir_archivo", "lista.txt | rojo\nverde\nazul\nnegro"),
                      ("contar_lineas", "lista.txt")],
    "json_make_key": [("escribir_archivo", 'config.json | {"puerto": 8080}'),
                      ("json_validar", "config.json")],
    "json_make_list": [("escribir_archivo", "datos.json | [1, 2, 3]"),
                       ("json_validar", "datos.json")],
    "json_anidado": [("escribir_archivo", 'cfg.json | {"db": {"host": "local", "port": 5432}}'),
                     ("json_validar", "cfg.json")],
    "py_write_validate": [("escribir_archivo", "hola.py | def saludar():\n    return 'hola'"),
                          ("py_validar", "hola.py")],
    "py_sumar": [("escribir_archivo", "suma.py | def sumar(a, b):\n    return a + b"),
                 ("py_validar", "suma.py")],
    "py_write_run": [("escribir_archivo", "calc.py | print(6*7)"),
                     ("py_validar", "calc.py"),
                     ("ejecutar", f'"{__import__("sys").executable}" calc.py')],
    "math_to_file": [("calcular", "15 * 4"), ("escribir_archivo", "resultado.txt | 60")],
    "math_to_file2": [("calcular", "12 * 12"), ("escribir_archivo", "cuadrado.txt | 144")],
    "append_then_count": [("escribir_archivo", "tareas.txt | comprar pan"),
                          ("apendar_archivo", "tareas.txt | lavar ropa"),
                          ("contar_lineas", "tareas.txt")],
    "append_tres": [("escribir_archivo", "agenda.txt | lunes"),
                    ("apendar_archivo", "agenda.txt | martes"),
                    ("apendar_archivo", "agenda.txt | miercoles")],
    "contar_seis": [("escribir_archivo", "colores.txt | rojo\nverde\nazul\nnegro\nblanco\ngris"),
                    ("contar_lineas", "colores.txt")],
    "copiar_dos_veces": [("escribir_archivo", "plantilla.txt | contenido_base"),
                         ("copiar_archivo", "plantilla.txt | copia1.txt"),
                         ("copiar_archivo", "plantilla.txt | copia2.txt")],
    "listar_dir": [("escribir_archivo", "a.txt | x"), ("escribir_archivo", "b.txt | x"),
                   ("escribir_archivo", "c.txt | x"), ("listar", ".")],
    # memoria de trabajo (anotar/notas) — sin ai, estado en ctx
    "anotar_recuperar": [("anotar", "color | azul"), ("notas", "")],
    "anotar_dos": [("anotar", "tarea1 | comprar"), ("anotar", "tarea2 | vender"),
                   ("notas", "")],
    # grafo de conocimiento (kg_agregar/kg_buscar) — requiere ctx["ai"].kg aislado
    "kg_agregar_buscar": [("kg_agregar", "Python | is_a | lenguaje"),
                          ("kg_buscar", "Python")],
    "kg_dos_hechos": [("kg_agregar", "perro | is_a | animal"),
                      ("kg_agregar", "perro | has_property | leal"),
                      ("kg_buscar", "perro")],
}

# Tareas expertas que necesitan un grafo de conocimiento aislado en ctx["ai"].kg
# (gen_expert.py inyecta un KnowledgeGraph sobre una DB temporal por trayectoria,
# para NO tocar la memoria real del usuario).
NEEDS_AI_KG = {"kg_agregar_buscar", "kg_dos_hechos", "kg_eval"}


# Tareas reservadas SOLO para evaluación (nunca aportan datos de entrenamiento),
# elegidas para cubrir herramientas diversas -> mide GENERALIZACIÓN, no memoria.
# Fase B suma held-out de memoria de trabajo, KG y multi-paso (json/append).
EVAL_IDS = {
    "math_pow", "append_two_lines", "copy_file",
    "search_word", "count_5_lines", "shell_echo",
    "anotar_eval", "kg_eval", "json_eval", "append_eval",
}


def train_tasks():
    return [t for t in TASKS if t["id"] not in EVAL_IDS]


def eval_tasks():
    return [t for t in TASKS if t["id"] in EVAL_IDS]


def expert_tasks():
    """Tareas con trayectoria experta scripted (para gen_expert.py). Excluye las
    reservadas a eval (no deben aportar datos de entrenamiento)."""
    return [t for t in TASKS if t["id"] in EXPERT_STEPS and t["id"] not in EVAL_IDS]
