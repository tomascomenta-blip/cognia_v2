# -*- coding: utf-8 -*-
"""Validar el tool call CONTRA SU SCHEMA antes de ejecutarlo.

Portado de SWE-agent (`sweagent/tools/parsing.py: FunctionCallingParser` con
`FunctionCallingFormatError(error_code in {missing, multiple, invalid_json,
invalid_command, missing_arg, unexpected_arg})` y su plantilla que ramifica
por `error_code`) y de mini-swe-agent (`parse_toolcall_actions`), 2026-09-04,
tras leer el código de los dos.

Lo que había: `args_legacy` convierte el dict en el string del protocolo
texto "tolerante por diseño" y deja que la tool reporte lo que le falte. En
la práctica una llamada `escribir_archivo({"path": "x.py"})` sin `contenido`
ESCRIBÍA un fichero vacío (la tool recibía "x.py | ") y el modelo leía
"ok"; una con `{"ruta": ...}` en vez de `path` caía al join de valores y la
tool fallaba explicando otra cosa. La lección de SWE-agent: el error de
formato se detecta ANTES, se nombra con un código, se le enseña la firma al
modelo, la herramienta NO corre y el paso NO cuenta (RETRY_WITH_OUTPUT).

Reglas (solo sobre tools con schema publicado por `tool_schemas.schemas_para`):
  falta_argumento      -> un `required` ausente o None
  argumento_vacio      -> un `required` de ruta/bloque vacío ("", "   ")
  argumento_inesperado -> claves que no están en `properties` (salvo `args`)
  tipo_incorrecto      -> integer/number/boolean declarado y el valor no lo es
                          ni se puede leer como tal ("42" vale para integer)
Kill-switch: COGNIA_VALIDAR_TOOL_CALLS=0.
"""
from __future__ import annotations

import os

ENV_ACTIVO = "COGNIA_VALIDAR_TOOL_CALLS"
_CLAVES_NO_VACIAS = ("path", "ruta", "origen", "destino", "buscar", "url", "archivo", "fichero")
_SCHEMAS: dict | None = None


def activo() -> bool:
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in ("0", "no", "off", "false")


def _schemas() -> dict:
    global _SCHEMAS
    if _SCHEMAS is None:
        try:
            from cognia.agent.tool_schemas import schemas_para
            _SCHEMAS = {s["function"]["name"]: s["function"].get("parameters") or {}
                        for s in schemas_para(None) if isinstance(s, dict) and "function" in s}
        except Exception:
            _SCHEMAS = {}
    return _SCHEMAS


def olvidar_cache() -> None:
    global _SCHEMAS
    _SCHEMAS = None


def firma(nombre: str, params: dict | None = None) -> str:
    p = params if params is not None else _schemas().get(nombre) or {}
    props = p.get("properties") or {}
    req = set(p.get("required") or [])
    partes = [f"{k}*" if k in req else k for k in props]
    return f"{nombre}({', '.join(partes)})"


def _es_entero(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    if isinstance(v, str):
        return v.strip().lstrip("+-").isdigit()
    return False


def _es_numero(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.strip())
            return True
        except ValueError:
            return False
    return False


def _es_bool(v) -> bool:
    if isinstance(v, bool):
        return True
    return isinstance(v, str) and v.strip().lower() in ("true", "false", "1", "0", "si", "sí", "no")


# Alias que los modelos usan de verdad (medidos en las trazas del repo: `ruta`
# por `path`, `cmd` por el comando, `path` por `directorio`). Solo se aplican
# cuando el destino existe en el schema y NO vino ya en la llamada.
ALIAS = {
    "file_path": "path", "filepath": "path", "ruta": "path", "archivo": "path",
    "fichero": "path", "filename": "path", "file": "path",
    "cmd": "comando", "command": "comando",
    "dir": "directorio", "directory": "directorio", "carpeta": "directorio",
    "content": "contenido", "text": "texto", "search": "buscar", "replace": "reemplazar",
    "old_string": "buscar", "new_string": "reemplazar", "old_str": "buscar", "new_str": "reemplazar",
    "query": "consulta", "pattern": "patron", "patrón": "patron",
}


def normalizar(nombre: str, argumentos):
    """Los argumentos con los alias resueltos (hermes `coerce_tool_args`).

    Devuelve un dict NUEVO (o el objeto tal cual si no es dict / no hay schema).
    Tres rescates, en este orden, todos sin ambigüedad posible:
      1. tabla ALIAS: `ruta`->`path` si `path` existe en el schema y no vino;
      2. una sola propiedad en el schema y una sola clave distinta -> se renombra;
      3. falta exactamente un `required` y sobra exactamente una clave -> se renombra.
    Lo que no encaje en ninguno queda igual y lo juzga `validar`. Nunca lanza.
    """
    try:
        if not activo() or not isinstance(argumentos, dict):
            return argumentos
        params = _schemas().get(nombre)
        props = (params or {}).get("properties") or {}
        if not props or set(argumentos) == {"args"}:
            return argumentos
        out = dict(argumentos)
        for k in list(out):
            destino = ALIAS.get(k)
            if k not in props and destino in props and destino not in out:
                out[destino] = out.pop(k)
        inesperadas = [k for k in out if k not in props and k != "args"]
        if len(props) == 1 and len(out) == 1 and inesperadas:
            (unica,) = props
            out[unica] = out.pop(inesperadas[0])
            return out
        faltan = [k for k in (params.get("required") or []) if k in props and k not in out]
        if len(faltan) == 1 and len(inesperadas) == 1:
            out[faltan[0]] = out.pop(inesperadas[0])
        return out
    except Exception:
        return argumentos


def validar(nombre: str, argumentos) -> tuple[str, str] | None:
    """None si la llamada es válida (o no hay schema); si no, (codigo, texto).

    `texto` es el RESULTADO completo para el modelo. Nunca lanza.
    """
    try:
        if not activo() or not isinstance(argumentos, dict):
            return None
        params = _schemas().get(nombre)
        if not params:
            return None
        props = params.get("properties") or {}
        if not props:
            return None
        claves = set(argumentos)
        if claves == {"args"} or not claves:
            return None                       # passthrough legítimo del protocolo texto
        req = [k for k in (params.get("required") or []) if k in props]
        faltan = [k for k in req if k not in argumentos or argumentos.get(k) is None]
        if faltan:
            return _error(nombre, params, "falta_argumento",
                          f"falta{'n' if len(faltan) > 1 else ''} {', '.join(repr(k) for k in faltan)}")
        vacios = [k for k in req if k in _CLAVES_NO_VACIAS
                  and isinstance(argumentos.get(k), str) and not argumentos[k].strip()]
        if vacios:
            return _error(nombre, params, "argumento_vacio",
                          f"{', '.join(repr(k) for k in vacios)} llegó vacío")
        inesperadas = sorted(k for k in claves if k not in props and k != "args")
        if inesperadas:
            return _error(nombre, params, "argumento_inesperado",
                          f"{', '.join(repr(k) for k in inesperadas)} no existe{'n' if len(inesperadas) > 1 else ''} "
                          f"en esta herramienta (válidos: {', '.join(props)})")
        for k, v in argumentos.items():
            tipo = (props.get(k) or {}).get("type")
            if v is None or tipo in (None, "string", "object", "array"):
                continue
            if tipo == "integer" and not _es_entero(v):
                return _error(nombre, params, "tipo_incorrecto", f"{k!r} debe ser un entero, llegó {v!r}")
            if tipo == "number" and not _es_numero(v):
                return _error(nombre, params, "tipo_incorrecto", f"{k!r} debe ser un número, llegó {v!r}")
            if tipo == "boolean" and not _es_bool(v):
                return _error(nombre, params, "tipo_incorrecto", f"{k!r} debe ser true/false, llegó {v!r}")
        return None
    except Exception:
        return None


def _error(nombre: str, params: dict, codigo: str, detalle: str) -> tuple[str, str]:
    return codigo, (f"RESULTADO {nombre} ERROR de formato ({codigo}): {detalle}. "
                    f"Firma: {firma(nombre, params)} (* = obligatorio). La herramienta "
                    f"NO se ejecutó y este intento no cuenta: repite la llamada "
                    f"con TODOS los argumentos y sus nombres exactos.")


__all__ = ["validar", "normalizar", "firma", "activo", "olvidar_cache", "ENV_ACTIVO", "ALIAS"]
