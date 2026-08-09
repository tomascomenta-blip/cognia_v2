"""
cognia/ux/events.py
===================
El embudo UNICO de eventos del turno (2026-08-09).

POR QUE EXISTE: Cognia tenia CUATRO canales de salida sin coordinar
(_print_line/rich, logger a stderr, prints crudos [degradado]/[backend], y
prints sueltos de tools/modulos). El CLI mezclaba todo en pantalla y el remoto
lo re-clasificaba por regex sobre stdout — cualquier limpieza del CLI rompia
el movil. Este modulo invierte la dependencia: el loop del agente y el
fast-path EMITEN eventos tipados; quien decide que se ve es el consumidor
(renderer del CLI, sink JSONL para el remoto, nada para tests).

Contrato (acordado entre WP1/WP3/WP4 de la obra 2026-08-09):

- Los productores llaman ``emitir(<Evento>)`` y NUNCA imprimen directo.
- ``emitir`` es NO-LANZANTE por contrato: un suscriptor roto no puede romper
  un turno (misma regla que ux/estilo.py: el adorno jamas re-ejecuta ni
  aborta la sustancia).
- Los consumidores se registran con ``suscribir(fn)``; reciben el dataclass.
- El remoto consume el mismo bus via ``activar_sink_jsonl()`` (una linea JSON
  por evento) — mismo bus, otro sink; jamas volver al regex sobre stdout.

Solo stdlib. Sin dependencias de rich ni del CLI: este modulo esta DEBAJO de
todos y no importa nada de cognia (evita ciclos de import con cli.py).
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Los eventos del turno. Pocos y estables: agregar uno es tocar el contrato
# (avisar en el docstring y a los consumidores), no un cajon de sastre.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Evento:
    """Base: todos llevan timestamp; el tipo va implicito en la clase."""
    ts: float = field(default_factory=time.time, init=False)


@dataclass(frozen=True)
class TareaInicio(Evento):
    """Arranca una tarea del agente (/hacer) o un turno de chat."""
    tarea: str = ""
    modo: str = "agente"        # "agente" | "chat"
    modelo: str = ""            # el GGUF/alias que va a responder de verdad


@dataclass(frozen=True)
class PasoIntencion(Evento):
    """El agente decidio que va a hacer en este paso (1 linea legible)."""
    paso: int = 0
    intencion: str = ""         # p.ej. "Voy a leer motor.py para ver la firma"


@dataclass(frozen=True)
class ToolInicio(Evento):
    tool: str = ""
    args: str = ""              # forma corta legible (ruta, comando…)
    paso: int = 0


@dataclass(frozen=True)
class ToolFin(Evento):
    tool: str = ""
    args: str = ""
    ok: bool = True
    resumen: str = ""           # 1-3 lineas: "42 lineas", "exit 0", diff corto
    duracion_s: float = 0.0
    paso: int = 0


@dataclass(frozen=True)
class TokenTexto(Evento):
    """Trozo de la respuesta final en streaming (prosa del asistente)."""
    texto: str = ""


@dataclass(frozen=True)
class RazonamientoTick(Evento):
    """El modelo esta pensando (reasoning_content fluyendo): alimenta el
    indicador 'pensando… (Ns)'. chars acumulados, no el contenido entero."""
    chars: int = 0
    fragmento: str = ""         # ultimo trozo, por si el renderer lo muestra


@dataclass(frozen=True)
class Aviso(Evento):
    """Algo que el usuario deberia poder ver pero no rompe el turno."""
    texto: str = ""
    origen: str = ""            # modulo que lo emite, p.ej. "llama_backend"


@dataclass(frozen=True)
class Degradado(Evento):
    """Una via se degrado (backend caido, fallback a modelo menor…).
    SIEMPRE va tambien a telemetria: la degradacion silenciosa es el modo de
    fallo historico de Cognia."""
    donde: str = ""
    motivo: str = ""
    accion_sugerida: str = ""   # p.ej. "python scripts/servir_flota.py pensar"


@dataclass(frozen=True)
class TareaFin(Evento):
    ok: bool = True
    resumen: str = ""           # la respuesta final o el motivo del fallo
    pasos: int = 0
    tokens_predichos: int = 0   # usage REAL del backend, no len//4
    duracion_s: float = 0.0


# ---------------------------------------------------------------------------
# El bus: modulo-global, thread-safe, no-lanzante.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_suscriptores: list[Callable[[Evento], None]] = []


def suscribir(fn: Callable[[Evento], None]) -> None:
    with _lock:
        if fn not in _suscriptores:
            _suscriptores.append(fn)


def desuscribir(fn: Callable[[Evento], None]) -> None:
    with _lock:
        if fn in _suscriptores:
            _suscriptores.remove(fn)


def emitir(evento: Evento) -> None:
    """Reparte el evento a todos los suscriptores. Nunca lanza: un consumidor
    roto se ignora (el turno del usuario vale mas que el adorno)."""
    with _lock:
        actuales = list(_suscriptores)
    for fn in actuales:
        try:
            fn(evento)
        except Exception:
            pass


def a_dict(evento: Evento) -> dict:
    """Serializa un evento a dict plano con su tipo, listo para JSON."""
    d = dataclasses.asdict(evento)
    d["tipo"] = type(evento).__name__
    return d


# ---------------------------------------------------------------------------
# Sink JSONL (el canal del remoto y de la telemetria de sesion).
# ---------------------------------------------------------------------------

_sink_jsonl: Optional[object] = None


def activar_sink_jsonl(ruta: str = "") -> None:
    """Suscribe un sink que escribe una linea JSON por evento. Con ruta vacia
    usa COGNIA_EVENTS_JSONL (ruta de archivo) o stdout-linea si vale '1'
    (el remoto lanza el proceso con esto y consume el stream tipado)."""
    global _sink_jsonl
    if _sink_jsonl is not None:
        return
    destino = ruta or os.environ.get("COGNIA_EVENTS_JSONL", "")
    if not destino:
        return

    if destino == "1":
        def _escribir(linea: str) -> None:
            print(linea, flush=True)
    else:
        f = open(destino, "a", encoding="utf-8")

        def _escribir(linea: str) -> None:
            f.write(linea + "\n")
            f.flush()

    def _sink(evento: Evento) -> None:
        _escribir(json.dumps(a_dict(evento), ensure_ascii=False))

    _sink_jsonl = _sink
    suscribir(_sink)
