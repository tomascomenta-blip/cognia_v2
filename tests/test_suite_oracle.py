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


# ── G2A: oráculo de tool-use formato ACCION (suite g2_accion.jsonl) ─────────

def test_accion_pass_primera_accion():
    from cognia_v3.eval.suites.suite_oracle import accion_pass
    oracle = {"accion_tools": ["contar_lineas"], "args_regex": r"copia_f\.txt"}
    # tool correcta + archivo correcto
    assert accion_pass("ACCION: contar_lineas copia_f.txt", oracle)
    # tool correcta, archivo equivocado -> falla por args_regex
    assert not accion_pass("ACCION: contar_lineas fuente.txt", oracle)
    # tool equivocada aunque despues venga la correcta (mide la PRIMERA)
    assert not accion_pass("ACCION: leer_archivo copia_f.txt\n"
                           "ACCION: contar_lineas copia_f.txt", oracle)
    # sin ACCION parseable
    assert not accion_pass("voy a contar las lineas de copia_f.txt", oracle)
    # acento en ACCIÓN y case-insensitive
    assert accion_pass("ACCIÓN: contar_lineas copia_f.txt", oracle)


def test_accion_pass_bloque_multilinea():
    from cognia_v3.eval.suites.suite_oracle import accion_pass
    oracle = {"accion_tools": ["escribir_archivo"], "args_regex": r"compras\.txt"}
    # args multilínea dentro del bloque de la primera ACCION
    assert accion_pass("ACCION: escribir_archivo compras.txt | leche\ncafe\nazucar",
                       oracle)
    # el regex NO debe matchear en el bloque de una segunda ACCION
    oracle2 = {"accion_tools": ["leer_archivo"], "args_regex": r"compras\.txt"}
    assert not accion_pass("ACCION: leer_archivo otro.txt\n"
                           "ACCION: escribir_archivo compras.txt | x", oracle2)


def test_accion_pass_sin_args_regex_y_cierre():
    from cognia_v3.eval.suites.suite_oracle import accion_pass
    assert accion_pass("ACCION: responder Listo, tarea completada.",
                       {"accion_tools": ["responder"], "args_regex": None})
    assert not accion_pass("ACCION: leer_archivo x.txt",
                           {"accion_tools": ["responder"], "args_regex": None})


def test_carga_suite_g2a(tmp_path):
    ok = {"id": "g2a_x-s1", "gate": "G2A", "dominio": "archivo", "idioma": "es",
          "shots": 0, "prompt": "TAREA: algo\n\nSiguiente ACCION:",
          "oracle": {"accion_tools": ["escribir_archivo"], "args_regex": None},
          "max_new_tokens": 200}
    p = tmp_path / "g2a.jsonl"
    p.write_text(json.dumps(ok) + "\n", encoding="utf-8")
    assert len(carga_suite(str(p))) == 1
    # G2A sin accion_tools -> rechazo
    malo = dict(ok, id="g2a_x-s2", oracle={"accion_tools": []})
    p.write_text(json.dumps(malo) + "\n", encoding="utf-8")
    try:
        carga_suite(str(p))
        raise AssertionError("debía rechazar G2A sin accion_tools")
    except ValueError:
        pass
    # G2A con clave de oracle de texto -> rechazo
    malo2 = dict(ok, id="g2a_x-s3",
                 oracle={"accion_tools": ["leer_archivo"], "must_all": ["x"]})
    p.write_text(json.dumps(malo2) + "\n", encoding="utf-8")
    try:
        carga_suite(str(p))
        raise AssertionError("debía rechazar clave must_all en G2A")
    except ValueError:
        pass


def test_suite_g2a_congelada_carga():
    """La suite real congelada carga y valida (regresión del freeze)."""
    import os
    here = os.path.join(os.path.dirname(__file__), "..", "cognia_v3", "eval",
                        "suites", "g2_accion.jsonl")
    items = carga_suite(here)
    assert len(items) >= 100
    # todos los cierres esperan 'responder' (miden terminación)
    cierres = [it for it in items if it["step"] == it["n_steps"]]
    assert cierres and all(it["oracle"]["accion_tools"] == ["responder"]
                           for it in cierres)


def test_train_v2_no_toca_superficies_de_suite_g2a():
    """Higiene held-out: el banco de train v2 no puede usar filenames de la
    suite congelada G2A (check programático, no lista manual)."""
    from cognia_v3.training.tooluse.tasks_v2 import check_superficies
    assert check_superficies() == []
