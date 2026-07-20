"""
tests/test_idea_eval.py
=======================
Tests de la autoevaluacion de novedad (cognia/reasoning/idea_eval.py).

evaluate_idea / rank_ideas se prueban con un orchestrator FAKE (doble de test,
NO mock de produccion): solo necesita .infer() devolviendo un objeto con .text,
que es por donde creative_generate habla con el backend. _parse_axes se prueba
directo sobre strings.
"""

import cognia.reasoning.idea_eval as ie


# ── _parse_axes ─────────────────────────────────────────────────────────────

def test_parse_axes_formato_exacto():
    text = "novedad: 0.7\nfactibilidad: 0.5\nimpacto: 0.8"
    assert ie._parse_axes(text) == {"novedad": 0.7, "factibilidad": 0.5, "impacto": 0.8}


def test_parse_axes_coma_decimal():
    text = "novedad: 0,6\nfactibilidad: 0,4\nimpacto: 0,9"
    assert ie._parse_axes(text) == {"novedad": 0.6, "factibilidad": 0.4, "impacto": 0.9}


def test_parse_axes_mayusculas_y_acentos_ausentes():
    # NOVEDAD en mayuscula; el modelo escribe sin acentos (ya es asi) -> casa igual.
    text = "NOVEDAD: 0.3\nFactibilidad = 0.2\nImpacto - 0.1"
    assert ie._parse_axes(text) == {"novedad": 0.3, "factibilidad": 0.2, "impacto": 0.1}


def test_parse_axes_separador_igual():
    text = "novedad=0.5\nfactibilidad=0.6\nimpacto=0.7"
    assert ie._parse_axes(text) == {"novedad": 0.5, "factibilidad": 0.6, "impacto": 0.7}


def test_parse_axes_punto_decimal_sin_cero():
    text = "novedad: .7\nfactibilidad: 1\nimpacto: .25"
    assert ie._parse_axes(text) == {"novedad": 0.7, "factibilidad": 1.0, "impacto": 0.25}


def test_parse_axes_eje_faltante_no_aparece():
    text = "novedad: 0.4\nimpacto: 0.6"
    parsed = ie._parse_axes(text)
    assert parsed == {"novedad": 0.4, "impacto": 0.6}
    assert "factibilidad" not in parsed


def test_parse_axes_valor_fuera_de_rango_clampeado():
    text = "novedad: 1\nfactibilidad: 0\nimpacto: 0.99"
    # El regex acota 0-1, pero validamos el clamp explicito de igual modo.
    parsed = ie._parse_axes(text)
    assert parsed["novedad"] == 1.0
    assert parsed["factibilidad"] == 0.0


def test_parse_axes_vacio():
    assert ie._parse_axes("") == {}
    assert ie._parse_axes("sin numeros aqui") == {}


# ── doble de test ────────────────────────────────────────────────────────────

class _FakeOrchestrator:
    """Doble de test: infer() devuelve objetos con .text segun una cola de payloads.

    Acepta un payload fijo (str) o una lista de payloads (uno por llamada). Cuando
    se agota la lista, repite el ultimo (sirve para 'siempre vacio').
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


# ── evaluate_idea ────────────────────────────────────────────────────────────

def test_evaluate_idea_producto_correcto():
    fake = _FakeOrchestrator("novedad: 0.5\nfactibilidad: 0.4\nimpacto: 0.5")
    res = ie.evaluate_idea(fake, "una idea cualquiera")
    assert res["novedad"] == 0.5
    assert res["factibilidad"] == 0.4
    assert res["impacto"] == 0.5
    # value = 0.5 * 0.4 * 0.5 = 0.1
    assert res["value"] == 0.1


def test_evaluate_idea_reintento_rescata():
    # 1a llamada vacia (server frio), 2a completa -> debe evaluar bien.
    fake = _FakeOrchestrator(["", "novedad: 0.8\nfactibilidad: 0.5\nimpacto: 0.5"])
    res = ie.evaluate_idea(fake, "idea con server frio")
    assert fake.calls == 2  # hubo reintento
    assert res["novedad"] == 0.8
    # value = 0.8 * 0.5 * 0.5 = 0.2
    assert res["value"] == 0.2


def test_evaluate_idea_reintento_parcial_completa_default():
    # 1a da solo novedad, 2a aporta factibilidad; impacto nunca aparece -> default 0.5.
    # (Los payloads pasan el largo minimo de creative_generate, >=15 chars.)
    fake = _FakeOrchestrator(["el eje novedad: 0.6", "la factibilidad: 0.4"])
    res = ie.evaluate_idea(fake, "idea parcial")
    assert res["novedad"] == 0.6
    assert res["factibilidad"] == 0.4
    assert res["impacto"] == 0.5            # eje faltante -> default 0.5
    # value = 0.6 * 0.4 * 0.5 = 0.12
    assert res["value"] == 0.12


def test_evaluate_idea_fallo_total_es_none():
    # El FAKE nunca devuelve ejes -> None (honesto), tras el reintento.
    fake = _FakeOrchestrator("no hay numeros utiles en esta respuesta")
    assert ie.evaluate_idea(fake, "idea sin evaluar") is None
    assert fake.calls == 2  # se reintento antes de rendirse


def test_evaluate_idea_sin_orchestrator_es_none():
    assert ie.evaluate_idea(None, "idea") is None


def test_evaluate_idea_idea_vacia_es_none():
    fake = _FakeOrchestrator("novedad: 0.5\nfactibilidad: 0.5\nimpacto: 0.5")
    assert ie.evaluate_idea(fake, "   ") is None
    assert fake.calls == 0  # cortocircuito: no llama al backend


# ── rank_ideas ───────────────────────────────────────────────────────────────

class _PerIdeaOrchestrator:
    """Doble de test: mapea cada idea (por substring) a una respuesta de ejes."""

    class _R:
        def __init__(self, text):
            self.text = text

    def __init__(self, mapping):
        self._mapping = mapping

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        for key, payload in self._mapping.items():
            if key in prompt:
                return self._R(payload)
        return self._R("")  # sin match -> respuesta vacia -> evalua None


def test_rank_ideas_orden_desc_y_none_al_final():
    mapping = {
        "alta":  "novedad: 0.9\nfactibilidad: 0.9\nimpacto: 0.9",   # value 0.729
        "media": "novedad: 0.5\nfactibilidad: 0.5\nimpacto: 0.5",   # value 0.125
        "nula":  "no se puede evaluar esto",                         # -> None
    }
    fake = _PerIdeaOrchestrator(mapping)
    ranked = ie.rank_ideas(fake, ["idea media", "idea alta", "idea nula"])
    assert [r["idea"] for r in ranked] == ["idea alta", "idea media", "idea nula"]
    assert ranked[0]["value"] == 0.729
    assert ranked[1]["value"] == 0.125
    assert ranked[-1]["value"] is None       # la None va al final, marcada


def test_rank_ideas_trunca_a_8():
    # 10 ideas -> evalua solo 8 y lo marca; no se silencia el truncado.
    fake = _FakeOrchestrator("novedad: 0.5\nfactibilidad: 0.5\nimpacto: 0.5")
    ideas = [f"idea {i}" for i in range(10)]
    ranked = ie.rank_ideas(fake, ideas)
    assert len(ranked) == 8
    assert all(r.get("truncated") for r in ranked)
