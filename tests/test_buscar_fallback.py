# -*- coding: utf-8 -*-
"""Regresión: el tool `buscar` rescata la búsqueda cuando el 3B agrega spam a los
args. Repro 2026-07-11 (tarea G6-015): el modelo llamó `buscar CLAVE-FENIX tetas
Incontri` — el patrón literal con spam no matcheaba 'CLAVE-FENIX-701' en el archivo
y el agente respondía 'No se encontraron resultados' (FALSO). Fix: si el patrón
completo (varias palabras) no matcha, reintentar con el token IDENTIFICADOR
distintivo (con guion/dígito/guion-bajo); no rescatar palabras comunes."""
from cognia.agent.tools import _buscar


def test_rescata_token_distintivo_pese_al_spam(tmp_path):
    (tmp_path / "notas_a.txt").write_text("lista de compras: pan, yerba\n", encoding="utf-8")
    (tmp_path / "notas_b.txt").write_text("referencia CLAVE-FENIX-701 anotada aca\n", encoding="utf-8")
    out = _buscar(f"CLAVE-FENIX tetas Incontri | {tmp_path}", {})
    assert "notas_b.txt" in out or "CLAVE-FENIX-701" in out, out
    assert "acotado a 'CLAVE-FENIX'" in out, "no reportó el acotado del patrón"


def test_patron_limpio_sigue_funcionando(tmp_path):
    (tmp_path / "doc.txt").write_text("hola mundo cruel\n", encoding="utf-8")
    out = _buscar(f"mundo | {tmp_path}", {})
    assert "doc.txt" in out, out
    assert "acotado" not in out, "no debía acotar un patrón que matcheó directo"


def test_no_rescata_palabras_comunes(tmp_path):
    # patrón multi-palabra sin token identificador -> NO rescate (evita falsos +)
    (tmp_path / "f.txt").write_text("config y settings varios\n", encoding="utf-8")
    out = _buscar(f"archivo config settings | {tmp_path}", {})
    assert ("sin resultados" in out or "sin coincidencias" in out), f"rescató palabras comunes (falso +): {out}"


def test_sin_match_devuelve_sin_resultados(tmp_path):
    (tmp_path / "f.txt").write_text("nada relevante aca\n", encoding="utf-8")
    out = _buscar(f"XYZ-INEXISTENTE-999 | {tmp_path}", {})
    assert ("sin resultados" in out or "sin coincidencias" in out), out
