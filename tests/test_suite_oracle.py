"""Regresión del oráculo determinista de las suites COGNIA 3B (P0-ii)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cognia_v3" / "eval" / "suites"))

from suite_oracle import (carga_suite, es_espanol, fold, oracle_pass,
                          ultimo_numero)


def test_fold_quita_acentos_y_case():
    assert fold("Sí, CAFÉ años") == "si, cafe anos"


def test_must_all_y_any():
    assert oracle_pass("La capital es París, claro", {"must_all": ["paris"]})
    assert not oracle_pass("La capital es Roma", {"must_all": ["paris"]})
    assert oracle_pass("sí, es verdad", {"must_any": ["yes", "si"]})
    assert not oracle_pass("no lo sé", {"must_any": ["yes", "si"]})


def test_not_any_rechaza():
    assert not oracle_pass("Soy Qwen, un asistente",
                           {"must_any": ["cognia"], "not_any": ["qwen"]})
    assert oracle_pass("Soy Cognia, tu asistente local",
                       {"must_any": ["cognia"], "not_any": ["qwen", "alibaba"]})


def test_number_toma_el_ultimo():
    assert ultimo_numero("Primero 12, después el resultado es 30") == 30
    assert ultimo_numero("cuesta 12,5 euros") == 12.5
    assert ultimo_numero("sin cifras") is None
    assert oracle_pass("El cálculo da 15% de 200 = 30", {"number": 30})
    assert not oracle_pass("El cálculo da 25", {"number": 30})
    # respuesta correcta seguida de otro número = falla (regla del ÚLTIMO)
    assert not oracle_pass("Son 30. Ver página 12.", {"number": 30})


def test_combinacion_de_restricciones():
    o = {"must_all": ["mamifero"], "must_any": ["si", "yes"], "not_any": ["reptil"]}
    assert oracle_pass("Sí: la ballena es un mamífero", o)
    assert not oracle_pass("Sí: la ballena es un mamífero... o reptil", o)
    assert not oracle_pass("la ballena es un mamífero", o)  # falta must_any


def test_es_espanol_heuristica():
    assert es_espanol("La fotosíntesis es el proceso por el cual las plantas "
                      "convierten la luz del sol en energía química.")
    assert not es_espanol("The answer is that plants convert sunlight into "
                          "chemical energy through photosynthesis.")


def test_carga_suite_valida_y_rechaza(tmp_path):
    ok = {"id": "G1-RZ-001", "gate": "G1", "dominio": "razonamiento",
          "idioma": "es", "shots": 0, "prompt": "¿2+2?",
          "oracle": {"number": 4}, "max_new_tokens": 50}
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps(ok) + "\n", encoding="utf-8")
    assert len(carga_suite(str(p))) == 1

    malo = dict(ok, oracle={})  # oracle sin restricciones
    p.write_text(json.dumps(ok) + "\n" + json.dumps(dict(malo, id="G1-RZ-002")) + "\n",
                 encoding="utf-8")
    try:
        carga_suite(str(p))
        raise AssertionError("debía rechazar oracle vacío")
    except ValueError:
        pass

    dup = dict(ok)  # id duplicado
    p.write_text(json.dumps(ok) + "\n" + json.dumps(dup) + "\n", encoding="utf-8")
    try:
        carga_suite(str(p))
        raise AssertionError("debía rechazar id duplicado")
    except ValueError:
        pass
