"""
tests/test_investigate.py
=========================
Tests del loop /investigar (Cognia.investigate). El metodo encadena 4 piezas
creativas que TODAS tocan el LLM vivo, asi que no se puede ejercitar end-to-end
sin backend (eso lo hace el manager via CLI). Lo testeable SIN modelo es la
LOGICA DE COMPOSICION, que esta extraida a dos funciones puras de modulo en
cognia/cognia.py:

  - _rank_hypotheses: ordena por value desc dejando las None al final.
  - _render_investigation: arma el reporte ASCII a partir de datos ya calculados.

Aca se prueban esas dos: ranking (value desc, None al final, desempate por
plausibility) y render honesto (value None / analogias vacias / experimento no
ejecutable / hipotesis vacias). Sin mocks de produccion, sin LLM.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.cognia import _rank_hypotheses, _render_investigation


# ── _rank_hypotheses ─────────────────────────────────────────────────────────

class TestRankHypotheses:
    def test_ordena_por_value_desc(self):
        hyps = [
            {"hypothesis": "A", "plausibility": 0.5, "value": 0.10},
            {"hypothesis": "B", "plausibility": 0.5, "value": 0.40},
            {"hypothesis": "C", "plausibility": 0.5, "value": 0.25},
        ]
        ranked = _rank_hypotheses(hyps)
        assert [h["hypothesis"] for h in ranked] == ["B", "C", "A"]

    def test_value_none_va_al_final(self):
        # Las que no se pudieron evaluar (value None) quedan SIEMPRE despues de
        # las puntuadas, aunque su plausibility sea alta.
        hyps = [
            {"hypothesis": "sin-eval", "plausibility": 0.99, "value": None},
            {"hypothesis": "baja", "plausibility": 0.1, "value": 0.05},
            {"hypothesis": "alta", "plausibility": 0.2, "value": 0.30},
        ]
        ranked = _rank_hypotheses(hyps)
        assert [h["hypothesis"] for h in ranked] == ["alta", "baja", "sin-eval"]
        # La None es la ultima, no importa su plausibility alta.
        assert ranked[-1]["hypothesis"] == "sin-eval"

    def test_todas_none_desempata_por_plausibility(self):
        # Si NINGUNA se pudo evaluar (todas value None), el orden cae a
        # plausibility desc (el mejor proxy disponible).
        hyps = [
            {"hypothesis": "p3", "plausibility": 0.3, "value": None},
            {"hypothesis": "p9", "plausibility": 0.9, "value": None},
            {"hypothesis": "p6", "plausibility": 0.6, "value": None},
        ]
        ranked = _rank_hypotheses(hyps)
        assert [h["hypothesis"] for h in ranked] == ["p9", "p6", "p3"]

    def test_lista_vacia_no_rompe(self):
        assert _rank_hypotheses([]) == []
        assert _rank_hypotheses(None) == []

    def test_no_muta_la_entrada(self):
        hyps = [
            {"hypothesis": "A", "plausibility": 0.5, "value": 0.1},
            {"hypothesis": "B", "plausibility": 0.5, "value": 0.9},
        ]
        original = list(hyps)
        _rank_hypotheses(hyps)
        # La lista de entrada conserva su orden (sorted() devuelve una nueva).
        assert hyps == original


# ── _render_investigation ────────────────────────────────────────────────────

class TestRenderInvestigation:
    def _hyps_ok(self):
        return [
            {"hypothesis": "regar de noche", "plausibility": 0.70, "value": 0.30},
            {"hypothesis": "reusar agua gris", "plausibility": 0.60, "value": 0.45},
        ]

    def test_header_y_orden_por_valor(self):
        out = _render_investigation("ahorrar agua", self._hyps_ok(), [], None)
        assert out.startswith("INVESTIGACION: ahorrar agua")
        # La de mayor value (0.45) sale como "1." antes que la de 0.30.
        lineas = out.splitlines()
        idx_45 = next(i for i, l in enumerate(lineas) if "reusar agua gris" in l)
        idx_30 = next(i for i, l in enumerate(lineas) if "regar de noche" in l)
        assert idx_45 < idx_30
        assert "1. [valor 0.45 | plaus 0.60] reusar agua gris" in out

    def test_value_none_se_muestra_sin_evaluar(self):
        hyps = [
            {"hypothesis": "idea evaluada", "plausibility": 0.5, "value": 0.20},
            {"hypothesis": "idea sin medir", "plausibility": 0.8, "value": None},
        ]
        out = _render_investigation("X", hyps, [], None)
        # La None se renderiza honesta como "[sin evaluar | plaus ...]" y va al final.
        assert "[sin evaluar | plaus 0.80] idea sin medir" in out
        assert "[valor 0.20 | plaus 0.50] idea evaluada" in out
        # Orden: la evaluada (1.) antes que la sin evaluar (2.).
        assert out.index("idea evaluada") < out.index("idea sin medir")

    def test_sin_hipotesis_mensaje_honesto(self):
        out = _render_investigation("X", [], [], None)
        assert "(no se generaron hipotesis)" in out

    def test_analogias_vacias_mensaje_honesto(self):
        out = _render_investigation("X", self._hyps_ok(), [], None)
        assert "Analogias para enmarcar el problema:" in out
        assert "(sin analogias)" in out

    def test_analogias_se_renderizan_por_dominio(self):
        analogias = [
            {"dominio": "biologia", "analogia": "...", "solucion": "...",
             "adaptacion": "imitar la transpiracion de las plantas"},
            {"dominio": "logistica", "analogia": "...", "solucion": "...",
             "adaptacion": "ruteo de agua como ruteo de paquetes"},
        ]
        out = _render_investigation("X", self._hyps_ok(), analogias, None)
        assert "[biologia] imitar la transpiracion de las plantas" in out
        assert "[logistica] ruteo de agua como ruteo de paquetes" in out

    def test_experimento_no_ejecutable_mensaje_honesto(self):
        exp = {"executed": False, "reason": "el modelo no produjo codigo ejecutable"}
        out = _render_investigation("X", self._hyps_ok(), [], exp)
        assert "Validacion empirica de la hipotesis top:" in out
        assert "no ejecutable: el modelo no produjo codigo ejecutable" in out

    def test_experimento_none_se_trata_como_no_ejecutable(self):
        out = _render_investigation("X", self._hyps_ok(), [], None)
        assert "no ejecutable:" in out

    def test_experimento_ejecutado_muestra_veredicto(self):
        exp = {"executed": True, "success": True, "verdict": "PASS"}
        out = _render_investigation("X", self._hyps_ok(), [], exp)
        assert "VEREDICTO: PASS" in out
        assert "no ejecutable" not in out

    def test_salida_es_ascii_puro(self):
        # Regla dura del repo: CLI/prints ASCII puro (CP1252). El render no debe
        # introducir caracteres fuera de ASCII por su cuenta.
        analogias = [{"dominio": "fisica", "adaptacion": "difusion de calor"}]
        exp = {"executed": True, "verdict": "FAIL"}
        out = _render_investigation("ahorrar agua", self._hyps_ok(), analogias, exp)
        out.encode("ascii")  # lanza si hay algun no-ASCII
