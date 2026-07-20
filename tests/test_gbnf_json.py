# -*- coding: utf-8 -*-
"""
tests/test_gbnf_json.py
Tests de cognia_v3/eval/gbnf_json.py (generador+validador+matcher GBNF) y del
clasificador ampliado de diag_json — sin modelo ni server real: el matcher
propio hace de "server" FAKE contra outputs positivos y negativos.
"""

from __future__ import annotations

import pytest

from cognia_v3.eval.gbnf_json import (
    autocomprobar, coincide, esquema_a_gbnf, parsear_gbnf, validar_gbnf,
)
from cognia_v3.eval.diag_json import TAREAS, clasificar, sha256_tareas

# Suite CONGELADA antes de medir (regla del método): estos hashes fijan las
# 24 originales del hallazgo N=24 y la ampliación completa N=72. Si alguien
# toca/reordena una tarea, estos tests fallan ANTES de que se mida nada.
SHA24 = "07ad39d9b3663547a0e4c447a9d9e0cec8bbaf8ada7efa921311094b33cc78ea"
SHA72 = "616cb05f8ba8768407e7bdfda7a7e51be91fafeec4cbe60f5d5a27d307a7e1ed"


# ---------------------------------------------------------------------------
# Parser/validador GBNF propio
# ---------------------------------------------------------------------------

class TestValidarGbnf:
    def test_grammar_generada_es_valida(self):
        g = esquema_a_gbnf({"nombre": str, "edad": (int, float)})
        assert validar_gbnf(g) == []

    def test_grammar_de_benchmark_code_parsea(self):
        """Cross-check con una GBNF REAL ya desplegada en producción."""
        from cognia_v3.eval.benchmark_code import GRAMMAR_PYTHON_BLOCK
        reglas = parsear_gbnf(GRAMMAR_PYTHON_BLOCK)
        assert set(reglas) == {"root", "body"}
        assert validar_gbnf(GRAMMAR_PYTHON_BLOCK) == []

    def test_referencia_no_definida(self):
        errs = validar_gbnf('root ::= "a" fantasma\n')
        assert any("fantasma" in e for e in errs)

    def test_paren_sin_cerrar(self):
        errs = validar_gbnf('root ::= ("a" | "b"\n')
        assert errs and "')'" in errs[0]

    def test_literal_sin_cerrar(self):
        errs = validar_gbnf('root ::= "abc\n')
        assert errs and "literal" in errs[0]

    def test_falta_root(self):
        errs = validar_gbnf('regla ::= "a"\n')
        assert any("root" in e for e in errs)

    def test_regla_duplicada(self):
        errs = validar_gbnf('root ::= "a"\nroot ::= "b"\n')
        assert errs and "duplicada" in errs[0]

    def test_multilinea_con_parens_estilo_json_gbnf(self):
        """El estilo de grammars/json.gbnf (regla que abre paréntesis y sigue
        en la línea siguiente) parsea — mismo comportamiento que llama.cpp."""
        g = 'root ::= "\\"" (\n  [^"] |\n  "\\\\" ["nrt]\n)* "\\""\n'
        assert validar_gbnf(g) == []
        assert coincide(g, '"hola"')
        assert coincide(g, '"a\\n"')
        assert not coincide(g, '"sin cerrar')


# ---------------------------------------------------------------------------
# esquema_a_gbnf: tipos
# ---------------------------------------------------------------------------

class TestTipos:
    def test_string(self):
        g = esquema_a_gbnf({"k": str})
        assert coincide(g, '{"k": "hola"}')
        assert not coincide(g, '{"k": 5}')

    def test_numero(self):
        g = esquema_a_gbnf({"k": (int, float)})
        for ok in ('{"k": 5}', '{"k": -2.5}', '{"k": 0}', '{"k": 1e3}',
                   '{"k": -1500.75}'):
            assert coincide(g, ok), ok
        for mal in ('{"k": "5"}', '{"k": 007}', '{"k": .5}', '{"k": 1.}'):
            assert not coincide(g, mal), mal

    def test_entero_estricto(self):
        g = esquema_a_gbnf({"k": int})
        assert coincide(g, '{"k": -7}')
        assert not coincide(g, '{"k": 7.5}')

    def test_boolean(self):
        g = esquema_a_gbnf({"k": bool})
        assert coincide(g, '{"k": true}')
        assert coincide(g, '{"k": false}')
        assert not coincide(g, '{"k": "true"}')
        assert not coincide(g, '{"k": 1}')

    def test_lista(self):
        g = esquema_a_gbnf({"k": list})
        for ok in ('{"k": []}', '{"k": [1, "a", true, null]}',
                   '{"k": [[1, 2], [3, 4]]}', '{"k": [{"x": 1}]}'):
            assert coincide(g, ok), ok
        assert not coincide(g, '{"k": {}}')

    def test_dict(self):
        g = esquema_a_gbnf({"k": dict})
        for ok in ('{"k": {}}', '{"k": {"a": 1, "b": [2]}}',
                   '{"k": {"a": {"b": {"c": 1}}}}'):
            assert coincide(g, ok), ok
        assert not coincide(g, '{"k": []}')

    def test_null(self):
        g = esquema_a_gbnf({"k": type(None)})
        assert coincide(g, '{"k": null}')
        assert not coincide(g, '{"k": "null"}')
        assert not coincide(g, "{}")


# ---------------------------------------------------------------------------
# esquema_a_gbnf: claves exactas, cualquier orden
# ---------------------------------------------------------------------------

class TestClavesExactas:
    def test_cualquier_orden_3_claves(self):
        import itertools
        g = esquema_a_gbnf({"a": (int, float), "b": str, "c": bool})
        vals = {"a": "1", "b": '"x"', "c": "true"}
        for p in itertools.permutations("abc"):
            j = "{" + ", ".join(f'"{k}": {vals[k]}' for k in p) + "}"
            assert coincide(g, j), j

    def test_rechaza_objeto_vacio_y_subconjunto(self):
        g = esquema_a_gbnf({"a": (int, float), "b": str})
        assert not coincide(g, "{}")
        assert not coincide(g, '{"a": 1}')
        assert not coincide(g, '{"b": "x"}')

    def test_rechaza_clave_extra(self):
        g = esquema_a_gbnf({"a": (int, float)})
        assert not coincide(g, '{"a": 1, "b": 2}')

    def test_fallo_a_clave_traducida(self):
        """El fallo (a) del hallazgo N=24: pide 'dependencias' y el 3B emite
        'dependencies'. La grammar fija la clave como literal: la traducción
        queda IMPOSIBLE por construcción."""
        g = esquema_a_gbnf({"version": str, "dependencias": list})
        assert coincide(g, '{"version": "1.0.0", "dependencias": []}')
        assert not coincide(g, '{"version": "1.0.0", "dependencies": []}')

    def test_fallo_b_objeto_vacio(self):
        """Fallo (b): pide {empty:{}} y el 3B emite {} — la clave es obligatoria."""
        g = esquema_a_gbnf({"empty": dict})
        assert coincide(g, '{"empty": {}}')
        assert not coincide(g, "{}")

    def test_fallo_c_null(self):
        """Fallo (c): pide {nulo:null} y el 3B emite {} — null forzado."""
        g = esquema_a_gbnf({"nulo": type(None)})
        assert coincide(g, '{"nulo": null}')
        assert not coincide(g, "{}")
        assert not coincide(g, '{"nulo": "null"}')

    def test_clave_con_acento_literal(self):
        g = esquema_a_gbnf({"título": str})
        assert coincide(g, '{"título": "x"}')
        assert not coincide(g, '{"titulo": "x"}')

    def test_whitespace_tolerado(self):
        g = esquema_a_gbnf({"a": (int, float), "b": str})
        assert coincide(g, '{ "a" : 1 , "b" : "x" }')
        assert coincide(g, '{\n  "a": 1,\n  "b": "x"\n}')
        # pero NO whitespace antes del '{' ni después del '}' (diseño: al
        # cerrar el objeto el único token legal es EOS)
        assert not coincide(g, ' {"a": 1, "b": "x"}')
        assert not coincide(g, '{"a": 1, "b": "x"} ')


class TestEscapes:
    def test_backslashes_escapados(self):
        g = esquema_a_gbnf({"ruta": str})
        assert coincide(g, '{"ruta": "C:\\\\temp\\\\datos.txt"}')
        # backslash SUELTO (escape JSON inválido \\d) rechazado
        assert not coincide(g, '{"ruta": "C:\\datos"}')

    def test_comillas_escapadas(self):
        g = esquema_a_gbnf({"m": str})
        assert coincide(g, '{"m": "He said \\"hello\\""}')

    def test_control_crudo_rechazado_escapado_aceptado(self):
        g = esquema_a_gbnf({"t": str})
        assert not coincide(g, '{"t": "a\tb"}')   # tab crudo = control char
        assert coincide(g, '{"t": "a\\tb"}')      # \t escapado
        assert coincide(g, '{"t": "l1\\nl2"}')    # \n escapado
        assert coincide(g, '{"t": "\\u00f1and\\u00fa"}')  # escape unicode
        assert coincide(g, '{"t": "ñandú"}')      # UTF-8 crudo también


class TestLimites:
    def test_schema_vacio_o_invalido(self):
        with pytest.raises(ValueError):
            esquema_a_gbnf({})
        with pytest.raises(ValueError):
            esquema_a_gbnf(None)

    def test_tipo_no_soportado(self):
        with pytest.raises(ValueError):
            esquema_a_gbnf({"k": set})

    def test_tope_permutaciones(self):
        # 6 claves > _PERM_MAX=5: error explícito, no degradar en silencio
        schema = {f"k{i}": str for i in range(6)}
        with pytest.raises(ValueError):
            esquema_a_gbnf(schema)
        assert esquema_a_gbnf({f"k{i}": str for i in range(5)})  # 5 pasa


# ---------------------------------------------------------------------------
# Autocomprobación sobre la suite COMPLETA (los 71 schemas de las 72 tareas)
# ---------------------------------------------------------------------------

class TestSuiteCompleta:
    def test_autocomprobar_todos_los_schemas(self):
        con_schema = 0
        for i, (_, schema, _) in enumerate(TAREAS):
            if not schema:
                continue
            con_schema += 1
            assert autocomprobar(schema) == [], f"tarea {i}: {schema}"
        assert con_schema == 71  # 72 tareas - idx 9 (array sin schema)


# ---------------------------------------------------------------------------
# Suite ampliada: congelada por sha256, balanceada, con cobertura declarada
# ---------------------------------------------------------------------------

class TestTareasCongeladas:
    def test_n_total(self):
        assert len(TAREAS) == 72

    def test_originales_intactas(self):
        """Las 24 del hallazgo N=24 no se tocan (comparabilidad)."""
        assert sha256_tareas(TAREAS[:24]) == SHA24

    def test_suite_completa_congelada(self):
        assert sha256_tareas() == SHA72

    def test_balance_es_en_de_las_nuevas(self):
        nuevas = TAREAS[24:]
        es = sum(1 for p, _, _ in nuevas if p.startswith(("Devolvé", "Generá")))
        en = sum(1 for p, _, _ in nuevas if p.startswith("Return"))
        assert es == 24 and en == 24

    def test_formato_de_las_nuevas(self):
        from cognia_v3.eval.gbnf_json import _TIPO_A_REGLA
        for prompt, schema, checks in TAREAS[24:]:
            assert isinstance(prompt, str) and prompt
            assert isinstance(schema, dict) and 1 <= len(schema) <= 4
            for t in schema.values():
                for tt in (t if isinstance(t, tuple) else (t,)):
                    assert tt in _TIPO_A_REGLA, tt
            assert checks is None or isinstance(checks, dict)

    def test_cobertura_de_categorias(self):
        nuevas = TAREAS[24:]
        schemas = [s for _, s, _ in nuevas]
        checks = [c for _, _, c in nuevas if isinstance(c, dict)]
        # null
        assert any(type(None) in s.values() for s in schemas)
        # vacíos: string, lista y objeto
        assert any("" in c.values() for c in checks)
        assert any(v == [] for c in checks for v in c.values())
        assert any(v == {} for c in checks for v in c.values())
        # escapes en el enunciado (backslashes / \n / comillas)
        assert any("\\\\" in p or "\\n" in p or '\\"' in p or '"' in p
                   for p, _, _ in nuevas)
        # anidamiento (dict dentro de dict, o lista de dicts)
        assert any(isinstance(v, dict) and any(isinstance(x, dict)
                   for x in v.values()) for c in checks for v in c.values())
        assert any(isinstance(v, list) and any(isinstance(x, dict) for x in v)
                   for c in checks for v in c.values())
        # booleanos y negativos/floats
        assert any(isinstance(v, bool) for c in checks for v in c.values())
        assert any(isinstance(v, float) and v < 0
                   for c in checks for v in c.values())


# ---------------------------------------------------------------------------
# Clasificador ampliado de diag_json (con outputs FAKE)
# ---------------------------------------------------------------------------

class TestClasificador:
    def test_no_json(self):
        assert clasificar("no puedo hacer eso", {"k": str}, None) == "no_json"
        assert clasificar("", {"k": str}, None) == "no_json"

    def test_pasa_crudo_y_con_fence(self):
        assert clasificar('{"k": "hola"}', {"k": str}, None) == "pasa"
        assert clasificar('```json\n{"k": "hola"}\n```', {"k": str}, None) == "pasa"

    def test_schema_clave_traducida(self):
        # el fallo (a) real del hallazgo N=24
        schema = {"version": str, "dependencias": list}
        assert clasificar('{"version": "1.0.0", "dependencies": []}',
                          schema, None) == "schema"

    def test_schema_tipo_mal(self):
        assert clasificar('{"k": "5"}', {"k": (int, float)}, None) == "schema"

    def test_contenido_valor_mal(self):
        assert clasificar('{"k": 7}', {"k": (int, float)}, {"k": 9}) == "contenido"

    def test_string_vacio_igualdad_exacta(self):
        """Regresión del fix: '' es substring de todo — sin igualdad exacta,
        cualquier string pasaría el check de vacío."""
        schema, checks = {"note": str}, {"note": ""}
        assert clasificar('{"note": ""}', schema, checks) == "pasa"
        assert clasificar('{"note": "algo"}', schema, checks) == "contenido"

    def test_bool_no_pasa_check_numerico(self):
        """Regresión del fix: True==1/False==0 en Python — sin el chequeo de
        booleanidad, false pasaría un check numérico 0."""
        schema, checks = {"errores": (int, float)}, {"errores": 0}
        assert clasificar('{"errores": 0}', schema, checks) == "pasa"
        assert clasificar('{"errores": false}', schema, checks) == "contenido"

    def test_null_ok_y_faltante(self):
        schema, checks = {"nulo": type(None)}, {"nulo": None}
        assert clasificar('{"nulo": null}', schema, checks) == "pasa"
        assert clasificar("{}", schema, checks) == "schema"   # fallo (c)

    def test_array_especial(self):
        assert clasificar("[1, 2, 3, 4, 5]", None, "array_1_5") == "pasa"
        assert clasificar("[1, 2, 3]", None, "array_1_5") == "contenido"
        assert clasificar('{"a": 1}', None, "array_1_5") == "schema"


# ---------------------------------------------------------------------------
# Cableado de correr() con backend FAKE: qué se le pasa al server por ítem
# ---------------------------------------------------------------------------

class _FakeBackend:
    """Registra los kwargs de cada generate() y devuelve JSON fijo (parseable,
    así ningún ítem cae en no_json y el conteo de clases es determinista)."""

    def __init__(self):
        self.llamadas = []

    def generate(self, prompt, max_tokens=256, temperature=0.7,
                 cache_prompt=True, grammar=None, **kw):
        self.llamadas.append({"prompt": prompt, "temperature": temperature,
                              "cache_prompt": cache_prompt, "grammar": grammar})
        return '{"stub": 1}'


class TestCorrerCableado:
    def test_brazo_a_sin_grammar(self):
        from cognia_v3.eval.diag_json import correr
        fake = _FakeBackend()
        res = correr(fake, TAREAS[:12], con_grammar=False)
        assert len(fake.llamadas) == 12
        assert all(c["grammar"] is None for c in fake.llamadas)
        # invariantes del instrumento: greedy + prefill completo SIEMPRE
        assert all(c["temperature"] == 0.0 for c in fake.llamadas)
        assert all(c["cache_prompt"] is False for c in fake.llamadas)
        assert sum(len(v) for v in res.values()) == 12

    def test_brazo_b_grammar_por_item_con_schema(self):
        from cognia_v3.eval.diag_json import correr
        fake = _FakeBackend()
        res = correr(fake, TAREAS[:12], con_grammar=True)
        assert len(fake.llamadas) == 12
        for j, (_, schema, _) in enumerate(TAREAS[:12]):
            g = fake.llamadas[j]["grammar"]
            if schema:
                # la grammar enviada es GBNF válida y es LA del schema del ítem
                assert g is not None and validar_gbnf(g) == []
                assert g == esquema_a_gbnf(schema)
            else:
                assert g is None    # idx 9 (array): sin restricción
        # los ítems guardan si corrieron restringidos (auditoría del brazo)
        marcados = {d["i"]: d["grammar"] for v in res.values() for d in v}
        assert marcados[9] is False and marcados[0] is True
