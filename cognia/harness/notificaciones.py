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
y de Codex.

CORRECCION CON EVIDENCIA (2026-08-23, misma noche): el toast OSC 9 PLANO
(ESC ] 9 ; texto BEL) NO esta soportado en Windows Terminal — el issue
microsoft/terminal#8592 sigue ABIERTO y WT interpreta la familia OSC 9;x como
secuencias ConEmu, asi que el "toast del terminal" de la primera version era
un no-op justo en la terminal del dueno. Lo que SI funciona en WT:
  (a) OSC 9;4 progreso (ConEmu): ESC ] 9 ; 4 ; <estado> ; <pct> BEL pinta un
      anillo en la pestana Y en la taskbar (0=ocultar 1=normal 2=error rojo
      3=indeterminado 4=warning) — la senal "estoy trabajando" visible desde
      otra ventana;
  (b) BEL '\\a': flash de la taskbar si la ventana no tiene foco;
  (c) el toast NATIVO de Windows via PowerShell (patron Aider
      io.py get_default_notification_command: un comando por SO).

MODOS (env COGNIA_NOTIFY gana a la config; /notificar la cambia persistida):

    auto   (default) solo con una terminal DE VERDAD al otro lado del stdout
           REAL (mismo criterio por fd que renderer._consola_interactiva: un
           pipe/CI no recibe secuencias de escape jamas). Bajo Windows
           Terminal (WT_SESSION en el env) el aviso de fin de turno es BEL
           (el OSC 9 plano seria un no-op ahi); en otras terminales, OSC 9.
    osc    OSC 9 plano siempre (terminales que SI lo pintan: WezTerm,
           ConEmu... — Windows Terminal NO).
    bell   solo BEL (terminales sin soporte OSC 9).
    toast  notificacion NATIVA del SO (PowerShell NotifyIcon en Windows,
           plyer si esta en el venv, notify-send en Linux); si nada esta
           disponible degrada a bell avisando una vez.
    off    nada.

EL ANILLO DE PROGRESO (independiente del modo, solo bajo WT y modo != off):
turno_inicio() emite 9;4;3 (indeterminado) al arrancar el turno del agente,
turno_fin(ok=True) lo limpia con 9;4;0, turno_fin(ok=False) deja 9;4;2;100
(rojo) y progreso_limpiar() — el REPL la llama al siguiente prompt tecleado —
lo apaga cuando el dueno ya volvio. Lo cablea el renderer en TareaInicio/
TareaFin, asi que el spinner vivo y el anillo comparten disparador.

QUIEN NO NOTIFICA JAMAS: los subagentes (contexto de agente sellado en
ux.events.agente_actual()) y el carril de fondo del REPL (cli.corrida_en_
curso()): ahi el dueno esta EN el prompt tecleando; un toast por cada agente
de un workflow seria spam puro.

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
import re
import sys
from datetime import datetime

logger = logging.getLogger("cognia.harness.notificaciones")

# Umbral del turno largo (segundos) si la config no dice otra cosa: por debajo
# el toast molesta (el dueno sigue mirando), por encima ya se fue a otra ventana.
UMBRAL_SEGUNDOS = 20.0

# Tope de chars del texto del toast (patron OpenCode): un titulo+cuerpo de
# 4 KB (un traceback entero) ni siquiera debe intentarse.
_TOPE_TEXTO = 240

# Secuencias ANSI dentro del texto (un resumen puede traer el color del REPL):
# CSI entera (colores/cursor), OSC entera (hasta BEL o ST) y cualquier otro
# escape de dos bytes. Se quitan ANTES del filtro de controles para no dejar
# la cola de la secuencia ('[31m') como texto literal en el toast.
_RE_ANSI = re.compile(
    r"\x1b\[[0-9;:?]*[ -/]*[@-~]"           # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC
    # Un ESC suelto (o el arranque de otra secuencia) lo quita el filtro de
    # controles de _sanear: comerse tambien el char SIGUIENTE mutilaba texto
    # legitimo ('Cog\x1bnia' -> 'Cogia', cazado por el test viejo).
)

_MODOS_VALIDOS = ("auto", "osc", "bell", "toast", "off")

# Estados del OSC 9;4 (ConEmu; Windows Terminal los pinta en pestana+taskbar).
PROG_OCULTAR, PROG_NORMAL, PROG_ERROR, PROG_INDET, PROG_WARN = 0, 1, 2, 3, 4

# turno_fin(ok=False) dejo el anillo en ROJO y hay que apagarlo cuando el
# dueno vuelva: progreso_limpiar() (el REPL la llama al siguiente prompt
# tecleado) lo consume. Solo memoria de proceso, como _ULTIMO.
_ERROR_PENDIENTE = [False]

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
    """Sin ANSI ni controles, tope 240 chars (patron OpenCode): un ESC o un
    BEL DENTRO del texto rompe/cierra la propia secuencia OSC y el resto se
    pinta crudo; una secuencia de color entera ('\\x1b[31m') dejaria su cola
    como basura literal en el toast nativo."""
    sin_ansi = _RE_ANSI.sub("", texto or "")
    limpio = "".join(c for c in sin_ansi if ord(c) >= 0x20 and ord(c) != 0x7f)
    return limpio[:_TOPE_TEXTO]


def en_wt() -> bool:
    """True bajo Windows Terminal (WT_SESSION en el env). WT NO pinta el
    OSC 9 plano (issue microsoft/terminal#8592, abierto: interpreta 9;x como
    ConEmu), pero SI el 9;4 de progreso y el BEL."""
    return bool(os.environ.get("WT_SESSION", "").strip())


def secuencia_osc9(titulo: str, cuerpo: str) -> str:
    """La secuencia exacta del toast OSC 9 PLANO: ESC ] 9 ; titulo: cuerpo
    BEL (la pintan WezTerm/ConEmu...; Windows Terminal NO — ver en_wt).
    Funcion pura, separada para que el test la fije."""
    titulo, cuerpo = _sanear(titulo), _sanear(cuerpo)
    texto = f"{titulo}: {cuerpo}" if titulo and cuerpo else (titulo or cuerpo)
    return f"\x1b]9;{texto}\x07"


def secuencia_progreso(estado: int, pct: int | None = None) -> str:
    """La secuencia exacta del progreso ConEmu que WT SI soporta:
    ESC ] 9 ; 4 ; estado [; pct] BEL. Estados en PROG_* (0=ocultar 1=normal
    2=error rojo 3=indeterminado 4=warning); pct solo pesa en 1/2/4."""
    if pct is None:
        return f"\x1b]9;4;{int(estado)}\x07"
    return f"\x1b]9;4;{int(estado)};{int(pct)}\x07"


def _en_fondo() -> bool:
    """True si esto corre en un subagente (contexto sellado en el bus de
    eventos) o con el carril de fondo del REPL vivo: esos JAMAS notifican —
    el dueno esta EN el prompt y un toast por agente de workflow es spam.
    Se mira sys.modules sin importar nada (mismo criterio que _leer_config_
    cli); ante un fallo del gate se avisa y se deja notificar (perder el gate
    es spam recuperable; perder el toast del turno largo es el bug F5)."""
    try:
        _ev = sys.modules.get("cognia.ux.events")
        if _ev is not None and _ev.agente_actual():
            return True
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None and _cli.corrida_en_curso():
            return True
    except Exception as exc:
        _degradar("gate_fondo", exc)
    return False


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
        if _en_fondo():
            # Subagente o carril de fondo: JAMAS notifican (ver docstring).
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
            # Bajo Windows Terminal el OSC 9 plano es un NO-OP (#8592): el
            # aviso audible/visible que si funciona ahi es el BEL (flash de
            # taskbar sin foco). El anillo 9;4 va aparte (turno_inicio/fin).
            m = "bell" if en_wt() else "osc"
        if m == "toast":
            if _toast_nativo(_sanear(titulo), _sanear(cuerpo)):
                _ULTIMO.clear()
                _ULTIMO.update(titulo=_sanear(titulo), cuerpo=_sanear(cuerpo),
                               modo="toast",
                               ts=datetime.now().isoformat(timespec="seconds"))
                return True
            # Sin toast nativo posible: _toast_nativo ya aviso (una vez);
            # degradar a bell para que ALGO suene igual.
            m = "bell"
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


# ── Toast nativo del SO (modo 'toast') ───────────────────────────────────────

def _toast_nativo(titulo: str, cuerpo: str) -> bool:
    """Notificacion NATIVA del SO, sin dependencias nuevas (patron Aider,
    io.py get_default_notification_command: un comando por SO). Orden:
    plyer si YA esta en el venv; en Windows, PowerShell con el NotifyIcon
    estandar de WinForms (globo del area de notificacion — cero paquetes);
    en Linux, notify-send. El proceso se lanza y NO se espera: el toast es
    adorno y un PowerShell de 7 s no puede congelar el fin del turno.
    False = nada disponible/fallo (ya degradado aca, una vez por sesion)."""
    titulo = titulo or "Cognia"
    cuerpo = cuerpo or "..."       # ShowBalloonTip revienta con texto vacio
    try:
        from plyer import notification as _plyer_notif
    except Exception:
        _plyer_notif = None
    if _plyer_notif is not None:
        try:
            _plyer_notif.notify(title=titulo, message=cuerpo, timeout=6)
            return True
        except Exception as exc:
            # plyer instalado pero sin backend util: cae al camino por SO.
            logger.warning("harness.notificaciones plyer fallo: %s", exc)
    try:
        import subprocess
        if sys.platform == "win32":
            t = titulo.replace("'", "''")   # comilla simple de PS
            c = cuerpo.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(6000, '{t}', '{c}', "
                "[System.Windows.Forms.ToolTipIcon]::Info); "
                "Start-Sleep -Seconds 7; $n.Dispose()"
            )
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
                 "-Command", ps],
                creationflags=0x08000000,   # CREATE_NO_WINDOW
            )
            return True
        subprocess.Popen(["notify-send", titulo, cuerpo])
        return True
    except Exception as exc:
        _degradar("toast", exc)
        return False


# ── El anillo de progreso OSC 9;4 (Windows Terminal) ─────────────────────────

def progreso(estado: int, pct: int | None = None, destino=None) -> bool:
    """Emite UNA secuencia 9;4 al fd real (o al `destino` de los tests).
    Gates: modo != off, Windows Terminal presente (fuera de WT el 9;4 es
    ruido para el terminal), ni subagente ni carril de fondo, y el mismo
    gate de tty por fd que notificar. NUNCA lanza."""
    try:
        if modo_activo() == "off" or not en_wt() or _en_fondo():
            return False
        stream = destino if destino is not None else _destino_real()
        if stream is None:
            return False
        if destino is None and not _es_tty(stream):
            return False
        stream.write(secuencia_progreso(estado, pct))
        stream.flush()
        return True
    except Exception as exc:
        _degradar("progreso", exc)
        return False


def turno_inicio(destino=None) -> bool:
    """Arranca el turno del agente: anillo INDETERMINADO en pestana/taskbar
    (la senal 'estoy trabajando' aunque el dueno este en otra ventana). Lo
    llama el renderer en TareaInicio."""
    return progreso(PROG_INDET, destino=destino)


def turno_fin(ok: bool = True, destino=None) -> bool:
    """Termina el turno: OK limpia el anillo (9;4;0); error lo deja ROJO al
    100% (9;4;2;100) y queda pendiente hasta progreso_limpiar(). Lo llama el
    renderer en TareaFin; el BEL/toast del turno largo va aparte
    (notificar_evento('turno_terminado'))."""
    if ok:
        _ERROR_PENDIENTE[0] = False
        return progreso(PROG_OCULTAR, destino=destino)
    emitido = progreso(PROG_ERROR, 100, destino=destino)
    _ERROR_PENDIENTE[0] = emitido
    return emitido


def progreso_limpiar(destino=None) -> bool:
    """Apaga el anillo ROJO que dejo un turno en error. El REPL la llama al
    siguiente prompt TECLEADO (no al mostrarse: si se limpiara al pintar el
    prompt, el rojo viviria milisegundos y el dueno en otra ventana no lo
    veria jamas). Sin error pendiente es un no-op barato."""
    if not _ERROR_PENDIENTE[0]:
        return False
    _ERROR_PENDIENTE[0] = False
    return progreso(PROG_OCULTAR, destino=destino)


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
        "wt": en_wt(),
        "error_pendiente": _ERROR_PENDIENTE[0],
        "en_fondo": _en_fondo(),
        "eventos": sorted(EVENTOS),
        "ultima": dict(_ULTIMO),
        "ultimo_error": dict(_ULTIMO_ERROR),
    }
