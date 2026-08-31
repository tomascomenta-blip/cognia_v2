# -*- coding: utf-8 -*-
"""Guards del cierre del bucle del agente (salida continua, 2026-08-31).

El bucle vive en una funcion larga que habla con el modelo y no se puede
invocar de punta a punta en un unitario — mismo criterio que
test_fast_path_guard.py, y por eso este fichero es de guards A NIVEL DE
FUENTE. La logica que protegen esta testeada aparte y a fondo en
test_salida_continua.py (43 casos); lo que se fija aqui es el CABLEADO, que es
justo lo que se pierde en un refactor.

Lo que fallaba (chat_history del dueno, 2026-08-31):
  id 1071 -> el turno se cerro con la respuesta vacia y solo razonamiento, y el
             bucle entregaba el CoT marcado como no cumplido sin intentar nada.
  y su gemelo: una respuesta final en prosa cortada por max_tokens se entregaba
             truncada Y marcada como ok=True.
"""
import inspect

from cognia.agent import loop as loop_mod


def _loop_src() -> str:
    return inspect.getsource(loop_mod)


def test_la_respuesta_final_cortada_por_tope_se_continua():
    src = _loop_src()
    assert "def _continuar_final" in src, (
        "desaparecio la continuacion de la respuesta final")
    # Se dispara con el corte por tope, dentro de la rama que SI tiene texto.
    i_txt = src.find("if resp.texto:")
    i_cont = src.find("_continuar_final(result_text)")
    assert i_txt != -1 and i_cont != -1
    assert i_txt < i_cont, "la continuacion quedo fuera de la rama con texto"
    assert 'finish == "length"' in src


def test_el_turno_que_solo_razona_insiste_antes_de_rendirse():
    src = _loop_src()
    assert "def _insistir_final" in src
    i_razon = src.find("elif resp.reasoning_content:")
    # La LLAMADA, no la definicion (que esta antes en el fichero).
    i_insiste = src.find("_rescate, _tk_ins = _insistir_final()")
    assert i_razon != -1 and i_insiste != -1
    assert i_razon < i_insiste, (
        "la insistencia quedo fuera de la rama de solo-razonamiento")


def test_no_se_insiste_cuando_el_corte_lo_dio_la_VENTANA():
    """Con la ventana llena, otra generacion entera no puede ayudar: lo unico
    que sirve es liberar contexto. Insistir ahi seria la rampa inutil que este
    mismo fichero documenta."""
    src = _loop_src()
    i_insiste = src.find("_rescate, _tk_ins = _insistir_final()")
    assert i_insiste != -1
    guarda = src[max(0, i_insiste - 400):i_insiste]
    assert "es_corte_por_contexto" in guarda


def test_la_continuacion_del_agente_no_ofrece_tools():
    """El modelo ya eligio cerrar en prosa; ofrecerle herramientas a mitad de
    frase lo saca del cierre."""
    src = _loop_src()
    i = src.find("def _continuar_final")
    cuerpo = src[i:i + 2500]
    assert "completar(_sc.continuacion_mensajes" in cuerpo
    assert "tools=" not in cuerpo


def test_los_tokens_de_la_continuacion_se_cuentan():
    """Una generacion que no se cuenta es un presupuesto que miente."""
    src = _loop_src()
    assert "tokens_total += _tk_cont" in src
    assert "tokens_total += _tk_ins" in src


def test_el_fallo_de_importacion_no_calla():
    """Regla del repo: 'no lo cablearon' y 'se rompio' no pueden verse igual."""
    src = _loop_src()
    i = src.find("def _continuar_final")
    cuerpo = src[i:i + 2500]
    assert "salida continua no disponible" in cuerpo
    assert "except Exception as exc" in cuerpo
