# -*- coding: utf-8 -*-
"""
cognia/harness/notificaciones.py
================================
NOTIFICACIONES DE ESCRITORIO via OSC 9: un toast del terminal cuando el agente
termina un turno largo o cuando algo se degrada.

POR QUE EXISTE (2026-08-23): un turno del 27B local dura MINUTOS y el dueno se
va a otra ventana mientras tanto. Hoy no hay NINGUNA senal de "ya termine":
hay que volver a la ventana a mirar. Es el patron de Crush (notifica al
terminar el turno y al pedir permiso, backends auto|native|osc|bell|disabled)
y de Codex. Windows Terminal soporta OSC 9 (ESC ] 9 ; texto BEL) y lo pinta
como toast nativo; cualquier terminal que no lo soporte ignora la secuencia
sin ensuciar nada, y para esos queda el modo 'bell' (BEL a secas, que como
minimo hace parpadear la pestana).

MODOS (env COGNIA_NOTIFY gana a la config; /notificar la cambia persistida):

    auto   (default) OSC 9 solo si hay una terminal DE VERDAD al otro lado
           del stdout REAL (mismo criterio por fd que renderer._consola_
           interactiva: un pipe/CI no recibe secuencias de escape jamas).
    osc    OSC 9 siempre (para forzarlo en demos/capturas).
    bell   solo BEL (terminales sin soporte OSC 9).
    off    nada.

EL SINK: la secuencia va a ``sys.__stdout__`` (el fd real), NO a ``sys.stdout``
del momento. Con la vista Textual abierta sys.stdout es su _PrintCapture y una
secuencia escrita ahi no llega nunca al terminal (se descarta o se pinta como
texto); escribir al fd real es seguro porque un OSC/BEL no pinta NADA visible:
el terminal lo interpreta, no lo muestra — no puede ensuciar la pantalla
alterna como si ensuciaban las lineas "@EV" de ux/events._stdout_real.

Esto es solo el MECANISMO: arma la secuencia y la emite. El cableado (cuando
notificar) lo hace el integrador via `notificar_evento` y el registry EVENTOS:

    from cognia.harness import notificaciones as notif

    # al terminar un turno (renderer._on_tarea_fin ya tiene la duracion):
    notif.notificar_evento("turno_terminado", duracion_s=dur)
    # -> solo emite si dur >= umbral_segundos() (default 20 s)

    # cuando salta un degradado (cli._aviso_degradado):
    notif.notificar_evento("degradado", via="backend", detalle="...")
    # -> solo emite si la config 'notificar_degradado' esta en on (default
    #    off: los degradados ya se ven ambar en el REPL y un toast por cada
    #    uno seria spam)

API publica:

    notificar(titulo, cuerpo, destino=None, modo=None) -> bool
        Emite UNA notificacion. True si algo salio al stream. NUNCA lanza:
        un fallo emitiendo avisa por el avisador registrado (una vez por
        sesion) y devuelve False. `destino`/`modo` existen para los tests y
        para /notificar prueba; en produccion se dejan en None.

    notificar_evento(nombre, destino=None, **datos) -> bool
        Punto de extension: busca el builder en EVENTOS y emite lo que este
        devuelva. Un builder devuelve (titulo, cuerpo) o None ("este evento
        no amerita toast": bajo umbral, opt-in apagado...). Anadir un caso
        nuevo = una entrada nueva en el dict, cero cambios aca.

    modo_activo() -> str          'auto'|'osc'|'bell'|'off' efectivo
    umbral_segundos() -> float    umbral del turno largo (config, default 20)
    estado() -> dict              foto para la puerta /notificar del CLI
    registrar_avisador(fn)        el CLI pasa su _aviso_degradado

La config se lee a CALL-TIME de la config persistida del CLI (claves
'notificar', 'notificar_modo', 'notificar_umbral_s', 'notificar_degradado';
se cambian con /notificar) mirando sys.modules SIN importar cli: un modulo
suelto en tests no paga las 15k lineas de cli.py por un default.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

logger = logging.getLogger("cognia.harness.notificaciones")

# Umbral del turno largo (segundos) si la config no dice otra cosa: por debajo
# el toast molesta (el dueno sigue mirando), por encima ya se fue a otra ventana.
UMBRAL_SEGUNDOS = 20.0

# Tope de chars del texto del toast: Windows Terminal trunca solo, pero un
# titulo+cuerpo de 4 KB (un traceback entero) ni siquiera debe intentarse.
_TOPE_TEXTO = 200

_MODOS_VALIDOS = ("auto", "osc", "bell", "off")

# Telemetria minima para la puerta /notificar del CLI: la ultima notificacion
# emitida y el ultimo fallo del subsistema. Solo memoria de proceso.
_ULTIMO: dict = {}
_ULTIMO_ERROR: dict = {}

# Punto de extension: el CLI registra aca su _aviso_degradado para que un
# fallo emitiendo se VEA en el REPL ademas del logger. None = solo logger.
_AVISADOR = None

# Un fallo emitiendo avisa UNA vez por sesion: la notificacion es adorno y un
# terminal que rechaza el write lo rechaza siempre — repetir el aviso por cada
# turno seria exactamente el spam que este modulo quiere evitar.
_AVISADO = [False]


def registrar_avisador(fn) -> None:
    """Registra el callable (origen, motivo) -> None que recibe los fallos del
    subsistema (el CLI pasa su `_aviso_degradado`). Un solo avisador: el ultimo
    registrado gana (el REPL se registra una vez al arrancar)."""
    global _AVISADOR
    _AVISADOR = fn


# ── Config a call-time (sin importar cli) ────────────────────────────────────

def _leer_config_cli() -> dict:
    """La config persistida del CLI si cli.py ya esta cargado; {} si no.
    Se mira sys.modules y NO se importa: mismo criterio que _config_colapso
    del renderer. Los tests monkeypatchean esta funcion."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            return _cli._load_config()
    except Exception as exc:
        logger.warning("harness.notificaciones config ilegible: %s", exc)
    return {}


def _cfg(clave: str, default: str) -> str:
    valor = _leer_config_cli().get(clave, default)
    return str(valor).strip().lower()


def _encendido_en(valor: str) -> bool:
    return valor not in ("off", "0", "false", "no")


def modo_activo() -> str:
    """El modo efectivo: env COGNIA_NOTIFY gana a TODO (apagado/forzado de
    emergencia), despues 'notificar' off apaga, despues 'notificar_modo'."""
    env = os.environ.get("COGNIA_NOTIFY", "").strip().lower()
    if env:
        if env in _MODOS_VALIDOS:
            return env
        if env in ("0", "false", "no", "disabled"):
            return "off"
        if env in ("1", "on", "true"):
            return "auto"
        # Un valor irreconocible NO apaga en silencio: se avisa y se cae al
        # default (la env olvidada con typo es la clase de bug del estilo
        # conservador de mejorar_prompt).
        _degradar("modo", ValueError(f"COGNIA_NOTIFY={env!r} no es "
                                     f"{'|'.join(_MODOS_VALIDOS)}"))
    if not _encendido_en(_cfg("notificar", "on")):
        return "off"
    cfg_modo = _cfg("notificar_modo", "auto")
    return cfg_modo if cfg_modo in _MODOS_VALIDOS else "auto"


def umbral_segundos() -> float:
    """Umbral del turno largo, de la config ('notificar_umbral_s')."""
    try:
        return float(_cfg("notificar_umbral_s", str(UMBRAL_SEGUNDOS)))
    except ValueError:
        return UMBRAL_SEGUNDOS


# ── El mecanismo: armar y emitir la secuencia ────────────────────────────────

def _sanear(texto: str) -> str:
    """Sin controles: un ESC o un BEL DENTRO del texto rompe/cierra la propia
    secuencia OSC y el resto se pinta crudo en el terminal."""
    limpio = "".join(c for c in (texto or "") if ord(c) >= 0x20)
    return limpio[:_TOPE_TEXTO]


def secuencia_osc9(titulo: str, cuerpo: str) -> str:
    """La secuencia exacta: ESC ] 9 ; titulo: cuerpo BEL (Windows Terminal la
    pinta como toast). Funcion pura, separada para que el test la fije."""
    titulo, cuerpo = _sanear(titulo), _sanear(cuerpo)
    texto = f"{titulo}: {cuerpo}" if titulo and cuerpo else (titulo or cuerpo)
    return f"\x1b]9;{texto}\x07"


def _destino_real():
    """El fd REAL del proceso (ver docstring del modulo: con Textual abierto
    sys.stdout es un _PrintCapture y la secuencia moriria ahi). Puede ser None
    (pythonw): entonces no hay a donde notificar."""
    real = getattr(sys, "__stdout__", None)
    return real if real is not None else sys.stdout


def _es_tty(stream) -> bool:
    """Mismo criterio por fd que renderer._consola_interactiva: ante la duda
    False — perder un toast es cosmetico, meter bytes de escape en un pipe de
    diagnostico no lo es."""
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def notificar(titulo: str, cuerpo: str, destino=None, modo: str | None = None) -> bool:
    """Emite UNA notificacion segun el modo efectivo. True si salio algo.

    `destino` (stream) y `modo` son overrides para tests y /notificar prueba;
    en produccion quedan en None y deciden modo_activo() y el fd real.
    NUNCA lanza: el fallo se degrada (avisador, una vez por sesion)."""
    try:
        m = (modo or modo_activo()).strip().lower()
        if m == "off" or m not in _MODOS_VALIDOS:
            return False
        stream = destino if destino is not None else _destino_real()
        if stream is None:
            return False
        if destino is None and not _es_tty(stream):
            # El fd REAL no es un terminal (sesion remota con stdout=PIPE, CI,
            # redireccion): NINGUN modo, ni siquiera 'osc'/'bell' forzados,
            # puede escribirle bytes de escape — la secuencia se pega como
            # prefijo de la linea siguiente del canal JSONL y '@EV {...}' deja
            # de casar en remoto/sesiones.py: el movil pierde justo el evento
            # de fin de turno (revision adversarial 2026-08-23). El gate cubre
            # solo el destino de produccion: un `destino` inyectado (tests,
            # buffers propios) es responsabilidad de quien lo inyecta.
            return False
        if m == "auto":
            if not _es_tty(stream):
                return False
            m = "osc"
        secuencia = secuencia_osc9(titulo, cuerpo) if m == "osc" else "\a"
        stream.write(secuencia)
        stream.flush()
        _ULTIMO.clear()
        _ULTIMO.update(titulo=_sanear(titulo), cuerpo=_sanear(cuerpo), modo=m,
                       ts=datetime.now().isoformat(timespec="seconds"))
        return True
    except Exception as exc:
        _degradar("emitir", exc)
        return False


# ── Punto de extension: eventos con builder ──────────────────────────────────

def _ev_turno_terminado(duracion_s: float = 0.0, **_) -> tuple | None:
    """Turno del agente terminado: solo amerita toast si duro lo bastante
    como para que el dueno se haya ido a otra ventana."""
    if duracion_s < umbral_segundos():
        return None
    return ("Cognia", f"turno terminado ({duracion_s:.0f}s)")


def _ev_degradado(via: str = "", detalle: str = "", **_) -> tuple | None:
    """Degradado del sistema: OPT-IN por config (default off). El REPL ya lo
    pinta ambar; el toast es para el que no esta mirando, y solo si lo pidio."""
    if not _encendido_en(_cfg("notificar_degradado", "off")):
        return None
    cuerpo = f"{via}: {detalle}" if detalle else via
    return ("Cognia degradado", cuerpo)


# nombre del evento -> builder(**datos) -> (titulo, cuerpo) | None.
# Anadir un caso futuro (permiso pedido, workflow terminado...) = una entrada.
EVENTOS = {
    "turno_terminado": _ev_turno_terminado,
    "degradado":       _ev_degradado,
}


def notificar_evento(nombre: str, destino=None, **datos) -> bool:
    """Busca el builder de `nombre` en EVENTOS y emite lo que devuelva.
    None del builder = "sin toast" (bajo umbral, opt-in apagado): False sin
    ser un fallo. Un nombre desconocido SI se degrada: es un cableado roto."""
    try:
        builder = EVENTOS.get(nombre)
        if builder is None:
            _degradar("evento", KeyError(f"evento sin builder: {nombre!r}"))
            return False
        par = builder(**datos)
        if not par:
            return False
        return notificar(par[0], par[1], destino=destino)
    except Exception as exc:
        _degradar(f"evento {nombre}", exc)
        return False


# ── Degradacion y estado ─────────────────────────────────────────────────────

def _degradar(donde: str, exc: Exception) -> None:
    """La notificacion es ADORNO: si falla, se avisa (logger + el avisador del
    CLI si esta registrado, UNA vez por sesion) y el turno sigue."""
    motivo = f"{donde}: {exc.__class__.__name__}: {exc}"
    logger.warning("harness.notificaciones degradado: %s", motivo)
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update(motivo=motivo,
                         ts=datetime.now().isoformat(timespec="seconds"))
    if _AVISADO[0]:
        return
    _AVISADO[0] = True
    if _AVISADOR is not None:
        try:
            _AVISADOR("notificaciones", motivo)
        except Exception as exc2:
            # El aviso jamas puede romper el camino que esta avisando.
            logger.warning("harness.notificaciones avisador roto: %s", exc2)


def estado() -> dict:
    """Foto del subsistema para la puerta /notificar del CLI."""
    env = os.environ.get("COGNIA_NOTIFY", "").strip()
    destino = _destino_real()
    return {
        "modo": modo_activo(),
        "fuente": f"env COGNIA_NOTIFY={env}" if env else "config 'notificar'/'notificar_modo'",
        "umbral_s": umbral_segundos(),
        "degradado_optin": _encendido_en(_cfg("notificar_degradado", "off")),
        "consola_interactiva": _es_tty(destino) if destino is not None else False,
        "eventos": sorted(EVENTOS),
        "ultima": dict(_ULTIMO),
        "ultimo_error": dict(_ULTIMO_ERROR),
    }
