"""
tests/test_abstraction_engine.py
================================
Tests del motor de abstraccion (cognia/reasoning/abstraction_engine.py).

solve_by_abstraction se prueba con un orchestrator FAKE (doble de test, NO mock
de produccion): solo necesita .infer() devolviendo un objeto con .text, que es
por donde creative_generate habla con el backend. _parse_abstraction se prueba
directo sobre strings.
"""

import cognia.reasoning.abstraction_engine as ab


# ── _parse_abstraction ───────────────────────────────────────────────────────

_TRES_PARTES = (
    "FORMA ABSTRACTA: hay mas demanda de un recurso finito que oferta disponible\n"
    "SOLUCION ABSTRACTA: priorizar por valor y descartar o diferir lo de menor retorno\n"
    "SOLUCION CONCRETA: hacer primero las tareas de mayor impacto y delegar o posponer el resto\n"
)


def test_parse_tres_partes_bien_formadas():
    d = ab._parse_abstraction(_TRES_PARTES)
    assert set(d) == {"forma_abstracta", "solucion_abstracta", "solucion_concreta"}
    assert d["forma_abstracta"].startswith("hay mas demanda")
    assert d["solucion_abstracta"].startswith("priorizar por valor")
    assert d["solucion_concreta"].startswith("hacer primero las tareas")


def test_parse_claves_acentos_y_mayusculas():
    # Claves en mayus/minus mezcladas y con acentos: deben casar igual.
    text = (
        "Forma abstracta: un flujo se sobrecarga mas rapido de lo que se vacia\n"
        "Solución abstracta: regular la entrada o acelerar la salida\n"
        "SOLUCION CONCRETA: limitar lo que entra y procesar mas rapido lo pendiente\n"
    )
    d = ab._parse_abstraction(text)
    assert set(d) == {"forma_abstracta", "solucion_abstracta", "solucion_concreta"}
    assert d["solucion_concreta"].startswith("limitar lo que entra")


def test_parse_dos_puntos_interno_preservado():
    # Un ':' DENTRO de un valor (en linea de continuacion) no rompe el bloque:
    # esa linea no es una de nuestras claves, asi que se foldea al valor abierto.
    text = (
        "FORMA ABSTRACTA: un sistema acumula estado sin liberarlo\n"
        "SOLUCION ABSTRACTA: introducir un ciclo de limpieza periodico\n"
        "ejemplo: cada N pasos se purga lo viejo\n"
        "SOLUCION CONCRETA: agendar una rutina que descarte lo que ya no aporta\n"
    )
    d = ab._parse_abstraction(text)
    assert set(d) == {"forma_abstracta", "solucion_abstracta", "solucion_concreta"}
    # La linea 'ejemplo: ...' se preservo dentro de solucion_abstracta.
    assert "ejemplo: cada N pasos" in d["solucion_abstracta"]


def test_parse_clave_faltante_ausente_del_dict():
    # Falta SOLUCION CONCRETA: el dict trae solo las 2 que aparecieron.
    text = (
        "FORMA ABSTRACTA: dos partes compiten por el mismo cuello de botella\n"
        "SOLUCION ABSTRACTA: serializar el acceso o duplicar el recurso\n"
    )
    d = ab._parse_abstraction(text)
    assert set(d) == {"forma_abstracta", "solucion_abstracta"}
    assert "solucion_concreta" not in d


def test_parse_vacio():
    assert ab._parse_abstraction("") == {}
    assert ab._parse_abstraction("texto suelto sin estructura") == {}


# ── doble de test ────────────────────────────────────────────────────────────

class _FakeOrchestrator:
    """Doble de test: infer() devuelve objetos con .text segun una cola de payloads.

    Acepta un payload fijo (str) o una lista de payloads (uno por llamada). Cuando
    se agota la lista, repite el ultimo (sirve para 'siempre lo mismo').
    """

    class _R:
        def __init__(self, text):
            self.text = text

    def __init__(self, payloads):
        self._queue = [payloads] if isinstance(payloads, str) else list(payloads)
        self.calls = 0

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        self.calls += 1
        if not self._queue:
            return self._R("")
        text = self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]
        return self._R(text)


# ── solve_by_abstraction ─────────────────────────────────────────────────────

def test_solve_tres_partes_dict_completo():
    fake = _FakeOrchestrator(_TRES_PARTES)
    res = ab.solve_by_abstraction(fake, "no me alcanza el tiempo para todas mis tareas")
    assert res is not None
    assert set(res) == {"forma_abstracta", "solucion_abstracta", "solucion_concreta"}
    assert res["forma_abstracta"].startswith("hay mas demanda")
    assert res["solucion_concreta"].startswith("hacer primero las tareas")
    assert fake.calls == 1  # con las 3 partes a la 1a no hace falta reintento


def test_solve_reintento_rescata():
    # 1a generacion en server frio = basura; reintento devuelve las 3 partes.
    fake = _FakeOrchestrator(["ruido sin estructura alguna util", _TRES_PARTES])
    res = ab.solve_by_abstraction(fake, "problema con server frio")
    assert res is not None
    assert set(res) == {"forma_abstracta", "solucion_abstracta", "solucion_concreta"}
    assert fake.calls == 2  # generacion fallida + reintento


def test_solve_fallo_total_es_none():
    # El FAKE nunca devuelve las 3 partes -> None tras el reintento (honesto).
    fake = _FakeOrchestrator("nunca hay estructura completa en esta respuesta larga")
    res = ab.solve_by_abstraction(fake, "problema irresoluble para el fake")
    assert res is None


def test_solve_faltante_tras_retry_es_none():
    # Siempre falta SOLUCION CONCRETA, incluso tras el reintento -> None.
    incompleto = (
        "FORMA ABSTRACTA: dos partes compiten por el mismo cuello de botella\n"
        "SOLUCION ABSTRACTA: serializar el acceso o duplicar el recurso\n"
    )
    fake = _FakeOrchestrator(incompleto)
    res = ab.solve_by_abstraction(fake, "problema que nunca cierra el ciclo")
    assert res is None
    assert fake.calls == 2  # 1a + reintento, ambas incompletas


def test_solve_sin_orchestrator_es_none():
    assert ab.solve_by_abstraction(None, "cualquier problema") is None


def test_solve_problem_vacio_es_none():
    fake = _FakeOrchestrator(_TRES_PARTES)
    assert ab.solve_by_abstraction(fake, "   ") is None
    assert fake.calls == 0  # cortocircuito: no llama al backend
