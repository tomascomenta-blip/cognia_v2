# -*- coding: utf-8 -*-
"""Extracción sin modelo sobre los textos EXACTOS de scripts/memoria_larga/generar_dataset.py."""
import logging

from cognia.memoria_larga import NIVEL_POR_TIPO
from cognia.memoria_larga.extraccion import (extraer, extraer_simbolos, hash_contenido, normalizar_entidad,
                                             ficheros_en, recortar)

K = dict(task_id="t1", session_id="s1", paso=5)

# Textos tal cual los produce el generador (Gen.decision / cambio / restriccion / codigo / error / solucion)
DECISION = "Decisión: para la base de datos usamos SQLite. Motivo: el equipo ya lo conoce."
CAMBIO = ("Cambio de decisión: la base de datos deja de ser SQLite y pasa a ser PostgreSQL, "
          "porque no soporta transacciones anidadas. Actualizá lo que haga falta.")
RESTRICCION = "Restricción, no negociable: nunca escribir fuera de src/ ni de tests/."
DISTRACTOR = "Aparte, en el proyecto del vecino usan MySQL para la base de datos; no aplica aquí, es solo un comentario."
OBJETIVO = "Vamos a construir el sistema de facturas paso a paso. Mantené un registro de las decisiones."
FICHERO = ("RESULTADO leer_archivo pagos/tarifas.py:\n"
           "   1| def calcular_recargo_417(importe, tramo):\n"
           "   2|     \"\"\"Calcula el recargo por tramo: 0-100 → 2 %, 100-1000 → 5 %, >1000 → 9 %,\n"
           "   3|     y suma un fijo de 1.50 si el tramo es 'urgente'. Redondea a 2 decimales.\"\"\"\n"
           "   4|     pct = 0.02 if importe <= 100 else 0.05 if importe <= 1000 else 0.09\n"
           "   5|     fijo = 1.50 if tramo == 'urgente' else 0.0\n"
           "   6|     return round(importe * pct + fijo, 2)\n")
ERROR = ("RESULTADO tests: rc=1 12 passed, 1 failed\nFAILED tests/test_envios.py::test_fecha_limite - "
         "TypeError: can't compare offset-naive and offset-aware datetimes")
SOLUCION = ("Arreglado el fallo de fechas: el problema era comparar un datetime naive con uno aware; "
            "ahora normalizo todo a UTC con `.replace(tzinfo=timezone.utc)` en el parser de entrada.")


def _uno(role, texto, **kw):
    ms = extraer(role, texto, **K, **kw)
    assert len(ms) == 1, [(m.tipo, m.resumen) for m in ms]
    return ms[0]


def test_decision_del_dataset():
    m = _uno("user", DECISION)
    assert m.tipo == "decision" and m.importancia == 5 and m.nivel == NIVEL_POR_TIPO["decision"]
    assert m.entidad == "base de datos" and m.valor == "SQLite"
    assert "SQLite" in m.resumen and "motivo" in m.resumen and len(m.resumen) <= 200
    assert m.fuente == "user" and m.task_id == "t1" and m.session_id == "s1" and m.paso == 5
    assert m.hash == hash_contenido(DECISION) and m.tokens == int(len(DECISION) / 3.7) + 1
    assert "decision" in m.tags and "base de datos" in m.entidades


def test_cambio_de_decision_del_dataset():
    m = _uno("user", CAMBIO)
    assert m.tipo == "decision" and m.importancia == 5
    assert m.entidad == "base de datos" and m.valor == "PostgreSQL"
    assert "SQLite → PostgreSQL" in m.resumen and "transacciones anidadas" in m.resumen


def test_restriccion_del_dataset():
    m = _uno("user", RESTRICCION)
    assert m.tipo == "restriccion" and m.importancia == 5 and m.nivel == 1
    assert m.resumen.startswith("nunca escribir fuera de src/")


def test_distractor_del_dataset_es_nota_imp_1():
    m = _uno("user", DISTRACTOR)
    assert m.tipo == "nota" and m.importancia == 1 and "distractor" in m.tags
    assert m.entidad == "" and m.valor == ""      # no compite con la decisión real


def test_objetivo_primer_mensaje():
    m = _uno("user", OBJETIVO, )
    assert m.tipo == "objetivo" and m.importancia == 5
    m2 = extraer("user", "Quiero que implementes el login con JWT y tests.", task_id="t", session_id="s", paso=9)
    assert [x.tipo for x in m2] == ["objetivo"]


def test_relleno_de_usuario_no_genera_nada():
    for t in ("ok", "dale", "seguí con pagos", "¿cómo va auth?", "continuá, no te frenes", "revisá que cache no rompa nada"):
        assert extraer("user", t, **K) == [], t


def test_relleno_de_asistente_no_genera_nada():
    for t in ("Entendido. Empiezo revisando la estructura y anotando cada decisión.",
              "Reviso el módulo pagos antes de tocar nada.",
              "Los tests de auth pasan; sigo con la siguiente subtarea.",
              "Ajusto el manejo de errores en cache y vuelvo a correr la suite.",
              "Anoto que envios depende de auth; lo tendré en cuenta al refactorizar.", ""):
        assert extraer("assistant", t, **K) == [], t


def test_solucion_del_dataset():
    m = _uno("assistant", SOLUCION)
    assert m.tipo == "solucion" and m.importancia == 4 and m.fuente == "assistant"
    assert m.resumen == "solución: comparar un datetime naive con uno aware"
    assert "UTC" in m.contenido


def test_decision_y_pendiente_del_asistente():
    d = _uno("assistant", "Decido: voy a usar httpx para el cliente HTTP, por async nativo.")
    assert d.tipo == "decision" and d.importancia == 4 and d.valor == "httpx" and d.entidad == "cliente http"
    p = _uno("assistant", "Queda pendiente migrar pagos/modelo.py al nuevo esquema; próximo paso: los tests.")
    assert p.tipo == "pendiente" and p.importancia == 3 and "pagos/modelo.py" in p.entidades


def test_error_de_tests_del_dataset():
    m = _uno("tool", ERROR, tool="tests")
    assert m.tipo == "error" and m.importancia == 4 and m.fuente == "tool:tests"
    assert m.resumen.startswith("FAILED tests/test_envios.py::test_fecha_limite") and "naive" in m.resumen
    assert "TypeError" in m.tags and "tests/test_envios.py" in m.entidades


def test_tests_ok_del_dataset():
    m = _uno("tool", "RESULTADO tests: rc=0 41 passed in 3.10s", tool="tests")
    assert m.tipo == "test" and m.importancia == 2 and m.resumen == "41 passed"
    # ok=False del arnés manda aunque el texto no lo diga
    e = _uno("tool", "RESULTADO ejecutar: nada", tool="ejecutar", ok=False)
    assert e.tipo == "error"


def test_fichero_con_funcion_del_dataset():
    ms = extraer("tool", FICHERO, tool="leer_archivo", **K)
    assert [m.tipo for m in ms] == ["fichero", "codigo"]
    f, c = ms
    assert f.importancia == 2 and f.entidad == "pagos/tarifas.py" and f.referencias == ["pagos/tarifas.py"]
    assert c.importancia == 3 and c.nivel == NIVEL_POR_TIPO["codigo"] == 4
    assert c.entidad == "calcular_recargo_417" and c.valor == "pagos/tarifas.py"
    assert c.contenido.startswith("def calcular_recargo_417(importe, tramo):")
    assert "9 %" in c.contenido and "1.50" in c.contenido and "round(importe * pct + fijo, 2)" in c.contenido
    assert c.referencias == ["pagos/tarifas.py"] and "calcular_recargo_417" in c.entidades
    assert "calcular_recargo_417" in c.resumen and len(c.resumen) <= 200


def test_extraer_simbolos_docstring_clase_y_metodo():
    s = extraer_simbolos(FICHERO)
    assert len(s) == 1 and s[0]["nombre"] == "calcular_recargo_417" and s[0]["fichero"] == "pagos/tarifas.py"
    assert s[0]["linea"] == 1 and s[0]["firma"] == "def calcular_recargo_417(importe, tramo)"
    assert s[0]["doc"].startswith("Calcula el recargo por tramo") and s[0]["doc"].endswith("Redondea a 2 decimales.")
    assert len(s[0]["cuerpo"]) == 3 and s[0]["clase"] == ""
    texto = ("RESULTADO leer_archivo auth/modelo.py:\n   1| import os\n   2| \n   3| class Usuario:\n"
             "   4|     \"\"\"Un usuario.\"\"\"\n   5|     def nombre(self) -> str:\n   6|         return self._n\n"
             "   7| \n   8| def obtener_auth_3(x):\n   9|     return x\n")
    s = extraer_simbolos(texto)
    assert [(d["nombre"], d["tipo"], d["clase"], d["linea"]) for d in s] == [
        ("Usuario", "class", "", 3), ("nombre", "def", "Usuario", 5), ("obtener_auth_3", "def", "", 8)]
    assert s[0]["doc"] == "Un usuario." and s[1]["doc"] == "" and s[1]["cuerpo"] == ["        return self._n"]
    assert extraer_simbolos("") == [] and extraer_simbolos("sin código") == []


def test_fichero_de_relleno_genera_codigo_por_cada_def():
    texto = ("RESULTADO leer_archivo cache/servicio.py:\n   1| def obtener_cache_4(x):\n   2|     return x.get('cache', 1)\n"
             "   3|     # TODO revisar cache\n   4| def validar_cache_9(x):\n   5|     if not x: raise ValueError('cache vacío')\n")
    ms = extraer("tool", texto, tool="leer_archivo", **K)
    assert [(m.tipo, m.entidad) for m in ms] == [("fichero", "cache/servicio.py"), ("codigo", "obtener_cache_4"),
                                                  ("codigo", "validar_cache_9")]


def test_listar_es_ruido_y_escribir_buscar_dan_memoria():
    assert extraer("tool", "RESULTADO listar pagos/:\npagos/modelo.py  300 B", tool="listar", **K) == []
    e = _uno("tool", "RESULTADO escribir_archivo src/nuevo.py: 12 líneas", tool="escribir_archivo", ok=True)
    assert e.tipo == "fichero" and e.importancia == 3 and e.resumen == "escrito src/nuevo.py" and e.entidad == "src/nuevo.py"
    h = _uno("tool", "RESULTADO buscar 'timezone':\n" + "x" * 500, tool="buscar")
    assert h.tipo == "hecho" and h.importancia == 2 and len(h.contenido) == 300
    assert extraer("tool", "RESULTADO desconocida: nada relevante", tool="desconocida", **K) == []
    assert extraer("tool", "Traceback (most recent call last):\n  File x", tool="desconocida", **K)[0].tipo == "error"


def test_nunca_lanza(monkeypatch, caplog):
    import cognia.memoria_larga.extraccion as ex

    def rompe(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(ex, "_de_usuario", rompe)
    with caplog.at_level(logging.WARNING):
        assert extraer("user", DECISION, **K) == []
    assert "falló" in caplog.text
    assert extraer("otro_rol", "texto", **K) == [] and extraer("user", None, **K) == []


def test_utilidades():
    assert normalizar_entidad("la Base de Datos") == "base de datos"
    assert normalizar_entidad("El planificador.") == "planificador"
    assert ficheros_en("toco pagos/modelo.py y tests/test_x.py, no README") == ["pagos/modelo.py", "tests/test_x.py"]
    assert len(recortar("a" * 500)) == 200 and recortar("a  b\n c") == "a b c"
    assert hash_contenido("Hola   Mundo") == hash_contenido("hola mundo")
