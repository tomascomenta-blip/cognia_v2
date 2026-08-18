"""
Tanda UI 2026-08-18: el movil ve el progreso POR AGENTE, agrupado.

Lo que se fija aqui (y falla sin el cambio):

  1. `agente_de_evento` — la AGRUPACION viaja como campo, no como adivinanza
     por regex. Incluye el caso torcido: MensajeAlAgente agrupa por DESTINO,
     no por el agente_id heredado (que sella al emisor y suele ser "").
  2. El campo llega al JSONL y SOBREVIVE a `transcripcion()`: un workflow
     terminado se reabre con sus bloques por agente, no solo en vivo.
  3. El contrato del de-dup: las lineas del renderer real siguen cayendo en
     `es_eco_renderer` (si no, el movil pinta cada agente dos veces).
  4. `ColaSuscriptor` — techo con AVISO: la cola de un WS no crece sin limite
     y lo descartado se cuenta para anunciarlo, nunca en silencio.
"""

import json
import pathlib

import pytest

from cognia.remoto import sesiones as _ses
from cognia.remoto.sesiones import (ColaSuscriptor, Sesion, agente_de_evento,
                                    es_eco_renderer, interpretar_evento)


def _ev(tipo: str, **campos) -> str:
    return "@EV " + json.dumps({"tipo": tipo, "ts": 0.0, **campos},
                               ensure_ascii=False)


def _sesion(tmp_path, monkeypatch) -> Sesion:
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    s._arrancando = False
    return s


def _lineas(s: Sesion) -> list[dict]:
    if not s.fichero.exists():
        return []                      # nada anotado: el gate lo tiro todo
    return [json.loads(l)
            for l in s.fichero.read_text(encoding="utf-8").splitlines()]


AID = "r1#pasos.2@7"


# ── 1. la agrupacion es un CAMPO ───────────────────────────────────────────

def test_agente_inicio_trae_id_ref_y_estado_vivo():
    ag = agente_de_evento({"tipo": "AgenteInicio", "agente_id": AID,
                           "indice": 2, "total": 6, "fase": "pasos",
                           "etiqueta": "resume TLS"})
    assert ag == {"id": AID, "ref": "agente 2/6 resume TLS",
                  "estado": "vivo", "fase": "pasos"}


def test_agente_fin_trae_estado_tokens_y_segundos():
    ag = agente_de_evento({"tipo": "AgenteFin", "agente_id": AID, "indice": 2,
                           "total": 6, "etiqueta": "resume TLS", "ok": True,
                           "tokens": 812, "duracion_s": 4.137})
    assert ag["id"] == AID and ag["estado"] == "ok"
    assert ag["tokens"] == 812 and ag["seg"] == 4.1
    malo = agente_de_evento({"tipo": "AgenteFin", "agente_id": AID,
                             "ok": False, "motivo": "cancelado"})
    assert malo["estado"] == "fallo"


def test_cache_hit_y_tardio_se_declaran():
    ag = agente_de_evento({"tipo": "AgenteFin", "agente_id": AID, "ok": True,
                           "cache_hit": True, "tardio": True})
    assert ag["cache"] is True and ag["tardio"] is True


def test_progreso_agrupa_con_sus_chars():
    ag = agente_de_evento({"tipo": "AgenteProgreso", "agente_id": AID,
                           "chars": 190})
    assert ag == {"id": AID, "chars": 190}


def test_mensaje_al_agente_agrupa_por_DESTINO_no_por_el_emisor():
    """El agente_id heredado sella al EMISOR (la UI: ""), el destinatario va
    en `destino`. Agrupar por el emisor mandaba el eco al bloque equivocado —
    o a ninguno."""
    ag = agente_de_evento({"tipo": "MensajeAlAgente", "agente_id": "",
                           "destino": AID, "texto": "hace foco",
                           "aceptado": True})
    assert ag == {"id": AID}


def test_evento_de_dentro_de_un_agente_hereda_el_id():
    # un ToolFin emitido DENTRO del agente lleva agente_id por el ContextVar:
    # su linea tiene que caer en el bloque de ese agente, no en la lista plana
    ag = agente_de_evento({"tipo": "ToolFin", "agente_id": AID,
                           "tool": "leer_archivo", "ok": True})
    assert ag == {"id": AID}


def test_lo_que_no_es_de_un_agente_no_agrupa():
    for d in ({"tipo": "WorkflowInicio", "run_id": "r1", "nombre": "repl"},
              {"tipo": "Degradado", "donde": "backend"},
              {"tipo": "MensajeAlAgente", "destino": "", "texto": "x"},
              {"tipo": "AgenteInicio", "agente_id": "", "indice": 1}):
        assert agente_de_evento(d) == {}, d


# ── 2. el campo viaja al JSONL y sobrevive a la relectura ──────────────────

_WORKFLOW_3 = [
    _ev("WorkflowInicio", run_id="r1", nombre="repl", total_agentes=3),
    _ev("AgenteInicio", run_id="r1", agente_id="r1#pasos.1@1", indice=1,
        total=3, fase="pasos", etiqueta="paso A"),
    _ev("AgenteProgreso", run_id="r1", agente_id="r1#pasos.1@1", chars=190),
    _ev("AgenteFin", run_id="r1", agente_id="r1#pasos.1@1", indice=1, total=3,
        etiqueta="paso A", ok=True, tokens=100, duracion_s=1.5,
        resumen="listo A"),
    _ev("AgenteInicio", run_id="r1", agente_id="r1#pasos.2@2", indice=2,
        total=3, fase="pasos", etiqueta="paso B"),
    _ev("AgenteFin", run_id="r1", agente_id="r1#pasos.2@2", indice=2, total=3,
        etiqueta="paso B", ok=True, tokens=120, duracion_s=2.0,
        resumen="listo B"),
    _ev("AgenteInicio", run_id="r1", agente_id="r1#pasos.3@3", indice=3,
        total=3, fase="pasos", etiqueta="paso C"),
    _ev("AgenteFin", run_id="r1", agente_id="r1#pasos.3@3", indice=3, total=3,
        etiqueta="paso C", ok=True, tokens=90, duracion_s=1.1,
        resumen="listo C"),
    _ev("WorkflowFin", run_id="r1", nombre="repl", ok=True, agentes=3,
        fallidos=0, tokens=310, duracion_s=4.6),
]


def test_el_jsonl_guarda_la_agrupacion(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    for l in _WORKFLOW_3:
        s._procesar_linea(l)
    lineas = _lineas(s)
    ids = {e["ag"]["id"] for e in lineas if e.get("ag")}
    assert ids == {"r1#pasos.1@1", "r1#pasos.2@2", "r1#pasos.3@3"}
    # las dos lineas del workflow (inicio/fin) NO se atribuyen a nadie
    sin_ag = [e["texto"] for e in lineas if not e.get("ag")]
    assert len(sin_ag) == 2 and all("workflow" in t for t in sin_ag)


def test_el_workflow_terminado_se_reabre_agrupado(tmp_path, monkeypatch):
    """Punto 4 del pedido: consultar DESPUES. transcripcion() reclasifica al
    leer y antes se comia cualquier clave que no fuera quien/texto."""
    s = _sesion(tmp_path, monkeypatch)
    for l in _WORKFLOW_3:
        s._procesar_linea(l)
    trans = s.transcripcion()
    por_agente: dict = {}
    for e in trans:
        ag = e.get("ag")
        if ag:
            por_agente.setdefault(ag["id"], []).append(e)
    assert len(por_agente) == 3, por_agente
    # el bloque del agente 1 conserva su inicio, su latido y su fin con metrica
    uno = por_agente["r1#pasos.1@1"]
    assert [e["ag"].get("estado") for e in uno] == ["vivo", None, "ok"]
    assert uno[-1]["ag"]["tokens"] == 100 and uno[-1]["ag"]["seg"] == 1.5


def test_una_transcripcion_vieja_sin_el_campo_sigue_leyendose(tmp_path,
                                                              monkeypatch):
    """Respaldo: lo grabado antes de esta tanda no tiene `ag` y no puede
    reventar la relectura (el cliente cae al regex)."""
    s = _sesion(tmp_path, monkeypatch)
    s.anotar("actividad", "· agente 1/3 paso A…")
    s.anotar("actividad", "⏺ agente 1/3 paso A — listo (1.5s · 100 tok)")
    trans = s.transcripcion()
    assert all("ag" not in e for e in trans)
    assert [e["quien"] for e in trans] == ["actividad", "actividad"]


def test_la_agrupacion_no_cambia_el_texto_de_las_lineas():
    """Blindaje del punto 3: agrupar es aniadir un campo, jamas retocar el
    texto — el de-dup del movil se apoya en la marca inicial."""
    for tipo, campos in (("AgenteInicio", dict(indice=1, total=2,
                                               etiqueta="paso A")),
                         ("AgenteFin", dict(indice=1, total=2,
                                            etiqueta="paso A", ok=True,
                                            tokens=100, duracion_s=1.0,
                                            resumen="listo"))):
        quien, texto, ecos = interpretar_evento(
            {"tipo": tipo, "agente_id": AID, **campos})
        assert quien == "actividad" and ecos == []
        assert texto[0] in "·⏺✗", texto
        assert es_eco_renderer(texto), texto


def test_el_renderer_real_sigue_siendo_eco(capsys):
    """El test que ata los dos ficheros, re-corrido tras la tanda: si el
    formato de una linea se movio, el movil DUPLICA."""
    from cognia.ux import events as _ev_mod
    from cognia.ux.renderer import Renderer

    ident = dict(run_id="r1", agente_id=AID, indice=2, total=3, fase="pasos",
                 etiqueta="resume TLS")
    eventos = [
        _ev_mod.WorkflowInicio(run_id="r1", nombre="repl", total_agentes=3),
        _ev_mod.AgenteInicio(**ident),
        _ev_mod.AgenteFin(ok=True, tokens=812, duracion_s=4.1,
                          resumen="3 parrafos", **ident),
        _ev_mod.WorkflowFin(run_id="r1", nombre="repl", ok=True, agentes=3,
                            fallidos=0, tokens=4210, duracion_s=31.2),
    ]
    r = Renderer(console=None)
    for ev in eventos:
        r(ev)
    lineas = [l for l in capsys.readouterr().out.split("\n") if l.strip()]
    assert len(lineas) == len(eventos), lineas
    for l in lineas:
        assert es_eco_renderer(l), l


def test_los_ecos_del_renderer_no_se_cuelan_en_los_bloques(tmp_path,
                                                           monkeypatch):
    """Circuito entero con agrupacion: 3 agentes, 3 bloques, 0 duplicados."""
    s = _sesion(tmp_path, monkeypatch)
    for l in [_WORKFLOW_3[0], "  · workflow «repl» — 3 agentes",
              _WORKFLOW_3[1], "  · agente 1/3 paso A…",
              _WORKFLOW_3[3], "  ⏺ agente 1/3 paso A — listo (1.5s · 100 tok)",
              _WORKFLOW_3[4], "  · agente 2/3 paso B…",
              _WORKFLOW_3[5], "  ⏺ agente 2/3 paso B — listo (2.0s · 120 tok)",
              _WORKFLOW_3[6], "  · agente 3/3 paso C…",
              _WORKFLOW_3[7], "  ⏺ agente 3/3 paso C — listo (1.1s · 90 tok)",
              _WORKFLOW_3[8], "  ⏺ workflow «repl» — 3 de 3 · 310 tokens"]:
        s._procesar_linea(l)
    lineas = _lineas(s)
    assert len(lineas) == 8, [e["texto"] for e in lineas]   # 8 eventos, 0 ecos
    assert not [e for e in lineas if e["quien"] != "actividad"]


# ── 4. techo de la cola con AVISO ──────────────────────────────────────────

def test_la_cola_tiene_techo_y_tira_lo_MAS_VIEJO():
    q = ColaSuscriptor(tope=3)
    for i in range(10):
        q.put_nowait({"n": i})
    assert len(q) == 3
    assert [q.get(timeout=0.1)["n"] for _ in range(3)] == [7, 8, 9]


def test_lo_descartado_se_cuenta_y_se_entrega_una_sola_vez():
    q = ColaSuscriptor(tope=2)
    for i in range(6):
        q.put_nowait({"n": i})
    assert q.tomar_descartadas() == 4      # 6 puestas, 2 sobreviven
    assert q.tomar_descartadas() == 0      # ya se anuncio: no se repite
    q.get(timeout=0.1)                     # el WS drena: vuelve a haber sitio
    q.put_nowait({"n": 99})                # y con sitio no se tira nada
    assert q.tomar_descartadas() == 0


def test_una_cola_bajo_el_techo_no_pierde_nada():
    q = ColaSuscriptor(tope=1000)
    for i in range(500):
        q.put_nowait({"n": i})
    assert q.tomar_descartadas() == 0 and len(q) == 500


def test_anotar_alimenta_la_cola_con_techo(tmp_path, monkeypatch):
    """El circuito real: Sesion.anotar -> ColaSuscriptor. Un workflow largo con
    el movil desconectado ya no hace crecer la cola sin limite."""
    s = _sesion(tmp_path, monkeypatch)
    q = ColaSuscriptor(tope=5)
    s.suscriptores.append(q)
    for i in range(200):
        s.anotar("actividad", f"linea {i}")
    assert len(q) == 5
    assert q.tomar_descartadas() == 195
    assert q.get(timeout=0.1)["texto"] == "linea 195"   # sobrevive lo RECIENTE


# ── 5. el gate de arranque cerraba con el banner de HOY ────────────────────
# Cazado midiendo el e2e de esta tanda: llegaban los eventos tipados (se
# juzgan ANTES del gate) y NO llegaba nada de la prosa del CLI. El unico
# marcador vivo era el del panel compacto y el REPL arranca con el banner
# COMPLETO, que dice "/ayuda para TODOS los comandos" y ya no dice "Sistema
# listo": el gate se comia 200 lineas de cada sesion.

_BANNER_COMPLETO = [
    "┌" + "─" * 20 + " COGNIA v4.6 " + "─" * 20 + "┐",
    "│ ██╔════╝   ██╔═══██╗                                          │",
    "│   Sistema cognitivo local · memoria + grafo + agente               │",
    "│   /ayuda para todos los comandos                                    │",
    "│ Para empezar                                                        │",
    "│   Tab completar   ↑↓ historial   /ayuda todo                        │",
    "└" + "─" * 26 + " sistema cognitivo local " + "─" * 26 + "┘",
    "  modelo qwen2.5-coder-14b (:8080)   modo unico   tema claro",
    r"  Sesion 88c63646 en C:\proy",
    "  Continuidad: 20 mensajes de sesiones previas restaurados",
]


def test_el_banner_COMPLETO_cierra_el_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    for l in _BANNER_COMPLETO:
        s._procesar_linea(l)
    assert not s._arrancando, "el gate sigue abierto tras el banner entero"
    # y la prosa que viene DESPUES llega al chat, que es lo que se perdia
    s._procesar_linea("ALFA")
    quienes = [e["quien"] for e in _lineas(s)]
    assert "cognia" in quienes, quienes


def test_el_panel_de_resultado_de_workflow_llega_al_movil(tmp_path,
                                                          monkeypatch):
    """La perdida MEDIDA: /workflow imprime su resultado en un panel rich y
    con el gate abierto no llegaba ni una linea."""
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    for l in _BANNER_COMPLETO:
        s._procesar_linea(l)
    for l in [_WORKFLOW_3[1], _WORKFLOW_3[3],
              "│ --- paso 1: di solo ALFA                     │",
              "│ ALFA                                         │",
              "corrida 20260818-repl · 172 tokens"]:
        s._procesar_linea(l)
    textos = [e["texto"] for e in _lineas(s)]
    assert any("paso 1: di solo ALFA" in t for t in textos), textos
    assert any("172 tokens" in t for t in textos), textos


def test_las_lineas_de_estado_del_arranque_van_al_registro(tmp_path,
                                                           monkeypatch):
    """Contrapartida del gate nuevo: cierra en el borde del panel, asi que las
    tres lineas de estado quedan fuera. Su sitio es el Registro, no el chat."""
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    for l in _BANNER_COMPLETO:
        s._procesar_linea(l)
    assert [e["quien"] for e in _lineas(s)] == ["log", "log", "log"]


def test_el_panel_compacto_sigue_cerrando_el_gate(tmp_path, monkeypatch):
    """Regresion del marcador viejo: el compacto no tiene borde de panel."""
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    for l in ["cognia v4.6 · sistema cognitivo local",
              "  modelo gpt-oss-20b (:8080)", "  cwd    C:/proy",
              "  /ayuda para comandos · /hacer <tarea> para el agente"]:
        s._procesar_linea(l)
    assert not s._arrancando
    assert _lineas(s) == []          # el compacto entero se descarta


# ── 6. el WS REAL avisa lo que descarto ────────────────────────────────────

def test_el_ws_real_anuncia_las_lineas_perdidas(tmp_path, monkeypatch):
    """Punto 2 del pedido, por el endpoint de verdad: se llena la cola de un
    WS conectado por encima del techo y el cliente recibe el AVISO antes del
    primer evento que sobrevivio. Sin el aviso, el movil cree que vio el
    workflow entero."""
    from starlette.testclient import TestClient
    from cognia.remoto import servidor as _srv
    from cognia.remoto.sesiones import GestorSesiones, registrar_proyecto

    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    monkeypatch.setattr(_ses, "TOPE_COLA_WS", 3)
    monkeypatch.setattr(_srv, "ESPERA_WS_S", 0.5)   # teardown rapido
    # la sesion la crea el endpoint dentro de su propio gestor: se espia para
    # poder empujar por la MISMA cola que el WS suscribio
    vistas = []
    orig = GestorSesiones.obtener
    monkeypatch.setattr(GestorSesiones, "obtener",
                        lambda self, pr, sid: vistas.append(
                            orig(self, pr, sid)) or vistas[-1])

    pr = registrar_proyecto(str(tmp_path))
    c = TestClient(_srv.crear_app())
    tok = _srv.asegurar_token(tmp_path)
    with c.websocket_connect(f"/ws/{pr['id']}/s1?token={tok}") as ws:
        assert vistas, "el endpoint no creo la sesion"
        colas = list(vistas[-1].suscriptores)
        assert len(colas) == 1 and isinstance(colas[0], ColaSuscriptor)
        for i in range(20):
            colas[0].put_nowait({"t": "00:00:00", "quien": "actividad",
                                 "texto": f"linea {i}"})
        aviso = ws.receive_json()
        assert aviso["quien"] == "sistema" and aviso["perdidas"] == 17
        assert "se perdieron 17 lineas" in aviso["texto"], aviso
        # y despues del aviso llega lo que SI sobrevivio: lo mas RECIENTE
        assert ws.receive_json()["texto"] == "linea 17"
        assert ws.receive_json()["texto"] == "linea 18"
        # una cola que no desborda no vuelve a avisar
        colas[0].put_nowait({"t": "00:00:00", "quien": "actividad",
                             "texto": "linea 99"})
        assert ws.receive_json()["texto"] == "linea 19"
        assert ws.receive_json()["texto"] == "linea 99"


# ── 7. el CLIENTE de verdad, en Chromium headless ──────────────────────────
# Sin esto la parte visible del pedido queda declarada y no medida: el HTML se
# carga por file:// (sin red ni servidor) y se le pasan las MISMAS lineas que
# produce sesiones.py. Se salta solo si no hay playwright/Chromium.

def _pagina(pw):
    ruta = (pathlib.Path(__file__).resolve().parent.parent
            / "cognia" / "remoto" / "static" / "index.html").as_uri()
    nav = pw.chromium.launch()
    pg = nav.new_context().new_page()
    pg.goto(ruta)
    pg.wait_for_timeout(400)
    return nav, pg


def _alimentar(pg, eventos, envivo=True):
    """Pasa la transcripcion por burbuja(), el mismo camino que el WS."""
    pg.evaluate("""([evs, envivo]) => {
        for (const e of evs) burbuja(e.quien, e.texto, e.t, e.ag, envivo);
    }""", [eventos, envivo])


def _bloques(pg):
    return pg.evaluate("""() => [...document.querySelectorAll(
        'details.actividad.agente')].map(d => ({
          clave: d.dataset.agente, estado: d.dataset.estado,
          titulo: d.querySelector('.act-titulo').textContent,
          metrica: d.querySelector('.ag-metrica').textContent,
          items: [...d.querySelectorAll('.items > *')]
                   .map(x => x.textContent)}))""")


def _transcripcion_de(lineas_evento, tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    for l in lineas_evento:
        s._procesar_linea(l)
    return s.transcripcion()


def test_chromium_agrupa_los_tres_agentes(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    trans = _transcripcion_de(_WORKFLOW_3, tmp_path, monkeypatch)
    with sync_playwright() as pw:
        nav, pg = _pagina(pw)
        try:
            _alimentar(pg, trans)
            bl = _bloques(pg)
            assert [b["clave"] for b in bl] == [
                "r1#pasos.1@1", "r1#pasos.2@2", "r1#pasos.3@3"], bl
            assert all(b["estado"] == "ok" for b in bl), bl
            assert bl[0]["titulo"].startswith("agente 1/3 paso A")
            assert bl[0]["metrica"] == "1.5s · 100 tok", bl[0]
            # un decimal SIEMPRE: el 2.0 del servidor llega como 2 en JSON y
            # "2s" junto a "1.5s" en la misma columna se lee torcido
            assert bl[1]["metrica"] == "2.0s · 120 tok", bl[1]
            # el latido NO ensucia la lista: 2 filas (inicio y fin), no 3
            assert len(bl[0]["items"]) == 2, bl[0]["items"]
            # las lineas del WORKFLOW quedan fuera de los bloques por agente
            gen = pg.evaluate("""() => [...document.querySelectorAll(
                'details.actividad:not(.agente) .items > *')]
                .map(e => e.textContent)""")
            assert any("workflow" in t for t in gen), gen
        finally:
            nav.close()


def test_chromium_pinta_vivo_y_fallo(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    trans = _transcripcion_de([
        _WORKFLOW_3[1],                       # AgenteInicio 1 -> vivo
        _ev("AgenteProgreso", run_id="r1", agente_id="r1#pasos.1@1", chars=42),
        _ev("AgenteInicio", run_id="r1", agente_id="r1#pasos.2@2", indice=2,
            total=3, fase="pasos", etiqueta="paso B"),
        _ev("AgenteFin", run_id="r1", agente_id="r1#pasos.2@2", indice=2,
            total=3, etiqueta="paso B", ok=False, motivo="cancelado por el "
            "usuario"),
    ], tmp_path, monkeypatch)
    with sync_playwright() as pw:
        nav, pg = _pagina(pw)
        try:
            _alimentar(pg, trans)
            bl = {b["clave"]: b for b in _bloques(pg)}
            assert bl["r1#pasos.1@1"]["estado"] == "vivo"
            # el latido va a la CABECERA (chars), no a una fila
            assert "42 chars" in bl["r1#pasos.1@1"]["metrica"]
            assert len(bl["r1#pasos.1@1"]["items"]) == 1
            assert bl["r1#pasos.2@2"]["estado"] == "fallo"
            assert "cancelado" in bl["r1#pasos.2@2"]["items"][-1]
        finally:
            nav.close()


def test_chromium_respaldo_por_regex_sin_el_campo(tmp_path, monkeypatch):
    """Transcripcion VIEJA (sin `ag`): el cliente cae al regex y agrupa igual.
    Es el 'respaldo cuando no' del pedido."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    viejo = [
        {"t": "10:00:00", "quien": "actividad", "texto": "· agente 1/2 paso A…"},
        {"t": "10:00:01", "quien": "actividad",
         "texto": "⏺ agente 1/2 paso A — listo (1.5s · 100 tok)"},
        {"t": "10:00:02", "quien": "actividad", "texto": "· agente 2/2 paso B…"},
    ]
    with sync_playwright() as pw:
        nav, pg = _pagina(pw)
        try:
            _alimentar(pg, viejo, envivo=False)
            bl = _bloques(pg)
            assert [b["clave"] for b in bl] == ["~texto:1/2", "~texto:2/2"], bl
            assert bl[0]["titulo"].startswith("agente 1/2 paso A")
            # sin campo no hay estado que pintar, pero las filas estan
            assert len(bl[0]["items"]) == 2 and len(bl[1]["items"]) == 1
        finally:
            nav.close()


def test_chromium_muestra_el_aviso_de_lineas_perdidas():
    """El aviso del techo de la cola tiene que VERSE, no quedarse en el log."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav, pg = _pagina(pw)
        try:
            _alimentar(pg, [{"t": "10:00:00", "quien": "sistema",
                             "texto": "⚠ se perdieron 42 lineas mientras "
                                      "estabas desconectado"}])
            visible = pg.evaluate("""() => [...document.querySelectorAll(
                '#chat .msg.sistema')].map(e => e.textContent)""")
            assert any("se perdieron 42 lineas" in t for t in visible), visible
        finally:
            nav.close()


# ── 8. el eco ENVUELTO (la cola sin marca) ─────────────────────────────────
# Lineas COPIADAS de un REPL real (2026-08-18, /workflow contra :8080): rich
# parte el eco de AgenteFin en 3 y solo la primera lleva ⏺. Sin la regla de
# cola, las otras dos entraban al chat como prosa de Cognia.

_ECO_ENVUELTO = [
    "  ⏺ agente 1/2 di solo ALFA — I'm sorry, but your message seems "
    "incomplete.",
    "Could you please provide more context or clarify what you are asking "
    "about…",
    "(1.3s · 77 tok)",
]


def test_la_cola_de_un_eco_envuelto_no_entra_al_chat(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_WORKFLOW_3[1])          # activa el modo eventos
    for l in _ECO_ENVUELTO:
        s._procesar_linea(l)
    textos = [e["texto"] for e in _lineas(s)]
    assert len(textos) == 1, textos            # solo el evento, 0 ecos
    assert textos[0].startswith("· agente 1/3 paso A")


def test_el_panel_de_resultado_NO_se_come_por_la_cola(tmp_path, monkeypatch):
    """El freno: un eco CORTO no abre cola, y nada que empiece por marco de
    panel es cola. Si esto falla, la regla anti-duplicado se traga la
    respuesta — peor que el duplicado que arregla."""
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_WORKFLOW_3[8])          # WorkflowFin (eco corto)
    for l in ["  ⏺ workflow «repl» — 3 de 3 · 115 tokens · 0.6s",
              "│ --- paso 1: di solo la palabra ALFA                          │",
              "│ ALFA                                                         │"]:
        s._procesar_linea(l)
    textos = [e["texto"] for e in _lineas(s)]
    assert any("paso 1" in t for t in textos), textos
    assert any("ALFA" in t for t in textos), textos


def test_la_cola_tiene_tope_y_no_se_come_media_respuesta(tmp_path,
                                                         monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_WORKFLOW_3[1])
    s._procesar_linea(_ECO_ENVUELTO[0])
    larga = "x" * 70
    for _ in range(6):                         # 6 lineas largas seguidas
        s._procesar_linea(larga)
    textos = [e["texto"] for e in _lineas(s)]
    # 4 de cola como mucho: las otras 2 llegan al chat
    assert textos.count(larga) == 2, textos
