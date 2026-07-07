"""Banco HELD-OUT de tareas para la suite G2-ACCION (gate G2A, P0-ii/DC-10).

46 tareas de tool-use formato ACCION, TODAS con superficie NUEVA (nombres de
archivo, valores y palabras distintos de las 42 tareas de train en
cognia_v3/training/tooluse/tasks.py). Estas tareas NUNCA aportan datos de
entrenamiento: existen solo para generar la suite congelada g2_accion.jsonl
(gen_g2_accion.py las ejecuta con trayectorias expertas scripted contra las
tools REALES, verifica la postcondicion, y corta cada trayectoria en items de
eval por paso: seleccion de primera accion + pasos multi-paso teacher-forced +
cierre `responder`).

Cada tarea:
    id           -> slug unico (prefijo g2a_)
    prompt       -> pedido en espanol (formato del deploy)
    dominio      -> familia (archivo/json/py/calc/busqueda/fecha/memoria/kg/shell/mixta)
    expert_steps -> [(tool, args)] secuencia correcta a ejecutar
    first_alt    -> tools alternativas validas para el PRIMER paso (ambiguedad real)
    needs_kg     -> True si necesita KnowledgeGraph aislado
    verify       -> fn(ws, transcript, answer) -> bool  (postcondicion; gate de
                    entrada del item a la suite, NO se usa en el kernel)
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# ── helpers de verificación (mismo patrón que training/tooluse/tasks.py) ──

def _read(ws: Path, name: str) -> str:
    p = ws / name
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _lines(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _has(transcript: str, needle: str) -> bool:
    return needle.lower() in transcript.lower()


def _json_load(ws: Path, name: str):
    try:
        return json.loads(_read(ws, name))
    except Exception:
        return None


def _py_ok(ws: Path, name: str) -> bool:
    import ast
    src = _read(ws, name)
    if not src:
        return False
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def _calc_equals(transcript: str, value) -> bool:
    v = str(value)
    return bool(re.search(rf"=\s*{re.escape(v)}(?:\.0+)?\b", transcript))


TASKS = [
    # ── A. archivo: escribir single ──────────────────────────────────────
    {
        "id": "g2a_write_nota",
        "prompt": "Crea un archivo notas_reunion.txt con exactamente este contenido: acta pendiente",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "notas_reunion.txt | acta pendiente")],
        "verify": lambda ws, t, a: _read(ws, "notas_reunion.txt").strip().lower() == "acta pendiente",
    },
    {
        "id": "g2a_write_ml",
        "prompt": "Crea compras.txt que tenga tres lineas en este orden: leche, despues cafe, despues azucar (cada una en su propia linea).",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "compras.txt | leche\ncafe\nazucar")],
        "verify": lambda ws, t, a: [x.lower() for x in _lines(_read(ws, "compras.txt"))] == ["leche", "cafe", "azucar"],
    },
    {
        "id": "g2a_write_sub",
        "prompt": "Genera el archivo docs/leeme.txt (queda dentro de la subcarpeta docs) con el texto version uno.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "docs/leeme.txt | version uno")],
        "verify": lambda ws, t, a: _read(ws, "docs/leeme.txt").strip().lower() == "version uno",
    },
    {
        "id": "g2a_write_num",
        "prompt": "Crea numero.txt cuyo contenido sea exactamente 777.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "numero.txt | 777")],
        "verify": lambda ws, t, a: _read(ws, "numero.txt").strip() == "777",
    },
    # ── B. archivo: multi-paso ───────────────────────────────────────────
    {
        "id": "g2a_append_bitacora",
        "prompt": "Crea bitacora.txt con la linea 'turno manana', y despues agrega al final la linea 'turno tarde'.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "bitacora.txt | turno manana"),
                         ("apendar_archivo", "bitacora.txt | turno tarde")],
        "verify": lambda ws, t, a: (lambda L: len(L) == 2 and L[0].lower() == "turno manana" and L[1].lower() == "turno tarde")(_lines(_read(ws, "bitacora.txt"))),
    },
    {
        "id": "g2a_append_count",
        "prompt": "Crea eventos.txt con la linea 'evento a'. Agrega al final 'evento b' y despues 'evento c'. Al final conta cuantas lineas tiene.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "eventos.txt | evento a"),
                         ("apendar_archivo", "eventos.txt | evento b"),
                         ("apendar_archivo", "eventos.txt | evento c"),
                         ("contar_lineas", "eventos.txt")],
        "verify": lambda ws, t, a: len(_lines(_read(ws, "eventos.txt"))) == 3 and _has(t, "3 lineas"),
    },
    {
        "id": "g2a_read_confirm",
        "prompt": "Crea token.txt con el texto token_abc_55, y despues leelo para confirmar su contenido.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "token.txt | token_abc_55"),
                         ("leer_archivo", "token.txt")],
        "verify": lambda ws, t, a: "token_abc_55" in _read(ws, "token.txt") and _has(t, "token_abc_55"),
    },
    {
        "id": "g2a_copy",
        "prompt": "Crea base.txt con el texto duplicame. Despues copialo a un archivo respaldo.txt.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "base.txt | duplicame"),
                         ("copiar_archivo", "base.txt | respaldo.txt")],
        "verify": lambda ws, t, a: _read(ws, "respaldo.txt").strip().lower() == "duplicame",
    },
    {
        "id": "g2a_copy_rename",
        "prompt": "Crea informe.txt con el texto borrador v2. Despues copialo a informe_final.txt.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "informe.txt | borrador v2"),
                         ("copiar_archivo", "informe.txt | informe_final.txt")],
        "verify": lambda ws, t, a: _read(ws, "informe_final.txt").strip().lower() == "borrador v2",
    },
    {
        "id": "g2a_count7",
        "prompt": "Crea dias.txt con 7 lineas exactas: lunes, martes, miercoles, jueves, viernes, sabado, domingo (cada dia en su linea). Al final medi el numero de lineas del archivo.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "dias.txt | lunes\nmartes\nmiercoles\njueves\nviernes\nsabado\ndomingo"),
                         ("contar_lineas", "dias.txt")],
        "verify": lambda ws, t, a: len(_lines(_read(ws, "dias.txt"))) == 7 and _has(t, "7 lineas"),
    },
    {
        "id": "g2a_append_read",
        "prompt": "Crea temario.txt con la linea 'tema uno'. Agrega al final la linea 'tema dos'. Despues leelo para confirmar.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "temario.txt | tema uno"),
                         ("apendar_archivo", "temario.txt | tema dos"),
                         ("leer_archivo", "temario.txt")],
        "verify": lambda ws, t, a: len(_lines(_read(ws, "temario.txt"))) == 2 and _has(t, "tema dos"),
    },
    {
        "id": "g2a_write3_listar",
        "prompt": "Crea tres archivos x1.txt, x2.txt y x3.txt con el contenido que quieras, y luego mostra un listado del directorio actual.",
        "dominio": "archivo",
        "expert_steps": [("escribir_archivo", "x1.txt | x"),
                         ("escribir_archivo", "x2.txt | x"),
                         ("escribir_archivo", "x3.txt | x"),
                         ("listar", ".")],
        "verify": lambda ws, t, a: all((ws / f).is_file() for f in ("x1.txt", "x2.txt", "x3.txt")) and _has(t, "resultado listar"),
    },
    # ── C. json ──────────────────────────────────────────────────────────
    {
        "id": "g2a_json_timeout",
        "prompt": "Crea red.json que contenga JSON valido donde la clave \"timeout\" valga 30, y validalo al final.",
        "dominio": "json",
        "expert_steps": [("escribir_archivo", 'red.json | {"timeout": 30}'),
                         ("json_validar", "red.json")],
        "verify": lambda ws, t, a: (_json_load(ws, "red.json") or {}).get("timeout") == 30 and _has(t, "json valido"),
    },
    {
        "id": "g2a_json_lista",
        "prompt": "Crea pares.json que contenga JSON valido: una lista formada por los numeros 2, 4 y 6. Validalo al final.",
        "dominio": "json",
        "expert_steps": [("escribir_archivo", "pares.json | [2, 4, 6]"),
                         ("json_validar", "pares.json")],
        "verify": lambda ws, t, a: _json_load(ws, "pares.json") == [2, 4, 6] and _has(t, "json valido"),
    },
    {
        "id": "g2a_json_anidado",
        "prompt": "Crea app.json que contenga JSON valido donde la clave \"ui\" sea un objeto con \"tema\" en \"oscuro\" y \"zoom\" en 2. Validalo al final.",
        "dominio": "json",
        "expert_steps": [("escribir_archivo", 'app.json | {"ui": {"tema": "oscuro", "zoom": 2}}'),
                         ("json_validar", "app.json")],
        "verify": lambda ws, t, a: (_json_load(ws, "app.json") or {}).get("ui", {}).get("zoom") == 2 and _has(t, "json valido"),
    },
    {
        "id": "g2a_json_bool",
        "prompt": "Crea flags.json que contenga JSON valido donde la clave \"debug\" valga false. Validalo al final.",
        "dominio": "json",
        "expert_steps": [("escribir_archivo", 'flags.json | {"debug": false}'),
                         ("json_validar", "flags.json")],
        "verify": lambda ws, t, a: (_json_load(ws, "flags.json") or {}).get("debug") is False and _has(t, "json valido"),
    },
    # ── D. python ────────────────────────────────────────────────────────
    {
        "id": "g2a_py_resta",
        "prompt": "Escribi resta.py con una funcion que reste dos numeros, restar(a, b), devolviendo a - b. Luego revisa que la sintaxis sea correcta.",
        "dominio": "py",
        "expert_steps": [("escribir_archivo", "resta.py | def restar(a, b):\n    return a - b"),
                         ("py_validar", "resta.py")],
        "verify": lambda ws, t, a: _py_ok(ws, "resta.py") and "def restar" in _read(ws, "resta.py") and _has(t, "sintaxis ok"),
    },
    {
        "id": "g2a_py_run",
        "prompt": "Escribi cuenta.py que imprima el resultado de 9*9. Revisa que la sintaxis sea correcta y luego corre: python cuenta.py",
        "dominio": "py",
        "expert_steps": [("escribir_archivo", "cuenta.py | print(9*9)"),
                         ("py_validar", "cuenta.py"),
                         ("ejecutar", "__PYTHON__ cuenta.py")],
        "verify": lambda ws, t, a: _py_ok(ws, "cuenta.py") and _has(t, "81"),
    },
    {
        "id": "g2a_py_mayus",
        "prompt": "Escribi un archivo mayus.py que defina una funcion gritar(s) que retorne s.upper(). Despues valida su sintaxis.",
        "dominio": "py",
        "expert_steps": [("escribir_archivo", "mayus.py | def gritar(s):\n    return s.upper()"),
                         ("py_validar", "mayus.py")],
        "verify": lambda ws, t, a: _py_ok(ws, "mayus.py") and "def gritar" in _read(ws, "mayus.py") and _has(t, "sintaxis ok"),
    },
    {
        "id": "g2a_py_run2",
        "prompt": "Escribi potencia.py que imprima el resultado de 5**3. Revisa que la sintaxis sea correcta y luego corre: python potencia.py",
        "dominio": "py",
        "expert_steps": [("escribir_archivo", "potencia.py | print(5**3)"),
                         ("py_validar", "potencia.py"),
                         ("ejecutar", "__PYTHON__ potencia.py")],
        "verify": lambda ws, t, a: _py_ok(ws, "potencia.py") and _has(t, "125"),
    },
    # ── E. calcular single ───────────────────────────────────────────────
    {
        "id": "g2a_math_mul",
        "prompt": "Cuanto da 31 multiplicado por 17? Resolvelo con la herramienta de calculo e informa el valor.",
        "dominio": "calc",
        "expert_steps": [("calcular", "31 * 17")],
        "verify": lambda ws, t, a: _calc_equals(t, 527),
    },
    {
        "id": "g2a_math_div",
        "prompt": "Calcula 950 dividido 25 y responde el resultado.",
        "dominio": "calc",
        "expert_steps": [("calcular", "950 / 25")],
        "verify": lambda ws, t, a: _calc_equals(t, 38),
    },
    {
        "id": "g2a_math_pow",
        "prompt": "Cuanto es 3 elevado a la 7? Calculalo y responde.",
        "dominio": "calc",
        "expert_steps": [("calcular", "3 ** 7")],
        "verify": lambda ws, t, a: _calc_equals(t, 2187),
    },
    {
        "id": "g2a_math_mod",
        "prompt": "Cual es el resto de dividir 500 entre 9? Calculalo (usa %) y responde.",
        "dominio": "calc",
        "expert_steps": [("calcular", "500 % 9")],
        "verify": lambda ws, t, a: _calc_equals(t, 5),
    },
    {
        "id": "g2a_math_expr",
        "prompt": "Calcula (81 / 9) + 50 y responde el resultado.",
        "dominio": "calc",
        "expert_steps": [("calcular", "(81 / 9) + 50")],
        "verify": lambda ws, t, a: _calc_equals(t, 59),
    },
    # ── F. calcular + guardar ────────────────────────────────────────────
    {
        "id": "g2a_math_save",
        "prompt": "Multiplica 14 por 6 con la calculadora y escribi unicamente ese numero en un archivo producto.txt.",
        "dominio": "mixta",
        "expert_steps": [("calcular", "14 * 6"),
                         ("escribir_archivo", "producto.txt | 84")],
        "verify": lambda ws, t, a: "84" in _read(ws, "producto.txt"),
    },
    {
        "id": "g2a_math_save2",
        "prompt": "Eleva 2 a la 12 con la calculadora y escribi unicamente ese numero en un archivo potencia12.txt.",
        "dominio": "mixta",
        "expert_steps": [("calcular", "2 ** 12"),
                         ("escribir_archivo", "potencia12.txt | 4096")],
        "verify": lambda ws, t, a: "4096" in _read(ws, "potencia12.txt"),
    },
    {
        "id": "g2a_math_save3",
        "prompt": "Suma 45 mas 55 con la calculadora y escribi unicamente ese numero en un archivo total.txt.",
        "dominio": "mixta",
        "expert_steps": [("calcular", "45 + 55"),
                         ("escribir_archivo", "total.txt | 100")],
        "verify": lambda ws, t, a: "100" in _read(ws, "total.txt"),
    },
    # ── G. busqueda / arbol / listar ─────────────────────────────────────
    {
        "id": "g2a_buscar",
        "prompt": "Crea apuntes.txt cuyo contenido incluya la palabra TELESCOPIO. Despues busca 'TELESCOPIO' en el directorio actual.",
        "dominio": "busqueda",
        "expert_steps": [("escribir_archivo", "apuntes.txt | observacion con TELESCOPIO nocturno"),
                         ("buscar", "TELESCOPIO")],
        "verify": lambda ws, t, a: "telescopio" in _read(ws, "apuntes.txt").lower() and _has(t, "telescopio") and not _has(t, "sin resultados"),
    },
    {
        "id": "g2a_buscar2",
        "prompt": "Crea catalogo.txt con varias lineas de plantas, una de ellas con la palabra GIRASOL. Despues busca 'GIRASOL' en el directorio actual.",
        "dominio": "busqueda",
        "expert_steps": [("escribir_archivo", "catalogo.txt | rosa\nGIRASOL amarillo\ntulipan"),
                         ("buscar", "GIRASOL")],
        "verify": lambda ws, t, a: "girasol" in _read(ws, "catalogo.txt").lower() and _has(t, "girasol") and not _has(t, "sin resultados"),
    },
    {
        "id": "g2a_arbol",
        "prompt": "Genera modulos/nucleo.txt (queda dentro de la subcarpeta modulos) con el texto y. Luego mostra el arbol del directorio actual.",
        "dominio": "busqueda",
        "expert_steps": [("escribir_archivo", "modulos/nucleo.txt | y"),
                         ("arbol", ".")],
        "verify": lambda ws, t, a: (ws / "modulos" / "nucleo.txt").is_file() and _has(t, "resultado arbol"),
    },
    {
        "id": "g2a_listar2",
        "prompt": "Crea dos archivos m1.txt y m2.txt con el contenido que quieras, y luego mostra un listado del directorio actual.",
        "dominio": "busqueda",
        "expert_steps": [("escribir_archivo", "m1.txt | m"),
                         ("escribir_archivo", "m2.txt | m"),
                         ("listar", ".")],
        "verify": lambda ws, t, a: all((ws / f).is_file() for f in ("m1.txt", "m2.txt")) and _has(t, "resultado listar"),
    },
    # ── H. fecha ─────────────────────────────────────────────────────────
    {
        "id": "g2a_fecha",
        "prompt": "Consulta con la herramienta adecuada que fecha y hora es ahora mismo, y decimelo.",
        "dominio": "fecha",
        "expert_steps": [("fecha", "")],
        "verify": lambda ws, t, a: bool(re.search(r"\d{4}-\d{2}-\d{2}", t)),
    },
    {
        "id": "g2a_fecha_save",
        "prompt": "Consulta la fecha actual con la herramienta correspondiente y despues guarda esa fecha en un archivo hoy.txt.",
        "dominio": "mixta",
        "expert_steps": [("fecha", ""),
                         ("escribir_archivo", "hoy.txt | 2026-07-07")],
        "verify": lambda ws, t, a: bool(re.search(r"\d{4}-\d{2}-\d{2}", _read(ws, "hoy.txt"))),
    },
    # ── I. memoria de trabajo (anotar/notas) ─────────────────────────────
    {
        "id": "g2a_anotar",
        "prompt": "Registra en tus notas de trabajo la clave 'idioma' con el valor 'frances'; revisalas despues para confirmar.",
        "dominio": "memoria",
        "expert_steps": [("anotar", "idioma | frances"),
                         ("notas", "")],
        "verify": lambda ws, t, a: "idioma: frances" in t.lower(),
    },
    {
        "id": "g2a_anotar2",
        "prompt": "Guarda dos entradas en tus notas de trabajo: 'meta' con 'terminar' y 'plazo' con 'viernes'; luego mostralas.",
        "dominio": "memoria",
        "expert_steps": [("anotar", "meta | terminar"),
                         ("anotar", "plazo | viernes"),
                         ("notas", "")],
        "verify": lambda ws, t, a: _has(t, "terminar") and _has(t, "viernes") and _has(t, "meta"),
    },
    {
        "id": "g2a_anotar3",
        "prompt": "Registra en tus notas de trabajo la clave 'animal' con el valor 'gato'; revisalas despues.",
        "dominio": "memoria",
        "expert_steps": [("anotar", "animal | gato"),
                         ("notas", "")],
        "verify": lambda ws, t, a: "animal: gato" in t.lower(),
    },
    {
        "id": "g2a_anotar_calc",
        "prompt": "Calcula 6 por 9 con la herramienta de calculo, anota el resultado en tu memoria de trabajo bajo la clave 'resultado', y despues consulta tus notas.",
        "dominio": "mixta",
        "expert_steps": [("calcular", "6 * 9"),
                         ("anotar", "resultado | 54"),
                         ("notas", "")],
        "verify": lambda ws, t, a: "resultado: 54" in t.lower(),
    },
    # ── J. grafo de conocimiento ─────────────────────────────────────────
    {
        "id": "g2a_kg_rust",
        "prompt": "Suma este hecho al grafo de conocimiento: Rust is_a lenguaje. Luego consulta que contiene el grafo acerca de Rust.",
        "dominio": "kg",
        "needs_kg": True,
        "expert_steps": [("kg_agregar", "Rust | is_a | lenguaje"),
                         ("kg_buscar", "Rust")],
        "verify": lambda ws, t, a: _has(t, "rust") and _has(t, "lenguaje") and not _has(t, "sin hechos"),
    },
    {
        "id": "g2a_kg_luna",
        "prompt": "Suma este hecho al grafo de conocimiento: luna related_to tierra. Luego consulta que contiene el grafo acerca de luna.",
        "dominio": "kg",
        "needs_kg": True,
        "expert_steps": [("kg_agregar", "luna | related_to | tierra"),
                         ("kg_buscar", "luna")],
        "verify": lambda ws, t, a: _has(t, "luna") and _has(t, "tierra") and not _has(t, "sin hechos"),
    },
    {
        "id": "g2a_kg_gaudi",
        "prompt": "Suma estos dos hechos al grafo de conocimiento: 'Gaudi is_a arquitecto' y 'Gaudi located_in Barcelona'. Luego consulta que contiene el grafo acerca de Gaudi.",
        "dominio": "kg",
        "needs_kg": True,
        "expert_steps": [("kg_agregar", "Gaudi | is_a | arquitecto"),
                         ("kg_agregar", "Gaudi | located_in | Barcelona"),
                         ("kg_buscar", "Gaudi")],
        "verify": lambda ws, t, a: _has(t, "arquitecto") and not _has(t, "sin hechos"),
    },
    {
        "id": "g2a_kg_sol",
        "prompt": "Suma este hecho al grafo de conocimiento: sol is_a estrella. Luego consulta que contiene el grafo acerca de sol.",
        "dominio": "kg",
        "needs_kg": True,
        "expert_steps": [("kg_agregar", "sol | is_a | estrella"),
                         ("kg_buscar", "sol")],
        "verify": lambda ws, t, a: _has(t, "sol") and _has(t, "estrella") and not _has(t, "sin hechos"),
    },
    # ── K. shell ─────────────────────────────────────────────────────────
    {
        "id": "g2a_shell_echo",
        "prompt": "Ejecuta el comando de shell: echo prueba_g2a_ok",
        "dominio": "shell",
        "expert_steps": [("ejecutar", "echo prueba_g2a_ok")],
        "verify": lambda ws, t, a: bool(re.search(r"resultado ejecutar:\s*[^\n]*prueba_g2a_ok", t, re.IGNORECASE)),
    },
    {
        "id": "g2a_shell_echo2",
        "prompt": "Ejecuta el comando de shell: echo canal_listo",
        "dominio": "shell",
        "expert_steps": [("ejecutar", "echo canal_listo")],
        "verify": lambda ws, t, a: bool(re.search(r"resultado ejecutar:\s*[^\n]*canal_listo", t, re.IGNORECASE)),
    },
    # ── L. mixtas multi-paso largas ──────────────────────────────────────
    {
        "id": "g2a_mix_json_read",
        "prompt": "Crea estado.json que contenga JSON valido donde la clave \"fase\" valga 3. Validalo al final, y despues leelo para confirmar.",
        "dominio": "mixta",
        "expert_steps": [("escribir_archivo", 'estado.json | {"fase": 3}'),
                         ("json_validar", "estado.json"),
                         ("leer_archivo", "estado.json")],
        "verify": lambda ws, t, a: (_json_load(ws, "estado.json") or {}).get("fase") == 3 and _has(t, "json valido"),
    },
    {
        "id": "g2a_mix_copy_count",
        "prompt": "Crea fuente.txt con dos lineas: alfa y beta (una por linea). Copialo a copia_f.txt y despues conta cuantas lineas tiene copia_f.txt.",
        "dominio": "mixta",
        "expert_steps": [("escribir_archivo", "fuente.txt | alfa\nbeta"),
                         ("copiar_archivo", "fuente.txt | copia_f.txt"),
                         ("contar_lineas", "copia_f.txt")],
        "verify": lambda ws, t, a: len(_lines(_read(ws, "copia_f.txt"))) == 2 and _has(t, "2 lineas"),
    },
    {
        "id": "g2a_mix_write_search",
        "prompt": "Crea indice.txt cuyo contenido incluya la palabra BRUJULA. Despues busca 'BRUJULA' en el directorio actual, y al final conta cuantas lineas tiene indice.txt.",
        "dominio": "mixta",
        "expert_steps": [("escribir_archivo", "indice.txt | mapa con BRUJULA dorada"),
                         ("buscar", "BRUJULA"),
                         ("contar_lineas", "indice.txt")],
        "verify": lambda ws, t, a: "brujula" in _read(ws, "indice.txt").lower() and _has(t, "brujula") and _has(t, "1 lineas"),
    },
    {
        "id": "g2a_mix_anotar_save",
        "prompt": "Registra en tus notas de trabajo la clave 'codigo' con el valor 'omega9'. Mostra tus notas, y despues escribi el texto omega9 en un archivo codigo.txt.",
        "dominio": "mixta",
        "expert_steps": [("anotar", "codigo | omega9"),
                         ("notas", ""),
                         ("escribir_archivo", "codigo.txt | omega9")],
        "verify": lambda ws, t, a: "omega9" in _read(ws, "codigo.txt") and "codigo: omega9" in t.lower(),
    },
]


def by_id(task_id: str):
    for t in TASKS:
        if t["id"] == task_id:
            return t
    return None
