"""
Checker AST para el harness BFCL-slice (cognia_v3/eval/bench_bfcl_slice.py).

PORT MINIMO del eval_checker oficial de Gorilla/BFCL:
  github.com/ShishirPatil/gorilla, commit congelado
  cd9429ccf3d4d04156affe883c495b3b047e6b64 (ultimo commit ANTES del rename a
  BFCL v4 — el mismo commit del que se descargaron los datos), archivos:
    berkeley-function-call-leaderboard/bfcl_eval/eval_checker/ast_eval/ast_checker.py
    berkeley-function-call-leaderboard/bfcl_eval/model_handler/utils.py (ast_parse,
      resolve_ast_call, resolve_ast_by_type, default_decode_ast_prompting)
Licencia del original: Apache-2.0 (mismo repo). No se instala el paquete
`bfcl-eval` (arrastra deps pesadas de inferencia); la logica de chequeo se
reescribe standalone aca con el mismo comportamiento para las 5 categorias
prompt-based que usa nuestra slice (simple, multiple, parallel,
parallel_multiple, live_simple) — todas categoria "Python" en BFCL.

SIMPLIFICACIONES DECLARADAS respecto al original (todas se declaran, ninguna
se esconde):
  1. Sin Java ni JavaScript: solo el branch "Python" de simple_function_checker
     (nuestras 5 categorias son 100% Python — verificado sobre los datos
     descargados, 0 items con parametros no-Python).
  2. Sin MODEL_CONFIG_MAPPING: el original convierte "." -> "_" en el nombre
     de funcion SOLO para modelos que no soportan "." (OpenAI, etc), leyendo
     una tabla de configuracion por modelo. Nosotros no tenemos esa tabla
     (modelo propio via llama.cpp) asi que en su lugar TOLERAMOS ambas formas
     al comparar: si el nombre con puntos no matchea, se prueba la variante
     con "." reemplazado por "_" (mangling) — cubre el caso real (el 3B
     reproduce el nombre "tal cual" o mangled) sin depender de una tabla que
     no aplica a nuestro backend.
  3. parse_model_response (mas abajo) reemplaza a ast_parse/
     default_decode_ast_prompting: el original espera el formato nativo BFCL
     `[func1(a=1), func2(b=2)]` (una lista Python); nuestro prompt pide
     `func1(a=1); func2(b=2)` (llamadas separadas por ';', ver bench_bfcl_
     slice.SYSTEM_PROMPT) porque asi lo fija el enunciado de esta tarea. El
     parser reescrito localiza cada llamada `nombre(...)` balanceando
     parentesis/comillas (tolera prosa alrededor y comas dentro de los args,
     igual que extract_code() en benchmark_code.py tolera fences rotos) y
     parsea cada una por separado con ast.parse(..., mode="eval"); no
     depende de que el separador global sea coma.
  4. resolve_ast_by_type: solo constantes, listas, dicts, tuplas y unario
     negativo (-N). Sin soporte para BinOp/Lambda/Call-anidado como valor de
     argumento (el original los evalua con eval() para tolerar casos raros
     de las categorias multi-turn/agentic — nuestras 5 categorias
     single-turn no los usan; verificado: 0 casos en los datos descargados
     donde el valor esperado de un parametro sea el resultado de otra
     llamada).
  5. type_checker / dict_checker / list_dict_checker: portados casi
     verbatim (misma logica, mismos mensajes de error) porque son cortos y
     la fidelidad importa para el oraculo. dict/list-of-dict anidado se
     chequea a UN nivel de profundidad, igual que el original (limitacion
     documentada arriba del checker oficial, no nuestra).
"""
from __future__ import annotations

import ast
import re

# ---------------------------------------------------------------------------
# Constantes (branch Python de PYTHON_TYPE_MAPPING en el original)
# ---------------------------------------------------------------------------

PYTHON_TYPE_MAPPING = {
    "string": str, "integer": int, "float": float, "boolean": bool,
    "array": list, "tuple": list, "dict": dict, "any": str,
}
PYTHON_NESTED_TYPE_CHECK_LIST = ["array", "tuple"]


# ---------------------------------------------------------------------------
# Parser de la respuesta del modelo: "func(a=1, b='x'); func2(c=2)" -> calls
# ---------------------------------------------------------------------------

_CALL_START_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\s*\(")
_CODE_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n?(.*?)```", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Si la respuesta viene en un bloque ```...``` se usa solo el contenido
    (el modelo puede envolver las llamadas en markdown pese al system prompt)."""
    m = _CODE_FENCE_RE.search(text)
    return m.group(1).strip() if m else text


def _find_matching_paren(text: str, open_idx: int) -> int | None:
    """Indice del ')' que cierra el '(' en open_idx, respetando comillas y
    parentesis anidados. None si el parentesis nunca cierra (respuesta
    cortada por max_tokens)."""
    depth = 0
    i = open_idx
    quote = None
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _resolve_value(node: ast.AST):
    """Literal Python de un nodo AST: constantes, listas, dicts, tuplas y
    unario negativo. Ver simplificacion #4 del docstring del modulo."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_resolve_value(node.operand)
    if isinstance(node, ast.List):
        return [_resolve_value(v) for v in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_resolve_value(v) for v in node.elts)
    if isinstance(node, ast.Dict):
        return {_resolve_value(k): _resolve_value(v)
                for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Name):
        # Variable sin resolver (rara en single-turn): se trata como string
        # con su propio nombre, igual que el "is_variable" del original.
        return node.id
    raise ValueError(f"tipo de nodo AST no soportado: {type(node).__name__}")


def _resolve_call(call_node: ast.Call) -> dict:
    """{func_name: {param: value}} de un ast.Call (solo keyword args, igual
    que el formato nativo BFCL — no soportamos args posicionales)."""
    func_parts = []
    func_part = call_node.func
    while isinstance(func_part, ast.Attribute):
        func_parts.append(func_part.attr)
        func_part = func_part.value
    if isinstance(func_part, ast.Name):
        func_parts.append(func_part.id)
    func_name = ".".join(reversed(func_parts))
    args = {kw.arg: _resolve_value(kw.value) for kw in call_node.keywords
            if kw.arg is not None}
    return {func_name: args}


def parse_model_response(text: str) -> tuple[list[dict], str | None]:
    """
    Extrae llamadas `func(param=value)` de la respuesta cruda del modelo.
    Devuelve (calls, error_type). calls = [{func_name: {param: value}}, ...]
    en orden de aparicion. error_type es None si se parseo >=1 llamada;
    "empty" si la respuesta esta vacia, "no_calls_parsed" si no se encontro
    ninguna llamada valida (todo prosa o sintaxis rota).

    Tolera: fences markdown, prosa antes/despues/entre llamadas, separador
    ';' o ',' o salto de linea entre llamadas (se ignora todo lo que no sea
    una llamada balanceada) — misma filosofia que extract_code() en
    benchmark_code.py: recuperar lo bueno de una respuesta imperfecta en vez
    de exigir formato exacto.
    """
    if not text or not text.strip():
        return [], "empty"
    text = _strip_code_fence(text)
    calls = []
    idx = 0
    for m in _CALL_START_RE.finditer(text):
        start = m.start()
        if start < idx:
            continue  # ya consumido dentro de una llamada anterior
        open_paren = m.end() - 1
        end = _find_matching_paren(text, open_paren)
        if end is None:
            break  # parentesis sin cerrar: probablemente corte por max_tokens
        call_src = text[start:end + 1]
        idx = end + 1
        try:
            tree = ast.parse(call_src, mode="eval")
        except SyntaxError:
            continue  # substring no parsea como llamada valida: se ignora
        if not isinstance(tree.body, ast.Call):
            continue
        try:
            calls.append(_resolve_call(tree.body))
        except ValueError:
            continue
    if not calls:
        return [], "no_calls_parsed"
    return calls, None


# ---------------------------------------------------------------------------
# Checker AST (port de ast_checker.py, branch Python unicamente)
# ---------------------------------------------------------------------------

def find_description(func_descriptions: list[dict], name: str) -> dict | None:
    """Descripcion de la funcion `name` dentro de la lista de tools
    disponibles (usado por multiple/parallel_multiple, donde hay >1 opcion)."""
    for fd in func_descriptions:
        if fd["name"] == name:
            return fd
    return None


def get_possible_answer_type(possible_answer: list):
    for answer in possible_answer:
        if answer != "":  # "" marca parametro opcional
            return type(answer)
    return None


def standardize_string(s: str) -> str:
    """Normaliza espacios/puntuacion menor para comparar strings sin
    castigar variantes de formato equivalentes (p.ej. 'April 1, 2024' vs
    'April 1 2024')."""
    return re.sub(r"[ \,\.\/\-\_\*\^]", "", s).lower().replace("'", '"')


def type_checker(param: str, value, possible_answer: list,
                 expected_type_description: str, expected_type_converted,
                 nested_type_converted) -> dict:
    """Solo chequea 1 nivel de anidamiento (misma limitacion documentada en
    el original: no vale la pena la recursion completa para este dataset)."""
    result = {"valid": True, "error": [], "is_variable": False,
              "error_type": "type_error:simple"}
    possible_answer_type = get_possible_answer_type(possible_answer)
    is_variable = (possible_answer_type is not None
                   and possible_answer_type != expected_type_converted)

    if type(value) == expected_type_converted:
        if nested_type_converted is None:
            result["is_variable"] = is_variable
            return result
        for possible_answer_item in possible_answer:
            if type(possible_answer_item) != list:
                continue
            flag = True
            for value_item in value:
                sub = type_checker(param, value_item, possible_answer_item,
                                   str(nested_type_converted),
                                   nested_type_converted, None)
                if not sub["valid"]:
                    flag = False
                    break
            if flag:
                return {"valid": True, "error": [], "is_variable": is_variable}
        result["valid"] = False
        result["error"] = [
            f"Nested type checking failed for parameter {param!r}. Expected "
            f"outer type {expected_type_description} with inner type "
            f"{nested_type_converted}. Parameter value: {value!r}."]
        result["error_type"] = "type_error:nested"
        return result

    # Valor de tipo distinto: puede ser una variable (string) sustituyendo
    # al tipo real esperado en possible_answer.
    if possible_answer_type is not None and type(value) == possible_answer_type:
        result["is_variable"] = True
        return result

    result["valid"] = False
    result["error"].append(
        f"Incorrect type for parameter {param!r}. Expected type "
        f"{expected_type_description}, got {type(value).__name__}. "
        f"Parameter value: {value!r}.")
    result["error_type"] = "type_error:simple"
    return result


def string_checker(param: str, model_output: str, possible_answer: list) -> dict:
    std_possible = [standardize_string(a) for a in possible_answer if type(a) == str]
    if standardize_string(model_output) not in std_possible:
        return {"valid": False, "error_type": "value_error:string", "error": [
            f"Invalid value for parameter {param!r}: {model_output!r}. "
            f"Expected one of {possible_answer}. Case insensitive."]}
    return {"valid": True, "error": []}


def list_checker(param: str, model_output: list, possible_answer: list) -> dict:
    std_model = [standardize_string(v) if type(v) == str else v for v in model_output]
    std_possible = []
    for row in possible_answer:
        std_possible.append([standardize_string(v) if type(v) == str else v for v in row])
    if std_model not in std_possible:
        return {"valid": False, "error_type": "value_error:list/tuple", "error": [
            f"Invalid value for parameter {param!r}: {model_output!r}. "
            f"Expected one of {possible_answer}."]}
    return {"valid": True, "error": []}


def dict_checker(param: str, model_output: dict, possible_answers: list) -> dict:
    """Solo dicts simples (sin dicts anidados) — igual que el original."""
    result = {"valid": False, "error": [], "error_type": "dict_checker:unclear"}
    for possible_answer in possible_answers:
        if possible_answer == "":
            continue
        result = {"valid": False, "error": [], "error_type": "dict_checker:unclear"}
        flag = True
        for key, value in model_output.items():
            if key not in possible_answer:
                result["error"].append(f"Unexpected dict key parameter: {key!r}.")
                result["error_type"] = "value_error:dict_key"
                flag = False
                break
            std_value = standardize_string(value) if type(value) == str else value
            std_possible = [standardize_string(v) if type(v) == str else v
                           for v in possible_answer[key]]
            if std_value not in std_possible:
                result["error"].append(
                    f"Invalid value for parameter {key!r}: {value!r}. "
                    f"Expected one of {std_possible}.")
                result["error_type"] = "value_error:dict_value"
                flag = False
                break
        if flag:
            for key, value in possible_answer.items():
                if key not in model_output and "" not in value:
                    result["error"].append(f"Missing dict key parameter: {key!r}.")
                    result["error_type"] = "value_error:dict_key"
                    flag = False
                    break
        if flag:
            return {"valid": True, "error": []}
    return result


def list_dict_checker(param: str, model_output: list, possible_answers: list) -> dict:
    result = {"valid": False, "error": [], "error_type": "list_dict_checker:unclear"}
    for answer in possible_answers:
        if len(model_output) != len(answer):
            result = {"valid": False, "error_type": "value_error:list_dict_count",
                      "error": ["Wrong number of dictionaries in the list."]}
            continue
        flag = True
        for i, item in enumerate(model_output):
            result = dict_checker(param, item, [answer[i]])
            if not result["valid"]:
                flag = False
                break
        if flag:
            return {"valid": True, "error": []}
    return result


def simple_function_checker(func_description: dict, model_output: dict,
                            possible_answer: dict) -> dict:
    """possible_answer = {func_name: {param: [valores aceptables]}} (un solo
    elemento de la lista ground_truth)."""
    possible_answer_params = list(possible_answer.values())[0]
    func_name = func_description["name"]
    param_details = func_description["parameters"]["properties"]
    required_params = func_description["parameters"]["required"]

    result = {"valid": True, "error": [], "error_type": "simple_function_checker:unclear"}

    # Tolerancia al mangling de puntos (simplificacion #2 del docstring):
    # el modelo puede reproducir "math.hypot" o "math_hypot".
    if func_name not in model_output:
        mangled = func_name.replace(".", "_")
        if mangled in model_output:
            func_name = mangled
        else:
            result["valid"] = False
            result["error"].append(
                f"Function name {func_name!r} not found in model output.")
            result["error_type"] = "simple_function_checker:wrong_func_name"
            return result

    model_params = model_output[func_name]

    for param in required_params:
        if param not in model_params:
            result["valid"] = False
            result["error"].append(f"Missing required parameter: {param!r}.")
            result["error_type"] = "simple_function_checker:missing_required"
            return result

    for param, value in model_params.items():
        if param not in param_details or param not in possible_answer_params:
            result["valid"] = False
            result["error"].append(f"Unexpected parameter: {param!r}.")
            result["error_type"] = "simple_function_checker:unexpected_param"
            return result

        expected_type_description = param_details[param]["type"]
        expected_type_converted = PYTHON_TYPE_MAPPING[expected_type_description]
        nested_type_converted = None
        if expected_type_description in PYTHON_NESTED_TYPE_CHECK_LIST:
            nested_type = param_details[param]["items"]["type"]
            nested_type_converted = PYTHON_TYPE_MAPPING[nested_type]

        if expected_type_description == "tuple" and type(value) == tuple:
            value = list(value)
        if expected_type_description == "float" and type(value) == int:
            value = float(value)

        type_result = type_checker(param, value, possible_answer_params[param],
                                   expected_type_description,
                                   expected_type_converted, nested_type_converted)
        is_variable = type_result["is_variable"]
        if not type_result["valid"]:
            return type_result

        if not is_variable:
            if expected_type_converted == dict:
                sub = dict_checker(param, value, possible_answer_params[param])
                if not sub["valid"]:
                    return sub
                continue
            if expected_type_converted == list and nested_type_converted == dict:
                sub = list_dict_checker(param, value, possible_answer_params[param])
                if not sub["valid"]:
                    return sub
                continue
            if expected_type_converted == str:
                sub = string_checker(param, value, possible_answer_params[param])
                if not sub["valid"]:
                    return sub
                continue
            if expected_type_converted == list:
                sub = list_checker(param, value, possible_answer_params[param])
                if not sub["valid"]:
                    return sub
                continue

        if value not in possible_answer_params[param]:
            result["valid"] = False
            result["error"].append(
                f"Invalid value for parameter {param!r}: {value!r}. "
                f"Expected one of {possible_answer_params[param]}.")
            result["error_type"] = "value_error:others"
            return result

    for param in possible_answer_params:
        if param not in model_params and "" not in possible_answer_params[param]:
            result["valid"] = False
            result["error"].append(
                f"Optional parameter {param!r} not provided and not marked as optional.")
            result["error_type"] = "simple_function_checker:missing_optional"
            return result

    return result


def parallel_function_checker_no_order(func_descriptions: list, model_output: list,
                                       possible_answers: list) -> dict:
    """Las llamadas pueden venir en cualquier orden: cada ground-truth busca
    su match entre las llamadas del modelo aun no emparejadas."""
    if len(model_output) != len(possible_answers):
        return {"valid": False, "error_type": "parallel_function_checker_no_order:wrong_count",
                "error": ["Wrong number of functions."]}

    matched = set()
    for expected in possible_answers:
        func_name_expected = list(expected.keys())[0]
        func_description = find_description(func_descriptions, func_name_expected)
        result = None
        for i, out in enumerate(model_output):
            if i in matched:
                continue
            result = simple_function_checker(func_description, out, expected)
            if result["valid"]:
                matched.add(i)
                break
        if result is None or not result["valid"]:
            return result or {"valid": False, "error_type": "parallel_function_checker_no_order:cannot_find_match",
                              "error": ["No matching function found."]}
    return {"valid": True, "error": []}


def multiple_function_checker(func_descriptions: list, model_output: list,
                              possible_answers: list) -> dict:
    """Categoria 'multiple': N funciones disponibles, el modelo elige 1."""
    if len(model_output) != len(possible_answers):
        return {"valid": False, "error_type": "multiple_function_checker:wrong_count",
                "error": ["Wrong number of functions."]}
    func_name_expected = list(possible_answers[0].keys())[0]
    func_description = find_description(func_descriptions, func_name_expected)
    return simple_function_checker(func_description, model_output[0], possible_answers[0])


def ast_checker(func_descriptions: list, model_output: list, possible_answer: list,
               test_category: str) -> dict:
    """
    Entry point. Dispatch por substring de test_category (mismo orden que
    el original: "parallel" ANTES que "multiple" — parallel_multiple cae en
    el branch parallel, que ya resuelve la funcion correcta por nombre via
    find_description, cubriendo tambien el caso de multiples funciones
    disponibles).
    """
    if "parallel" in test_category:
        return parallel_function_checker_no_order(
            func_descriptions, model_output, possible_answer)
    if "multiple" in test_category:
        return multiple_function_checker(
            func_descriptions, model_output, possible_answer)
    if len(model_output) != 1:
        return {"valid": False, "error_type": "simple_function_checker:wrong_count",
                "error": ["Wrong number of functions."]}
    return simple_function_checker(func_descriptions[0], model_output[0], possible_answer[0])


def check_response(category: str, functions: list, ground_truth: list,
                   response_text: str) -> tuple[bool, str, str]:
    """
    Punto de entrada del harness: texto crudo del modelo -> (passed,
    error_type, error_detail). Junta parse_model_response + ast_checker.
    error_type: "empty" | "no_calls_parsed" | el error_type del checker AST
    (ver los distintos *_checker de arriba) | "" si passed.
    """
    calls, parse_err = parse_model_response(response_text)
    if parse_err is not None:
        return False, parse_err, f"no se pudo parsear ninguna llamada de: {response_text[:200]!r}"
    result = ast_checker(functions, calls, ground_truth, category)
    if result["valid"]:
        return True, "", ""
    return False, result["error_type"], "; ".join(result["error"])[:300]
