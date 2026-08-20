# -*- coding: utf-8 -*-
"""EL lector UNICO del flag COGNIA_TX.

POR QUE EXISTE (medido 2026-08-19): habia CUATRO lecturas del mismo flag y no
coincidian. `cli._tx_activo()` y `driver.activo()` leian env O config
persistida; `agent.tools._flag_activo()` y `harness.interceptor._activo()`
leian SOLO el env. Consecuencia reproducida en dos procesos:

    /tx on  ->  guarda tx_activo=true y pone COGNIA_TX=1 en ESTE proceso
    (cierras el REPL, lo reabres al dia siguiente sin la env var)
    /tx estado  -> "TX / LIBRO: ACTIVO"   /tx iniciar -> abre la tarea
    ... y `interceptor._libro()` hace `return` en su primera linea:
    una llamada real a run_tool llevaba el libro de 7 eventos a 7.

Es decir: tarea abierta, panel verde, y la memoria append-only sin un solo
evento del trabajo del dueno. El vacio silencioso exacto que el subsistema
existe para impedir -- y ni `_avisar_libro_ausente` ni `_aviso_degradado` se
enteraban, porque el `return` iba antes.

DOS DECISIONES DE DISENO, las dos por el mismo motivo:

1. SIN DEPENDENCIAS PESADAS. Se lee `~/.cognia_config.json` a mano en vez de
   importar `cognia.cli`: esto lo llama el interceptor en el camino caliente de
   CADA tool, y arrastrar el CLI ahi seria pagar el REPL entero en cualquier
   proceso que use el agente.
2. PROPAGA AL ENV. Cuando manda la config, se escribe `COGNIA_TX` en el
   entorno del proceso. Asi los cuatro lectores convergen a la primera lectura
   y un subproceso hereda el mismo estado que su padre -- que es lo que el
   dueno cree que pasa cuando teclea `/tx on`.
"""

import json
import os

ENV = "COGNIA_TX"
CLAVE_CONFIG = "tx_activo"
_VERDAD = ("1", "on", "true", "yes", "si")

# La config se lee UNA vez por proceso: si el env manda (que es el caso normal)
# ni se toca el disco, y cuando no manda, `/tx on` deja el env puesto, asi que
# el cache no puede quedarse rancio en la direccion que importa.
_CACHE = {"leido": False, "valor": False, "error": ""}


def ruta_config():
    """El mismo fichero que `cli._load_config`. Se resuelve en cada llamada
    para que un test que mueve HOME no vea la ruta congelada del import."""
    from pathlib import Path
    return Path.home() / ".cognia_config.json"


def _de_env():
    """True/False si el env dice algo, None si no esta puesto."""
    crudo = os.environ.get(ENV, "").strip().lower()
    if not crudo:
        return None
    return crudo in _VERDAD


def _de_config():
    """Lo que dice la config persistida. NUNCA lanza: si no se puede leer, el
    subsistema esta apagado (que es el defecto), no reventado."""
    if _CACHE["leido"]:
        return _CACHE["valor"]
    valor = False
    try:
        ruta = ruta_config()
        if ruta.exists():
            with ruta.open(encoding="utf-8") as fh:
                valor = bool(json.load(fh).get(CLAVE_CONFIG, False))
    except Exception as exc:
        # NO se avisa AQUI (quien pregunta es el interceptor en mitad de una
        # tool, y un aviso por llamada seria ruido en el bucle), pero tampoco
        # se traga: el motivo queda en `ultimo_error()` y `/tx diagnostico` lo
        # imprime. Un config ilegible significa "no hay opt-in guardado", que
        # es el defecto, no una averia del LIBRO.
        _CACHE["error"] = "%s: %s" % (type(exc).__name__, exc)
        valor = False
    _CACHE["leido"] = True
    _CACHE["valor"] = valor
    return valor


def ultimo_error():
    """El motivo por el que la config no se pudo leer, o '' si se leyo bien."""
    return _CACHE.get("error") or ""


def activo():
    """El flag TX. EL ENV MANDA; si no esta puesto, la config persistida."""
    valor = _de_env()
    if valor is not None:
        return valor
    valor = _de_config()
    if valor:
        propagar(True)
    return bool(valor)


def propagar(encendido):
    """Deja el flag en el entorno del proceso para que los cuatro lectores (y
    cualquier subproceso) vean lo mismo. Lo llama tambien `/tx on|off`."""
    os.environ[ENV] = "1" if encendido else "0"
    _CACHE["leido"] = True
    _CACHE["valor"] = bool(encendido)


def olvidar_cache():
    """Solo para los tests: fuerza a releer la config en la proxima consulta."""
    _CACHE["leido"] = False
    _CACHE["valor"] = False
    _CACHE["error"] = ""
