"""Regresion exp021/cycle34: _spec_args() arma --spec-type ngram-mod por defecto,
es desactivable, y PROHIBE draft-* (un draft model separado en CPU bandwidth-bound
mide 0.37x en habla — exp021). Falla sin el fix (la funcion no existia)."""
from node.llama_backend import _spec_args


def test_default_es_ngram_mod(monkeypatch):
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    assert _spec_args() == ["--spec-type", "ngram-mod"]


def test_none_desactiva(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "none")
    assert _spec_args() == []


def test_override_ngram_simple(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "ngram-simple")
    assert _spec_args() == ["--spec-type", "ngram-simple"]


def test_draft_separado_prohibido(monkeypatch):
    # draft-* compite por banda/nucleos en CPU (exp021: 0.37x en habla) -> nunca al server
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-simple")
    assert _spec_args() == []
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-eagle3")
    assert _spec_args() == []


def test_basura_ignorada(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "evil; rm -rf /")
    assert _spec_args() == []

# ── MTP nativo (2026-08-18) ───────────────────────────────────────────────────
# La cabeza de draft viaja DENTRO del gguf, asi que no es un "draft separado" y
# la prohibicion de arriba no le aplica. Medido en Qwythos-9B: 1,75x en codigo,
# 1,32x en prosa con n-max 2 (con n-max 6 la prosa cae a 0,78x). En la misma
# corrida ngram-mod acepto 0% en la primera peticion.

def _con_cabeza(monkeypatch, capas=1):
    """gguf que DECLARA cabeza MTP (nextn_predict_layers)."""
    import cognia.agent.gguf_meta as GM
    monkeypatch.setattr(GM, "meta", lambda ruta: {"arch": "qwen35",
                                                  "mtp_capas": capas})


def _sin_cabeza(monkeypatch):
    import cognia.agent.gguf_meta as GM
    monkeypatch.setattr(GM, "meta", lambda ruta: {"arch": "nemotron_h_moe"})


def test_default_con_cabeza_es_mtp_n_max_2(monkeypatch):
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    _con_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == ["--spec-type", "draft-mtp",
                                    "--spec-draft-n-max", "2"]


def test_default_sin_cabeza_sigue_siendo_ngram_mod(monkeypatch):
    # CONTRAFACTUAL: un modelo sin cabeza no cambia de comportamiento.
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    _sin_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == ["--spec-type", "ngram-mod"]


def test_sin_ruta_no_cambia_nada(monkeypatch):
    # El llamador viejo (sin gguf_path) tiene que seguir dando ngram-mod: es
    # lo que verifica exp021/verify_spec_wiring.py.
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    assert _spec_args() == ["--spec-type", "ngram-mod"]


def test_mtp_pedido_sin_cabeza_no_se_manda_al_server(monkeypatch):
    # El fallo que evita: el server ACEPTA draft-mtp sin cabeza, no acelera y
    # no dice nada. Preferimos ngram-mod y un warning.
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-mtp")
    _sin_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == ["--spec-type", "ngram-mod"]


def test_mtp_pedido_con_cabeza_vale(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "draft-mtp")
    _con_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == ["--spec-type", "draft-mtp",
                                    "--spec-draft-n-max", "2"]


def test_none_gana_incluso_con_cabeza(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "none")
    _con_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == []


def test_ngram_explicito_gana_a_la_cabeza(monkeypatch):
    # Quien necesite salida BIT-IDENTICA tiene esta puerta: MTP diverge en una
    # palabra por batching, ngram-mod no.
    monkeypatch.setenv("COGNIA_SPEC_TYPE", "ngram-mod")
    _con_cabeza(monkeypatch)
    assert _spec_args("x.gguf") == ["--spec-type", "ngram-mod"]


def test_el_draft_separado_sigue_prohibido_con_cabeza(monkeypatch):
    # Tener cabeza MTP no abre la puerta a los draft externos.
    _con_cabeza(monkeypatch)
    for malo in ("draft-simple", "draft-eagle3", "draft-dflash"):
        monkeypatch.setenv("COGNIA_SPEC_TYPE", malo)
        assert _spec_args("x.gguf") == [], malo


def test_gguf_ilegible_no_revienta(monkeypatch):
    # Es un backstop, no un requisito: si meta() lanza, se cae al default.
    import cognia.agent.gguf_meta as GM

    def explota(ruta):
        raise OSError("fichero ocupado")

    monkeypatch.setattr(GM, "meta", explota)
    monkeypatch.delenv("COGNIA_SPEC_TYPE", raising=False)
    assert _spec_args("x.gguf") == ["--spec-type", "ngram-mod"]
