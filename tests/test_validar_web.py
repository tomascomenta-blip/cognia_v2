# -*- coding: utf-8 -*-
"""Tests de cognia/estado/validar_web.py.

El caso que fija el modulo es el REAL: la traza del dueno del 2026-08-31, donde
un index.html de 32 KB cortado a mitad de una clase contaba como avance
verificado y se entregaba con "✓ Objetivo verificado".

Sin red y sin modelo: todo es texto.
"""

import pytest

from cognia.estado import validar_web as V


# ── El caso que motiva el modulo ───────────────────────────────────────

HTML_CORTADO = """<!DOCTYPE html>
<html lang="es">
<head><title>Juego</title></head>
<body>
<button id="btnNew">NEW GAME</button>
<script>
class Renderer {
  constructor(gl){ this.gl = gl; }
  draw(){
    this.gl.clear();
"""

HTML_ENTERO = """<!DOCTYPE html>
<html lang="es">
<head><title>Juego</title></head>
<body>
<button id="btnNew">NEW GAME</button>
<script>
class Renderer {
  constructor(gl){ this.gl = gl; }
  draw(){ this.gl.clear(); }
}
document.getElementById('btnNew').addEventListener('click', () => new Renderer(null));
</script>
</body>
</html>
"""


def test_html_cortado_es_invalido_y_dice_por_que():
    ok, motivo = V.veredicto("index.html", HTML_CORTADO)
    assert ok is False
    assert "script" in motivo.lower() or "html" in motivo.lower()
    fallos = V.problemas("index.html", HTML_CORTADO)
    assert any("<script>" in f for f in fallos)
    assert any("</html>" in f for f in fallos)


def test_html_entero_es_valido():
    ok, motivo = V.veredicto("index.html", HTML_ENTERO)
    assert ok is True
    assert V.problemas("index.html", HTML_ENTERO) == []


def test_un_html_sano_con_botones_muertos_PASA():
    """Limite honesto: este modulo dice si el fichero esta ENTERO, no si sirve.

    El index.html del dueno tambien tenia 50 ids y un solo addEventListener, y
    eso NO lo caza esto — lo caza `fase_producto`, que abre la pagina en un
    navegador de verdad. Un validador estructural que fingiera juzgar semantica
    seria la clase de gate que acaba apagado.
    """
    muerto = HTML_ENTERO.replace(
        "document.getElementById('btnNew').addEventListener('click', "
        "() => new Renderer(null));", "")
    assert V.problemas("index.html", muerto) == []


# ── El lexer de JS ─────────────────────────────────────────────────────

@pytest.mark.parametrize("js, roto", [
    ("function f(){ return 1; }", False),
    ("function f(){ return 1;", True),                      # llave abierta
    ("const r = /\\/[a-z]+/g; const x = 4 / 2;", False),    # regex y division
    ("const s = 'el fichero se acaba aqui", True),   # cadena abierta al EOF
    ("const s = 'cierra en la linea;\nconst t = 2;\n", False),  # sin EOF: no se opina
    ("// no me fio de don't y se acaba", False),     # apostrofe en comentario
    ("const t = `plantilla ${ 1 + 1 } fin`;", False),
    ("const t = `plantilla ${ 1 + 1 } sin cerrar", True),
    ("const c = /* comentario\n sigue */ 3;", False),
    ("const c = /* comentario que no cierra", True),
    ("if (a) { b(); }}", True),                             # cierre de mas
    ("const glsl = `void main(){ gl_Position = vec4(0.0); }`;", False),
    ("// solo un comentario", False),
])
def test_balanceo_js(js, roto):
    assert bool(V.problemas_js(js)) is roto


def test_un_bundle_minificado_no_se_juzga():
    """La heuristica de `/` se rompe en un bundle de una sola linea de 200 KB, y
    un bundle no es codigo que el agente escriba: el modulo NO opina.

    MEDIDO: sobre los 439 .html/.js escritos a mano del disco del dueno los
    tres unicos falsos positivos eran assets de vite (playwright).
    """
    bundle = "!function(){" + "var a=1;" * 3000 + "}();/*"
    assert V.parece_minificado(bundle)
    assert V.problemas_js(bundle) == []


def test_script_externo_y_no_javascript_se_saltan():
    html = ('<html><body><script src="app.js"></script>'
            '<script type="x-shader/x-vertex">void main(){</script>'
            '</body></html>')
    assert V.problemas("p.html", html) == []


def test_fragmento_html_sin_html_no_se_reprueba():
    """Una plantilla parcial es legitima: solo se exige cerrar lo que se abrio."""
    assert V.problemas("parcial.html", "<div class='x'>hola</div>") == []


def test_no_opina_sobre_lo_que_no_sabe_mirar():
    assert V.problemas("notas.md", "# hola") == []
    assert V.veredicto("notas.md", "# hola")[0] is None
    assert V.es_web("a.html") and V.es_web("a.js") and not V.es_web("a.md")


def test_js_suelto_truncado():
    ok, _ = V.veredicto("app.js", "export function f(){\n  const x = [1,2,\n")
    assert ok is False
