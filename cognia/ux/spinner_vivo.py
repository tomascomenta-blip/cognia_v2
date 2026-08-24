"""
cognia/ux/spinner_vivo.py
=========================
La linea de estado VIVA del turno (F2, 2026-08-23).

POR QUE EXISTE: la linea de espera de Claude Code/Codex SIEMPRE responde tres
preguntas — ¿esta vivo? ¿cuanto lleva? ¿como lo paro? — y el spinner de Cognia
era mas mudo que eso ('pensando… (3s)' en el mejor caso). Este modulo COMPONE
esa linea: verbo rotatorio con personalidad de gato + segundos + ~tokens
recibidos del stream + el hint de corte REAL de Cognia (Ctrl-C corta el turno,
no el REPL — cli.py maneja KeyboardInterrupt en el streaming y en /hacer; no
existe 'esc' aqui y decirlo seria mentir).

Solo composicion PURA y lectura de config: el que anima es el renderer
(ux/renderer.py, un hilo ticker sobre el rich status ya existente). Asi la
linea se testea sin terminal ni hilos.

Config (a CALL-TIME, mismo patron que renderer._config_colapso):
- clave 'spinner_info' on|off (default on) -> /spinner on|off
- clave 'spinner_verbos' (lista JSON o texto separado por comas; vacia = los
  VERBOS_GATO de aqui) -> /spinner verbos ...
- env COGNIA_SPINNER_INFO=0 apaga la linea viva GANANDO a la config (y =1 la
  fuerza); COGNIA_SPINNER=0 sigue apagando TODO el spinner (renderer).
"""
from __future__ import annotations

import os

# El hint de corte REAL: Ctrl-C corta el turno y el REPL sigue vivo
# (cli.py: except KeyboardInterrupt en el streaming y en el spinner de
# 'Procesando...'). No es 'esc': prompt_toolkit no cablea escape a nada aqui.
HINT_CORTE = "ctrl+c corta"

# Cada cuantos segundos rota el verbo. 4s: bastante para leerlo, poco para
# que la linea parezca congelada.
PERIODO_ROTACION = 4

# ~4 chars por token: es una ESTIMACION honesta (por eso el '~' en la linea).
# El footer final sigue mostrando los tokens REALES del backend; esta cifra
# solo dice "siguen llegando cosas" mientras no hay footer.
_CHARS_POR_TOKEN = 4

# Los ~20 verbos gato por defecto: personalidad propia, sobrios, ASCII puro
# (la consola cp1252 no tiene donde tropezar). Se reemplazan enteros con la
# clave de config 'spinner_verbos' (/spinner verbos ...).
VERBOS_GATO = [
    "Maullando ideas",
    "Afilando garras",
    "Olfateando el repo",
    "Persiguiendo el hilo",
    "Amasando la respuesta",
    "Acechando el problema",
    "Ronroneando en voz baja",
    "Trepando al contexto",
    "Cazando el bug",
    "Escarbando en los datos",
    "Atando cabos",
    "Rumiando opciones",
    "Hilando fino",
    "Merodeando la solucion",
    "Desenredando el ovillo",
    "Agazapado, pensando",
    "Husmeando pistas",
    "Estirando el lomo",
    "Ordenando bigotes",
    "Saltando entre ramas",
]


def estimar_tokens(chars: int) -> int:
    """~tokens a partir de chars del stream. 0 si todavia no llego nada."""
    return max(0, int(chars) // _CHARS_POR_TOKEN)


def _sanear_verbo(v) -> str:
    """Un verbo de config apto para la linea: sin corchetes (romperian el
    markup de rich del status), sin saltos de linea, recortado."""
    return str(v).replace("[", "").replace("]", "").replace("\n", " ").strip()


def verbos_config(cfg_valor=None) -> list:
    """La lista de verbos vigente. Acepta el valor crudo de la config (lista
    JSON o texto separado por comas); vacio/invalido -> VERBOS_GATO."""
    crudo = cfg_valor
    if isinstance(crudo, str):
        crudo = [p for p in crudo.split(",")]
    if not isinstance(crudo, (list, tuple)):
        return list(VERBOS_GATO)
    limpios = [s for s in (_sanear_verbo(v) for v in crudo) if s]
    return limpios or list(VERBOS_GATO)


def config() -> tuple:
    """(info_activa, verbos) a CALL-TIME.

    COGNIA_SPINNER_INFO manda ('0' apaga la linea viva, '1' la fuerza); sin la
    env decide la config persistida del CLI (claves 'spinner_info' y
    'spinner_verbos', se cambian con /spinner). Se mira sys.modules y NO se
    importa cli: en el REPL ya esta cargado, y un renderer suelto (tests,
    scripts) no paga las 15k lineas de cli.py por un default."""
    activo, verbos = True, list(VERBOS_GATO)
    try:
        import sys
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            cfg = _cli._load_config()
            activo = (str(cfg.get("spinner_info", "on")).strip().lower()
                      not in ("off", "0", "false", "no"))
            verbos = verbos_config(cfg.get("spinner_verbos", ""))
    except Exception:
        activo, verbos = True, list(VERBOS_GATO)
    v = (os.environ.get("COGNIA_SPINNER_INFO") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        activo = False
    elif v in ("1", "true", "si", "on"):
        activo = True
    return activo, verbos


def activo() -> bool:
    return config()[0]


def verbo_rotante(t0: float, ahora: float, verbos: list | None = None,
                  periodo: int = PERIODO_ROTACION) -> str:
    """El verbo del momento: rota cada `periodo` segundos. El offset por int(t0)
    hace que cada turno arranque en un verbo distinto sin dejar de ser
    determinista (mismos t0/ahora -> mismo verbo, testeable)."""
    verbos = verbos or VERBOS_GATO
    if not verbos:
        return "Trabajando"
    transcurrido = max(0.0, float(ahora) - float(t0))
    idx = (int(t0) + int(transcurrido // max(1, periodo))) % len(verbos)
    return verbos[idx]


def componer_linea(verbo: str, segundos: int, tokens: int = 0,
                   hint: str = HINT_CORTE, ancho: int = 100) -> str:
    """UNA linea: 'Maullando ideas… (12s · ~340 tok · ctrl+c corta)'.

    Truncado elegante para anchos estrechos, por prioridad de las tres
    preguntas (¿vivo? ¿cuanto? ¿como paro?): primero caen los ~tokens (el
    bonus), despues el hint, y al final se recorta el verbo con '…'. Los
    segundos no caen nunca: son el latido. JAMAS devuelve '\\n' ni una linea
    mas larga que `ancho` (anti-jitter: una linea que envuelve salta de
    altura y ensucia el scrollback)."""
    verbo = (verbo or "Trabajando").rstrip(".").rstrip("…").strip()
    segundos = max(0, int(segundos))
    candidatas = []
    partes = [f"{segundos}s"]
    if tokens > 0:
        partes.append(f"~{tokens} tok")
    if hint:
        partes.append(hint)
    candidatas.append(partes)                       # completa
    if tokens > 0:
        candidatas.append([f"{segundos}s"] + ([hint] if hint else []))
    if hint:
        candidatas.append([f"{segundos}s"])         # solo el latido
    for p in candidatas:
        linea = f"{verbo}… ({' · '.join(p)})"
        if len(linea) <= ancho:
            return linea
    # ni con solo los segundos entra: recortar el verbo, conservar '(Ns)'
    cola = f"… ({segundos}s)"
    sitio = ancho - len(cola)
    if sitio >= 2:
        return verbo[:sitio - 1] + "…" + cola[1:] if len(verbo) > sitio \
            else verbo[:sitio] + cola
    # ancho absurdo (< ~8): devolver lo que quepa, sin romper linea
    return (f"{verbo}{cola}")[:max(1, ancho)]


def linea_estado(base: str | None, t0: float, ahora: float, chars: int,
                 ancho: int = 100) -> str:
    """La linea viva completa para el ticker del renderer. `base` es la
    etiqueta de la tool en curso ('Leyendo motor.py…' — mas honesta que un
    verbo generico); None = fase de pensar, verbo gato rotatorio."""
    _, verbos = config()
    if base:
        verbo = base
    else:
        verbo = verbo_rotante(t0, ahora, verbos)
    return componer_linea(verbo, int(max(0.0, ahora - t0)),
                          tokens=estimar_tokens(chars), ancho=ancho)
