"""
Regresion: /crear con una idea de pagina web devolvia un script de terminal.

Medido el 2026-07-19: pedir "pagina web que simule un dashboard de inversiones
con movimiento" producia un programa Python que pintaba barras ASCII con
'=' en la terminal. La causa no era el modelo sino el pipeline:

  - _build_prompt exigia "Terminal only, no GUI" y "Standard library ONLY"
  - _parse_response solo aceptaba fences ```python
  - run_in_sandbox ejecutaba todo con el interprete de Python
  - storage escribia siempre program.py con cabecera de comentarios '#'

Es decir: aunque el modelo hubiera devuelto HTML perfecto, el parser lo habria
tirado. Estos tests fijan la rama web de punta a punta.
"""

from pathlib import Path

import pytest

from cognia.program_creator.evaluator import evaluate_program
from cognia.program_creator.generator import (
    GeneratedProgram,
    _es_idea_web,
    _parse_response,
)
from cognia.program_creator.sandbox_runner import revisar_html
from cognia.program_creator.storage import save_program

PAGINA_BUENA = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dashboard</title>
<style>
  body { background:#0b0e14; color:#e6e6e6; font-family:sans-serif; }
  .sube { color:#16c784; } .baja { color:#ea3943; }
  @keyframes latido { from { opacity:.6 } to { opacity:1 } }
  .tarjeta { animation: latido 1s infinite alternate; box-shadow:0 0 8px #000; }
  @media (max-width:600px) { .tarjeta { width:100% } }
</style></head>
<body>
  <div id="panel" class="tarjeta"></div>
  <canvas id="grafico" width="600" height="200"></canvas>
  <script>
    const activos = [{n:"AAPL", p:180}, {n:"MSFT", p:410}];
    function tick() {
      activos.forEach(a => a.p *= 1 + (Math.random() - 0.5) / 100);
      document.getElementById("panel").textContent =
        activos.map(a => a.n + " " + a.p.toFixed(2)).join("  ");
    }
    setInterval(tick, 800);
    tick();
  </script>
</body></html>"""


class TestDeteccionDeIdeaWeb:
    @pytest.mark.parametrize("idea", [
        "pagina web que simule un dashboard de inversiones con movimiento",
        "página web con cotizaciones animadas",
        "landing page para una startup",
        "un sitio web con HTML y CSS",
        "dashboard web de criptomonedas",
    ])
    def test_ideas_web_se_detectan(self, idea):
        assert _es_idea_web(idea) is True

    @pytest.mark.parametrize("idea", [
        "Conway's Game of Life that runs N generations automatically",
        "ASCII art generator that runs automatically",
        "simple Markov chain text generator",
    ])
    def test_ideas_de_terminal_no_son_web(self, idea):
        assert _es_idea_web(idea) is False


class TestParseoHTML:
    def test_extrae_html_del_fence(self):
        raw = ("Title: Investment Dashboard\n"
               "Description: Un panel de inversiones animado.\n"
               "HTML Code:\n"
               "```html\n" + PAGINA_BUENA + "\n```")
        prog = _parse_response(raw, "pagina web", lenguaje="html")

        assert prog is not None
        assert prog.lenguaje == "html"
        assert prog.title == "Investment Dashboard"
        assert "<canvas" in prog.code

    def test_fragmento_sin_html_se_rechaza(self):
        """Un trozo suelto no es una pagina: no debe guardarse como si lo fuera."""
        raw = ("Title: Trozo\nDescription: x\n"
               "HTML Code:\n```html\n<div>hola</div>\n" + "x" * 50 + "\n```")
        assert _parse_response(raw, "pagina web", lenguaje="html") is None

    def test_el_parser_python_no_traga_html(self):
        """Antes del fix esto es lo que pasaba: fence html contra parser python."""
        raw = "Title: Dash\nDescription: x\nHTML Code:\n```html\n" + PAGINA_BUENA + "\n```"
        assert _parse_response(raw, "pagina web", lenguaje="python") is None


class TestRevisionHTML:
    def test_pagina_completa_pasa(self):
        r = revisar_html(PAGINA_BUENA)
        assert r.success is True
        assert r.exit_code == 0
        assert "autocontenida" in r.execution_output

    def test_pagina_sin_animacion_falla(self):
        estatica = "<!DOCTYPE html><html><head></head><body><script>var a=1;</script></body></html>"
        r = revisar_html(estatica)
        assert r.success is False
        assert "no se anima sola" in r.execution_errors

    def test_selector_css_muerto_falla(self):
        """
        Bug real medido en Chrome el 2026-07-19 sobre una pagina generada:
        CSS `.quote.up span` pero el JS ponia 'up' en el <span>. Los tres
        valores salian rgb(0,0,0) pese a pedir verde y rojo, y la revision
        estatica lo daba por bueno.
        """
        rota = """<!DOCTYPE html><html><head><style>
          .quote.up span { color: green; }
          .quote.down span { color: red; }
        </style></head><body>
          <div class="quote" id="q1"><span>A: $100</span></div>
          <script>
            setInterval(() => {
              document.getElementById('q1').innerHTML =
                '<span class="up">A: $101</span>';
            }, 1000);
          </script>
        </body></html>"""
        r = revisar_html(rota)

        assert r.success is False
        assert "nunca casa" in r.execution_errors
        assert "'up'" in r.execution_errors

    def test_clase_de_estado_bien_puesta_pasa(self):
        """La misma pagina con la clase en el elemento correcto no se marca."""
        buena = """<!DOCTYPE html><html><head><style>
          .quote.up span { color: green; }
        </style></head><body>
          <div class="quote up" id="q1"><span>A: $100</span></div>
          <script>
            setInterval(() => {
              document.getElementById('q1').className = 'quote up';
            }, 1000);
          </script>
        </body></html>"""
        r = revisar_html(buena)

        assert "nunca casa" not in (r.execution_errors or "")

    def test_dependencia_externa_falla(self):
        """Un CDN caido deja la pagina en blanco una vez desplegada."""
        con_cdn = PAGINA_BUENA.replace(
            "<canvas", '<script src="https://cdn.jsdelivr.net/chart.js"></script><canvas')
        r = revisar_html(con_cdn)
        assert r.success is False
        assert "recursos externos" in r.execution_errors


class TestEvaluacionYGuardado:
    def _programa(self):
        return GeneratedProgram(
            title="Investment Dashboard", description="Panel de inversiones animado en vivo.",
            code=PAGINA_BUENA, category="pagina web", lenguaje="html")

    def test_una_web_buena_supera_el_umbral(self):
        """Con el evaluador de Python una web nunca llegaba al umbral de guardado."""
        prog = self._programa()
        ev = evaluate_program(prog, revisar_html(prog.code))

        assert ev.should_store is True
        assert ev.functionality_score >= 3.0

    def test_meta_directory_es_nombre_no_ruta(self, tmp_path):
        """
        Regresion: el pipeline hacia Path(meta.directory) para dejar ahi las
        capturas, pero `directory` es solo el NOMBRE del directorio. El
        resultado fue crear input_images/ y output_images/ vacios en el cwd
        (la raiz del repo) y perder todas las capturas. Hay que componer la
        ruta con el storage_dir.
        """
        prog = self._programa()
        ev   = evaluate_program(prog, revisar_html(prog.code))
        meta = save_program(prog, ev, tmp_path)

        assert "/" not in meta.directory and "\\" not in meta.directory
        assert not Path(meta.directory).is_absolute()
        assert (tmp_path / meta.directory).is_dir()

    def test_se_guarda_como_index_html(self, tmp_path):
        prog = self._programa()
        ev   = evaluate_program(prog, revisar_html(prog.code))
        save_program(prog, ev, tmp_path)

        # iterdir() trae tambien el index.json del propio storage: solo el dir.
        destino = next(p for p in tmp_path.iterdir() if p.is_dir())
        assert (destino / "index.html").exists()
        assert not (destino / "program.py").exists()

        guardado = (destino / "index.html").read_text(encoding="utf-8")
        assert guardado.lstrip().startswith("<!--")   # cabecera que no rompe el HTML
        assert "<!DOCTYPE html>" in guardado
        assert "setInterval" in guardado
