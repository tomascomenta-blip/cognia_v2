"""
Enrutador por inferencia (goal 2026-07-21): el modelo elige la ruta sobre
TODO el catalogo. Aqui se fija el contrato SIN modelo (infer_fn fake):
parseo estricto, validacion contra el catalogo, vetados y fallback a chat.
El E2E con modelo real vive en la verificacion del REPL.
"""
import pytest

import cognia.backend_activo as backend_activo
from cognia.enrutador import decidir, catalogo_compacto, _VETADOS


@pytest.fixture(autouse=True)
def _audit_a_tmp(tmp_path, monkeypatch):
    """decidir() ahora audita sin_backend cuando no hubo inferencia: que los
    tests NO escriban en el ~/.cognia/backend_audit.jsonl real."""
    monkeypatch.setattr(backend_activo, "AUDIT", tmp_path / "backend_audit.jsonl")

CATALOGO = ("\n".join([
    "/pensar — Razonamiento PROFUNDO con modelo thinking  <pregunta>",
    "/investigar — Investigar en GitHub <query>",
    "/crear — Crear programa ahora <idea>",
    "/stats — Estadisticas de la sesion",
]))


def test_ruta_comando_valida():
    ruta, extra = decidir("investiga sobre transformers",
                          lambda p: "RUTA: /investigar transformers", CATALOGO)
    assert (ruta, extra) == ("comando", "/investigar transformers")


def test_ruta_chat_y_agente():
    assert decidir("x y z", lambda p: "RUTA: CHAT", CATALOGO)[0] == "chat"
    assert decidir("x y z", lambda p: "RUTA: AGENTE", CATALOGO)[0] == "agente"


def test_comando_inexistente_cae_a_chat():
    ruta, _ = decidir("x", lambda p: "RUTA: /formatear_disco ya", CATALOGO)
    assert ruta == "chat"


def test_vetados_caen_a_chat():
    cat = CATALOGO + "\n/salir — Salir del REPL"
    ruta, _ = decidir("x", lambda p: "RUTA: /salir", cat)
    assert ruta == "chat"


def test_salida_basura_cae_a_chat():
    for basura in ("", "no se", "RUTA:", "???", None):
        fn = (lambda b: (lambda p: b))(basura)
        assert decidir("x", fn, CATALOGO)[0] == "chat"


def test_infer_que_lanza_cae_a_chat():
    def explota(p):
        raise RuntimeError("backend caido")
    assert decidir("x", explota, CATALOGO)[0] == "chat"


def test_tolera_ruido_alrededor():
    crudo = "  \nRUTA: /pensar cuanto es 2+2?  \nokay eso elegi"
    ruta, extra = decidir("x", lambda p: crudo, CATALOGO)
    assert ruta == "comando" and extra.startswith("/pensar cuanto es 2+2")


def test_catalogo_compacto_excluye_vetados():
    cat = catalogo_compacto({"/pensar": "Razonar", "/salir": "Salir",
                             "/stats": "Stats"})
    assert "/pensar" in cat and "/stats" in cat
    assert "/salir" not in cat
    for v in _VETADOS:
        assert v not in cat


def test_sin_inferencia_audita_sin_modelo(monkeypatch):
    """REGRESION 2026-08-01: decidir() devolvia ('chat','') identico con modelo
    que sin inferencia — un backend caido enrutaba todo a chat sin rastro.
    Ahora crudo vacio o excepcion dejan sin_backend('enrutador', 'sin_modelo...')
    en el audit; la basura NO vacia sigue siendo decision (sin audit)."""
    llamadas = []
    monkeypatch.setattr(backend_activo, "sin_backend",
                        lambda via, detalle="": llamadas.append((via, detalle)))

    def explota(p):
        raise RuntimeError("backend caido")
    assert decidir("x", explota, CATALOGO)[0] == "chat"
    assert decidir("x", lambda p: "", CATALOGO)[0] == "chat"
    assert len(llamadas) == 2
    assert all(v == "enrutador" and "sin_modelo" in d for v, d in llamadas)

    llamadas.clear()
    assert decidir("x", lambda p: "no se", CATALOGO)[0] == "chat"
    assert llamadas == []   # el modelo SI contesto: chat es decision, no fallo


def test_argumentos_pierden_las_comillas():
    """El modelo entrecomilla los argumentos y /crear terminaba con la idea
    entre comillas. Se pelan al validar el comando."""
    ruta, extra = decidir(
        "x", lambda p: 'RUTA: /crear "un juego de la serpiente"', CATALOGO)
    assert (ruta, extra) == ("comando", "/crear un juego de la serpiente")


def test_barra_omitida_se_repara():
    """El 7B a veces responde 'RUTA: stats' sin la barra (medido): si el
    comando existe en el catalogo, se acepta igual."""
    ruta, extra = decidir("x", lambda p: "RUTA: stats", CATALOGO)
    assert (ruta, extra) == ("comando", "/stats")
    # pero un token que NO existe sigue cayendo a chat
    assert decidir("x", lambda p: "RUTA: yolo", CATALOGO)[0] == "chat"
