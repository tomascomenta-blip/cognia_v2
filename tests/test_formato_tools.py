# -*- coding: utf-8 -*-
"""Familia de pruebas: validadores y lectores (cognia/agent/formato_tools,
2026-09-07). Cada validador con un fichero valido y uno roto en tmp_path; el
resto de tools contra artefactos REALES creados en el test (pdf con pymupdf,
docx, xlsx, cubo trimesh, http.server local, sockets, procesos). Se registra
con el decorador real y se llama por TOOLS[nombre]['fn'] como hace run_tool."""
from __future__ import annotations

import http.server
import re
import os
import socket
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from cognia.agent import formato_tools as FT
from cognia.agent.tools import TOOLS, tool

FT.register(tool)


def _ctx(tmp_path):
    return {"_scratchpad": str(tmp_path), "workspace": str(tmp_path)}


def _t(nombre, args, tmp_path):
    return TOOLS[nombre]["fn"](args, _ctx(tmp_path))


def _w(tmp_path, nombre, texto):
    p = tmp_path / nombre
    p.write_text(textwrap.dedent(texto), encoding="utf-8")
    return str(p)


# ── formato_validar ──────────────────────────────────────────────────────────

def test_registro_familia():
    esperadas = {"formato_validar", "diff_texto", "sql_probar", "pdf_inspeccionar", "pdf_ver",
                 "docx_texto", "xlsx_leer", "modelo3d_inspeccionar", "modelo3d_ver", "py_lint",
                 "py_importar", "py_perfilar", "py_cobertura", "http_solicitud", "puerto_esperar",
                 "esperar_fichero", "consola_sesion", "tui_probar"}
    assert esperadas <= set(TOOLS)
    for n in esperadas:
        assert TOOLS[n]["doc"].startswith(n + " ")
        assert TOOLS[n]["desc"]
    for n in ("py_perfilar", "py_cobertura", "http_solicitud", "consola_sesion", "tui_probar"):
        assert TOOLS[n]["danger"] is True


def test_html_valido_y_roto(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    ok = _w(tmp_path, "ok.html", """\
        <!doctype html><html><head><title>t</title><style>body{}</style></head>
        <body><ul><li>uno<li>dos</ul><p>a<p>b<img src="logo.png"><br>
        <script>console.log(1)</script></body></html>""")
    out = _t("formato_validar", ok, tmp_path)
    assert "OK" in out and "lineas" in out, out
    roto = _w(tmp_path, "roto.html", """\
        <html><body>
        <div class="a" class="b"><span>hola</span>
        <img src="nope.png">
        <p>fin</p>
        </body></html>""")
    out = _t("formato_validar", roto, tmp_path)
    assert "problema" in out
    assert "<div>" in out and "sin cerrar" in out
    assert "nope.png" in out
    assert "duplicado" in out


def test_html_script_sin_cerrar(tmp_path):
    p = _w(tmp_path, "s.html", "<html><body><script>var a = 1;</body></html>")
    out = _t("formato_validar", p, tmp_path)
    assert "<script> abiertos: 1, cerrados: 0" in out


def test_css_valido_y_roto(tmp_path):
    ok = _w(tmp_path, "ok.css", "body { margin: 0; color: rgb(1,2,3); }\n.a:hover { x: 1 }\n@media (x) { .b { y: 2; } }")
    assert "OK" in _t("formato_validar", ok, tmp_path)
    roto = _w(tmp_path, "roto.css", "body { margin: 0;\n.a { color red; background: url(falta.png) }")
    out = _t("formato_validar", roto, tmp_path)
    assert "sin cerrar" in out and "no tiene ':'" in out and "falta.png" in out


def test_json_yaml_toml_ini(tmp_path):
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.json", '{"a": [1, 2]}'), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.json", '{"a": [1, 2,]}'), tmp_path)
    assert "linea 1" in out
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.yaml", "a: 1\nb:\n  - x\n"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.yaml", "a: [1, 2\nb: {\n"), tmp_path)
    assert "problema" in out
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.toml", "[x]\na = 1\n"), tmp_path)
    assert "problema" in _t("formato_validar", _w(tmp_path, "b.toml", "[x\na = \n"), tmp_path)
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.ini", "[s]\nk = v\n"), tmp_path)
    assert "problema" in _t("formato_validar", _w(tmp_path, "b.ini", "k = v\n[s\n"), tmp_path)


def test_svg_xml_csv_md(tmp_path):
    ok = _w(tmp_path, "ok.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect id="a"/></svg>')
    assert "OK" in _t("formato_validar", ok, tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.svg", '<svg xmlns="http://www.w3.org/2000/svg"><g id="a"/><g id="a"/></svg>'), tmp_path)
    assert "viewBox" in out and "repetido" in out
    assert "mal formado" in _t("formato_validar", _w(tmp_path, "b.xml", "<a><b></a>"), tmp_path)
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.csv", "a,b,c\n1,2,3\n4,5,6\n"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.csv", "a,b,c\n1,2\n4,5,6,7\n"), tmp_path)
    assert "fila 2: 2 columnas" in out and "fila 3: 4 columnas" in out
    (tmp_path / "existe.md").write_text("x", encoding="utf-8")
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.md", "# t\n[x](existe.md) [w](https://x.y)\n```\ncode\n```\n"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.md", "[x](no.md)\n```\nabierto\n"), tmp_path)
    assert "no.md" in out and "``` sin cerrar" in out


def test_py_valido_y_roto(tmp_path):
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.py", "import os\nprint(os.name)\n"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.py", "print(nombre_sin_definir)\n"), tmp_path)
    assert "pyflakes" in out and "nombre_sin_definir" in out
    out = _t("formato_validar", _w(tmp_path, "c.py", "def f(:\n"), tmp_path)
    assert "SyntaxError" in out


def test_sql_sh_y_sin_validador(tmp_path):
    assert "OK" in _t("formato_validar", _w(tmp_path, "a.sql", "CREATE TABLE t(a); SELECT a FROM t;"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "b.sql", "SELECT * FROM no_existe;"), tmp_path)
    assert "sentencia 1" in out and "no_existe" in out
    assert "sin shebang" in _t("formato_validar", _w(tmp_path, "a.sh", "echo hola\n"), tmp_path)
    out = _t("formato_validar", _w(tmp_path, "a.xyz", "lo que sea"), tmp_path)
    assert "sin validador" in out and "bytes" in out
    assert "ERROR" in _t("formato_validar", "no_existe.html", tmp_path)


def test_js_con_node_o_aviso(tmp_path):
    out = _t("formato_validar", _w(tmp_path, "a.js", "const a = 1;\nfunction f(){ return a }\n"), tmp_path)
    roto = _t("formato_validar", _w(tmp_path, "b.js", "function f( {\n"), tmp_path)
    import shutil
    if shutil.which("node"):
        assert "OK" in out, out
        assert "node --check" in roto and "problema" in roto
    else:
        assert "sin comprobar" in out


# ── diff / sql ───────────────────────────────────────────────────────────────

def test_diff_texto_ficheros_y_literal(tmp_path):
    a = _w(tmp_path, "a.txt", "uno\ndos\ntres\n")
    b = _w(tmp_path, "b.txt", "uno\nDOS\ntres\ncuatro\n")
    out = _t("diff_texto", "%s | %s" % (a, b), tmp_path)
    assert "+2 -1" in out and "+DOS" in out and "+cuatro" in out
    assert "IGUALES" in _t("diff_texto", "%s | %s" % (a, a), tmp_path)
    out = _t("diff_texto", "%s | uno\\ndos\\ntres | contexto=0" % a, tmp_path)
    assert "IGUALES" in out
    assert "ERROR" in _t("diff_texto", a, tmp_path)


def test_sql_probar_memoria_y_copia(tmp_path):
    esquema = _w(tmp_path, "esq.sql", "CREATE TABLE t(a INTEGER, b TEXT);")
    out = _t("sql_probar", ":memoria: | sql=INSERT INTO t VALUES (1,'x'); INSERT INTO t VALUES (2,'y'); "
             "SELECT * FROM t ORDER BY a; SELECT nope FROM t | esquema=%s" % esquema, tmp_path)
    assert "esquema" in out and "aplicado" in out
    assert "1 fila(s) afectada" in out
    assert "2 fila(s)" in out and "a | b" in out and "2 | y" in out
    assert "ERROR en `SELECT nope FROM t`" in out and "1 error(es)" in out
    # copia temporal: la original no cambia
    import sqlite3
    db = tmp_path / "real.db"
    con = sqlite3.connect(str(db)); con.execute("CREATE TABLE k(v)"); con.execute("INSERT INTO k VALUES (1)"); con.commit(); con.close()
    out = _t("sql_probar", "%s | sql=DELETE FROM k; SELECT count(*) FROM k" % db, tmp_path)
    assert "copia temporal" in out and "0 error" in out
    con = sqlite3.connect(str(db)); assert con.execute("SELECT count(*) FROM k").fetchone()[0] == 1; con.close()
    assert "ERROR" in _t("sql_probar", ":memoria:", tmp_path)


# ── pdf / docx / xlsx ───────────────────────────────────────────────────────

def test_pdf_inspeccionar_y_ver(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "Hola Cognia PDF", fontsize=20)
    doc.new_page()          # en blanco
    pdf = tmp_path / "doc.pdf"
    doc.set_metadata({"title": "Prueba"})
    doc.save(str(pdf)); doc.close()
    out = _t("pdf_inspeccionar", str(pdf), tmp_path)
    assert "2 pagina(s)" in out and "Hola Cognia PDF" in out and "EN BLANCO: paginas 2" in out and "title=Prueba" in out
    out = _t("pdf_ver", "%s | pagina=1 | zoom=1" % pdf, tmp_path)
    # una linea de texto en una pagina A4 es 99% blanco: el resumen dice
    # "probablemente vacia" y eso es honesto, no un fallo
    assert "pagina 1/2" in out and ".png" in out and "dominante #ffffff" in out
    png = out.split(" en ", 1)[1].split(" · ")[0]
    assert Path(png).is_file()


def test_docx_texto(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Titulo grande", level=1)
    d.add_paragraph("Parrafo normal.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "a"; t.cell(0, 1).text = "b"; t.cell(1, 0).text = "1"; t.cell(1, 1).text = "2"
    f = tmp_path / "d.docx"
    d.save(str(f))
    out = _t("docx_texto", str(f), tmp_path)
    assert "# [Heading 1] Titulo grande" in out and "Parrafo normal." in out
    assert "tabla 1 (2 filas x 2 cols)" in out and "1 | 2" in out and "0 imagen" in out


def test_xlsx_leer(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws.append(["a", "b", "suma"])
    ws.append([1, 2, "=A2+B2"])
    ws["D2"] = "#DIV/0!"
    wb.create_sheet("Otra")
    f = tmp_path / "x.xlsx"
    wb.save(str(f))
    out = _t("xlsx_leer", str(f), tmp_path)
    assert "hojas: Datos, Otra" in out and "a | b | suma" in out
    assert "sin valor cacheado" in out and "C2" in out
    assert "CELDAS CON ERROR" in out and "D2: #DIV/0!" in out
    assert "ERROR" in _t("xlsx_leer", "%s | hoja=NoExiste" % f, tmp_path)


# ── 3D ──────────────────────────────────────────────────────────────────────

def test_modelo3d_inspeccionar_y_ver(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    cubo = trimesh.creation.box(extents=(2, 2, 2))
    f = tmp_path / "cubo.obj"
    cubo.export(str(f))
    out = _t("modelo3d_inspeccionar", str(f), tmp_path)
    assert "1 malla(s)" in out and "8 vertices" in out and "12 caras" in out
    assert "cerrada (watertight)" in out and "volumen 8.000" in out
    out = _t("modelo3d_ver", "%s | vista=iso" % f, tmp_path)
    assert "vistas iso" in out and "tiene contenido" in out
    png = out.split(" en ", 1)[1].split(" · ")[0]
    assert Path(png).is_file()
    assert "ERROR" in _t("modelo3d_inspeccionar", str(tmp_path / "no.obj"), tmp_path)


# ── python ──────────────────────────────────────────────────────────────────

def test_py_lint(tmp_path):
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "ok.py").write_text("x = 1\nprint(x)\n", encoding="utf-8")
    (d / "mal.py").write_text("import os\nprint(y)\n", encoding="utf-8")
    out = _t("py_lint", str(d), tmp_path)
    assert "aviso(s) en 1 de 2" in out and "mal.py" in out and "undefined name 'y'" in out and "'os' imported but unused" in out
    assert "sin avisos" in _t("py_lint", str(d / "ok.py"), tmp_path)


def test_py_importar_bueno_y_roto(tmp_path):
    bueno = _w(tmp_path, "modbueno.py", "VALOR = 1\nprint('efecto')\n")
    out = _t("py_importar", bueno, tmp_path)
    assert "OK en" in out and "efecto" in out
    roto = _w(tmp_path, "modroto.py", "import paquete_que_no_existe_xyz\n")
    out = _t("py_importar", roto, tmp_path)
    assert "FALLO" in out and "ModuleNotFoundError" in out
    out = _t("py_importar", "modbueno | cwd=%s" % tmp_path, tmp_path)
    assert "OK en" in out


def test_py_perfilar(tmp_path):
    s = _w(tmp_path, "lento.py", "def f():\n    return sum(range(200000))\nfor _ in range(3): f()\nprint('hecho')\n")
    out = _t("py_perfilar", "python %s | top=5" % s, tmp_path)
    assert "rc 0" in out and "ncalls" in out and "lento.py" in out
    assert "ERROR" in _t("py_perfilar", "python", tmp_path)


def test_py_cobertura(tmp_path):
    pytest.importorskip("coverage")
    (tmp_path / "modulo.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n", encoding="utf-8")
    (tmp_path / "test_modulo.py").write_text("from modulo import a\n\ndef test_a():\n    assert a() == 1\n", encoding="utf-8")
    out = _t("py_cobertura", "pytest test_modulo.py -q -p no:cacheprovider | cwd=%s | timeout=120" % tmp_path, tmp_path)
    assert "% total" in out and "tests rc 0" in out, out
    assert "modulo.py" in out


# ── red / ficheros ──────────────────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = b'{"ok": true, "ruta": "%s"}' % self.path.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        datos = self.rfile.read(n)
        self.send_response(201)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"recibido:" + datos)

    def log_message(self, *a):
        pass


@pytest.fixture
def servidor():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield srv.server_address[1]
    srv.shutdown()


def test_http_solicitud(servidor, tmp_path):
    out = _t("http_solicitud", "GET http://127.0.0.1:%d/hola" % servidor, tmp_path)
    assert "200 en" in out and "application/json" in out and '"ok": true' in out
    out = _t("http_solicitud", 'POST http://127.0.0.1:%d/x | cuerpo={"a": 1} | cabeceras=X-Prueba:1' % servidor, tmp_path)
    assert "201 en" in out and 'recibido:{"a": 1}' in out
    out = _t("http_solicitud", "http://127.0.0.1:%d/" % servidor, tmp_path)
    assert "GET" in out and "200" in out
    out = _t("http_solicitud", "GET http://127.0.0.1:1/ | timeout=2", tmp_path)
    assert "ERROR" in out and "ejecutar_fondo" in out


def test_puerto_esperar(servidor, tmp_path):
    out = _t("puerto_esperar", "127.0.0.1:%d | timeout=5" % servidor, tmp_path)
    assert "ABIERTO" in out
    out = _t("puerto_esperar", "http://127.0.0.1:%d | timeout=5" % servidor, tmp_path)
    assert "ABIERTO" in out and "GET / -> 200" in out
    s = socket.socket(); s.bind(("127.0.0.1", 0)); libre = s.getsockname()[1]; s.close()
    out = _t("puerto_esperar", "%d | timeout=1" % libre, tmp_path)
    assert "CERRADO" in out and "ver_salida" in out


def test_esperar_fichero(tmp_path):
    f = tmp_path / "salida.bin"

    def escribir():
        time.sleep(0.3)
        with f.open("wb") as fh:
            for _ in range(3):
                fh.write(b"x" * 100); fh.flush(); time.sleep(0.15)
    threading.Thread(target=escribir, daemon=True).start()
    out = _t("esperar_fichero", "%s | timeout=10 | estable=400" % f, tmp_path)
    assert "listo, 300 bytes" in out
    out = _t("esperar_fichero", "%s | timeout=1" % (tmp_path / "nunca.txt"), tmp_path)
    assert "NO aparecio" in out


# ── consola_sesion ──────────────────────────────────────────────────────────

def test_consola_sesion_ciclo(tmp_path):
    prog = _w(tmp_path, "repl.py", """\
        print('listo>')
        while True:
            try:
                l = input()
            except EOFError:
                break
            if l == 'salir':
                print('adios'); break
            print('eco:', l.upper())
        """)
    out = _t("consola_sesion", 'abrir "%s" "%s"' % (sys.executable, prog), tmp_path)
    assert "sesion s" in out and "listo>" in out and "viva" in out
    sid = re.search(r"sesion (s\d+)", out).group(1)
    out = _t("consola_sesion", "enviar %s hola" % sid, tmp_path)
    assert "eco: HOLA" in out and "viva" in out
    out = _t("consola_sesion", "lista", tmp_path)
    assert sid in out and "viva" in out
    out = _t("consola_sesion", "enviar %s salir" % sid, tmp_path)
    assert "adios" in out and ("TERMINO" in out or "viva" in out)
    out = _t("consola_sesion", "cerrar %s" % sid, tmp_path)
    assert "cerrada (rc 0)" in out
    assert "ninguna sesion" in _t("consola_sesion", "lista", tmp_path)
    assert "ERROR" in _t("consola_sesion", "enviar s999 x", tmp_path)
    assert "ERROR" in _t("consola_sesion", "abrir", tmp_path)


def test_consola_sesion_cerrar_mata_proceso_vivo(tmp_path):
    prog = _w(tmp_path, "eterno.py", "import time\nprint('vivo')\nwhile True: time.sleep(0.1)\n")
    out = _t("consola_sesion", 'abrir "%s" "%s"' % (sys.executable, prog), tmp_path)
    sid = re.search(r"sesion (s\d+)", out).group(1)
    pid = FT._SESIONES[sid]["proc"].pid
    out = _t("consola_sesion", "cerrar %s" % sid, tmp_path)
    assert "cerrada" in out
    import psutil
    time.sleep(0.3)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


# ── tui_probar ──────────────────────────────────────────────────────────────

def test_tui_probar_pantalla_y_tecla(tmp_path):
    prog = _w(tmp_path, "tui.py", r"""
        import sys
        sys.stdout.write("\x1b[2J\x1b[1;1HMENU PRINCIPAL\x1b[3;1H> Opcion A\x1b[4;1H  Opcion B\n")
        sys.stdout.flush()
        t = sys.stdin.read(1)
        sys.stdout.write("\x1b[2J\x1b[1;1HPULSASTE: %r\n" % t)
        sys.stdout.flush()
        """)
    # sys.stdin.read(1) en una consola real es modo cocinado: la tecla llega
    # con el intro (como le pasaria a un humano). Por eso teclas=b,intro.
    out = _t("tui_probar", '"%s" "%s" | teclas=b,intro | espera=1200 | columnas=40 | filas=10' % (sys.executable, prog), tmp_path)
    if "ERROR" in out.split("\n", 1)[0]:
        pytest.skip("pseudo-terminal no disponible en este runner: " + out)
    arranque = out.split(">>> tecla", 1)[0]
    assert ">>> arranque" in arranque and "MENU PRINCIPAL" in arranque and "> Opcion A" in arranque, out
    assert ">>> tecla 'intro'" in out and "PULSASTE: 'b'" in out, out
    assert "3 pantalla(s)" in out
    assert "40x10" in out


def test_tui_tecla_a_ansi():
    assert FT._tecla_a_ansi("abajo") == "\x1b[B"
    assert FT._tecla_a_ansi("intro") == "\r"
    assert FT._tecla_a_ansi("ctrl-c") == "\x03"
    assert FT._tecla_a_ansi("x") == "x"


def test_ultimo_registra():
    u = FT.ultimo()
    assert u["tool"] and u["ts"] > 0
