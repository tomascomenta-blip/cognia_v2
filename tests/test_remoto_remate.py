"""
Remate del remoto (verificador e2e 2026-08-25): lo que el clasificador y el
servidor hacian mal con un REPL REAL detras y no cazaba la suite.

  1. Un eco del renderer de 60-79 chars ("  · filtrando <url>") dejaba la
     cola de eco armada y la RESPUESTA FINAL se tragaba entera (ni chat ni
     jsonl). Causa: la cola se inferia por longitud (>= 60 con rich a 80) y
     ningun evento la cerraba.
  2. Los Avisos de confianza, envueltos por rich a 80 columnas, entraban al
     chat como burbujas cognia: el eco se casaba solo entero.
  3. Con un WS abierto el servidor tardaba 29,1 s en salir por CTRL_BREAK y
     dejaba un traceback CancelledError: to_thread(q.get, timeout=30).
  4. `except Exception: pass` en Sesion._bombear: un reventon del
     clasificador mataba el lector en silencio y el REPL se bloqueaba al
     llenar el pipe.

Todos SIN modelo; RAIZ_DATOS parcheada en sesiones Y servidor.
"""
from __future__ import annotations

import io
import json
import signal
import threading
import time
import types

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cognia.remoto import servidor as _srv
from cognia.remoto import sesiones as _ses
from cognia.remoto.sesiones import (ANCHO_COLUMNAS_REMOTO, ColaSuscriptor,
                                    Sesion, _ANCHO_ECO, _corte_de_envoltorio,
                                    registrar_proyecto)


def _ev(tipo: str, **campos) -> str:
    return "@EV " + json.dumps({"tipo": tipo, "ts": 0.0, "agente_id": "",
                                **campos}, ensure_ascii=False)


def _sesion(tmp_path, monkeypatch) -> Sesion:
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    s._arrancando = False
    return s


def _lineas(s: Sesion) -> list[dict]:
    if not s.fichero.exists():
        return []
    return [json.loads(l)
            for l in s.fichero.read_text(encoding="utf-8").splitlines()]


def _fisicas(texto: str, ancho: int) -> list[str]:
    """Lo que el renderer REAL (rich, Console.print de '  {texto}') escribe
    en un pipe de `ancho` columnas, linea fisica a linea fisica."""
    from rich.console import Console
    buf = io.StringIO()
    Console(file=buf, width=ancho, highlight=False, force_terminal=False,
            no_color=True).print("  " + texto, markup=False, highlight=False)
    return [l for l in buf.getvalue().splitlines() if l.strip()]


_AVISO_A_PRIORI = ("◐ confianza a priori BAJA: métrica de plataforma "
                   "('suscriptores'); plataforma (youtube); pide una cifra "
                   "('cuantos') → investigando en la web…")
_URL_LARGA = ("https://kirainet.com/tokio-ciudad-numero-4-detras-de-londres-"
              "nueva-york-y-paris/…")


# ── 1. la respuesta final no se traga como cola de un eco ─────────────────

@pytest.mark.parametrize("url", [
    "https://socialblade.com/youtube/handle/aquaboy666…",        # eco de 64
    "https://www.youtube.com/c/ThatBoyAqua…",                    # eco de 52
    "https://socialblade.com/youtube/handle/aquaboy666/realtime…",  # 73
])
def test_1_respuesta_final_tras_eco_de_url_llega_al_chat(tmp_path, monkeypatch,
                                                          url):
    """El repro literal del verificador: Aviso '· filtrando <url>' + su eco
    del renderer, TokenTexto (la via de confianza NO imprime '· pensando…'
    entre medias), la respuesta final plana y el Confianza. Antes con la URL
    de 64 chars: cognia == []."""
    s = _sesion(tmp_path, monkeypatch)
    for l in [_ev("Aviso", texto="· filtrando " + url, origen="confianza"),
              "  · filtrando " + url,
              _ev("TokenTexto", texto="89.8"),
              _ev("TokenTexto", texto=" mil suscriptores [4]."),
              "89.8 mil suscriptores [4].",
              _ev("Confianza", nivel="media", glifo="◐", valor=0.7,
                  fuentes=[], texto="◐ confianza MEDIA (0,70)")]:
        s._procesar_linea(l)
    s._agrupador().vaciar()
    cognia = [e["texto"] for e in _lineas(s) if e["quien"] == "cognia"]
    assert cognia == ["89.8 mil suscriptores [4]."]
    assert "  · filtrando" not in " ".join(e["texto"] for e in _lineas(s))


def test_1b_una_linea_evento_cierra_la_cola_de_eco(tmp_path, monkeypatch):
    """Cola armada de verdad (eco que llena el ancho) + un evento cualquiera
    en medio: la prosa que sigue al evento es OTRA cosa, nunca cola."""
    s = _sesion(tmp_path, monkeypatch)
    eco_largo = "  ⏺ agente 1/2 " + "x" * _ANCHO_ECO
    s._procesar_linea(_ev("AgenteInicio", agente_id="a1"))
    s._procesar_linea(eco_largo)
    assert s._cola_eco > 0
    s._procesar_linea(_ev("TareaFin", ok=True, pasos=1))
    assert s._cola_eco == 0
    s._procesar_linea("La respuesta final, corta.")
    assert [e["texto"] for e in _lineas(s) if e["quien"] == "cognia"] == [
        "La respuesta final, corta."]


def test_1c_la_cola_por_longitud_solo_actua_al_ancho_real():
    """La heuristica de 'viene envuelto' se ata al ancho que _entorno fija:
    un eco de 60-79 chars (el caso del bug) ya no cuenta como envuelto."""
    assert _ANCHO_ECO > 79
    assert _ANCHO_ECO == ANCHO_COLUMNAS_REMOTO - 40


# ── 2. los Avisos envueltos por rich no entran al chat ────────────────────

@pytest.mark.parametrize("ancho", [80, ANCHO_COLUMNAS_REMOTO])
def test_2_aviso_a_priori_envuelto_no_es_burbuja_cognia(tmp_path, monkeypatch,
                                                         ancho):
    """El aviso a priori (127 chars) y una URL mas larga que la linea, tal
    como los escribe rich a 80 (dos y tres lineas fisicas) y al ancho del
    remoto (una): nada de eso es 'cognia'; la respuesta si."""
    s = _sesion(tmp_path, monkeypatch)
    lineas = [_ev("Aviso", texto=_AVISO_A_PRIORI, origen="confianza"),
              *_fisicas(_AVISO_A_PRIORI, ancho),
              _ev("Aviso", texto="· filtrando " + _URL_LARGA, origen="confianza"),
              *_fisicas("· filtrando " + _URL_LARGA, ancho),
              _ev("TokenTexto", texto="Tokio tiene 14 millones."),
              "Tokio tiene 14 millones.",
              _ev("FooterTurno", ok=True, segundos=1.0, tokens=0,
                  ctx_libre_pct=90.0)]
    if ancho == 80:
        # el escenario real: rich SI partio (2 lineas el aviso, 3 la URL)
        assert len(_fisicas(_AVISO_A_PRIORI, 80)) == 2
        assert len(_fisicas("· filtrando " + _URL_LARGA, 80)) == 3
    else:
        assert len(_fisicas(_AVISO_A_PRIORI, ancho)) == 1
    for l in lineas:
        s._procesar_linea(l)
    s._agrupador().vaciar()
    por_quien = [(e["quien"], e["texto"]) for e in _lineas(s)]
    assert [t for q, t in por_quien if q == "cognia"] == ["Tokio tiene 14 millones."]
    assert [q for q, _ in por_quien] == ["actividad", "actividad", "cognia", "footer"]
    assert por_quien[0][1].startswith("⚠ ◐ confianza a priori")
    assert s._eco_resto == "" and len(s._ecos_pendientes) == 0


def test_2b_entorno_fija_COLUMNS_y_rich_lo_honra_sobre_un_pipe(tmp_path,
                                                                monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    env = s._entorno()
    assert env["COLUMNS"] == str(ANCHO_COLUMNAS_REMOTO)
    assert env["TERM"] == "dumb"
    # rich lee COLUMNS del entorno cuando no hay terminal (pipe): la linea
    # logica sale ENTERA y casa exacta con el eco del evento
    from rich.console import Console
    monkeypatch.setenv("COLUMNS", env["COLUMNS"])
    buf = io.StringIO()
    c = Console(file=buf, highlight=False, force_terminal=False, no_color=True)
    # rich resta 1 en 'legacy windows' (pipe sin VT): 299; el margen de
    # _ANCHO_ECO (40) lo cubre de sobra
    assert c.size.width in (ANCHO_COLUMNAS_REMOTO - 1, ANCHO_COLUMNAS_REMOTO)
    c.print("  " + _AVISO_A_PRIORI, markup=False, highlight=False)
    assert [l.strip() for l in buf.getvalue().splitlines() if l.strip()] == [
        _AVISO_A_PRIORI]


def test_2c_corte_de_envoltorio_es_como_corta_rich():
    logica = "· filtrando https://a.b/c-d-e-f-g-h-i-j-k-l-m-n-o-p-q-r-s-t-u-v-w-x-y-z…"
    assert _corte_de_envoltorio(logica, "· filtrando")           # en espacio
    assert _corte_de_envoltorio(logica, logica)                  # entera
    assert _corte_de_envoltorio(logica, logica[:48])             # URL plegada
    assert not _corte_de_envoltorio(logica, "· filtr")           # media palabra
    assert not _corte_de_envoltorio(logica, "")                  # vacia
    assert not _corte_de_envoltorio(logica, "otra cosa")


def test_2d_un_eco_a_medias_que_no_sigue_se_suelta(tmp_path, monkeypatch):
    """Casado el primer trozo, si la siguiente linea NO es el resto, el
    resto se olvida y esa linea se clasifica normal (no se traga)."""
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_ev("Aviso", texto="hola mundo cruel", origen="x"))
    s._procesar_linea("  hola mundo")
    assert s._eco_resto == "cruel"
    s._procesar_linea("Respuesta que no es la cola.")
    assert s._eco_resto == ""
    assert [e["texto"] for e in _lineas(s) if e["quien"] == "cognia"] == [
        "Respuesta que no es la cola."]


def test_2e_el_footer_vacia_los_ecos_pendientes(tmp_path, monkeypatch):
    """La linea de Confianza no la pinta el renderer bajo remoto: su eco
    quedaba pendiente turno tras turno (maxlen 64). El FooterTurno cierra
    el turno y con el, los ecos que ya no van a llegar."""
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_ev("Confianza", nivel="alta", glifo="●", valor=0.9,
                          fuentes=[], texto="● confianza ALTA (0,90)"))
    assert len(s._ecos_pendientes) == 1
    s._procesar_linea(_ev("FooterTurno", ok=True, segundos=1.0, tokens=0,
                          ctx_libre_pct=90.0))
    assert len(s._ecos_pendientes) == 0


def test_2f_glifos_de_confianza_con_sangria_del_renderer_son_actividad():
    from cognia.remoto.sesiones import reclasificar
    assert reclasificar("cognia", "  ◐ confianza a priori BAJA: x", False)[0] == "actividad"
    # sin la sangria exacta del renderer sigue siendo prosa (respuesta final)
    assert reclasificar("cognia", "◐ un glifo en la respuesta", False)[0] == "cognia"


# ── 3. apagado con WS abierto: decimas, sin traceback ─────────────────────

def _app_con_sesion(tmp_path, monkeypatch):
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "proy"
    proyecto.mkdir(exist_ok=True)
    pr = registrar_proyecto(str(proyecto))
    app = _srv.crear_app()
    tok = _srv.asegurar_token(tmp_path)
    s = app.state.gestor.obtener(pr, "s1")       # sin arrancar el REPL
    return app, pr, tok, s


def test_3_despertar_para_apagar_cierra_el_ws_con_1001(tmp_path, monkeypatch):
    app, pr, tok, s = _app_con_sesion(tmp_path, monkeypatch)
    c = TestClient(app)
    with c.websocket_connect(f"/ws/{pr['id']}/s1?token={tok}") as ws:
        # el WS esta suscrito y esperando (sin hilo del pool: Event)
        for _ in range(50):
            if s.suscriptores:
                break
            time.sleep(0.02)
        assert len(s.suscriptores) == 1
        t0 = time.monotonic()
        assert _srv.despertar_para_apagar(app) == 1
        aviso = ws.receive_json()
        assert aviso["apagando"] is True and aviso["quien"] == "sistema"
        with pytest.raises(WebSocketDisconnect) as ex:
            ws.receive_text()
        assert ex.value.code == 1001
        assert time.monotonic() - t0 < 2.0
    for _ in range(50):
        if not s.suscriptores:
            break
        time.sleep(0.02)
    assert s.suscriptores == []                   # se dio de baja


def test_3b_los_eventos_siguen_llegando_al_instante_por_el_event(tmp_path,
                                                                 monkeypatch):
    """Sin hilo del pool la latencia sigue siendo la del Event, no la de un
    poll: anotar() -> el WS lo recibe en milisegundos."""
    app, pr, tok, s = _app_con_sesion(tmp_path, monkeypatch)
    c = TestClient(app)
    with c.websocket_connect(f"/ws/{pr['id']}/s1?token={tok}") as ws:
        for _ in range(50):
            if s.suscriptores:
                break
            time.sleep(0.02)
        t0 = time.monotonic()
        s.anotar("cognia", "hola movil")
        assert ws.receive_json()["texto"] == "hola movil"
        assert time.monotonic() - t0 < 1.0
        ws.close()


def test_3c_handle_exit_despierta_los_ws_y_pide_salir(tmp_path, monkeypatch):
    """La subclase de uvicorn.Server: la senal despierta a los suscriptores
    (en un hilo propio, ver el comentario) y despues marca should_exit."""
    import uvicorn
    app, pr, tok, s = _app_con_sesion(tmp_path, monkeypatch)
    q = ColaSuscriptor()
    s.suscriptores.append(q)
    srv = _srv._servidor_uvicorn(app)(uvicorn.Config(app))
    srv.handle_exit(signal.SIGINT, None)
    assert srv.should_exit is True
    ev = q.get(timeout=2.0)
    assert ev["apagando"] is True
    for _ in range(50):
        if srv.apagados:
            break
        time.sleep(0.02)
    assert srv.apagados == 1


def test_3d_cola_al_poner_que_revienta_no_es_mudo(tmp_path, monkeypatch, capsys):
    """El callback del WS puede fallar (loop cerrado): la excepcion sube al
    productor, que descarta ESA cola y lo dice en stderr — nunca en silencio
    ni tumbando a las demas."""
    s = _sesion(tmp_path, monkeypatch)
    rota = ColaSuscriptor(al_poner=lambda: (_ for _ in ()).throw(RuntimeError("loop cerrado")))
    sana = ColaSuscriptor()
    s.suscriptores.extend([rota, sana])
    s.anotar("cognia", "x")
    assert sana.get(timeout=1.0)["texto"] == "x"
    assert s.suscriptores == [sana]
    assert "suscriptor descartado" in capsys.readouterr().err


# ── 4. el lector no muere en silencio ─────────────────────────────────────

def test_4_bombear_sobrevive_a_un_reventon_del_clasificador(tmp_path, monkeypatch,
                                                             capsys):
    s = _sesion(tmp_path, monkeypatch)
    s.proc = types.SimpleNamespace(
        stdout=io.StringIO("primera\nBOOM\nBOOM\nBOOM\nBOOM\nultima\n"),
        wait=lambda timeout=None: 0, poll=lambda: 0)
    original = Sesion._procesar_linea

    def explosivo(self, linea):
        if linea == "BOOM":
            raise ValueError("clasificador roto")
        return original(self, linea)
    monkeypatch.setattr(Sesion, "_procesar_linea", explosivo)
    s._bombear()
    ev = _lineas(s)
    textos = [(e["quien"], e["texto"]) for e in ev]
    assert ("cognia", "primera") in textos
    assert ("cognia", "ultima") in textos          # siguio leyendo tras el fallo
    assert textos[-1] == ("sistema", "sesion terminada")
    assert [t for q, t in textos if q == "log"] == ["BOOM"] * 4   # crudas al Registro
    avisos = [t for q, t in textos if q == "sistema" and "clasificador" in t]
    assert len(avisos) == 3 and "ValueError" in avisos[0]        # tope de 3 al chat
    err = capsys.readouterr().err
    assert err.count("clasificador fallo en la linea") == 4 and "Traceback" in err


def test_4b_bombear_sin_fallos_no_ensucia_nada(tmp_path, monkeypatch, capsys):
    s = _sesion(tmp_path, monkeypatch)
    s.proc = types.SimpleNamespace(stdout=io.StringIO("hola\n"),
                                   wait=lambda timeout=None: 0, poll=lambda: 0)
    s._bombear()
    assert [(e["quien"], e["texto"]) for e in _lineas(s)] == [
        ("cognia", "hola"), ("sistema", "sesion terminada")]
    assert capsys.readouterr().err == ""
