"""
El trabajo YA PAGADO no se tira cuando la corrida falla despues.

El adaptador conserva el texto consolidado de los pasos que si salieron aunque
una etapa posterior reviente (el caso real: `criticar()` explota tras 2 pasos
OK, con 30 tokens ya gastados). Pero los DOS consumidores hacian

    if not res["ok"]: return / print(res["error"])

sin mirar `res["texto"]`, asi que el arreglo del adaptador era condicion
necesaria y no suficiente: el usuario veia solo el error y el modelo recibia
solo "ERROR" — y volvia a pedir el mismo trabajo que ya se habia pagado.

Es el mismo argumento por el que el envelope conserva 'critica': un veredicto
pagado con 3 llamadas al LLM no lo puede borrar una excepcion posterior.
"""

import cognia.cli as C
from cognia.harness import tools_harness as TH


# Envelope tal como lo devuelve workflows_adapter.ejecutar() cuando la corrida
# falla DESPUES de resolver pasos: ok=False, error puesto, y texto/pasos/tokens
# con lo que si se pago.
FALLO_CON_PAGADO = {
    "ok": False,
    "error": "el workflow fallo: el critico exploto",
    "texto": "--- paso 1: uno\nRESULTADO REAL del paso: uno\n(2 pasos completados)",
    "pasos": 2,
    "tokens": 30,
    "critica": None,
    "run_id": "20260817-000000-test",
}

FALLO_SIN_NADA = dict(FALLO_CON_PAGADO, texto="", pasos=0, tokens=0,
                      error="no encontre subtareas")


class TestElReplMuestraLoPagado:

    def test_el_texto_pagado_se_muestra_pese_al_error(self, monkeypatch):
        lineas, respuestas = [], []
        monkeypatch.setattr(C, "_print_line", lambda s, *a, **k: lineas.append(str(s)))
        monkeypatch.setattr(C, "_show_response", lambda t, *a, **k: respuestas.append(t))

        import cognia.harness.workflows_adapter as WA
        monkeypatch.setattr(WA, "ejecutar", lambda *a, **k: FALLO_CON_PAGADO)
        monkeypatch.setattr(WA, "partir_pasos", lambda s: ["uno", "dos"])

        C._slash_workflow("uno; dos")

        texto = "\n".join(lineas)
        assert "el critico exploto" in texto, "el error tiene que seguir viendose"
        assert respuestas and "2 pasos completados" in respuestas[0], (
            f"el texto pagado no se mostro; lineas={lineas!r}")
        assert "30 tokens" in texto, "hay que decir cuanto se pago"

    def test_un_fallo_sin_nada_pagado_no_inventa_un_bloque_vacio(self, monkeypatch):
        lineas, respuestas = [], []
        monkeypatch.setattr(C, "_print_line", lambda s, *a, **k: lineas.append(str(s)))
        monkeypatch.setattr(C, "_show_response", lambda t, *a, **k: respuestas.append(t))

        import cognia.harness.workflows_adapter as WA
        monkeypatch.setattr(WA, "ejecutar", lambda *a, **k: FALLO_SIN_NADA)
        monkeypatch.setattr(WA, "partir_pasos", lambda s: ["uno"])

        C._slash_workflow("uno")

        assert not respuestas, "sin texto pagado no se abre ningun bloque"
        assert "lo que si se resolvio" not in "\n".join(lineas)


class TestLaToolDevuelveLoPagado:

    def test_el_modelo_recibe_lo_ya_resuelto(self, monkeypatch):
        monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: FALLO_CON_PAGADO)
        salida = TH._workflow("uno; dos", {})

        assert "ERROR" in salida, "el fallo tiene que seguir declarandose"
        assert "2 pasos completados" in salida, (
            f"el modelo no recibio el trabajo pagado: {salida!r}")
        assert "30 tokens" in salida

    def test_sin_texto_la_salida_es_la_de_siempre(self, monkeypatch):
        monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: FALLO_SIN_NADA)
        salida = TH._workflow("uno", {})

        assert salida == "RESULTADO workflow ERROR: no encontre subtareas"

    def test_el_camino_feliz_no_cambio(self, monkeypatch):
        ok = {"ok": True, "texto": "resultado", "pasos": 2, "tokens": 30,
              "run_id": "r1", "error": "", "critica": None}
        monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: ok)
        salida = TH._workflow("uno; dos", {})

        assert salida.startswith("RESULTADO workflow (2 pasos, 30 tokens, corrida r1)")
        assert "ERROR" not in salida
