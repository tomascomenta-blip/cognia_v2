# -*- coding: utf-8 -*-
"""
Regresion de cognia/harness/verificacion.py (auto-lint + auto-test tras editar).

Todo es REAL: pytest se lanza de verdad en un subproceso sobre ficheros de test
escritos en tmp_path (nada de mocks). El anti-bucle se comprueba por evidencia
observable: el test generado APENDEA una linea a un log cada vez que corre, asi
que si la cache funciona el log sigue teniendo una sola linea.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cognia.harness import verificacion as _verif
from cognia.harness.verificacion import (
    correr_tests, limpiar_cache, texto_resultado, verificar_edicion,
    verificar_sintaxis,
)

# `tests_asociados` importado con su nombre lo COLECTA pytest como test (python_functions
# = 'test*') y falla pidiendo una fixture 'ruta_editada'. Se usa con alias privado.
_tests_asociados = _verif.tests_asociados

MOD_OK = "def sumar(a, b):\n    return a + b\n"
MOD_ROTO = "def sumar(a, b):\n    return a +\n"

# Test que deja rastro de CADA corrida: la evidencia del anti-bucle.
TEST_CONTADOR = (
    "from pathlib import Path\n"
    "\n"
    "def test_sumar():\n"
    "    log = Path(__file__).with_name('corridas.log')\n"
    "    with log.open('a', encoding='utf-8') as f:\n"
    "        f.write('corrida\\n')\n"
    "    assert 1 + 1 == 2\n"
)

TEST_QUE_FALLA = (
    "def test_falla():\n"
    "    esperado = 3\n"
    "    assert 1 + 1 == esperado\n"
)


def _escribir(p: Path, texto: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def _repo(tmp_path: Path) -> Path:
    raiz = (tmp_path / "repo").resolve()
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


# ── sintaxis ────────────────────────────────────────────────────────────

def test_sintaxis_python_ok_y_rota():
    ok, msg = verificar_sintaxis("pkg/mod.py", MOD_OK)
    assert ok is True and msg == "sintaxis OK"

    ok, msg = verificar_sintaxis("pkg/mod.py", MOD_ROTO)
    assert ok is False
    # numero de linea Y texto de la linea ofensora (el modelo no debe releer el fichero)
    assert "ERROR linea 2" in msg
    assert "return a +" in msg


def test_sintaxis_python_caza_lo_que_ast_parse_deja_pasar():
    """compile() (no ast.parse): 'return' fuera de funcion es error de compilacion."""
    ok, msg = verificar_sintaxis("x.py", "return 1\n")
    assert ok is False and "ERROR linea 1" in msg


def test_sintaxis_json():
    ok, msg = verificar_sintaxis("datos.json", '{"a": 1}')
    assert ok is True and "JSON valido" in msg

    ok, msg = verificar_sintaxis("datos.json", '{\n  "a": 1,\n}\n')
    assert ok is False and "ERROR linea 3" in msg

    # el TEXTO de la linea ofensora tambien en JSON: JSONDecodeError no trae `.text`,
    # asi que aqui solo lo puede dar _linea_ofensora (en Python cae el fallback y el
    # fallo se enmascara). Sin esto el "no releas el fichero" no estaba cubierto.
    ok, msg = verificar_sintaxis("datos.json", '{\n  "a": 1,\n  "b": nulo\n}\n')
    assert ok is False
    assert "ERROR linea 3 col" in msg
    assert '"b": nulo' in msg


def test_sintaxis_otros_lenguajes_declara_el_limite():
    ok, msg = verificar_sintaxis("notas/plan.md", "# titulo\n```\nlo que sea\n")
    assert ok is True
    assert "sin verificador" in msg and ".md" in msg


# ── tests asociados ─────────────────────────────────────────────────────

def test_asociados_orden_y_solo_lo_que_existe(tmp_path):
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    t_global = _escribir(raiz / "tests" / "test_mod.py", TEST_QUE_FALLA)
    t_vecino = _escribir(raiz / "pkg" / "test_mod.py", TEST_QUE_FALLA)
    t_paquete = _escribir(raiz / "tests" / "pkg" / "test_mod.py", TEST_QUE_FALLA)

    hallados = _tests_asociados(mod, raiz)
    assert hallados == [t_global, t_vecino, t_paquete]


def test_asociados_vacio_si_no_hay_nada(tmp_path):
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    (raiz / "tests").mkdir(exist_ok=True)
    # no se inventa nada: sin fichero de test en disco, lista vacia
    assert _tests_asociados(mod, raiz) == []


def test_asociados_el_propio_fichero_si_es_un_test(tmp_path):
    raiz = _repo(tmp_path)
    t = _escribir(raiz / "tests" / "test_cosa.py", TEST_QUE_FALLA)
    assert _tests_asociados(t, raiz) == [t]


def test_asociados_convencion_del_repo_paquete_nombre(tmp_path):
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "cognia" / "agent" / "tools.py", MOD_OK)
    t = _escribir(raiz / "tests" / "test_agent_tools.py", TEST_QUE_FALLA)
    assert _tests_asociados(mod, raiz) == [t]


# ── correr_tests (pytest de verdad, en subproceso) ──────────────────────

def test_correr_tests_pasa_y_falla_de_verdad(tmp_path):
    raiz = _repo(tmp_path)
    bueno = _escribir(raiz / "tests" / "test_bueno.py", TEST_CONTADOR)
    malo = _escribir(raiz / "tests" / "test_malo.py", TEST_QUE_FALLA)

    r = correr_tests([bueno], python_exe=sys.executable, cwd=raiz)
    assert r["ok"] is True
    assert "1 passed" in r["resumen"]

    r = correr_tests([malo], python_exe=sys.executable, cwd=raiz)
    assert r["ok"] is False
    assert "failed" in r["resumen"]
    # la cola conserva el traceback real, que es la senal para el modelo
    assert "assert" in r["salida_recortada"]


def test_correr_tests_sin_rutas_no_lanza_pytest():
    r = correr_tests([], python_exe=sys.executable)
    assert r["ok"] is True and r["resumen"] == "sin tests que correr"


def test_correr_tests_nunca_lanza_con_interprete_inexistente(tmp_path):
    r = correr_tests([tmp_path / "test_x.py"], python_exe=tmp_path / "no_existe.exe")
    assert r["ok"] is False
    assert "no se pudo lanzar" in r["resumen"]


def test_correr_tests_timeout_es_veredicto_no_excepcion(tmp_path):
    raiz = _repo(tmp_path)
    lento = _escribir(raiz / "tests" / "test_lento.py",
                      "import time\n\ndef test_lento():\n    time.sleep(30)\n")
    r = correr_tests([lento], python_exe=sys.executable, timeout=2, cwd=raiz)
    assert r["ok"] is False
    assert "timeout tras 2s" in r["resumen"]


def test_correr_tests_recorta_la_salida_conservando_la_cola(tmp_path):
    raiz = _repo(tmp_path)
    # 60 tests que fallan -> salida larga; el recorte deja la COLA (linea de resumen)
    cuerpo = "".join(f"def test_n{i}():\n    assert False\n\n" for i in range(60))
    largo = _escribir(raiz / "tests" / "test_largo.py", cuerpo)
    r = correr_tests([largo], python_exe=sys.executable, cwd=raiz)
    assert r["ok"] is False
    assert "60 failed" in r["resumen"]
    assert len(r["salida_recortada"].splitlines()) <= 41
    assert "lineas omitidas" in r["salida_recortada"]


# ── veredicto completo ──────────────────────────────────────────────────

def test_verificar_edicion_sintaxis_rota_no_corre_tests(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = raiz / "pkg" / "mod.py"
    _escribir(mod, MOD_ROTO)
    _escribir(raiz / "tests" / "test_mod.py", TEST_CONTADOR)

    v = verificar_edicion(mod, MOD_ROTO, raiz=raiz, python_exe=sys.executable)
    assert v["sintaxis_ok"] is False
    assert v["tests_ok"] is None
    assert v["tests_encontrados"] == []
    assert "ERROR linea 2" in v["texto"]
    # el test NO se corrio: no hay log
    assert not (raiz / "tests" / "corridas.log").exists()


def test_verificar_edicion_ok_corre_el_test_asociado(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    _escribir(raiz / "tests" / "test_mod.py", TEST_CONTADOR)

    v = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v["sintaxis_ok"] is True
    assert v["tests_ok"] is True
    assert v["tests_encontrados"] == ["tests/test_mod.py"]
    assert "1 passed" in v["resumen"]
    assert "tests OK" in v["texto"]
    assert (raiz / "tests" / "corridas.log").read_text(encoding="utf-8").count("corrida") == 1


def test_verificar_edicion_sin_tests_no_es_aprobado(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "solo.py", MOD_OK)

    v = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v["sintaxis_ok"] is True
    assert v["tests_ok"] is None          # ausencia de examen != aprobado
    assert "sin tests asociados" in v["resumen"]


def test_verificar_edicion_tests_que_fallan_devuelven_el_error_real(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    _escribir(raiz / "tests" / "test_mod.py", TEST_QUE_FALLA)

    v = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v["tests_ok"] is False
    assert "failed" in v["resumen"]
    assert "TESTS FALLAN" in v["texto"]
    assert "test_falla" in v["texto"]     # el traceback real viaja al modelo


def test_anti_bucle_no_recorre_si_el_contenido_no_cambio(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    _escribir(raiz / "tests" / "test_mod.py", TEST_CONTADOR)
    log = raiz / "tests" / "corridas.log"

    v1 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    v2 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v1["tests_ok"] is True and v2["tests_ok"] is True
    assert log.read_text(encoding="utf-8").count("corrida") == 1   # pytest corrio UNA vez
    assert "cache" in v2["resumen"]
    assert "cache" not in v1["resumen"]

    # contenido distinto -> se re-corre (la cache es por hash, no por ruta)
    nuevo = MOD_OK + "\n# comentario nuevo\n"
    v3 = verificar_edicion(mod, nuevo, raiz=raiz, python_exe=sys.executable)
    assert v3["tests_ok"] is True
    assert "cache" not in v3["resumen"]
    assert log.read_text(encoding="utf-8").count("corrida") == 2

    # limpiar_cache() fuerza la re-corrida del contenido ya visto
    limpiar_cache()
    v4 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert "cache" not in v4["resumen"]
    assert log.read_text(encoding="utf-8").count("corrida") == 3


def test_verificar_edicion_correr_false_lista_pero_no_ejecuta(tmp_path):
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    _escribir(raiz / "tests" / "test_mod.py", TEST_CONTADOR)

    v = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable, correr=False)
    assert v["tests_encontrados"] == ["tests/test_mod.py"]
    assert v["tests_ok"] is None
    assert not (raiz / "tests" / "corridas.log").exists()


def test_cache_se_invalida_si_cambia_el_TEST_no_el_modulo(tmp_path):
    """Regresion: el veredicto rancio empujaba a re-editar un fichero ya correcto.

    La cache se llaveaba por el hash del fichero VERIFICADO. Si el agente arreglaba el
    test (y no el modulo), el contenido del modulo no cambiaba -> cache hit -> el
    harness seguia gritando "TESTS FALLAN" sobre codigo sano, para siempre.
    """
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    test = raiz / "tests" / "test_mod.py"
    _escribir(test, TEST_QUE_FALLA)

    v1 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v1["tests_ok"] is False

    # se arregla EL TEST; el modulo no se toca
    _escribir(test, "def test_falla():\n    assert 1 + 1 == 2\n")
    v2 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v2["tests_ok"] is True, "veredicto rancio: la cache ignoro el test nuevo"
    assert "cache" not in v2["resumen"]

    # y con el test intacto, la cache SI sigue evitando la re-corrida
    v3 = verificar_edicion(mod, MOD_OK, raiz=raiz, python_exe=sys.executable)
    assert v3["tests_ok"] is True and "cache" in v3["resumen"]


def test_fallo_del_harness_no_se_le_achaca_al_modelo(tmp_path):
    """pytest no lanzable != codigo roto: el texto no debe pedir editar el fichero."""
    limpiar_cache()
    raiz = _repo(tmp_path)
    mod = _escribir(raiz / "pkg" / "mod.py", MOD_OK)
    _escribir(raiz / "tests" / "test_mod.py", TEST_CONTADOR)

    v = verificar_edicion(mod, MOD_OK, raiz=raiz,
                          python_exe=raiz / "interprete_que_no_existe.exe")
    assert v["tests_ok"] is False
    assert v["error_harness"] is True
    assert "VERIFICACION NO DISPONIBLE" in v["texto"]
    assert "TESTS FALLAN" not in v["texto"]
    assert "no cambies el fichero" in v["texto"]
    # y no se cachea: un fallo de harness se arregla fuera del contenido
    assert not _verif._CACHE


def test_sintaxis_sin_numero_de_linea_sigue_siendo_clasificable():
    """Bytes nulos: compile() da SyntaxError con lineno=None -> nada de 'ERROR linea None'."""
    from cognia.agent.stepwise import classify_exec_error

    ok, msg = verificar_sintaxis("x.py", "a = 1\x00\n")
    assert ok is False
    assert "linea None" not in msg
    assert classify_exec_error("py_validar", msg) == "syntax"


def test_correr_tests_acepta_una_ruta_suelta(tmp_path):
    """Una str/Path suelta se iteraba por CARACTERES -> 'no tests ran' falso."""
    raiz = _repo(tmp_path)
    bueno = _escribir(raiz / "tests" / "test_uno.py", TEST_QUE_FALLA.replace("3", "2"))

    r = correr_tests(str(bueno), python_exe=sys.executable, cwd=raiz)
    assert r["ok"] is True and "1 passed" in r["resumen"]
    r = correr_tests(bueno, python_exe=sys.executable, cwd=raiz)
    assert r["ok"] is True and "1 passed" in r["resumen"]


def test_resumen_no_confunde_un_traceback_con_el_sumario():
    """'ValueError: 3' cumplia 'tiene error y un digito' y se colaba como resumen."""
    salida = ("F\n=== FAILURES ===\n"
              "1 failed in 0.10s\n"
              "Exception ignored in: <function X>\n"
              "ValueError: 42 quedo colgado\n")
    assert _verif._resumen_pytest(salida, 1) == "1 failed in 0.10s"


def test_texto_resultado_es_clasificable_por_stepwise():
    """El texto debe encajar con classify_exec_error para reusar el lazo de reparacion."""
    from cognia.agent.stepwise import classify_exec_error

    v = {"ruta": "pkg/mod.py", "sintaxis_ok": False, "mensaje": "ERROR linea 2: invalid syntax",
         "tests_encontrados": [], "tests_ok": None, "resumen": "", "salida_recortada": ""}
    assert classify_exec_error("py_validar", texto_resultado(v)) == "syntax"

    v = {"ruta": "pkg/mod.py", "sintaxis_ok": True, "mensaje": "sintaxis OK",
         "tests_encontrados": ["tests/test_mod.py"], "tests_ok": False,
         "resumen": "1 failed in 0.10s", "salida_recortada": "E  AssertionError"}
    assert classify_exec_error("tests", texto_resultado(v)) == "assert"
