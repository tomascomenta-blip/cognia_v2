"""
El corte que cae ANTES del primer frame tiene que VERSE.

Al cancelar durante el prefill, el cliente no recibio ni un frame: `usage`
vuelve vacio entero. El presupuesto cobraba 0 —correcto, no hay numero que
cobrar— pero ademas `sin_prompt()`, el contador que EXISTE para declarar ese
agujero, tampoco ticaba: pedia `completion and not prompt`, o sea que el caso
donde el agujero es el 100% de la llamada era el unico invisible.

Medido en la corrida que lo destapo: el server prefilleo 6.869 tokens reales,
`gastado()` = 0 y `sin_prompt()` = 0. La unica constancia era una linea de
journal con `usage_desconocido=true`.

Y la eviccion del anillo de estados tiraba los mensajes encolados sin dejar
rastro, contra el invariante que el resto del modulo respeta: un mensaje
descartado en silencio es peor que uno rechazado a la vista.
"""

from cognia.agent.workflows import ControlCorrida, PresupuestoTokens


class TestElCorteEnPrefillSeVe:

    def test_un_usage_vacio_tica_el_contador_del_agujero(self):
        p = PresupuestoTokens(total=1000)
        p.registrar({})                      # el corte durante el prefill
        assert p.gastado() == 0, "no hay numero que cobrar, y esta bien"
        assert p.sin_prompt() == 1, (
            "la llamada se hizo y el prompt no se conto: tiene que verse")

    def test_el_corte_con_generacion_sigue_ticando(self):
        p = PresupuestoTokens(total=1000)
        p.registrar({"completion_tokens": 132}, estimado=True)
        assert p.gastado() == 132
        assert p.estimados() == 132
        assert p.sin_prompt() == 1

    def test_una_llamada_completa_no_tica_el_agujero(self):
        p = PresupuestoTokens(total=1000)
        p.registrar({"prompt_tokens": 43, "completion_tokens": 34})
        assert p.gastado() == 77
        assert p.estimados() == 0
        assert p.sin_prompt() == 0, "aca no falta nada: el agujero es cero"

    def test_varios_cortes_se_acumulan(self):
        p = PresupuestoTokens(total=1000)
        for _ in range(3):
            p.registrar({})
        assert p.sin_prompt() == 3


class TestLaEviccionNoTiraMensajesEnSilencio:

    def test_el_buzon_evictado_se_puede_drenar(self, monkeypatch):
        import cognia.agent.workflows as W
        monkeypatch.setattr(W, "_MAX_ESTADOS", 2)
        c = ControlCorrida()
        c.nace("a1")
        c.encolar("a1", "esto no lo lee nadie")
        c.nace("a2")
        c.nace("a3")                     # a1 se cae del anillo

        fuera = c.drenar_evictados()
        assert fuera == [("a1", "esto no lo lee nadie")], (
            f"el mensaje se perdio en silencio: {fuera!r}")
        assert c.drenar_evictados() == [], "drenar vacia"

    def test_sin_eviccion_no_hay_nada_que_drenar(self):
        c = ControlCorrida()
        c.nace("a1")
        c.encolar("a1", "hola")
        assert c.drenar_evictados() == []
