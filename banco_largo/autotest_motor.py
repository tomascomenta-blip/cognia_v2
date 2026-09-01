# -*- coding: utf-8 -*-
"""autotest_motor.py -- prueba el MOTOR contra productos sinteticos conocidos.

El motor tiene que dar VERDE a un producto sano y ROJO a uno roto. Sin este
autotest, un fallo del motor se leeria como un fallo del agente y contaminaria
todo el banco.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from banco_largo import motor  # noqa: E402

HTML_SANO = """<!doctype html><meta charset="utf-8"><title>t</title>
<canvas id="c" width="320" height="240"></canvas>
<button id="b">mas</button><div id="salida">0</div>
<script>
const c = document.getElementById('c'), g = c.getContext('2d');
let n = 0, t = 0;
window.JUEGO = {
  oro: 100, vidas: 3, enemigos: [{x: 0, y: 0, vida: 5}],
  construir(tipo, x, y) { if (this.oro < 10) return false; this.oro -= 10; return true; },
  tick(ms) { t += ms; this.enemigos.forEach(e => { e.x += ms * 0.05; }); },
};
function pinta() {
  g.fillStyle = 'rgb(' + (n % 200) + ',30,90)'; g.fillRect(0, 0, 320, 240);
  g.fillStyle = '#0f0'; g.fillRect((n * 3) % 300, 50, 20, 20);
  g.fillStyle = '#fff'; g.fillRect(10, 100, 40, 10);
  n++; requestAnimationFrame(pinta);
}
pinta();
document.getElementById('b').onclick = () => {
  document.getElementById('salida').textContent = String(++n);
};
</script>
"""

HTML_ROTO = """<!doctype html><meta charset="utf-8"><title>t</title>
<canvas id="c" width="320" height="240"></canvas>
<script>noExiste.metodo();</script>
"""

PY_SANO = "import sys\nprint('resultado: 42')\nsys.exit(0)\n"
PY_ROTO = "import sys\nprint('boom')\nsys.exit(3)\n"

SERVIDOR = """
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = json.dumps({"estado": "vivo", "items": [1, 2, 3]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)
    def log_message(self, *a):
        pass

ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8099"))), H).serve_forever()
"""

TEST_PY = "def test_suma():\n    assert 1 + 1 == 2\n\n\ndef test_lista():\n    assert len([1, 2, 3]) == 3\n"


def _ws(ficheros):
    d = Path(tempfile.mkdtemp(prefix="autotest_"))
    for nombre, contenido in ficheros.items():
        p = d / nombre
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
    return d


CASOS = []


def caso(nombre, ficheros, prueba, espera):
    CASOS.append((nombre, ficheros, prueba, espera))


caso("fichero-existe", {"a.js": "x" * 5000},
     {"tipo": "fichero", "glob": "*.js", "min_bytes": 4000}, True)
caso("fichero-pequeno", {"a.js": "x"},
     {"tipo": "fichero", "glob": "*.js", "min_bytes": 4000}, False)
caso("fichero-ausente", {"a.js": "x" * 5000},
     {"tipo": "fichero", "glob": "index.html"}, False)
caso("python-ok", {"m.py": PY_SANO},
     {"tipo": "python", "entry": "m.py", "stdout_re": ["resultado: 42"]}, True)
caso("python-exit3", {"m.py": PY_ROTO},
     {"tipo": "python", "entry": "m.py"}, False)
caso("python-salida-mal", {"m.py": PY_SANO},
     {"tipo": "python", "entry": "m.py", "stdout_re": ["resultado: 43"]}, False)
caso("pytest-verde", {"test_x.py": TEST_PY},
     {"tipo": "pytest", "ruta": ".", "min_tests": 2}, True)
caso("pytest-sin-tests", {"vacio.txt": "x"},
     {"tipo": "pytest", "ruta": ".", "min_tests": 1}, False)
caso("web-sana", {"index.html": HTML_SANO},
     {"tipo": "web", "pagina": "index.html", "max_errores_consola": 0,
      "afirmaciones": [{"tipo": "selector", "sel": "canvas", "min": 1},
                       {"tipo": "canvas", "min_colores": 3},
                       {"tipo": "canvas_cambia", "ms": 600},
                       {"tipo": "js", "nombre": "api", "codigo": "() => !!window.JUEGO"}]}, True)
caso("web-con-error-js", {"index.html": HTML_ROTO},
     {"tipo": "web", "pagina": "index.html", "max_errores_consola": 0,
      "afirmaciones": [{"tipo": "selector", "sel": "canvas", "min": 1}]}, False)
caso("web-canvas-vacio", {"index.html": "<canvas id=c width=100 height=100></canvas>"},
     {"tipo": "web", "pagina": "index.html",
      "afirmaciones": [{"tipo": "canvas", "min_colores": 4}]}, False)
caso("web-interaccion", {"index.html": HTML_SANO},
     {"tipo": "web", "pagina": "index.html", "max_errores_consola": 0,
      "acciones": [{"tipo": "click", "sel": "#b"}, {"tipo": "esperar", "ms": 200}],
      "afirmaciones": [{"tipo": "js", "nombre": "subio",
                        "codigo": "() => Number(document.getElementById('salida').textContent) > 0"}]}, True)
caso("web-estado-cambia-por-api", {"index.html": HTML_SANO},
     {"tipo": "web", "pagina": "index.html", "max_errores_consola": 0,
      "acciones": [{"tipo": "js", "codigo": "() => { window.__x = window.JUEGO.enemigos[0].x; window.JUEGO.tick(1000); }"}],
      "afirmaciones": [{"tipo": "js", "nombre": "movio",
                        "codigo": "() => window.JUEGO.enemigos[0].x > window.__x"},
                       {"tipo": "js", "nombre": "cobra",
                        "codigo": "() => { const a = window.JUEGO.oro; window.JUEGO.construir(0,1,1); return window.JUEGO.oro < a; }"}]}, True)
caso("web-canvas-estatico-detectado",
     {"index.html": "<canvas id=c width=200 height=200></canvas><script>"
                    "const g=document.getElementById('c').getContext('2d');"
                    "g.fillStyle='#123';g.fillRect(0,0,200,200);"
                    "g.fillStyle='#abc';g.fillRect(20,20,60,60);"
                    "g.fillStyle='#f0f';g.fillRect(120,30,40,90);</script>"},
     {"tipo": "web", "pagina": "index.html",
      "afirmaciones": [{"tipo": "canvas", "min_colores": 3},
                       {"tipo": "canvas_cambia", "ms": 700}]}, False)
caso("http-servidor", {"srv.py": SERVIDOR},
     {"tipo": "http_servidor", "entry": "srv.py",
      "peticiones": [{"ruta": "/", "status": 200, "re": ["vivo"]}]}, True)
caso("http-sin-servidor", {"srv.py": "print('no soy un servidor')\n"},
     {"tipo": "http_servidor", "entry": "srv.py", "espera": 6,
      "peticiones": [{"ruta": "/", "status": 200}]}, False)
caso("dos-pasadas-estable", {"m.py": PY_SANO},
     {"tipo": "dos_pasadas", "prueba": {"tipo": "python", "entry": "m.py"}}, True)


def main():
    fallos = []
    for nombre, ficheros, prueba, espera in CASOS:
        ws = _ws(ficheros)
        try:
            r = motor.correr_prueba(prueba, ws)
            marca = "OK " if r["ok"] == espera else "MAL"
            if r["ok"] != espera:
                fallos.append((nombre, espera, r))
            print("%s %-28s ok=%-5s esperado=%-5s %5dms  %s" % (
                marca, nombre, r["ok"], espera, r["ms"], r["detalle"][:110].replace("\n", " ")))
        finally:
            shutil.rmtree(str(ws), ignore_errors=True)
    print()
    if fallos:
        print("MOTOR NO FIABLE: %d/%d casos mal" % (len(fallos), len(CASOS)))
        for n, e, r in fallos:
            print("  - %s: esperaba %s, dio %s (%s)" % (n, e, r["ok"], r["detalle"][:300]))
        return 1
    print("MOTOR FIABLE: %d/%d casos correctos" % (len(CASOS), len(CASOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
