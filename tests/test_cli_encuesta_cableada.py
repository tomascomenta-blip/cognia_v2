# -*- coding: utf-8 -*-
"""
tests/test_cli_encuesta_cableada.py
==================================
La ENCUESTA del mejorador (cognia/harness/encuesta.py) existia, tenia 58 tests
propios... y casi nunca corria. Hasta hoy vivia SOLO dentro de la rama
'preguntar' de `_mejorar_linea_interactiva` y DETRAS de
`es_candidato(rechazar_ordenes=True)`, que rechaza justo las ordenes cortas y
vagas a las que la encuesta apunta: de 21 pedidos tipicos medidos, 11 ni
abrian el menu. El dueno lo reporto DOS veces.

Ningun test mencionaba `_encuesta_interactiva`: el fallo vivia en el CABLEADO,
que es exactamente lo que no tenia red. Esto la pone.

Lo que se fija:
  1. el gate `_encuesta_aplica` es INDEPENDIENTE del reformulador (una orden
     que `es_candidato` rechaza si pasa por la encuesta);
  2. las respuestas llegan al texto que se envia;
  3-4. F3 y '/mejorar <texto>' tambien encuestan (dos vias que no la llamaban);
  5. en 'auto' solo se abre un menu si de VERDAD hay preguntas;
  6. con las encuestas activas el system es v4 (el que NO mete preguntas en el
     prompt entregado), y el estilo explicito del dueno sigue ganando;
  7. si aun asi la salida vuelve con preguntas, se descarta y se entrega el
     original (la red determinista de `sanear_salida`);
  8. sin tty no se pregunta nada y no explota nada.

Ni modelo ni red: el generador se inyecta.
"""

import pytest

import cognia.cli as cli
from cognia.harness import encuesta as enc
from cognia.harness import mejorar_prompt as mp
from cognia.ux import selector as sel


# ---------------------------------------------------------------------------
# Aislamiento
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    monkeypatch.delenv(mp.ENV_VERSION, raising=False)
    cli._LINEA_INYECTADA[0] = False
    cli._MEJORA_YA_DECIDIDA[0] = False
    cli._PRECARGA_PROMPT[0] = ""
    yield
    cli._LINEA_INYECTADA[0] = False
    cli._MEJORA_YA_DECIDIDA[0] = False
    cli._PRECARGA_PROMPT[0] = ""


def _tty(monkeypatch, valor=True):
    monkeypatch.setattr(sel, "hay_tty", lambda: valor)


def _sin_contexto(monkeypatch):
    """El contexto de sesion lee disco y RAG; aca no aporta nada."""
    monkeypatch.setattr(cli, "_contexto_de_mejora", lambda raw: None)


def _encuesta_de(*preguntas):
    return enc.Encuesta(ok=bool(preguntas), preguntas=list(preguntas),
                        motivo="ok" if preguntas else "no falta nada",
                        origen="semilla" if preguntas else "")


def _pregunta(pid="estilo", texto="Que estilo?", opciones=("minimalista",
                                                          "colorido")):
    return enc.Pregunta(id=pid, tipo="unica", texto=texto,
                        opciones=list(opciones))


def _espiar_mejorar(monkeypatch, texto_salida="Reformulado y concreto."):
    """Sustituye mejorar_prompt.mejorar y guarda (texto, kwargs)."""
    visto = []

    def _falso(texto, **kw):
        visto.append((texto, kw))
        return mp.Mejora(ok=True, texto=texto_salida, original=texto,
                         motivo="ok", ms=1, modelo="falso")

    monkeypatch.setattr(mp, "mejorar", _falso)
    return visto


ORDEN = "hazme una pagina web"


# ---------------------------------------------------------------------------
# 1. El eje independiente
# ---------------------------------------------------------------------------

def test_preguntar_con_pedido_corto_llama_a_la_encuesta(monkeypatch):
    """El reformulador RECHAZA la orden y la encuesta la coge igual. Ese
    desacople es el pedido 5.2 entero."""
    _tty(monkeypatch)
    assert mp.es_candidato(ORDEN) is False, \
        "si esto cambia, el gate separado deja de tener sentido"
    assert cli._mejora_aplica(ORDEN) is False
    assert cli._encuesta_aplica(ORDEN) is True

    llamadas = []

    def _falsa(raw, ctx):
        llamadas.append(raw)
        return raw + " (estilo: minimalista)"

    monkeypatch.setattr(cli, "_encuesta_interactiva", _falsa)
    _sin_contexto(monkeypatch)

    enviado = cli._mejorar_linea_interactiva(ORDEN, solo_encuesta=True)

    assert llamadas == [ORDEN]
    assert enviado == ORDEN + " (estilo: minimalista)"


def test_el_bucle_del_repl_evalua_la_encuesta_antes_de_consumir_la_marca():
    """ESTRUCTURAL (repl() no se instancia): `_mejora_aplica` CONSUME la marca
    de 'linea ya decidida'. Si la encuesta se evaluara despues, se abriria
    sobre una linea que el dueno acaba de aprobar."""
    import inspect
    fuente = inspect.getsource(cli)
    cuerpo = fuente[fuente.index("def repl():"):]
    i_enc = cuerpo.index("_quiere_encuesta = _encuesta_aplica(raw)")
    i_mej = cuerpo.index("_quiere_mejora = _mejora_aplica(raw)")
    assert i_enc < i_mej, "la encuesta se evalua DESPUES de consumir la marca"
    assert "solo_encuesta=not _quiere_mejora" in cuerpo


def test_la_linea_ya_decidida_y_la_inyectada_no_encuestan(monkeypatch):
    _tty(monkeypatch)
    cli._MEJORA_YA_DECIDIDA[0] = True
    assert cli._encuesta_aplica(ORDEN) is False
    # y no la CONSUME: eso es trabajo de _mejora_aplica
    assert cli._MEJORA_YA_DECIDIDA[0] is True
    cli._MEJORA_YA_DECIDIDA[0] = False
    cli._LINEA_INYECTADA[0] = True
    assert cli._encuesta_aplica(ORDEN) is False


def test_con_mejorar_off_no_se_pregunta_al_dar_enter(monkeypatch):
    """'No volver a preguntar' es el nombre de la opcion que apaga /mejorar:
    seguir abriendo encuestas en cada Enter romperia esa promesa. F3 y
    '/mejorar <texto>' son ordenes explicitas y si preguntan."""
    _tty(monkeypatch)
    cli._save_config({**cli._CONFIG_DEFAULTS, "mejorar_prompt": "off"})
    assert cli._encuesta_aplica(ORDEN) is False
    assert cli._encuesta_aplica(ORDEN, explicito=True) is True


# ---------------------------------------------------------------------------
# 2. Las respuestas llegan al texto
# ---------------------------------------------------------------------------

def test_las_respuestas_de_la_encuesta_llegan_al_texto_enviado(monkeypatch):
    _tty(monkeypatch)
    _sin_contexto(monkeypatch)
    monkeypatch.setattr(enc, "preparar",
                        lambda texto, **kw: _encuesta_de(_pregunta()))
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: "minimalista")

    enviado = cli._mejorar_linea_interactiva(ORDEN, solo_encuesta=True)

    assert enviado != ORDEN
    assert "minimalista" in enviado
    assert ORDEN in enviado, "el pedido del dueno JAMAS se pierde"


# ---------------------------------------------------------------------------
# 3-4. Las otras dos vias
# ---------------------------------------------------------------------------

def test_f3_tambien_encuesta(monkeypatch):
    """F3 llamaba al reformulador con la linea PELADA: ni contexto ni
    preguntas."""
    _tty(monkeypatch)
    _sin_contexto(monkeypatch)
    visto = _espiar_mejorar(monkeypatch)
    llamadas = []
    monkeypatch.setattr(cli, "_encuesta_interactiva",
                        lambda raw, ctx: llamadas.append(raw) or (raw + " (para un negocio)"))

    cli._mejora_en_el_sitio("hazme una pagina web para vender")

    assert llamadas == ["hazme una pagina web para vender"]
    texto, kwargs = visto[0]
    assert texto.endswith("(para un negocio)")
    assert kwargs["encuesta_previa"] is True


def test_mejorar_texto_tambien_encuesta(monkeypatch, capsys):
    _tty(monkeypatch)
    _sin_contexto(monkeypatch)
    visto = _espiar_mejorar(monkeypatch)
    llamadas = []
    monkeypatch.setattr(cli, "_encuesta_interactiva",
                        lambda raw, ctx: llamadas.append(raw) or (raw + " (en 3 secciones)"))

    cli._slash_mejorar("hazme una pagina web para vender")

    assert llamadas == ["hazme una pagina web para vender"]
    assert visto[0][0].endswith("(en 3 secciones)")
    assert visto[0][1]["encuesta_previa"] is True


# ---------------------------------------------------------------------------
# 5. En 'auto' solo si hay algo que preguntar
# ---------------------------------------------------------------------------

def test_auto_encuesta_solo_si_hay_preguntas(monkeypatch):
    """En 'auto' el trato es que el dueno no toca nada: si `preparar()` no
    devuelve preguntas no se abre NI UN menu."""
    _tty(monkeypatch)
    _sin_contexto(monkeypatch)
    cli._save_config({**cli._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    _espiar_mejorar(monkeypatch)
    menus = []
    monkeypatch.setattr(sel, "elegir",
                        lambda *a, **k: menus.append(a) or "minimalista")

    monkeypatch.setattr(enc, "preparar", lambda texto, **kw: _encuesta_de())
    cli._mejorar_linea_interactiva("arregla el login del panel de admin")
    assert menus == [], "se abrio un menu sin preguntas que hacer"

    monkeypatch.setattr(enc, "preparar",
                        lambda texto, **kw: _encuesta_de(_pregunta()))
    cli._mejorar_linea_interactiva("arregla el login del panel de admin")
    assert len(menus) == 1, "en auto la encuesta con preguntas no se abrio"


def test_auto_no_encuesta_un_pedido_largo(monkeypatch):
    """El tope de 'auto': un pedido ya largo y especifico no se interrumpe."""
    _tty(monkeypatch)
    _sin_contexto(monkeypatch)
    cli._save_config({**cli._CONFIG_DEFAULTS, "mejorar_prompt": "auto"})
    _espiar_mejorar(monkeypatch)
    llamadas = []
    monkeypatch.setattr(cli, "_encuesta_interactiva",
                        lambda raw, ctx: llamadas.append(raw) or raw)

    cli._mejorar_linea_interactiva("x" * (cli._tope_encuesta() + 10))

    assert llamadas == []


# ---------------------------------------------------------------------------
# 6. La version del system
# ---------------------------------------------------------------------------

def test_orden_es_v4_cuando_las_encuestas_estan_activas(monkeypatch):
    _sin_contexto(monkeypatch)
    visto = _espiar_mejorar(monkeypatch)

    cli._save_config({**cli._CONFIG_DEFAULTS, "encuestas": "auto"})
    cli._mejora_generar("arregla el login del panel", "test")
    assert visto[-1][1]["version"] == "v4", visto[-1][1]

    cli._save_config({**cli._CONFIG_DEFAULTS, "encuestas": "off"})
    cli._mejora_generar("arregla el login del panel", "test")
    assert visto[-1][1]["version"] == "v2"

    # ...y encuesta_previa manda sobre el estado
    cli._mejora_generar("arregla el login del panel", "test",
                        encuesta_previa=True)
    assert visto[-1][1]["version"] == "v4"


def test_el_estilo_explicito_del_dueno_siempre_gana(monkeypatch):
    """Un 'default v2' NO es una eleccion: si lo fuera, el default pisaria al
    v4 que pide la encuesta y este cableado no haria nada."""
    _sin_contexto(monkeypatch)
    visto = _espiar_mejorar(monkeypatch)
    cli._save_config({**cli._CONFIG_DEFAULTS, "encuestas": "auto",
                      "mejorar_prompt_estilo": "v2"})
    cli._mejora_generar("arregla el login del panel", "test",
                        encuesta_previa=True)
    assert visto[-1][1]["version"] == "v2"


# ---------------------------------------------------------------------------
# 7. La red determinista
# ---------------------------------------------------------------------------

def test_la_salida_final_no_devuelve_preguntas_tras_encuestar(monkeypatch):
    """Con la encuesta ya corrida, una reformulacion que devuelve preguntas se
    DESCARTA y se entrega el original. Aca corre el saneador de verdad: solo
    se inyecta el generador."""
    _sin_contexto(monkeypatch)
    cli._save_config({**cli._CONFIG_DEFAULTS, "encuestas": "auto"})
    con_preguntas = ("Antes de proponer nada, preguntame: que secciones "
                     "necesitas? Y decime tambien para que publico es? "
                     "Con esas respuestas armo la estructura.")

    monkeypatch.setattr(mp, "_detectar_url", lambda url=None: "http://x/y")
    monkeypatch.setattr(mp, "_construir_generar",
                        lambda url, timeout_s, registro: (
                            lambda prompt, system: con_preguntas))

    original = "hazme una pagina web para mi tienda de bicicletas"
    mejora = cli._mejora_generar(original, "test", encuesta_previa=True)

    assert mejora is not None
    assert mejora.ok is False
    assert mejora.texto == original, "la salida con preguntas se colo"
    assert "encuesta" in mejora.motivo

    # y SIN encuesta previa el comportamiento de siempre no cambia
    mejora2 = cli._mejora_generar(original, "test", encuesta_previa=False)
    assert mejora2.ok is True


# ---------------------------------------------------------------------------
# 8. Sin tty
# ---------------------------------------------------------------------------

def test_sin_tty_no_pregunta_nada_y_no_explota(monkeypatch):
    _tty(monkeypatch, False)
    assert cli._encuesta_aplica(ORDEN) is False
    assert cli._encuesta_aplica(ORDEN, explicito=True) is False
    menus = []
    monkeypatch.setattr(sel, "elegir", lambda *a, **k: menus.append(a) or None)
    monkeypatch.setattr(enc, "preparar",
                        lambda texto, **kw: _encuesta_de(_pregunta()))
    # la funcion se puede llamar igual (los e2e pipeados pasan por aca)
    assert cli._encuesta_interactiva(ORDEN, None) == ORDEN
    assert menus == []
