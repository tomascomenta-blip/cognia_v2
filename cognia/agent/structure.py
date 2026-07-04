"""
cognia/agent/structure.py
=========================
Generate-then-structure para tool-calls ACCION (palanca #3 de
06_AGENTE_PLAN.md §2 — cierra el gap (b) de §1: el parser recortaba el
primer bloque ACCION pero nadie validaba ni reparaba los argumentos).

Evidencia: forzar formato estricto DURANTE el razonamiento degrada 10-30%
en modelos chicos; la ganancia esta en dejar generar libre y ESTRUCTURAR
despues. El formato ACCION ya es lineal (ventaja heredada); aca se agrega
el paso 2 en tres niveles, del mas barato al mas caro:

  1. auto_fix: normalizacion MECANICA determinista (quitar comillas/fences,
     insertar el '|' faltante cuando la 1ra linea es claramente una ruta).
     Cero LLM, cero costo — el codigo termina el formateo.
  2. validate_action: chequeo contra la firma declarada de la tool
     (RULES). Devuelve un error accionable, estilo mensaje de parser.
  3. repair con el modelo (1 solo retry): el caller re-infiere con el error
     real en el prompt (build_repair_hint) — mismo patron que el repair de
     benchmark_code (feedback de ejecucion, nunca autocritica ciega).

Concreto: dict de reglas + funciones planas, sin clases ni framework.
"""
from __future__ import annotations

import re

# Firma declarada por tool: cuantas partes separadas por '|' y como se llama
# cada una (para el mensaje de error). Solo tools con formato no trivial;
# una tool ausente aca no se valida (pasa directo a run_tool).
#   parts   -> cantidad EXACTA de partes '|'
#   nonempty-> el arg (o la parte 0) no puede ser vacio; valor = nombre
#   path0/1 -> la parte N debe parecer una ruta (sin saltos de linea, corta)
#   url     -> la parte 0 debe empezar con http:// o https://
RULES = {
    "escribir_archivo": {"parts": 2, "names": ("ruta", "contenido"), "path0": True},
    "generar_codigo":   {"parts": 2, "names": ("ruta.py", "descripcion"), "path0": True},
    "apendar_archivo":  {"parts": 2, "names": ("ruta", "texto"), "path0": True},
    "copiar_archivo":   {"parts": 2, "names": ("src", "dst"), "path0": True, "path1": True},
    "kg_agregar":       {"parts": 3, "names": ("sujeto", "relacion", "objeto")},
    "anotar":           {"parts": 2, "names": ("clave", "valor")},
    "leer_archivo":     {"nonempty": "ruta", "path0": True},
    "contar_lineas":    {"nonempty": "ruta", "path0": True},
    "py_validar":       {"nonempty": "ruta", "path0": True},
    "json_validar":     {"nonempty": "ruta", "path0": True},
    "tests":            {"nonempty": "ruta"},
    "ejecutar":         {"nonempty": "comando"},
    "recordar":         {"nonempty": "consulta"},
    "memorizar":        {"nonempty": "texto"},
    "kg_buscar":        {"nonempty": "concepto"},
    "resumir":          {"nonempty": "texto"},
    "calcular":         {"nonempty": "expresion"},
    "responder":        {"nonempty": "respuesta"},
    "buscar":           {"nonempty": "patron"},
    "http_get":         {"nonempty": "url", "url": True},
}

# Una "ruta" plausible: sin saltos de linea, sin 'ACCION:' colado, largo sano.
_PATH_BAD_RE = re.compile(r"ACCI[OÓ]N:", re.IGNORECASE)
# 1ra linea que parece ruta: token sin espacios con extension o separador de
# directorios (lo que un modelo emite cuando olvido el '|' antes del contenido).
_PATHLIKE_RE = re.compile(r"^[\w.\-/\\:~]+\.[A-Za-z0-9]{1,8}$|^[\w.\-~]+[/\\][\w.\-/\\]+$")


def _split(args: str, maxsplit: int) -> list:
    return re.split(r"\s*\|\s*", args, maxsplit=maxsplit)


def auto_fix(action: str, args: str) -> str:
    """Normalizacion mecanica ANTES de validar (determinista, sin LLM).

    - strip global + quitar backticks/comillas envolventes de args cortos.
    - escribir/apendar sin '|': si la 1ra linea es claramente una ruta y hay
      mas contenido, insertar el separador (el olvido tipico del 3B).
    Devuelve args (posiblemente corregidos); nunca levanta."""
    fixed = (args or "").strip()
    rule = RULES.get(action)
    if not rule:
        return fixed
    # comillas/backticks envolventes en args de una sola parte y una linea.
    # NO en 'responder': su arg es la respuesta final literal al usuario y
    # puede ser un string entrecomillado legitimo que no hay que recortar.
    if (action != "responder" and "parts" not in rule
            and "\n" not in fixed and len(fixed) < 300):
        m = re.fullmatch(r"[`\"']+(.*?)[`\"']+", fixed)
        if m:
            fixed = m.group(1).strip()
    # '|' faltante en tools de 2 partes cuya parte 0 es una ruta
    if rule.get("parts") == 2 and rule.get("path0") and "|" not in fixed:
        lines = fixed.split("\n", 1)
        if len(lines) == 2 and _PATHLIKE_RE.match(lines[0].strip()):
            fixed = lines[0].strip() + " | " + lines[1].lstrip("\n")
    return fixed


def validate_action(action: str, args: str) -> str | None:
    """None si (action, args) respeta la firma declarada; si no, un error
    ACCIONABLE (nombra la tool, el formato esperado y que fallo) para
    devolverselo al modelo como lo haria un parser."""
    rule = RULES.get(action)
    if rule is None:
        return None  # tool sin regla (o inexistente: run_tool ya la maneja)

    if "parts" in rule:
        n, names = rule["parts"], rule["names"]
        parts = _split(args, maxsplit=n - 1)
        if len(parts) != n or any(not p.strip() for p in parts):
            fmt = " | ".join(f"<{x}>" for x in names)
            return (f"{action} espera {n} partes separadas por '|': {fmt}. "
                    f"Recibido: {len([p for p in parts if p.strip()])} parte(s).")
        for i in (0, 1):
            if rule.get(f"path{i}"):
                err = _check_path(action, names[i], parts[i].strip())
                if err:
                    return err
        return None

    if "nonempty" in rule:
        val = (args or "").strip()
        if not val:
            return f"{action} espera <{rule['nonempty']}> y llego vacio."
        if rule.get("path0"):
            err = _check_path(action, rule["nonempty"], val)
            if err:
                return err
        if rule.get("url") and not re.match(r"https?://", val):
            return f"{action} espera una URL http(s); recibido: {val[:60]!r}"
    return None


def _check_path(action: str, name: str, value: str) -> str | None:
    if "\n" in value:
        return (f"{action}: <{name}> tiene un salto de linea adentro "
                f"(probablemente falto el separador '|').")
    if _PATH_BAD_RE.search(value):
        return (f"{action}: <{name}> contiene 'ACCION:' — se colo un segundo "
                "bloque de accion en los argumentos.")
    if len(value) > 300:
        return f"{action}: <{name}> demasiado largo para una ruta ({len(value)} chars)."
    return None


def build_repair_hint(action: str, args: str, error: str) -> str:
    """Instruccion de retry (1 solo) con el error del validador — va al final
    del prompt del paso, tras la respuesta invalida del modelo."""
    return ("\nFORMATO INVALIDO: " + error +
            "\nEmiti SOLO la linea ACCION corregida (una sola linea "
            "ACCION: <herramienta> <argumentos>), sin explicaciones:")


def structure_action(action: str, args: str, reinfer=None):
    """Pipeline completo nivel 1-3. Devuelve (action, args, meta).

    meta = {"auto_fixed": bool, "repaired": bool, "error": str|None}.
    ``reinfer(hint_text) -> str`` re-genera con el error en el prompt (el
    caller le pone los stop tokens y el contexto); None = sin nivel 3.
    Si el retry tampoco valida, se devuelven los args originales con el
    error en meta: el caller los pasa a run_tool, que respondera con su
    propio ERROR — señal real para el loop, nunca un crash."""
    meta = {"auto_fixed": False, "repaired": False, "error": None}

    fixed = auto_fix(action, args)
    if fixed != (args or "").strip():
        meta["auto_fixed"] = True
    err = validate_action(action, fixed)
    if err is None:
        return action, fixed, meta

    meta["error"] = err
    if reinfer is None:
        return action, fixed, meta

    # nivel 3: UN retry con el error real en el prompt
    try:
        raw = reinfer(build_repair_hint(action, fixed, err)) or ""
    except Exception:
        return action, fixed, meta
    m = re.search(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", raw, re.IGNORECASE | re.DOTALL)
    if not m:
        return action, fixed, meta
    new_action = m.group(1).lower().strip()
    new_args = auto_fix(new_action, m.group(2).strip())
    if validate_action(new_action, new_args) is None:
        meta.update(repaired=True, error=None)
        return new_action, new_args, meta
    return action, fixed, meta
