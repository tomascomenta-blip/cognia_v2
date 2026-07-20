"""
tests/test_transfer_engine.py
=============================
Tests del motor de transferencia de conocimiento (cognia/reasoning/transfer_engine.py).

transfer_principle se prueba con un orchestrator FAKE (doble de test, NO mock de
produccion): solo necesita .infer() devolviendo un objeto con .text, que es por
donde creative_generate habla con el backend. _parse_transfer se prueba directo
sobre strings.
"""

import cognia.reasoning.transfer_engine as tr


# ── _parse_transfer ──────────────────────────────────────────────────────────

_DOS_PARTES = (
    "PRINCIPIO: una senal indirecta refuerza los caminos que mas se usan y se evapora en los que no\n"
    "APLICACION: marcar cada ruta de red con un peso que sube al usarse y decae con el tiempo\n"
)


def test_parse_dos_partes_bien_formadas():
    d = tr._parse_transfer(_DOS_PARTES)
    assert set(d) == {"principio", "aplicacion"}
    assert d["principio"].startswith("una senal indirecta")
    assert d["aplicacion"].startswith("marcar cada ruta")


def test_parse_claves_acentos_y_mayusculas():
    # Claves en mayus/minus mezcladas y con acentos: deben casar igual.
    text = (
        "Principio: el sistema se autoorganiza por retroalimentacion positiva local\n"
        "Aplicación: dejar que cada nodo ajuste su comportamiento segun sus vecinos\n"
    )
    d = tr._parse_transfer(text)
    assert set(d) == {"principio", "aplicacion"}
    assert d["aplicacion"].startswith("dejar que cada nodo")


def test_parse_dos_puntos_interno_preservado():
    # Un ':' DENTRO de un valor (en linea de continuacion) no rompe el bloque:
    # esa linea no es una de nuestras claves, asi que se foldea al valor abierto.
    text = (
        "PRINCIPIO: la redundancia tolera fallos\n"
        "clave: cada parte puede sustituir a otra\n"
        "APLICACION: replicar los datos en varios nodos\n"
    )
    d = tr._parse_transfer(text)
    assert set(d) == {"principio", "aplicacion"}
    # La linea 'clave: ...' se preservo dentro de principio.
    assert "clave: cada parte" in d["principio"]


def test_parse_clave_faltante_ausente_del_dict():
    # Falta APLICACION: el dict trae solo la que aparecio.
    text = (
        "PRINCIPIO: separar la politica del mecanismo\n"
    )
    d = tr._parse_transfer(text)
    assert set(d) == {"principio"}
    assert "aplicacion" not in d


def test_parse_vacio():
    assert tr._parse_transfer("") == {}
    assert tr._parse_transfer("texto suelto sin estructura") == {}


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


# ── transfer_principle ───────────────────────────────────────────────────────

def test_transfer_dos_partes_dict_completo():
    fake = _FakeOrchestrator(_DOS_PARTES)
    res = tr.transfer_principle(
        fake, "como las hormigas encuentran el camino mas corto",
        "como rutear paquetes en una red")
    assert res is not None
    assert set(res) == {"principio", "aplicacion"}
    assert res["principio"].startswith("una senal indirecta")
    assert res["aplicacion"].startswith("marcar cada ruta")
    assert fake.calls == 1  # con las 2 partes a la 1a no hace falta reintento


def test_transfer_reintento_rescata():
    # 1a generacion en server frio = basura; reintento devuelve las 2 partes.
    fake = _FakeOrchestrator(["ruido sin estructura alguna util", _DOS_PARTES])
    res = tr.transfer_principle(fake, "fuente con server frio", "objetivo cualquiera")
    assert res is not None
    assert set(res) == {"principio", "aplicacion"}
    assert fake.calls == 2  # generacion fallida + reintento


def test_transfer_fallo_total_es_none():
    # El FAKE nunca devuelve las 2 partes -> None tras el reintento (honesto).
    fake = _FakeOrchestrator("nunca hay estructura completa en esta respuesta larga")
    res = tr.transfer_principle(fake, "fuente irresoluble", "objetivo irresoluble")
    assert res is None


def test_transfer_faltante_tras_retry_es_none():
    # Siempre falta APLICACION, incluso tras el reintento -> None.
    incompleto = (
        "PRINCIPIO: separar la politica del mecanismo\n"
    )
    fake = _FakeOrchestrator(incompleto)
    res = tr.transfer_principle(fake, "fuente que no cierra", "objetivo que no cierra")
    assert res is None
    assert fake.calls == 2  # 1a + reintento, ambas incompletas


def test_transfer_sin_orchestrator_es_none():
    assert tr.transfer_principle(None, "una fuente", "un objetivo") is None


def test_transfer_source_vacio_es_none():
    fake = _FakeOrchestrator(_DOS_PARTES)
    assert tr.transfer_principle(fake, "   ", "un objetivo") is None
    assert fake.calls == 0  # cortocircuito: no llama al backend


def test_transfer_target_vacio_es_none():
    fake = _FakeOrchestrator(_DOS_PARTES)
    assert tr.transfer_principle(fake, "una fuente", "   ") is None
    assert fake.calls == 0  # cortocircuito: no llama al backend
