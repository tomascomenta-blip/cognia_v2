# -*- coding: utf-8 -*-
"""
F6 -- Config RESUELTA con origen por clave (patron dump-config de
deepseek-harness).

El bug que mata: "que config esta corriendo DE VERDAD?". Cognia lo pago dos
veces (los dos backends: :8088 servia un modelo retirado mientras la flota
estaba apagada; el token de PyPI que vivia en cognia_v2/.env donde nadie
miraba). La config efectiva sale de TRES capas -- _CONFIG_DEFAULTS del CLI,
~/.cognia_config.json, y las env vars COGNIA_* que pisan claves concretas --
y hasta hoy ninguna vista decia de que capa salio cada valor.

Uso:
    from cognia.harness import config_resuelta as cr
    resuelta = cr.config_resuelta()      # {clave: {"valor","origen","default"}}
    sueltas  = cr.env_sueltas()          # [(env, valor)] COGNIA_* sin clave
    print("\n".join(cr.formatear_plano(resuelta, sueltas)))

Origen por clave: 'default' | 'fichero' | 'env:NOMBRE'. La capa env solo
declara PRECEDENCIA visible: el valor mostrado es el crudo de la env (los
modulos consumidores ya la leen a call-time; aqui no se re-interpreta).

Punto de extension: ENV_QUE_PISAN es EL registro clave->envs. Una feature
nueva que anada clave de config con env de apagado registra su par aqui y la
vista la recoge sola.

Degradacion explicita: un fallo leyendo una capa (JSON corrupto, permisos)
avisa via el avisador registrado (el CLI pasa su _aviso_degradado) y sigue
con las capas que si se pudieron leer. Nunca lanza, nunca calla.

Secretos: toda clave o env cuyo nombre huela a token/key/secret se muestra
enmascarada (primeros 4 chars + '...'), tanto aqui como en el CLI.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("cognia.harness.config_resuelta")

# ── Registro clave de config -> env vars que la pisan ────────────────────────
# EL punto de extension del modulo. Orden dentro de la tupla = precedencia de
# display (la primera env puesta es la que se reporta como origen). Cada par
# viene de la doc de _CONFIG_DEFAULTS (cli.py) o del modulo consumidor.
ENV_QUE_PISAN: dict = {
    "esfuerzo":               ("COGNIA_ESFUERZO",),
    "mejorar_prompt_estilo":  ("COGNIA_MEJORA_PROMPT",),
    "render_colapso":         ("COGNIA_RENDER_COLAPSO",),
    # COGNIA_SPINNER=0 apaga TODO el spinner (viva y clasico): tambien pisa.
    "spinner_info":           ("COGNIA_SPINNER_INFO", "COGNIA_SPINNER"),
    "offload":                ("COGNIA_OFFLOAD",),
    "offload_umbral":         ("COGNIA_TOOL_RESULT_MAX",),
    "offload_cabeza":         ("COGNIA_OFFLOAD_CABEZA",),
    "offload_cola":           ("COGNIA_OFFLOAD_COLA",),
    "compactacion":           ("COGNIA_COMPACT",),
    "compactacion_umbral":    ("COGNIA_COMPACT_UMBRAL",),
    "compactacion_retencion": ("COGNIA_COMPACT_RETENCION",),
    "compactacion_cap":       ("COGNIA_COMPACT_CAP",),
    "notificar":              ("COGNIA_NOTIFY",),
    "notificar_modo":         ("COGNIA_NOTIFY",),
    # Footer de contexto honesto (2026-08-23): el CLI siembra las tres desde
    # _aplicar_config_barra (marcadas como sembradas); sin este registro una
    # COGNIA_CTX_AVISO puesta por el dueno salia como env SUELTA y la clave
    # decia 'default' — la barra obedecia a una env que esta vista no veia.
    "contexto_umbral_aviso":   ("COGNIA_CTX_AVISO",),
    "contexto_umbral_critico": ("COGNIA_CTX_CRITICO",),
    "barra_bloques":           ("COGNIA_BARRA_BLOQUES",),
    # Higiene del lazo (2026-08-24): recordatorio de repeticion advisory
    # (harness/repeticion) y timeout por tool (harness/timeout_tool); el CLI
    # las siembra desde _aplicar_config_bucle y /bucle las persiste.
    "repeticion":              ("COGNIA_REPETICION",),
    "repeticion_umbrales":     ("COGNIA_REPETICION_UMBRALES",),
    "tool_timeout_s":          ("COGNIA_TOOL_TIMEOUT",),
}

# Nombres que huelen a credencial: se enmascaran SIEMPRE en cualquier render.
_RE_SECRETO = re.compile(r"token|secret|passphrase|password|api.?key|_key\b",
                         re.IGNORECASE)

# Envs SEMBRADAS por el propio CLI (config -> env en cada arranque del REPL:
# _aplicar_config_offload/_aplicar_config_compactacion y los handlers de
# /offload y /compactar). Sin este registro, /config-resuelta atribuia 8
# claves a 'env:COGNIA_*' — justo la mentira de origen que F6 existe para
# matar: el dueno buscando 'la env olvidada que gana a todo' veia falsas envs
# puestas por el CLI, con el valor crudo ('1' en vez de 'on') pintado como
# 'difiere del default' (revision adversarial 2026-08-23). Una env sembrada
# lleva un valor que SALIO de config/default: el origen se resuelve en esas
# capas. Una env que el usuario puso antes de arrancar NUNCA se marca (la
# siembra solo escribe cuando la env esta vacia).
_SEMBRADAS: set = set()


def marcar_sembrada(*envs: str) -> None:
    """El CLI declara que estas envs las escribio EL, copiando la config."""
    _SEMBRADAS.update(e for e in envs if e)


def es_sembrada(env: str) -> bool:
    """True si esa env la escribio el propio CLI (no el usuario)."""
    return env in _SEMBRADAS


# Avisador de degradacion: el CLI registra su _aviso_degradado. None = logger.
_AVISADOR = None


def registrar_avisador(fn) -> None:
    """Registra el callable (origen, motivo) -> None para los fallos de capa
    (el CLI pasa su `_aviso_degradado`). El ultimo registrado gana."""
    global _AVISADOR
    _AVISADOR = fn


def _degradar(motivo: str) -> None:
    """Fallo de una capa: visible si hay avisador, logger siempre. No lanza."""
    logger.warning("config degradada: %s", motivo)
    try:
        if _AVISADOR is not None:
            _AVISADOR("config", motivo)
        else:
            # sin REPL registrado: el import perezoso alcanza al subcomando
            from cognia.cli import _aviso_degradado
            _aviso_degradado("config", motivo)
    except Exception as exc:  # el aviso jamas tumba la vista
        logger.warning("avisador de config fallo: %s", exc)


def es_secreto(nombre: str) -> bool:
    """True si el NOMBRE (clave o env) huele a credencial."""
    return bool(_RE_SECRETO.search(nombre or ""))


def enmascarar(valor: str) -> str:
    """Primeros 4 chars + '...'; valores cortos quedan solo '...'."""
    v = str(valor or "")
    if len(v) <= 4:
        return "..."
    return v[:4] + "..."


def _defaults_cli() -> dict:
    """_CONFIG_DEFAULTS del CLI, import perezoso (el CLI importa este modulo
    tambien perezoso: sin ciclo en import-time)."""
    from cognia.cli import _CONFIG_DEFAULTS
    return dict(_CONFIG_DEFAULTS)


def _ruta_fichero_cli() -> Path:
    from cognia.cli import _CONFIG_PATH
    return _CONFIG_PATH


def _leer_capa_fichero(ruta: Path) -> dict:
    """La capa de ~/.cognia_config.json. Fallo -> degradado y capa vacia
    (la resolucion sigue con defaults + env, que es lo que corre de verdad
    cuando el fichero esta roto: _load_config tambien cae a defaults)."""
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            _degradar(f"{ruta.name} no es un objeto JSON: capa ignorada")
            return {}
        return datos
    except Exception as exc:
        _degradar(f"no se pudo leer {ruta.name}: {type(exc).__name__}: {exc}")
        return {}


def config_resuelta(defaults: dict | None = None,
                    ruta_fichero: Path | None = None,
                    entorno: dict | None = None) -> dict:
    """Resuelve las tres capas y devuelve, POR CLAVE:

        {clave: {"valor": str, "origen": "default"|"fichero"|"env:NOMBRE",
                 "default": str}}

    Los tres parametros existen para los tests; en produccion se toman del
    CLI y del proceso. Claves desconocidas del fichero tambien salen (con su
    origen 'fichero'): estan en la config efectiva de _load_config igual.
    """
    if defaults is None:
        try:
            defaults = _defaults_cli()
        except Exception as exc:
            # el subcomando existe JUSTO para cuando el REPL ni arranca: sin
            # defaults del CLI se sigue con fichero + env, que es lo visible
            _degradar(f"defaults del CLI no disponibles: "
                      f"{type(exc).__name__}: {exc}")
            defaults = {}
    if ruta_fichero is None:
        try:
            ruta_fichero = _ruta_fichero_cli()
        except Exception:
            ruta_fichero = Path.home() / ".cognia_config.json"
    if entorno is None:
        entorno = os.environ

    fichero = _leer_capa_fichero(ruta_fichero)

    resultado: dict = {}
    claves = list(defaults) + [k for k in fichero if k not in defaults]
    for clave in claves:
        base = str(defaults.get(clave, ""))
        valor, origen = base, "default"
        if clave in fichero and str(fichero[clave]) != base:
            valor, origen = str(fichero[clave]), "fichero"
        for env in ENV_QUE_PISAN.get(clave, ()):
            crudo = str(entorno.get(env, "")).strip()
            # una env sembrada por el CLI no es una capa: su valor ya salio
            # de config/default y reportarla como 'env:' es mentir el origen
            if crudo and not es_sembrada(env):
                valor, origen = crudo, f"env:{env}"
                break
        resultado[clave] = {"valor": valor, "origen": origen, "default": base}
    return resultado


def env_sueltas(entorno: dict | None = None) -> list:
    """Las COGNIA_* puestas en el proceso que NO pisan una clave de config:
    [(nombre, valor)] ordenadas. Son las que nadie ve y explican los 'va raro'
    (el COGNIA_MEJORA_PROMPT=v1 olvidado en el shell, el token en .env)."""
    if entorno is None:
        entorno = os.environ
    con_clave = {e for envs in ENV_QUE_PISAN.values() for e in envs}
    sueltas = []
    for nombre in sorted(entorno):
        if nombre.startswith("COGNIA_") and nombre not in con_clave:
            valor = str(entorno[nombre])
            if valor.strip():
                sueltas.append((nombre, valor))
    return sueltas


def formatear_plano(resuelta: dict, sueltas: list) -> list:
    """Render texto plano alineado, agrupado por ORIGEN (env primero: es lo
    que el dueno busca cuando algo va raro), no-default marcado con (*).
    Secretos enmascarados. El CLI con rich pinta su propia tabla; esta es la
    vista comun (subcomando, sin rich, tests)."""
    lineas = ["Configuracion RESUELTA (defaults <- ~/.cognia_config.json <- env):"]
    ancho_k = max([len(k) for k in resuelta] + [1])
    grupos = (("env", "Pisadas por ENV (ganan a todo)"),
              ("fichero", "Del fichero (~/.cognia_config.json)"),
              ("default", "Defaults"))
    for prefijo, titulo in grupos:
        filas = [(k, v) for k, v in resuelta.items()
                 if v["origen"].startswith(prefijo)]
        if not filas:
            continue
        lineas.append(f"  -- {titulo} --")
        for clave, info in filas:
            valor = enmascarar(info["valor"]) if es_secreto(clave) else info["valor"]
            marca = " (*)" if info["valor"] != info["default"] else ""
            origen = f"  [{info['origen']}]" if prefijo != "default" else ""
            lineas.append(f"    {clave:<{ancho_k}} = {valor}{origen}{marca}")
    if sueltas:
        lineas.append("  -- Env COGNIA_* sueltas activas (sin clave de config) --")
        ancho_e = max(len(n) for n, _ in sueltas)
        for nombre, valor in sueltas:
            mostrado = enmascarar(valor) if es_secreto(nombre) else valor
            lineas.append(f"    {nombre:<{ancho_e}} = {mostrado}")
    lineas.append("  (*) = difiere del default")
    return lineas
