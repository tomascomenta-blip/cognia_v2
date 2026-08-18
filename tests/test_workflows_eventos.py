# -*- coding: utf-8 -*-
"""
tests/test_workflows_eventos.py — el motor EMITE (tanda UI 2026-08-17)
======================================================================
Sin red y sin GPU: completar_fn siempre inyectado. Lo que se fija aca es el
contrato de eventos del motor, que es lo que hace posible un panel por agente:

- TODO agente que arranca termina con su AgenteFin (los 8 caminos de salida,
  incluida la excepcion): sin eso el panel deja filas abiertas para siempre;
- el agente_id es estable entre Inicio y Fin y legible a ojo en un log;
- AgenteFin REPITE la identidad para que el remoto la lea sin estado;
- los tokens del Fin SUMAN los reintentos (el usage del ultimo intento
  declaraba la mitad de lo que costo);
- un hilo nuevo de paralelo() no hereda el agente_id del padre: los TokenTexto
  de dos agentes concurrentes no se cruzan;
- el bus JAMAS tumba una corrida: ni un suscriptor roto ni un emitir roto.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

import pytest

from cognia.agent.workflows import agente, corrida, criticar, paralelo
from cognia.ux import events as ux


@dataclass
class _Resp:
    """Lo minimo que agente() mira de una RespuestaChat."""
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10,
                                                 "completion_tokens": 5})
    error: str = ""


class _Stub:
    """completar_fn de mentira: devuelve respuestas en orden."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append({"mensajes": mensajes, "kw": kw})
        if not self.respuestas:
            raise AssertionError("stub sin respuestas: llamada de mas")
        return self.respuestas.pop(0)


@pytest.fixture
def dir_wf(tmp_path, monkeypatch):
    """Corridas bajo tmp_path: nada toca ~/.cognia real."""
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def bus():
    """Acumula todo lo que pasa por el bus y se desuscribe siempre: un
    suscriptor colgado contamina los tests que corran despues."""
    vistos: list = []
    ux.suscribir(vistos.append)
    try:
        yield vistos
    finally:
        ux.desuscribir(vistos.append)


def _corrida(nombre="prueba", **kw):
    return corrida(nombre, print_fn=lambda *a, **k: None, **kw)


def _de(bus, clase):
    return [e for e in bus if isinstance(e, clase)]


# ------------------------------------------------- el invariante central
# Los 8 caminos de salida de agente(). Cada uno devuelve el nombre para el
# mensaje del assert; el que LANZA se atrapa aca dentro a proposito: el
# contrato es que el AgenteFin sale igual, no que la excepcion se trague.

def _camino_ok(c, bus):
    agente(c, "hola", completar_fn=_Stub([_Resp(texto="listo")]))


def _camino_cache_hit(c, bus):
    agente(c, "pregunta cara", completar_fn=_Stub([_Resp(texto="caro")]))
    del bus[:]                      # el hit es el SEGUNDO agente
    agente(c, "pregunta cara", completar_fn=_Stub([]))


def _camino_presupuesto_previo(c, bus):
    c.presupuesto.registrar({"prompt_tokens": 50, "completion_tokens": 0})
    agente(c, "hola", completar_fn=_Stub([]))


def _camino_presupuesto_en_retry(c, bus):
    # El 1er intento gasta todo el techo; el 2do se corta ANTES de llamar.
    agente(c, "dame json", {"type": "object"},
           completar_fn=_Stub([_Resp(texto="no es json",
                                     usage={"prompt_tokens": 30,
                                            "completion_tokens": 30})]))


def _camino_error_del_backend(c, bus):
    agente(c, "hola", completar_fn=_Stub([_Resp(error="connection refused")]))


def _camino_truncado(c, bus):
    agente(c, "hola", completar_fn=_Stub([_Resp(texto="a medi",
                                                finish_reason="length")]))


def _camino_schema_no_conforme(c, bus):
    agente(c, "dame json", {"type": "object"},
           completar_fn=_Stub([_Resp(texto="[]"), _Resp(texto="[]")]))


def _camino_excepcion(c, bus):
    def _revienta(mensajes, **kw):
        raise RuntimeError("el backend exploto")

    with pytest.raises(RuntimeError):
        agente(c, "hola", completar_fn=_revienta)


CAMINOS = {
    "ok": _camino_ok,
    "cache_hit": _camino_cache_hit,
    "presupuesto_previo": _camino_presupuesto_previo,
    "presupuesto_en_retry": _camino_presupuesto_en_retry,
    "error_del_backend": _camino_error_del_backend,
    "truncado": _camino_truncado,
    "schema_no_conforme": _camino_schema_no_conforme,
    "excepcion": _camino_excepcion,
}


@pytest.mark.parametrize("camino", sorted(CAMINOS))
def test_todo_agente_que_arranca_emite_su_fin(dir_wf, bus, camino):
    """El invariante de la tanda: una fila que se abre en el panel se cierra.
    Los 8 caminos, incluida la excepcion (que sigue subiendo al caller)."""
    c = _corrida(presupuesto_tokens=50)
    CAMINOS[camino](c, bus)
    c.cerrar()

    inicios, fines = _de(bus, ux.AgenteInicio), _de(bus, ux.AgenteFin)
    assert len(inicios) == 1, f"{camino}: {len(inicios)} AgenteInicio"
    assert len(fines) == 1, f"{camino}: {len(fines)} AgenteFin"
    assert inicios[0].agente_id == fines[0].agente_id


def test_el_agente_id_es_estable_y_legible(dir_wf, bus):
    c = _corrida()
    agente(c, "resume TLS", completar_fn=_Stub([_Resp(texto="ok")]),
           indice=2, total=6, fase="pasos", etiqueta="resume TLS")
    c.cerrar()
    ini, fin = _de(bus, ux.AgenteInicio)[0], _de(bus, ux.AgenteFin)[0]
    # "@1" = el contador monotono de la corrida (este es el primer agente).
    assert ini.agente_id == f"{c.run_id}#pasos.2@1"
    assert fin.agente_id == ini.agente_id


def test_dos_criticar_no_repiten_agente_id(dir_wf, bus):
    """DEFECTO 6. El lazo real es «refutado -> corrige -> vuelve a criticar»:
    dos criticar() sobre la MISMA Corrida. criticar() pasa indice=1..3 las dos
    veces, asi que un id construido solo con fase+indice salia
    '#critica.1','#critica.2','#critica.3','#critica.1',... El panel agrupa
    TokenTexto y Aviso por agente_id: con ids repetidos mezclaba la prosa de
    las dos rondas del lazo en una sola fila.

    Sin el sufijo @<contador> este test da 3 ids distintos de 6.
    """
    c = _corrida()

    def _comp(mensajes, **kw):
        return _Resp(texto='{"refutado": false, "motivo": "ok"}')

    criticar(c, "entrega A", completar_fn=_comp)
    criticar(c, "entrega B, ya corregida", completar_fn=_comp)
    c.cerrar()

    ids = [e.agente_id for e in _de(bus, ux.AgenteInicio)]
    assert len(ids) == 6, f"se lanzaron {len(ids)} criticos, no 6"
    assert len(set(ids)) == 6, f"ids repetidos: {ids}"
    # El Fin usa EL MISMO id que su Inicio: el panel cierra la fila que abrio.
    assert sorted(e.agente_id for e in _de(bus, ux.AgenteFin)) == sorted(ids)


def test_el_indice_logico_sobrevive_al_id_unico(dir_wf, bus):
    """El id se hizo unico SIN tocar el '2 de 6' legible: la segunda tanda de
    criticos sigue siendo 1/3, 2/3, 3/3 y no 4/3, 5/3, 6/3 — indice/total son
    lo que se MUESTRA, el sufijo @n es lo que CORRELACIONA."""
    c = _corrida()

    def _comp(mensajes, **kw):
        return _Resp(texto='{"refutado": false, "motivo": "ok"}')

    criticar(c, "entrega A", completar_fn=_comp)
    del bus[:]
    criticar(c, "entrega B", completar_fn=_comp)
    c.cerrar()

    segunda = _de(bus, ux.AgenteInicio)
    assert sorted((e.indice, e.total) for e in segunda) == [
        (1, 3), (2, 3), (3, 3)]
    # ...y aun asi los ids son de la SEGUNDA ronda (contador 4, 5 y 6).
    assert sorted(e.agente_id.rsplit("@", 1)[1] for e in segunda) == [
        "4", "5", "6"]


def test_agente_fin_repite_la_identidad(dir_wf, bus):
    """El remoto interpreta evento a evento SIN estado: si el Fin no repite
    indice/total/fase/etiqueta, el movil no puede escribir 'agente 2 de 6'."""
    c = _corrida()
    agente(c, "resume TLS", completar_fn=_Stub([_Resp(texto="ok")]),
           indice=2, total=6, fase="pasos", etiqueta="resume TLS")
    c.cerrar()
    fin = _de(bus, ux.AgenteFin)[0]
    assert (fin.indice, fin.total, fin.fase, fin.etiqueta) == (
        2, 6, "pasos", "resume TLS")


def test_el_agente_suelto_se_auto_numera(dir_wf, bus):
    """Un caller que no sabe nada del contrato nuevo igual aparece."""
    c = _corrida()
    agente(c, "primera linea del prompt\nsegunda linea",
           completar_fn=_Stub([_Resp(texto="ok")]))
    c.cerrar()
    ini = _de(bus, ux.AgenteInicio)[0]
    assert ini.fase == "suelto" and ini.indice == 1 and ini.total == 0
    assert ini.etiqueta == "primera linea del prompt"


def test_los_tokens_del_fin_suman_los_reintentos(dir_wf, bus):
    """La implementacion ingenua pasa el usage del ULTIMO intento: un agente
    que reintento por schema declararia la mitad de lo que costo."""
    c = _corrida()
    agente(c, "dame json", {"type": "object"},
           completar_fn=_Stub([
               _Resp(texto="[]", usage={"prompt_tokens": 10,
                                        "completion_tokens": 5}),
               _Resp(texto="{}", usage={"prompt_tokens": 100,
                                        "completion_tokens": 40})]))
    c.cerrar()
    fin = _de(bus, ux.AgenteFin)[0]
    assert fin.ok is True
    assert fin.intentos == 2
    assert fin.tokens == 155, f"declaro {fin.tokens} en vez de 15+140"


def test_los_tokens_se_cuentan_sin_presupuesto(dir_wf, bus):
    """El panel muestra el coste REAL, no el presupuestado."""
    c = _corrida()                      # presupuesto_tokens=None
    agente(c, "hola", completar_fn=_Stub([
        _Resp(texto="ok", usage={"prompt_tokens": 7, "completion_tokens": 3})]))
    c.cerrar()
    assert _de(bus, ux.AgenteFin)[0].tokens == 10


def test_cache_hit_se_declara_y_no_cuesta(dir_wf, bus):
    """Un fin en 0 ms sin explicacion se lee como un bug."""
    c = _corrida()
    agente(c, "pregunta cara", completar_fn=_Stub([_Resp(texto="caro")]))
    del bus[:]
    agente(c, "pregunta cara", completar_fn=_Stub([]))
    c.cerrar()
    fin = _de(bus, ux.AgenteFin)[0]
    assert (fin.cache_hit, fin.ok, fin.tokens, fin.intentos) == (
        True, True, 0, 0)
    assert fin.resumen == "caro"


def test_el_fallo_declara_su_motivo(dir_wf, bus):
    """'devolvio vacio' y 'revento' piden decisiones opuestas."""
    c = _corrida()
    agente(c, "hola", completar_fn=_Stub([_Resp(error="connection refused")]))
    c.cerrar()
    fin = _de(bus, ux.AgenteFin)[0]
    assert fin.ok is False and "connection refused" in fin.motivo
    assert fin.url, "la url efectiva se resolvio: tiene que constar"


def test_paralelo_no_cruza_identidades(dir_wf, bus):
    """La premisa del panel por agente: un hilo NUEVO arranca con contexto
    vacio, asi que el agente_id del padre jamas se filtra a un thunk."""
    c = _corrida()

    def _mk(i):
        def _completar(mensajes, **kw):
            ux.emitir(ux.TokenTexto(texto=f"p{i}"))
            time.sleep(0.01)            # fuerza el solape con cap=2
            ux.emitir(ux.TokenTexto(texto=f"p{i}"))
            return _Resp(texto=f"r{i}")

        def _correr():
            return agente(c, f"paso {i}", completar_fn=_completar,
                          indice=i, total=4, fase="pasos",
                          etiqueta=f"paso {i}")
        return _correr

    paralelo([_mk(i) for i in range(1, 5)], cap=2)
    c.cerrar()

    # El id se resuelve por el AgenteInicio de cada indice y no se arma a mano:
    # el sufijo @n es el ORDEN DE ARRANQUE, y con cap=2 no tiene por que
    # coincidir con el indice logico (el paso 2 puede arrancar antes que el 1).
    por_indice = {e.indice: e.agente_id for e in _de(bus, ux.AgenteInicio)}
    assert len(set(por_indice.values())) == 4, "los 4 ids tienen que diferir"
    tokens = _de(bus, ux.TokenTexto)
    assert len(tokens) == 8
    for ev in tokens:
        esperado = por_indice[int(ev.texto[1:])]
        assert ev.agente_id == esperado, (
            f"token de {ev.texto} sellado como {ev.agente_id}")


def test_fuera_de_un_agente_no_queda_sello(dir_wf, bus):
    """desmarcar_agente() en el finally: el contexto vuelve limpio."""
    c = _corrida()
    agente(c, "hola", completar_fn=_Stub([_Resp(texto="ok")]))
    ux.emitir(ux.TokenTexto(texto="prosa suelta"))
    c.cerrar()
    assert _de(bus, ux.TokenTexto)[0].agente_id == ""


def test_workflow_inicio_lleva_el_total_y_el_presupuesto(dir_wf, bus):
    """El panel dibuja 6 huecos de una vez y tiene el denominador de la barra
    de gasto ANTES del primer AgenteInicio."""
    c = _corrida(presupuesto_tokens=60000, total_agentes=6)
    ini = _de(bus, ux.WorkflowInicio)[0]
    c.cerrar()
    assert ini.run_id == c.run_id and ini.nombre == "prueba"
    assert ini.total_agentes == 6 and ini.presupuesto_tokens == 60000
    assert ini.resume_de == "" and ini.cache_precargada == 0


def test_workflow_inicio_declara_el_resume_y_la_cache(dir_wf, bus):
    """4 de 6 agentes terminando en 0 ms se lee como roto si nadie dice que
    ya estaban pagados."""
    c1 = _corrida()
    agente(c1, "pregunta cara", completar_fn=_Stub([_Resp(texto="caro")]))
    c1.cerrar()
    del bus[:]
    c2 = _corrida(resume_de=c1.run_id)
    c2.cerrar()
    ini = _de(bus, ux.WorkflowInicio)[0]
    assert ini.resume_de == c1.run_id and ini.cache_precargada == 1


def test_workflow_fin_una_sola_vez(dir_wf, bus):
    c = _corrida(presupuesto_tokens=60000)
    agente(c, "uno", completar_fn=_Stub([_Resp(texto="a")]))
    agente(c, "uno", completar_fn=_Stub([]))            # cache hit
    agente(c, "dos", completar_fn=_Stub([_Resp(error="boom")]))
    c.cerrar()
    c.cerrar()

    fines = _de(bus, ux.WorkflowFin)
    assert len(fines) == 1, f"{len(fines)} WorkflowFin"
    f = fines[0]
    assert f.agentes == len(_de(bus, ux.AgenteInicio)) == 3
    assert f.fallidos == len([e for e in _de(bus, ux.AgenteFin) if not e.ok]) == 1
    assert f.cache_hits == 1
    assert f.tokens == c.presupuesto.gastado() and f.presupuesto_tokens == 60000
    assert f.duracion_s >= 0.0


# ------------------------------------- el cierre no puede pintar exito falso
# DEFECTOS 1 y 3. Los dos salen del mismo escenario medido: paralelo() agota el
# timeout, los futuros que no arrancaron se cancelan sin pasar por agente() (no
# hay AgenteInicio ni AgenteFin) y el que colgo sigue vivo emitiendo despues del
# cierre.

def _corrida_con_timeout(bus, n_pasos=4, declarados=4):
    """Monta el escenario del revisor SIN dormir 6 s: el paso 1 se queda
    esperando un Event que el test suelta cuando ya midio. Devuelve
    (corrida, soltar, esperar_al_huerfano)."""
    soltar = threading.Event()
    c = _corrida(total_agentes=declarados)

    def _mk(i):
        def _comp(mensajes, **kw):
            if i == 1 and not soltar.wait(10):
                raise AssertionError("el huerfano no se solto: test colgado")
            return _Resp(texto=f"r{i}")

        def _correr():
            return agente(c, f"paso {i}", completar_fn=_comp, indice=i,
                          total=n_pasos, fase="pasos", etiqueta=f"paso {i}")
        return _correr

    def _esperar_al_huerfano():
        soltar.set()
        for _ in range(500):            # <=5 s; en la practica milisegundos
            if _de(bus, ux.AgenteFin):
                return
            time.sleep(0.01)
        raise AssertionError("el huerfano nunca emitio su AgenteFin")

    # cap=1 para que solo el paso 1 llegue a arrancar; timeout corto porque el
    # thunk colgado no se mata y la pared del test seria la suya.
    paralelo([_mk(i) for i in range(1, n_pasos + 1)], cap=1, timeout_s=0.2)
    return c, soltar, _esperar_al_huerfano


def test_workflow_fin_no_miente_cuando_paralelo_agota_el_timeout(dir_wf, bus):
    """DEFECTO 1. Con la cuenta vieja (agentes = AgenteInicio emitidos) esto
    salia 'agentes=1 fallidos=0' y el consumidor pintaba '1 de 1': exito sobre
    una corrida donde 3 de 4 pasos desaparecieron sin dejar rastro."""
    c, soltar, esperar = _corrida_con_timeout(bus)
    try:
        c.cerrar()                      # el caller cree que todo fue bien
        f = _de(bus, ux.WorkflowFin)[0]
        # el desglose: quien arranco, quien no, quien quedo colgando
        assert f.total_agentes == 4, "el declarado del caller se pierde"
        assert f.arrancados == 1, f"arrancados={f.arrancados}"
        assert f.no_arrancados == 3, f"no_arrancados={f.no_arrancados}"
        assert f.colgando == 1, f"colgando={f.colgando}"
        # el denominador honesto, no el que se encogio solo
        assert (f.agentes, f.fallidos) == (4, 4), (
            f"agentes={f.agentes} fallidos={f.fallidos}: "
            f"'{f.agentes - f.fallidos} de {f.agentes}' pintaria exito")
        assert f.ok is False, "un cierre al que le faltan 3 de 4 no es ok"
        assert "no llegaron a arrancar" in f.resumen
    finally:
        soltar.set()
        esperar()


def test_el_consumidor_real_no_puede_pintar_exito(dir_wf, bus):
    """La prueba de que el arreglo llega hasta el otro lado: se le pasa el
    WorkflowFin a interpretar_evento() de remoto/sesiones.py TAL CUAL ESTA
    (misma formula duplicada en ux/renderer.py) y tiene que salir la linea de
    fallo, no un '⏺ workflow — 1 de 1'."""
    from cognia.remoto.sesiones import interpretar_evento

    c, soltar, esperar = _corrida_con_timeout(bus)
    try:
        c.cerrar()
        _canal, texto, _ecos = interpretar_evento(
            ux.a_dict(_de(bus, ux.WorkflowFin)[0]))
        assert texto.startswith("✗"), f"el consumidor pinto: {texto!r}"
        assert "1 de 1" not in texto
        assert "no llegaron a arrancar" in texto
    finally:
        soltar.set()
        esperar()


def test_el_agente_fin_tardio_se_declara_tardio(dir_wf, bus):
    """DEFECTO 3. Al huerfano no se le puede esperar (por eso existe), asi que
    la salida honesta es que se ANUNCIE: su AgenteFin llega despues del
    WorkflowFin y sale con tardio=True. Sin la marca, el consumidor recibe una
    fila de agente sin workflow al que pertenecer y se entera por sorpresa."""
    c, soltar, esperar = _corrida_con_timeout(bus)
    try:
        c.cerrar()
        assert not _de(bus, ux.AgenteFin), "el huerfano no puede haber cerrado"
        wf_fin = _de(bus, ux.WorkflowFin)[0]
    finally:
        soltar.set()
        esperar()

    tardio = _de(bus, ux.AgenteFin)[0]
    assert tardio.ts >= wf_fin.ts, "el escenario no reprodujo: llego a tiempo"
    assert tardio.tardio is True, "AgenteFin tras WorkflowFin sin marcar"
    # y el que SI cerro dentro de la corrida no se marca de rebote
    assert _de(bus, ux.AgenteInicio)[0].tardio is False


def test_el_agente_fin_no_puede_adelantar_al_cierre_sin_marcarse(dir_wf, bus):
    """El AgenteFin se EMITE bajo el mismo lock que publica el cierre, no solo
    lee el flag bajo el lock y emite fuera. La diferencia no es teorica: con la
    emision fuera del lock queda una ventana entre soltar el lock y llamar a
    emitir(), y ahi cabe un cerrar() entero de otro hilo — el AgenteFin sale
    DESPUES del WorkflowFin con tardio=False, que es justo la sorpresa que el
    defecto 3 prohibe.

    El azar no caza esa ventana (300 rondas de carrera, 0 violaciones en las
    dos variantes: es demasiado estrecha), asi que aca se FUERZA: se engancha
    _emitir para que otro hilo llame a cerrar() justo cuando sale el AgenteFin.
    Emitiendo fuera del lock ese hilo entra y cierra primero; emitiendo dentro
    se queda bloqueado hasta que el AgenteFin ya salio.
    """
    from cognia.agent import workflows as W

    c = _corrida(total_agentes=1)
    real_emitir, disparado, hilos = W._emitir, [], []

    def _con_gancho(evento):
        if isinstance(evento, ux.AgenteFin) and not disparado:
            disparado.append(True)
            h = threading.Thread(target=c.cerrar)
            h.start()
            hilos.append(h)
            h.join(1.0)         # si el lock lo frena, expira y seguimos
        return real_emitir(evento)

    W._emitir = _con_gancho
    try:
        agente(c, "p1", completar_fn=_Stub([_Resp(texto="ok")]),
               indice=1, total=1, fase="pasos")
    finally:
        W._emitir = real_emitir
        for h in hilos:
            h.join(5)
        c.cerrar()

    assert disparado, "el gancho no llego a dispararse: el test no midio nada"
    fin_ag, wf_fin = _de(bus, ux.AgenteFin)[0], _de(bus, ux.WorkflowFin)[0]
    tarde = bus.index(fin_ag) > bus.index(wf_fin)
    assert (not tarde) or fin_ag.tardio, (
        "AgenteFin emitido tras WorkflowFin y sin tardio=True")


def test_el_cierre_declara_cuantos_quedaron_colgando(dir_wf, bus):
    """La otra mitad de DEFECTO 3: el consumidor se entera EN EL CIERRE de que
    hay filas que van a llegar tarde, sin tener que contar eventos."""
    c, soltar, esperar = _corrida_con_timeout(bus)
    try:
        c.cerrar()
        f = _de(bus, ux.WorkflowFin)[0]
        assert f.colgando == 1
        assert "colgando" in f.resumen and f.ok is False
    finally:
        soltar.set()
        esperar()


def test_una_corrida_sana_no_declara_faltantes(dir_wf, bus):
    """El contra-caso: los campos nuevos no pueden ensuciar el camino feliz ni
    convertir un cierre bueno en fallo."""
    c = _corrida(total_agentes=2)
    agente(c, "uno", completar_fn=_Stub([_Resp(texto="a")]),
           indice=1, total=2, fase="pasos")
    agente(c, "dos", completar_fn=_Stub([_Resp(texto="b")]),
           indice=2, total=2, fase="pasos")
    c.cerrar()
    f = _de(bus, ux.WorkflowFin)[0]
    assert (f.ok, f.agentes, f.fallidos) == (True, 2, 0)
    assert (f.arrancados, f.no_arrancados, f.colgando) == (2, 0, 0)
    assert f.resumen == ""
    assert all(e.tardio is False for e in _de(bus, ux.AgenteFin))


def test_los_agentes_de_mas_no_encogen_el_denominador(dir_wf, bus):
    """criticar() suma agentes que el adaptador no habia declarado (declara
    len(pasos) y luego lanza 3 criticos): el denominador es max(arrancados,
    declarados), nunca el declarado a secas."""
    c = _corrida(total_agentes=1)
    for i in (1, 2, 3):
        agente(c, f"p{i}", completar_fn=_Stub([_Resp(texto="ok")]))
    c.cerrar()
    f = _de(bus, ux.WorkflowFin)[0]
    assert (f.agentes, f.arrancados, f.no_arrancados) == (3, 3, 0)
    assert f.ok is True


# ------------------------------------------- el camino de excepcion no inventa

def test_la_excepcion_lleva_el_error_real_al_evento(dir_wf, bus):
    """DEFECTO 2. El _fin arrancaba con 'el agente termino sin resultado' y
    ningun camino de excepcion lo pisaba: un RuntimeError('backend caido')
    salia al bus como si el modelo hubiese contestado vacio. Son diagnosticos
    OPUESTOS —uno se arregla levantando el backend, el otro mirando el
    prompt— y renderer.py:529 afirma que el motor los distingue."""
    c = _corrida()

    def _revienta(mensajes, **kw):
        raise RuntimeError("backend caido")

    with pytest.raises(RuntimeError, match="backend caido"):
        agente(c, "hola", completar_fn=_revienta)
    c.cerrar()

    fin = _de(bus, ux.AgenteFin)[0]
    assert fin.ok is False
    assert fin.motivo == "RuntimeError: backend caido", (
        f"el evento dice {fin.motivo!r}")
    assert "sin resultado" not in fin.motivo


def test_la_excepcion_deja_linea_de_journal(dir_wf, bus):
    """El evento no puede ser la UNICA constancia: este camino no escribia
    journal, asi que un post-mortem sobre el disco no veia el fallo."""
    c = _corrida()

    def _revienta(mensajes, **kw):
        raise ValueError("json podrido")

    with pytest.raises(ValueError):
        agente(c, "hola", completar_fn=_revienta)
    c.cerrar()

    lineas = [json.loads(l) for l in
              (c.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    de_agente = [l for l in lineas if l.get("tipo") == "agente"]
    assert len(de_agente) == 1, f"{len(de_agente)} lineas 'agente' en el journal"
    assert de_agente[0]["error"] == "ValueError: json podrido"
    # y NO puede volver como cache-hit en un resume: no hay resultado que servir
    assert "resultado" not in de_agente[0]


def test_el_motivo_de_la_excepcion_distingue_del_vacio(dir_wf, bus):
    """El contraste que pide el defecto: 'revento' y 'devolvio vacio' tienen
    que llegar distintos al consumidor."""
    c = _corrida()
    agente(c, "vacio", completar_fn=_Stub([_Resp(texto="")]))

    def _revienta(mensajes, **kw):
        raise RuntimeError("backend caido")

    with pytest.raises(RuntimeError):
        agente(c, "revienta", completar_fn=_revienta)
    c.cerrar()

    vacio, revento = _de(bus, ux.AgenteFin)
    assert (vacio.ok, vacio.motivo) == (True, "")   # contesto, aunque sea nada
    assert revento.ok is False and revento.motivo == "RuntimeError: backend caido"


def test_workflow_fin_declara_el_veredicto(dir_wf, bus):
    c = _corrida()
    c.cerrar(ok=False, resumen="el workflow fallo: boom")
    f = _de(bus, ux.WorkflowFin)[0]
    assert f.ok is False and "boom" in f.resumen


def test_la_clave_de_cache_no_depende_de_la_identidad(dir_wf, bus):
    """Si el indice entrase en el sha256, mover un paso de la posicion 3 a la
    2 invalidaria el resume entero."""
    c1 = _corrida()
    agente(c1, "pregunta cara", completar_fn=_Stub([_Resp(texto="caro")]),
           indice=1, total=3, fase="pasos", etiqueta="pregunta cara")
    c1.cerrar()

    c2 = _corrida(resume_de=c1.run_id)
    stub = _Stub([])                    # cualquier llamada revienta el test
    r = agente(c2, "pregunta cara", completar_fn=stub,
               indice=5, total=9, fase="pasos", etiqueta="otra etiqueta")
    c2.cerrar()
    assert r == "caro" and stub.llamadas == []
    assert [e for e in _de(bus, ux.AgenteFin) if e.cache_hit]


def test_el_journal_y_los_eventos_hablan_de_la_misma_clave(dir_wf, bus):
    """AgenteInicio.clave joinea con la linea del journal sin heuristicas."""
    c = _corrida()
    agente(c, "hola", completar_fn=_Stub([_Resp(texto="ok")]))
    c.cerrar()
    lineas = [json.loads(l) for l in
              (c.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    claves = {l["clave"] for l in lineas if l.get("tipo") == "agente"}
    assert _de(bus, ux.AgenteInicio)[0].clave in claves


# ------------------------------------------------- el bus jamas tumba nada

def test_un_suscriptor_roto_no_tumba_la_corrida(dir_wf, bus):
    def _roto(_ev):
        raise RuntimeError("suscriptor de mentira")

    ux.suscribir(_roto)
    try:
        c = _corrida()
        r = agente(c, "hola", completar_fn=_Stub([_Resp(texto="ok")]))
        c.cerrar()
    finally:
        ux.desuscribir(_roto)
    assert r == "ok"
    assert _de(bus, ux.AgenteFin)[0].ok is True


def test_un_bus_roto_de_raiz_no_tumba_la_corrida(dir_wf, monkeypatch):
    """Ni siquiera si emitir() —que es no-lanzante por contrato— revienta."""
    def _revienta(_ev):
        raise RuntimeError("bus roto")

    monkeypatch.setattr("cognia.agent.workflows.ux.emitir", _revienta)
    c = _corrida()
    r = agente(c, "hola", completar_fn=_Stub([_Resp(texto="ok")]))
    c.cerrar()
    assert r == "ok"
