# -*- coding: utf-8 -*-
"""Fan-out con ENVELOPE: el fallo viaja con el resultado.

POR QUE EXISTE. `workflows.paralelo()` devuelve `None` cuando un thunk
revienta. Ese `None` es indistinguible de "la consulta corrio bien y no
encontro nada", y las dos cosas piden decisiones OPUESTAS: la primera hay que
re-despacharla, la segunda es informacion. Con 12 consultas en vuelo, una
caida silenciosa se lee como "el tema no existe" — el modo de fallo caro de
la casa, y el mismo que la documentacion del SDK de Perplexity nombra:
*"a silently failed query looks identical to a query with no results"*.

DOS REGLAS que se copian a proposito del diseño ajeno porque estan bien:

1. **Un fallo nunca tumba el lote.** `en_paralelo` no relanza NUNCA: devuelve
   un sobre por spec, en el ORDEN de entrada.
2. **Cero reintentos en la primitiva.** Reintentar aca esconde la tasa de
   error real y multiplica la carga contra un buscador que banea por
   frecuencia. El backoff es decision del llamador, que ve los sobres
   fallidos y decide (`redespachar()` baja la concurrencia y reintenta SOLO
   esos specs, una vez).

NO reemplaza a `workflows.paralelo()`: aquel tiene llamadores y su contrato
de `None` esta cableado. Este es el camino nuevo.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

# 5 y no 12: el limite de aca no es el dinero (Perplexity cobra por consulta)
# sino el BANEO. ddgs corta por frecuencia y el castigo dura horas, asi que la
# concurrencia por defecto es la que aguanta el buscador gratuito, no la que
# aguanta la maquina.
CONCURRENCIA_DEFECTO = 5
TIMEOUT_DEFECTO_S = 120.0


@dataclass
class Sobre:
    """El resultado de UNA unidad de trabajo, exitosa o no.

    `ok=False` con `error` poblado es un resultado legitimo del lote: se
    persiste, se cuenta y se puede re-despachar. Nunca es un hueco.
    """
    spec: Any
    ok: bool
    valor: Any = None
    error: str = ""
    tipo_error: str = ""
    segundos: float = 0.0
    indice: int = -1

    def como_dict(self) -> dict:
        d = asdict(self)
        # El spec puede ser cualquier cosa; para el jsonl vale su repr.
        if not isinstance(d["spec"], (str, int, float, bool, list, dict,
                                      type(None))):
            d["spec"] = repr(d["spec"])
        return d


@dataclass
class Lote:
    """Los sobres de una corrida, con las cuentas ya hechas.

    Que las cuentas vengan hechas no es comodidad: es que nadie pueda
    reportar "12 resultados" cuando 4 fueron errores.
    """
    sobres: list = field(default_factory=list)

    @property
    def ok(self) -> list:
        return [s for s in self.sobres if s.ok]

    @property
    def fallidos(self) -> list:
        return [s for s in self.sobres if not s.ok]

    @property
    def valores(self) -> list:
        """Solo los valores de los sobres OK. Usalo cuando ya miraste los
        fallidos; si lo usas sin mirarlos, volviste al agujero de antes."""
        return [s.valor for s in self.ok]

    def resumen(self) -> str:
        n, malos = len(self.sobres), len(self.fallidos)
        if not malos:
            return f"{n}/{n} ok"
        tipos: dict = {}
        for s in self.fallidos:
            tipos[s.tipo_error] = tipos.get(s.tipo_error, 0) + 1
        detalle = ", ".join(f"{k}×{v}" for k, v in sorted(tipos.items()))
        return f"{n - malos}/{n} ok, {malos} fallidos ({detalle})"

    def volcar(self, ruta) -> Path:
        """Persiste TODOS los sobres (ok y fallidos) como jsonl.

        Los errores van al MISMO archivo y no a un `errores.jsonl` aparte: un
        segundo archivo se olvida de mirar, y el punto entero de esto es que
        el fallo no se pueda perder de vista.
        """
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fh:
            for s in self.sobres:
                fh.write(json.dumps(s.como_dict(), ensure_ascii=False,
                                    default=repr) + "\n")
        return ruta


def en_paralelo(specs: list, trabajo: Callable, cap: int = CONCURRENCIA_DEFECTO,
                timeout_s: float = TIMEOUT_DEFECTO_S) -> Lote:
    """Corre `trabajo(spec)` para cada spec y devuelve un Lote de sobres.

    Nunca lanza. El orden de salida es el de ENTRADA (no el de terminación):
    sin eso, cruzar los resultados con sus specs obliga a etiquetar a mano y
    ahí es donde se traspapelan.
    """
    if not specs:
        return Lote(sobres=[])
    cap = max(1, min(int(cap), len(specs)))
    sobres: list = [None] * len(specs)

    def _uno(i: int, spec: Any) -> Sobre:
        t0 = time.time()
        try:
            valor = trabajo(spec)
            return Sobre(spec=spec, ok=True, valor=valor, indice=i,
                         segundos=round(time.time() - t0, 2))
        except Exception as exc:
            return Sobre(spec=spec, ok=False, indice=i,
                         error=f"{type(exc).__name__}: {exc}"[:500],
                         tipo_error=type(exc).__name__,
                         segundos=round(time.time() - t0, 2))

    # DEADLINE DEL LOTE, no timeout por futuro. `fut.result(timeout=X)` en un
    # bucle reinicia el reloj en cada iteracion: con N specs colgados la pared
    # es N x X, no X (medido: 6 specs a timeout_s=1 tardaban 6,03 s). Eso
    # rompia justo el contrato de `search.contexto`, que declara el
    # presupuesto en SEGUNDOS DE PARED -- un `responder(presupuesto_s=120)`
    # podia irse a media hora esperando URLs colgadas de a una.
    deadline = time.monotonic() + timeout_s
    ex = ThreadPoolExecutor(max_workers=cap)
    try:
        futuros = {ex.submit(_uno, i, s): i for i, s in enumerate(specs)}
        for fut, i in futuros.items():
            restante = deadline - time.monotonic()
            try:
                if restante <= 0:
                    raise TimeoutError(
                        f"deadline del lote agotado ({timeout_s:.0f}s)")
                sobres[i] = fut.result(timeout=restante)
            except Exception as exc:
                # El timeout NO mata el hilo (limitacion de threads en
                # Python): el trabajo colgado sigue vivo de fondo. Lo que
                # importa aca es que el LOTE no se queda esperando y que el
                # spec queda marcado como fallido, no como vacio.
                sobres[i] = Sobre(spec=specs[i], ok=False, indice=i,
                                  error=f"{type(exc).__name__}: {exc}"[:500],
                                  tipo_error="Timeout", segundos=timeout_s)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return Lote(sobres=list(sobres))


def redespachar(lote: Lote, trabajo: Callable, cap: int = 2,
                timeout_s: float = TIMEOUT_DEFECTO_S) -> Lote:
    """Reintenta UNA vez, y solo los specs que fallaron, con menos presion.

    Vive aparte de `en_paralelo` a proposito: mezclarlos volveria invisible
    la tasa de error de la primera pasada, que es justo el numero que hay que
    poder mirar. Los sobres reintentados quedan marcados en `tipo_error` para
    que el informe pueda decir cuantos se recuperaron.
    """
    malos = lote.fallidos
    if not malos:
        return lote
    nuevo = en_paralelo([s.spec for s in malos], trabajo, cap=cap,
                        timeout_s=timeout_s)
    sobres = list(lote.sobres)
    for viejo, fresco in zip(malos, nuevo.sobres):
        fresco.indice = viejo.indice
        if fresco.ok:
            fresco.tipo_error = "recuperado_en_reintento"
        sobres[viejo.indice] = fresco
    return Lote(sobres=sobres)


def reconstruibles(ruta) -> dict:
    """Cuenta, LEYENDO EL ARCHIVO, cuántos fallos quedaron reconstruibles.

    Es el verificador de la métrica primaria de esta pieza: con el fan-out
    viejo el número es 0 (los fallos se volvían `None` y no se persistía
    nada). Se mide sobre el archivo y no sobre el objeto en memoria porque lo
    que importa es lo que sobrevive a la corrida.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return {"total": 0, "fallidos": 0, "con_causa": 0, "fraccion": 0.0}
    total = fallidos = con_causa = 0
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            d = json.loads(linea)
        except Exception:
            continue
        total += 1
        if not d.get("ok"):
            fallidos += 1
            if d.get("error") and d.get("spec") is not None:
                con_causa += 1
    return {"total": total, "fallidos": fallidos, "con_causa": con_causa,
            "fraccion": (con_causa / fallidos) if fallidos else 1.0}


def buscar_many(consultas: list, por_consulta: int = 8,
                cap: int = CONCURRENCIA_DEFECTO, buscador=None) -> Lote:
    """Fan-out de consultas al buscador, con envelope.

    `buscador` inyectable (firma `(consulta, max_candidatos) -> list`) para
    poder medir esto sin red: el banco de fallos usa uno falso.
    """
    if buscador is None:
        from cognia.knowledge.navegador import _buscar_ddg as buscador
    return en_paralelo(list(consultas),
                       lambda q: buscador(q, por_consulta), cap=cap)
