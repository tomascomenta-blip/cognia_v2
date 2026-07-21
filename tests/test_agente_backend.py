"""
Regresion: el bucle del agente no llegaba al backend que si funcionaba.

Medido el 2026-07-20 corriendo una tarea real. El orquestador busca shards del
modelo o un Ollama, y en esta maquina no hay ninguno de los dos: el backend
real es el llama-server que `llm_local` SI detecta. Es exactamente el fallo que
documenta `cognia/llm_local.py` — modulos que degradan en silencio porque
tienen cableado un backend que no existe — y el bucle del agente se habia
quedado fuera de aquel arreglo.

Lo agravaba que el orquestador **no lanza excepcion**: devuelve el aviso
"[QWEN-CODER] No inference backend available..." como si fuera la respuesta del
modelo. El try/except no saltaba, el bucle tomaba el error por respuesta y
pedia dos pasos mas cada vez. Resultado medido: **40 pasos identicos** sin
producir nada.

Con el arreglo, la misma tarea se resolvio en 3 pasos y el agente uso por su
cuenta la herramienta MCP nueva.
"""

import pytest

from cognia.cli import _SIN_BACKEND, _inferir_para_agente


class _Orq:
    """Orquestador de mentira: devuelve lo que se le diga."""

    def __init__(self, texto):
        self._texto = texto

    def infer(self, prompt, **kw):
        return type("R", (), {"text": self._texto})()


class _OrqRoto:
    def infer(self, prompt, **kw):
        raise RuntimeError("shards no encontrados")


class TestCaidaALlmLocal:

    def test_usa_el_orquestador_cuando_responde_bien(self, monkeypatch):
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "NO DEBERIA LLAMARSE")
        salida = _inferir_para_agente(_Orq("ACCION: listar ."), "prompt")
        assert salida == "ACCION: listar ."

    @pytest.mark.parametrize("aviso", [
        "[QWEN-CODER] No inference backend available. Run the setup wizard...",
        "No inference backend available",
        "Run the setup wizard to download model shards",
    ])
    def test_cae_a_llm_local_si_no_hay_backend(self, aviso, monkeypatch):
        """El aviso llega como TEXTO, no como excepcion: por eso hay que mirarlo."""
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "ACCION: buscar_en_repo a b c")

        salida = _inferir_para_agente(_Orq(aviso), "prompt")
        assert salida == "ACCION: buscar_en_repo a b c"

    def test_cae_a_llm_local_si_el_orquestador_revienta(self, monkeypatch):
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "ACCION: responder ok")
        assert _inferir_para_agente(_OrqRoto(), "prompt") == "ACCION: responder ok"

    def test_orquestador_vacio_tambien_cae(self, monkeypatch):
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "ACCION: responder ok")
        assert _inferir_para_agente(_Orq(""), "prompt") == "ACCION: responder ok"


class TestSinNingunBackend:

    def test_devuelve_vacio_para_que_el_bucle_pueda_parar(self, monkeypatch):
        """
        Si no hay de donde inferir, hay que decirlo con "" en vez de devolver
        el aviso: es lo que permite al bucle cortar en vez de encadenar 40
        pasos identicos pidiendo mas presupuesto.
        """
        monkeypatch.setattr("cognia.llm_local.generar", lambda *a, **k: None)
        assert _inferir_para_agente(_Orq("No inference backend available"), "p") == ""

    def test_nunca_devuelve_el_aviso_como_si_fuera_respuesta(self, monkeypatch):
        monkeypatch.setattr("cognia.llm_local.generar", lambda *a, **k: "")
        salida = _inferir_para_agente(_Orq("[QWEN-CODER] No inference backend"), "p")

        for marca in _SIN_BACKEND:
            assert marca not in salida


def test_las_marcas_cubren_el_mensaje_real():
    """El texto exacto que se midio en la maquina del dueno."""
    real = ("[QWEN-CODER] No inference backend available. Run the setup wizard "
            "to download model shards, or start Ollama: ollama serve")
    assert any(marca in real for marca in _SIN_BACKEND)


class TestNoConcedePasosSobreUnFalloDeBackend:
    """
    `wants_more_steps` sacaba un digito a la brava del texto del orquestador,
    incluido su aviso de "no hay backend" — que no es una excepcion sino una
    respuesta normal. Asi concedia pasos extra sobre un fallo que no se iba a
    arreglar solo.
    """

    def test_sin_backend_no_concede_pasos(self):
        from cognia.agent.loop import wants_more_steps

        extra = wants_more_steps("tarea", "progreso", _Orq("no importa"),
                                 inferir=lambda orch, p: "")
        assert extra == 0

    def test_con_backend_respeta_lo_que_diga_el_modelo(self):
        from cognia.agent.loop import wants_more_steps

        extra = wants_more_steps("tarea", "progreso", _Orq("x"),
                                 inferir=lambda orch, p: "necesito 3 pasos mas")
        assert extra == 3

    def test_tarea_terminada_no_pide_mas(self):
        from cognia.agent.loop import wants_more_steps

        extra = wants_more_steps("tarea", "progreso", _Orq("x"),
                                 inferir=lambda orch, p: "0")
        assert extra == 0

    def test_sin_inferir_sigue_funcionando_como_antes(self):
        """Compatibilidad: quien no pase `inferir` usa el orquestador."""
        from cognia.agent.loop import wants_more_steps

        assert wants_more_steps("t", "p", _Orq("necesita 4 pasos")) == 4


class TestElOrquestadorCaeALlmLocal:
    """
    El arreglo de raiz: en vez de parchear los ~12 sitios que llaman a
    orch.infer(), el orquestador pregunta a llm_local antes de declarar que no
    hay backend. Ollama no es el unico posible, y en esta maquina el que existe
    es el llama-server que llm_local SI detecta.
    """

    def _orquestador(self):
        """Instancia pelada: solo hace falta el camino de inferencia."""
        from shattering.orchestrator import ShatteringOrchestrator
        o = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        o._ollama_model = 'modelo-de-prueba'   # lo usa _unavailable_response
        return o

    def test_usa_llm_local_si_ollama_no_responde(self, monkeypatch):
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "", raising=False)
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "respuesta real del modelo")

        salida = o._ollama_infer("prompt", "techne")
        assert salida == "respuesta real del modelo"
        assert "No inference backend" not in salida

    def test_si_ollama_responde_no_se_toca_nada(self, monkeypatch):
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "respuesta de ollama", raising=False)
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "NO DEBERIA LLAMARSE")

        assert o._ollama_infer("prompt", "techne") == "respuesta de ollama"

    def test_sin_ninguno_sigue_avisando_con_claridad(self, monkeypatch):
        """Si de verdad no hay backend, hay que decirlo, no inventar."""
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "", raising=False)
        monkeypatch.setattr(o, "_shards_available",
                            lambda: False, raising=False)
        monkeypatch.setattr("cognia.llm_local.generar", lambda *a, **k: None)

        assert "No inference backend available" in o._ollama_infer("p", "techne")

    def test_un_llm_local_roto_no_rompe_el_orquestador(self, monkeypatch):
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "", raising=False)
        monkeypatch.setattr(o, "_shards_available",
                            lambda: False, raising=False)
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("sin red")))

        assert "No inference backend available" in o._ollama_infer("p", "techne")


class TestElRefinadoTambienTieneRespaldo:
    """
    En modo calidad (n_passes >= 2) el orquestador refina su propia respuesta.
    Ese segundo paso usaba SOLO Ollama, asi que en una maquina sin Ollama el
    refinado sencillamente no ocurria — y nadie se enteraba, porque cuando el
    refinado sale vacio se conserva el texto original. Degradacion silenciosa
    de la misma familia, a menor escala.
    """

    def _orquestador(self):
        from shattering.orchestrator import ShatteringOrchestrator
        o = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        o._ollama_model = "modelo-de-prueba"
        return o

    def test_el_respaldo_esta_en_un_solo_sitio(self):
        """Duplicarlo en dos ramas es como se desincronizan."""
        import inspect

        from shattering.orchestrator import ShatteringOrchestrator
        fuente = inspect.getsource(ShatteringOrchestrator._ollama_infer)
        assert fuente.count("_generar_con_respaldo") == 2, (
            "la generacion y el refinado deben usar el mismo camino")
        assert "from cognia.llm_local import" not in fuente, (
            "el respaldo vive en el helper, no repetido aqui")

    def test_el_helper_cae_a_llm_local(self, monkeypatch):
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "", raising=False)
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "texto del respaldo")

        assert o._generar_con_respaldo("p", "techne") == "texto del respaldo"

    def test_el_helper_no_molesta_si_ollama_responde(self, monkeypatch):
        o = self._orquestador()
        monkeypatch.setattr(o, "_call_ollama_domain",
                            lambda p, s: "de ollama", raising=False)
        monkeypatch.setattr("cognia.llm_local.generar",
                            lambda *a, **k: "NO DEBERIA LLAMARSE")

        assert o._generar_con_respaldo("p", "techne") == "de ollama"
