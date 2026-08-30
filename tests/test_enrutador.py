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


@pytest.fixture(autouse=True)
def _cache_limpia():
    """decidir() cachea la decision de cada mensaje durante toda la SESION
    (LRU de 128, PLAN2 PEDIDO 2 escalon 4). Sin vaciarla entre tests, el
    segundo test que use el mismo mensaje leeria la decision del primero --
    con otro infer_fn falso -- y estaria pasando por el motivo equivocado."""
    from cognia.enrutador import invalidar_cache, reset_contadores
    invalidar_cache()
    reset_contadores()
    yield
    invalidar_cache()
    reset_contadores()

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
    from cognia.enrutador import invalidar_cache
    assert decidir("x y z", lambda p: "RUTA: CHAT", CATALOGO)[0] == "chat"
    invalidar_cache()   # mismo mensaje, otra salida del fake: sin esto gana la cache
    assert decidir("x y z", lambda p: "RUTA: AGENTE", CATALOGO)[0] == "agente"


def test_comando_inexistente_cae_a_chat():
    ruta, _ = decidir("x", lambda p: "RUTA: /formatear_disco ya", CATALOGO)
    assert ruta == "chat"


def test_vetados_caen_a_chat():
    cat = CATALOGO + "\n/salir — Salir del REPL"
    ruta, _ = decidir("x", lambda p: "RUTA: /salir", cat)
    assert ruta == "chat"


def test_salida_basura_cae_a_chat():
    from cognia.enrutador import invalidar_cache
    for i, basura in enumerate(("", "no se", "RUTA:", "???", None)):
        invalidar_cache()
        fn = (lambda b: (lambda p: b))(basura)
        assert decidir("x", fn, CATALOGO)[0] == "chat", basura


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
    # los fallos NO se cachean a proposito (un backend que vuelve tiene que
    # poder volver a decidir): por eso las dos llamadas llegan al infer_fn
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
    from cognia.enrutador import invalidar_cache
    invalidar_cache()
    assert decidir("x", lambda p: "RUTA: yolo", CATALOGO)[0] == "chat"


def test_invalidar_catalogo_deja_ver_el_nuevo_nivel():
    """REGRESION 2026-08-29. `catalogo_compacto` cachea en un global eterno
    ('el catalogo no cambia en runtime'), pero desde /avanzado y /modo SI
    cambia: el CLI le pasa el dict FILTRADO. Sin `invalidar_catalogo()` el
    enrutador se queda con el catalogo del arranque hasta reiniciar, y el
    sintoma es que cambiar de nivel 'no hace nada' -- sin ningun error."""
    import cognia.enrutador as enr

    enr.invalidar_catalogo()
    corto = enr.catalogo_compacto({"/pensar": "Razonar"})
    assert "/pensar" in corto and "/stats" not in corto

    # sin invalidar, el cache manda (esta es la mitad que fallaba)
    assert enr.catalogo_compacto({"/stats": "Stats"}) == corto

    enr.invalidar_catalogo()
    largo = enr.catalogo_compacto({"/pensar": "Razonar", "/stats": "Stats"})
    assert "/stats" in largo
    enr.invalidar_catalogo()   # no dejar el cache puesto para el resto


def test_el_cli_encuentra_invalidar_catalogo():
    """F-CABLE la llama con getattr para no depender del orden de las fases:
    ese getattr tolerante haria invisible que la funcion no exista. Aqui se
    comprueba que existe de verdad y que el CLI la nombra."""
    import inspect
    import cognia.enrutador as enr
    from cognia import cli

    assert callable(getattr(enr, "invalidar_catalogo", None))
    assert "invalidar_catalogo" in inspect.getsource(cli._invalidar_caches_de_nivel)
