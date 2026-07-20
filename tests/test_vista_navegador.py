"""
Cognia mira su propia pagina en un navegador de verdad.

Por que existe este modulo: revisar_html() lee el texto de la pagina y eso no
distingue "HTML valido" de "pagina que funciona". Medido el 2026-07-19: una
pagina paso la revision estatica con 8.7/10 y en Chrome salia entera en negro,
porque el CSS decia `.quote.up span` y el JS ponia la clase en el <span>.

Los tests necesitan el Chrome/Edge del sistema. Si no hay, se saltan: la
ausencia de navegador no debe romper la suite ni la generacion.
"""

import pytest

from cognia.program_creator.vista_navegador import (
    encontrar_navegador,
    revisar_en_navegador,
)

sin_navegador = pytest.mark.skipif(
    encontrar_navegador() is None,
    reason="no hay Chrome/Edge instalado para renderizar",
)

# Pagina sana: cambia sola y pinta verde y rojo de verdad.
BUENA = """<!DOCTYPE html><html><head><style>
  .up { color: rgb(0,128,0); } .down { color: rgb(255,0,0); }
</style></head><body>
  <div id="p"></div>
  <script>
    var v = [100, 200], n = 0;
    function tick() {
      n++;
      document.getElementById('p').innerHTML = v.map(function (x, i) {
        var nuevo = x + (i === 0 ? n : -n);
        return '<span class="' + (i === 0 ? 'up' : 'down') + '">' + nuevo.toFixed(2) + '</span>';
      }).join(' ');
    }
    tick(); setInterval(tick, 300);
  </script>
</body></html>"""

# El bug real: la clase de estado va al <span>, pero el CSS la pide en .quote.
COLORES_MUERTOS = """<!DOCTYPE html><html><head><style>
  .quote.up span { color: green; } .quote.down span { color: red; }
</style></head><body>
  <div class="quote" id="q"><span>100.00</span></div>
  <script>
    var n = 100;
    setInterval(function () {
      n += 1;
      document.getElementById('q').innerHTML =
        '<span class="' + (n % 2 ? 'up' : 'down') + '">' + n.toFixed(2) + '</span>';
    }, 300);
  </script>
</body></html>"""

ESTATICA = """<!DOCTYPE html><html><head><style>.a{color:blue}</style></head>
<body><div class="a">100.00</div><script>var x = 1;</script></body></html>"""


@sin_navegador
class TestLoQueSoloSeVeRenderizando:

    def test_pagina_sana_pasa(self):
        inf = revisar_en_navegador(BUENA)
        assert inf.ok is True
        assert inf.se_mueve is True
        assert len(inf.colores) > 1
        assert inf.defectos == []

    def test_colores_muertos_se_detectan(self):
        """
        El caso que engano a la revision estatica: HTML valido, CSS bien
        escrito, y aun asi ni un solo pixel verde o rojo.
        """
        inf = revisar_en_navegador(COLORES_MUERTOS)

        assert inf.ok is False
        assert inf.se_mueve is True          # los numeros SI cambian
        assert inf.colores == ["rgb(0, 0, 0)"]
        assert any("mismo color" in d for d in inf.defectos)

    def test_pagina_que_no_se_mueve_se_detecta(self):
        inf = revisar_en_navegador(ESTATICA)
        assert inf.ok is False
        assert inf.se_mueve is False
        assert any("no cambia sola" in d for d in inf.defectos)


@sin_navegador
def test_muestreo_multiple_evita_el_falso_negativo():
    """
    Regresion del bug de la propia sonda, medido el 2026-07-19.

    Con UNA sola lectura a los 2000 ms, una pagina cuyo setInterval tambien
    era de 2000 ms se leia justo antes del primer tick: los elementos aun no
    tenian clase de estado y la sonda reportaba "todo negro" sobre una pagina
    que pintaba verde y rojo. El falso positivo disparaba reparaciones
    inutiles y hundia la nota de paginas correctas.

    Esta pagina no pinta color hasta el primer tick, que llega tarde a
    proposito: solo el muestreo repetido la ve bien.
    """
    tardia = """<!DOCTYPE html><html><head><style>
      .up { color: rgb(0,128,0); }
    </style></head><body>
      <div id="p"><span>100.00</span></div>
      <script>
        var n = 100;
        setInterval(function () {
          n += 1;
          document.getElementById('p').innerHTML =
            '<span class="up">' + n.toFixed(2) + '</span>';
        }, 1800);
      </script>
    </body></html>"""

    inf = revisar_en_navegador(tardia)

    assert "rgb(0, 128, 0)" in inf.colores, (
        f"el verde llega tarde y la sonda no lo vio: {inf.colores}")
    assert inf.se_mueve is True


@sin_navegador
def test_guarda_input_y_output_images(tmp_path):
    """input images = evidencia de la validacion; output images = resultado."""
    inf = revisar_en_navegador(BUENA, dir_programa=tmp_path)

    assert inf.ok is True
    assert inf.input_images, "deberia dejar capturas de validacion"
    assert inf.output_images, "una pagina aceptada deberia tener captura final"

    assert (tmp_path / "input_images").is_dir()
    assert (tmp_path / "output_images" / "resultado.png").exists()
    for ruta in inf.input_images + inf.output_images:
        assert (tmp_path in __import__("pathlib").Path(ruta).parents
                or str(tmp_path) in ruta)


@sin_navegador
def test_pagina_rechazada_no_genera_output_images(tmp_path):
    """Solo lo aceptado merece output image: si no, la captura miente."""
    inf = revisar_en_navegador(COLORES_MUERTOS, dir_programa=tmp_path)

    assert inf.ok is False
    assert inf.output_images == []
    assert not (tmp_path / "output_images").exists()


def test_sin_navegador_no_rompe_la_generacion(monkeypatch):
    """Si no hay Chrome, se avisa y se sigue: no puede tumbar el pipeline."""
    import cognia.program_creator.vista_navegador as vn
    monkeypatch.setattr(vn, "encontrar_navegador", lambda: None)

    inf = vn.revisar_en_navegador(BUENA)
    assert inf.ok is True
    assert inf.defectos == []
    assert "navegador" in inf.nota.lower()
