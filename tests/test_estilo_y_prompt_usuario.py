"""
Tests del estilo conversacional (cognia/ux/estilo.py) y del system prompt
configurable (cognia/system_prompt.py + archivo de usuario), 2026-08-02.

Sin modelo ni disco compartido: el archivo de prompt va a tmp_path via el
override COGNIA_PROMPT_USUARIO_PATH.
"""
import io
import contextlib

import pytest

from cognia.ux import estilo
from cognia import system_prompt as sp


# ---------------------------------------------------------------------------
# FlujoSuave: streaming en trozos de palabra
# ---------------------------------------------------------------------------

def _stream_plano(tokens, umbral=8):
    """Corre FlujoSuave sin rich (console=None) y devuelve lo impreso."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        f = estilo.FlujoSuave(console=None, umbral=umbral)
        for t in tokens:
            f.escribir(t)
        f.cerrar()
    return buf.getvalue()


def test_flujo_suave_no_pierde_texto():
    tokens = ["Hol", "a ", "mun", "do, ", "esto ", "es ", "un ", "stream."]
    out = _stream_plano(tokens)
    assert "Hola mundo, esto es un stream." in out.replace("\n  ", "\n")


def test_flujo_suave_no_corta_palabras():
    # Con umbral chico, cada emision debe terminar en espacio o fin de texto:
    # nunca se parte una palabra a la mitad entre dos emisiones.
    emitido = []
    f = estilo.FlujoSuave(console=None, umbral=6)
    f._emitir = lambda t: emitido.append(t)          # capturar emisiones crudas
    for t in ["supercalifragilistico ", "y ", "algo ", "mas..."]:
        f.escribir(t)
    f.cerrar()
    for trozo in emitido[:-1]:
        assert trozo.endswith(" ") or trozo.endswith("\n"), repr(trozo)
    assert "".join(emitido).strip() == "supercalifragilistico y algo mas..."


def test_flujo_suave_salto_de_linea_vacia_el_buffer():
    out = _stream_plano(["linea uno\n", "linea dos"])
    assert "linea uno" in out and "linea dos" in out


# ---------------------------------------------------------------------------
# respuesta(): sin panel, con sangria y ancho comodo
# ---------------------------------------------------------------------------

def test_respuesta_plana_sangra_y_respira():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        estilo.respuesta("hola\nsegunda linea", console=None)
    out = buf.getvalue()
    assert out.startswith("\n")            # aire arriba
    assert out.endswith("\n\n") or out.endswith("\n")
    assert "  hola" in out                 # sangria de 2
    assert "  segunda linea" in out


def test_respuesta_no_reenvuelve_codigo_indentado():
    linea_codigo = "    x = " + "a" * 150   # larga Y con pinta de codigo
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        estilo.respuesta("texto\n" + linea_codigo, console=None)
    # la linea de codigo sale entera (con la sangria agregada), sin partirse
    assert "  " + linea_codigo in buf.getvalue()


def test_respuesta_vacia_no_imprime():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        estilo.respuesta("   ", console=None)
    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# actividad() / resumen_hecho(): la tool como parte de la conversacion
# ---------------------------------------------------------------------------

def test_actividad_propaga_la_excepcion_del_cuerpo():
    # El adorno jamas debe tragarse el error real de la tool.
    with pytest.raises(ValueError):
        with estilo.actividad("leer_archivo", "x.py", console=None):
            raise ValueError("boom")


def test_actividad_sin_console_imprime_una_linea():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with estilo.actividad("leer_archivo", "motor.py", console=None):
            pass
    assert "Leyendo motor.py" in buf.getvalue()


def test_resumen_hecho_ok_y_error():
    ok = estilo.resumen_hecho("escribir_archivo", "juego.py|print(1)", ok=True)
    assert "Escribiendo juego.py" in ok and "info_dim" in ok
    err = estilo.resumen_hecho("ejecutar", "python juego.py", ok=False)
    assert "fallo" in err and "warn_cl" in err


def test_objeto_de_recorta_payload_y_rutas_largas():
    assert estilo.objeto_de("motor.py|contenido enorme") == "motor.py"
    largo = estilo.objeto_de("C:/" + "sub/" * 40 + "archivo.py")
    assert len(largo) <= 49 and largo.endswith("archivo.py")


# ---------------------------------------------------------------------------
# System prompt configurable
# ---------------------------------------------------------------------------

@pytest.fixture
def prompt_en_tmp(tmp_path, monkeypatch):
    ruta = tmp_path / "system_prompt.md"
    monkeypatch.setenv("COGNIA_PROMPT_USUARIO_PATH", str(ruta))
    monkeypatch.delenv("COGNIA_PROMPT_USUARIO", raising=False)
    return ruta


def test_default_se_crea_y_es_idempotente(prompt_en_tmp):
    ruta = sp.asegurar_prompt_usuario()
    assert ruta.read_text(encoding="utf-8") == sp.PROMPT_USUARIO_DEFAULT
    # una edicion del usuario NO se pisa al re-asegurar
    ruta.write_text("mi prompt propio", encoding="utf-8")
    sp.asegurar_prompt_usuario()
    assert ruta.read_text(encoding="utf-8") == "mi prompt propio"
    # restaurar SI pisa (es su contrato)
    sp.restaurar_prompt_usuario()
    assert ruta.read_text(encoding="utf-8") == sp.PROMPT_USUARIO_DEFAULT


def test_prompt_usuario_manda_para_el_cerebro(prompt_en_tmp, monkeypatch):
    prompt_en_tmp.write_text("SOY EL PROMPT PERSONALIZADO", encoding="utf-8")
    # El prompt personal SIGUE mandando (va primero y reemplaza la identidad);
    # desde 2026-08-25 lo acompana el bloque operativo de ENTORNO (SO/shell/
    # cwd + "el chat no ejecuta"), igual que ya lo acompanaba el arbitro.
    cerebro = sp.build_system_prompt(rol="cerebro")
    assert cerebro.startswith("SOY EL PROMPT PERSONALIZADO")
    assert "ENTORNO DEL USUARIO" in cerebro
    # Con el kill-switch, la igualdad byte a byte de siempre.
    monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
    assert sp.build_system_prompt(rol="cerebro") == "SOY EL PROMPT PERSONALIZADO"


def test_agente_nunca_ve_el_prompt_usuario(prompt_en_tmp):
    # Medido 2026-07-23: texto extra en el prompt del agente degrada el gate.
    prompt_en_tmp.write_text("SOY EL PROMPT PERSONALIZADO", encoding="utf-8")
    agente = sp.build_system_prompt(rol="agente")
    assert "SOY EL PROMPT PERSONALIZADO" not in agente
    assert "agente de herramientas" in agente


def test_kill_switch_apaga_sin_borrar(prompt_en_tmp, monkeypatch):
    prompt_en_tmp.write_text("SOY EL PROMPT PERSONALIZADO", encoding="utf-8")
    monkeypatch.setenv("COGNIA_PROMPT_USUARIO", "0")
    cerebro = sp.build_system_prompt(rol="cerebro")
    assert "SOY EL PROMPT PERSONALIZADO" not in cerebro
    assert "Cognia" in cerebro                       # cae al integrado
    assert prompt_en_tmp.exists()                    # el archivo queda intacto


def test_archivo_vacio_cae_al_integrado(prompt_en_tmp):
    prompt_en_tmp.write_text("   \n", encoding="utf-8")
    cerebro = sp.build_system_prompt(rol="cerebro")
    assert "Cognia" in cerebro and "TU PAPEL AHORA" in cerebro


def test_con_arbitro_se_agrega_al_personalizado(prompt_en_tmp):
    prompt_en_tmp.write_text("MI PROMPT", encoding="utf-8")
    texto = sp.build_system_prompt(rol="cerebro", con_arbitro=True)
    assert texto.startswith("MI PROMPT")
    assert "CONVIVENCIA CON OTROS GENERADORES" in texto


def test_default_contiene_las_adaptaciones_pedidas():
    # Identidad de Cognia (no Anthropic) + la regla de voice_note pedida por
    # el dueno, adaptada al producto.
    d = sp.PROMPT_USUARIO_DEFAULT
    assert "Cognia" in d and "Tomas Montes" in d
    assert "<voice_note>" in d
    # Acotado: en CPU el prefill es caro; el default no puede ser un monstruo.
    assert len(d) < 6000
