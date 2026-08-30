# -*- coding: utf-8 -*-
"""
tests/test_cli_session_to_workflow.py
====================================
El handler de /session-to-workflow (cognia/cli.py) no tenia NI UN test, y por
eso el puente con el grabador llevaba roto desde que se escribio:

    activa = getattr(_gr, "grabacion_activa", None)   # esa funcion NO EXISTE

`getattr` devolvia None, `callable(None)` es False, el `except` no saltaba y
`pasos` quedaba SIEMPRE []. El comando trabajaba solo con la conversacion --
la fuente que `flujo_ia.de_sesion` documenta como la peor ("lo que se ejecuto
es un hecho, lo que se dijo es una intencion") -- y nada lo delataba.

Lo que se fija aca:
  1. se leen los pasos REALES de la grabacion abierta (API real: abiertas() +
     cargar(id));
  2. se descartan los pasos que fallaron y los que llegaron por el bus con los
     args recortados a 120 chars;
  3. un grabador que revienta AVISA y no mata el turno;
  4. al terminar se abre el editor, y la politica de apertura se respeta
     (config, COGNIA_REMOTO y --no-abrir);
  5. '--no-abrir' no se queda DENTRO del nombre del flujo.

Ni modelo ni red: `flujo_ia.de_sesion` se inyecta. La flujoteca va a tmp_path
con una fixture AUTOUSE, igual que en tests/test_flujoteca.py: sin eso, un
test escribe en la biblioteca real del dueno.
"""

import pytest

import cognia.cli as cli
from cognia.agent import flujo_ia
from cognia.flujos import grabador


# ---------------------------------------------------------------------------
# Aislamiento
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    """Flujoteca, config y estado del REPL, todo de mentira. Autouse."""
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    monkeypatch.setattr(cli, "_history", [{"role": "user", "content": "hola"}])
    return tmp_path


FLUJO = {"nombre": "informe", "nodos": [
    {"id": "leer", "tool": "leer_archivo", "args": "notas.md", "wires": []}]}


def _resultado(nombre="informe"):
    return flujo_ia.Resultado(ok=True, flujo={**FLUJO, "nombre": nombre},
                              motivo="ok", resumen="un flujo", ms=5,
                              modelo="falso")


def _espiar_de_sesion(monkeypatch, visto):
    def _falso(historial, **kw):
        visto.append(kw)
        return _resultado(kw.get("nombre") or "informe")

    monkeypatch.setattr(flujo_ia, "de_sesion", _falso)
    return visto


def _espiar_apertura(monkeypatch, abiertos):
    def _falso(nombre, *, forzar_visor=False):
        abiertos.append((nombre, forzar_visor))
        return {"ok": True, "que": "editor", "ruta": "http://127.0.0.1:1",
                "url": "http://127.0.0.1:1/?t=SECRETO", "abierto": True,
                "motivo": ""}

    monkeypatch.setattr(cli, "_abrir_editor_flujo", _falso)
    return abiertos


def _grabacion(pasos):
    return grabador.Grabacion(id="g1", titulo="t", pasos=list(pasos))


# ---------------------------------------------------------------------------
# 1-2. El puente con el grabador
# ---------------------------------------------------------------------------

def test_usa_los_pasos_reales_de_la_grabacion_abierta(monkeypatch):
    """El bug de `grabacion_activa`: `pasos` llegaba SIEMPRE vacio."""
    visto = _espiar_de_sesion(monkeypatch, [])
    _espiar_apertura(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: ["g0", "g1"])
    monkeypatch.setattr(grabador, "cargar", lambda gid: _grabacion([
        {"tool": "leer_archivo", "args": "a.md", "ok": True, "via_bus": False},
        {"tool": "escribir_archivo", "args": "b.md", "ok": True,
         "via_bus": False}]))

    cli._slash_session_to_workflow("informe")

    assert visto, "de_sesion ni se llamo"
    pasos = visto[0].get("pasos_reales")
    assert pasos, "los pasos reales siguen llegando vacios (el bug de origen)"
    assert [p["tool"] for p in pasos] == ["leer_archivo", "escribir_archivo"]


def test_descarta_pasos_fallidos_y_via_bus(monkeypatch, capsys):
    """Un paso que fallo no es un procedimiento, y un paso del bus trae los
    args recortados a 120 chars: guardarlos daria un flujo que corre mal."""
    visto = _espiar_de_sesion(monkeypatch, [])
    _espiar_apertura(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: ["g1"])
    monkeypatch.setattr(grabador, "cargar", lambda gid: _grabacion([
        {"tool": "bueno", "args": "x", "ok": True, "via_bus": False},
        {"tool": "fallido", "args": "x", "ok": False, "via_bus": False},
        {"tool": "recortado", "args": "x", "ok": True, "via_bus": True}]))

    cli._slash_session_to_workflow("informe")

    assert [p["tool"] for p in visto[0]["pasos_reales"]] == ["bueno"]
    salida = capsys.readouterr().out
    # Y se DICE: descartar en silencio es indistinguible de "no habia nada".
    assert "bus" in salida and "fallaron" in salida


def test_grabador_que_explota_avisa_y_no_mata_el_turno(monkeypatch):
    """El `except` se tragaba el error: la unica senal de que el puente estaba
    roto era un flujo peor, y eso no se ve."""
    visto = _espiar_de_sesion(monkeypatch, [])
    _espiar_apertura(monkeypatch, [])
    gritos = []
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, detalle="": gritos.append((via, detalle)))

    def _revienta():
        raise RuntimeError("disco muerto")

    monkeypatch.setattr(grabador, "abiertas", _revienta)

    cli._slash_session_to_workflow("informe")     # no lanza

    assert any(v == "cli.s2w.grabador" for v, _d in gritos), gritos
    assert visto, "el turno siguio y el flujo se genero igual"
    assert visto[0]["pasos_reales"] == []


# ---------------------------------------------------------------------------
# 3. La apertura al terminar
# ---------------------------------------------------------------------------

def test_abre_el_editor_al_terminar(monkeypatch, capsys):
    _espiar_de_sesion(monkeypatch, [])
    abiertos = _espiar_apertura(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: [])

    cli._slash_session_to_workflow("informe")

    assert abiertos == [("informe", False)], abiertos
    # El GUARDADO ya ocurrio y se dijo ANTES: un fallo al abrir jamas puede
    # parecer que el flujo no se guardo.
    assert "guardado como v1" in capsys.readouterr().out


def test_no_abre_si_memorias_abrir_navegador_es_false(monkeypatch):
    """La politica esta centralizada en _abrir_en_navegador: aca se comprueba
    de verdad, no contra el doble."""
    _espiar_de_sesion(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: [])
    cli._save_config({**cli._CONFIG_DEFAULTS, "memorias_abrir_navegador": False})
    vistas = []
    monkeypatch.setattr(cli, "_flujoteca_pintar_apertura",
                        lambda nombre, res: vistas.append(res))

    def _sin_editor(*a, **k):
        raise AssertionError("no deberia levantarse el editor")

    monkeypatch.setattr("cognia.agent.flujoteca_editor.abrir", _sin_editor)
    monkeypatch.setattr("cognia.agent.flujoteca_view.export",
                        lambda nombre, open_browser=True: "C:/x/lienzo.html")

    cli._slash_session_to_workflow("informe")

    assert vistas and vistas[0]["que"] == "visor"
    assert vistas[0]["abierto"] is False


def test_bajo_remoto_no_abre_ventana(monkeypatch):
    """COGNIA_REMOTO=1: el REPL es hijo del servidor del movil y una ventana se
    abriria en la maquina equivocada."""
    _espiar_de_sesion(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: [])
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    vistas = []
    monkeypatch.setattr(cli, "_flujoteca_pintar_apertura",
                        lambda nombre, res: vistas.append(res))
    monkeypatch.setattr("cognia.agent.flujoteca_view.export",
                        lambda nombre, open_browser=True: "C:/x/lienzo.html")

    assert cli._abrir_en_navegador() is False
    cli._slash_session_to_workflow("informe")

    assert vistas and vistas[0]["abierto"] is False


# ---------------------------------------------------------------------------
# 4. El flag no contamina el nombre
# ---------------------------------------------------------------------------

def test_flag_no_abrir_no_contamina_el_nombre(monkeypatch):
    """Hasta hoy `nombre = arg.strip()` se tragaba el flag ENTERO y el flujo se
    llamaba 'informe --no-abrir'."""
    visto = _espiar_de_sesion(monkeypatch, [])
    abiertos = _espiar_apertura(monkeypatch, [])
    monkeypatch.setattr(grabador, "abiertas", lambda: [])

    cli._slash_session_to_workflow("informe semanal --no-abrir")

    assert visto[0]["nombre"] == "informe semanal"
    assert abiertos == [], "con --no-abrir no se abre nada"
    from cognia.agent import flujoteca as ft
    assert [f["nombre"] for f in ft.listar()] == ["informe semanal"]


def test_el_alias_castellano_esta_cableado():
    """'/sesion-a-workflow' es como lo llama el dueno y hasta hoy contestaba
    'Comando desconocido'."""
    import inspect
    fuente = inspect.getsource(cli)
    assert '"/sesion-a-workflow"' in fuente
    assert "/sesion-a-workflow" in cli._CMD_DESCRIPTIONS
