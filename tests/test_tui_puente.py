"""
test_tui_puente.py -- El puente del bus de eventos a Textual (cognia/tui/puente.py).

QUE SE VERIFICA (y por que cada cosa es un test y no una promesa del docstring):

1. RECONSTRUCCION BYTE A BYTE bajo concurrencia real: 4 hilos emitiendo 400
   TokenTexto cada uno contra una App de Textual VIVA (app.run_test()), y los 4
   streams tienen que salir identicos y SIN cruzarse. Es la prueba de que el
   ContextVar de events.py sella bien el agente_id y de que el puente no mezcla
   colas: si el merge por seq estuviera mal, un AgenteFin se aplicaria antes que
   sus tokens y el agente aparecerira cerrado escribiendo.
2. EL EMISOR NO SE BLOQUEA NI SE ROMPE: emitir() corre en el hilo del motor.
   Se mide el peor emitir() de cada hilo y se comprueba que una App rota
   (post_message que lanza) no propaga la excepcion al emisor.
3. EL DESCARTE SE VE: con la cola llena hay que poder decir CUANTO se perdio,
   DE QUIEN, y que ese texto ya no esta completo. Un evento perdido en silencio
   es el bug que este repo persigue.
4. ENCHUFAR DOS VECES NO DUPLICA: abrir la vista de agentes dos veces no puede
   dejar dos suscriptores (cada evento aplicado dos veces).

El arnes es app.run_test() (headless de verdad), el mismo que ya usan
test_tui_foundation.py y compania.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import threading
import time

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from cognia.tui import puente as mod_puente
from cognia.tui.puente import PuenteBus, conectar_puente, desconectar_puente
from cognia.ux import events


class AppJuguete(App):
    """App minima: el puente NO conoce widgets, asi que esta alcanza."""

    def compose(self) -> ComposeResult:
        yield Static("puente")


@pytest.fixture
def bus_limpio():
    """El bus y el puente son modulo-globales: se guardan y se restauran."""
    mod_puente.desconectar_puente()
    with events._lock:
        previos = list(events._suscriptores)
        events._suscriptores.clear()
    sink_previo = events._sink_jsonl
    events._sink_jsonl = None
    try:
        yield
    finally:
        mod_puente.desconectar_puente()
        with events._lock:
            events._suscriptores.clear()
            events._suscriptores.extend(previos)
        events._sink_jsonl = sink_previo


def _emitir_agente(k: int, n: int, run_id: str, peores: list,
                   barrera: threading.Barrier) -> None:
    """Un 'agente' completo desde SU hilo: inicio, n tokens, fin."""
    aid = f"{run_id}#pasos.{k + 1}@{k + 1}"
    tok = events.marcar_agente(aid)      # lo que hace workflows.agente()
    try:
        barrera.wait(timeout=10)
        events.emitir(events.AgenteInicio(
            run_id=run_id, agente_id=aid, indice=k + 1, total=4,
            fase="pasos", etiqueta=f"lente {k}"))
        peor = 0.0
        for i in range(n):
            t0 = time.perf_counter()
            events.emitir(events.TokenTexto(texto=f"[{k}:{i}]"))
            peor = max(peor, time.perf_counter() - t0)
        events.emitir(events.AgenteFin(
            run_id=run_id, agente_id=aid, indice=k + 1, total=4,
            fase="pasos", etiqueta=f"lente {k}", ok=True,
            tokens=100 + k, intentos=1, duracion_s=1.5))
        peores.append(peor)
    finally:
        events.desmarcar_agente(tok)


def _texto_esperado(k: int, n: int) -> str:
    return "".join(f"[{k}:{i}]" for i in range(n))


# ---------------------------------------------------------------------------
# 1. La prueba grande: 4 hilos x 400 eventos contra una App viva.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cuatro_hilos_reconstruyen_los_streams_byte_a_byte(bus_limpio, capsys):
    N_AGENTES, N_EVENTOS = 4, 400
    RUN = "run-concurrente"

    app = AppJuguete()
    async with app.run_test() as pilot:
        ident_ui = threading.get_ident()
        cambios = []
        p = conectar_puente(app)
        p.al_cambiar(lambda est: cambios.append(threading.get_ident()))

        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="concurrencia", total_agentes=N_AGENTES))

        peores: list = []
        barrera = threading.Barrier(N_AGENTES)
        hilos = [threading.Thread(target=_emitir_agente,
                                  args=(k, N_EVENTOS, RUN, peores, barrera),
                                  name=f"emisor-{k}")
                 for k in range(N_AGENTES)]
        t0 = time.perf_counter()
        for h in hilos:
            h.start()

        # La UI SIGUE VIVA mientras los hilos producen: los drenajes se
        # intercalan con la emision (que es el caso real, no un volcado final).
        for _ in range(4000):
            await pilot.pause()
            await asyncio.sleep(0.001)
            if not any(h.is_alive() for h in hilos) and p.pendientes == 0:
                break
        for h in hilos:
            h.join(timeout=10)
            assert not h.is_alive(), "un hilo emisor quedo colgado"
        for _ in range(200):
            if p.pendientes == 0:
                break
            await pilot.pause()
        p.drenar(10 ** 6)        # por si quedo algo tras el ultimo post
        pared = time.perf_counter() - t0

        events.emitir(events.WorkflowFin(
            run_id=RUN, nombre="concurrencia", ok=True, agentes=N_AGENTES,
            fallidos=0, tokens=406, duracion_s=pared, total_agentes=N_AGENTES,
            arrancados=N_AGENTES))
        p.drenar(10 ** 6)

        estado = p.estado
        met = p.metricas()

        # --- los 4 streams, byte a byte y sin cruzarse ---------------------
        for k in range(N_AGENTES):
            aid = f"{RUN}#pasos.{k + 1}@{k + 1}"
            a = estado.agente(aid)
            assert a is not None, f"falta el agente {aid}"
            esperado = _texto_esperado(k, N_EVENTOS)
            assert a.texto == esperado, f"stream de {aid} corrupto"
            assert a.chars_texto == len(esperado)
            assert a.completo is True
            assert a.estado == "ok"
            assert a.tokens == 100 + k
            assert a.etiqueta == f"lente {k}"
            # cero contaminacion cruzada (explicito, no solo implicito):
            for j in range(N_AGENTES):
                if j != k:
                    assert f"[{j}:" not in a.texto

        # --- nada se perdio ni se duplico ----------------------------------
        # 1 WorkflowInicio + 4x(1 inicio + 400 tokens + 1 fin) + 1 WorkflowFin
        total_eventos = 1 + N_AGENTES * (N_EVENTOS + 2) + 1
        assert met["encolados"] == total_eventos
        assert estado.aplicados == total_eventos
        assert estado.descartes.total == 0
        assert p.pendientes == 0

        # --- el estado de la corrida ---------------------------------------
        c = estado.corrida(RUN)
        assert c is not None and c.sintetica is False
        assert len(c.agentes_vista) == N_AGENTES
        assert c.vivos == []
        assert c.abierta is False and c.ok is True

        # --- el despertador va coalescido y el drenaje por lotes -----------
        assert met["pasadas"] > 1, "se aplico todo de una: no hubo lotes"
        assert met["wakeups"] < total_eventos, "un wakeup por evento: no coalesce"
        assert met["wakeups_fallidos"] == 0

        # --- el modelo se escribe SOLO en el hilo de la UI -----------------
        assert cambios, "al_cambiar nunca corrio"
        assert set(cambios) == {ident_ui}

        peor_emision = max(peores) if peores else 0.0

    with capsys.disabled():
        print(f"\n  [puente] {total_eventos} eventos / {N_AGENTES} hilos en "
              f"{pared * 1000:.0f} ms de pared")
        print(f"  [puente] peor emitir() de un hilo emisor: "
              f"{peor_emision * 1000:.3f} ms")
        print(f"  [puente] wakeups={met['wakeups']} pasadas={met['pasadas']} "
              f"pico_pendientes={met['pico_pendientes']} descartes=0")

    # El emisor no puede quedarse esperando a la UI. Cota FLOJA a proposito
    # (Windows, GIL, CI cargado): lo que se vigila es un orden de magnitud, no
    # un microbenchmark. call_from_thread aca costaria un round-trip completo.
    assert peor_emision < 0.5


# ---------------------------------------------------------------------------
# 2. La App tarda: la cola se llena y el descarte TIENE que verse.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_lenta_descarta_flujo_y_el_descarte_se_ve(bus_limpio):
    RUN = "run-lenta"
    AID = f"{RUN}#pasos.1@1"
    app = AppJuguete()
    async with app.run_test() as pilot:
        p = conectar_puente(app, cap_cola=32, tope_por_pasada=8)
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="lenta",
                                            total_agentes=1))
        events.emitir(events.AgenteInicio(run_id=RUN, agente_id=AID, indice=1,
                                          total=1, fase="pasos", etiqueta="lenta"))

        listo = threading.Event()
        fragmentos = [f"<{i}>" for i in range(500)]

        def productor():
            tok = events.marcar_agente(AID)
            try:
                for frag in fragmentos:
                    events.emitir(events.TokenTexto(texto=frag))
                events.emitir(events.AgenteFin(
                    run_id=RUN, agente_id=AID, indice=1, total=1, ok=True,
                    tokens=7, duracion_s=0.2))
            finally:
                events.desmarcar_agente(tok)
                listo.set()

        h = threading.Thread(target=productor, name="emisor-lento")
        h.start()
        # La App TARDA: el hilo de la UI se bloquea a proposito (un widget lento
        # pintando, un handler pesado). Nada se drena mientras tanto.
        while not listo.wait(timeout=0.05):
            time.sleep(0.01)
        h.join(timeout=10)
        assert not h.is_alive()

        # La cola de flujo quedo tapada en su tope; lo estructural NO se tira.
        assert p.pendientes == 32 + 3

        for _ in range(200):
            if p.pendientes == 0:
                break
            await pilot.pause()
        p.drenar(10 ** 6)

        a = p.estado.agente(AID)
        d = p.estado.descartes
        met = p.metricas()

    # 500 tokens, 32 sobrevivieron: 468 descartados y CONTADOS.
    assert d.total == 468
    assert d.por_tipo == {"TokenTexto": 468}
    assert d.hubo is True
    assert d.chars == sum(len(f) for f in fragmentos[:468])

    # El texto que queda es la COLA del stream (lo que el usuario esta leyendo),
    # y esta declarado como INCOMPLETO con los chars que le faltan.
    assert a.texto == "".join(fragmentos[468:])
    assert a.completo is False
    assert a.chars_perdidos == d.chars
    # Invariante: nada desaparece sin cuenta.
    assert a.chars_texto + a.chars_perdidos == sum(len(f) for f in fragmentos)

    # Lo ESTRUCTURAL sobrevivio entero: el agente cerro y la corrida existe.
    assert a.estado == "ok" and a.tokens == 7
    assert p.estado.corrida(RUN) is not None
    assert met["descartados"] == 468


def test_el_descarte_se_loguea_en_warning(bus_limpio):
    """Ademas del contador: un WARNING (que con la TUI abierta cae en el
    LogsPanel via TuiLogHandler). El descarte no puede ser solo un numero que
    nadie mira.

    No se usa caplog: el logger "cognia" va con propagate=False
    (logger_config.py), asi que el handler que caplog pone en el root NO ve
    estos records. Se engancha uno propio al logger real."""
    registros: list = []

    class _Captura(logging.Handler):
        def emit(self, record):
            registros.append(record.getMessage())

    lg = logging.getLogger("cognia.tui.puente")
    handler, nivel_previo = _Captura(logging.WARNING), lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.WARNING)
    try:
        p = PuenteBus(cap_cola=4)
        p.conectar()
        tok = events.marcar_agente("run-w#pasos.1@1")
        try:
            for i in range(40):
                events.emitir(events.TokenTexto(texto=f"{i},"))
        finally:
            events.desmarcar_agente(tok)
        p.drenar(10 ** 6)
    finally:
        lg.removeHandler(handler)
        lg.setLevel(nivel_previo)

    assert any("descartados" in m for m in registros), registros
    assert any("36" in m for m in registros), registros


def test_lo_estructural_aguanta_mucho_mas_que_el_flujo(bus_limpio):
    """El techo estructural NO es backpressure: es el seguro contra un puente
    que quedo conectado a una App muerta. Con la cola de flujo llena, lo
    estructural sigue entrando (4x) y cuando revienta, tambien se cuenta."""
    p = PuenteBus(cap_cola=4, cap_estructural=8)
    p.conectar()
    for i in range(6):
        events.emitir(events.TokenTexto(texto=f"{i}"))     # flujo: se recorta a 4
    for i in range(12):
        events.emitir(events.Aviso(texto=f"a{i}", origen="t"))
    assert p.pendientes == 4 + 8
    d = p.estado.descartes
    assert d.por_tipo == {"TokenTexto": 2, "Aviso": 4}
    p.drenar(10 ** 6)
    # Sobrevivieron los ULTIMOS 8 avisos, en orden.
    assert [x["texto"] for x in p.estado.avisos] == [f"a{i}" for i in range(4, 12)]


@pytest.mark.asyncio
async def test_el_puente_no_deja_ciego_al_movil(bus_limpio, monkeypatch):
    """LA RESTRICCION DURA: la vista de agentes NO puede romper el telefono.

    El sink stdout (COGNIA_EVENTS_JSONL=1) y el puente son DOS suscriptores del
    mismo bus. Este test los pone juntos con la App REAL abierta y exige las dos
    cosas a la vez: las lineas '@EV' siguen saliendo por el stdout real (el
    unico canal de remoto/sesiones.py) y el puente reconstruye el estado.

    Como en test_events_sink_tui.py, se neutraliza ``app._original_stdout``:
    run_test() fuerza headless y el reenvio de cortesia de Textual taparia el
    bug que este test vigila."""
    from cognia.tui.app import CogniaTUI

    class _Nulo:
        def write(self, texto):
            pass

        def flush(self):
            pass

    real = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", real)
    events.activar_sink_jsonl("1")

    RUN, AID = "run-movil", "run-movil#pasos.1@1"
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._original_stdout = _Nulo()          # condicion de PRODUCCION
        p = conectar_puente(app)
        assert len(events._suscriptores) == 2   # sink + puente

        def productor():
            tok = events.marcar_agente(AID)
            try:
                events.emitir(events.AgenteInicio(
                    run_id=RUN, agente_id=AID, indice=1, total=1,
                    fase="pasos", etiqueta="movil"))
                for i in range(20):
                    events.emitir(events.TokenTexto(texto=f"t{i}"))
                events.emitir(events.AgenteFin(
                    run_id=RUN, agente_id=AID, indice=1, total=1, ok=True,
                    tokens=20, duracion_s=0.1))
            finally:
                events.desmarcar_agente(tok)

        h = threading.Thread(target=productor, name="emisor-movil")
        h.start()
        h.join(timeout=10)
        assert not h.is_alive()
        for _ in range(200):
            if p.pendientes == 0:
                break
            await pilot.pause()
        p.drenar(10 ** 6)
        estado = p.estado

    # --- el telefono sigue viendo ---------------------------------------
    lineas = [json.loads(x[len(events.PREFIJO_STDOUT):])
              for x in real.getvalue().splitlines()
              if x.startswith(events.PREFIJO_STDOUT)]
    tipos = [d["tipo"] for d in lineas]
    assert tipos == ["AgenteInicio", "AgenteFin"], tipos
    assert lineas[0]["agente_id"] == AID
    # El contrato del sink no cambia: TokenTexto NO va por stdout.
    assert "TokenTexto" not in tipos

    # --- y el panel tiene el stream entero -------------------------------
    a = estado.agente(AID)
    assert a.texto == "".join(f"t{i}" for i in range(20))
    assert a.estado == "ok" and a.completo is True


# ---------------------------------------------------------------------------
# 3. El contrato del emisor: no lanza, no bloquea, no depende de la App.
# ---------------------------------------------------------------------------

def test_emitir_no_lanza_aunque_la_app_este_rota(bus_limpio):
    class AppRota:
        def post_message(self, mensaje):
            raise RuntimeError("app muerta")

    p = PuenteBus(AppRota())
    p.conectar()
    events.emitir(events.Aviso(texto="hola", origen="test"))   # no debe lanzar
    events.emitir(events.Aviso(texto="chau", origen="test"))
    assert p.metricas()["wakeups_fallidos"] >= 1
    # El evento NO se pierde: sigue en cola y un drenaje manual lo aplica.
    assert p.pendientes == 2
    assert p.drenar() == 2
    assert len(p.estado.avisos) == 2


def test_emitir_no_lanza_aunque_el_puente_reviente(bus_limpio, monkeypatch):
    p = PuenteBus()
    p.conectar()

    def _boom(_ev):
        raise ValueError("puente roto")

    monkeypatch.setattr(p, "_encolar", _boom)
    events.emitir(events.Aviso(texto="x", origen="test"))       # no debe lanzar


def test_sin_app_el_puente_funciona_con_drenar(bus_limpio):
    """Headless total: sin App el modelo se llena llamando drenar() a mano."""
    p = PuenteBus()
    p.conectar()
    events.emitir(events.WorkflowInicio(run_id="r1", nombre="suelta",
                                        total_agentes=1))
    assert p.estado.corrida("r1") is None      # nada se aplico todavia
    assert p.drenar() == 1
    assert p.estado.corrida("r1").nombre == "suelta"


# ---------------------------------------------------------------------------
# 4. Enchufar y desenchufar limpio.
# ---------------------------------------------------------------------------

def test_conectar_dos_veces_no_deja_dos_suscriptores(bus_limpio):
    p1 = conectar_puente()
    p2 = conectar_puente()
    assert p1 is p2
    assert len(events._suscriptores) == 1
    p1.conectar()                       # y la instancia tambien es idempotente
    assert len(events._suscriptores) == 1

    events.emitir(events.Aviso(texto="uno", origen="test"))
    p1.drenar()
    assert len(p1.estado.avisos) == 1   # aplicado UNA vez, no dos


def test_desconectar_saca_el_suscriptor_y_es_idempotente(bus_limpio):
    p = conectar_puente()
    assert len(events._suscriptores) == 1
    desconectar_puente()
    assert len(events._suscriptores) == 0
    assert p.conectado is False
    desconectar_puente()                # dos veces no rompe
    events.emitir(events.Aviso(texto="fantasma", origen="test"))
    assert p.pendientes == 0
    assert mod_puente.puente_activo() is None


@pytest.mark.asyncio
async def test_reabrir_la_vista_en_otra_app_reemplaza_el_puente(bus_limpio):
    app1 = AppJuguete()
    async with app1.run_test():
        p1 = conectar_puente(app1)
    app2 = AppJuguete()
    async with app2.run_test():
        p2 = conectar_puente(app2)
        assert p2 is not p1
        assert p1.conectado is False
        assert len(events._suscriptores) == 1


# ---------------------------------------------------------------------------
# 5. El modelo de estado.
# ---------------------------------------------------------------------------

def test_orden_entre_estructural_y_flujo(bus_limpio):
    """Las dos colas se re-mezclan por numero de secuencia: sin eso el
    AgenteFin (estructural) se aplicaria ANTES que los tokens y el agente
    aparecerira cerrado mientras todavia escribe."""
    p = PuenteBus()
    p.conectar()
    aid = "run-o#pasos.1@1"
    events.emitir(events.AgenteInicio(run_id="run-o", agente_id=aid, indice=1,
                                      total=1))
    tok = events.marcar_agente(aid)
    try:
        for frag in ("a", "b", "c"):
            events.emitir(events.TokenTexto(texto=frag))
    finally:
        events.desmarcar_agente(tok)
    events.emitir(events.AgenteFin(run_id="run-o", agente_id=aid, indice=1,
                                   total=1, ok=True))

    assert p.drenar(tope=2) == 2        # AgenteInicio + "a"
    a = p.estado.agente(aid)
    assert a.estado == "corriendo" and a.texto == "a"
    assert p.drenar(tope=10) == 3
    assert a.estado == "ok" and a.texto == "abc"


def test_techo_de_texto_conserva_la_cola_y_lo_declara(bus_limpio):
    p = PuenteBus(cap_texto=64)
    p.conectar()
    aid = "run-t#pasos.1@1"
    events.emitir(events.AgenteInicio(run_id="run-t", agente_id=aid))
    tok = events.marcar_agente(aid)
    fragmentos = [f"{i:04d}." for i in range(100)]     # 100 x 5 = 500 chars
    try:
        for frag in fragmentos:
            events.emitir(events.TokenTexto(texto=frag))
    finally:
        events.desmarcar_agente(tok)
    p.drenar(10 ** 6)

    a = p.estado.agente(aid)
    entero = "".join(fragmentos)
    assert len(a.texto) == 64
    assert a.texto == entero[-64:]      # recorte EXACTO, no "el fragmento entero"
    assert a.chars_texto == 500         # lo que paso de verdad
    assert a.chars_truncados == 500 - 64
    assert a.chars_perdidos == 0        # esto NO es descarte: es el techo
    assert a.completo is False
    assert p.estado.descartes.total == 0


def test_token_de_agente_no_visto_crea_una_fila_sintetica(bus_limpio):
    """El puente se puede enchufar a mitad de corrida: el TokenTexto solo trae
    el agente_id sellado por el ContextVar, y de ahi sale el run_id."""
    p = PuenteBus()
    p.conectar()
    tok = events.marcar_agente("run-z#critica.2@7")
    try:
        events.emitir(events.TokenTexto(texto="hola"))
    finally:
        events.desmarcar_agente(tok)
    p.drenar()

    a = p.estado.agente("run-z#critica.2@7")
    assert a is not None and a.sintetico is True and a.texto == "hola"
    c = p.estado.corrida("run-z")
    assert c is not None and c.sintetica is True


def test_eventos_sin_agente_van_al_bucle_suelto(bus_limpio):
    p = PuenteBus()
    p.conectar()
    events.emitir(events.TokenTexto(texto="chat "))
    events.emitir(events.TokenTexto(texto="suelto"))
    p.drenar()
    assert p.estado.suelto.texto == "chat suelto"
    assert p.estado.corridas == {}


def test_corrida_completa_con_fallo_y_cancelacion(bus_limpio):
    p = PuenteBus()
    p.conectar()
    RUN = "run-mix"
    events.emitir(events.WorkflowInicio(run_id=RUN, nombre="mix",
                                        total_agentes=3, interactivo=True))
    for k, (ok, cancelado) in enumerate([(True, False), (False, False),
                                         (False, True)]):
        aid = f"{RUN}#pasos.{k + 1}@{k + 1}"
        events.emitir(events.AgenteInicio(run_id=RUN, agente_id=aid,
                                          indice=k + 1, total=3, fase="pasos"))
        events.emitir(events.AgenteFin(
            run_id=RUN, agente_id=aid, indice=k + 1, total=3, ok=ok,
            cancelado=cancelado, motivo="" if ok else "backend caido",
            tokens=10 * (k + 1), duracion_s=0.5))
    events.emitir(events.WorkflowFin(run_id=RUN, nombre="mix", ok=False,
                                     agentes=3, fallidos=2, cancelados=1,
                                     tokens=60, duracion_s=2.0))
    p.drenar(10 ** 6)

    c = p.estado.corrida(RUN)
    estados = [a.estado for a in c.agentes_vista.values()]
    assert estados == ["ok", "fallo", "cancelado"]
    assert c.interactivo is True
    assert c.abierta is False and c.ok is False
    assert c.fallidos == 2 and c.cancelados == 1
    assert c.tokens_vistos == 60        # contado en vivo por el puente
    assert c.vivos == []
    assert p.estado.ultima_corrida is c


def test_progreso_y_mensajes_por_agente(bus_limpio):
    p = PuenteBus()
    p.conectar()
    RUN, aid = "run-p", "run-p#pasos.1@1"
    events.emitir(events.AgenteInicio(run_id=RUN, agente_id=aid, indice=1,
                                      total=1))
    tok = events.marcar_agente(aid)
    try:
        # AgenteProgreso trae ACUMULADOS de la llamada: max(), no suma.
        events.emitir(events.AgenteProgreso(run_id=RUN, chars=400,
                                            chars_razonamiento=50, intento=1))
        events.emitir(events.AgenteProgreso(run_id=RUN, chars=800,
                                            chars_razonamiento=90, intento=1))
    finally:
        events.desmarcar_agente(tok)
    events.emitir(events.MensajeAlAgente(run_id=RUN, destino=aid, texto="para",
                                         aceptado=True, estado="encolado",
                                         pendientes=1))
    events.emitir(events.MensajeAlAgente(run_id=RUN, destino=aid, texto="che",
                                         aceptado=False, estado="cerrado"))
    p.drenar(10 ** 6)

    a = p.estado.agente(aid)
    assert a.chars_progreso == 800 and a.chars_razonamiento == 90
    assert a.mensajes == 2 and a.mensajes_aceptados == 1
    # `pendientes` es el ULTIMO valor visto (mensajes en cola AHORA), no un
    # acumulado: el segundo mensaje llego rechazado y con la cola en 0.
    assert a.estado_control == "cerrado" and a.pendientes == 0
    # Reloj VIVO: el agente sigue corriendo, asi que `segundos` crece solo.
    # (el sleep no es adorno: time.time() en Windows salta de a ~15 ms y sin el
    # la resta da 0.0 clavado)
    time.sleep(0.03)
    assert a.segundos > 0 and a.estado == "corriendo"


def test_tope_de_corridas_olvida_las_cerradas_primero(bus_limpio):
    p = PuenteBus(max_corridas=3)
    p.conectar()
    for i in range(5):
        rid = f"r{i}"
        events.emitir(events.WorkflowInicio(run_id=rid, nombre=rid))
        events.emitir(events.AgenteInicio(run_id=rid, agente_id=f"{rid}#p.1@1"))
        if i < 3:
            events.emitir(events.WorkflowFin(run_id=rid, nombre=rid, ok=True))
    p.drenar(10 ** 6)

    assert len(p.estado.corridas) <= 3
    assert "r4" in p.estado.corridas and "r3" in p.estado.corridas
    assert p.estado.corridas_olvidadas >= 2
    # El indice global no queda con basura de las corridas olvidadas.
    assert p.estado.agente("r0#p.1@1") is None
    assert p.estado.agente("r4#p.1@1") is not None


def test_tope_de_agentes_por_corrida_se_declara(bus_limpio):
    p = PuenteBus(max_agentes=2)
    p.conectar()
    RUN = "run-tope"
    events.emitir(events.WorkflowInicio(run_id=RUN, nombre="tope"))
    for k in range(5):
        events.emitir(events.AgenteInicio(run_id=RUN,
                                          agente_id=f"{RUN}#p.{k}@{k}"))
    p.drenar(10 ** 6)

    c = p.estado.corrida(RUN)
    assert len(c.agentes_vista) == 2
    assert c.agentes_omitidos == 3      # no se pierden en silencio


def test_avisos_y_degradados_quedan_en_el_anillo(bus_limpio):
    p = PuenteBus()
    p.conectar()
    events.emitir(events.Aviso(texto="ojo", origen="backend"))
    events.emitir(events.Degradado(donde="flota", motivo="pensar caido",
                                   accion_sugerida="servir_flota.py"))
    p.drenar()
    niveles = [x["nivel"] for x in p.estado.avisos]
    assert niveles == ["aviso", "degradado"]
    assert p.estado.avisos[1]["texto"] == "flota: pensar caido"


def test_version_sube_solo_cuando_se_aplica_algo(bus_limpio):
    p = PuenteBus()
    p.conectar()
    assert p.estado.version == 0
    assert p.drenar() == 0
    assert p.estado.version == 0
    events.emitir(events.Aviso(texto="x", origen="t"))
    p.drenar()
    assert p.estado.version == 1
