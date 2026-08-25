# -*- coding: utf-8 -*-
"""
cognia/harness/repeticion.py
============================
RECORDATORIO DE REPETICION: un guard ADVISORY que le habla al modelo cuando
repite la misma llamada con los mismos argumentos, ANTES de que los cortes
duros (register_action / GuardiaBucle) tengan que parar el turno.

POR QUE EXISTE (2026-08-24, destilado del repeat-tool-reminder de
deepseek-harness): Cognia ya tiene DOS detectores de bucle y los dos CORTAN:
`agent/loop.py:register_action` (mismo par tool+args 3 veces en TODA la tarea
-> stop; 2da vez -> un aviso generico) y `hermes/guardia_bucle.GuardiaBucle`
(ventana deslizante, ping-pong y ciclos; aviso a la 3ra, bloqueo a la 5ta).
Lo que NO habia era un recordatorio que CITE la llamada repetida con sus
argumentos y le pida al modelo analizar el resultado previo — la leccion
medida del repo (+62pp, bench_estancamiento) es que el aviso concreto desvia
al modelo y el abstracto no. Este modulo es esa pieza, y es ADVISORY: nunca
veta, nunca corta, solo anexa texto a la observacion que el modelo lee en el
paso siguiente.

QUE HACE
    Por AGENTE (el ctx de run_tool) guarda (clave, contador) de la llamada
    CONSECUTIVA en curso. La clave es el JSON canonico de [tool, args] con
    key-sort RECURSIVO: dos dicts con las claves en otro orden son la MISMA
    llamada; un string se normaliza por espacios (y si es JSON, se parsea y
    se ordena igual). Al cruzar el 1er umbral (default 3) anexa un recordatorio
    SUAVE; en los siguientes (5, 8) uno DETALLADO que nombra la tool, cuantas
    llamadas consecutivas lleva y cita los args (cap 500 chars). Cuenta
    TAMBIEN las llamadas vetadas y fallidas (repetir un fallo identico es el
    caso tipico). Se resetea con cada prompt humano nuevo. Las tools EXENTAS
    (polling legitimo: ver_salida, procesos, tests) son TRANSPARENTES: ni
    cuentan ni rompen la racha.

PRECEDENCIA CON LOS CORTES DUROS (documentada, no escondida): en
`bucle_nativo` register_action corta a la 3ra llamada identica de la TAREA,
asi que con el umbral 3 el primer recordatorio coincide con el corte y solo
llega al modelo cuando (a) los args difieren como string pero son la misma
llamada canonica, (b) el bucle es el legacy / un subagente / un flujo que no
pasa por register_action, o (c) el dueno baja el umbral (/bucle umbrales
2,4,6). No se toca el corte duro: es el techo, y esto es el aviso.

CONFIG (patron dsh: se VALIDA al cargar y falla RUIDOSO con config invalida)
    COGNIA_REPETICION            '0/off' apaga; vacio o '1' = encendido.
    COGNIA_REPETICION_UMBRALES   'a,b,c' enteros >= 2, estrictamente
                                 crecientes; vacio = 3,5,8. Basura ->
                                 ConfigInvalida: el hook avisa via el
                                 avisador registrado (el CLI pasa su
                                 _aviso_degradado) UNA vez y se comporta
                                 como apagado hasta que se arregle.
    El CLI siembra las dos desde ~/.cognia_config.json ('repeticion',
    'repeticion_umbrales') con /bucle.

CONTRATO: `anexar(...)` NUNCA lanza y NUNCA veta: ante cualquier fallo devuelve
el texto que recibio. El unico efecto posible es texto ANADIDO al final.

BUCLE POR FICHERO (2026-08-24, deepagents 0.7.8: LoopDetectionMiddleware
del blog de harness engineering, y el system_prompt.md de dcode: "DO NOT
loop more than 3 times fixing the same error with the same approach"). Los
CUATRO detectores del repo (register_action, GuardiaBucle, `Contador` de
arriba y el Disyuntor de disciplina) cuentan por tool+args: tres
editar_archivo sobre a.py con bloques SEARCH distintos son, para todos
ellos, tres llamadas distintas. `ContadorFichero` cuenta EDICIONES AL MISMO
FICHERO normalizado dentro de una tarea, con args distintos o no, y al
llegar al umbral (default 3, config 'repeticion_umbral_fichero' /
COGNIA_REPETICION_UMBRAL_FICHERO) devuelve un nudge de RECONSIDERACION que
el bucle nativo inyecta como turno user (loop.py, junto al aviso del
guardia). Advisory como todo lo de este modulo: no corta, no veta.
"""

from __future__ import annotations

import json
import os
import re
import time

UMBRALES_DEFECTO = (3, 5, 8)
CAP_ARGS = 500
MARCA = "[RECORDATORIO DE REPETICION]"
ENV_ACTIVO = "COGNIA_REPETICION"
ENV_UMBRALES = "COGNIA_REPETICION_UMBRALES"
# Bucle por fichero: N ediciones al MISMO fichero dentro de una tarea.
UMBRAL_FICHERO_DEFECTO = 3
ENV_UMBRAL_FICHERO = "COGNIA_REPETICION_UMBRAL_FICHERO"
# Las tools que EDITAN (no borrar/mover: esas no se reintentan en bucle).
# Nombres reales de agent/tools.py (@tool "escribir_archivo" etc.).
TOOLS_EDICION = frozenset({"escribir_archivo", "editar_archivo",
                           "apendar_archivo"})

# Tools cuyo trabajo ES repetirse (polling de un proceso de fondo, correr la
# misma suite tras cada arreglo). Mismo criterio que EXENTAS_COGNIA del
# guardia de Hermes; se importa de ahi si existe para no tener dos listas.
try:
    from cognia.hermes.guardia_bucle import EXENTAS_COGNIA as EXENTAS
except Exception:  # pragma: no cover - el guardia es opcional
    EXENTAS = frozenset({"ver_salida", "procesos", "tests"})

# Generacion de prompt humano: cada prompt nuevo la sube y todo contador que
# la vea cambiada se resetea SOLO en su proxima llamada. Asi el reset no
# depende de conocer todos los ctx vivos (subagentes, lazos, horizonte).
_GENERACION = [0]

# Telemetria de proceso para /bucle estado. Nada en disco.
_ULTIMO: dict = {}
_ULTIMO_ERROR: dict = {}
_TOTAL = [0]            # recordatorios emitidos en este proceso
_AVISADO = [False]      # la config invalida se grita UNA vez por proceso
_ULTIMO_FICHERO: dict = {}   # ultimo nudge por fichero (para /bucle estado)
_TOTAL_FICHERO = [0]         # nudges por fichero emitidos en este proceso

# Punto de extension: el CLI registra su _aviso_degradado.
_AVISADOR = None


class ConfigInvalida(ValueError):
    """Umbrales o flag que no se pueden interpretar. Se lanza al CARGAR."""


def registrar_avisador(fn) -> None:
    """Callable (origen, motivo) -> None para los fallos del subsistema. Un
    solo avisador: el ultimo registrado gana."""
    global _AVISADOR
    _AVISADOR = fn


def _avisar(motivo: str) -> None:
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update({"motivo": motivo,
                          "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    if _AVISADO[0]:
        return
    _AVISADO[0] = True
    if _AVISADOR is not None:
        try:
            _AVISADOR("repeticion", motivo)
            return
        except Exception:
            pass
    import logging
    logging.getLogger(__name__).warning("repeticion degradada: %s", motivo)


# ── Config ───────────────────────────────────────────────────────────────────

def parsear_umbrales(texto) -> tuple:
    """'3,5,8' -> (3, 5, 8). Enteros >= 2, estrictamente crecientes, al menos
    uno. Cualquier otra cosa es ConfigInvalida con el motivo exacto."""
    crudo = str(texto if texto is not None else "").strip()
    if not crudo:
        return UMBRALES_DEFECTO
    partes = [p.strip() for p in re.split(r"[,\s;]+", crudo) if p.strip()]
    if not partes:
        raise ConfigInvalida(f"umbrales vacios: {crudo!r}")
    valores = []
    for p in partes:
        try:
            v = int(p)
        except ValueError:
            raise ConfigInvalida(f"umbral no entero: {p!r} (en {crudo!r})")
        if v < 2:
            raise ConfigInvalida(f"umbral {v} < 2: una sola llamada no es "
                                 f"repeticion (en {crudo!r})")
        if valores and v <= valores[-1]:
            raise ConfigInvalida(f"umbrales no crecientes: {crudo!r}")
        valores.append(v)
    return tuple(valores)


def umbrales() -> tuple:
    """Los umbrales efectivos (env COGNIA_REPETICION_UMBRALES o el default).
    Lanza ConfigInvalida con basura: el que llama decide si grita o cae."""
    return parsear_umbrales(os.environ.get(ENV_UMBRALES, ""))


def parsear_umbral_fichero(texto) -> int:
    """'3' -> 3. Entero >= 2 (una edicion no es un bucle); vacio = default.
    Basura -> ConfigInvalida con el motivo exacto (mismo patron que
    parsear_umbrales: se valida al cargar y falla RUIDOSO)."""
    crudo = str(texto if texto is not None else "").strip()
    if not crudo:
        return UMBRAL_FICHERO_DEFECTO
    try:
        v = int(crudo)
    except ValueError:
        raise ConfigInvalida(f"umbral por fichero no entero: {crudo!r}")
    if v < 2:
        raise ConfigInvalida(f"umbral por fichero {v} < 2: una edicion no es "
                             f"un bucle")
    return v


def umbral_fichero() -> int:
    """El umbral efectivo de ediciones al mismo fichero (env
    COGNIA_REPETICION_UMBRAL_FICHERO o el default 3)."""
    return parsear_umbral_fichero(os.environ.get(ENV_UMBRAL_FICHERO, ""))


def activo() -> bool:
    """Encendido salvo COGNIA_REPETICION=0/off/false/no. Vacio = encendido:
    es advisory y cuesta un dict lookup, asi que embebido tambien va."""
    crudo = os.environ.get(ENV_ACTIVO, "").strip().lower()
    if not crudo:
        return True
    if crudo in ("1", "on", "true", "yes", "si"):
        return True
    if crudo in ("0", "off", "false", "no"):
        return False
    raise ConfigInvalida(f"{ENV_ACTIVO}={crudo!r}: esperaba on/off")


def validar_config() -> dict:
    """Valida TODA la config de una (para el arranque del CLI): devuelve
    {'activo', 'umbrales', 'umbral_fichero'} o lanza ConfigInvalida."""
    return {"activo": activo(), "umbrales": umbrales(),
            "umbral_fichero": umbral_fichero()}


# ── Clave canonica ───────────────────────────────────────────────────────────

def _ordenar(valor):
    """Key-sort RECURSIVO: dicts anidados en listas, listas en dicts, todo."""
    if isinstance(valor, dict):
        return {str(k): _ordenar(valor[k]) for k in sorted(valor, key=str)}
    if isinstance(valor, (list, tuple)):
        return [_ordenar(v) for v in valor]
    return valor


def _normalizar_args(args):
    if isinstance(args, (dict, list, tuple)):
        return _ordenar(args)
    if args is None:
        return ""
    texto = str(args).strip()
    if texto[:1] in ("{", "["):
        try:
            return _ordenar(json.loads(texto))
        except Exception:
            pass
    # el protocolo texto 'a | b': solo los espacios varian entre dos llamadas
    # que el modelo considera la misma
    return re.sub(r"\s+", " ", texto)


def clave_canonica(tool: str, args) -> str:
    """JSON canonico de [tool, args]: sort_keys recursivo, sin espacios,
    default=str para lo que no sea JSON (Path, bytes...)."""
    return json.dumps([str(tool), _normalizar_args(args)], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, default=str)


# ── Textos ───────────────────────────────────────────────────────────────────

def _citar_args(args) -> str:
    if isinstance(args, (dict, list, tuple)):
        try:
            texto = json.dumps(_ordenar(args), ensure_ascii=False, default=str)
        except Exception:
            texto = str(args)
    else:
        texto = str(args if args is not None else "")
    texto = texto.strip()
    if len(texto) > CAP_ARGS:
        return texto[:CAP_ARGS] + f"... [{len(texto) - CAP_ARGS} chars mas]"
    return texto


def texto_suave(tool: str, n: int) -> str:
    return (f"{MARCA} Estas repitiendo la misma llamada a '{tool}' con los "
            f"mismos argumentos ({n} veces seguidas). Analiza el resultado "
            f"previo antes de repetirla: si ya te dio lo que necesitabas, "
            f"usalo; si fallo, cambia los argumentos o la herramienta.")


def texto_detallado(tool: str, n: int, args) -> str:
    return (f"{MARCA} '{tool}' lleva {n} llamadas CONSECUTIVAS con estos "
            f"argumentos exactos:\n    {_citar_args(args)}\n"
            f"No vuelvas a llamar '{tool}' con estos argumentos exactos: el "
            f"resultado va a ser el mismo. Lee el resultado que ya tienes y "
            f"decide otra accion (otros argumentos, otra herramienta, o la "
            f"respuesta final con lo que hay).")


def texto_fichero(ruta: str, n: int) -> str:
    """El nudge de RECONSIDERACION por fichero (misma voz que los dos de
    arriba: concreto, cita el hecho, pide un cambio de enfoque)."""
    return (f"{MARCA} Llevas {n} ediciones sobre {ruta} sin cerrar el "
            f"problema. Antes de la siguiente: relee el fichero entero, "
            f"enuncia la causa por escrito y cambia de enfoque; si no puedes, "
            f"para y explica.")


# ── El contador por agente ───────────────────────────────────────────────────

class Contador:
    """(clave, n) de la racha consecutiva en curso. Un contador por ctx."""

    def __init__(self):
        self.clave = None
        self.n = 0
        self.tool = ""
        self.args = None
        self.generacion = _GENERACION[0]
        self.recordatorios = 0

    def reset(self) -> None:
        self.clave = None
        self.n = 0
        self.tool = ""
        self.args = None
        self.generacion = _GENERACION[0]

    def registrar(self, tool: str, args, ok: bool = True) -> str:
        """Anota la llamada y devuelve el recordatorio a anexar ('' si no
        toca). `ok` se acepta por contrato (las fallidas cuentan IGUAL) y
        queda en la telemetria. Lanza ConfigInvalida si los umbrales son
        basura: el hook la convierte en aviso degradado."""
        if self.generacion != _GENERACION[0]:
            self.reset()
        if tool in EXENTAS:
            return ""                   # transparente: ni cuenta ni corta
        lista = umbrales()
        clave = clave_canonica(tool, args)
        if clave == self.clave:
            self.n += 1
        else:
            self.clave, self.n, self.tool, self.args = clave, 1, tool, args
        if self.n == lista[0]:
            texto = texto_suave(tool, self.n)
        elif self.n in lista[1:]:
            texto = texto_detallado(tool, self.n, args)
        else:
            return ""
        self.recordatorios += 1
        _TOTAL[0] += 1
        _ULTIMO.clear()
        _ULTIMO.update({"tool": tool, "n": self.n, "ok": bool(ok),
                        "tipo": "suave" if self.n == lista[0] else "detallado",
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        return texto

    def estado(self) -> dict:
        return {"tool": self.tool, "n": self.n,
                "recordatorios": self.recordatorios}


def normalizar_ruta(ruta) -> str:
    """Clave de fichero: sin comillas, separadores '/', sin './', y en
    minusculas (Windows no distingue mayusculas; 'A.py' y 'a.py' son el
    mismo fichero y el modelo alterna entre ambas cuando se atasca)."""
    texto = str(ruta or "").strip().strip('"').strip("'")
    if not texto:
        return ""
    return os.path.normpath(texto).replace("\\", "/").lower()


class ContadorFichero:
    """Ediciones por fichero normalizado dentro de UNA tarea (el bucle
    nativo crea uno por bucle_nativo). Hermano de Contador: mismo reset por
    prompt humano, misma telemetria de proceso, mismo 'nunca veta'.

    `registrar(ruta, tool)` devuelve el nudge cuando el fichero ALCANZA el
    umbral (n == umbral) y de nuevo en cada multiplo (2N, 3N...): una vez por
    cruce, nunca en cada edicion (un nudge en cada paso es ruido que el
    modelo aprende a ignorar). Tools fuera de TOOLS_EDICION y rutas vacias
    son transparentes."""

    def __init__(self):
        self.por_fichero: dict = {}
        self.generacion = _GENERACION[0]
        self.nudges = 0

    def reset(self) -> None:
        self.por_fichero = {}
        self.generacion = _GENERACION[0]

    def registrar(self, ruta, tool: str) -> str:
        if self.generacion != _GENERACION[0]:
            self.reset()
        if tool not in TOOLS_EDICION:
            return ""
        clave = normalizar_ruta(ruta)
        if not clave:
            return ""
        umbral = umbral_fichero()
        n = self.por_fichero.get(clave, 0) + 1
        self.por_fichero[clave] = n
        if n < umbral or n % umbral != 0:
            return ""
        self.nudges += 1
        _TOTAL_FICHERO[0] += 1
        _ULTIMO_FICHERO.clear()
        _ULTIMO_FICHERO.update({"ruta": clave, "n": n, "tool": tool,
                                "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        return texto_fichero(clave, n)

    def estado(self) -> dict:
        return {"ficheros": dict(self.por_fichero), "nudges": self.nudges}


_GLOBAL = Contador()     # fallback cuando run_tool no recibe un ctx dict


def contador_de(ctx) -> Contador:
    """El contador del agente duenio de `ctx` (se guarda en el propio ctx:
    un subagente con su ctx tiene el suyo). Sin ctx dict, el global."""
    if isinstance(ctx, dict):
        c = ctx.get("_repeticion")
        if not isinstance(c, Contador):
            c = Contador()
            ctx["_repeticion"] = c
        return c
    return _GLOBAL


def nuevo_prompt_humano() -> None:
    """El REPL lo llama con cada linea humana: todos los contadores se
    resetean en su proxima llamada (y el global ya)."""
    _GENERACION[0] += 1
    _GLOBAL.reset()


# ── El hook (lo que cablea el interceptor) ───────────────────────────────────

def anexar(name: str, args, ctx, texto: str, ok: bool = True) -> str:
    """Cuenta la llamada y, si toca, anexa el recordatorio al final de
    `texto`. NUNCA lanza; apagado o roto devuelve `texto` tal cual."""
    try:
        if not activo():
            return texto
        rec = contador_de(ctx).registrar(name, args, ok)
    except ConfigInvalida as exc:
        _avisar(f"config invalida, guard apagado: {exc}")
        return texto
    except Exception as exc:
        _avisar(f"{type(exc).__name__}: {exc}")
        return texto
    if not rec:
        return texto
    base = texto if isinstance(texto, str) else str(texto)
    return base.rstrip() + "\n\n" + rec


def estado() -> dict:
    """La foto del subsistema para /bucle estado. No lanza: una config rota
    sale como 'error' en vez de reventar la puerta."""
    try:
        act = activo()
        err_act = ""
    except ConfigInvalida as exc:
        act, err_act = False, str(exc)
    try:
        umb = umbrales()
        err_umb = ""
    except ConfigInvalida as exc:
        umb, err_umb = UMBRALES_DEFECTO, str(exc)
    try:
        umb_f = umbral_fichero()
        err_f = ""
    except ConfigInvalida as exc:
        umb_f, err_f = UMBRAL_FICHERO_DEFECTO, str(exc)
    return {
        "activo": act,
        "umbrales": umb,
        "config_error": err_act or err_umb or err_f,
        "exentas": sorted(EXENTAS),
        "total": _TOTAL[0],
        "ultimo": dict(_ULTIMO),
        "ultimo_error": dict(_ULTIMO_ERROR),
        "generacion": _GENERACION[0],
        # bucle por fichero (ContadorFichero)
        "umbral_fichero": umb_f,
        "total_fichero": _TOTAL_FICHERO[0],
        "ultimo_fichero": dict(_ULTIMO_FICHERO),
    }
