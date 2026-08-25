"""
Paridad remoto <-> CLI (2026-08-24), lado CLIENTE: cognia/remoto/static/index.html.

El HTML es un monolito sin build; lo que se prueba aqui es el JS REAL en
Chromium headless (playwright, misma via que tests/test_remoto_agrupado.py):
se carga por file://, se falsifica `fetch`/`WebSocket` dentro de la pagina y
se ejercitan las funciones con page.evaluate. Sin playwright, los tests de
Chromium se saltan y quedan los de regex sobre el HTML.

Contrato cubierto (letras del pedido):
  A  boton "Detener" visible entre el primer delta/progreso y la final; POST
     .../interrumpir; oculto si /api/version no anuncia "interrumpir" (K).
  B  el textarea manda el texto CON sus "\\n"; Enter envia, Shift+Enter salta.
  C  burbuja viva por delta; la final la REEMPLAZA (una sola burbuja) y va
     con markdown.
  D  chip de confianza (fuentes clicables) y footer gris.
  E  un resultado largo de comando slash se ve como burbuja cognia.
  F  sugerencias @fichero (Tab completa) y subida de adjuntos.
  G  dialogo de nueva sesion con acceso restringido por defecto.
  I  reconexion del WS con backoff 1,2,4..30 s y reanudar desde la ultima
     linea vista; punto verde/ambar/rojo.
  J  historial con flechas; fuzzy por subsecuencia en los comandos.
"""

import json
import pathlib
import re

import pytest

HTML = (pathlib.Path(__file__).resolve().parent.parent
        / "cognia" / "remoto" / "static" / "index.html")


# ── regex sobre el HTML (sin navegador) ────────────────────────────────────

def test_html_declara_los_controles_nuevos():
    h = HTML.read_text(encoding="utf-8")
    for ident in ("btn-detener", "btn-adjuntar", "adjunto", "dlg-sesion",
                  "sesion-titulo", "form-sesion", "estado-punto"):
        assert f'id="{ident}"' in h, ident
    # restringido es el default del FRONT (el back conserva "total")
    assert re.search(r'value="restringido"\s+checked', h)
    assert not re.search(r'value="total"\s+checked', h)
    # la linea que explica que total permite computer-use sin confirmacion
    assert re.search(r"computer-use.*SIN confirmaci", h, re.I)


def test_html_sin_dependencias_externas():
    """CSP: nada de CDN. Solo se admite el rel=noopener de los enlaces que
    genera el markdown (van a donde apunte la respuesta, no a un script)."""
    h = HTML.read_text(encoding="utf-8")
    assert not re.search(r'<script[^>]+src=', h)
    assert not re.search(r'<link[^>]+href="https?://', h)
    assert "@import" not in h


# ── Chromium: el cliente de verdad ─────────────────────────────────────────

_FETCH_FALSO = """
(respuestas) => {
  window.__llamadas = [];
  window.fetch = async (url, o) => {
    o = o || {};
    let body = o.body;
    if (body && typeof FormData !== "undefined" && body instanceof FormData)
      body = "FormData:" + [...body.keys()].join(",");
    window.__llamadas.push({url: String(url), method: o.method || "GET", body});
    const r = respuestas.find(x => String(url).includes(x.match));
    const status = r && r.status ? r.status : 200;
    return {ok: status < 400, status, statusText: "X",
            json: async () => (r ? r.json : {})};
  };
}
"""

_WS_FALSO = """
() => {
  window.__ws = [];
  class WSFalso {
    constructor(url) { this.url = url; this.readyState = 0; window.__ws.push(this); }
    close() { this.readyState = 3; }
    send() {}
  }
  window.WebSocket = WSFalso;
}
"""


def _pagina(pw):
    nav = pw.chromium.launch()
    pg = nav.new_context().new_page()
    pg.goto(HTML.as_uri())
    pg.wait_for_timeout(300)
    pg.evaluate(_WS_FALSO)
    return nav, pg


@pytest.fixture
def pg():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav, pagina = _pagina(pw)
        try:
            yield pagina
        finally:
            nav.close()


def _alimentar(pg, eventos, envivo=True):
    pg.evaluate("""([evs, envivo]) => {
        for (const e of evs) burbuja(e.quien, e.texto, e.t, e.ag, envivo, e);
    }""", [eventos, envivo])


def _cognias(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#chat .msg.cognia')]
        .map(e => ({viva: e.classList.contains('viva'),
                    html: e.querySelector('.md').innerHTML,
                    texto: e.querySelector('.md').textContent}))""")


def _sistemas(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#chat .msg.sistema')]
        .map(e => e.textContent)""")


def _con_sesion(pg, caps=("interrumpir", "delta", "subir")):
    pg.evaluate("""(caps) => {
        S.proyecto = {id: "p1", nombre: "P"}; S.sesion = "s1";
        aplicarCaps({caps});
    }""", list(caps))


# ── A + K: Detener ───────────────────────────────────────────────────────────

def test_detener_oculto_sin_capacidad_y_visible_generando(pg):
    _con_sesion(pg, caps=())
    pg.evaluate("() => marcarGenerando(true)")
    est = pg.evaluate("""() => { const b = $('btn-detener');
        return {hidden: b.hidden, visible: b.classList.contains('visible')}; }""")
    assert est == {"hidden": True, "visible": False}, est
    # el servidor anuncia la capacidad: aparece SOLO mientras se genera
    pg.evaluate("() => aplicarCaps({caps: ['interrumpir', 'delta']})")
    assert pg.evaluate("() => $('btn-detener').hidden") is False
    assert pg.evaluate("() => $('btn-detener').classList.contains('visible')") is False
    _alimentar(pg, [{"quien": "delta", "texto": "Hol"}])
    assert pg.evaluate("() => $('btn-detener').classList.contains('visible')") is True
    _alimentar(pg, [{"quien": "cognia", "texto": "Hola.", "t": "10:00:00"}])
    assert pg.evaluate("() => $('btn-detener').classList.contains('visible')") is False


def test_progreso_de_agente_enciende_detener(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "actividad", "texto": "generando…",
                     "ag": {"id": "r1#pasos.1@1", "chars": 42}}])
    assert pg.evaluate("() => S.generando") is True
    # el footer del turno lo apaga
    _alimentar(pg, [{"quien": "footer", "texto": "✓ 1.0s · 10 tokens", "ok": True}])
    assert pg.evaluate("() => S.generando") is False


def test_detener_hace_post_interrumpir_y_muestra_el_motivo(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/interrumpir",
                                "json": {"ok": False, "motivo": "no hay generacion en curso"}}])
    pg.evaluate("() => interrumpir()")
    ll = pg.evaluate("() => window.__llamadas")
    assert ll == [{"url": "/api/proyectos/p1/sesiones/s1/interrumpir",
                   "method": "POST", "body": None}], ll
    assert any("no hay generacion en curso" in t for t in _sistemas(pg))
    # ok=true sin motivo: sin ruido (la confirmacion la manda el REPL como Aviso)
    pg.evaluate(_FETCH_FALSO, [{"match": "/interrumpir", "json": {"ok": True, "motivo": ""}}])
    pg.evaluate("() => interrumpir()")
    assert len(_sistemas(pg)) == 1
    # ok=true CON motivo (el real: dice el limite de la senal, hallazgo 9
    # 2026-08-25): se pinta, para que Detener no parezca muerto mientras el
    # REPL sigue bloqueado esperando al modelo
    from cognia.remoto.sesiones import MOTIVO_INTERRUPCION_ENVIADA as MOTIVO
    pg.evaluate(_FETCH_FALSO, [{"match": "/interrumpir", "json": {"ok": True, "motivo": MOTIVO}}])
    pg.evaluate("() => interrumpir()")
    assert any("al terminar la llamada en curso" in t for t in _sistemas(pg))


def test_el_aviso_de_interrupcion_cierra_el_turno(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "delta", "texto": "Voy a "},
                    {"quien": "sistema", "texto": "generacion interrumpida desde el remoto"}])
    assert pg.evaluate("() => S.generando") is False
    assert not any(c["viva"] for c in _cognias(pg))
    # el REPL real lo manda como ACTIVIDAD ("⚠ generacion interrumpida desde
    # el remoto", medido 2026-08-25): tambien cierra el turno
    _alimentar(pg, [{"quien": "delta", "texto": "Otra vez "},
                    {"quien": "actividad", "texto": "⚠ generacion interrumpida desde el remoto"}])
    assert pg.evaluate("() => S.generando") is False
    assert not any(c["viva"] for c in _cognias(pg))


# ── C: burbuja viva y reemplazo ──────────────────────────────────────────────

def test_delta_acumula_en_una_viva_y_la_final_la_reemplaza(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "delta", "texto": "Hola, "},
                    {"quien": "delta", "texto": "soy **Cog"},
                    {"quien": "delta", "texto": "nia**."}])
    c = _cognias(pg)
    assert len(c) == 1 and c[0]["viva"] and c[0]["texto"] == "Hola, soy Cognia.", c
    _alimentar(pg, [{"quien": "cognia", "texto": "Hola, soy **Cognia**. Listo.",
                     "t": "10:00:01"}])
    c = _cognias(pg)
    # UNA burbuja (no dos), ya no viva, con markdown renderizado
    assert len(c) == 1 and not c[0]["viva"], c
    assert "<strong>Cognia</strong>" in c[0]["html"]
    assert c[0]["texto"] == "Hola, soy Cognia. Listo."


def test_delta_no_se_pinta_al_releer_la_transcripcion(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "delta", "texto": "fantasma"}], envivo=False)
    assert _cognias(pg) == []


def test_delta_tras_actividad_baja_la_viva_al_final(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "delta", "texto": "Voy a leer el fichero"},
                    {"quien": "actividad", "texto": "RESULTADO leer_archivo OK"},
                    {"quien": "delta", "texto": "El fichero dice"},
                    {"quien": "cognia", "texto": "El fichero dice hola.", "t": "1"}])
    orden = pg.evaluate("""() => [...document.querySelector('#chat').children]
        .map(e => e.className.split(' ')[0] + (e.tagName === 'DETAILS' ? ':det' : ''))""")
    # la respuesta queda DEBAJO de la actividad, y hay una sola burbuja
    assert orden[-1].startswith("msg") and "actividad" in orden[-2], orden
    assert len(_cognias(pg)) == 1


# ── D: confianza y footer ────────────────────────────────────────────────────

def test_chip_de_confianza_bajo_la_burbuja_con_fuentes_clicables(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "cognia", "texto": "La capital es Paris.", "t": "1"},
                    {"quien": "confianza", "texto": "confianza alta · 2 fuentes",
                     "nivel": "alta", "glifo": "●",
                     "fuentes": ["https://es.wikipedia.org/wiki/Paris", "memoria local"]}])
    chip = pg.evaluate("""() => { const c = document.querySelector('#chat .msg.cognia .confianza');
        return c && {nivel: c.dataset.nivel, texto: c.textContent,
                     links: [...c.querySelectorAll('a')].map(a => a.href)}; }""")
    assert chip and chip["nivel"] == "alta", chip
    assert "●" in chip["texto"] and "memoria local" in chip["texto"]
    assert chip["links"] == ["https://es.wikipedia.org/wiki/Paris"]


def test_footer_gris_cierra_el_bloque_de_respuesta(pg):
    _con_sesion(pg)
    _alimentar(pg, [{"quien": "cognia", "texto": "uno", "t": "1"},
                    {"quien": "footer", "texto": "✓ 14.6s · 312 tokens · ctx 95% libre",
                     "ok": True, "segundos": 14.6, "tokens": 312},
                    {"quien": "cognia", "texto": "dos", "t": "2"}])
    foot = pg.evaluate("() => [...document.querySelectorAll('.footer-turno')].map(e => e.textContent)")
    assert foot == ["✓ 14.6s · 312 tokens · ctx 95% libre"]
    # el footer separa los turnos: "dos" es OTRA burbuja, no se pega a "uno"
    assert [c["texto"] for c in _cognias(pg)] == ["uno", "dos"]
    _alimentar(pg, [{"quien": "footer", "texto": "✗ 0.2s · 0 tokens · error", "ok": False}])
    assert pg.evaluate("() => document.querySelectorAll('.footer-turno.fallo').length") == 1


# ── E: resultado largo de un slash como burbuja ─────────────────────────────

def test_resultado_largo_de_slash_se_ve_como_burbuja_cognia(pg):
    _con_sesion(pg)
    largo = "## Comandos\n" + "\n".join(f"- /cmd{i} — hace {i}" for i in range(40)) + \
            "\n```\n$ cognia --help\n```"
    _alimentar(pg, [{"quien": "cognia", "texto": largo, "t": "1"}])
    c = _cognias(pg)
    assert len(c) == 1 and "<h2>" in c[0]["html"] and "<pre>" in c[0]["html"]
    assert c[0]["html"].count("<li>") == 40
    # y NO cayo plegada en un bloque de actividad
    assert pg.evaluate("() => document.querySelectorAll('details.actividad').length") == 0


# ── B: multilinea ────────────────────────────────────────────────────────────

def test_el_texto_viaja_con_sus_saltos_de_linea(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/mensaje", "json": {"ok": True}}])
    pg.evaluate("() => enviar('linea 1\\nlinea 2\\n  linea 3')")
    ll = pg.evaluate("() => window.__llamadas")
    assert ll[-1]["url"].endswith("/sesiones/s1/mensaje") and ll[-1]["method"] == "POST"
    assert json.loads(ll[-1]["body"]) == {"texto": "linea 1\nlinea 2\n  linea 3"}
    # enviar ARMA el boton Detener (188 s de "pensando" sin delta, medido)
    assert pg.evaluate("() => $('btn-detener').classList.contains('visible')") is True


def test_enter_envia_y_shift_enter_salta_de_linea(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/mensaje", "json": {"ok": True}}])
    ta = pg.locator("#entrada")
    ta.click()
    ta.type("hola")
    ta.press("Shift+Enter")
    ta.type("mundo")
    assert ta.input_value() == "hola\nmundo"
    assert pg.evaluate("() => window.__llamadas.length") == 0
    ta.press("Enter")
    ll = pg.evaluate("() => window.__llamadas")
    assert len(ll) == 1 and json.loads(ll[0]["body"]) == {"texto": "hola\nmundo"}
    assert ta.input_value() == ""


def test_error_del_servidor_al_enviar_se_ve(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/mensaje", "status": 413,
                                "json": {"error": "mensaje demasiado grande (max 1 MB)"}}])
    pg.evaluate("() => enviar('x')")
    assert any("max 1 MB" in t for t in _sistemas(pg))


# ── F: @fichero y adjuntos ───────────────────────────────────────────────────

def test_arroba_sugiere_ficheros_y_tab_completa(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/ficheros?q=re",
                                "json": {"items": ["README.md", "recursos/regla.txt"]}}])
    ta = pg.locator("#entrada")
    ta.click()
    ta.type("mira @re")
    pg.wait_for_timeout(350)
    ll = pg.evaluate("() => window.__llamadas.map(l => l.url)")
    assert "/api/proyectos/p1/ficheros?q=re" in ll, ll
    filas = pg.evaluate("() => [...document.querySelectorAll('#sugerencias .sug')].map(e => e.textContent)")
    assert filas == ["@README.md", "@recursos/regla.txt"], filas
    ta.press("ArrowDown")          # resalta la segunda
    ta.press("Tab")
    assert ta.input_value() == "mira @recursos/regla.txt "
    assert pg.evaluate("() => $('sugerencias').classList.contains('visible')") is False


def test_enter_completa_la_mencion_en_vez_de_enviar(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/ficheros?q=", "json": {"items": ["a.py"]}},
                               {"match": "/mensaje", "json": {"ok": True}}])
    ta = pg.locator("#entrada")
    ta.click(); ta.type("@a")
    pg.wait_for_timeout(350)
    ta.press("Enter")
    assert ta.input_value() == "@a.py "
    assert not any(l["url"].endswith("/mensaje") for l in pg.evaluate("() => window.__llamadas"))


def test_subir_adjunto_mete_la_mencion_en_el_textarea(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/subir",
                                "json": {"ruta": "imagenes/foto.png", "mencion": "@imagenes/foto.png"}}])
    pg.evaluate("() => { $('entrada').value = 'mira'; $('entrada').selectionStart = $('entrada').selectionEnd = 4; }")
    pg.evaluate("() => subirAdjunto(new File(['x'], 'foto.png', {type: 'image/png'}))")
    ll = pg.evaluate("() => window.__llamadas")
    assert ll[-1] == {"url": "/api/proyectos/p1/subir", "method": "POST",
                      "body": "FormData:archivo"}, ll
    assert pg.evaluate("() => $('entrada').value") == "mira @imagenes/foto.png "


def test_subida_rechazada_se_ve_como_linea_sistema(pg):
    _con_sesion(pg)
    pg.evaluate(_FETCH_FALSO, [{"match": "/subir", "status": 413,
                                "json": {"error": "supera 20 MB"}}])
    pg.evaluate("() => subirAdjunto(new File(['x'], 'grande.bin'))")
    assert any("grande.bin" in t and "supera 20 MB" in t for t in _sistemas(pg))


# ── G: nueva sesion con acceso ───────────────────────────────────────────────

def test_nueva_sesion_pide_acceso_y_el_default_es_restringido(pg):
    pg.evaluate(_FETCH_FALSO, [
        {"match": "/sesiones/nueva/transcripcion", "json": []},
        {"match": "/sesiones", "json": {"id": "nueva", "titulo": "T", "acceso": "restringido"}},
    ])
    pg.evaluate("() => { S.vistaIzq = 'sesiones'; S.proyecto = {id: 'p1', nombre: 'P'}; }")
    pg.evaluate("() => $('btn-nuevo-izq').click()")   # el cajon esta fuera de pantalla
    assert pg.evaluate("() => $('dlg-sesion').open") is True
    assert pg.evaluate("() => document.querySelector('#dlg-sesion input[name=acceso]:checked').value") == "restringido"
    pg.fill("#sesion-titulo", "prueba")
    pg.click("#sesion-crear")
    pg.wait_for_timeout(200)
    post = [l for l in pg.evaluate("() => window.__llamadas")
            if l["method"] == "POST" and l["url"].endswith("/sesiones")]
    assert post and json.loads(post[0]["body"]) == {"titulo": "prueba", "acceso": "restringido"}
    assert pg.evaluate("() => S.sesion") == "nueva"


def test_nueva_sesion_total_solo_si_se_elige(pg):
    pg.evaluate(_FETCH_FALSO, [
        {"match": "/transcripcion", "json": []},
        {"match": "/sesiones", "json": {"id": "n2", "titulo": "T", "acceso": "total"}},
    ])
    pg.evaluate("() => { S.vistaIzq = 'sesiones'; S.proyecto = {id: 'p1', nombre: 'P'}; }")
    pg.evaluate("() => $('btn-nuevo-izq').click()")   # el cajon esta fuera de pantalla
    pg.check("#dlg-sesion input[value=total]")
    pg.click("#sesion-crear")
    pg.wait_for_timeout(200)
    post = [l for l in pg.evaluate("() => window.__llamadas") if l["method"] == "POST"]
    assert json.loads(post[0]["body"])["acceso"] == "total"
    # cancelar no crea nada
    pg.evaluate("() => { window.__llamadas = []; }")
    pg.evaluate("() => $('btn-nuevo-izq').click()")   # el cajon esta fuera de pantalla
    pg.click("#sesion-cancelar")
    pg.wait_for_timeout(100)
    assert pg.evaluate("() => window.__llamadas.filter(l => l.method === 'POST').length") == 0


# ── I: reconexion con backoff y reanudar ─────────────────────────────────────

def test_ws_reconecta_con_backoff_exponencial_hasta_30s(pg):
    _con_sesion(pg)
    pg.evaluate("""() => {
        window.__esperas = [];
        window.setTimeout = (fn, ms) => { window.__esperas.push(ms); return 1; };
        conectarWS(S.proyecto, S.sesion);
        for (let i = 0; i < 7; i++) { const ws = window.__ws[window.__ws.length - 1];
          S.ws = ws; ws.onclose({code: 1006}); }
    }""")
    assert pg.evaluate("() => window.__esperas") == \
        [1000, 2000, 4000, 8000, 16000, 30000, 30000]
    assert pg.evaluate("() => $('estado-punto').classList.contains('ambar')") is True
    # al abrir de nuevo: verde y el contador a cero
    pg.evaluate("() => { const ws = conectarWS(S.proyecto, S.sesion); ws.onopen(); }")
    pg.wait_for_timeout(100)
    assert pg.evaluate("() => [S.reintento, $('estado-punto').classList.contains('vivo')]") == [0, True]


def test_token_invalido_no_reintenta_y_pone_rojo(pg):
    _con_sesion(pg)
    pg.evaluate("""() => {
        window.__esperas = [];
        window.setTimeout = (fn, ms) => { window.__esperas.push(ms); return 1; };
        const ws = conectarWS(S.proyecto, S.sesion); ws.onclose({code: 4401});
    }""")
    assert pg.evaluate("() => window.__esperas") == []
    assert pg.evaluate("() => $('estado-punto').classList.contains('rojo')") is True
    assert any("token" in t for t in _sistemas(pg))


def test_demasiados_intentos_4429_avisa_y_reintenta_tras_la_espera(pg):
    """WS cerrado con 4429 (IP bloqueada por fallos de token; el servidor
    no bloquea al token bueno): se pinta el reason con la espera y se
    reintenta UNA vez pasada esa espera, no con el backoff generico."""
    _con_sesion(pg)
    pg.evaluate("""() => {
        window.__esperas = [];
        window.setTimeout = (fn, ms) => { window.__esperas.push(ms); return 1; };
        const ws = conectarWS(S.proyecto, S.sesion);
        ws.onclose({code: 4429, reason: "demasiados intentos, espera 37 s"});
    }""")
    assert pg.evaluate("() => window.__esperas") == [37000]
    assert pg.evaluate("() => $('estado-punto').classList.contains('rojo')") is True
    assert any("espera 37 s" in t for t in _sistemas(pg))
    # sin reason: 60 s por defecto y un texto que lo diga
    pg.evaluate("""() => {
        window.__esperas = [];
        const ws = conectarWS(S.proyecto, S.sesion);
        ws.onclose({code: 4429});
    }""")
    assert pg.evaluate("() => window.__esperas") == [60000]
    assert any("demasiados intentos" in t for t in _sistemas(pg))


def test_al_reconectar_pinta_solo_lo_posterior_a_la_ultima_linea_vista(pg):
    _con_sesion(pg)
    viejas = [{"t": "10:00:00", "quien": "usuario", "texto": "hola"},
              {"t": "10:00:01", "quien": "cognia", "texto": "Hola."},
              {"t": "10:00:01", "quien": "cognia", "texto": "Hola."}]   # duplicada a proposito
    nuevas = [{"t": "10:00:05", "quien": "cognia", "texto": "Sigo aqui."},
              {"t": "10:00:06", "quien": "footer", "texto": "✓ 1s"}]
    pg.evaluate("(t) => { S.ultimas = []; pintarTranscripcion(t); }", viejas)
    pg.evaluate(_FETCH_FALSO, [{"match": "/transcripcion", "json": viejas + nuevas}])
    pg.evaluate("() => reanudarDesdeUltima(S.proyecto, S.sesion)")
    pg.wait_for_timeout(150)
    # (las dos "Hola." se juntan en un parrafo: mdHTML une lineas contiguas)
    assert [c["texto"] for c in _cognias(pg)] == ["Hola. Hola.", "Sigo aqui."]
    assert any("2 línea(s) recuperada(s)" in t for t in _sistemas(pg))
    # otra reconexion sin novedades: no duplica nada
    pg.evaluate("() => reanudarDesdeUltima(S.proyecto, S.sesion)")
    pg.wait_for_timeout(150)
    assert len(_cognias(pg)) == 2 and len(_sistemas(pg)) == 1


def test_reanudar_sin_ancla_avisa_en_vez_de_duplicar(pg):
    _con_sesion(pg)
    pg.evaluate("(t) => { S.ultimas = []; pintarTranscripcion(t); }",
                [{"t": "1", "quien": "cognia", "texto": "algo que ya no esta"}])
    pg.evaluate(_FETCH_FALSO, [{"match": "/transcripcion",
                                "json": [{"t": "2", "quien": "cognia", "texto": "otra cosa"}]}])
    pg.evaluate("() => reanudarDesdeUltima(S.proyecto, S.sesion)")
    pg.wait_for_timeout(150)
    assert len(_cognias(pg)) == 1
    assert any("reabre la sesión" in t for t in _sistemas(pg))


def test_los_delta_del_ws_no_cuentan_como_vistos(pg):
    _con_sesion(pg)
    pg.evaluate("""() => {
        S.ultimas = [];
        const ws = conectarWS(S.proyecto, S.sesion);
        ws.onmessage({data: JSON.stringify({quien: "delta", texto: "tro"})});
        ws.onmessage({data: JSON.stringify({t: "1", quien: "sistema", texto: "⚠ se perdieron 3 lineas", perdidas: 3})});
        ws.onmessage({data: JSON.stringify({t: "1", quien: "cognia", texto: "final"})});
    }""")
    assert pg.evaluate("() => S.ultimas") == ["1" + chr(1) + "cognia" + chr(1) + "final"]   # huella = t + SOH + quien + SOH + texto


# ── J: historial y fuzzy ─────────────────────────────────────────────────────

def test_historial_con_flechas_en_textarea_vacio(pg):
    _con_sesion(pg)
    pg.evaluate("() => { S.historial = []; recordarEnviado('uno'); recordarEnviado('dos'); }")
    ta = pg.locator("#entrada")
    ta.click()
    ta.press("ArrowUp");   assert ta.input_value() == "dos"
    ta.press("ArrowUp");   assert ta.input_value() == "uno"
    ta.press("ArrowUp");   assert ta.input_value() == "uno"      # tope
    ta.press("ArrowDown"); assert ta.input_value() == "dos"
    ta.press("ArrowDown"); assert ta.input_value() == ""         # vuelve al borrador
    # con el cursor en MEDIO de un texto multilinea, la flecha mueve el cursor
    pg.evaluate("() => { const t = $('entrada'); t.value = 'a\\nb\\nc'; t.selectionStart = t.selectionEnd = 2; }")
    ta.press("ArrowUp")
    assert ta.input_value() == "a\nb\nc"
    # el historial sobrevive a recargar (localStorage)
    assert json.loads(pg.evaluate("() => localStorage.getItem('historial')")) == ["uno", "dos"]


def test_filtro_de_comandos_por_subsecuencia(pg):
    _con_sesion(pg)
    assert pg.evaluate("() => [puntuarFuzzy('/vlc', '/velocidad'), puntuarFuzzy('/ver', '/ver'),"
                       " puntuarFuzzy('loc', '/velocidad'), puntuarFuzzy('/xz', '/velocidad')]") == [1, 3, 2, 0]
    pg.evaluate("""() => { S.comandos = [{cmd: '/velocidad', desc: 'v'}, {cmd: '/ver', desc: 'ver'},
                                        {cmd: '/ayuda', desc: 'a'}]; }""")
    ta = pg.locator("#entrada")
    ta.click(); ta.type("/vlc")
    filas = pg.evaluate("() => [...document.querySelectorAll('#sugerencias .sug .c')].map(e => e.textContent)")
    assert filas == ["/velocidad"], filas
    ta.press("Tab")
    assert ta.input_value() == "/velocidad "
    # prefijo primero, luego substring, luego subsecuencia
    pg.evaluate("() => { $('entrada').value = ''; }")
    ta.type("/ve")
    filas = pg.evaluate("() => [...document.querySelectorAll('#sugerencias .sug .c')].map(e => e.textContent)")
    assert filas == ["/velocidad", "/ver"], filas
