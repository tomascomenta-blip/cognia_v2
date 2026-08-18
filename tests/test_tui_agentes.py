"""
test_tui_agentes.py -- La pantalla de agentes en vivo (cognia/tui/agentes.py).

QUE SE VERIFICA, Y POR QUE CADA COSA ES UN TEST Y NO UNA PROMESA DEL DOCSTRING:

1. LA PANTALLA SE ALIMENTA DEL PUENTE REAL, DESDE HILOS. Los eventos se emiten
   por cognia/ux/events.py desde threads de verdad (como hace el motor de
   workflows) contra una App VIVA. Nada de construir AgenteVista a mano: si el
   sellado del agente_id por ContextVar o el merge de colas del puente se
   rompen, este test tiene que caerse.

2. LA HONESTIDAD NO ES OPCIONAL. Con la cola del puente llena de verdad
   (cap_cola minimo + un hilo escupiendo tokens), el panel del agente TIENE que
   decir que descarto texto. Un panel que muestra un stream con agujeros como
   si fuera entero es el modo de fallo que este repo persigue, y el unico modo
   de que no vuelva es que su ausencia rompa la suite.

3. CERRAR NO CANCELA. Salir con esc no puede tocar el motor: el test comprueba
   que tras cerrar la pantalla el bus sigue aceptando eventos y nadie lanzo.

4. LAS ACCIONES MANDAN, Y LA PANTALLA NO TRADUCE LA RESPUESTA. Hasta el
   2026-08-18 aca vivia `test_las_acciones_estan_pero_no_mienten`, que fijaba
   lo contrario: que x / ctrl+x / el Input estaban DECLARADOS y sin cablear, y
   que el dia que se cablearan habia que venir a cambiarlo. Ese dia llego y el
   test se REEMPLAZO (no se borro: esta la tanda de tests de "MANDAR" abajo).
   Lo que se fija ahora es mas fuerte que "hacen algo": que la palabra del
   conjunto cerrado del envelope (aceptado | ya_cancelado | ya_termino |
   desconocido_agente | corrida_cerrada | desconocido_corrida | texto_vacio |
   buzon_lleno) y su detalle LLEGAN A LA PANTALLA sin que la vista los
   interprete. El motor es el de verdad (cognia.agent.workflows con corridas
   registradas y agentes en hilos); lo unico de juguete es `completar()`.

5. NI UN COLOR PROPIO. El .tcss no puede traer un hex: el color baja del tema,
   que baja de cognia/ux/paleta.py. Es el mismo test que ya protege app.tcss.

El arnes es app.run_test(size=(120, 38)) + export_screenshot, el mismo de
test_tui_foundation.py y compania.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path

import pytest
from textual.widgets import Input

from cognia.tui import agentes as mod_agentes
from cognia.tui import puente as mod_puente
from cognia.tui.agentes import (CASILLA_FALLO, CASILLA_OK, CASILLA_PENDIENTE,
                                PanelAgente, PantallaAgentes, corto,
                                descripcion_tool, miles, onda, run_corto,
                                segundos, tokens_de)
from cognia.tui.theme import COLORS
from cognia.ux import events

TCSS = Path(__file__).resolve().parents[1] / "cognia" / "tui" / "agentes.tcss"


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


def _correr_agente(aid: str, run_id: str, *, indice: int, total: int,
                   fase: str, etiqueta: str, rol: str = "", trozos: int = 12,
                   tool: str = "", cierre: dict | None = None) -> threading.Thread:
    """Un agente COMPLETO desde su propio hilo (lo que hace workflows.agente)."""
    def cuerpo() -> None:
        tok = events.marcar_agente(aid)
        try:
            events.emitir(events.AgenteInicio(
                run_id=run_id, agente_id=aid, indice=indice, total=total,
                fase=fase, etiqueta=etiqueta, rol=rol))
            if tool:
                events.emitir(events.ToolInicio(tool=tool, paso=1))
            for i in range(trozos):
                events.emitir(events.TokenTexto(texto=f"trozo-{i} "))
            if cierre is not None:
                events.emitir(events.AgenteFin(
                    run_id=run_id, agente_id=aid, indice=indice, total=total,
                    fase=fase, etiqueta=etiqueta, rol=rol, **cierre))
        finally:
            events.desmarcar_agente(tok)
    h = threading.Thread(target=cuerpo, daemon=True)
    h.start()
    return h


async def _asentar(pilot, veces: int = 12) -> None:
    """Deja correr el latido: el repintado NO es sincrono con los eventos (el
    puente marca sucio y el timer pinta), asi que un solo pause no alcanza."""
    for _ in range(veces):
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# 1. Formato y piezas puras (sin App: son las que se leen en cada cabecera)
# ---------------------------------------------------------------------------

def test_formato_es_el_del_producto():
    assert miles(1204) == "1.204"
    assert miles(0) == "0"
    assert segundos(12.34) == "12,3 s"
    assert corto("abcdefghij", 5) == "abcd…"
    assert corto("abc", 5) == "abc"
    # El run_id se acorta por la CABEZA: lo que identifica una corrida es su
    # final (el prefijo es igual en todas las de la misma sesion).
    assert run_corto("corrida-tls-0001", 16) == "corrida-tls-0001"
    largo = run_corto("run-2026-08-18-abcdef123456", 16)
    assert largo.startswith("…") and largo.endswith("123456") and len(largo) == 16


def test_los_tokens_estimados_se_declaran_estimados():
    """Un numero estimado presentado como medido es la mentira barata de todo
    panel de progreso: tokens_de() devuelve la bandera para que salga con '~'."""
    from cognia.tui.puente import AgenteVista
    vivo = AgenteVista(agente_id="a", chars_progreso=400)
    assert tokens_de(vivo) == (100, True)
    cerrado = AgenteVista(agente_id="a", chars_progreso=400, tokens=137)
    assert tokens_de(cerrado) == (137, False)


def test_la_onda_recorre_el_texto_y_usa_la_paleta():
    """El shimmer se mueve (dos fases distintas dan dos pintados distintos) y
    sus extremos son colores de la paleta, no hex inventados."""
    texto = "generando" * 4
    a, b = onda(texto, 0), onda(texto, 3)
    assert a.plain == b.plain == texto
    assert [(s.start, s.end) for s in a.spans] != [(s.start, s.end) for s in b.spans]
    # El brillo va de 'detalle' a 'texto' de la paleta.
    assert mod_agentes.RAMPA_ONDA[3].lower() == COLORS["text"].lower()
    assert len(set(mod_agentes.RAMPA_ONDA)) >= 4     # es una rampa, no un flash
    # Y no cuesta un estilo por celda: son tramos.
    assert len(a.spans) <= len(mod_agentes.RAMPA_ONDA) + 1


def test_la_descripcion_de_tool_sale_del_catalogo_real():
    """FIJA por herramienta (que ES la tool), no los argumentos de la llamada."""
    desc = descripcion_tool("leer_archivo")
    assert desc and "archivo" in desc.lower()
    assert descripcion_tool("leer_archivo") == desc      # estable
    assert descripcion_tool("no_existe_esta_tool") == ""
    assert descripcion_tool("") == ""


def test_el_tcss_no_tiene_ni_un_color_propio():
    """Mismo contrato que app.tcss: el color baja del tema -> paleta.py."""
    hoja = TCSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", hoja, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios), \
        "hay un hex en agentes.tcss: el color tiene que venir del tema"


# ---------------------------------------------------------------------------
# 2. La pantalla, alimentada por el puente REAL desde hilos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_un_panel_por_agente_montado_en_vivo(bus_limpio):
    """Tres agentes en tres hilos -> tres paneles, con SU texto cada uno."""
    RUN = "run-tres"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="revisar TLS", total_agentes=6))
        hilos = [
            _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=6,
                           fase="pasos", etiqueta="leer handshake.py",
                           tool="leer_archivo"),
            _correr_agente(f"{RUN}#pasos.2@2", RUN, indice=2, total=6,
                           fase="pasos", etiqueta="buscar el nonce", rol="worker"),
            _correr_agente(f"{RUN}#critica.3@3", RUN, indice=3, total=6,
                           fase="critica", etiqueta="resume TLS", rol="worker"),
        ]
        for h in hilos:
            h.join(timeout=5)
        await _asentar(pilot)

        paneles = list(app.query(PanelAgente))
        assert len(paneles) == 3, f"esperaba 3 paneles, hay {len(paneles)}"
        # Cada panel muestra el texto de SU agente y su cabecera.
        titulos = [p.border_title for p in paneles]
        assert any("«resume TLS»" in t for t in titulos), titulos
        # Con DOS columnas el panel mide 58 celdas y la cabecera completa del
        # encargo ("2/6 · critica · «resume TLS» · worker · 1.204 tok · 12,3 s")
        # no entra: son 57 mas el "[n]" del atajo. La degradacion esta ordenada
        # -- se recorta la etiqueta, despues se va el rol, despues la fase --
        # y los NUMEROS no se sacrifican nunca, porque son lo unico que cambia.
        assert all("tok" in t and " s" in t for t in titulos), titulos
        assert all(t.startswith(f"[{i}] {i}/6") for i, t in enumerate(titulos, 1)), titulos
        assert all(len(t) <= 56 for t in titulos), [len(t) for t in titulos]
        for p in paneles:
            assert "trozo-0" in p._texto.content
        # La tool se describe por lo que ES, del catalogo.
        lineas = [p._linea.content.plain for p in paneles]
        assert any("leer_archivo" in l and "archivo" in l.lower() for l in lineas), lineas


@pytest.mark.asyncio
async def test_con_un_solo_agente_la_cabecera_va_entera(bus_limpio):
    """El formato del encargo, literal: "2/6 · critica · «resume TLS» · worker
    · 1.204 tok · 12,3 s". Con un agente la rejilla va a UNA columna y el panel
    tiene las 118 celdas: aca no hay excusa para recortar nada."""
    RUN = "run-uno"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=6))
        _correr_agente(f"{RUN}#critica.2@2", RUN, indice=2, total=6,
                       fase="critica", etiqueta="resume TLS", rol="worker",
                       cierre=dict(ok=True, tokens=1204, intentos=1,
                                   duracion_s=12.3, resumen="ok")).join(timeout=5)
        await _asentar(pilot)
        panel = app.query_one(PanelAgente)
        assert panel.border_title == (
            "[1] 2/6 · critica · «resume TLS» · worker · 1.204 tok · 12,3 s"),             panel.border_title


@pytest.mark.asyncio
async def test_estado_y_plan_se_marcan_en_vivo(bus_limpio):
    """ok / fallo / corriendo: clase CSS, subtitulo y casilla del plan."""
    RUN = "run-estados"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="revisar TLS", total_agentes=3))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=3, fase="pasos",
                       etiqueta="leer", cierre=dict(ok=True, tokens=1204,
                                                    intentos=1, duracion_s=12.3,
                                                    resumen="380 lineas")
                       ).join(timeout=5)
        _correr_agente(f"{RUN}#pasos.2@2", RUN, indice=2, total=3, fase="pasos",
                       etiqueta="parchear",
                       cierre=dict(ok=False, tokens=311, intentos=2,
                                   duracion_s=4.8,
                                   motivo="RuntimeError: backend caido")
                       ).join(timeout=5)
        _correr_agente(f"{RUN}#critica.3@3", RUN, indice=3, total=3,
                       fase="critica", etiqueta="resume", trozos=6)
        await _asentar(pilot)

        por_id = {p.agente_id: p for p in app.query(PanelAgente)}
        ok = por_id[f"{RUN}#pasos.1@1"]
        fallo = por_id[f"{RUN}#pasos.2@2"]
        vivo = por_id[f"{RUN}#critica.3@3"]
        assert ok.has_class("est-ok") and "ok" in ok.border_subtitle
        assert fallo.has_class("est-fallo") and "fallo" in fallo.border_subtitle
        assert vivo.has_class("est-corriendo")
        # El color es el SEMANTICO de la paleta, no uno inventado.
        assert COLORS["err"] in fallo._linea.content.markup or any(
            COLORS["err"] in str(s.style) for s in fallo._linea.content.spans)
        assert "backend caido" in fallo._linea.content.plain
        # Los tokens del que cerro son EXACTOS (sin '~'); los del vivo, estimados.
        assert "1.204 tok" in ok.border_title and "~" not in ok.border_title
        assert "~" in vivo.border_title
        # El plan: una casilla por agente, marcandose en vivo.
        plan = app.query_one("#plan").content.plain
        assert plan.count(CASILLA_OK) == 1, plan
        assert plan.count(CASILLA_FALLO) == 1, plan
        assert plan.count(CASILLA_PENDIENTE) == 1, plan
        # Y la cabecera cuenta la corrida.
        cab = app.query_one("#cabecera").content.plain
        assert "revisar TLS" in cab and "3/3 agentes" in cab and "1 vivos" in cab


@pytest.mark.asyncio
async def test_el_plan_dice_cuantas_tareas_no_entran(bus_limpio):
    """Con ocho agentes el plan no cabe en 120 celdas. Se corta, pero DICE
    cuantas faltan: una tarea escondida en la pantalla que existe para que no
    se escondan es el mismo bug que el texto con agujeros."""
    RUN = "run-plan"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=8))
        for k in range(1, 9):
            _correr_agente(f"{RUN}#pasos.{k}@{k}", RUN, indice=k, total=8,
                           fase="pasos", etiqueta=f"tarea numero {k}",
                           trozos=2).join(timeout=5)
        await _asentar(pilot)
        plan = app.query_one("#plan").content.plain
        assert "más" in plan, plan
        visibles = plan.count(CASILLA_PENDIENTE)
        faltan = int(re.search(r"\+(\d+) más", plan).group(1))
        assert visibles + faltan == 8, (visibles, faltan, plan)
        assert len(plan) <= 120, len(plan)


@pytest.mark.asyncio
async def test_el_panel_dice_que_el_puente_descarto_texto(bus_limpio):
    """LA PRUEBA QUE MAS IMPORTA. Con la cola del puente llena de verdad, el
    panel tiene que declarar el agujero. Sin esto, la pantalla muestra un
    stream incompleto como si fuera la respuesta del modelo."""
    RUN = "run-descarte"
    # cap_cola minusculo: el puente se crea ANTES que la App (conectar_puente
    # reusa el del proceso) y el descarte ocurre por backpressure REAL.
    mod_puente.conectar_puente(None, cap_cola=4)
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="revisar TLS", total_agentes=1))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=1, fase="pasos",
                       etiqueta="leer", trozos=600).join(timeout=10)
        await _asentar(pilot)

        p = mod_puente.puente_activo()
        a = p.estado.agente(f"{RUN}#pasos.1@1")
        assert a is not None and a.chars_perdidos > 0 and not a.completo, \
            "el arnes no provoco descarte: el test no esta midiendo nada"

        panel = app.query_one(PanelAgente)
        assert panel.has_class("incompleto")
        aviso = panel._aviso.content.plain
        assert "DESCARTADOS" in aviso and miles(a.chars_perdidos) in aviso
        assert "agujeros" in aviso
        assert panel._aviso.styles.display == "block"
        assert "!" in panel.border_title
        # Y la cabecera de la corrida tambien lo dice: si la UI se quedo atras,
        # el numero tiene que estar donde se mira primero.
        cab = app.query_one("#cabecera").content.plain
        assert "puente" in cab and "chars" in cab


@pytest.mark.asyncio
async def test_seleccion_por_teclado_y_por_clic(bus_limpio):
    """El clic enfoca, y SIEMPRE hay un atajo equivalente (1..9 y tab)."""
    RUN = "run-foco"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=2))
        for k in (1, 2):
            _correr_agente(f"{RUN}#pasos.{k}@{k}", RUN, indice=k, total=2,
                           fase="pasos", etiqueta=f"paso {k}", trozos=4).join(timeout=5)
        await _asentar(pilot)
        paneles = {p.orden: p for p in app.query(PanelAgente)}
        assert set(paneles) == {1, 2}

        await pilot.press("2")
        await pilot.pause()
        assert paneles[2].has_focus, "la tecla 2 no enfoco el panel 2"

        await pilot.press("1")
        await pilot.pause()
        assert paneles[1].has_focus

        # El clic hace lo mismo (mismo camino: on_click -> focus).
        paneles[2].on_click()
        await pilot.pause()
        assert paneles[2].has_focus

        # tab recorre PANELES (no se mete en los scrollables de adentro).
        await pilot.press("tab")
        await pilot.pause()
        assert paneles[1].has_focus, "tab no paso al panel siguiente"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert paneles[2].has_focus, "shift+tab no volvio al anterior"


@pytest.mark.asyncio
async def test_vista_vacia_sin_corrida(bus_limpio):
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await _asentar(pilot, 4)
        assert app.query_one("#vacio").styles.display == "block"
        assert app.query_one("#rejilla").styles.display == "none"
        assert not list(app.query(PanelAgente))
        assert "Sin corrida" in app.query_one("#cabecera").content.plain


@pytest.mark.asyncio
async def test_cerrar_no_cancela_nada_y_no_deja_timer(bus_limpio):
    """esc cierra la vista; el workflow sigue y el bus sigue aceptando eventos.

    Ademas: el timer se para en on_unmount. Un tick con el DOM ya desarmado
    revienta con NoMatches y Textual lo escupe como traceback -- la ultima
    impresion de la pantalla era un stack trace (paso de verdad)."""
    RUN = "run-cierre"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=1))
        h = _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=1,
                           fase="pasos", etiqueta="paso", trozos=4)
        h.join(timeout=5)
        await _asentar(pilot, 6)
        assert app._timer is not None
        await pilot.press("escape")
        await pilot.pause()
    assert app._timer is None, "el latido sigue vivo despues de cerrar"

    # El motor sigue: emitir despues de cerrar no lanza ni cancela nada.
    events.emitir(events.TokenTexto(texto="el workflow sigue"))
    events.emitir(events.AgenteFin(run_id=RUN, agente_id=f"{RUN}#pasos.1@1",
                                   ok=True, tokens=10, duracion_s=1.0))
    events.emitir(events.WorkflowFin(run_id=RUN, nombre="x", ok=True, agentes=1))


@pytest.mark.asyncio
async def test_las_acciones_ya_no_son_una_maqueta(bus_limpio):
    """REEMPLAZA a `test_las_acciones_estan_pero_no_mienten` (2026-08-18).

    Aquel test fijaba que x / ctrl+x / el Input estaban declarados y SIN
    cablear ("en la tanda siguiente"), y decia en su docstring que el dia que
    se cablearan tenia que fallar. Fallo, y esto es lo que lo reemplaza: el
    campo esta habilitado, las teclas ya no avisan de un hueco y ninguna
    descripcion dice "(prox.)". Lo que HACEN se verifica contra el motor real
    en la seccion de MANDAR."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        entrada = app.query_one("#hablar")
        assert not entrada.disabled
        assert "tanda siguiente" not in entrada.placeholder
        # El campo NO se queda con el foco de arranque: si no, `2` escribe un
        # "2" en vez de enfocar el panel 2.
        assert not entrada.has_focus and app.focused is None

        teclas = {b.key: b.description for b in PantallaAgentes.BINDINGS
                  if hasattr(b, "key")}
        assert teclas.get("x") == "Interrumpir agente", teclas
        assert teclas.get("ctrl+x") == "Cancelar corrida", teclas
        assert "prox." not in " ".join(teclas.values())
        assert not hasattr(PantallaAgentes, "action_pendiente")
        for accion in ("action_interrumpir", "action_cancelar_corrida",
                       "action_hablar", "on_input_submitted"):
            assert hasattr(PantallaAgentes, accion), accion


@pytest.mark.asyncio
async def test_una_corrida_nueva_tira_los_paneles_de_la_anterior(bus_limpio):
    """La pantalla mira la ULTIMA corrida: los paneles viejos no se quedan
    colgados mostrando texto de otra cosa."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id="vieja", nombre="v", total_agentes=1))
        _correr_agente("vieja#pasos.1@1", "vieja", indice=1, total=1,
                       fase="pasos", etiqueta="vieja", trozos=4).join(timeout=5)
        await _asentar(pilot, 6)
        assert len(list(app.query(PanelAgente))) == 1

        events.emitir(events.WorkflowInicio(run_id="nueva", nombre="n", total_agentes=2))
        for k in (1, 2):
            _correr_agente(f"nueva#pasos.{k}@{k}", "nueva", indice=k, total=2,
                           fase="pasos", etiqueta=f"nueva {k}", trozos=4).join(timeout=5)
        await _asentar(pilot, 10)
        paneles = list(app.query(PanelAgente))
        assert len(paneles) == 2, [p.agente_id for p in paneles]
        assert all(p.agente_id.startswith("nueva") for p in paneles)


@pytest.mark.asyncio
async def test_el_shimmer_solo_anima_lo_que_genera(bus_limpio):
    """La onda se mueve en el panel vivo y NO en el que ya cerro: el gasto se
    apaga solo cuando el agente termina."""
    RUN = "run-shimmer"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=2))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=2, fase="pasos",
                       etiqueta="cerrado", trozos=4,
                       cierre=dict(ok=True, tokens=10, intentos=1, duracion_s=1.0,
                                   resumen="listo")).join(timeout=5)
        _correr_agente(f"{RUN}#pasos.2@2", RUN, indice=2, total=2, fase="pasos",
                       etiqueta="vivo", trozos=4, tool="leer_archivo").join(timeout=5)
        await _asentar(pilot, 8)
        por_id = {p.agente_id: p for p in app.query(PanelAgente)}
        cerrado = por_id[f"{RUN}#pasos.1@1"]
        vivo = por_id[f"{RUN}#pasos.2@2"]

        def spans(panel):
            r = panel._linea.content
            return [(s.start, s.end, str(s.style)) for s in r.spans]

        quieto_0, vivo_0 = spans(cerrado), spans(vivo)
        await _asentar(pilot, 4)
        assert spans(cerrado) == quieto_0, "el panel cerrado sigue animando"
        assert spans(vivo) != vivo_0, "el panel vivo no anima"


@pytest.mark.asyncio
async def test_captura_de_la_pantalla_con_tres_agentes(bus_limpio):
    """La captura REAL (export_screenshot, 120x38): el SVG tiene que traer la
    cabecera, el plan, los tres paneles y el pie. Es el mismo arnes con el que
    se miraron las capturas a mano."""
    RUN = "run-captura"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="revisar TLS", total_agentes=6))
        for k, (fase, etq) in enumerate((("pasos", "leer handshake.py"),
                                         ("pasos", "buscar el nonce"),
                                         ("critica", "resume TLS")), start=1):
            _correr_agente(f"{RUN}#{fase}.{k}@{k}", RUN, indice=k, total=6,
                           fase=fase, etiqueta=etq, rol="worker" if k > 1 else "",
                           trozos=8).join(timeout=5)
        await _asentar(pilot)
        svg = app.export_screenshot()
    # El SVG de Textual escribe cada espacio como &#160;: comparar con espacios
    # normales mediria la codificacion del export, no lo que se dibujo.
    plano = svg.replace("&#160;", " ")
    assert "revisar TLS" in plano
    assert CASILLA_PENDIENTE in plano        # el plan se dibujo
    assert "resume" in plano and "nonce" in plano
    assert "Salir" in plano                  # el pie con los atajos
    # Las acciones se ven en el pie CON SU NOMBRE. Hasta el 2026-08-18 aca se
    # exigia "tanda siguiente" (el hueco declarado); ahora estan cableadas y lo
    # que tiene que verse es que teclas mandan.
    assert "Interrumpir agente" in plano
    assert "Cancelar corrida" in plano
    assert "tanda siguiente" not in plano


# ---------------------------------------------------------------------------
# 3. Los TRECE defectos de la maqueta (revision del 2026-08-18).
#
# Cada uno de estos tests FALLA con el codigo anterior al arreglo. Los numeros
# no son inventados: salen de leer el compositor de Textual (lo que se pinta de
# verdad), no el .plain del renderable -- justamente porque el bug era que el
# renderable decia una cosa y la pantalla mostraba otra.
# ---------------------------------------------------------------------------

def _filas(app) -> list[str]:
    """La pantalla RENDERIZADA, fila por fila. Es la unica fuente que no
    miente: `Static.content.plain` trae el texto que se quiso pintar, no el
    que entro en las celdas."""
    strips = app.screen._compositor.render_strips()
    return ["".join(seg.text for seg in strip) for strip in strips]


def _pintado(app, widget) -> str:
    """Lo que se ve del widget, recortado a su region en la pantalla."""
    reg = app.screen._compositor.visible_widgets[widget][0]
    return _filas(app)[reg.y][reg.x:reg.x + reg.width]


MOTIVO_LARGO = ("RuntimeError: backend caido (connection refused a "
                "127.0.0.1:8080 tras 3 reintentos con backoff 1/2/4 s)")


def test_la_aritmetica_del_ancho_esta_en_un_solo_sitio():
    """D1/D2/D13 son el MISMO bug: dos anchos utiles distintos y la cuenta
    escrita a mano en tres lugares. MEDIDO en un panel de 58 exteriores
    (scratchpad/t5b_arreglos/p1_ancho.py): el border-title entra en 52 y el
    contenido en 54."""
    from cognia.tui.agentes import ancho_contenido, ancho_titulo
    assert ancho_titulo(58) == 52
    assert ancho_contenido(58) == 54
    # Y no devuelven basura si el panel todavia no midio.
    assert ancho_titulo(0) == 52 and ancho_contenido(0) == 54
    assert ancho_titulo(10) >= 1 and ancho_contenido(10) >= 1


@pytest.mark.asyncio
async def test_el_titulo_no_pierde_la_cola_a_dos_columnas(bus_limpio):
    """D1 + D11. Con dos columnas el panel mide 58 y el titulo entra en 52, no
    en 54: la cuenta vieja daba por buenos titulos de 53-54 que Textual pintaba
    con elipsis, y lo que la elipsis se comia era la COLA -- o sea los tokens,
    el reloj y el '!' de honestidad, que es todo lo que promete no sacrificar."""
    RUN = "run-ancho"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=3))
        for k, etq in enumerate(("leer handshake.py", "parchear el nonce",
                                 "resume TLS"), start=1):
            _correr_agente(f"{RUN}#pasos.{k}@{k}", RUN, indice=k, total=3,
                           fase="pasos", etiqueta=etq, rol="worker",
                           cierre=dict(ok=True, tokens=1204, intentos=1,
                                       duracion_s=12.3, resumen="ok")).join(timeout=5)
        await _asentar(pilot)
        for p in app.query(PanelAgente):
            util = p.outer_size.width - 6
            assert len(p.border_title) <= util, (p.border_title, util)
            # Lo que se ve en el BORDE trae el titulo entero (sin la elipsis
            # que ponia Textual) y con los numeros puestos.
            borde = _pintado(app, p)
            assert p.border_title in borde, (p.border_title, borde)
            assert "1.204 tok" in borde and "12,3 s" in borde, borde


@pytest.mark.asyncio
async def test_el_motivo_del_fallo_no_se_corta_en_seco(bus_limpio):
    """D2. La linea de estado se recortaba a 74 chars, un numero sin relacion
    con el panel: con dos columnas el panel tiene 54 utiles y el resto
    desaparecia SIN elipsis y sin ninguna marca -- justo donde vive el motivo
    del fallo."""
    RUN = "run-motivo"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=2))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=2, fase="pasos",
                       etiqueta="ok", cierre=dict(ok=True, tokens=1, intentos=1,
                                                  duracion_s=1.0, resumen="ok")
                       ).join(timeout=5)
        _correr_agente(f"{RUN}#pasos.2@2", RUN, indice=2, total=2, fase="pasos",
                       etiqueta="parchear",
                       cierre=dict(ok=False, tokens=311, intentos=2,
                                   duracion_s=4.8, motivo=MOTIVO_LARGO)
                       ).join(timeout=5)
        await _asentar(pilot)
        fallo = {p.agente_id: p for p in app.query(PanelAgente)}[f"{RUN}#pasos.2@2"]
        util = fallo.outer_size.width - 4
        quiso = fallo._linea.content.plain
        assert len(quiso) <= util, (len(quiso), util, quiso)
        # Se corto, y por eso TIENE que llevar la marca.
        assert quiso.endswith("…"), quiso
        assert _pintado(app, fallo._linea).rstrip() == quiso.rstrip()


@pytest.mark.asyncio
async def test_el_badge_de_descarte_sobrevive_a_una_terminal_angosta(bus_limpio):
    """D13, hermano del D1. A 80 columnas la cabecera no entra y el badge
    quedaba decapitado en el signo ('... 1,3 s  !'): se perdian los dos numeros
    que dicen que la vista miente."""
    RUN = "run-descarte-angosto-0001"
    mod_puente.conectar_puente(None, cap_cola=4)
    app = PantallaAgentes()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(
            run_id=RUN, nombre="revisar el handshake TLS entero", total_agentes=1))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=1, fase="pasos",
                       etiqueta="leer", trozos=900).join(timeout=20)
        await _asentar(pilot, 20)
        d = mod_puente.puente_activo().estado.descartes
        assert d.hubo, "el arnes no provoco descarte: el test no mide nada"
        visto = _pintado(app, app.query_one("#cabecera"))
        assert miles(d.total) in visto, visto
        assert miles(d.chars) in visto, visto


@pytest.mark.asyncio
async def test_el_plan_conserva_el_color_cuando_la_corrida_cierra(bus_limpio):
    """D3. `color if a.viva else COLORS['text']` mandaba ok/fallo/cancelado al
    mismo gris claro: cuando la corrida cerraba, el plan dejaba de decir que
    fallo. Los COLORS['ok']/['err'] de tres lineas antes eran codigo muerto."""
    RUN = "run-colores"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=2))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=2, fase="pasos",
                       etiqueta="bien", cierre=dict(ok=True, tokens=1, intentos=1,
                                                    duracion_s=1.0, resumen="ok")
                       ).join(timeout=5)
        _correr_agente(f"{RUN}#pasos.2@2", RUN, indice=2, total=2, fase="pasos",
                       etiqueta="mal", cierre=dict(ok=False, tokens=1, intentos=1,
                                                   duracion_s=1.0, motivo="boom")
                       ).join(timeout=5)
        events.emitir(events.WorkflowFin(run_id=RUN, nombre="x", ok=False, agentes=2))
        await _asentar(pilot)
        plan = app.query_one("#plan").content
        estilos = {str(s.style) for s in plan.spans}
        assert any(COLORS["ok"] in e for e in estilos), estilos
        assert any(COLORS["err"] in e for e in estilos), estilos


@pytest.mark.asyncio
async def test_el_plan_no_esconde_la_ultima_tarea_por_la_cola(bus_limpio):
    """D12. La cola de "cuantas faltan" se reservaba tambien para el ULTIMO
    item, asi que una tarea que entraba se cambiaba por un cartel de seis
    celdas que avisa de tareas escondidas. Si entran todas, estan todas."""
    RUN = "run-cola"
    app = PantallaAgentes()
    etiquetas = ["tarea numero uno18", "tarea numero dos18",
                 "tarea numero tre18", "tarea numero cua18", "final de todo"]
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=5))
        for k, e in enumerate(etiquetas, start=1):
            _correr_agente(f"{RUN}#pasos.{k}@{k}", RUN, indice=k, total=5,
                           fase="pasos", etiqueta=e, trozos=2).join(timeout=5)
        await _asentar(pilot)
        plan = app.query_one("#plan").content.plain
        # El caso esta construido para caer JUSTO en el borde: las cinco
        # entran (6 + 4*23 + 18 = 116 <= 118), la cola no (122 > 118).
        assert "final de todo" in plan, plan
        assert "ás" not in plan, plan
        assert plan.count(CASILLA_PENDIENTE) == 5, plan
        assert len(plan) <= 118, len(plan)


@pytest.mark.asyncio
async def test_el_texto_de_un_agente_se_lee_con_el_teclado(bus_limpio):
    """D4, el que mas importa: sin esto, 275 de 300 filas solo se alcanzaban
    con la rueda del raton, y la regla del dueno es que el clic NUNCA puede ser
    la unica via. El cuerpo es can_focus=False (para que tab no se quede
    adentro), asi que las bindings de scroll tienen que estar en el PANEL."""
    RUN = "run-leer"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=1))
        aid = f"{RUN}#pasos.1@1"
        _correr_agente(aid, RUN, indice=1, total=1, fase="pasos",
                       etiqueta="largo", trozos=2).join(timeout=10)
        # 300 LINEAS de verdad: el _correr_agente del arnes manda trozos sin
        # salto, y 300 trozos son una sola linea larga que wrappea en 24 filas
        # -- no alcanza para que el scroll signifique algo.
        tok = events.marcar_agente(aid)
        try:
            for i in range(300):
                events.emitir(events.TokenTexto(texto=f"linea {i} del agente\n"))
            events.emitir(events.AgenteFin(run_id=RUN, agente_id=aid, indice=1,
                                           total=1, fase="pasos", etiqueta="largo",
                                           ok=True, tokens=10, intentos=1,
                                           duracion_s=1.0, resumen="listo"))
        finally:
            events.desmarcar_agente(tok)
        await _asentar(pilot)
        panel = app.query_one(PanelAgente)
        cuerpo = panel._cuerpo
        assert cuerpo.max_scroll_y > 20, cuerpo.max_scroll_y
        await pilot.press("1")
        await pilot.pause()
        assert panel.has_focus

        await pilot.press("end")
        await _asentar(pilot, 3)
        assert cuerpo.scroll_y == cuerpo.max_scroll_y, cuerpo.scroll_y
        await pilot.press("home")
        await _asentar(pilot, 3)
        assert cuerpo.scroll_y == 0, cuerpo.scroll_y
        await pilot.press("down")
        await _asentar(pilot, 3)
        assert cuerpo.scroll_y == 1, cuerpo.scroll_y
        await pilot.press("pagedown")
        await _asentar(pilot, 3)
        una_pagina = cuerpo.scroll_y
        assert una_pagina > 1, una_pagina
        await pilot.press("up")
        await _asentar(pilot, 3)
        assert cuerpo.scroll_y == una_pagina - 1, (cuerpo.scroll_y, una_pagina)
        await pilot.press("pageup")
        await _asentar(pilot, 3)
        assert cuerpo.scroll_y < una_pagina


@pytest.mark.asyncio
async def test_leer_para_arriba_suelta_la_cola_y_fin_la_reengancha(bus_limpio):
    """Corolario del D4: de nada sirve poder subir si el proximo token te
    devuelve al final. Mientras el agente genera, desplazarse a mano suelta el
    auto-scroll; Fin lo vuelve a enganchar."""
    RUN = "run-cola-viva"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=1))
        aid = f"{RUN}#pasos.1@1"
        _correr_agente(aid, RUN, indice=1, total=1, fase="pasos",
                       etiqueta="vivo", trozos=200).join(timeout=10)
        await _asentar(pilot)
        panel = app.query_one(PanelAgente)
        assert panel._corriendo, "el agente tiene que seguir vivo"
        await pilot.press("1")
        await pilot.press("home")
        await _asentar(pilot, 3)
        assert panel._cuerpo.scroll_y == 0
        # Llega mas texto del MISMO agente vivo: no puede robarnos la lectura.
        tok = events.marcar_agente(aid)
        try:
            for i in range(40):
                events.emitir(events.TokenTexto(texto=f"nueva linea {i}\n"))
        finally:
            events.desmarcar_agente(tok)
        await _asentar(pilot, 8)
        assert panel._cuerpo.scroll_y == 0, panel._cuerpo.scroll_y
        # Y Fin reengancha: vuelve al final y se queda ahi.
        await pilot.press("end")
        await _asentar(pilot, 3)
        assert panel._seguir_cola


@pytest.mark.asyncio
async def test_la_pista_dice_como_leer_el_texto(bus_limpio):
    """D10. La pista decia solo como SELECCIONAR: la unica via documentada para
    leer un texto largo era la rueda."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        pista = app.query_one("#pista").content.plain
        assert "tab" in pista and "1..9" in pista
        for tecla in ("↑↓", "Pág", "Inicio/Fin"):
            assert tecla in pista, pista
        # Y desde 2026-08-18 tambien dice como MANDAR: una tecla que corta un
        # agente y no esta escrita en ningun lado se descubre por accidente.
        for tecla in ("x", "ctrl+x", "enter"):
            assert tecla in pista, pista
        assert app.query_one("#pista").size.height == 1
    # En una terminal angosta lo sigue diciendo TODO, en dos filas. Antes se
    # recortaba a una version mas corta; con las teclas de accion adentro, esa
    # version tendria que callarse algo, y la pista es justo la fila que existe
    # para no callarse nada (misma decision que la franja de desconexion).
    app2 = PantallaAgentes()
    async with app2.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        pista = app2.query_one("#pista").content.plain
        assert "↑↓" in pista and "Inicio/Fin" in pista, pista
        for tecla in ("x", "ctrl+x", "enter"):
            assert tecla in pista, pista
        assert app2.query_one("#pista").size.height == 2, "no se envolvio"


@pytest.mark.asyncio
async def test_con_todo_cerrado_la_pantalla_deja_de_pintar(bus_limpio):
    """D5, EL GRANDE. El docstring prometia que 'la corrida entera cerrada
    cuesta lo mismo que una pantalla quieta' y era falso: la rama del agente
    terminado no tenia guarda de firma, y cabecera/plan hacian update() cada
    cuadro. MEDIDO antes del arreglo: 49 cuadros -> 245 update() reales."""
    RUN = "run-quieto"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=3))
        for k in (1, 2, 3):
            _correr_agente(f"{RUN}#pasos.{k}@{k}", RUN, indice=k, total=3,
                           fase="pasos", etiqueta=f"t{k}", trozos=4,
                           cierre=dict(ok=True, tokens=10, intentos=1,
                                       duracion_s=1.0, resumen="listo")).join(timeout=5)
        events.emitir(events.WorkflowFin(run_id=RUN, nombre="x", ok=True, agentes=3))
        await _asentar(pilot, 20)

        updates = {"n": 0}

        def espiar(w):
            orig = w.update

            def envuelto(*a, _o=orig, **k):
                updates["n"] += 1
                return _o(*a, **k)
            w.update = envuelto

        for p in app.query(PanelAgente):
            for w in (p._linea, p._aviso, p._texto):
                espiar(w)
        for wid in ("#cabecera", "#plan"):
            espiar(app.query_one(wid))

        antes = app.metricas_vista()
        await _asentar(pilot, 30)
        despues = app.metricas_vista()
        cuadros = despues["cuadros"] - antes["cuadros"]
        assert cuadros >= 8, cuadros        # el latido SI corre
        assert updates["n"] == 0, f"{updates['n']} update() con todo cerrado"
        # Y la metrica lo refleja: 'repintados' cuenta cuadros que PINTARON.
        assert despues["repintados"] == antes["repintados"], (antes, despues)


@pytest.mark.asyncio
async def test_la_pantalla_vacia_no_repinta(bus_limpio):
    """D5, segunda mitad: sin ninguna corrida la cabecera se reescribia una vez
    por cuadro para decir siempre lo mismo (medido: 35 cuadros -> 35 update)."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await _asentar(pilot, 8)
        cab = app.query_one("#cabecera")
        n = {"v": 0}
        orig = cab.update
        cab.update = lambda *a, **k: (n.__setitem__("v", n["v"] + 1), orig(*a, **k))[1]
        c0 = app.metricas_vista()["cuadros"]
        await _asentar(pilot, 25)
        assert app.metricas_vista()["cuadros"] - c0 >= 8
        assert n["v"] == 0, f"{n['v']} update() con la pantalla vacia"


@pytest.mark.asyncio
async def test_repintados_no_es_un_alias_de_cuadros(bus_limpio):
    """D7. metricas_vista()['repintados'] se incrementaba al final de cada
    latido con corrida, pintara o no (medido: cuadros=36, repintados=35). Era
    la metrica con la que el informe decia 'medir sin adivinar'."""
    RUN = "run-metrica"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=1))
        _correr_agente(f"{RUN}#pasos.1@1", RUN, indice=1, total=1, fase="pasos",
                       etiqueta="t", trozos=4,
                       cierre=dict(ok=True, tokens=10, intentos=1,
                                   duracion_s=1.0, resumen="ok")).join(timeout=5)
        events.emitir(events.WorkflowFin(run_id=RUN, nombre="x", ok=True, agentes=1))
        await _asentar(pilot, 20)
        a = app.metricas_vista()
        await _asentar(pilot, 20)
        b = app.metricas_vista()
        assert b["cuadros"] - a["cuadros"] >= 8
        assert b["repintados"] == a["repintados"], (a, b)


@pytest.mark.asyncio
async def test_una_vista_sin_puente_lo_dice_en_pantalla(bus_limpio):
    """D6. conectar_puente() NO devuelve el que ya existe si la App es otra:
    puente.py compara `p.app is not app`, desconecta el viejo y crea uno nuevo.
    La primera pantalla quedaba montada, con su timer a 15 fps, mostrando datos
    congelados y sin un solo suscriptor -- en silencio."""
    app1 = PantallaAgentes()
    async with app1.run_test(size=(120, 38)) as pilot1:
        await _asentar(pilot1, 4)
        p1 = app1._puente
        assert p1.conectado and not app1.metricas_vista()["desconectada"]
        assert app1.query_one("#desconectada").styles.display == "none"

        app2 = PantallaAgentes()
        async with app2.run_test(size=(120, 38)) as pilot2:
            await _asentar(pilot2, 4)
            assert not p1.conectado, "el arnes no reprodujo el robo del puente"
            await _asentar(pilot1, 6)
            assert app1.metricas_vista()["desconectada"], "app1 no se entero"
            franja = app1.query_one("#desconectada")
            assert franja.styles.display == "block"
            visto = franja.content.plain
            assert "DESCONECTADA" in visto and "CONGELADO" in visto, visto
            # Y deja de animar: una vista que no recibe nada no gasta cuadros.
            r0 = app1.metricas_vista()["repintados"]
            await _asentar(pilot1, 15)
            assert app1.metricas_vista()["repintados"] == r0


@pytest.mark.asyncio
async def test_cerrar_una_pantalla_no_apaga_el_puente_de_la_otra(bus_limpio):
    """D6, segunda mitad: el desconectar_puente() del on_unmount es GLOBAL y se
    llevaba puesto el puente de quien fuera que lo tuviera."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await _asentar(pilot, 4)
        p = app._puente
        assert p.conectado
        # Exactamente lo que hace el on_unmount de OTRA pantalla al cerrarse.
        mod_puente.desconectar_puente(solo_de=object())
        assert p.conectado, "una pantalla ajena apago este puente"
        assert mod_puente.puente_activo() is p
        # Y el dueno legitimo si puede.
        mod_puente.desconectar_puente(solo_de=app)
        assert not p.conectado
        assert mod_puente.puente_activo() is None


def test_abrir_pantalla_agentes_expone_las_dos_decisiones():
    """D9. `desconectar_al_salir` existe en el __init__ y esta documentado como
    decision de diseno, pero el unico punto de entrada publico no lo dejaba
    tomar."""
    import inspect
    par = inspect.signature(mod_agentes.abrir_pantalla_agentes).parameters
    assert "fps" in par and "desconectar_al_salir" in par
    assert par["desconectar_al_salir"].default is True


def test_los_comentarios_no_dicen_numeros_que_no_son():
    """D8. Dos comentarios traian numeros de otra version: 'doce veces por
    segundo' con FPS=15 ocho lineas arriba, y '~9 spans por cuadro' con una
    RAMPA_ONDA de 7 entradas. Corregidos, no borrados."""
    fuente = Path(mod_agentes.__file__).read_text(encoding="utf-8")
    assert "doce veces por segundo" not in fuente
    assert "~9 spans" not in fuente
    assert len(mod_agentes.RAMPA_ONDA) == 7
    assert mod_agentes.FPS == 15
    assert "QUINCE veces por segundo" in fuente
    # Y la promesa que invalidaba la medicion del shimmer ya no esta como
    # promesa: sobrevive citada dentro de la correccion que la desmiente.
    assert "CORRECCION 2026-08-18" in fuente
    assert "Hasta hoy la frase era" in fuente
    i = fuente.index("mismo que una pantalla quieta")
    assert "y era FALSO" in fuente[i:i + 260], fuente[i:i + 260]
    # 2026-08-18, tercera instancia del MISMO defecto, encontrada al
    # re-verificar: el comentario ubicaba a FPS "ocho lineas mas arriba" y
    # estaba a TRES. Una referencia POSICIONAL es un numero que se pudre solo
    # -- cualquier linea que se agregue en el medio la deja mintiendo -- asi
    # que no puede haber ninguna AFIRMADA; citada dentro de su correccion, si.
    for m in re.finditer(r"lineas mas arriba", fuente):
        ctx = fuente[max(0, m.start() - 200):m.end() + 60]
        assert "decia" in ctx or "ubicaba" in ctx, ctx
    # Y los numeros que los comentarios MIDEN se comprueban contra el codigo,
    # que es la unica forma de que no se pudran en silencio.
    assert len(mod_agentes.PISTA_ANCHA) == 116, len(mod_agentes.PISTA_ANCHA)
    assert len(mod_agentes.PISTA_COMPACTA) == 95, len(mod_agentes.PISTA_COMPACTA)
    assert mod_agentes.ancho_titulo(58) == 52     # "W-6" del comentario
    assert mod_agentes.ancho_contenido(58) == 54  # "W-4"
    # el ultimo peldano de la escalera del titulo: el comentario de
    # ANCHO_MIN_2COL dice 30 celdas, y el umbral se deriva de ese numero.
    peldano = len("[8] 8/8 · 12.345 tok · 123,4 s")
    assert peldano == 30, peldano
    assert (mod_agentes.ANCHO_MIN_2COL - 3) // 2 >= peldano + 6


def test_todas_las_ramas_de_sincronizar_tienen_guarda():
    """D5, la causa raiz: la rama del agente TERMINADO era la unica de las
    cinco `_sincronizar_*` sin comparacion previa. Se fija por contrato -- las
    cinco devuelven si tocaron algo, y `sincronizar` es la disyuncion."""
    import inspect
    from cognia.tui.agentes import PanelAgente as P
    for nombre in ("_sincronizar_estado_css", "_sincronizar_cabecera",
                   "_sincronizar_linea", "_sincronizar_aviso",
                   "_sincronizar_texto"):
        fn = getattr(P, nombre)
        assert inspect.signature(fn).return_annotation == "bool", nombre
        cuerpo = inspect.getsource(fn)
        assert "return False" in cuerpo, f"{nombre} no tiene salida temprana"


# ---------------------------------------------------------------------------
# 4. MANDAR: las acciones cableadas contra el MOTOR REAL (2026-08-18)
#
# El motor es el de produccion: `workflows.corrida()` registra la corrida en
# _VIVAS, `workflows.agente()` corre en su hilo, sella el agente_id por
# ContextVar y honra el control. Lo UNICO de juguete es `completar()`, que en
# vez de hablar con :8080 escupe palabras cada 40 ms mirando `cancelado()` --
# que es exactamente lo que hace la rama SSE de chat_client. Sin eso no hay
# nada que interrumpir, y un test de "interrumpir" contra un mock del motor
# verificaria el mock.
#
# El que ESTA seccion reemplaza es `test_las_acciones_estan_pero_no_mienten`.
# ---------------------------------------------------------------------------

from cognia.agent import workflows as motor        # noqa: E402


class _RespJuguete:
    """Lo minimo que agente() mira de una RespuestaChat."""

    def __init__(self, texto="", cortado=False, comp=8):
        self.texto = texto
        self.cortado = cortado
        self.error = ""
        self.finish_reason = "stop"
        self.usage = {"prompt_tokens": 7, "completion_tokens": comp}
        self.usage_estimado = bool(cortado)
        self.usage_via = "juguete" if cortado else ""


def _completar_lento(mensajes, *, cancelado=None, on_token=None,
                     on_reasoning=None, **kw):
    """Genera hasta 400 palabras mirando el corte, como el SSE de verdad."""
    salida = []
    for i in range(400):
        if cancelado is not None and cancelado():
            return _RespJuguete("".join(salida), cortado=True, comp=len(salida))
        frag = f"palabra{i} "
        salida.append(frag)
        if on_token is not None:
            on_token(frag)
        time.sleep(0.04)
    return _RespJuguete("".join(salida), comp=400)


def _completar_rapido(mensajes, **kw):
    on_token = kw.get("on_token")
    if on_token is not None:
        on_token("listo.\n")
    return _RespJuguete("listo.\n", comp=3)


def _completar_sordo(mensajes, url=None, temperature=None, top_p=None,
                     max_tokens=None, razonador=None, via=None):
    """Un completar() SIN el kwarg `cancelado`: _llamar() lo descarta (y emite
    Degradado). Consecuencia real y declarada: el corte solo llega ENTRE
    llamadas, o sea que los mensajes se APILAN en el buzon -- que es la unica
    forma honesta de llegar a `buzon_lleno` con el motor de verdad."""
    time.sleep(6.0)
    return _RespJuguete("no escuche nada", comp=4)


_HILOS: list = []


@pytest.fixture
def dir_workflows(tmp_path, monkeypatch):
    """Las corridas van a tmp_path (nunca a ~/.cognia) y NINGUN agente sale
    vivo del test.

    Lo segundo no es prolijidad: los agentes corren en hilos daemon y emiten al
    bus, que es global. Un agente que sobrevive al test le manda su AgenteFin
    al puente del test SIGUIENTE, que se inventa una corrida sintetica -- y asi
    la pantalla "sin corrida" del test de al lado tenia una corrida y ctrl+x le
    abria el modal (paso de verdad, 2026-08-18). Se cancela todo y se ESPERA a
    los hilos."""
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))
    _HILOS.clear()
    try:
        yield tmp_path
    finally:
        motor.cancelar_corrida()        # panico global: todas las vivas
        for h in _HILOS:
            h.join(timeout=10)
        vivos = [h for h in _HILOS if h.is_alive()]
        _HILOS.clear()
        assert not vivos, f"{len(vivos)} agentes siguen vivos tras el test"


def _corrida_real(nombre="acciones", total=2):
    return motor.corrida(nombre, print_fn=lambda *a, **k: None,
                         total_agentes=total, interactivo=True)


def _lanzar(c, *, indice, total, etiqueta, fn=_completar_lento, fase="pasos"):
    def cuerpo():
        motor.agente(c, f"{etiqueta}: contame", completar_fn=fn, indice=indice,
                     total=total, fase=fase, etiqueta=etiqueta, max_tokens=256)
    h = threading.Thread(target=cuerpo, daemon=True)
    h.start()
    _HILOS.append(h)
    return h


def _respuesta(app) -> str:
    """La fila #respuesta tal como se ve (no el renderable: el compositor)."""
    return _pintado(app, app.query_one("#respuesta")).strip()


@pytest.mark.asyncio
async def test_x_interrumpe_de_verdad_al_agente_seleccionado(bus_limpio,
                                                             dir_workflows):
    """`x` no "marca" nada: llama a workflows.cancelar_agente() y el agente
    REAL se corta. Se verifica en los dos lados -- el envelope que vuelve y el
    estado del agente en el control del motor."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("interrumpir", 2)
        _lanzar(c, indice=1, total=2, etiqueta="uno")
        _lanzar(c, indice=2, total=2, etiqueta="dos")
        await _asentar(pilot, 14)
        paneles = {p.orden: p for p in app.query(PanelAgente)}
        assert set(paneles) == {1, 2}, list(paneles)
        aid = paneles[2].agente_id
        assert motor.estado_agente(aid) == motor.EST_VIVO

        await pilot.press("2")
        await pilot.press("x")
        await pilot.pause()

        env = app.metricas_vista()["ultimo_envelope"]
        assert env["estado"] == motor.ACEPTADO and env["ok"] is True, env
        assert env["agente_id"] == aid and env["agentes"] == 1, env
        # La palabra del motor esta EN LA PANTALLA, con su prefijo.
        pintado = _respuesta(app)
        assert "motor: aceptado" in pintado, pintado
        assert pintado.startswith("✓"), pintado

        # Y el motor lo corto de verdad: el agente muere cancelado.
        await _asentar(pilot, 20)
        assert motor.estado_agente(aid) == motor.EST_TERMINADO
        assert c.control.fue_cortado(aid)
        assert paneles[2]._estado_css == "est-cancelado"
        # El OTRO sigue vivo: `x` corta UNO, no la corrida.
        assert motor.estado_agente(paneles[1].agente_id) == motor.EST_VIVO


@pytest.mark.asyncio
async def test_las_tres_teclas_sin_corrida_dicen_por_que_y_no_revientan(
        bus_limpio, dir_workflows, monkeypatch):
    """Pantalla vacia: x, ctrl+x y el Input tienen que contestar algo legible y
    NO llamar al motor (ctrl+x con run_id "" seria el PANICO GLOBAL del motor:
    cortaria corridas que esta pantalla ni siquiera muestra)."""
    llamadas: list = []
    for nombre in ("cancelar_agente", "cancelar_corrida", "decirle"):
        orig = getattr(motor, nombre)

        def espia(*a, _n=nombre, _o=orig, **kw):
            llamadas.append(_n)
            return _o(*a, **kw)
        monkeypatch.setattr(motor, nombre, espia)

    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await _asentar(pilot, 4)
        await pilot.press("x")
        await pilot.pause()
        assert "⚠" in _respuesta(app) and "motor:" not in _respuesta(app)
        assert "panel" in _respuesta(app)

        await pilot.press("ctrl+x")
        await pilot.pause()
        # NO se abre el modal: no hay nada que confirmar.
        assert type(app.screen).__name__ != "ConfirmModal"
        assert "corrida" in _respuesta(app) and "⚠" in _respuesta(app)

        await pilot.press("enter")          # el foco va al campo
        await pilot.pause()
        assert app.query_one("#hablar", Input).has_focus
        await pilot.press("enter")          # y manda vacio, sin destino
        await pilot.pause()
        assert "⚠" in _respuesta(app), _respuesta(app)
        assert app.metricas_vista()["ultimo_envelope"] is None
        # Nada de esto toco el motor.
        assert llamadas == [], llamadas


@pytest.mark.asyncio
async def test_el_envelope_de_uno_que_ya_termino_se_muestra_con_su_detalle(
        bus_limpio, dir_workflows):
    """La regla del encargo: NADA de tragarse el resultado.

    `ya_termino` viene con ok=False y con el motivo escrito; si la vista se lo
    guardara, el usuario apretaria `x` y no pasaria nada, sin saber por que. Se
    verifica en la PANTALLA (compositor), no en el renderable."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("termino", 1)
        _lanzar(c, indice=1, total=1, etiqueta="rapido",
                fn=_completar_rapido).join(timeout=10)
        await _asentar(pilot, 12)
        panel = app.query_one(PanelAgente)
        assert motor.estado_agente(panel.agente_id) == motor.EST_TERMINADO

        await pilot.press("1")
        await pilot.press("x")
        await pilot.pause()
        env = app.metricas_vista()["ultimo_envelope"]
        assert env["estado"] == motor.YA_TERMINO and env["ok"] is False, env
        pintado = _respuesta(app)
        assert pintado.startswith("✗"), pintado
        assert "motor: ya_termino" in pintado, pintado
        # El DETALLE del motor, no una parafrasis de la vista.
        assert env["detalle"][:40] in pintado, (env["detalle"], pintado)

        # Y hablarle a uno que ya entrego contesta lo mismo, no "aceptado".
        await pilot.press("enter")
        for ch in "hola":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        env2 = app.metricas_vista()["ultimo_envelope"]
        assert env2["estado"] == motor.YA_TERMINO, env2
        assert "motor: ya_termino" in _respuesta(app)
        # El texto rechazado NO se pierde: sigue en el campo.
        assert app.query_one("#hablar", Input).value == "hola"


@pytest.mark.asyncio
async def test_un_agente_ya_cancelado_contesta_ya_cancelado(bus_limpio,
                                                            dir_workflows):
    """La segunda `x` sobre el mismo agente es IDEMPOTENTE: ya_cancelado con
    ok=True. La vista no puede pintarla como fallo (el pedido del usuario esta
    cumplido) ni esconderla (no se corto nada nuevo)."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("dos veces", 1)
        _lanzar(c, indice=1, total=1, etiqueta="uno")
        await _asentar(pilot, 14)
        await pilot.press("1")
        await pilot.press("x")
        await pilot.pause()
        assert app.metricas_vista()["ultimo_envelope"]["estado"] == motor.ACEPTADO
        await _asentar(pilot, 20)      # el motor lo corta de verdad

        await pilot.press("x")
        await pilot.pause()
        env = app.metricas_vista()["ultimo_envelope"]
        assert env["estado"] == motor.YA_CANCELADO and env["ok"] is True, env
        pintado = _respuesta(app)
        assert pintado.startswith("✓") and "motor: ya_cancelado" in pintado


@pytest.mark.asyncio
async def test_el_input_interrumpe_y_dice_y_devuelve_el_foco(bus_limpio,
                                                             dir_workflows):
    """El Input manda al agente SELECCIONADO (no al enfocado: mientras se
    escribe, el foco es del campo y ningun panel lo tiene), enter manda y el
    foco vuelve a la rejilla. El mensaje llega al buzon del motor de verdad."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("hablar", 2)
        _lanzar(c, indice=1, total=2, etiqueta="uno")
        _lanzar(c, indice=2, total=2, etiqueta="dos")
        await _asentar(pilot, 14)
        paneles = {p.orden: p for p in app.query(PanelAgente)}
        aid = paneles[2].agente_id

        await pilot.press("2")
        assert app.metricas_vista()["seleccionado"] == aid
        await pilot.press("enter")
        await pilot.pause()
        campo = app.query_one("#hablar", Input)
        assert campo.has_focus, "enter tiene que llevar el foco al campo"
        # La seleccion SOBREVIVE al foco: el panel sigue marcado y el
        # placeholder dice a quien se le habla.
        assert paneles[2].has_class("seleccionado")
        assert "[2]" in campo.placeholder and "dos" in campo.placeholder
        assert not paneles[2].has_focus     # el foco es del campo

        for ch in "mira_el_nonce":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()

        env = app.metricas_vista()["ultimo_envelope"]
        assert env["estado"] == motor.ACEPTADO and env["ok"] is True, env
        assert env["agente_id"] == aid and env["pendientes"] == 1, env
        assert "1 mensaje en cola" in _respuesta(app), _respuesta(app)
        # Aceptado -> el campo se limpia; y el foco vuelve a los paneles.
        assert campo.value == ""
        assert paneles[2].has_focus, "el foco no volvio a la rejilla"
        # Y el mensaje esta en el MOTOR, no solo en la pantalla: el agente lo
        # drena y vuelve a preguntar (una llamada mas, como dice el contrato).
        await _asentar(pilot, 20)
        journal = (c.dir / "journal.jsonl").read_text(encoding="utf-8")
        assert "mira_el_nonce" in journal, "el mensaje no llego al motor"


@pytest.mark.asyncio
async def test_el_buzon_lleno_se_ve_y_el_texto_no_se_pierde(bus_limpio,
                                                            dir_workflows):
    """`buzon_lleno` es de los ocho estados y tiene que verse. Se llega a el
    con el motor real: un agente cuyo completar() no acepta `cancelado` no se
    entera de los mensajes hasta terminar la llamada, asi que se apilan."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("sordo", 1)
        _lanzar(c, indice=1, total=1, etiqueta="no escucha", fn=_completar_sordo)
        await _asentar(pilot, 10)
        await pilot.press("1")
        await pilot.pause()
        campo = app.query_one("#hablar", Input)
        estados = []
        for i in range(9):
            campo.focus()
            campo.value = f"m{i}"
            await pilot.press("enter")
            await pilot.pause()
            estados.append(app.metricas_vista()["ultimo_envelope"]["estado"])
        # Ocho entran (el tope del buzon del motor) y el noveno rebota.
        assert estados[:8] == [motor.ACEPTADO] * 8, estados
        assert estados[8] == motor.BUZON_LLENO, estados
        pintado = _respuesta(app)
        assert "motor: buzon_lleno" in pintado, pintado
        assert "no los esta leyendo" in pintado, pintado
        # Rechazado -> el texto sigue en el campo (se perdio el mensaje, no
        # hace falta perder tambien lo escrito).
        assert campo.value == "m8"


@pytest.mark.asyncio
async def test_ctrl_x_confirma_antes_de_cortar_y_el_modal_no_premia_el_corte(
        bus_limpio, dir_workflows):
    """ctrl+x abre el ConfirmModal de la TUI. Dos cosas se fijan aca:

    1. que NO corta hasta que se confirma (con "n" la corrida sigue viva en el
       motor, no solo en la pantalla);
    2. que el modal sigue sin premiar la accion destructiva -- ningun boton
       enfocado por defecto y los dos con el mismo peso (mismo fondo). Ese
       equilibrio costo cuatro pasadas en app.tcss y traerlo a esta pantalla
       no puede deshacerlo."""
    from cognia.tui.widgets.modals import ConfirmModal
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("cortar", 2)
        _lanzar(c, indice=1, total=2, etiqueta="uno")
        _lanzar(c, indice=2, total=2, etiqueta="dos")
        await _asentar(pilot, 14)
        assert c.run_id in [d["run_id"] for d in motor.corridas_vivas()]
        primero = app.query(PanelAgente).first().agente_id

        await pilot.press("ctrl+x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        # Nadie enfocado: 'enter' confirma y marcar un boton mentiria.
        assert app.focused is None, app.focused
        si = app.screen.query_one("#confirm-yes")
        no = app.screen.query_one("#confirm-no")
        assert si.styles.background == no.styles.background, "un boton pesa mas"
        assert "Cortar" in str(si.label) and "No" in str(no.label)
        # El dialogo dice CUANTO se destruye, con el numero real de vivos.
        pregunta = str(app.screen.query_one("#confirm-question").content)
        assert "2 agentes" in pregunta, pregunta

        await pilot.press("n")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)
        assert app.metricas_vista()["ultimo_envelope"] is None
        assert "no se canceló nada" in _respuesta(app), _respuesta(app)
        # NO se corto nada en el motor.
        assert not c.control.esta_cancelado(primero)

        await pilot.press("ctrl+x")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        env = app.metricas_vista()["ultimo_envelope"]
        assert env["estado"] == motor.ACEPTADO and env["corridas"] == 1, env
        assert env["run_id"] == c.run_id, env
        assert "1 corrida alcanzada" in _respuesta(app), _respuesta(app)
        # Y ahora si: el corte llego a los agentes de verdad.
        await _asentar(pilot, 24)
        for panel in app.query(PanelAgente):
            assert c.control.fue_cortado(panel.agente_id), panel.agente_id
            assert panel._estado_css == "est-cancelado", panel._estado_css


def test_los_ocho_estados_del_motor_se_pueden_pintar():
    """El conjunto es CERRADO y la vista tiene que poder mostrarlos TODOS con
    su palabra literal. Un estado nuevo en workflows.py que la pantalla no
    supiera pintar es exactamente el silencio que el envelope evita."""
    vistos = []

    class _Espia(PantallaAgentes):
        def _pintar_respuesta(self, glifo, accion, cuerpo, color):
            vistos.append((glifo, cuerpo))

    app = _Espia()
    for estado in motor.ESTADOS_CONTROL:
        env = motor._envelope(estado == motor.ACEPTADO, estado, "a", "r",
                              detalle=f"detalle de {estado}")
        app._mostrar_envelope("x", env)
    assert len(vistos) == len(motor.ESTADOS_CONTROL) == 8
    for (glifo, cuerpo), estado in zip(vistos, motor.ESTADOS_CONTROL):
        assert f"motor: {estado}" in cuerpo, cuerpo
        assert f"detalle de {estado}" in cuerpo, cuerpo
        assert glifo in ("✓", "✗")
    # Y el aviso de la VISTA no se puede confundir con uno del motor.
    vistos.clear()
    app._mostrar_aviso("no hay ningún panel seleccionado")
    assert vistos[0][0] == "⚠" and "motor:" not in vistos[0][1]
    assert app._ultimo_envelope is None


@pytest.mark.asyncio
async def test_tab_recorre_paneles_aunque_el_input_sea_focusable(bus_limpio):
    """Bug encontrado al cablear: `tab -> panel(1)` estaba declarado en la App
    y NUNCA disparaba (Screen trae `tab -> app.focus_next` y gana). Funcionaba
    de casualidad porque los unicos focusables eran los paneles; al habilitar
    el Input, tab desde el ultimo panel se iba al campo de texto."""
    RUN = "run-tab"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=2))
        for k in (1, 2):
            _correr_agente(f"{RUN}#p.{k}@{k}", RUN, indice=k, total=2,
                           fase="p", etiqueta=f"paso {k}", trozos=2).join(timeout=5)
        await _asentar(pilot)
        paneles = {p.orden: p for p in app.query(PanelAgente)}
        await pilot.press("2")
        await pilot.press("tab")
        await pilot.pause()
        assert paneles[1].has_focus, "tab se fue del ciclo de paneles"
        assert not app.query_one("#hablar", Input).has_focus
        await pilot.press("shift+tab")
        await pilot.pause()
        assert paneles[2].has_focus


@pytest.mark.asyncio
async def test_escape_mientras_se_escribe_no_cierra_la_pantalla(bus_limpio):
    """El Input de Textual no consume escape, asi que escape llegaba a la App y
    CERRABA la pantalla con el mensaje a medio tipear. Devuelve el foco."""
    RUN = "run-esc"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="x", total_agentes=1))
        _correr_agente(f"{RUN}#p.1@1", RUN, indice=1, total=1, fase="p",
                       etiqueta="uno", trozos=2).join(timeout=5)
        await _asentar(pilot)
        panel = app.query_one(PanelAgente)
        await pilot.press("1")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#hablar", Input).has_focus
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running, "escape cerro la pantalla mientras se escribia"
        assert panel.has_focus
        assert "esc otra vez" in _respuesta(app), _respuesta(app)
        # Y desde la rejilla, escape SI sale.
        await pilot.press("escape")
        await pilot.pause()
    assert app._timer is None


@pytest.mark.asyncio
async def test_la_interrupcion_se_declara_en_la_franja_de_honestidad(
        bus_limpio, dir_workflows):
    """"Interrumpir y decir" TIRA lo generado, pero el panel lo sigue
    mostrando pegado a lo que viene despues.

    Medido en la corrida real contra :8080: el journal anota corte
    causa='mensaje' con 460 chars descartados y el panel pintaba
    '...actualizadaLISTO' como una sola respuesta. El texto es cierto; lo que
    no es cierto es que sea UN turno. Va a la franja que ya existe para eso."""
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        c = _corrida_real("honestidad", 1)
        _lanzar(c, indice=1, total=1, etiqueta="uno")
        await _asentar(pilot, 14)
        panel = app.query_one(PanelAgente)
        # Antes de hablarle no hay nada que declarar.
        assert panel._aviso.styles.display == "none"
        assert not panel.has_class("incompleto")

        await pilot.press("1")
        await pilot.press("enter")
        for ch in "otra_cosa":
            await pilot.press(ch)
        await pilot.press("enter")
        await _asentar(pilot, 8)

        assert panel._aviso.styles.display == "block"
        aviso = str(panel._aviso.content)
        assert "interrumpido 1 vez" in aviso, aviso
        assert "descartado" in aviso and "modelo ya no lo ve" in aviso, aviso
        # Y NO se corta en seco: la franja tiene max-height 2 y lo que no
        # entraba desaparecia sin marca (el mismo D2, en la fila que existe
        # para declarar que falta algo). Entra entera o termina en elipsis.
        cabe = mod_agentes.ancho_contenido(panel.outer_size.width) * 2 - 9
        assert len(aviso) <= cabe + 4, (len(aviso), cabe, aviso)
        # Y el titulo queda marcado con el "!" de honestidad.
        assert panel.has_class("incompleto")


# ---------------------------------------------------------------------------
# 5. Lo que se cayo AL RE-VERIFICAR (tanda de verificacion final, 2026-08-18)
# ---------------------------------------------------------------------------
# Dos defectos que NO estaban en la lista de trece y aparecieron al probar la
# promesa de D11 ("los NUMEROS del titulo no se sacrifican") con la terminal
# redimensionada de verdad, en vez de a 120 columnas fijas.

@pytest.mark.asyncio
async def test_los_numeros_del_titulo_sobreviven_a_una_terminal_angosta(
        bus_limpio):
    """D11, el piso que la escalera sola no sostiene.

    La escalera de degradacion suelta etiqueta -> rol -> fase y despues no
    tiene nada mas que soltar: el ultimo peldano es "[N] i/total" + los
    numeros, 30 celdas en su peor caso. Con DOS columnas eso no entra por
    debajo de 76 columnas de terminal y lo que corta el renderer es la COLA, o
    sea el reloj. MEDIDO antes del arreglo (scratchpad/t5b_final/r4_d11.py, la
    terminal redimensionada de 40 a 170 y leyendo el compositor): 46 de 198
    titulos pintados salian como "[1] 1/3 · 12.345 tok…". Se arregla no
    partiendo la pantalla en dos cuando cada mitad no da (ANCHO_MIN_2COL).
    """
    RUN = "run-angosto"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="angosta",
                                            total_agentes=3))
        for i in (1, 2, 3):
            # el peor caso realista: 5 cifras de tokens y 3 de segundos
            _correr_agente(f"{RUN}#pasos.{i}@{i}", RUN, indice=i, total=3,
                           fase="pasos", etiqueta="leer el handshake completo",
                           rol="worker", trozos=2,
                           cierre=dict(ok=True, tokens=12345, duracion_s=123.4,
                                       resumen="listo")).join(timeout=5)
        await _asentar(pilot, 14)

        for ancho in (56, 60, 64, 70, 74, 76, 80, 120):
            await pilot.resize_terminal(ancho, 36)
            await _asentar(pilot, 6)
            columnas = app.query_one("#rejilla").styles.grid_size_columns
            assert columnas == (2 if ancho >= mod_agentes.ANCHO_MIN_2COL
                                else 1), (ancho, columnas)
            for p in app.query(PanelAgente):
                t = p.border_title
                # el titulo ENTRA (no lo corta el renderer)...
                assert len(t) <= mod_agentes.ancho_titulo(p.outer_size.width), \
                    (ancho, p.orden, len(t), t)
                # ...y los dos numeros estan enteros
                assert "12.345 tok" in t, (ancho, p.orden, t)
                assert re.search(r"\d+,\d+ s", t), (ancho, p.orden, t)


@pytest.mark.asyncio
async def test_la_pista_y_la_rejilla_siguen_al_redimensionar(bus_limpio):
    """El on_resize de la App corre con `App.size` TODAVIA vieja.

    MEDIDO con un espia sobre la secuencia 120 -> 60 -> 100: la App vio
    [120, 120, 120, 60] con la terminal ya en 100. O sea que todo lo que se
    calculaba con `self.size` dentro de on_resize quedaba un paso atras -- la
    pista se quedaba en el nivel de dos filas en una terminal de 120 (medido:
    nivel 0 con 120 columnas). Se arregla leyendo el ancho DEL EVENTO y
    re-decidiendolo en el latido, que tiene el ancho ya asentado.
    """
    RUN = "run-resize"
    app = PantallaAgentes()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        events.emitir(events.WorkflowInicio(run_id=RUN, nombre="resize",
                                            total_agentes=2))
        for i in (1, 2):
            _correr_agente(f"{RUN}#f.{i}@{i}", RUN, indice=i, total=2,
                           fase="f", etiqueta=f"t{i}", trozos=2).join(timeout=5)
        await _asentar(pilot, 14)

        # el nivel que le toca a cada ancho (mismos umbrales que _pintar_pista)
        for ancho, nivel in ((150, 2), (110, 1), (90, 0), (60, 0), (120, 2)):
            await pilot.resize_terminal(ancho, 34)
            await _asentar(pilot, 8)
            assert app._pista_nivel == nivel, (ancho, app._pista_nivel, nivel)
            texto = app.query_one("#pista").content.plain
            assert texto == (mod_agentes.PISTA_ANCHA if nivel == 2
                             else mod_agentes.PISTA_COMPACTA), (ancho, texto)
            assert app.query_one("#rejilla").styles.grid_size_columns == (
                2 if ancho >= mod_agentes.ANCHO_MIN_2COL else 1), ancho


def test_repartir_la_rejilla_tiene_guarda_como_todo_lo_demas():
    """Se llama por cuadro desde el latido: sin guarda seria un set_class y un
    estilo inline quince veces por segundo, o sea el D5 de vuelta por otra
    puerta. Devuelve False cuando la reparticion ya era esa."""
    import inspect
    fn = mod_agentes.PantallaAgentes._repartir_rejilla
    assert inspect.signature(fn).return_annotation == "bool"
    cuerpo = inspect.getsource(fn)
    assert "self._reparto" in cuerpo and "return False" in cuerpo
