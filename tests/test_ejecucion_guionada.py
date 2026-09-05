# -*- coding: utf-8 -*-
"""Contrato de `ejecutar_guion` (cognia/agent/ejecucion_guionada, 2026-09-04): un
programa de consola REAL con menu por input() recibe las entradas una a una y la
salida vuelve segmentada por entrada; un guion corto deja al programa esperando
(TIMEOUT dicho, no fallo mudo); y la tool pasa por el sentinel y se puede llamar
por run_tool."""
from __future__ import annotations

import sys
from pathlib import Path

from cognia.agent import ejecucion_guionada as EG

PROGRAMA = '''
import sys
def main():
    print("Calculadora. 1) sumar 2) restar q) salir")
    while True:
        op = input("opcion> ").strip()
        if op == "q":
            print("chau"); return
        if op not in ("1", "2"):
            print("opcion invalida"); continue
        a = int(input("a> ")); b = int(input("b> "))
        print("resultado:", a + b if op == "1" else a - b)
main()
'''


def _prog(tmp_path) -> Path:
    p = tmp_path / "calc.py"
    p.write_text(PROGRAMA, encoding="utf-8")
    return p


def test_partir_entradas():
    assert EG.partir_entradas("1|4|5|q") == ["1", "4", "5", "q"]
    assert EG.partir_entradas("1;4;q") == ["1", "4", "q"]
    assert EG.partir_entradas("1\\n4\\nq") == ["1", "4", "q"]
    assert EG.partir_entradas("") == []


def test_salida_segmentada_por_entrada(tmp_path):
    p = _prog(tmp_path)
    r = EG.correr_guionado(f'"{sys.executable}" "{p}"', ["1", "4", "5", "9", "q"], cwd=str(tmp_path), timeout_s=40)
    assert not r.get("error"), r
    assert r["rc"] == 0 and not r["expiro"]
    seg = r["segmentos"]
    assert "Calculadora" in seg[0]["salida"] and "opcion>" in seg[0]["salida"]
    assert seg[1]["entrada"] == "1" and "a>" in seg[1]["salida"]
    assert seg[2]["entrada"] == "4" and "b>" in seg[2]["salida"]
    assert seg[3]["entrada"] == "5" and "resultado: 9" in seg[3]["salida"]
    assert seg[4]["entrada"] == "9" and "opcion invalida" in seg[4]["salida"]
    assert seg[5]["entrada"] == "q" and "chau" in seg[5]["salida"]
    texto = EG.texto_guionado(r)
    assert ">>> entrada: '5'" in texto and "resultado: 9" in texto and "rc=0" in texto


def test_guion_corto_deja_el_programa_esperando_y_se_dice(tmp_path):
    p = _prog(tmp_path)
    r = EG.correr_guionado(f'"{sys.executable}" "{p}"', ["1"], cwd=str(tmp_path), timeout_s=8, espera_max_ms=1500)
    # tras '1' pide 'a>' y al cerrar stdin muere de EOFError: no cuelga, y se ve el EOFError
    texto = EG.texto_guionado(r)
    assert "a>" in texto
    assert "EOFError" in texto or r["expiro"]
    assert "hay un error de Python" in texto or "TIMEOUT" in texto


def test_tool_ejecutar_guion_por_run_tool(tmp_path, monkeypatch):
    from cognia.agent.tools import run_tool
    p = _prog(tmp_path)
    monkeypatch.setattr("cognia.agent.sentinel.evaluar_shell", lambda cmd, ctx=None, cwd="": (True, ""))
    out = run_tool("ejecutar_guion", f'"{sys.executable}" "{p}" | entradas=2|10|3|q | timeout=40',
                   {"workspace": str(tmp_path)})
    assert out.startswith("RESULTADO ejecutar_guion"), out
    assert "resultado: 7" in out and ">>> entrada: '3'" in out and "rc=0" in out


def test_tool_ejecutar_guion_respeta_el_sentinel(monkeypatch):
    from cognia.agent.tools import run_tool
    monkeypatch.setattr("cognia.agent.sentinel.evaluar_shell", lambda cmd, ctx=None, cwd="": (False, "BLOQUEADO por prueba"))
    out = run_tool("ejecutar_guion", "rm -rf / | entradas=s", {})
    assert "BLOQUEADO" in out


def test_tool_ejecutar_guion_sin_comando():
    from cognia.agent.tools import run_tool
    out = run_tool("ejecutar_guion", "| entradas=1", {})
    assert "falta el comando" in out
