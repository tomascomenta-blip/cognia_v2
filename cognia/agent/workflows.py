# -*- coding: utf-8 -*-
"""
cognia/agent/workflows.py
=========================
Motor MINIMO de workflows: agentes con salida estructurada validada,
presupuesto de tokens transversal, resume por journal con cache por hash y
paralelismo realista (cap 2-3: la fisica medida dice que un slot serializa y
mas hilos solo solapan I/O o cerebro+worker).

POR QUE existe (contrato congelado 2026-08-11): el veredicto medido dijo que
lo barato que falta es (1) salida estructurada con retry sobre el error REAL,
(2) techo de tokens compartido entre llamadas, (3) poder retomar una corrida
cara sin re-pagar lo ya hecho. Cero frameworks: funciones planas + dataclases,
el estilo de la casa.

Diseno anti-degradacion-silenciosa:
- El journal es append-only con flush por linea (patron bitacora.py): un
  crash deja legible todo hasta la ultima linea entera, y el resume tolera
  una linea final truncada.
- completar() nunca lanza; aca se mira .error y .finish_reason SIEMPRE.
- finish_reason == 'length' NO se reintenta igual-igual: es presupuesto, no
  formato (la leccion de los 10 bugs identicos de max_tokens).
"""
from __future__ import annotations

import collections
import hashlib
import inspect
import json
import os
import re
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Import de nivel de modulo y no perezoso: cognia/ux/events.py es solo-stdlib y
# no importa NADA de cognia, asi que no hay ciclo posible. El motor emite al bus
# para que la UI pueda pintar el workflow por agente.
from cognia.ux import events as ux

# Sampling por rol (contrato): el worker es Qwen3-4B-Thinking (0.6/0.95,
# la receta del model card); el cerebro es qwythos (0.7/0.8). Una temperatura
# explicita del caller pisa ambos; el top_p queda del rol.
_SAMPLING_WORKER = {"temperature": 0.6, "top_p": 0.95}
_SAMPLING_CEREBRO = {"temperature": 0.7, "top_p": 0.8}

# ── Control por agente (2026-08-17) ─────────────────────────────────────────
# "CORTAR Y VOLVER A PREGUNTAR" (decision del dueno, es una restriccion y no
# una opcion): hablarle a un agente en curso CORTA la generacion, apendea el
# mensaje como turno del usuario y vuelve a llamar al modelo con el contexto
# nuevo. Se tira lo generado y cuesta una llamada mas del presupuesto. En la
# UI el boton se llama "interrumpir y decir".
#
# LO QUE CUESTA UN CORTE, DECLARADO CON SU NUMERO (defecto #5, cerrado el
# 2026-08-17). Al cortar, el cliente deja de leer y el frame final —el que
# lleva el chunk de usage y las timings— no llega nunca:
#   - los tokens GENERADOS se cobran igual, contando los frames de contenido
#     recibidos (en SSE, un frame = un token). Medido contra :8080 con
#     /tokenize sobre el texto descartado entero: estimacion 134 / real 134 en
#     un corte, 124 / 123 en otro. Van marcados como estimados en el journal
#     (usage_estimado, usage_via), en el presupuesto (estimados()) y en el
#     cierre (WorkflowFin.tokens_estimados);
#   - el PROMPT de ese turno NO se cuenta: no lo manda nadie y estimarlo desde
#     el cliente seria un numero silenciosamente mal. Es el agujero que queda,
#     acotado por max_repreguntas (8) x prompt_tokens por agente y CONTADO en
#     presupuesto.sin_prompt(), que es lo que impide que crezca sin verse.
#     Ese contador tica por TODA llamada sin prompt contabilizado, incluido el
#     corte que cae en pleno prefill (usage vacio entero, la llamada valdria
#     cero): la primera version solo ticaba si ademas hubo generacion, o sea
#     que el peor caso era el unico invisible.
#     Medido en la corrida de verificacion: 73 tokens de 391 (19%), contra el
#     82% que se perdia cuando el corte entero valia CERO.
#
# LAS TRES PREGUNTAS DEL CONTROL, que no son la misma (defectos #2 y #3):
#   estado(id)          -> vivo | comprometido | terminado: ¿sigue corriendo?
#   esta_cancelado(id)  -> ¿le ALCANZA un corte? (incluye el flag global)
#   fue_cortado(id)     -> ¿se corto a ESTE? (no ORea el global)
# Confundir la segunda con la tercera hacia que, tras un panico, cancelar un
# agente que ya habia entregado contestara "ya_cancelado".

_MAX_BUZON = 8          # mensajes en cola por agente
_MAX_ESTADOS = 256      # ids recordados por corrida (eviccion FIFO)
_MAX_REPREGUNTAS = 8    # tope del lazo "cortar y volver a preguntar"

# Latido de AgenteProgreso. Se throttlea el PROGRESO, jamas el CONTENIDO: a
# ~70 tok/s ≈ 280 chars/s manda el tiempo -> ~4 eventos/s por agente, contra
# ~560 TokenTexto/s. Factor 70 en el stdout del movil.
_LATIDO_S = 0.25
_LATIDO_CHARS = 400
# Indireccion del reloj SOLO para el throttle: asi un test puede congelarlo
# sin monkeypatchear el modulo time entero (que afectaria a perf_counter y a
# los ts del journal).
_reloj = time.monotonic

# Estados de un agente dentro del control.
EST_VIVO = "vivo"
EST_COMPROMETIDO = "comprometido"
EST_TERMINADO = "terminado"

# El conjunto CERRADO de `estado` del envelope de control (§2.1). Cerrado a
# proposito: oficina/estado.py::solicitar() devuelve False para "no existe",
# "ya termino" y "accion invalida" a la vez, y ese silencio de tres causas es
# exactamente lo que aca no se repite.
ACEPTADO = "aceptado"
YA_CANCELADO = "ya_cancelado"
YA_TERMINO = "ya_termino"
DESCONOCIDO_AGENTE = "desconocido_agente"
CORRIDA_CERRADA = "corrida_cerrada"
DESCONOCIDO_CORRIDA = "desconocido_corrida"
TEXTO_VACIO = "texto_vacio"
BUZON_LLENO = "buzon_lleno"
ESTADOS_CONTROL = (ACEPTADO, YA_CANCELADO, YA_TERMINO, DESCONOCIDO_AGENTE,
                   CORRIDA_CERRADA, DESCONOCIDO_CORRIDA, TEXTO_VACIO,
                   BUZON_LLENO)


class ControlCorrida:
    """Cancelacion cooperativa + buzon, POR AGENTE.

    Mismo patron que oficina/estado.py::solicitar(): quien manda deja una
    SOLICITUD y el motor la honra en su proximo checkpoint. Dos diferencias:
    aca no hay JSON en disco (la corrida vive en memoria y muere con el
    proceso) y el corte llega ADEMAS dentro de la llamada, via el kwarg
    `cancelado` de completar().

    Ningun metodo lanza: `debe_cortar` se le pasa a chat_client como
    `cancelado`, y la politica de alli es que "un cancelado() que lanza no
    cancela" — o sea que una excepcion nuestra volveria la llamada
    INCANCELABLE. Se lee bajo lock y se devuelve bool, siempre.
    """

    def __init__(self):
        # RLock: `agente()` toma este lock en el commit atomico y dentro
        # consulta debe_cortar/comprometer, que vuelven a tomarlo.
        self.lock = threading.RLock()
        self._global = threading.Event()        # cancelar_corrida()
        self._cancelados: set = set()           # agente_id
        self._buzon: dict = {}                  # agente_id -> [mensajes]
        self._estado: "collections.OrderedDict" = collections.OrderedDict()
        self._motivo: dict = {}                 # agente_id -> por que se corto
        self._degradado_avisado = False         # el Degradado sale UNA vez
        # Mensajes que se cayeron con la eviccion del anillo, para que
        # `nace()` no los tire en silencio. Los drena quien pueda anotarlos.
        self._evictados: list = []

    # --- lo que usa agente() ---------------------------------------------
    def nace(self, agente_id: str) -> None:
        with self.lock:
            self._estado[agente_id] = EST_VIVO
            self._estado.move_to_end(agente_id)
            # Anillo de _MAX_ESTADOS: una corrida con cientos de agentes
            # (varios criticar() en lazo) no puede crecer sin techo. El precio
            # esta declarado: los mas viejos pasan a decir desconocido_agente.
            while len(self._estado) > _MAX_ESTADOS:
                viejo, _ = self._estado.popitem(last=False)
                self._cancelados.discard(viejo)
                # Un mensaje que se cae con el anillo se ANOTA. Mismo
                # invariante que el resto de los descartes: un mensaje tirado
                # en silencio es peor que uno rechazado a la vista. Pide mas
                # de _MAX_ESTADOS agentes en UNA corrida, pero el lazo de
                # criticar() los produce.
                for _texto in self._buzon.pop(viejo, []) or []:
                    self._evictados.append((viejo, _texto))
                self._motivo.pop(viejo, None)

    def drenar_evictados(self) -> list:
        """Los mensajes que se cayeron con el anillo, y los vacia. Devuelve
        [(agente_id, texto)]. Quien los drena es agente(), que si tiene el
        journal donde anotarlos."""
        with self.lock:
            fuera, self._evictados = self._evictados, []
        return fuera

    def muere(self, agente_id: str) -> None:
        with self.lock:
            if agente_id in self._estado:
                self._estado[agente_id] = EST_TERMINADO

    def comprometer(self, agente_id: str) -> bool:
        """Marca el resultado como ENTREGADO. Desde aca decirle() -> ya_termino."""
        with self.lock:
            if self._estado.get(agente_id) == EST_VIVO:
                self._estado[agente_id] = EST_COMPROMETIDO
                return True
            return False

    def debe_cortar(self, agente_id: str) -> bool:
        """La union de las TRES causas: cancelacion global, cancelacion de
        este agente, o un mensaje sin entregar."""
        try:
            with self.lock:
                return bool(self._global.is_set()
                            or agente_id in self._cancelados
                            or self._buzon.get(agente_id))
        except Exception:
            return False        # nunca lanza: ver el docstring de la clase

    def drenar(self, agente_id: str) -> list:
        with self.lock:
            return list(self._buzon.pop(agente_id, []))

    def pendientes(self, agente_id: str) -> int:
        with self.lock:
            return len(self._buzon.get(agente_id) or ())

    def esta_cancelado(self, agente_id: str) -> bool:
        """Si el corte le ALCANZA: incluye el flag global, que vale para TODO
        id. Es la pregunta correcta para "¿este agente va a poder seguir?" y la
        EQUIVOCADA para "¿se corto a este agente?" — ver fue_cortado()."""
        with self.lock:
            return bool(self._global.is_set() or agente_id in self._cancelados)

    def fue_cortado(self, agente_id: str) -> bool:
        """Si a ESTE agente se le corto de verdad (defecto #3, 2026-08-17).

        NO ORea el flag global: tras un cancelar_corrida(), esta_cancelado()
        vale True para todo id existente y tambien para los que ya habian
        entregado su resultado — con eso, cancelar_agente() sobre uno que ya
        termino contestaba ok=True/'ya_cancelado' sobre algo que nadie corto.
        Aca solo esta quien recibio un cancelar_agente() explicito o quien
        murio POR el corte global (agente() lo sella en su salida cancelada)."""
        with self.lock:
            return agente_id in self._cancelados

    def estado(self, agente_id: str) -> str:
        with self.lock:
            return self._estado.get(agente_id, "")

    def motivo_de(self, agente_id: str) -> str:
        with self.lock:
            return self._motivo.get(agente_id) or self._motivo.get("*", "")

    def marcar_degradado(self) -> bool:
        """True la PRIMERA vez: el Degradado de _llamar sale una vez por
        corrida, no una por llamada."""
        with self.lock:
            if self._degradado_avisado:
                return False
            self._degradado_avisado = True
            return True

    # --- lo que usa la API publica de control -----------------------------
    def cancelar(self, agente_id: str, motivo: str) -> bool:
        """False si ya estaba cancelado (idempotente)."""
        with self.lock:
            if agente_id in self._cancelados:
                return False
            self._cancelados.add(agente_id)
            self._motivo[agente_id] = motivo
            return True

    def cancelar_todo(self, motivo: str) -> bool:
        with self.lock:
            if self._global.is_set():
                return False
            self._global.set()
            self._motivo["*"] = motivo
            return True

    def encolar(self, agente_id: str, texto: str) -> int:
        """Devuelve cuantos hay en cola tras encolar, o -1 si el buzon esta
        lleno (8 sin entregar = el agente no los esta leyendo)."""
        with self.lock:
            cola = self._buzon.setdefault(agente_id, [])
            if len(cola) >= _MAX_BUZON:
                return -1
            cola.append(texto)
            return len(cola)

    def vivos(self) -> int:
        with self.lock:
            return sum(1 for v in self._estado.values() if v == EST_VIVO)


class PresupuestoTokens:
    """Techo de tokens COMPARTIDO entre llamadas (viaja por parametro, jamas
    global de modulo). total=None significa sin techo. Thread-safe porque
    paralelo() registra usage desde varios hilos.

    El techo es BLANDO por diseno (documentado 2026-08-11): el corte es
    check-then-act SIN reserva — agente() mira agotado() ANTES de llamar y
    registra el usage DESPUES — asi que hasta cap llamadas concurrentes
    pueden pasar el corte cuando queda presupuesto para una sola; el
    sobregiro maximo es cap x (tokens de una llamada). Es tolerancia
    deliberada, no bug: reservar exigiria adivinar el usage de una llamada
    antes de pagarla, y el error de esa adivinanza seria peor que el
    sobregiro acotado."""

    def __init__(self, total: int = None):
        self.total = total
        self._gastado = 0
        self._estimado = 0
        self._sin_prompt = 0
        self._lock = threading.Lock()

    def registrar(self, usage: dict, estimado: bool = False) -> None:
        """Suma prompt+completion de un usage del server.

        `estimado=True` (defecto #5, 2026-08-17) marca los tokens que NO vienen
        del chunk de usage sino de una estimacion de chat_client (timings o
        frames de contenido al cortar). Se cobran igual —un corte cuesta
        tokens de verdad y el presupuesto es COMPARTIDO— pero se cuentan
        aparte, que es lo que permite decir "de los 253 gastados, 65 son
        estimados" en vez de dar un unico numero de fiabilidad desconocida.
        Misma regla que timings.predicted_n: se usa el numero Y se declara.

        `sin_prompt` cuenta las llamadas cuyo PROMPT no se pudo contabilizar
        —traigan completion o no— porque es exactamente el agujero que queda
        abierto tras cobrar el corte: el prompt del turno cortado no lo manda
        nadie. Incluye el corte en pleno prefill, donde el usage viene vacio
        entero y la llamada valdria CERO. Contarlo es lo que impide que el
        agujero vuelva a crecer sin que se vea."""
        u = usage or {}
        prompt = int(u.get("prompt_tokens") or 0)
        completion = int(u.get("completion_tokens") or 0)
        delta = prompt + completion
        with self._lock:
            self._gastado += delta
            if estimado:
                self._estimado += delta
            if not prompt:
                # Tica tambien cuando el usage viene VACIO ENTERO: es el corte
                # que cae ANTES del primer frame (el usuario corta durante el
                # prefill). Ahi la llamada se hizo, el server prefilleo el
                # prompt y no se cobra NADA. La condicion vieja pedia
                # `completion and not prompt`, asi que justo el caso donde el
                # agujero es el 100% de la llamada era el UNICO invisible.
                # Medido: prompt real 6.869 tokens, gastado 0, sin_prompt 0.
                self._sin_prompt += 1

    def gastado(self) -> int:
        with self._lock:
            return self._gastado

    def estimados(self) -> int:
        """Cuantos de los gastados son ESTIMADOS (no vinieron del server)."""
        with self._lock:
            return self._estimado

    def sin_prompt(self) -> int:
        """Llamadas cuyo prompt no se pudo contabilizar (tipicamente cortes).
        El agujero declarado del control por agente: visible, no invisible."""
        with self._lock:
            return self._sin_prompt

    def restante(self) -> float:
        if self.total is None:
            return float("inf")
        return max(float(self.total - self.gastado()), 0.0)

    def agotado(self) -> bool:
        return self.total is not None and self.gastado() >= self.total


def _dir_base() -> Path:
    """Raiz de las corridas; override por env para tests y bancos."""
    override = os.environ.get("COGNIA_WORKFLOWS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "workflows"


def _nuevo_run_id(nombre: str) -> str:
    """'YYYYmmdd-HHMMSS-<slug8>' — mismo formato que estado_tarea.nuevo_task_id
    (ordenable por nombre y legible a ojo)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (nombre or "").lower())[:8].strip("-")
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + (slug or "corrida")


@dataclass
class Corrida:
    """Estado de UNA corrida de workflow. Viaja por parametro (regla
    transversal: nada de estado global nuevo de modulo)."""
    nombre: str = ""
    run_id: str = ""
    dir: Path = None
    presupuesto: PresupuestoTokens = None
    print_fn: object = print
    cache: dict = field(default_factory=dict)   # clave sha256 -> resultado ok
    _fh: object = None                          # journal.jsonl abierto en 'a'
    # Contadores para WorkflowFin: el consumidor no debe tener que contar
    # eventos para pintar el cierre (bajo el sink stdout algunos se saltan y
    # no hay garantia de que los haya visto todos).
    total_agentes: int = 0                      # lo que el caller anuncio
    # Arranque para la duracion, en perf_counter y NO en time.time(): MEDIDO
    # en esta maquina, time.get_clock_info('time') da resolution=0.015625 y
    # adjustable=True (GetSystemTimeAsFileTime) — un reloj de 15,6 ms que
    # ademas puede saltar hacia atras a mitad de corrida. Los ts del journal
    # siguen siendo time.time() porque ahi hace falta hora de pared.
    _t0: float = 0.0
    _n_agentes: int = 0                         # AgenteInicio emitidos
    _n_terminados: int = 0                      # AgenteFin emitidos
    _n_fallidos: int = 0
    _n_hits: int = 0
    _cerrada: bool = False
    # El WorkflowFin que se emitio, para que cerrar() lo devuelva tambien en
    # las llamadas idempotentes (defecto #1: UN veredicto, dos consumidores).
    _fin_ev: object = None
    # RLock y no Lock (2026-08-17): el lock pasa a cubrir tambien la EMISION de
    # AgenteFin/WorkflowFin, que es lo unico que ordena de verdad los dos
    # eventos (ver el sello 'tardio' en agente()). Reentrante porque emitir()
    # llama a codigo de consumidores: uno que tocase la corrida desde su
    # callback se auto-bloquearia con un Lock simple, y el contrato del bus es
    # que un suscriptor jamas tumba un turno.
    _lock_ev: object = field(default_factory=threading.RLock)
    # ── CONTROL POR AGENTE (2026-08-17) — campos AL FINAL del dataclass a
    # proposito: todos los de arriba ya tenian default y ninguna posicion se
    # mueve, asi que ningun caller posicional existente se rompe.
    # `control` con default_factory y no None: decirle()/cancelar_*() nunca
    # revientan por un None que nadie construyo.
    control: ControlCorrida = field(default_factory=ControlCorrida)
    # interactivo=False deja el body de la llamada BYTE-IDENTICO al de hoy:
    # sin `cancelado` y sin `on_token`, chat_client no entra en la rama SSE.
    # Quien lo enciende es la VISTA, no el modelo (no se publica en
    # PARAMS_WORKFLOW): encenderlo por defecto cambiaria el transporte de
    # todas las corridas batch sin que nadie lo pidiera.
    interactivo: bool = False
    tokens_en_vivo: bool = None                 # None = sigue a interactivo
    max_repreguntas: int = _MAX_REPREGUNTAS
    _n_cancelados: int = 0                      # AgenteFin con cancelado=True

    def _siguiente(self) -> int:
        """Numero de agente, monotono y thread-safe: paralelo(cap=2) pide dos
        a la vez. Es el ORDEN DE ARRANQUE dentro de la corrida y nunca se
        repite: por eso es la parte del agente_id que garantiza unicidad."""
        with self._lock_ev:
            self._n_agentes += 1
            return self._n_agentes

    def _journal(self, linea: dict) -> None:
        """Append + flush por linea (patron bitacora._escribir): un crash deja
        el journal legible hasta el ultimo evento. Traga excepciones: el
        journal es constancia, no puede tumbar la corrida."""
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception as e:
            # Un thunk HUERFANO de paralelo() puede llegar aca con la corrida
            # ya cerrada (write sobre fh cerrado -> ValueError): se traga con
            # aviso a stderr en vez de en silencio (2026-08-11) — la linea se
            # pierde a sabiendas, pero la degradacion queda a la vista.
            try:
                print(f"aviso: journal no escribible "
                      f"({type(e).__name__}: {e}); linea perdida",
                      file=sys.stderr)
            except Exception:
                pass

    def cerrar(self, ok: bool = True, resumen: str = ""):
        """Cierra el journal (idempotente). En Windows dejar el handle abierto
        bloquea renombres/truncados del archivo, asi que los tests y los
        callers prolijos cierran al terminar.

        Emite WorkflowFin UNA sola vez: el adaptador cierra en un finally y los
        tests al terminar. El evento va DESPUES de cerrar el handle a proposito:
        en Windows un handle abierto bloquea renombres, y un consumidor que
        reciba WorkflowFin y quiera leer/mover el journal tiene que encontrarlo
        cerrado y flusheado.

        CONTABILIDAD HONESTA (2026-08-17). Hay TRES formas de no terminar y el
        cierre las distingue, porque contar solo los AgenteFin con ok=False
        dejaba pasar dos agujeros:

        - no_arrancados: el caller declaro N en corrida(total_agentes=N) y solo
          arrancaron M<N. Pasa cuando paralelo() agota el timeout: los futuros
          que nunca empezaron se cancelan y JAMAS llaman a agente(), asi que no
          hay AgenteInicio ni AgenteFin y el denominador se encogia solo. Con 4
          pasos, cap=1 y el primero colgado, esto salia como "agentes=1
          fallidos=0" -> el consumidor pintaba "1 de 1" (exito) sobre una
          corrida que perdio 3 de 4.
        - colgando: arrancaron (hay AgenteInicio) y al cerrar todavia no habian
          emitido AgenteFin. Son los HUERFANOS vivos de paralelo(): no se puede
          esperarlos —existen precisamente porque un hilo de Python no se mata—
          asi que la unica salida honesta es DECLARAR cuantos quedaron. Su
          AgenteFin, cuando llegue, sale marcado tardio=True.
        - _n_fallidos: los que si terminaron, con ok=False.

        Y si falta alguno, el cierre se fuerza a ok=False. Es lo que impide que
        el consumidor pinte exito: las dos formulas de presentacion
        (ux/renderer.py y remoto/sesiones.py) cortan con la linea de fallo
        cuando ok es False, sin tener que aprender los campos nuevos.

        DEVUELVE EL WorkflowFin QUE EMITIO (defecto #1, 2026-08-17). El cierre
        es quien DECIDE el veredicto —el caller propone `ok`/`resumen` y aca se
        corrige con la contabilidad— asi que un caller que construya su propio
        envelope a partir de lo que el propuso publica un veredicto DISTINTO
        del que fue al bus. Paso de verdad: con 2 de 2 agentes cancelados,
        ejecutar() del adaptador decia "ningun paso devolvio resultado" y
        WorkflowFin decia "2 agente(s) cancelados por el usuario"; con 1 de 3,
        uno decia ok=True y el otro ok=False sobre la MISMA corrida. Devolver
        el evento hace imposible la divergencia: hay UN veredicto y los dos
        consumidores leen el mismo objeto. En las llamadas siguientes
        (idempotente) devuelve el MISMO evento, nunca None: un caller que
        cierre dos veces no puede quedarse sin veredicto."""
        try:
            if self._fh is not None:
                self._fh.close()
        except Exception:
            pass
        self._fh = None
        # Todo el cierre va bajo el MISMO lock que agente() toma para sellar
        # 'tardio', y la emision incluida: es lo unico que garantiza que un
        # AgenteFin cae de un lado o del otro de WorkflowFin y nunca "despues
        # pero sin marca". Fuera del lock quedaba una ventana real (el huerfano
        # leia _cerrada=False, el cierre corria entero, y el Fin salia tarde y
        # sin marcar).
        with self._lock_ev:
            if self._cerrada:
                return self._fin_ev
            self._cerrada = True
            # Baja del directorio de corridas vivas ANTES de emitir: un
            # consumidor de WorkflowFin que llame cancelar_corrida(run_id)
            # tiene que recibir 'corrida_cerrada' y no 'aceptado' sobre algo
            # que ya no existe.
            _desregistrar(self)
            arrancados, term = self._n_agentes, self._n_terminados
            fall, hits = self._n_fallidos, self._n_hits
            cancelados = self._n_cancelados

            declarados = int(self.total_agentes or 0)
            no_arrancados = max(declarados - arrancados, 0)
            colgando = max(arrancados - term, 0)
            # max() y no el declarado a secas: criticar() suma agentes que el
            # adaptador no habia contado (declara len(pasos) y luego lanza 3
            # criticos), y el denominador no puede quedarse corto tampoco por ahi.
            agentes = max(arrancados, declarados)
            # Los que faltan cuentan como fallidos para que "agentes - fallidos"
            # siga significando "terminaron BIEN" en las formulas ya escritas.
            fallidos = fall + no_arrancados + colgando
            faltan = []
            if no_arrancados:
                faltan.append(f"{no_arrancados} de {declarados} agentes no "
                              f"llegaron a arrancar")
            if colgando:
                faltan.append(f"{colgando} agente(s) siguen colgando sin "
                              f"AgenteFin (huerfanos de paralelo)")
            if cancelados:
                # Mismo criterio que colgando/no_arrancados: una corrida donde
                # el usuario corto agentes NO es una corrida exitosa, y las dos
                # formulas de presentacion ya cortan por ok.
                faltan.append(f"{cancelados} agente(s) cancelados por el usuario")
            if faltan:
                ok = False
                # Los cancelados van PRIMERO: es lo unico de esta lista que el
                # usuario hizo a proposito, y cli.py imprime `error` y corta.
                # "ningun paso devolvio resultado; 2 cancelados" le dice al que
                # acaba de apretar el boton que el workflow no produjo nada.
                if cancelados:
                    faltan = ([f"{cancelados} agente(s) cancelados por el "
                               f"usuario"]
                              + [f for f in faltan if "cancelados" not in f])
                    resumen = "; ".join(faltan + ([resumen] if resumen else []))
                else:
                    resumen = "; ".join(([resumen] if resumen else []) + faltan)
            ev = ux.WorkflowFin(
                run_id=self.run_id, nombre=self.nombre, ok=bool(ok),
                agentes=agentes, fallidos=fallidos, cache_hits=hits,
                tokens=(self.presupuesto.gastado() if self.presupuesto else 0),
                tokens_estimados=(self.presupuesto.estimados()
                                  if self.presupuesto else 0),
                presupuesto_tokens=(getattr(self.presupuesto, "total", None) or 0),
                duracion_s=(time.perf_counter() - self._t0) if self._t0 else 0.0,
                resumen=resumen, total_agentes=declarados,
                arrancados=arrancados, no_arrancados=no_arrancados,
                colgando=colgando, cancelados=cancelados)
            # Se guarda ANTES de emitir: emitir() llama a consumidores y uno de
            # ellos puede volver a cerrar (el adaptador cierra en un finally).
            self._fin_ev = ev
            _emitir(ev)
            return ev


# ── Directorio de corridas VIVAS ────────────────────────────────────────────
# EXCEPCION DECLARADA a la regla del repo "nada de estado global de modulo", y
# acotada aca mismo:
#   - es un DIRECTORIO DE OBJETOS VIVOS, no configuracion;
#   - el motor NO lo lee: agente() usa `c.control`, que sigue viajando por
#     parametro. Solo lo consultan las funciones publicas de control;
#   - la referencia es DEBIL: si el caller suelta la Corrida sin cerrarla, el
#     GC se la lleva y el run_id cae en desconocido_corrida (declarado en §8).
# La alternativa (pasar el control desde el CLI) exige tocar cli.py y
# tools_harness.py, que no estan en el terreno, y aun asi la vista no conoceria
# el run_id antes de que exista: lo unico que la vista recibe es el bus
# (WorkflowInicio.run_id / AgenteInicio.agente_id). Ese es el handle.
_VIVAS: "weakref.WeakValueDictionary" = weakref.WeakValueDictionary()
# Los ultimos 32 cerrados. Sin esto, una corrida que acaba de terminar se ve
# IGUAL que un id mal tecleado, y eso es la degradacion silenciosa de siempre.
_CERRADAS: "collections.deque" = collections.deque(maxlen=32)
_REG_LOCK = threading.Lock()


def _registrar(c: "Corrida") -> None:
    with _REG_LOCK:
        _VIVAS[c.run_id] = c


def _desregistrar(c: "Corrida") -> None:
    with _REG_LOCK:
        _VIVAS.pop(c.run_id, None)
        if c.run_id and c.run_id not in _CERRADAS:
            _CERRADAS.append(c.run_id)


def _buscar_corrida(run_id: str):
    """(corrida, estado_si_no_esta). Uno de los dos es None."""
    with _REG_LOCK:
        c = _VIVAS.get(run_id)
        if c is not None:
            return c, ""
        return None, (CORRIDA_CERRADA if run_id in _CERRADAS
                      else DESCONOCIDO_CORRIDA)


def _cargar_cache_de_journal(ruta: Path) -> dict:
    """Lee un journal viejo linea a linea y devuelve {clave: resultado} de los
    agente() que terminaron SIN error. Tolera la ultima linea truncada por un
    crash (json.loads falla -> se salta): el resume nunca exige un archivo
    perfecto, solo lineas enteras."""
    cache: dict = {}
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            for cruda in fh:
                cruda = cruda.strip()
                if not cruda:
                    continue
                try:
                    d = json.loads(cruda)
                except ValueError:
                    continue    # linea a medio escribir: se pierde solo esa
                if (d.get("tipo") == "agente" and not d.get("error")
                        and "resultado" in d and d.get("clave")):
                    cache[d["clave"]] = d["resultado"]
    except OSError:
        pass
    return cache


def _contar_dialogos(ruta: Path) -> int:
    """Cuantos agentes de un journal viejo recibieron mensajes en curso.

    Su resultado se guardo bajo `resultado_dialogo` (nombre DISTINTO a
    proposito) y por eso _cargar_cache_de_journal no puede recogerlo: en un
    resume se vuelven a pagar. Un resume que cuesta el doble sin explicar por
    que es degradacion silenciosa, asi que se cuentan para poder avisarlo."""
    n = 0
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            for cruda in fh:
                cruda = cruda.strip()
                if not cruda:
                    continue
                try:
                    d = json.loads(cruda)
                except ValueError:
                    continue
                if d.get("tipo") == "agente" and "resultado_dialogo" in d:
                    n += 1
    except OSError:
        pass
    return n


def corrida(nombre: str, presupuesto_tokens: int = None,
            resume_de: str = "", print_fn=print,
            total_agentes: int = 0, interactivo: bool = False,
            tokens_en_vivo: bool = None) -> Corrida:
    """Abre una corrida nueva bajo <base>/<run_id>/ con su journal.jsonl.

    resume_de = run_id de una corrida previa: se cargan del journal viejo los
    resultados OK de agente() y las claves identicas se sirven de cache sin
    llamar al LLM (el hit queda anotado en el journal NUEVO).

    total_agentes lo declara quien CONOCE el plan (el adaptador sabe cuantos
    pasos hay): el panel dibuja los huecos de una vez en vez de crecer de a
    uno. 0 = no se sabe.

    interactivo=True habilita el control por agente (cancelar_agente/decirle)
    y le pasa a completar() el kwarg `cancelado`, con lo que el corte llega
    DENTRO de la llamada. Cambia el transporte a la rama SSE de chat_client:
    por eso es opt-in y lo enciende la VISTA. tokens_en_vivo=None sigue a
    interactivo; ponerlo en False deja el control sin emitir TokenTexto."""
    c = Corrida(nombre=nombre, run_id=_nuevo_run_id(nombre),
                presupuesto=PresupuestoTokens(presupuesto_tokens),
                print_fn=print_fn or (lambda *_a, **_k: None),
                interactivo=bool(interactivo),
                tokens_en_vivo=tokens_en_vivo)
    # Des-colisionar: dos corridas del mismo nombre en el MISMO segundo
    # compartirian run_id (la resolucion del timestamp es 1 s) y por lo tanto
    # journal — el resume leeria historia ajena. Sufijo -2, -3... si ya existe.
    base = _dir_base()
    candidato, n = c.run_id, 1
    while True:
        try:
            # mkdir ATOMICO como reserva del run_id: exists()+mkdir(exist_ok=
            # True) era TOCTOU (dos corridas concurrentes pasaban ambas el
            # check y compartian dir+journal). FileExistsError = reintentar.
            (base / candidato).mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            n += 1
            candidato = f"{c.run_id}-{n}"
    c.run_id = candidato
    c.dir = base / c.run_id
    dialogados = 0
    if resume_de:
        viejo = _dir_base() / resume_de / "journal.jsonl"
        c.cache = _cargar_cache_de_journal(viejo)
        dialogados = _contar_dialogos(viejo)
    # 'a' y no 'w': si un reloj repetido choca run_id, no se pisa historia.
    c._fh = open(c.dir / "journal.jsonl", "a", encoding="utf-8")
    c._journal({"tipo": "corrida", "nombre": nombre, "run_id": c.run_id,
                "resume_de": resume_de or None,
                "cache_precargada": len(c.cache), "ts": time.time()})
    # El evento va ACA y no al principio de la funcion: el run_id no es
    # definitivo hasta el bucle de des-colision y el dir no existe hasta el
    # mkdir — el consumidor recibe un run_id y un journal que YA estan en disco.
    c.total_agentes = int(total_agentes or 0)
    c._t0 = time.perf_counter()
    # El registro va tras fijar el run_id DEFINITIVO (despues del bucle de
    # des-colision) y antes del evento: quien reciba WorkflowInicio y llame
    # cancelar_corrida(run_id) tiene que encontrarla.
    _registrar(c)
    _emitir(ux.WorkflowInicio(
        run_id=c.run_id, nombre=nombre, total_agentes=c.total_agentes,
        presupuesto_tokens=int(presupuesto_tokens or 0),
        resume_de=resume_de or "", cache_precargada=len(c.cache),
        interactivo=c.interactivo))
    if dialogados:
        _emitir(ux.Aviso(
            texto=(f"{dialogados} agentes de la corrida {resume_de} recibieron "
                   f"mensajes; su resultado NO se sirve de cache y se vuelve a "
                   f"pagar (con la pregunta ORIGINAL: el dialogo no sobrevive "
                   f"al resume)"),
            origen="workflows.corrida"))
    return c


def _clave_cache(prompt: str, system: str, schema, rol: str,
                 max_tokens: int) -> str:
    """sha256 del JSON canonico de lo que DEFINE la salida. La temperatura NO
    entra a proposito: ajustar sampling no debe invalidar un resume."""
    carga = {"prompt": prompt, "system": system, "schema": schema,
             "rol": rol, "max_tokens": max_tokens}
    canon = json.dumps(carga, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _valida(obj, schema, ruta: str = "$") -> list:
    """Validacion JSON Schema MINIMA sin dependencia externa: type /
    properties / required / items / enum. Devuelve lista de errores legibles
    (vacia = conforme). Suficiente para schemas de salida de agentes; lo que
    no entiende, lo ignora (permisivo a proposito: el server ya fuerza la
    gramatica, esto es la red de seguridad local)."""
    errores: list = []
    if not isinstance(schema, dict):
        return errores

    tipo = schema.get("type")
    if tipo:
        tipos = tipo if isinstance(tipo, list) else [tipo]
        # bool es subclase de int en Python: excluirlo explicitamente de
        # integer/number para que true no pase por 1.
        def _es(t):
            if t == "object":
                return isinstance(obj, dict)
            if t == "array":
                return isinstance(obj, list)
            if t == "string":
                return isinstance(obj, str)
            if t == "integer":
                return isinstance(obj, int) and not isinstance(obj, bool)
            if t == "number":
                return isinstance(obj, (int, float)) and not isinstance(obj, bool)
            if t == "boolean":
                return isinstance(obj, bool)
            if t == "null":
                return obj is None
            return True     # tipo desconocido: no opinar
        if not any(_es(t) for t in tipos):
            errores.append(f"{ruta}: se esperaba type {tipo!r} y vino "
                           f"{type(obj).__name__}")
            return errores  # sin el tipo correcto, lo demas no aplica

    if "enum" in schema:
        # Igualdad a mano (2026-08-11): en Python True == 1 (bool es subclase
        # de int), asi que 'obj in enum' dejaba pasar true contra [1, 2] — el
        # server lo rechazaria. bool solo matchea bool; entre no-bools vale la
        # igualdad numerica matematica (1.0 si matchea 1, como en JSON).
        def _en_enum(v, op):
            if isinstance(v, bool) != isinstance(op, bool):
                return False
            return v == op
        if not any(_en_enum(obj, op) for op in schema["enum"]):
            errores.append(
                f"{ruta}: valor {obj!r} fuera del enum {schema['enum']!r}")

    if isinstance(obj, dict):
        for req in schema.get("required") or []:
            if req not in obj:
                errores.append(f"{ruta}: falta la clave requerida '{req}'")
        for k, sub in (schema.get("properties") or {}).items():
            if k in obj:
                errores.extend(_valida(obj[k], sub, f"{ruta}.{k}"))

    if isinstance(obj, list) and isinstance(schema.get("items"), dict):
        for i, elem in enumerate(obj):
            errores.extend(_valida(elem, schema["items"], f"{ruta}[{i}]"))

    return errores


def _resolver_backend(c: Corrida, rol: str, url: str) -> tuple:
    """(url, sampling) segun rol. rol 'worker' -> summoner.ensure con
    DEGRADACION al cerebro (jamas colgar la corrida por el worker: el aviso
    va por print_fn y se sigue)."""
    if url:
        return url, dict(_SAMPLING_CEREBRO)
    if rol == "worker":
        try:
            # Import perezoso: summoner arrastra estado de flota y aca solo
            # se necesita si el caller pidio el rol. Via importlib (sys.modules
            # manda): `from cognia import summoner` resuelve por el atributo
            # del paquete cuando el modulo real ya se importo, y un stub de
            # sys.modules en tests quedaria ignorado segun el ORDEN de la
            # suite (verde aislado, rojo en suite — cazado 2026-08-11).
            import importlib
            summoner = importlib.import_module("cognia.summoner")
            res = summoner.ensure("worker")
            if res.get("url"):
                return res["url"], dict(_SAMPLING_WORKER)
            raise RuntimeError("ensure devolvio sin url")
        except Exception as e:
            try:
                c.print_fn(f"aviso: worker no disponible "
                           f"({type(e).__name__}: {e}); hijos van al cerebro")
            except Exception:
                pass
    from cognia.agent.model_profiles import url_del_backend
    return url_del_backend(), dict(_SAMPLING_CEREBRO)


def _completar_por_defecto():
    """Import perezoso de chat_client (regla transversal: riesgo de ciclo)."""
    from cognia.agent.chat_client import completar
    return completar


def _emitir(evento) -> None:
    """emitir() ya es no-lanzante por contrato; este guard cubre solo un bus
    roto de raiz. La regla dura: si el bus falla, la corrida sigue."""
    try:
        ux.emitir(evento)
    except Exception:
        pass


def _avisar_clamp(c, pedido: int, efectivo: int, minimo: int) -> None:
    """Deja constancia de que max_tokens se SUBIO por debajo de la mano.

    Dos canales con propositos distintos y a proposito desiguales:
      - JOURNAL: una linea por AGENTE clampeado. Es la contabilidad, y contar
        cuantas llamadas se clamparon solo se puede si estan todas.
      - BUS (Aviso): UNA vez por corrida y valor pedido. Es la UI, y seis
        avisos identicos en un workflow de seis pasos no informan: tapan.

    Tolerante con una Corrida a medio construir (tests que llaman agente() con
    un doble): sin `_clamps_avisados` se avisa igual, nunca se lanza. Este
    aviso no puede costar un turno.
    """
    linea = (f"max_tokens={pedido} se subio a {efectivo}: por debajo de "
             f"MIN_TOKENS_RAZONADOR={minimo} el pensamiento del razonador se "
             f"come el techo y el content vuelve VACIO (medido). La llamada, "
             f"la clave de cache y los errores hablan de {efectivo}, no de "
             f"{pedido}")
    try:
        c._journal({"tipo": "clamp_max_tokens", "pedido": pedido,
                    "efectivo": efectivo, "minimo": minimo,
                    "ts": time.time()})
    except Exception:
        pass
    try:
        vistos = getattr(c, "_clamps_avisados", None)
        if vistos is None:
            vistos = set()
            try:
                c._clamps_avisados = vistos
            except Exception:
                pass            # dataclass con slots o doble de test: se avisa igual
        if pedido in vistos:
            return
        vistos.add(pedido)
    except Exception:
        pass
    _emitir(ux.Aviso(texto=linea, origen="workflows.agente"))


def _tokens_desconocidos(usage: dict) -> bool:
    """True si el usage NO dice cuantos tokens se generaron.

    Vacio significa "no se pudo saber", JAMAS "0 tokens" (misma regla que
    RespuestaChat.completion_tokens).

    CAMBIO DE CONTRATO (defecto #5, 2026-08-17). Aca decia "al cortar es lo
    normal; se registra 0 antes que inventar: PROHIBIDO estimar", y ese 0
    silencioso costaba ~88 tokens por corte (MEDIDO con /tokenize: prompt 23 +
    generados 65, tres veces) contra un presupuesto COMPARTIDO, con un techo
    de max_repreguntas(8) x (prompt + max_tokens) ≈ 16k tokens invisibles por
    agente. La regla nueva no es "inventar": es la MISMA que ya regia para
    timings.predicted_n — se cuenta lo que se puede MEDIR (los frames de
    contenido recibidos, que en SSE son un token cada uno) y se declara que
    es estimado, en el journal (usage_estimado/usage_via), en el presupuesto
    (estimados()) y en el cierre (WorkflowFin.tokens_estimados). Lo que sigue
    prohibido es inventar lo que no se puede medir: el PROMPT del turno
    cortado no llega y no se estima — se cuenta en presupuesto.sin_prompt()
    para que el agujero que queda sea visible en vez de invisible.

    Asi que hoy esto solo es True cuando se corto ANTES del primer frame."""
    v = (usage or {}).get("completion_tokens")
    return not isinstance(v, (int, float)) or isinstance(v, bool)


def _etiqueta(texto: str, tope: int = 60) -> str:
    """Titulo de UNA linea para el panel. El prompt de un critico son 900
    chars de plantilla: el panel necesita un nombre, no el encargo."""
    linea = next((l.strip() for l in (texto or "").split("\n") if l.strip()), "")
    return linea[:tope] + ("…" if len(linea) > tope else "")


# Los kwargs que pueden NO existir en la firma de un completar() ajeno. `kw`
# (url, temperature, top_p, max_tokens, razonador, via) son los que TODO
# completar acepta desde siempre y jamas se filtran; los dos conjuntos son
# disjuntos por construccion, asi que no hay colision de claves.
_KW_OPCIONALES = ("response_format", "on_token", "on_reasoning", "cancelado")


def _llamar(fn, mensajes, rf, opcionales=None, **kw):
    """Una llamada tolerando que la firma de fn no acepte los kwargs nuevos.

    Devuelve (resp, descartados: tuple[str, ...]). La tupla es la DEGRADACION
    VISIBLE y no un detalle: perder `response_format` cuesta gramatica (la
    validacion local y el retry siguen cubriendo el contrato), pero perder
    `cancelado` vuelve la llamada INCANCELABLE, y eso no puede pasar callado.

    Se conservan las dos reglas de 2026-08-11: UNA sola llamada (nada de
    try/except TypeError, que tragaba un TypeError INTERNO de fn y pagaba una
    segunda llamada identica con la gramatica caida en silencio) y la decision
    por inspect.signature."""
    ops = {k: v for k, v in (opcionales or {}).items() if v is not None}
    if rf is not None:
        ops["response_format"] = rf
    if not ops:
        return fn(mensajes, **kw), ()       # camino historico, intacto
    try:
        params = inspect.signature(fn).parameters
        libre = any(p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in params.values())
        acepta = set(params)
    except (TypeError, ValueError):
        # Firma no introspectable (builtin/C): asumir el chat_client nuevo.
        libre, acepta = True, set()
    if libre:
        return fn(mensajes, **ops, **kw), ()
    pasa = {k: v for k, v in ops.items() if k in acepta}
    return fn(mensajes, **pasa, **kw), tuple(sorted(set(ops) - set(pasa)))


def _mk_callbacks(c: Corrida, agente_id: str, intento_de):
    """(on_token, on_reasoning) para UNA llamada.

    TokenTexto sale 1:1 y SIN throttle: el trabajo de ese evento es SER el
    texto, y cualquier coalescido por tiempo introduce un modo de fallo nuevo
    (el ultimo fragmento se queda en el buffer) para resolver un coste que no
    esta medido. La palanca correcta es el opt-in (interactivo/tokens_en_vivo)
    y COGNIA_EVENTS_SALTAR, no el filtro.

    AgenteProgreso y RazonamientoTick SI van throttleados (250 ms / 400 chars):
    su trabajo es "algo esta pasando", no "este es el texto". Existen porque el
    sink stdout salta TokenTexto por una razon medida y, sin latido, el movil
    no sabe que hay algo que interrumpir.

    Los callbacks corren en el MISMO hilo que llamo a completar() (es
    sincrono), que es el hilo donde agente() hizo marcar_agente: los eventos
    salen sellados con el agente_id correcto sin tocar nada mas."""
    st = {"chars": 0, "razon": 0, "t": _reloj(), "marca": 0}

    def _toca_latido() -> bool:
        ahora = _reloj()
        total = st["chars"] + st["razon"]
        if (ahora - st["t"]) >= _LATIDO_S or (total - st["marca"]) >= _LATIDO_CHARS:
            st["t"], st["marca"] = ahora, total
            return True
        return False

    def _on_token(frag: str) -> None:
        frag = frag or ""
        st["chars"] += len(frag)
        _emitir(ux.TokenTexto(texto=frag))
        if _toca_latido():
            _emitir(ux.AgenteProgreso(
                run_id=c.run_id, chars=st["chars"],
                chars_razonamiento=st["razon"], intento=intento_de()))

    def _on_reasoning(frag: str) -> None:
        frag = frag or ""
        st["razon"] += len(frag)
        if _toca_latido():
            _emitir(ux.RazonamientoTick(chars=st["razon"], fragmento=frag))
            _emitir(ux.AgenteProgreso(
                run_id=c.run_id, chars=st["chars"],
                chars_razonamiento=st["razon"], intento=intento_de()))

    return _on_token, _on_reasoning


def agente(c: Corrida, prompt: str, schema: dict = None, *, system: str = "",
           rol: str = "", url: str = "", max_tokens: int = 2048,
           temperatura: float = None, reintentos: int = 1,
           completar_fn=None, via: str = "wf_agente",
           indice: int = 0, total: int = 0, fase: str = "",
           etiqueta: str = ""):
    """UN agente de workflow: prompt -> str, o prompt+schema -> dict validado.

    Contrato (congelado 2026-08-11):
    - cache por sha256 canonico de {prompt, system, schema, rol, max_tokens};
      un hit (corrida con resume_de) se devuelve SIN llamar al LLM.
    - presupuesto agotado -> {"_error": ...} SIN llamar; cada respuesta real
      registra su usage.
    - schema -> response_format json_schema (forma verificada EN VIVO contra
      :8080, ver abajo) + json.loads + _valida; fallo -> 1 reintento con el
      error REAL apendeado al prompt (patron structure.py repair); segundo
      fallo -> {"_error": ..., "_crudo": texto}.
    - finish_reason 'length' -> error de presupuesto con numeros, SIN retry.
    - Todo (hit o real) deja una linea en el journal.
    Los errores vuelven como dict {"_error": ...}, nunca como excepcion.

    Eventos (2026-08-17): AgenteInicio al arrancar y AgenteFin SIEMPRE, desde
    un finally — cache-hit, presupuesto agotado, error del backend, truncado y
    excepcion incluidos. Un agente que arranca TERMINA en el panel.
    indice/total/fase/etiqueta los pone quien CONSTRUYE el plan (el adaptador,
    criticar()); si no vienen, el agente se auto-numera con el contador de la
    corrida y sale como fase 'suelto' — asi el invariante vale tambien para
    callers que no saben nada de esto.
    """
    # Clamp del razonador ANTES que nada (2026-08-11): chat_client ya clampea
    # por su lado, asi que el error de 'length' reportaba el max_tokens
    # PRE-clamp (p.ej. 64) mientras la llamada real iba con 1024 — clave de
    # cache, llamada y mensajes de error tienen que hablar del MISMO numero.
    # Import perezoso: model_profiles arrastra la tabla de familias y aca
    # solo hace falta la constante.
    from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR
    _pedido = int(max_tokens)
    max_tokens = max(_pedido, MIN_TOKENS_RAZONADOR)
    if max_tokens != _pedido:
        # EL CLAMP SE AVISA (2026-08-17). Se mantiene —quitarlo revive el modo
        # de fallo medido: con un razonador y max_tokens=32 el `content` sale
        # VACIO porque el pensamiento se come el techo (model_profiles.py:67,
        # y "10 bugs identicos de max_tokens" en la memoria del repo)— pero
        # deja de ser MUDO. Un instrumento que recibe 64 y llama con 1024 sin
        # decirlo convierte en mentira toda tabla que anote "pedi 64": el que
        # mide cree estar midiendo el techo bajo y esta midiendo 1024.
        # Por que avisar y no obedecer: obedecer devuelve texto vacio y cuesta
        # igual; el clamp entrega algo. La eleccion es del que mide, y para
        # elegir tiene que ENTERARSE.
        # UNA vez por corrida y por valor pedido: un workflow de 6 pasos con el
        # mismo max_tokens emitiria 6 avisos identicos y el panel se vuelve
        # ilegible. El JOURNAL, en cambio, lleva la linea de TODOS los agentes
        # (es constancia, no UI) para que un analisis posterior pueda contar
        # cuantas llamadas se clamparon, no solo que hubo alguna.
        _avisar_clamp(c, _pedido, max_tokens, MIN_TOKENS_RAZONADOR)

    clave = _clave_cache(prompt, system, schema, rol, max_tokens)

    # --- identidad del agente. El contador se pide SIEMPRE, tambien cuando el
    # caller trae su propio indice: WorkflowFin.agentes tiene que cuadrar con
    # los AgenteInicio emitidos.
    n = c._siguiente()
    idx = int(indice) if indice else n
    fase = fase or "suelto"
    etiqueta = etiqueta or _etiqueta(prompt)
    # FORMATO "<run_id>#<fase>.<indice>@<n>" (2026-08-17). El "@<n>" —el
    # contador monotono de la corrida— es lo que hace el id UNICO, y va SIEMPRE,
    # tambien cuando coincide con el indice.
    #
    # POR QUE hacia falta: "#<fase>.<indice>" NO era unico. El indice es el
    # numero LOGICO que pone el caller ("2 de 6") y se repite legitimamente:
    # criticar() pasa indice=1..3, y el lazo "refutado -> corrige -> vuelve a
    # criticar" llama a criticar() dos veces sobre la MISMA Corrida, con lo que
    # salian '#critica.1','#critica.2','#critica.3','#critica.1',... El panel
    # agrupa TokenTexto y Aviso por agente_id, asi que mezclaba la prosa de dos
    # rondas distintas del lazo en una sola fila.
    #
    # POR QUE no se arreglo pisando el indice con el contador: indice/total son
    # la CARA VISIBLE ("agente 2/6 critico evidencia" en renderer._ref_agente y
    # en sesiones._ref_agente) y tienen que seguir siendo el numero logico de la
    # fase, no el orden de arranque global — con dos criticar() el segundo lote
    # se leeria "agente 4/3". Separar las dos cosas: indice/total para MOSTRAR,
    # el sufijo @n para CORRELACIONAR.
    #
    # POR QUE se anade siempre y no solo cuando colisiona: un formato que cambia
    # de forma segun el caso obliga a todo consumidor a parsear dos gramaticas y
    # a acertar cual aplica. El id es opaco para los consumidores actuales
    # (renderer, sesiones y el panel lo usan como clave de agrupacion, nunca lo
    # descomponen), asi que el coste de la redundancia es cero.
    agente_id = f"{c.run_id}#{fase}.{idx}@{n}"
    # --- A0: el agente NACE para el control ANTES de anunciarse. emitir() es
    # SINCRONO: un suscriptor de AgenteInicio que llame decirle(ev.agente_id,…)
    # corre antes del checkpoint A, y si el agente no hubiese nacido todavia
    # recibiria 'desconocido_agente' por un mensaje perfectamente legitimo.
    c.control.nace(agente_id)
    # El anillo de estados pudo tirar el buzon de un agente viejo al hacer
    # sitio para este. Se anota aca —el control no conoce el journal— para que
    # ningun mensaje se pierda en silencio (mismo invariante que los otros
    # cuatro caminos de descarte).
    for _viejo_id, _texto in c.control.drenar_evictados():
        _mensaje_no_atendido(c, _viejo_id, "evictado del anillo de estados",
                             _texto)
    _emitir(ux.AgenteInicio(run_id=c.run_id, agente_id=agente_id, indice=idx,
                            total=int(total or 0), fase=fase,
                            etiqueta=etiqueta, rol=rol, clave=clave,
                            tardio=c._cerrada))
    try:
        # Sella la identidad en el CONTEXTO: los TokenTexto que emita el
        # backend durante esta llamada salen correlacionados sin que el
        # productor (node/llama_backend.py) sepa nada de workflows.
        _tok_ctx = ux.marcar_agente(agente_id)
    except Exception:
        _tok_ctx = None
    _t0 = time.perf_counter()           # monotono: ver el comentario de _t0
    # Dict mutable a proposito: cada camino de salida deja SU verdad sin
    # duplicar la construccion del evento en los ocho returns.
    _fin = {"ok": False, "motivo": "el agente termino sin resultado",
            "cache_hit": False, "tokens": 0, "intentos": 0,
            "url": "", "resumen": "", "cancelado": False,
            "repreguntas": 0, "descartado_chars": 0}
    try:
        def _falla(msg: str, crudo: str = None, usage: dict = None,
                   url_j: str = None, cancelado: bool = False):
            # usage/url_j (2026-08-11): los caminos de FALLO perdian el usage
            # pagado y la url efectiva en el journal — un fallo post-llamada
            # tiene que dejar constancia de lo que COSTO y contra que backend.
            #
            # INVARIANTE CRITICO (2026-08-17): esta linea lleva "error" no
            # vacio y NO lleva la clave "resultado". Es lo unico que hace que
            # _cargar_cache_de_journal —que exige `not error and "resultado" in
            # d`— se salte a un agente cancelado en un resume, SIN tocar el
            # loader. El camino cancelado sale por aca a proposito.
            _fin["ok"] = False
            _fin["motivo"] = msg
            if url_j is not None:
                _fin["url"] = url_j
            salida = {"_error": msg}
            if crudo is not None:
                salida["_crudo"] = crudo
            if cancelado:
                # MARCA, no prosa: el caller (el adaptador) tiene que poder
                # distinguir "lo corto el usuario" de "fallo" sin husmear el
                # texto de _error. Un consumidor que decida por substring se
                # rompe la primera vez que alguien reescriba el mensaje.
                salida["_cancelado"] = True
            c._journal({"tipo": "agente", "agente_id": agente_id,
                        "clave": clave, "cache_hit": False,
                        "rol": rol, "url": url_j if url_j is not None else url,
                        "usage": usage, "error": msg, "ts": time.time()})
            return salida

        def _cancelado():
            """Salida CANCELADA. Emite AgenteInicio y AgenteFin igual que
            cualquier otro agente: la contabilidad honesta de cerrar() cuenta
            con que todo lo que nace muere, y un return mudo lo dejaria
            contado como 'colgando'.

            Es el EMBUDO UNICO de los cuatro puntos de corte (checkpoints A, B,
            D y E), y por eso dos cosas viven aca y no repetidas en cada uno:

            - SELLA el corte en el control (defecto #3). Un agente que muere
              por el flag GLOBAL no estaba en `_cancelados`, asi que despues de
              morir era indistinguible de uno que entrego: fue_cortado() tiene
              que poder decir cual de los dos es sin ORear el flag global.
            - VACIA el buzon dejando constancia (defecto #2). El checkpoint B
              devuelve por aca ANTES de drenar, asi que un mensaje que llego
              justo antes del corte se perdia sin una linea. Se drena para que
              no quede colgado en un buzon que nadie va a leer, y cada uno deja
              su 'mensaje_no_atendido' como en los otros caminos de descarte.
            """
            _fin["cancelado"] = True
            mot = c.control.motivo_de(agente_id) or "el usuario corto"
            c.control.cancelar(agente_id, mot)      # idempotente: sella
            for pendiente in c.control.drenar(agente_id):
                _mensaje_no_atendido(c, agente_id, "agente cancelado",
                                     pendiente)
            return _falla(f"cancelado por el usuario: {mot}",
                          url_j=_fin["url"] or url, cancelado=True)

        # --- checkpoint A: cancelado antes de llamar a nadie ---------------
        if c.control.esta_cancelado(agente_id):
            return _cancelado()

        # --- cache hit (resume): resultado ya pagado en una corrida previa ---
        # Se SALTA el hit si hay mensajes pendientes para este agente: dos
        # pasos con el mismo prompt, el primero cachea, y al segundo le hablan
        # antes de arrancar -> sin este check se devolveria la respuesta del
        # primero sin haber leido nunca el mensaje.
        if clave in c.cache and not c.control.pendientes(agente_id):
            resultado = c.cache[clave]
            c._journal({"tipo": "agente", "agente_id": agente_id,
                        "clave": clave, "cache_hit": True,
                        "rol": rol, "url": "", "usage": None, "error": None,
                        "resultado": resultado, "ts": time.time()})
            _fin["ok"] = True
            _fin["motivo"] = ""
            _fin["cache_hit"] = True
            _fin["resumen"] = _etiqueta(str(resultado), 200)
            return resultado

        # Techo ANTES de tocar backend alguno: con el presupuesto agotado ni
        # siquiera se convoca al worker (convocar cuesta VRAM y segundos).
        if c.presupuesto and c.presupuesto.agotado():
            return _falla(f"presupuesto de {c.presupuesto.total} tokens "
                          f"agotado (gastados {c.presupuesto.gastado()})")

        fn = completar_fn or _completar_por_defecto()
        url_efectiva, sampling = _resolver_backend(c, rol, url)
        _fin["url"] = url_efectiva
        if temperatura is not None:
            sampling["temperature"] = temperatura

        # Forma de response_format VERIFICADA EN VIVO 2026-08-11 contra :8080
        # (Qwythos-9B, llama-server): {"type": "json_schema", "json_schema":
        # {"name": ..., "schema": <JSON Schema>, "strict": true}} -> HTTP 200,
        # el server fuerza la gramatica y el content sale JSON conforme
        # (probado con {"x": integer} -> '{ "x": 7 }'). La forma plana
        # {"type": "json_object", "schema": ...} tambien funciona, pero se fija
        # la anidada por ser la del estandar OpenAI (portable a otros servers).
        rf = None
        # 'is not None' y no truthiness (2026-08-11): schema={} es falsy pero ES
        # un schema valido (todo JSON conforme) — tratarlo como texto libre
        # devolvia el string crudo sin parsear ni pedir gramatica.
        if schema is not None:
            rf = {"type": "json_schema",
                  "json_schema": {"name": "salida", "schema": schema,
                                  "strict": True}}

        # --- "cortar y volver a preguntar" ---------------------------------
        # mensajes = [system?, user(prompt), user(t1), … user(tk)]: turnos de
        # usuario SEPARADOS, tal como lo pidio el dueno. Lo generado NO se
        # reinyecta como turno assistant: se TIRA. Consecuencia declarada: el
        # modelo no ve su propio arranque y puede repetirlo.
        dialogo: list = []
        fusionar = False        # fallback de plantilla (ver mas abajo)

        def _armar() -> list:
            base = [{"role": "system", "content": system}] if system else []
            if not dialogo:
                return base + [{"role": "user", "content": prompt}]
            if fusionar:
                return base + [{"role": "user",
                                "content": prompt + "\n\n" + "\n\n".join(dialogo)}]
            return (base + [{"role": "user", "content": prompt}]
                    + [{"role": "user", "content": t} for t in dialogo])

        def _corte(causa: str, parcial: str, usage: dict,
                   estimado: bool = False, via: str = "") -> None:
            """Lo generado se tira, pero queda en el journal: si no, el usuario
            paga tokens que no puede ni ver.

            `usage_desconocido` ya NO es lo normal al cortar (defecto #5):
            chat_client estima los generados contando los frames de contenido.
            Queda para el caso que sigue siendo desconocido de verdad —cortar
            antes del primer frame— y se agrega `usage_estimado`/`usage_via`
            para que la linea diga de donde salio el numero."""
            parcial = parcial or ""
            _fin["descartado_chars"] += len(parcial)
            desconocido = _tokens_desconocidos(usage)
            c._journal({"tipo": "corte", "agente_id": agente_id,
                        "causa": causa, "descartado": parcial[:500],
                        "descartado_chars": len(parcial),
                        "usage": (usage or None),
                        "usage_desconocido": desconocido,
                        "usage_estimado": bool(estimado),
                        "usage_via": via, "ts": time.time()})

        mensajes = _armar()
        # El ultimo turno de usuario LIMPIO (sin prompt de reparacion pegado).
        # Se refresca SOLO cuando se rearma, no en cada vuelta: si no, con
        # reintentos>=2 el segundo repair se construiria sobre el primero y el
        # prompt crecerian apilando "SALIDA INVALIDA" sobre "SALIDA INVALIDA".
        base_ultimo = mensajes[-1]["content"]
        # `reintentos` es el del SCHEMA y se reinicia en cada re-pregunta: es
        # otra pregunta, y el "SALIDA INVALIDA en el intento anterior" del
        # prompt de reparacion hablaria de una respuesta que ya no existe.
        reint_schema = max(int(reintentos), 0) if schema is not None else 0
        usados_schema = 0
        texto = ""
        # `_fin["intentos"]` acumula TODAS las llamadas al LLM, cortadas
        # incluidas: su contrato documentado es "llamadas al LLM que costo".
        en_vivo = (c.tokens_en_vivo if c.tokens_en_vivo is not None
                   else c.interactivo)
        while True:
            # El techo se mira ANTES de cada llamada (tambien de los retries y
            # de las re-preguntas): un retry no tiene licencia para pasarse del
            # presupuesto.
            if c.presupuesto and c.presupuesto.agotado():
                # El mensaje del usuario NO se evapora sin rastro.
                for pendiente in c.control.drenar(agente_id):
                    _mensaje_no_atendido(c, agente_id, "presupuesto agotado",
                                         pendiente)
                return _falla(f"presupuesto de {c.presupuesto.total} tokens "
                              f"agotado (gastados {c.presupuesto.gastado()})",
                              url_j=url_efectiva)

            # --- checkpoint B: cancelacion y buzon, ENTRE llamadas ---------
            if c.control.esta_cancelado(agente_id):
                return _cancelado()
            if c.control.pendientes(agente_id):
                if _fin["repreguntas"] >= int(c.max_repreguntas or 0):
                    for pendiente in c.control.drenar(agente_id):
                        _mensaje_no_atendido(c, agente_id,
                                             "tope de repreguntas", pendiente)
                    return _falla(
                        f"{c.max_repreguntas} repreguntas seguidas: el agente "
                        f"no llega a terminar", url_j=url_efectiva)
                for t in c.control.drenar(agente_id):
                    dialogo.append(t)
                    c._journal({"tipo": "mensaje", "agente_id": agente_id,
                                "texto": t, "ts": time.time()})
                _fin["repreguntas"] += 1
                usados_schema = 0       # otra pregunta: el retry se reinicia
                mensajes = _armar()
                base_ultimo = mensajes[-1]["content"]

            # --- checkpoint C: el corte llega DENTRO de la llamada ---------
            # Los tres kwargs solo con interactivo=True: pasarlos mete a
            # chat_client en la rama SSE para TODA llamada de workflow y el
            # usage pasa a depender de stream_options.include_usage. Con
            # interactivo=False el body queda byte-identico al historico.
            opcionales = None
            if c.interactivo:
                opcionales = {"cancelado":
                              lambda: c.control.debe_cortar(agente_id)}
                if en_vivo:
                    _ot, _orz = _mk_callbacks(c, agente_id,
                                              lambda: _fin["intentos"])
                    opcionales["on_token"] = _ot
                    opcionales["on_reasoning"] = _orz

            _fin["intentos"] += 1
            resp, descartados = _llamar(
                fn, mensajes, rf, opcionales, url=url_efectiva,
                temperature=sampling["temperature"],
                top_p=sampling["top_p"], max_tokens=max_tokens,
                razonador=True, via=via)
            if "cancelado" in descartados and c.control.marcar_degradado():
                # UNA vez por corrida. El agente sigue siendo cancelable en los
                # checkpoints B/D/E, con granularidad de UNA llamada al LLM
                # (minutos, no milisegundos). Eso se declara, no se esconde.
                motivo_deg = ("completar() de este caller no acepta "
                              "'cancelado': el corte solo llega ENTRE "
                              "llamadas, no durante")
                _emitir(ux.Degradado(
                    donde="workflows._llamar", motivo=motivo_deg,
                    accion_sugerida="usar cognia.agent.chat_client.completar"))
                c._journal({"tipo": "degradado", "donde": "_llamar",
                            "agente_id": agente_id, "motivo": motivo_deg,
                            "ts": time.time()})
            # El usage se registra SIEMPRE que hubo respuesta del server, aunque
            # el parseo/validacion falle despues: esos tokens ya se pagaron.
            usage_resp = getattr(resp, "usage", None) or {}
            # `usage_estimado` viaja al presupuesto (defecto #5): los tokens de
            # un corte se COBRAN —se pagaron— pero se cuentan aparte para que
            # el cierre pueda decir cuanto del gasto es medido y cuanto no.
            est_resp = bool(getattr(resp, "usage_estimado", False))
            via_resp = str(getattr(resp, "usage_via", "") or "")
            if c.presupuesto:
                c.presupuesto.registrar(usage_resp, estimado=est_resp)
            # ACUMULADO, no el usage del ultimo intento: un agente que
            # reintento por schema y fallo declaraba la mitad de lo que costo.
            # Se cuenta aunque no haya presupuesto: el panel muestra el coste
            # REAL, no el presupuestado.
            _fin["tokens"] += (int(usage_resp.get("prompt_tokens") or 0)
                               + int(usage_resp.get("completion_tokens") or 0))

            # --- checkpoint D: volvio CORTADA. Clasificar la causa ---------
            # Nada de "cortado sin causa": si el control no sabe por que se
            # corto, es un bug del control y tiene que verse.
            if getattr(resp, "cortado", False):
                with c.control.lock:
                    por_cancelacion = c.control.esta_cancelado(agente_id)
                    hay_mensaje = c.control.pendientes(agente_id) > 0
                causa = ("cancelacion" if por_cancelacion
                         else "mensaje" if hay_mensaje else "sin_causa")
                _corte(causa, getattr(resp, "texto", ""), usage_resp,
                       estimado=est_resp, via=via_resp)
                if por_cancelacion:
                    return _cancelado()
                if hay_mensaje:
                    continue        # arriba se drena y se vuelve a preguntar
                return _falla("cortado sin causa registrada (bug del control)",
                              usage=usage_resp, url_j=url_efectiva)

            if getattr(resp, "error", ""):
                # Fallback de plantilla (Cognia ya no es mono-familia): una
                # plantilla que no admite turnos de usuario consecutivos
                # revienta la re-pregunta. Se reintenta UNA sola vez con los
                # turnos FUSIONADOS. Esa llamada cuenta como intento y como
                # presupuesto.
                if dialogo and not fusionar:
                    fusionar = True
                    c._journal({"tipo": "degradado", "donde": "plantilla",
                                "agente_id": agente_id,
                                "motivo": "plantilla sin turnos de usuario "
                                          "consecutivos",
                                "ts": time.time()})
                    mensajes = _armar()
                    base_ultimo = mensajes[-1]["content"]
                    continue
                return _falla(resp.error, usage=usage_resp, url_j=url_efectiva)

            if getattr(resp, "finish_reason", "") == "length":
                # NO reintentar igual-igual: el mismo prompt con el mismo techo
                # trunca igual (la leccion de los 10 bugs de max_tokens). El error
                # lleva los numeros para que el caller suba el presupuesto.
                usados = usage_resp.get("completion_tokens", "?")
                # EL PARCIAL VIAJA EN `_crudo` (2026-08-17). Los tokens YA se
                # cobraron al presupuesto: tirar el texto es pagarlos dos veces.
                # Medido antes del fix: pedir "los numeros del 1 al 400" con
                # max_tokens=1024 devolvia {"_error": ...} SIN _crudo, con 1076
                # tokens cobrados y 23,7 s de pared en la basura — y los numeros
                # del 1 al ~340 estaban generados y completos.
                # Es la MISMA regla que ya cumple el camino de schema no
                # conforme (crudo=texto mas abajo) y la que cumple el adaptador
                # con su consolidado: lo pagado no se borra.
                # SEGURO PARA EL RESUME: la linea de journal que escribe _falla
                # lleva `error` no vacio y NO lleva la clave "resultado", asi
                # que _cargar_cache_de_journal (que exige `not error and
                # "resultado" in d`) jamas sirve un truncado como si estuviese
                # completo. El parcial es para el CALLER de este turno, no para
                # la cache.
                return _falla(f"salida truncada (finish_reason=length): "
                              f"max_tokens={max_tokens}, completion_tokens="
                              f"{usados}; subir max_tokens, no reintentar",
                              crudo=getattr(resp, "texto", "") or "",
                              usage=usage_resp, url_j=url_efectiva)

            texto = getattr(resp, "texto", "") or ""

            if schema is None:
                resultado = texto
            else:
                # --- schema: parsear y validar localmente (red de seguridad
                # aunque el server ya haya forzado gramatica) ---
                try:
                    obj = json.loads(texto)
                    errores = _valida(obj, schema)
                except ValueError as e:
                    errores = [f"JSON invalido: {e}"]
                if errores:
                    detalle = "; ".join(errores)
                    if usados_schema >= reint_schema:
                        return _falla(f"salida no conforme al schema tras "
                                      f"{usados_schema + 1} intento(s): "
                                      f"{detalle}", crudo=texto,
                                      usage=usage_resp, url_j=url_efectiva)
                    usados_schema += 1
                    # Retry con el ERROR REAL en el prompt (patron
                    # structure.py: build_repair_hint): el modelo corrige lo
                    # que el validador vio, no adivina. Se construye sobre
                    # `base_ultimo` (el turno de usuario tal cual salio de
                    # _armar) para no apilar reparaciones ni perder el dialogo.
                    mensajes = mensajes[:-1] + [{
                        "role": "user",
                        "content": base_ultimo + "\n\nSALIDA INVALIDA en el "
                                   f"intento anterior: {detalle}\nRespuesta "
                                   f"cruda: {texto[:500]}\nDevolve SOLO el "
                                   "JSON conforme al schema pedido."}]
                    continue
                resultado = obj

            # --- checkpoint E: COMMIT ATOMICO ------------------------------
            # Sin este handshake pasaria una de dos: decirle() devolveria
            # 'aceptado' por un mensaje que el agente nunca va a leer, o el
            # motor tiraria a la basura una respuesta YA PAGADA por un mensaje
            # que llego 3 ms tarde. Con el, una de las dos cosas pasa y nunca
            # las dos, y la UI se entera por el valor de retorno de decirle().
            comprometido = False
            with c.control.lock:
                if not c.control.debe_cortar(agente_id):
                    c.control.comprometer(agente_id)
                    comprometido = True
            if not comprometido:
                # FUERA del lock: esto hace I/O (journal).
                por_cancelacion = c.control.esta_cancelado(agente_id)
                _corte("cancelacion" if por_cancelacion else "mensaje",
                       texto, usage_resp, estimado=est_resp, via=via_resp)
                if por_cancelacion:
                    return _cancelado()
                continue        # se re-pregunta; el resultado completo se tira
            break

        # Un agente al que se le HABLO no escribe en c.cache y su resultado va
        # al journal bajo "resultado_dialogo" (nombre distinto a proposito):
        # _cargar_cache_de_journal exige la clave "resultado" y por lo tanto no
        # puede recogerlo — cero cambios en el loader. En un resume ese paso se
        # re-paga, que es la respuesta correcta: nadie va a repetir el dialogo.
        # _clave_cache NO se toca: meterle el dialogo cambiaria el hash de
        # TODAS las claves y romperia TODOS los resumes existentes.
        _linea = {"tipo": "agente", "agente_id": agente_id, "clave": clave,
                  "cache_hit": False, "rol": rol, "url": url_efectiva,
                  "usage": usage_resp, "error": None, "ts": time.time()}
        if _fin["repreguntas"]:
            _linea["resultado_dialogo"] = resultado
            _linea["dialogo_n"] = _fin["repreguntas"]
        else:
            _linea["resultado"] = resultado
            c.cache[clave] = resultado
        c._journal(_linea)
        _fin["ok"] = True
        _fin["motivo"] = ""
        _fin["resumen"] = _etiqueta(
            resultado if isinstance(resultado, str)
            else json.dumps(resultado, ensure_ascii=False, default=str), 200)
        return resultado
    except BaseException as exc:
        # El motivo REAL, no el generico (2026-08-17). Antes el _fin inicial
        # decia "el agente termino sin resultado" y NINGUN camino de excepcion
        # lo pisaba: un RuntimeError("backend caido") salia al bus como si el
        # modelo hubiese contestado vacio. Son diagnosticos opuestos —uno se
        # arregla levantando el backend, el otro mirando el prompt— y el evento
        # es la UNICA constancia, porque este camino tampoco dejaba linea de
        # journal. Ahora deja las dos cosas.
        #
        # BaseException y no Exception a proposito: un KeyboardInterrupt o un
        # SystemExit a mitad de una llamada tambien mata al agente, y el panel
        # tiene que poder decir cual fue. El `raise` pelado devuelve la
        # excepcion original al caller con su traceback intacto: aca no se
        # traga nada, solo se anota.
        _fin["ok"] = False
        _fin["motivo"] = f"{type(exc).__name__}: {exc}"
        c._journal({"tipo": "agente", "agente_id": agente_id, "clave": clave,
                    "cache_hit": False,
                    "rol": rol, "url": _fin["url"] or url, "usage": None,
                    "error": _fin["motivo"], "ts": time.time()})
        raise
    finally:
        # El finally es lo que hace cumplir "todo agente que arranca termina":
        # cubre los ocho returns y tambien la excepcion (un TypeError interno
        # de _llamar, un import perezoso roto, KeyboardInterrupt).
        ux.desmarcar_agente(_tok_ctx)
        # --- checkpoint F: el agente MUERE para el control ANTES de emitir
        # AgenteFin. emitir() es sincrono: un suscriptor de AgenteFin que
        # llame decirle(ev.agente_id,…) tiene que recibir 'ya_termino' y no
        # 'aceptado' por un mensaje que nadie va a leer.
        c.control.muere(agente_id)
        # El sello TARDIO se decide Y se emite bajo el MISMO lock que cerrar()
        # usa para publicar _cerrada y emitir WorkflowFin. Sin eso la carrera es
        # real (el huerfano y el cierre corren en hilos distintos): el huerfano
        # leia _cerrada=False, el cierre corria entero y el AgenteFin salia
        # DESPUES del WorkflowFin con tardio=False — justo la sorpresa que hay
        # que evitar. Con el lock, o el Fin entra antes del cierre y cuenta como
        # terminado, o sale despues y sale MARCADO.
        with c._lock_ev:
            c._n_terminados += 1
            if not _fin["ok"]:
                c._n_fallidos += 1
            if _fin["cache_hit"]:
                c._n_hits += 1
            if _fin["cancelado"]:
                c._n_cancelados += 1
            _emitir(ux.AgenteFin(
                run_id=c.run_id, agente_id=agente_id, indice=idx,
                total=int(total or 0), fase=fase, etiqueta=etiqueta,
                duracion_s=time.perf_counter() - _t0, rol=rol,
                tardio=c._cerrada, **_fin))


# ── API PUBLICA DE CONTROL ──────────────────────────────────────────────────
# Las tres funciones que MANDAN devuelven un envelope de FORMA FIJA (las mismas
# seis claves siempre) por la misma razon que ejecutar() del adaptador: un
# envelope de forma variable revienta con KeyError justo en el camino de fallo.
# Y nada devuelve None ni bool pelado: oficina/estado.py::solicitar() devuelve
# False para "no existe", "ya termino" y "accion invalida" a la vez, y ese
# silencio de tres causas es exactamente lo que aca no se repite.

def _envelope(ok: bool, estado: str, agente_id: str = "", run_id: str = "",
              pendientes: int = 0, detalle: str = "", agentes: int = 0,
              corridas: int = 0) -> dict:
    """Las OCHO claves, siempre. Forma fija por la misma razon de siempre.

    TRES CONTADORES Y NO UNO (defecto #4, 2026-08-17). `pendientes` significaba
    tres cosas segun quien contestara —mensajes en cola (decirle), agentes
    vivos (cancelar_corrida(rid)) y corridas alcanzadas (cancelar_corrida(''))—
    asi que una UI que pintara "N mensajes pendientes" mostraba "1 corridas
    alcanzadas". Ahora cada uno tiene su clave y las tres van SIEMPRE:
      pendientes = mensajes encolados para ESE agente
      agentes    = agentes vivos que alcanzo este corte
      corridas   = corridas alcanzadas por el panico global
    Un cero significa "no aplica a esta operacion", y eso es leible; lo que no
    era leible era el mismo entero significando tres cosas."""
    return {"ok": bool(ok), "estado": estado, "agente_id": agente_id,
            "run_id": run_id, "pendientes": int(pendientes),
            "agentes": int(agentes), "corridas": int(corridas),
            "detalle": detalle}


def _run_de(agente_id: str) -> str:
    """agente_id -> run_id, por PREFIJO.

    Es legal porque run_id sale de _nuevo_run_id() = '%Y%m%d-%H%M%S' + '-' +
    slug de [^a-z0-9]+ -> '-', mas el sufijo de des-colision '-2'/'-3': JAMAS
    contiene '#'. Ese invariante lo fija un test. Este modulo es el UNICO
    autorizado a parsear el id; para renderer y remoto/sesiones.py sigue
    siendo OPACO (clave de agrupacion, nunca se descompone). Evita un segundo
    mapa agente_id -> Corrida que habria que purgar a mano."""
    return str(agente_id or "").split("#", 1)[0]


def _detalle_falta(estado: str, run_id: str) -> str:
    if estado == CORRIDA_CERRADA:
        return f"la corrida {run_id} ya cerro"
    return f"no hay ninguna corrida {run_id}"


def cancelar_agente(agente_id: str, motivo: str = "el usuario corto") -> dict:
    """Corta UN agente. Idempotente: la segunda vez vuelve ya_cancelado con
    ok=True. Si el agente ya entrego su resultado (comprometido o terminado)
    vuelve ya_termino con ok=False: no se cancelo nada y hay que decirlo.

    EL ORDEN DE LOS CHECKS ES EL CONTRATO (defecto #3, 2026-08-17). Antes se
    preguntaba esta_cancelado() ANTES del estado del agente, y esa funcion
    ORea el flag global: despues de un cancelar_corrida() era cierta para TODO
    id, incluidos los que ya habian entregado. Resultado medido: un agente en
    estado 'terminado', con su resultado 'LISTO' intacto y cacheado, salia como
    ok=True/'ya_cancelado' — la funcion mentia contra su propio docstring.
    Primero el ESTADO (que es un hecho del agente), despues el corte."""
    agente_id = str(agente_id or "")
    run_id = _run_de(agente_id)
    c, falta = _buscar_corrida(run_id)
    if c is None:
        return _envelope(False, falta, agente_id, run_id, 0,
                         _detalle_falta(falta, run_id))
    st = c.control.estado(agente_id)
    if not st:
        return _envelope(False, DESCONOCIDO_AGENTE, agente_id, run_id, 0,
                         f"la corrida {run_id} no conoce ese agente")
    if st in (EST_COMPROMETIDO, EST_TERMINADO):
        # Ya no corre. Las dos formas de "ya no corre" piden respuestas
        # distintas: al que SE CORTO se le contesta ya_cancelado (el pedido del
        # usuario esta cumplido, ok=True e idempotente), y al que ENTREGO se le
        # contesta ya_termino con ok=False. fue_cortado() y no esta_cancelado()
        # justamente para no confundirlas bajo un panico global.
        if c.control.fue_cortado(agente_id):
            return _envelope(True, YA_CANCELADO, agente_id, run_id, 0,
                             "ya estaba cancelado y ya termino")
        return _envelope(False, YA_TERMINO, agente_id, run_id, 0,
                         "el agente ya entrego su resultado; no se cancelo nada")
    if c.control.esta_cancelado(agente_id):
        return _envelope(True, YA_CANCELADO, agente_id, run_id,
                         c.control.pendientes(agente_id), "ya estaba cancelado",
                         agentes=1)
    c.control.cancelar(agente_id, motivo)
    return _envelope(True, ACEPTADO, agente_id, run_id,
                     c.control.pendientes(agente_id), "", agentes=1)


def cancelar_corrida(run_id: str = "", motivo: str = "el usuario corto") -> dict:
    """Corta TODOS los agentes de una corrida. Con run_id vacio, todas las
    vivas: la firma pedida no puede saber cual cancelar con dos en vuelo, y
    "el panico corta todo" es la semantica correcta de un boton de panico."""
    run_id = str(run_id or "")
    if not run_id:
        with _REG_LOCK:
            vivas = list(_VIVAS.items())
        alcanzadas, agentes = [], 0
        for rid, c in vivas:
            try:
                # vivos() ANTES de cancelar_todo() no cambia nada (el flag no
                # mata a nadie hasta el proximo checkpoint), pero se lee
                # despues para contar lo que el corte alcanzo de verdad.
                c.control.cancelar_todo(motivo)
                alcanzadas.append(rid)
                agentes += c.control.vivos()
            except Exception:
                pass
        if not alcanzadas:
            return _envelope(False, DESCONOCIDO_CORRIDA, "", "", 0,
                             "no hay ninguna corrida viva")
        # `corridas` y no `pendientes` (defecto #4): un panico global no
        # alcanza mensajes, alcanza CORRIDAS.
        return _envelope(True, ACEPTADO, "", "", 0,
                         "corridas alcanzadas: " + ", ".join(alcanzadas),
                         agentes=agentes, corridas=len(alcanzadas))
    c, falta = _buscar_corrida(run_id)
    if c is None:
        return _envelope(False, falta, "", run_id, 0,
                         _detalle_falta(falta, run_id))
    nuevo = c.control.cancelar_todo(motivo)
    return _envelope(True, ACEPTADO if nuevo else YA_CANCELADO, "", run_id, 0,
                     "" if nuevo else "ya estaba cancelado",
                     agentes=c.control.vivos(), corridas=1)


def _mensaje_no_atendido(c, agente_id: str, motivo: str, texto: str) -> None:
    """La constancia de un mensaje que NO se va a leer. UNA sola forma de
    escribirla para los cuatro caminos que descartan (presupuesto agotado,
    tope de repreguntas, agente cancelado y buzon de un agente que se corta
    con mensajes dentro): un journal donde cada caso invente su linea es un
    journal que no se puede consultar."""
    c._journal({"tipo": "mensaje_no_atendido", "agente_id": agente_id,
                "motivo": motivo, "texto": texto, "ts": time.time()})


def _rechazar_mensaje(c, agente_id: str, run_id: str, texto: str,
                      estado: str, detalle: str) -> dict:
    _mensaje_no_atendido(c, agente_id, "agente cancelado", texto)
    return _envelope(False, estado, agente_id, run_id, 0, detalle)


def _decidir_mensaje(agente_id: str, run_id: str, texto: str) -> dict:
    if not texto:
        return _envelope(False, TEXTO_VACIO, agente_id, run_id, 0,
                         "un mensaje vacio no es un mensaje")
    c, falta = _buscar_corrida(run_id)
    if c is None:
        return _envelope(False, falta, agente_id, run_id, 0,
                         _detalle_falta(falta, run_id))
    st = c.control.estado(agente_id)
    if not st:
        return _envelope(False, DESCONOCIDO_AGENTE, agente_id, run_id, 0,
                         f"la corrida {run_id} no conoce ese agente")
    if st in (EST_COMPROMETIDO, EST_TERMINADO):
        # Un mensaje va a UN agente y, si ese agente termino, NO se re-encola
        # a ningun otro: no se le puede hablar "al workflow".
        if c.control.fue_cortado(agente_id):
            return _rechazar_mensaje(c, agente_id, run_id, texto, YA_CANCELADO,
                                     "el agente esta cancelado y ya termino: "
                                     "nadie va a leer el mensaje")
        return _envelope(False, YA_TERMINO, agente_id, run_id, 0,
                         "el agente ya entrego su resultado; no se cancelo nada")
    # CANCELADO Y TODAVIA VIVO (defecto #2, 2026-08-17). Este check no existia:
    # _decidir_mensaje no consultaba el corte, asi que encolaba y devolvia
    # 'aceptado', y despues el checkpoint B de agente() devolvia _cancelado()
    # ANTES de mirar el buzon — el mensaje se evaporaba sin una sola linea de
    # journal, con la UI diciendo "aceptado, 1 pendiente". Los otros dos
    # caminos que descartan mensajes (presupuesto agotado y tope de
    # repreguntas) SI dejan 'mensaje_no_atendido'; este es el tercero.
    # esta_cancelado() y no fue_cortado(): bajo un panico global el agente
    # tampoco va a leer nada, aunque el corte no fuera para el en particular.
    if c.control.esta_cancelado(agente_id):
        return _rechazar_mensaje(c, agente_id, run_id, texto, YA_CANCELADO,
                                 "el agente esta cancelado: no va a leer el "
                                 "mensaje")
    n = c.control.encolar(agente_id, texto)
    if n < 0:
        return _envelope(False, BUZON_LLENO, agente_id, run_id,
                         c.control.pendientes(agente_id),
                         f"{_MAX_BUZON} mensajes sin entregar; el agente no "
                         f"los esta leyendo")
    return _envelope(True, ACEPTADO, agente_id, run_id, n, "")


def decirle(agente_id: str, texto: str) -> dict:
    """"Interrumpir y decir": corta la generacion en curso, apendea el texto
    como turno del usuario y el agente vuelve a llamar al modelo con el
    contexto nuevo. Se tira lo generado y cuesta una llamada mas del
    presupuesto (decision del dueno, 2026-08-17).

    Emite MensajeAlAgente SIEMPRE, tambien cuando RECHAZA: un mensaje
    descartado en silencio es peor que uno rechazado a la vista."""
    agente_id = str(agente_id or "")
    texto = (texto or "").strip()
    run_id = _run_de(agente_id)
    res = _decidir_mensaje(agente_id, run_id, texto)
    _emitir(ux.MensajeAlAgente(run_id=run_id, destino=agente_id, texto=texto,
                               aceptado=res["ok"], estado=res["estado"],
                               pendientes=res["pendientes"]))
    return res


def estado_agente(agente_id: str) -> str:
    """Consulta pura, sin efectos. Devuelve vivo|comprometido|terminado, o uno
    de desconocido_agente|corrida_cerrada|desconocido_corrida."""
    agente_id = str(agente_id or "")
    run_id = _run_de(agente_id)
    c, falta = _buscar_corrida(run_id)
    if c is None:
        return falta
    return c.control.estado(agente_id) or DESCONOCIDO_AGENTE


def corridas_vivas() -> list:
    """El directorio de corridas abiertas, para que un panel pueda ofrecer el
    boton sin haber visto el WorkflowInicio."""
    with _REG_LOCK:
        items = list(_VIVAS.items())
    salida = []
    for rid, c in items:
        try:
            salida.append({"run_id": rid, "nombre": c.nombre,
                           "interactivo": bool(c.interactivo),
                           "agentes_vivos": c.control.vivos()})
        except Exception:
            pass
    return salida


def paralelo(thunks: list, cap: int = 2, timeout_s: float = 900) -> list:
    """Corre thunks (callables sin args) en un pool de cap hilos y devuelve
    los resultados EN ORDEN; un thunk que lanza o agota el timeout vale None.

    cap default 2: la fisica medida de esta maquina — un slot de GPU
    serializa, 2-3 hilos solo solapan I/O o cerebro+worker; mas es mentira.
    timeout_s generoso POR future (bajo contencion la pared medida llego a
    35x el computo). Un timeout no mata el hilo (limitacion de threads en
    Python): el thunk colgado queda como hilo HUERFANO VIVO hasta que termine
    solo — paralelo() retorna igual (shutdown con wait=False, 2026-08-11) y
    el huerfano puede seguir gastando backend/VRAM en segundo plano. Si el
    huerfano escribe al journal de una corrida ya cerrada, _journal lo traga
    con aviso a stderr: no rompe nada."""
    resultados: list = []
    # SIN 'with': el __exit__ del context manager hace shutdown(wait=True) y
    # eso ESPERABA al thunk colgado — el timeout era cosmetico (la pared real
    # era la del thunk, cazado 2026-08-11). El executor se cierra a mano con
    # wait=False para devolver el control apenas se decidio cada resultado.
    ex = ThreadPoolExecutor(max_workers=max(int(cap), 1))
    try:
        futuros = [ex.submit(t) for t in thunks]
        for i, fut in enumerate(futuros):
            try:
                resultados.append(fut.result(timeout=timeout_s))
            except Exception as e:
                print(f"aviso: thunk {i} fallo ({type(e).__name__}: {e}); "
                      f"resultado None", file=sys.stderr)
                resultados.append(None)
    finally:
        # cancel_futures: lo que no arranco no arranca (un thunk colgado no
        # tiene licencia para encolar mas trabajo). Lo que YA corre queda
        # huerfano vivo (ver docstring).
        ex.shutdown(wait=False, cancel_futures=True)
    return resultados


def paralelo_env(thunks: list, cap: int = 2, timeout_s: float = 900):
    """Como `paralelo()`, pero un fallo VUELVE con su causa en vez de `None`.

    Existe porque el `None` de `paralelo()` significa dos cosas a la vez —
    "reventó" y "corrió bien y no había nada"— y las dos piden decisiones
    OPUESTAS: la primera hay que re-despacharla, la segunda es información.
    En un workflow con 12 ramas, una caída silenciosa se lee como "esa rama
    no tenía nada que aportar" y la síntesis final concluye sobre un hueco.

    Devuelve un `cognia.search.fanout.Lote`: sobres en ORDEN DE ENTRADA, con
    `.ok`, `.fallidos`, `.resumen()` y `.volcar()` para dejar rastro en disco.

    `paralelo()` NO se toca: tiene llamadores cuyo contrato es el `None`.
    Cambiarlo por debajo sería arreglar un fallo silencioso creando otro.
    """
    from cognia.search.fanout import en_paralelo
    # Los thunks no llevan spec propio: el índice ES la identidad, y por eso
    # el orden de entrada no es un detalle estético sino la única forma de
    # saber qué rama falló.
    return en_paralelo(list(range(len(thunks))),
                       lambda i: thunks[i](), cap=cap, timeout_s=timeout_s)


def pipeline(items: list, *etapas, cap: int = 2) -> list:
    """Cada item atraviesa TODAS las etapas SIN barrera entre items: un item
    puede ir por la etapa 2 mientras otro sigue en la 1 (un future por item
    que encadena las etapas — la ausencia de barrera sale gratis de ahi).
    Etapa que lanza -> ese item queda None y no sigue; los demas continuan."""
    def _correr(item):
        valor = item
        for etapa in etapas:
            valor = etapa(valor)
        return valor

    resultados: list = []
    with ThreadPoolExecutor(max_workers=max(int(cap), 1)) as ex:
        futuros = [ex.submit(_correr, it) for it in items]
        for i, fut in enumerate(futuros):
            try:
                resultados.append(fut.result())
            except Exception as e:
                print(f"aviso: item {i} fallo en una etapa "
                      f"({type(e).__name__}: {e}); resultado None",
                      file=sys.stderr)
                resultados.append(None)
    return resultados


# ── Crítica adversarial ──────────────────────────────────────────────────────
# Un workflow que solo GENERA no se entera de sus errores. Esta sección es la
# otra mitad: lanzar críticos cuyo encargo es TUMBAR la entrega, y decidir por
# voto. Añadido 2026-08-15 tras ver que el patrón (fan-out → síntesis →
# refutación) cazó 8 defectos MORTALES en un plan que sus propios autores
# daban por bueno — entre ellos un paso de medición físicamente imposible y
# una regla estadística que se contradecía a sí misma.

# Cada lente es un ÁNGULO DISTINTO, no una repetición. Tres críticos idénticos
# encuentran casi lo mismo tres veces; tres lentes distintas encuentran cosas
# que la otra no puede ver por construcción. El reparto está copiado de lo que
# de hecho funcionó: aritmética / evidencia / encargo.
LENTES_POR_DEFECTO = (
    ("aritmetica",
     "Rehaz TODAS las cuentas TÚ MISMO, no las revises: recalcula desde los "
     "datos de origen y compara. Una sola celda mal invalida la tabla."),
    ("evidencia",
     "Comprueba que cada afirmación trae evidencia CITABLE (URL, ruta:línea, "
     "salida literal de un comando). Lo que solo esté razonado, márcalo como "
     "no respaldado — por convincente que suene."),
    ("encargo",
     "Comprueba que esto responde a lo que se PIDIÓ y no a una versión más "
     "cómoda del problema. Busca el requisito que se reinterpretó por el "
     "camino, o el que se cumplió solo de nombre."),
)

VEREDICTO_SCHEMA = {
    "type": "object",
    "required": ["refutado", "motivo"],
    "properties": {
        "refutado": {
            "type": "boolean",
            "description": "true si encontraste un defecto que INVALIDA la entrega",
        },
        "motivo": {"type": "string"},
        "defectos": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["defecto", "gravedad"],
                "properties": {
                    "defecto": {"type": "string"},
                    "gravedad": {
                        "type": "string",
                        "enum": ["MATA", "SESGA", "MENOR"],
                    },
                    "arreglo": {"type": "string"},
                },
            },
        },
    },
}

_PROMPT_CRITICO = """\
Eres el crítico «{lente}». Tu encargo NO es evaluar: es REFUTAR.

{encargo}

Por defecto, DUDA. Si no puedes confirmar algo con evidencia citable, trátalo
como no respaldado en vez de darlo por bueno. Un PARCIAL honesto vale más que
un visto bueno complaciente.

Si de verdad no encuentras nada que invalide la entrega, dilo (refutado=false)
y explica qué comprobaste — pero no inventes un defecto para tener algo que
decir: un defecto falso cuesta más que ninguno.

SÉ BREVE. `motivo` en 3 líneas como mucho; cada `defecto`, en una. No pienses
en voz alta ni explores alternativas: emite el objeto JSON y para. (Medido
2026-08-15: los críticos que divagan agotan el techo de tokens sea cual sea —
1536 o 4096— y su voto se pierde entero.)
{contexto}
ENTREGA A REFUTAR:
{afirmacion}"""


def contar_votos(veredictos: list, n_lanzados: int) -> dict:
    """Decide por voto, contando también a los que NO contestaron.

    Función PURA a propósito: la regla de decisión se puede testear sin
    encender un modelo, que es justo lo que hace falta para confiar en ella.

    El QUÓRUM es la parte que no se puede omitir. Si lanzas 3 críticos y 2
    revientan, el único que sobrevivió NO es "1 voto a favor": es una muestra
    de tamaño 1 disfrazada de consenso. Esa confusión —"falló" leído como "no
    había nada"— es el fallo silencioso que este repo ya documentó en fan-out,
    y aquí volvería a entrar por la puerta de atrás si el conteo mirase solo a
    los que respondieron.
    """
    n_lanzados = max(int(n_lanzados), 0)
    respondieron = len(veredictos)
    quorum = (n_lanzados + 1) // 2          # mayoría de los LANZADOS

    refutan = [v for v in veredictos if v.get("refutado")]
    mortales = [d for v in veredictos for d in (v.get("defectos") or [])
                if d.get("gravedad") == "MATA"]

    if respondieron < max(quorum, 1):
        veredicto = "INDETERMINADO"
    elif mortales or len(refutan) * 2 > respondieron:
        veredicto = "REFUTADO"
    else:
        veredicto = "SOBREVIVE"

    return {
        "veredicto": veredicto,
        "lanzados": n_lanzados,
        "respondieron": respondieron,
        "refutan": len(refutan),
        "mortales": mortales,
        "defectos": [d for v in veredictos for d in (v.get("defectos") or [])],
        "motivos": [v.get("motivo", "") for v in veredictos],
    }


# MEDIDO 2026-08-15 contra Qwythos-9B en :8080, y el resultado NO es el que
# parecia. Con max_tokens=1536 dos de tres criticos murieron con
# finish_reason='length'. Se subio a 4096 y murieron los MISMOS dos, otra vez
# al tope exacto:
#     1536 -> completion 1536 / 1359 / 1536   (1 de 3 responde)
#     4096 -> completion 1078 / 4096 / 4096   (1 de 3 responde)
# El que responde gasta ~1.100-1.360. Los que fallan consumen TODO lo que se
# les de: no les falta presupuesto, entran en bucle de razonamiento. Subir el
# techo solo hace la factura mas cara con el mismo resultado — por eso este
# numero es 3072 (2,3x lo que de hecho basta) y no 8192, y por eso el arreglo
# de verdad esta en el prompt: pedir brevedad y prohibir pensar en voz alta.
TOKENS_CRITICO = 3072


def criticar(c: Corrida, afirmacion: str, *, contexto: str = "",
             lentes=None, cap: int = 2, rol: str = "", url: str = "",
             max_tokens: int = TOKENS_CRITICO, completar_fn=None) -> dict:
    """Lanza un crítico por lente, en paralelo, y devuelve el veredicto votado.

    Uso típico al final de un workflow, sobre lo que se va a entregar:

        entrega = agente(c, "escribe el plan...")
        juicio  = criticar(c, entrega, contexto="Objetivo: " + tarea)
        if juicio["veredicto"] == "REFUTADO":
            entrega = agente(c, f"corrige esto: {juicio['defectos']}...")

    Va por `paralelo_env` y no por `paralelo` a propósito: un crítico que se
    cayó y un crítico que no encontró nada piden decisiones OPUESTAS, y con
    `None` para ambos el segundo caso se traga al primero. `contar_votos` los
    distingue porque recibe los dos números (lanzados y respondidos).
    """
    lentes = tuple(lentes or LENTES_POR_DEFECTO)
    if not lentes:
        return contar_votos([], 0)

    ctx = f"\n{contexto.strip()}\n" if contexto and contexto.strip() else "\n"

    # La identidad la pone quien CONSTRUYE los thunks: `paralelo_env` recibe
    # callables opacos y no tiene forma de saber que es cada uno.
    def _mk(i: int, lente: str, encargo: str):
        def _thunk():
            return agente(c,
                          _PROMPT_CRITICO.format(lente=lente, encargo=encargo,
                                                 contexto=ctx,
                                                 afirmacion=afirmacion),
                          VEREDICTO_SCHEMA, rol=rol, url=url,
                          max_tokens=max_tokens, via="wf_critico",
                          completar_fn=completar_fn,
                          indice=i, total=len(lentes), fase="critica",
                          etiqueta=f"critico {lente}")
        return _thunk

    lote = paralelo_env([_mk(i, n, e) for i, (n, e) in enumerate(lentes, 1)],
                        cap=cap)

    # Un `agente()` con `_error` NO es un voto: devolvió, pero no juzgó. Se
    # descarta del recuento y por eso `lanzados` sigue siendo len(lentes) —
    # así el quórum lo ve.
    veredictos = [v for v in lote.valores
                  if isinstance(v, dict) and "_error" not in v]

    resultado = contar_votos(veredictos, len(lentes))
    resultado["lentes"] = [n for n, _ in lentes]
    resultado["fanout"] = lote.resumen()
    c._journal({"tipo": "critica", "lentes": resultado["lentes"],
                "veredicto": resultado["veredicto"],
                "respondieron": resultado["respondieron"],
                "refutan": resultado["refutan"],
                "fanout": resultado["fanout"], "ts": time.time()})
    return resultado
