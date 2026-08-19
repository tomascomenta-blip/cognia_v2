# -*- coding: utf-8 -*-
"""Presupuesto de vueltas POR TURNO + razon de salida sellada (destilado de Hermes Agent).

QUE RESUELVE
------------
Dos agujeros distintos del bucle del agente, que en este repo ya se pagaron caros:

 1. **La infraestructura se come el presupuesto de la tarea.** El bucle cuenta
    "vueltas" y corta al llegar al techo, pero no todas las vueltas son trabajo
    del modelo: una compactacion de contexto, un reintento por error de red o por
    JSON invalido, o una llamada barata de RPC consumen exactamente lo mismo que
    un paso de razonamiento. La tarea se queda sin pasos por culpa del arnes y
    nadie puede saberlo despues.
 2. **La salida silenciosa.** Un bucle con doce `break` y tres `return` termina
    sin decir POR QUE. Memoria del repo: "Cognia degrada en silencio" (el fallo
    tipico es el vacio silencioso, no la excepcion) y "un fallo que devuelve None
    es invisible" ('fallo' y 'no habia nada' piden decisiones opuestas).

DE DONDE SALE (fichero:linea de Hermes Agent, leidos de verdad)
--------------------------------------------------------------
`agent/iteration_budget.py` — `IterationBudget`: contador thread-safe por agente
con `consume()/refund()/used/remaining`, un `threading.Lock` y un tope `max_total`.
Su docstring dice literalmente que las vueltas de `execute_code` se devuelven "so
they don't eat into the budget".

`agent/turn_context.py:487` — `agent.iteration_budget = IterationBudget(agent.max_iterations)`:
el presupuesto se REINSTANCIA al arrancar cada turno de conversacion. No es un
contador de proceso; muere con el turno. (Cognia ya se quemo con lo contrario:
el tope de acciones de pantalla era de proceso y una corrida gastaba el
presupuesto de la siguiente — ver cli.py:_run_agent_task.)

`agent/conversation_loop.py:1316` — la guarda del bucle:
`while (api_call_count < agent.max_iterations and agent.iteration_budget.remaining > 0) or agent._budget_grace_call`.

`agent/conversation_loop.py:1342-1350` — el gasto: `elif not agent.iteration_budget.consume(): _turn_exit_reason = "budget_exhausted"; break`.

Los refunds REALES de Hermes (los motivos de este modulo salen de ahi, uno a uno):
  - `:1841`  contexto de runtime demasiado pequeno (fallo del backend, no del modelo)
  - `:1996`  compactacion de contexto -> `api_call_count -= 1; refund()`
  - `:5483`  reinicio con mensajes redirigidos (correccion del usuario en vuelo)
  - `:5494`  reinicio tras compresion en el bucle
  - `:5519`  reinicio tras stall del filtro de contenido (cambio de proveedor)
  - `:6257`  la vuelta cuyo UNICO tool call fue `execute_code` (RPC barato)

`agent/conversation_loop.py:1271` — `_turn_exit_reason = "unknown"  # Diagnostic: why the loop ended`,
sellado en CADA salida (`interrupted_by_user`, `budget_exhausted`,
`all_retries_exhausted_no_response`, `guardrail_halt`, `empty_response_exhausted`,
`text_response(...)`, ...) y arrastrado hasta `agent/turn_finalizer.py:443`.

`agent/turn_finalizer.py:449-457` — LA ALARMA que copiamos entera:

    if _last_msg_role == "tool" and not interrupted:
        # Agent was mid-work — this is the "just stops" case.
        logger.warning("Turn ended with pending tool result (agent may appear stuck). " ...)

Si el turno acaba y el ULTIMO mensaje del historial es un resultado de tool, el
modelo se fue sin cerrar: hubo trabajo a medias que nadie observo. Es la firma
exacta de "el agente parece colgado" y en Cognia es un WARNING, no un adorno.

DECISIONES
----------
 * **Nada rompe el turno.** `consume()` devuelve bool, `refund()` devuelve bool,
   `cerrar()` devuelve dict. La instrumentacion jamas lanza (regla del repo).
 * **El motivo del refund es OBLIGATORIO y se guarda.** Devolver una vuelta sin
   decir por que reproduce el problema que el refund venia a resolver: al auditar
   no se distingue "la tarea uso 12 vueltas" de "la tarea uso 8 y el arnes 4".
   Un motivo vacio se registra como ``sin_motivo`` y se avisa por log.
 * **Un refund que no aplica NO se registra** (igual que Hermes, que solo baja el
   contador `if self._used > 0`), pero se cuenta aparte en `refunds_ignorados`
   para que el registro no mienta por omision.
 * **La razon de salida no puede faltar.** `cerrar()` sin sellar deja
   ``desconocida`` y loguea WARNING: preferimos un turno ruidoso a uno mudo.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Motivos de refund. Los administrativos son los que NO gastaron razonamiento
# del modelo: portados uno a uno de los refunds reales de conversation_loop.py
# (ver la cabecera). La lista es orientativa, no un enum cerrado: `refund()`
# acepta cualquier motivo no vacio para que el integrador pueda anadir los
# suyos sin tocar este modulo.
# --------------------------------------------------------------------------
MOTIVO_COMPACTACION = "compactacion"        # conversation_loop.py:1996
MOTIVO_REINTENTO_RED = "reintento_red"      # conversation_loop.py:5519
MOTIVO_REINTENTO_FORMATO = "reintento_formato"   # JSON/ACCION invalida
MOTIVO_LLAMADA_BARATA = "llamada_barata"    # conversation_loop.py:6257 (execute_code)
MOTIVO_REDIRECCION = "redireccion_usuario"  # conversation_loop.py:5483
MOTIVO_BACKEND = "error_backend"            # conversation_loop.py:1841
MOTIVO_SIN_MOTIVO = "sin_motivo"

MOTIVOS_ADMIN = (
    MOTIVO_COMPACTACION,
    MOTIVO_REINTENTO_RED,
    MOTIVO_REINTENTO_FORMATO,
    MOTIVO_LLAMADA_BARATA,
    MOTIVO_REDIRECCION,
    MOTIVO_BACKEND,
)


class PresupuestoTurno:
    """Contador de vueltas thread-safe, de UN turno (destilado de IterationBudget).

    Se instancia al arrancar el turno y se tira al acabarlo: nunca es un contador
    de proceso (turn_context.py:487). `consume()` cobra una vuelta y devuelve
    False cuando ya no queda; `refund(motivo)` devuelve una vuelta y APUNTA por
    que, para poder auditar despues cuanto presupuesto se comio el arnes.
    """

    def __init__(self, max_total: int):
        # Un tope no positivo significa "no arranca": consume() devuelve False
        # desde la primera vuelta en vez de dejar el bucle correr sin freno.
        try:
            self.max_total = max(0, int(max_total))
        except (TypeError, ValueError):
            logger.warning("PresupuestoTurno: max_total invalido (%r), uso 0", max_total)
            self.max_total = 0
        self._lock = threading.Lock()
        self._gastado = 0            # neto (consumos - refunds aplicados)
        self._consumos = 0           # bruto: vueltas realmente arrancadas
        self._refunds: List[Dict[str, Any]] = []
        self._refunds_ignorados = 0

    # -- gasto -------------------------------------------------------------
    def consume(self) -> bool:
        """Cobra una vuelta. True si habia presupuesto; False si se agoto."""
        with self._lock:
            if self._gastado >= self.max_total:
                return False
            self._gastado += 1
            self._consumos += 1
            return True

    def refund(self, motivo: str) -> bool:
        """Devuelve una vuelta APUNTANDO el motivo. True si se aplico de verdad.

        Un motivo vacio no se rechaza (la instrumentacion no rompe el turno) pero
        queda como ``sin_motivo`` y avisa: un refund anonimo es justo el agujero
        de auditoria que este contador viene a tapar.
        """
        motivo_limpio = str(motivo).strip() if motivo is not None else ""
        if not motivo_limpio:
            motivo_limpio = MOTIVO_SIN_MOTIVO
            logger.warning(
                "PresupuestoTurno.refund() sin motivo: se apunta como '%s'",
                MOTIVO_SIN_MOTIVO,
            )
        with self._lock:
            if self._gastado <= 0:
                # Igual que Hermes (`if self._used > 0`): no se baja de cero. Y
                # NO se registra, para que el registro de refunds no invente
                # vueltas devueltas que nunca existieron.
                self._refunds_ignorados += 1
                return False
            self._gastado -= 1
            self._refunds.append({
                "motivo": motivo_limpio,
                "administrativo": motivo_limpio in MOTIVOS_ADMIN,
                "gastado_tras": self._gastado,
                "consumo_n": self._consumos,
            })
            return True

    # -- lectura -----------------------------------------------------------
    @property
    def gastado(self) -> int:
        """Vueltas cobradas NETAS (lo que ve la guarda del bucle)."""
        with self._lock:
            return self._gastado

    @property
    def restante(self) -> int:
        with self._lock:
            return max(0, self.max_total - self._gastado)

    @property
    def agotado(self) -> bool:
        with self._lock:
            return self._gastado >= self.max_total

    @property
    def vueltas(self) -> int:
        """Vueltas BRUTAS arrancadas (consumos aceptados, refunds incluidos).

        La diferencia con `gastado` es exactamente lo que el arnes se comio y
        devolvio: sin este numero, "la tarea uso 8 pasos" oculta las 4 vueltas
        de compactacion que si costaron tiempo y tokens de verdad.
        """
        with self._lock:
            return self._consumos

    @property
    def refunds_ignorados(self) -> int:
        with self._lock:
            return self._refunds_ignorados

    def refunds(self) -> List[Dict[str, Any]]:
        """Copia del registro de refunds (serializable, en orden de ocurrencia)."""
        with self._lock:
            return [dict(r) for r in self._refunds]

    def refunds_por_motivo(self) -> Dict[str, int]:
        with self._lock:
            conteo: Dict[str, int] = {}
            for r in self._refunds:
                conteo[r["motivo"]] = conteo.get(r["motivo"], 0) + 1
            return conteo

    def resumen(self) -> Dict[str, Any]:
        """Dict serializable con la contabilidad del turno."""
        with self._lock:
            conteo: Dict[str, int] = {}
            admin = 0
            for r in self._refunds:
                conteo[r["motivo"]] = conteo.get(r["motivo"], 0) + 1
                if r["administrativo"]:
                    admin += 1
            return {
                "max_total": self.max_total,
                "gastado": self._gastado,
                "restante": max(0, self.max_total - self._gastado),
                "vueltas": self._consumos,
                "refunds": len(self._refunds),
                "refunds_administrativos": admin,
                "refunds_ignorados": self._refunds_ignorados,
                "refunds_por_motivo": conteo,
            }


# --------------------------------------------------------------------------
# Razones de salida. Igual que en Hermes, la lista es abierta (alli conviven
# 'budget_exhausted' con f"text_response(finish_reason={...})"): lo obligatorio
# es que HAYA una, no que este en el catalogo.
# --------------------------------------------------------------------------
RAZON_RESPUESTA_TEXTO = "respuesta_texto"
RAZON_PRESUPUESTO_AGOTADO = "presupuesto_agotado"
RAZON_ERROR_BACKEND = "error_backend"
RAZON_BUCLE_DETECTADO = "bucle_detectado"
RAZON_PARADA_VERIFICADA = "parada_verificada"
RAZON_INTERRUMPIDO = "interrumpido"
RAZON_EXCEPCION = "excepcion"
RAZON_DESCONOCIDA = "desconocida"

RAZONES = (
    RAZON_RESPUESTA_TEXTO,
    RAZON_PRESUPUESTO_AGOTADO,
    RAZON_ERROR_BACKEND,
    RAZON_BUCLE_DETECTADO,
    RAZON_PARADA_VERIFICADA,
    RAZON_INTERRUMPIDO,
    RAZON_EXCEPCION,
)

# Roles/prefijos que identifican "el ultimo mensaje es un resultado de tool".
# Hermes mira `msg["role"] == "tool"`; el bucle de Cognia guarda strings
# ("RESULTADO: ...", cli.py:_run_agent_task -> history.append(result)), asi que
# el detector entiende los dos formatos y no obliga a cambiar el historial.
_ROLES_TOOL = ("tool", "tool_result", "herramienta", "resultado")
_PREFIJOS_TOOL = ("RESULTADO", "OBSERVACI", "TOOL:", "ACCION:")

AVISO_TOOL_PENDIENTE = (
    "el turno acabo con un RESULTADO de tool sin cerrar: el modelo se fue a "
    "medio trabajo (el agente parece colgado)"
)


def rol_de_mensaje(mensaje: Any) -> str:
    """Rol normalizado de un mensaje del historial ('' si no se puede saber).

    Acepta los tres formatos que circulan por el repo: dict estilo OpenAI, objeto
    con atributo ``role`` y string suelto del bucle ReAct.
    """
    if mensaje is None:
        return ""
    if isinstance(mensaje, dict):
        rol = mensaje.get("role") or mensaje.get("rol") or ""
        return str(rol).strip().lower()
    rol = getattr(mensaje, "role", None) or getattr(mensaje, "rol", None)
    if rol:
        return str(rol).strip().lower()
    if isinstance(mensaje, str):
        cabeza = mensaje.lstrip()
        for pref in _PREFIJOS_TOOL:
            if cabeza.upper().startswith(pref):
                return "tool"
        return ""
    return ""


def ultimo_es_resultado_de_tool(historial: Any) -> bool:
    """True si el ULTIMO mensaje del historial es un resultado de herramienta.

    Portado de turn_finalizer.py:449 (`_last_msg_role == "tool"`). Best-effort:
    ante cualquier forma rara devuelve False, nunca lanza.
    """
    try:
        if not historial:
            return False
        ultimo = historial[-1]
    except Exception:
        return False
    return rol_de_mensaje(ultimo) in _ROLES_TOOL


class RazonSalida:
    """Sello de POR QUE termino el turno, con log garantizado y alarma de tool.

    Uso: una instancia por turno; cada `break`/`return` del bucle llama a
    `sellar(...)` y el epilogo llama a `cerrar(historial)` UNA vez. Si nadie
    sello, `cerrar()` deja ``desconocida`` y avisa: en Hermes ese hueco se llama
    "unknown" y existe justo para que un turno mudo se vea en el log.
    """

    def __init__(self, presupuesto: Optional[PresupuestoTurno] = None,
                 etiqueta: str = ""):
        self.presupuesto = presupuesto
        self.etiqueta = str(etiqueta or "")
        self.razon: str = ""
        self.detalle: str = ""
        self.aviso: str = ""
        self.cerrada: bool = False
        # Historial de sellos: el ultimo manda (igual que `_turn_exit_reason`,
        # que se reasigna en cada salida), pero conservamos los previos porque
        # un turno que sella dos veces suele estar tapando el primer fallo.
        self.sellos: List[Dict[str, str]] = []

    def sellar(self, razon: str, detalle: str = "") -> str:
        """Estampa la razon de salida. Devuelve la razon efectiva. Nunca lanza."""
        limpia = str(razon).strip() if razon is not None else ""
        if not limpia:
            limpia = RAZON_DESCONOCIDA
            logger.warning("RazonSalida.sellar() sin razon%s: queda '%s'",
                           self._suf(), RAZON_DESCONOCIDA)
        self.razon = limpia
        self.detalle = str(detalle or "")
        self.sellos.append({"razon": limpia, "detalle": self.detalle})
        return limpia

    def cerrar(self, historial: Any = None) -> Dict[str, Any]:
        """Cierra el turno: loguea SIEMPRE y devuelve el envelope serializable.

        Es idempotente en el sentido util: se puede llamar dos veces y no rompe,
        pero solo la primera loguea (el epilogo del bucle no deberia duplicar).
        """
        try:
            if not self.razon:
                self.razon = RAZON_DESCONOCIDA
                logger.warning(
                    "Turno cerrado SIN razon de salida%s: ningun punto del bucle "
                    "sello. Queda '%s'.", self._suf(), RAZON_DESCONOCIDA)
            # La alarma de Hermes: turno acabado con un resultado de tool colgando.
            # Se salta cuando el turno fue INTERRUMPIDO (turn_finalizer.py:449
            # exige `and not interrupted`): ahi cortar a medias es lo esperado.
            if (self.razon != RAZON_INTERRUMPIDO
                    and ultimo_es_resultado_de_tool(historial)):
                self.aviso = AVISO_TOOL_PENDIENTE
            envelope = resumen_envelope(self, self.presupuesto)
            if not self.cerrada:
                if self.aviso:
                    logger.warning(
                        "Turno terminado con tool pendiente%s: razon=%s pasos=%s "
                        "vueltas=%s refunds=%s aviso=%s",
                        self._suf(), envelope["razon"], envelope["pasos"],
                        envelope["vueltas"], len(envelope["refunds"]), self.aviso)
                elif self.razon in (RAZON_DESCONOCIDA, RAZON_EXCEPCION,
                                    RAZON_ERROR_BACKEND, RAZON_BUCLE_DETECTADO):
                    logger.warning(
                        "Turno terminado%s: razon=%s detalle=%s pasos=%s "
                        "vueltas=%s refunds=%s",
                        self._suf(), envelope["razon"], envelope["detalle"],
                        envelope["pasos"], envelope["vueltas"],
                        len(envelope["refunds"]))
                else:
                    logger.info(
                        "Turno terminado%s: razon=%s pasos=%s vueltas=%s refunds=%s",
                        self._suf(), envelope["razon"], envelope["pasos"],
                        envelope["vueltas"], len(envelope["refunds"]))
            self.cerrada = True
            return envelope
        except Exception as e:  # pragma: no cover - la instrumentacion no rompe
            logger.warning("RazonSalida.cerrar() fallo: %s: %s", type(e).__name__, e)
            self.cerrada = True
            return {"razon": self.razon or RAZON_DESCONOCIDA, "pasos": 0,
                    "refunds": [], "aviso": self.aviso}

    def resumen_envelope(self) -> Dict[str, Any]:
        """Atajo: el mismo envelope sin cerrar ni loguear (para inspeccion viva)."""
        return resumen_envelope(self, self.presupuesto)

    def _suf(self) -> str:
        return f" [{self.etiqueta}]" if self.etiqueta else ""


def resumen_envelope(salida: Optional[RazonSalida] = None,
                     presupuesto: Optional[PresupuestoTurno] = None
                     ) -> Dict[str, Any]:
    """Envelope serializable del turno: {razon, pasos, refunds, aviso, ...}.

    Se puede llamar con solo el presupuesto (razon 'desconocida') o solo con la
    salida. Todo lo que devuelve es json-able: dicts, listas, ints y strings.
    """
    pres = presupuesto
    if pres is None and salida is not None:
        pres = salida.presupuesto
    cuenta = pres.resumen() if isinstance(pres, PresupuestoTurno) else {}
    refunds = pres.refunds() if isinstance(pres, PresupuestoTurno) else []
    return {
        "razon": (salida.razon if salida is not None and salida.razon
                  else RAZON_DESCONOCIDA),
        "detalle": salida.detalle if salida is not None else "",
        "pasos": cuenta.get("gastado", 0),
        "vueltas": cuenta.get("vueltas", 0),
        "restante": cuenta.get("restante", 0),
        "max_total": cuenta.get("max_total", 0),
        "refunds": refunds,
        "refunds_por_motivo": cuenta.get("refunds_por_motivo", {}),
        "refunds_administrativos": cuenta.get("refunds_administrativos", 0),
        "aviso": salida.aviso if salida is not None else "",
        "sellos": [dict(s) for s in salida.sellos] if salida is not None else [],
    }


__all__ = [
    "PresupuestoTurno",
    "RazonSalida",
    "resumen_envelope",
    "ultimo_es_resultado_de_tool",
    "rol_de_mensaje",
    "AVISO_TOOL_PENDIENTE",
    "MOTIVOS_ADMIN",
    "MOTIVO_COMPACTACION",
    "MOTIVO_REINTENTO_RED",
    "MOTIVO_REINTENTO_FORMATO",
    "MOTIVO_LLAMADA_BARATA",
    "MOTIVO_REDIRECCION",
    "MOTIVO_BACKEND",
    "MOTIVO_SIN_MOTIVO",
    "RAZONES",
    "RAZON_RESPUESTA_TEXTO",
    "RAZON_PRESUPUESTO_AGOTADO",
    "RAZON_ERROR_BACKEND",
    "RAZON_BUCLE_DETECTADO",
    "RAZON_PARADA_VERIFICADA",
    "RAZON_INTERRUMPIDO",
    "RAZON_EXCEPCION",
    "RAZON_DESCONOCIDA",
]
