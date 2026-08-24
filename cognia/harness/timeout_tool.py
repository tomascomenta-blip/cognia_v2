# -*- coding: utf-8 -*-
"""
cognia/harness/timeout_tool.py
==============================
TIMEOUT POR TOOL con RESULTADO ESTRUCTURADO: si una herramienta no vuelve en
su plazo, el modelo recibe un resultado tipado ('ERROR: tool agotada tras Ns
(TOOL_TIMEOUT)') que baja por el camino normal (interceptor.despues, render,
buffer) — nunca una excepcion que salte el pipeline — y el proceso hijo se
espera/mata DE VERDAD antes de seguir.

POR QUE EXISTE (2026-08-24, timeout-policy de deepseek-harness): una tool
colgada (un http_get contra un host que no contesta, un subagente que se
queda pensando, una lectura de un pipe que nunca cierra) congelaba el turno
entero sin ninguna senal — el spinner seguia y el dueno no sabia si el modelo
pensaba o el agente estaba muerto. Y la leccion propia del repo 'matar el
shell NO mata el proceso' (2026-08-15): un banco 'abortado' siguio 2 h
golpeando el unico slot de GPU. Por eso aqui el vencimiento no es un `return`
y a otra cosa: se pide la cancelacion cooperativa, se matan los hijos
REGISTRADOS por arbol y se espera acotadamente a que el hilo de la tool
termine; lo que no quiescio se DICE (aviso degradado + campo en el resultado).

PRECEDENCIA (documentada):
    1. `spec['timeout_s']` declarado en @tool ......... manda sobre el global.
       0 = sin limite (subagentes/LLM: el reloj lo pone el backend).
    2. global `COGNIA_TOOL_TIMEOUT` (config 'tool_timeout_s', default 120;
       0 = sin limite) ................................. para el resto.
    3. `spec['timeout_interno']` (callable(args) -> segundos): el timeout que
       la propia tool aplica a su subprocess (ejecutar: 'timeout=N' de los
       args, default 30 / max 600; tests: 180). El deadline externo NUNCA
       corta antes que el interno: efectivo = max(externo, interno + margen).
       Asi un `ejecutar ... | timeout=300` sigue viviendo 300 s aunque el
       global sea 120, y su error de timeout es el suyo (accionable), no este.
    4. `SIN_DEADLINE`: tools que llaman al modelo o a un subagente. Con el 27B
       local un subagente tarda minutos legitimamente; el deadline seria
       ruido. Declarar timeout_s en su @tool lo cambia.

CONFIG (se valida al cargar, falla RUIDOSO con basura: ConfigInvalida)
    COGNIA_TOOL_TIMEOUT          segundos (entero >= 0). Vacio = 120.
    COGNIA_TOOL_TIMEOUT_GRACIA   segundos de espera de quiescencia tras el
                                 vencimiento (entero >= 0). Vacio = 5.

CONTRATO
    correr_con_deadline(fn, name, args, ctx, limite) -> (out, agotada, info)
        Corre `fn(args, ctx)` en un hilo con deadline. Si vuelve a tiempo,
        `out` es su resultado y `agotada` False (una excepcion de la tool se
        RE-LANZA en el hilo llamador: run_tool ya la maneja). Si vence:
        `out` es el texto tipado, `agotada` True e `info` dice si el hilo y
        los hijos quiesceron. NO lanza por el vencimiento.
    Las tools que lanzan procesos los registran en ctx['_procesos_tool']
    (lista de Popen) para que el vencimiento los mate por arbol (en el repo
    lo hace tools._correr_proceso, el subprocess de 'ejecutar'/'tests'/git);
    las que quieren cooperar miran ctx['_cancelar_tool'] (threading.Event)
    o ctx['_deadline'] (epoch).

    pedir_al_llamador(fn) -> (True, fn()) | (False, None)
        Desde el hilo de la tool: corre `fn` EN EL HILO QUE ESPERA en
        correr_con_deadline (el dueno de la consola cuando run_tool se llamo
        desde el principal) y devuelve su resultado. (False, None) si este
        hilo no es un worker del modulo o su deadline ya vencio. POR QUE
        (revision adversarial 2026-08-24): el ctx['confirm'] del sentinel
        (cli._confirmar_accion) NO pregunta desde un hilo que no es el
        principal — con tty y sin carril de fondo deniega — y con el deadline
        TODA tool corre en un hilo: en el despacho inline (COGNIA_SIN_FONDO=1,
        /lazo, bucle legacy) todo comando CONFIRM se auto-denegaba y el dueno
        jamas veia la pregunta.
    pausa_deadline()  (context manager)
        Mientras dura, el reloj del deadline de ESTE worker (y de los que lo
        esperan, si hay anidamiento) NO corre. Lo usa el gate de permisos:
        el tiempo que el dueno tarda en contestar '[permiso] ...' no es tiempo
        de la tool. Sin esto, en el carril de fondo el deadline (120 s) vencia
        antes que la espera del permiso (600 s): el modelo recibia
        TOOL_TIMEOUT y, al contestar 's' al minuto 3, el hilo huerfano
        ejecutaba el comando igual (y el modelo lo volvia a pedir).
    hilo_agotado() -> bool
        True si el hilo actual es el worker de una tool cuyo deadline YA
        vencio (huerfano). tools._marcar_exit lo consulta para NO escribir
        ctx['_exit'] tarde: el exit del huerfano lo heredaba la SIGUIENTE
        tool (el bug 'evento sellado con el reloj rancio', otra vez).
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time

DEFECTO_S = 120
GRACIA_DEFECTO_S = 5
MARGEN_INTERNO_S = 5
CODIGO = "TOOL_TIMEOUT"
ENV_TIMEOUT = "COGNIA_TOOL_TIMEOUT"
ENV_GRACIA = "COGNIA_TOOL_TIMEOUT_GRACIA"

# Tools que hablan con el modelo o con otro agente: su duracion la fija el
# backend y un deadline de 120 s las mataria a mitad de un razonamiento sano.
SIN_DEADLINE = frozenset({
    "delegar_subtarea", "rlm_llamar", "generar_codigo", "resumir",
    "preguntar_repo", "consultar_oraculo", "crear_herramienta", "crear_flujo",
    "ejecutar_flujo", "workflow", "plan", "buscar_herramientas",
})

_ULTIMO: dict = {}
_ULTIMO_ERROR: dict = {}
_TOTAL = [0]
_AVISADOR = None

# Registro de los workers vivos: ident del hilo de la tool -> su estado
# (cola de pedidos al llamador, pausas del reloj, agotado, ident del padre).
# Lo escribe correr_con_deadline y lo consultan pedir_al_llamador,
# pausa_deadline e hilo_agotado desde el propio worker.
_WORKERS: dict = {}
_LOCK = threading.Lock()
_FIN = object()          # centinela en la cola: el worker termino
# Paso maximo de espera del llamador entre comprobaciones del reloj: una
# pausa puede alargar el deadline y hay que recalcular; el fin del worker y
# los pedidos despiertan al instante por la cola.
_PASO_S = 0.5


class ConfigInvalida(ValueError):
    """Un timeout que no se puede interpretar. Se lanza al CARGAR."""


def registrar_avisador(fn) -> None:
    global _AVISADOR
    _AVISADOR = fn


def _avisar(motivo: str) -> None:
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update({"motivo": motivo,
                          "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    if _AVISADOR is not None:
        try:
            _AVISADOR("timeout_tool", motivo)
            return
        except Exception:
            pass
    import logging
    logging.getLogger(__name__).warning("timeout_tool: %s", motivo)


# ── Config ───────────────────────────────────────────────────────────────────

def _segundos_env(nombre: str, defecto: int) -> int:
    crudo = os.environ.get(nombre, "").strip()
    if not crudo:
        return defecto
    try:
        valor = int(float(crudo))
    except ValueError:
        raise ConfigInvalida(f"{nombre}={crudo!r}: esperaba segundos enteros")
    if valor < 0:
        raise ConfigInvalida(f"{nombre}={crudo!r}: no puede ser negativo "
                             f"(0 = sin limite)")
    return valor


def timeout_global() -> int:
    """Segundos del deadline por defecto; 0 = sin limite. ConfigInvalida con
    basura."""
    return _segundos_env(ENV_TIMEOUT, DEFECTO_S)


def gracia_s() -> int:
    return _segundos_env(ENV_GRACIA, GRACIA_DEFECTO_S)


def validar_config() -> dict:
    return {"timeout_s": timeout_global(), "gracia_s": gracia_s()}


def timeout_efectivo(name: str, spec: dict, args: str) -> float:
    """La regla de precedencia de arriba, en un numero. 0 = sin deadline.
    Lanza ConfigInvalida si el global es basura (el llamador decide)."""
    spec = spec or {}
    declarado = spec.get("timeout_s")
    if declarado is not None:
        try:
            externo = float(declarado)
        except (TypeError, ValueError):
            raise ConfigInvalida(f"timeout_s de '{name}' no numerico: "
                                 f"{declarado!r}")
    elif name in SIN_DEADLINE:
        externo = 0.0
    else:
        externo = float(timeout_global())
    if externo <= 0:
        return 0.0
    interno = spec.get("timeout_interno")
    if callable(interno):
        try:
            seg = interno(args)
        except Exception:
            seg = None
        if isinstance(seg, (int, float)) and seg > 0:
            externo = max(externo, float(seg) + MARGEN_INTERNO_S)
    return externo


# ── Sonda y matanza de hijos ─────────────────────────────────────────────────

def pid_vivo(pid: int) -> bool:
    """True si el PID sigue existiendo. psutil si esta; si no, tasklist en
    Windows y kill(0) en POSIX. Ante la duda, True (mejor avisar de mas)."""
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        pass
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}",
                                "/NH"], capture_output=True, timeout=5)
            return str(pid).encode() in (r.stdout or b"")
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _matar_arbol(proc) -> None:
    """Mata el proceso Y sus descendientes: en Windows `taskkill /T` (matar
    solo el cmd.exe deja vivo al python de abajo: la leccion del repo); en
    POSIX el grupo si lo hay, si no kill()."""
    pid = getattr(proc, "pid", None)
    if pid is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            # Solo el grupo del hijo si ES suyo (start_new_session): sin eso
            # getpgid(pid) es NUESTRO grupo y killpg mataria a Cognia entera.
            try:
                pg = os.getpgid(pid)
                if pg != os.getpgid(0):
                    os.killpg(pg, 9)
                else:
                    proc.kill()
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def matar_hijos(ctx, gracia: float) -> dict:
    """Mata los Popen registrados en ctx['_procesos_tool'] y espera hasta
    `gracia` s a que mueran DE VERDAD (poll + sonda de PID). Devuelve
    {'matados': n, 'vivos': [pids que no murieron]}."""
    procesos = ctx.get("_procesos_tool") if isinstance(ctx, dict) else None
    if not procesos:
        return {"matados": 0, "vivos": []}
    matados, vivos = 0, []
    for p in list(procesos):
        try:
            if p.poll() is not None:
                continue
        except Exception:
            continue
        _matar_arbol(p)
        matados += 1
    limite = time.time() + max(0.0, gracia)
    for p in list(procesos):
        while True:
            try:
                muerto = p.poll() is not None and not pid_vivo(p.pid)
            except Exception:
                muerto = True
            if muerto or time.time() >= limite:
                break
            time.sleep(0.05)
        try:
            if p.poll() is None or pid_vivo(p.pid):
                vivos.append(p.pid)
        except Exception:
            pass
    return {"matados": matados, "vivos": vivos}


# ── Texto tipado ─────────────────────────────────────────────────────────────

def texto_timeout(name: str, limite: float, info: dict) -> str:
    seg = int(limite) if float(limite).is_integer() else round(limite, 1)
    cola = ""
    if info.get("hilo_vivo") or info.get("vivos"):
        cola = (" El proceso de la tool NO termino en la gracia de "
                f"{info.get('gracia_s', 0)}s (hilo vivo: "
                f"{bool(info.get('hilo_vivo'))}; pids vivos: "
                f"{info.get('vivos') or []}): no la relances hasta que "
                f"muera.")
    return (f"RESULTADO {name} ERROR: tool agotada tras {seg}s ({CODIGO})."
            f" No devolvio resultado. Acota la llamada (menos datos, un "
            f"target mas especifico) o usa otra herramienta.{cola}")


# ── El ejecutor con deadline ─────────────────────────────────────────────────

def _transcurrido(reg: dict, inicio: float, ahora: float) -> float:
    """Segundos del deadline consumidos: el reloj menos las pausas."""
    pausa = reg["pausa_acum"]
    if reg["pausado_desde"] is not None:
        pausa += ahora - reg["pausado_desde"]
    return ahora - inicio - pausa


def _atender_pedido(p: dict) -> None:
    """Corre el fn de un pedido EN ESTE hilo y despierta al worker."""
    try:
        p["res"] = p["fn"]()
    except BaseException as exc:          # viaja al worker, que lo re-lanza
        p["exc"] = exc
    finally:
        p["listo"].set()


def pedir_al_llamador(fn):
    """Ver el CONTRATO del modulo. NUNCA lanza por su cuenta: una excepcion
    de `fn` se re-lanza aqui, en el worker."""
    reg = _WORKERS.get(threading.get_ident())
    if reg is None:
        return False, None
    p = {"fn": fn, "listo": threading.Event(), "res": None, "exc": None}
    with _LOCK:
        if reg["agotado"]:
            return False, None            # el llamador ya se fue: nadie atiende
        reg["cola"].put(p)
    p["listo"].wait()
    if p["exc"] is not None:
        raise p["exc"]
    return True, p["res"]


class pausa_deadline:
    """`with pausa_deadline():` — el reloj del deadline del worker actual (y
    de sus padres, si la tool corre anidada) se detiene. Fuera de un worker
    es un no-op. Reentrante."""

    def __enter__(self):
        self._regs = []
        ident = threading.get_ident()
        ahora = time.time()
        with _LOCK:
            while ident is not None:
                reg = _WORKERS.get(ident)
                if reg is None:
                    break
                if reg["pausas"] == 0:
                    reg["pausado_desde"] = ahora
                reg["pausas"] += 1
                self._regs.append(reg)
                ident = reg["padre"]
        return self

    def __exit__(self, *exc):
        ahora = time.time()
        with _LOCK:
            for reg in self._regs:
                reg["pausas"] -= 1
                if reg["pausas"] == 0 and reg["pausado_desde"] is not None:
                    reg["pausa_acum"] += ahora - reg["pausado_desde"]
                    reg["pausado_desde"] = None
        return False


def hilo_agotado() -> bool:
    """True si este hilo es el worker de una tool cuyo deadline ya vencio."""
    reg = _WORKERS.get(threading.get_ident())
    return bool(reg and reg["agotado"])


def correr_con_deadline(fn, name: str, args: str, ctx, limite: float):
    """Ver el CONTRATO del modulo. `limite` <= 0 = correr en linea."""
    if not limite or limite <= 0:
        return fn(args, ctx), False, {}
    caja: dict = {}
    cancelar = threading.Event()
    if isinstance(ctx, dict):
        ctx["_cancelar_tool"] = cancelar
        ctx["_deadline"] = time.time() + limite
        ctx.setdefault("_procesos_tool", [])
    reg = {"cola": queue.Queue(), "pausas": 0, "pausado_desde": None,
           "pausa_acum": 0.0, "agotado": False,
           "padre": threading.get_ident()}

    def _w():
        ident = threading.get_ident()
        _WORKERS[ident] = reg
        try:
            caja["out"] = fn(args, ctx)
        except BaseException as exc:      # se re-lanza en el llamador
            caja["exc"] = exc
        finally:
            _WORKERS.pop(ident, None)
            reg["cola"].put(_FIN)

    hilo = threading.Thread(target=_w, name=f"tool-{name}", daemon=True)
    inicio = time.time()
    hilo.start()
    # El llamador ESPERA ATENDIENDO: los pedidos del worker (permisos que
    # solo el dueno de la consola puede contestar) se corren aqui; el fin del
    # worker llega por la misma cola; y el reloj descuenta las pausas.
    vencio = False
    while True:
        ahora = time.time()
        restante = limite - _transcurrido(reg, inicio, ahora)
        if restante <= 0:
            vencio = hilo.is_alive()
            break
        if isinstance(ctx, dict):
            ctx["_deadline"] = ahora + restante
        try:
            p = reg["cola"].get(timeout=min(restante, _PASO_S))
        except queue.Empty:
            continue
        if p is _FIN:
            break
        _atender_pedido(p)
    if not vencio:
        hilo.join(5)
        _limpiar(ctx)
        if "exc" in caja:
            raise caja["exc"]
        return caja.get("out"), False, {}
    # VENCIO: cancelacion cooperativa, hijos por arbol, y espera acotada.
    # Se marca agotado BAJO EL LOCK y se drenan los pedidos pendientes: un
    # pedido que llegue despues ya no encuentra a nadie y lo sabe.
    cancelar.set()
    with _LOCK:
        reg["agotado"] = True
        while True:
            try:
                p = reg["cola"].get_nowait()
            except queue.Empty:
                break
            if p is not _FIN:
                p["exc"] = RuntimeError(
                    f"la tool '{name}' agoto su deadline: nadie atiende")
                p["listo"].set()
    try:
        gracia = float(gracia_s())
    except ConfigInvalida as exc:
        _avisar(f"gracia invalida, uso {GRACIA_DEFECTO_S}s: {exc}")
        gracia = float(GRACIA_DEFECTO_S)
    hijos = matar_hijos(ctx, gracia)
    hilo.join(gracia)
    info = {"hilo_vivo": hilo.is_alive(), "matados": hijos["matados"],
            "vivos": hijos["vivos"], "gracia_s": gracia}
    _limpiar(ctx)
    if isinstance(ctx, dict):
        ctx.pop("_exit", None)            # no hubo exit real: None, no 0
    _TOTAL[0] += 1
    _ULTIMO.clear()
    _ULTIMO.update({"tool": name, "limite_s": limite, "args": str(args)[:120],
                    "quiescente": not info["hilo_vivo"] and not info["vivos"],
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    if info["hilo_vivo"] or info["vivos"]:
        _avisar(f"'{name}' agoto {limite:g}s y NO quiescio en {gracia:g}s "
                f"(hilo vivo={info['hilo_vivo']}, pids vivos={info['vivos']})")
    return texto_timeout(name, limite, info), True, info


def _limpiar(ctx) -> None:
    if isinstance(ctx, dict):
        ctx.pop("_cancelar_tool", None)
        ctx.pop("_deadline", None)
        ctx.pop("_procesos_tool", None)


def estado() -> dict:
    try:
        glob = timeout_global()
        err = ""
    except ConfigInvalida as exc:
        glob, err = DEFECTO_S, str(exc)
    try:
        gr = gracia_s()
    except ConfigInvalida as exc:
        gr, err = GRACIA_DEFECTO_S, err or str(exc)
    return {"timeout_s": glob, "gracia_s": gr, "config_error": err,
            "sin_deadline": sorted(SIN_DEADLINE), "total": _TOTAL[0],
            "ultimo": dict(_ULTIMO), "ultimo_error": dict(_ULTIMO_ERROR),
            "plataforma": sys.platform}
