"""
tests/test_investigador_busqueda.py
===================================
Regresion del fallo de investigacion de Cognia (2026-07-19).

El bug: la cadena de investigacion terminaba en `buscar_duckduckgo`, que pega
contra la Instant Answer API de DuckDuckGo. Esa API NO es un buscador — solo
devuelve fichas de entidades enciclopedicas — asi que ante una consulta tecnica
respondia vacio, `investigar_si_necesario` devolvia None y el modelo terminaba
contestando de memoria (medido: alucino `from pynput import microphone`, que no
existe).

El fix agrega `buscar_web` como ultimo eslabon. Estos tests no tocan la red:
verifican la forma del contrato y que la degradacion sea honesta ([] / None en
vez de excepciones o datos inventados).
"""

import pytest

import investigador


FALSOS = [
    {"titulo": "openWakeWord", "url": "https://github.com/dscripka/openWakeWord",
     "resumen": "An open-source audio wake word detection framework"},
    {"titulo": "OpenWakeWord docs", "url": "https://openwakeword.com/",
     "resumen": "Train custom wake words"},
]


class TestBuscarWeb:
    def test_devuelve_el_mismo_contrato_que_los_otros_buscadores(self, monkeypatch):
        """buscar_web tiene que encajar en la cadena sin tocar a los llamadores."""
        monkeypatch.setattr(investigador, "buscar_web_resultados",
                            lambda q, max_resultados=5: FALSOS)
        r = investigador.buscar_web("openWakeWord")
        assert set(r) == {"titulo", "extracto", "url", "idioma", "fuente"}
        assert r["fuente"] == "busqueda_web"
        # El extracto va anclado a las fuentes: si el modelo despues inventa,
        # se puede contrastar contra las URLs que tenia delante.
        assert "github.com/dscripka/openWakeWord" in r["extracto"]
        assert "openwakeword.com" in r["extracto"]

    def test_sin_resultados_devuelve_none_en_vez_de_inventar(self, monkeypatch):
        monkeypatch.setattr(investigador, "buscar_web_resultados",
                            lambda q, max_resultados=5: [])
        assert investigador.buscar_web("cualquier cosa") is None

    def test_un_fallo_de_red_no_propaga_excepcion(self, monkeypatch):
        """La investigacion es best-effort: nunca puede romper la respuesta."""
        def explota(*a, **k):
            raise OSError("red caida")
        monkeypatch.setattr(investigador.urllib.request, "urlopen", explota)
        monkeypatch.setattr(investigador, "_buscar_con_ddgs",
                            lambda q, n: [])
        assert investigador.buscar_web_resultados("x", intentos=1) == []

    def test_ddgs_es_la_via_principal(self, monkeypatch):
        """Si ddgs responde, no se toca el endpoint crudo."""
        monkeypatch.setattr(investigador, "_buscar_con_ddgs",
                            lambda q, n: FALSOS)
        def no_deberia_llamarse(*a, **k):
            raise AssertionError("no debia caer al endpoint crudo")
        monkeypatch.setattr(investigador.urllib.request, "urlopen",
                            no_deberia_llamarse)
        assert investigador.buscar_web_resultados("openWakeWord") == FALSOS


class TestPertinenciaDeLaMemoria:
    """El gate tiene que mirar si la memoria VIENE AL CASO, no cuánta hay.

    Caso real (2026-07-19): ante una pregunta sobre los modelos MiniCPM de
    OpenBMB, la memoria devolvió 3 episodios de 'conocimiento_python' con 0.564
    de cobertura, el gate concluyó "ya sé" y el modelo respondió de memoria
    paramétrica recomendando DINOv2 — mientras 12 fuentes correctas ya
    recuperadas se descartaban sin usarse.
    """

    CTX_PYTHON = ("- 'Python es un lenguaje de programacion interpretado y de "
                  "alto nivel muy usado' (etiqueta: conocimiento_python, sim: 56.4%)")

    def test_memoria_de_otro_tema_no_cuenta_como_saber(self):
        assert investigador.necesita_investigar(
            self.CTX_PYTHON, pregunta="que modelos publica OpenBMB MiniCPM") is True

    def test_memoria_del_tema_si_cuenta(self):
        assert investigador.necesita_investigar(
            self.CTX_PYTHON, pregunta="para que sirve Python en la ciencia") is False

    def test_sin_pregunta_conserva_el_comportamiento_viejo(self):
        """Los llamadores que no pasan pregunta no cambian de conducta."""
        assert investigador.necesita_investigar(self.CTX_PYTHON) is False

    def test_contexto_vacio_siempre_investiga(self):
        assert investigador.necesita_investigar("", pregunta="lo que sea") is True
        assert investigador.necesita_investigar(None, pregunta="lo que sea") is True

    def test_ignora_acentos_al_comparar(self):
        ctx = ("- 'La fotosintesis es el proceso por el cual las plantas "
               "generan energia' (etiqueta: biologia, sim: 70%)")
        assert investigador.necesita_investigar(
            ctx, pregunta="explicame la fotosíntesis") is False

    def test_terminos_solo_toma_palabras_de_contenido(self):
        t = investigador._terminos("¿Qué es la fotosíntesis de las plantas?")
        assert "fotosintesis" in t and "plantas" in t
        # Vacías y palabras cortas quedan afuera, para que no haya coincidencias
        # espurias por 'para', 'sobre' o 'los'.
        assert "para" not in t and "sobre" not in t and "los" not in t


class TestCadenaDeInvestigacion:
    def test_cae_a_busqueda_web_cuando_wikipedia_y_ddg_fallan(self, monkeypatch):
        """LA REGRESION: antes del fix la cadena moria aca y no se investigaba.

        Falla sin el fix (buscar_web no estaba en la cadena) y pasa con el.
        """
        monkeypatch.setattr(investigador, "necesita_investigar", lambda c, **k: True)
        monkeypatch.setattr(investigador, "limpiar_pregunta", lambda p: "wake word")
        monkeypatch.setattr(investigador, "buscar_wikipedia", lambda *a, **k: None)
        monkeypatch.setattr(investigador, "buscar_duckduckgo", lambda *a, **k: None)
        monkeypatch.setattr(investigador, "buscar_web_resultados",
                            lambda q, max_resultados=5: FALSOS)
        monkeypatch.setattr(investigador, "extraer_hechos_simples",
                            lambda t, e: [])
        monkeypatch.setattr(investigador, "generar_hipotesis", lambda *a: [])
        monkeypatch.setattr(investigador, "guardar_en_cognia",
                            lambda *a: {"episodios": 0, "hechos_grafo": 0})

        contexto, investigado, info = investigador.investigar_si_necesario(
            object(), "que es openWakeWord?", "")

        assert investigado is True
        assert "openWakeWord" in contexto
        # La fuente se nombra de verdad: antes decia "(Wikipedia)" pasara lo
        # que pasara, lo que le mentia al modelo sobre su propia evidencia.
        assert "busqueda_web" in contexto
        assert "Wikipedia" not in contexto.split("\n")[0]

    def test_sin_ninguna_fuente_no_se_inventa_investigacion(self, monkeypatch):
        monkeypatch.setattr(investigador, "necesita_investigar", lambda c, **k: True)
        monkeypatch.setattr(investigador, "limpiar_pregunta", lambda p: "x")
        monkeypatch.setattr(investigador, "buscar_wikipedia", lambda *a, **k: None)
        monkeypatch.setattr(investigador, "buscar_duckduckgo", lambda *a, **k: None)
        monkeypatch.setattr(investigador, "buscar_web_resultados",
                            lambda q, max_resultados=5: [])

        contexto, investigado, info = investigador.investigar_si_necesario(
            object(), "pregunta rara", "contexto previo")

        assert investigado is False
        assert contexto == "contexto previo"
