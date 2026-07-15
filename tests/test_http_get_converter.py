# -*- coding: utf-8 -*-
"""http_get usa el conversor universal para extraer texto limpio (B14-lite)."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cognia.agent.tools as T

_HTML = (b"<html><head><style>.a{color:red}</style>"
         b"<script>var secreto=42;</script></head><body>"
         b"<h1>Titulo Real</h1><p>Contenido visible del articulo.</p>"
         b"</body></html>")


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_HTML)

    def log_message(self, *a):
        pass


@pytest.fixture()
def servidor():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def test_http_get_extrae_texto_limpio_sin_script(servidor):
    out = T.run_tool("http_get", servidor, {})
    assert "Titulo Real" in out
    assert "Contenido visible del articulo." in out
    # el JS/CSS inline ya NO se cuela como 'texto' (el bug del strip crudo)
    assert "secreto" not in out and "color:red" not in out and "var " not in out


def test_http_get_rechaza_no_http():
    out = T.run_tool("http_get", "ftp://x", {})
    assert "ERROR" in out and "http/https" in out
