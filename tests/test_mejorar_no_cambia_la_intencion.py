# -*- coding: utf-8 -*-
"""REGRESION (transcript real del dueno, 2026-08-25 11:52, CLI 4.12.0).

Con mejorar_prompt="preguntar", la linea "bueno quiero que limpies todas las
capturas de pantalla en mi computador porfavor" salio reescrita como "Arma un
plan de limpieza para que yo elimine... Antes de ejecutar nada, preguntame en
que directorio... que formato de respuesta prefieres": una ORDEN al asistente
convertida en un plan con preguntas PARA EL USUARIO. Cambio la intencion y la
unidad de accion; el dueno la ignoro y tuvo que reteclearla.

Lo que se defiende aca, sin modelo (el reformulador se inyecta):
- es_candidato devuelve False para las ordenes cortas de accion (las 4 lineas
  del transcript) y True para las peticiones ambiguas/largas, que son para lo
  que la mejora existe;
- el post-check determinista de sanear_salida DESCARTA una reformulacion que
  devuelve la accion al usuario, con un motivo que el CLI grita
  ("mejora descartada: cambiaba la intencion ...");
- el descarte NO rompe el caso legitimo: en una peticion ambigua, "preguntame"
  sigue siendo valido (es lo que v2 ensena en sus ejemplos);
- en modo "preguntar", la opcion por DEFECTO tras reformular es conservar el
  original: Enter jamas envia la reescritura por inercia.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from cognia.harness import mejorar_prompt as mp  # noqa: E402

# Las 4 lineas del transcript, byte a byte como las tecleo el dueno.
ORDEN_1 = ("bueno quiero que limpies todas las capturas de pantalla en mi "
           "computador porfavor")
ORDEN_2 = ("Quiero que limpies todas las capturas de pantalla en mi "
           "computador porfavor")
ORDEN_3 = "hazlo tu"
ORDEN_4 = "no los ejecutaste"

# La reescritura MALA que produjo /mejorar (resumen fiel del transcript: plan
# para el usuario + preguntas + formato).
MEJORA_MALA = (
    "Arma un plan de limpieza para que yo elimine las capturas de pantalla "
    "de mi computador. Antes de ejecutar nada, preguntame en que directorio "
    "estan las capturas y que formato de respuesta prefieres.")

# Una reformulacion que SI conserva la intencion (Cognia sigue ejecutando).
MEJORA_BUENA = (
    "Limpia todas las capturas de pantalla de mi computador y dime cuantos "
    "archivos borraste y de que carpetas salieron.")


# ------------------------------------------------- es_candidato y las ordenes

@pytest.mark.parametrize("orden", [ORDEN_1, ORDEN_2, ORDEN_3, ORDEN_4])
def test_las_ordenes_del_transcript_no_son_candidatas(orden):
    # El enganche del Enter no puede interceptar una orden: va directa al
    # enrutador. Reformularla es lo que fabrico el bug.
    assert mp.es_candidato(orden) is False


def test_una_orden_imperativa_del_enrutador_tampoco():
    # "borra ..." es needs_agent=True en cognia.agent.intent.detect: si el
    # enrutador la mandaria al agente, el mejorador no se mete.
    assert mp.es_candidato("borra las capturas de pantalla") is False


@pytest.mark.parametrize("peticion", [
    # ambigua larga: el caso para el que la mejora EXISTE
    ("me gustaria tener una manera de organizar mis notas de estudio para "
     "el parcial de quimica"),
    # casos medidos del A/B que NO son ordenes de accion sobre el sistema
    # ("organizame el escritorio" dejo de ser candidato el 2026-08-25: el
    # enrutador lo manda al agente -- accion:sistema -- y donde ejecuta el
    # agente, el mejorador no se mete)
    "arregla el login que rechaza usuarios validos",
    "quiero ponerme en forma y no se por donde empezar",
])
def test_las_peticiones_ambiguas_siguen_siendo_candidatas(peticion):
    assert mp.es_candidato(peticion) is True


def test_f3_explicito_acepta_ordenes():
    # F3 es un pedido explicito de reformular: ahi la orden se acepta
    # (rechazar_ordenes=False) y la intencion la protege el post-check.
    assert mp.es_candidato(ORDEN_2, rechazar_ordenes=False) is True


def test_orden_al_asistente_da_motivos_distintos(monkeypatch):
    # El motivo distingue las clases (sirve para diagnosticar, no solo
    # filtrar). Se apaga intent.detect para probar el PARACAIDAS local: los
    # marcadores tienen que cazar el transcript aunque el clasificador del
    # agente no exista o diga "chat" (que es justo lo que decia el 2026-08-25).
    from cognia.agent import intent as intent_mod
    monkeypatch.setattr(intent_mod, "detect",
                        lambda t: intent_mod.Intent(False, reason="chat"))
    assert "quiero/necesito que" in mp.orden_al_asistente(ORDEN_1)
    assert "hazlo" in mp.orden_al_asistente(ORDEN_3)
    assert "no ejecutada" in mp.orden_al_asistente(ORDEN_4)
    assert mp.orden_al_asistente("dame un plan de comidas semanal") == ""


def test_una_peticion_larga_no_se_bloquea_por_el_marcador():
    # El tope de palabras: "quiero que" en una peticion LARGA (> 25 palabras)
    # no la convierte en orden bloqueada -- ahi reformular si puede aportar.
    larga = ("quiero que me ayudes a pensar como organizar el viaje de fin "
             "de curso con mis companeros teniendo en cuenta el presupuesto "
             "que tenemos las fechas posibles los lugares que nos gustan y "
             "las restricciones de cada uno porque no logro ordenarlo solo")
    assert len(larga.split()) > mp._MAX_PALABRAS_ORDEN
    assert mp.es_candidato(larga) is True


# --------------------------------------------- el post-check de sanear_salida

def test_la_mejora_del_transcript_se_descarta():
    texto, motivo = mp.sanear_salida(MEJORA_MALA, ORDEN_2)
    assert motivo.startswith("mejora descartada: cambiaba la intencion")
    # y el motivo dice QUE marca la delato (auditable en el aviso)
    assert "para que yo" in motivo


def test_mejorar_con_reformulador_falso_malo_devuelve_el_original():
    # Sin modelo: el generar_fn inyectado devuelve la mejora mala del
    # transcript. mejorar() tiene que rechazarla ENTERA (ok=False) y el texto
    # enviable queda identico al original.
    res = mp.mejorar(ORDEN_2, generar_fn=lambda p, s: MEJORA_MALA)
    assert res.ok is False
    assert res.texto == ORDEN_2
    assert res.motivo.startswith("mejora descartada: cambiaba la intencion")


def test_una_reformulacion_que_conserva_la_orden_pasa():
    # El post-check no es un veto a reformular ordenes: si Cognia sigue siendo
    # quien ejecuta, la mejora es valida (camino F3 y '/mejorar <texto>').
    res = mp.mejorar(ORDEN_2, generar_fn=lambda p, s: MEJORA_BUENA)
    assert res.ok is True
    assert res.texto == MEJORA_BUENA


def test_preguntame_sigue_valido_en_peticiones_ambiguas():
    # Proteccion del caso principal de v2: en una peticion que NO es orden,
    # convertir huecos en preguntas es la mejora deseada, no un descarte.
    original = "quiero ponerme en forma y no se por donde empezar"
    mejora = ("Arma un plan de entrenamiento para que yo me ponga en forma "
              "partiendo de cero. Antes de proponer nada, preguntame cuantos "
              "dias por semana puedo entrenar y de cuanto tiempo dispongo "
              "cada dia. Con esas respuestas devuelve un plan semana a "
              "semana y una senal concreta de progreso.")
    texto, motivo = mp.sanear_salida(mejora, original)
    assert motivo == "ok"


def test_plan_mas_preguntas_sin_para_que_yo_tambien_se_descarta():
    # La variante sin "para que yo": el entregable pasa de ACTUAR a "arma un
    # plan" + "preguntame". Es la misma devolucion con otras palabras.
    mejora = ("Arma un plan de limpieza de las capturas de pantalla de mi "
              "computador. Preguntame en que directorio estan las capturas "
              "antes de empezar con el plan.")
    texto, motivo = mp.sanear_salida(mejora, ORDEN_1)
    assert motivo.startswith("mejora descartada: cambiaba la intencion")


def test_preguntar_datos_sin_soltar_la_accion_es_valido():
    # Una orden reformulada puede PEDIR datos si el asistente sigue siendo
    # quien ejecuta (el EJEMPLO 3 de v3 hace exactamente esto): 'preguntame'
    # a secas no descarta.
    mejora = ("Limpia todas las capturas de pantalla de mi computador. Antes "
              "de borrar nada, preguntame que carpetas debo revisar y si "
              "quiero conservar alguna captura reciente.")
    texto, motivo = mp.sanear_salida(mejora, ORDEN_2)
    assert motivo == "ok"


def test_el_system_prompt_lleva_la_regla_de_intencion():
    # La regla viaja en los TRES estilos (v3 se construye sobre v2).
    assert "Nunca conviertas una orden en preguntas al usuario" in mp._SYSTEM_V1
    for v in (mp._SYSTEM_V2, mp._SYSTEM_V3):
        assert "Cambiar QUIEN ejecuta la accion" in v
        assert "para que yo lo haga" in v


# ------------------------------------------------------- el cableado del CLI

@pytest.fixture()
def cfg_temporal(tmp_path, monkeypatch):
    """Config de mentira: nada de esta suite toca ~/.cognia_config.json."""
    import cognia.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH",
                        tmp_path / ".cognia_config.json")
    return tmp_path


def _con_tty(monkeypatch, valor=True):
    from cognia.ux import selector as sel
    monkeypatch.setattr(sel, "hay_tty", lambda: valor)


def test_mejora_aplica_ignora_las_ordenes_del_transcript(cfg_temporal,
                                                         monkeypatch):
    import cognia.cli as cli_mod
    _con_tty(monkeypatch, True)
    cli_mod._LINEA_INYECTADA[0] = False
    cli_mod._MEJORA_YA_DECIDIDA[0] = False
    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS,
                          "mejorar_prompt": "preguntar"})
    for orden in (ORDEN_1, ORDEN_2, ORDEN_3, ORDEN_4):
        assert cli_mod._mejora_aplica(orden) is False, orden
    # y la peticion ambigua larga SI pasa por el menu
    assert cli_mod._mejora_aplica(
        "me gustaria tener una manera de organizar mis notas de estudio "
        "para el parcial de quimica") is True


def test_el_descarte_se_grita_con_aviso_degradado(cfg_temporal, monkeypatch):
    # "mejora descartada: ..." tiene que pasar por _aviso_degradado: un
    # descarte mudo se veria igual que "no habia nada que mejorar".
    import cognia.cli as cli_mod
    from cognia.harness import mejorar_prompt

    def _falso(texto, **kw):
        return mejorar_prompt.Mejora(
            ok=False, texto=texto, original=texto,
            motivo=("mejora descartada: cambiaba la intencion (el original "
                    "ordenaba al asistente y la mejora se la devuelve al "
                    "usuario ('para que yo'))"),
            ms=7, modelo="falso")

    monkeypatch.setattr(mejorar_prompt, "mejorar", _falso)
    avisos = []
    monkeypatch.setattr(cli_mod, "_aviso_degradado",
                        lambda via, det="": avisos.append((via, det)))
    mejora = cli_mod._mejora_generar(ORDEN_2, "cli.mejorar.test")
    assert mejora is not None and mejora.ok is False
    assert any("mejora descartada" in det for _via, det in avisos)


def test_en_preguntar_el_default_conserva_el_original(cfg_temporal,
                                                      monkeypatch):
    # Tras reformular, la fila por defecto (Enter) del menu "Que envio?" es el
    # ORIGINAL: la reescritura mala del transcript se enviaba con el mismo
    # Enter reflejo con el que se abrio el menu.
    import cognia.cli as cli_mod
    from cognia.ux import selector as sel
    from cognia.harness import mejorar_prompt

    monkeypatch.setattr(
        mejorar_prompt, "mejorar",
        lambda texto, **kw: mejorar_prompt.Mejora(
            ok=True, texto=MEJORA_BUENA, original=texto, motivo="ok",
            ms=7, modelo="falso"))
    menus = []

    def _espia(titulo, opciones, default=0, **kw):
        menus.append((titulo, [o[0] for o in opciones], default))
        return "mejorar" if len(menus) == 1 else opciones[default][0]

    monkeypatch.setattr(sel, "elegir", _espia)
    enviado = cli_mod._mejorar_linea_interactiva(
        "dame ideas para ordenar mis fotos del viaje")
    # el segundo menu es el de "Que envio?": su default apunta al original
    titulo, valores, default = menus[1]
    assert valores[default] == "original"
    # y al elegir el default, lo enviado es EXACTAMENTE lo tecleado
    assert enviado == "dame ideas para ordenar mis fotos del viaje"
