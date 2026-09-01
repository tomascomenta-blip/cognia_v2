# -*- coding: utf-8 -*-
"""
El tool call cortado a medias apaga el PENSAMIENTO, no sube el tope.

Corrida real que lo cazo (Vaelmark, 2026-08-31, Qwen3.8-27B-Ridge). El paso
llevaba 20.000 chars pensando, el tool call salio cortado a los 697 y el bucle
respondio con la rampa:

    el server no pudo parsear el tool call (se corto a medias):
        repito el paso con max_tokens 8192 -> 16384
    el server no pudo parsear el tool call (se corto a medias):
        repito el paso con max_tokens 16384 -> 32768
    el contenido no cabe en un solo tool call ni con max_tokens=32768
    x 448.8s - 14241 tokens - 3 pasos - backend: tool call cortado sin salida

Tres generaciones enteras dandole MAS SITIO PARA PENSAR a un turno que se
habia gastado el presupuesto pensando. Medido el mismo dia con el mismo
modelo y el mismo prompt: thinking ON, 2.500 tokens -> 10.359 chars de
razonamiento y CERO de respuesta; thinking OFF, 1.115 tokens -> 4.691 chars de
respuesta y finish='stop'.

Dos defectos encadenados, uno por fichero:

  1. chat_client: el HTTPError (el 500 del server cuando los argumentos se
     cortan) devolvia SOLO el error, tirando el reasoning ya acumulado.
  2. loop: `_puede_apagar_pensamiento` exigia CORTE_ANTES_DEL_TOOL_CALL, asi
     que el corte DENTRO del tool call nunca apagaba nada.

Sin el 1 el bucle es ciego; sin el 2 no actua aunque vea. Hacen falta los dos.
"""
import inspect

from cognia.agent import chat_client, loop


# -- 1. chat_client no tira lo generado cuando el server contesta 500 --------
def test_el_http_error_conserva_el_razonamiento_acumulado():
    src = inspect.getsource(chat_client)
    i = src.find("except urllib.error.HTTPError as e:")
    assert i != -1
    rama = src[i:i + 1600]
    assert "reasoning_content=" in rama, (
        "el 500 vuelve a tirar el razonamiento: el bucle no puede saber que "
        "el turno se fue en pensar")
    assert "texto=" in rama, "el 500 vuelve a tirar el texto parcial"


def test_el_http_error_sigue_llevando_el_error():
    """Conservar lo acumulado NO puede convertir un 500 en un exito."""
    src = inspect.getsource(chat_client)
    i = src.find("except urllib.error.HTTPError as e:")
    rama = src[i:i + 1600]
    assert 'error=f"HTTP {e.code}' in rama


# -- 2. el guard cubre el corte DENTRO del tool call ------------------------
def test_el_guard_ya_no_exige_que_el_corte_sea_antes_del_tool_call():
    src = inspect.getsource(loop._puede_apagar_pensamiento) \
        if hasattr(loop, "_puede_apagar_pensamiento") else inspect.getsource(loop)
    i = src.find("def _puede_apagar_pensamiento")
    assert i != -1
    cuerpo = src[i:i + 2000]
    assert "motivo != CORTE_ANTES_DEL_TOOL_CALL" not in cuerpo, (
        "volvio el guard que dejaba fuera el corte DENTRO del tool call")
    assert "not motivo" in cuerpo, "un corte vacio no debe apagar nada"


def test_el_guard_usa_el_contador_vivo_cuando_no_hay_reasoning():
    """Con el 500, `resp.reasoning_content` puede venir vacio aunque el turno
    llevara veinte mil chars pensando: la evidencia es el contador del stream."""
    src = inspect.getsource(loop)
    i = src.find("def _puede_apagar_pensamiento")
    cuerpo = src[i:i + 2000]
    assert '_vivo["chars_razon"]' in cuerpo
    assert "_RAZON_SE_LO_COMIO" in cuerpo


def test_el_umbral_de_razonamiento_esta_declarado_y_es_sensato():
    """Ni tan bajo que apague por un pensamiento normal, ni tan alto que no
    dispare nunca: el caso real llevaba 20.000 chars."""
    assert 3000 <= loop._RAZON_SE_LO_COMIO <= 12000


def test_el_dueno_sigue_mandando_con_COGNIA_THINKING_on():
    src = inspect.getsource(loop)
    i = src.find("def _puede_apagar_pensamiento")
    cuerpo = src[i:i + 2000]
    assert 'os.environ.get("COGNIA_THINKING"' in cuerpo


def test_sin_reasoning_y_sin_empezar_el_tool_call_no_se_apaga():
    """CORTE_ANTES_DEL_TOOL_CALL sin una sola letra de razonamiento no es un
    problema de pensamiento: apagar ahi seria adivinar."""
    src = inspect.getsource(loop)
    i = src.find("def _puede_apagar_pensamiento")
    cuerpo = src[i:i + 2000]
    j = cuerpo.find("if motivo == CORTE_ANTES_DEL_TOOL_CALL")
    assert j != -1
    assert "return False" in cuerpo[j:j + 200]


# -- 3. el aviso dice la verdad en los dos casos ----------------------------
def test_el_aviso_ya_no_afirma_que_no_llamo_a_la_herramienta():
    """Cuando el tool call SI empezo, el mensaje viejo ('sin llegar a llamar
    la herramienta') era falso."""
    src = inspect.getsource(loop)
    assert "el turno se fue en razonar {_donde}" in src
    assert "salio cortada a medias" in src
