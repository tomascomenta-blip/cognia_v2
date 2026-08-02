"""
Higiene de las auditorias JSONL (A11):
  - backend_activo._append escribe la linea COMPLETA en una sola write()
    sobre O_APPEND (las lineas corruptas venian del open("a") bufereado
    con varios procesos escribiendo a la vez).
  - leer_audit() salta las lineas no-JSON heredadas y las CUENTA en vez
    de ocultarlas.
  - Ambos jsonl (backend_activo y sentinel) rotan a una generacion (.1)
    al superar el tope, en vez de crecer sin cota.
"""
import json

import pytest

from cognia import backend_activo as BA
from cognia.agent import sentinel as S


@pytest.fixture
def audit_tmp(tmp_path, monkeypatch):
    ruta = tmp_path / "backend_audit.jsonl"
    monkeypatch.setattr(BA, "AUDIT", ruta)
    return ruta


def test_append_escribe_linea_json_completa(audit_tmp):
    BA._append({"via": "test", "modelo": "m1"})
    BA._append({"via": "test2", "modelo": "m2"})
    lineas = audit_tmp.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    assert json.loads(lineas[0])["via"] == "test"
    assert json.loads(lineas[1])["modelo"] == "m2"


def test_leer_audit_salta_y_cuenta_corruptas(audit_tmp):
    # una linea partida a la mitad (herencia de escrituras concurrentes)
    audit_tmp.write_text(
        '{"via": "ok1"}\n{"via": "trunca", "mod\n{"via": "ok2"}\n',
        encoding="utf-8")
    filas, corruptas = BA.leer_audit()
    assert [f["via"] for f in filas] == ["ok1", "ok2"]
    assert corruptas == 1


def test_leer_audit_sin_archivo(audit_tmp):
    assert BA.leer_audit() == ([], 0)


def test_append_rota_a_una_generacion(audit_tmp, monkeypatch):
    monkeypatch.setattr(BA, "_ROTAR_BYTES", 100)
    audit_tmp.write_text("x" * 200 + "\n", encoding="utf-8")
    BA._append({"via": "post_rotacion"})
    # el gordo quedo en .1 y el fresco solo tiene la fila nueva
    gen1 = audit_tmp.with_name(audit_tmp.name + ".1")
    assert gen1.exists() and gen1.stat().st_size > 100
    filas, corruptas = BA.leer_audit()
    assert len(filas) == 1 and filas[0]["via"] == "post_rotacion"


def test_sentinel_audit_rota_a_una_generacion(tmp_path, monkeypatch):
    ruta = tmp_path / "sentinel_audit.jsonl"
    monkeypatch.setattr(S, "_AUDIT", ruta)
    monkeypatch.setattr(S, "_ROTAR_BYTES", 100)
    ruta.write_text("x" * 200 + "\n", encoding="utf-8")
    S._audit("shell", "git status", "allow", "prefijo conocido")
    gen1 = ruta.with_name(ruta.name + ".1")
    assert gen1.exists() and gen1.stat().st_size > 100
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    assert json.loads(lineas[0])["veredicto"] == "allow"


def test_sentinel_audit_linea_json_completa(tmp_path, monkeypatch):
    ruta = tmp_path / "sentinel_audit.jsonl"
    monkeypatch.setattr(S, "_AUDIT", ruta)
    S._audit("web", "https://x", "block", "patron de inyeccion")
    fila = json.loads(ruta.read_text(encoding="utf-8").splitlines()[0])
    assert fila["accion"] == "web" and fila["veredicto"] == "block"
