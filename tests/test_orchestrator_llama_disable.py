"""
Regresion A1 (2026-08-01): politica de deshabilitacion de llama.cpp.

Antes, un generate()==None en _local_infer deshabilitaba llama.cpp para TODA
la sesion (self._llama=None, sin reintento) aunque el fallo fuera un blip
transitorio (reset durante la carga del 14B, timeout por slot ocupado). Ahora
el orchestrator consulta server_state():
  - 'ok'/'cargando'/'in-process' -> el backend sigue vivo: degrada SOLO esa
    peticion y el proximo turno vuelve a intentar llama.cpp;
  - 'ausente' -> deshabilita, pero con _llama_checked=False para RE-SONDEAR
    en el turno siguiente (no queda muerto para siempre).

Mismo patron de construccion que tests/test_orchestrator_max_tokens.py:
orquestador real desde el manifest, backend llama reemplazado por un fake.
"""

from shattering.orchestrator import ShatteringOrchestrator

_MANIFEST = "shattering/manifests/cognia_desktop.json"


class _FakeLlamaFalla:
    """Facade fake: generate() devuelve None (fallo); server_state configurable."""

    def __init__(self, estado):
        self._estado = estado
        self.last_tokens_predicted = None
        self.last_stop_reason = None

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kwargs):
        return None

    def server_state(self):
        return self._estado


def _make_orch(estado):
    orch = ShatteringOrchestrator(manifest_path=_MANIFEST, max_new_tokens=8)
    orch._llama = _FakeLlamaFalla(estado)
    orch._llama_checked = True
    # Fallback numpy stubeado: el test mide la POLITICA de deshabilitacion,
    # no la inferencia por shards (que seria lenta y depende del disco).
    orch._shards_available = lambda: True
    orch._shard_infer = lambda prompt, **kwargs: ("fallback-numpy", 1)
    return orch


def test_server_vivo_no_se_deshabilita():
    """Blip con el server 'ok' (p.ej. timeout por slot ocupado): la peticion
    degrada a numpy pero llama.cpp queda habilitado para el proximo turno."""
    orch = _make_orch("ok")
    result = orch.infer("hola")
    assert result.text == "fallback-numpy"      # esta peticion si degrado
    assert orch._llama is not None              # pero el backend NO se apago
    assert orch._llama_checked is True


def test_server_cargando_no_se_deshabilita():
    """Reset durante la carga fria del 14B: 'cargando' no es 'ausente'."""
    orch = _make_orch("cargando")
    orch.infer("hola")
    assert orch._llama is not None


def test_server_ausente_se_deshabilita_pero_resondea():
    """Server realmente caido: se apaga llama.cpp, pero _llama_checked=False
    hace que el turno siguiente re-sondee/relance en vez de quedar muerto."""
    orch = _make_orch("ausente")
    orch.infer("hola")
    assert orch._llama is None
    assert orch._llama_checked is False


def test_impl_sin_server_state_se_deshabilita_como_antes():
    """Un impl viejo sin server_state() cae en 'ausente' (comportamiento
    conservador: igual al historico, pero con re-sondeo al turno siguiente)."""
    orch = ShatteringOrchestrator(manifest_path=_MANIFEST, max_new_tokens=8)

    class _Viejo:
        last_tokens_predicted = None
        last_stop_reason = None

        def generate(self, prompt, max_tokens=256, temperature=0.7, **kwargs):
            return None

    orch._llama = _Viejo()
    orch._llama_checked = True
    orch._shards_available = lambda: True
    orch._shard_infer = lambda prompt, **kwargs: ("fallback-numpy", 1)
    orch.infer("hola")
    assert orch._llama is None
    assert orch._llama_checked is False
