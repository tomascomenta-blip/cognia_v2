"""
Tests for the research-engine relevance layer.

Pins the three failures measured on the 2026-07-19 research run:
  - ranking by stars put a 2019 W3C report above actual language models
  - a 6-term query returned zero results and the scraper gave up silently
  - HuggingFace was never consulted, so model questions only found tutorials

Offline: no network, no LLM.
"""

import pytest

from cognia.research_engine import relevance
from cognia.research_engine.hf_scraper import ModelContent
from cognia.research_engine.query_planner import (
    planificar_deterministico,
    terminos_de_busqueda,
)

# La query real que fallo, y los dos resultados reales que devolvio.
QUERY_MEDIDA = "long context small language model"

REPO_RUIDO = {
    "full_name": "jettbrains/-L-",
    "description": "W3C Strategic Highlights September 2019",
    "topics": [],
    "stargazers_count": 149,
}
REPO_BUENO = {
    "full_name": "ArkS0001/SmolLM3-3B",
    "description": ("SmolLM3 is a 3B parameter language model designed to push the "
                    "boundaries of small models. It supports dual mode reasoning and long context."),
    "topics": [],
    "stargazers_count": 1,
}


def _texto(item):
    return " ".join([item["full_name"], item["description"], " ".join(item["topics"])])


def _estrellas(item):
    return item["stargazers_count"]


# ── Puntuacion ──────────────────────────────────────────────────────────

def test_tokenizar_quita_stopwords_es_y_en():
    assert relevance.tokenizar("el mejor modelo de lenguaje") == ["modelo", "lenguaje"]
    assert relevance.tokenizar("the best language model") == ["language", "model"]


def test_cobertura_cuenta_terminos_presentes():
    assert relevance.cobertura(["long", "context"], "a long context window") == 1.0
    assert relevance.cobertura(["long", "context"], "a long window") == 0.5
    assert relevance.cobertura([], "cualquier cosa") == 1.0


def test_repo_relevante_gana_al_popular_pero_irrelevante():
    """La regresion principal: ordenar por estrellas ponia el W3C primero."""
    terminos = relevance.tokenizar(QUERY_MEDIDA)
    p_ruido  = relevance.puntuar(terminos, _texto(REPO_RUIDO), _estrellas(REPO_RUIDO))
    p_bueno  = relevance.puntuar(terminos, _texto(REPO_BUENO), _estrellas(REPO_BUENO))
    assert p_bueno > p_ruido, f"SmolLM3 ({p_bueno}) deberia ganar al W3C ({p_ruido})"


def test_filtrar_y_ordenar_descarta_el_ruido():
    items = [REPO_RUIDO, REPO_BUENO]
    out = relevance.filtrar_y_ordenar(items, QUERY_MEDIDA, _texto, _estrellas)
    assert out, "no deberia quedar vacio"
    assert out[0]["full_name"] == "ArkS0001/SmolLM3-3B"
    assert REPO_RUIDO not in out, "el informe del W3C no cubre los terminos minimos"


def test_popularidad_desempata_entre_igual_de_relevantes():
    a = dict(REPO_BUENO, full_name="a/x", stargazers_count=10)
    b = dict(REPO_BUENO, full_name="b/x", stargazers_count=5000)
    out = relevance.filtrar_y_ordenar([a, b], QUERY_MEDIDA, _texto, _estrellas)
    assert out[0]["full_name"] == "b/x"


# ── Degradacion de queries ──────────────────────────────────────────────

def test_degradar_query_acorta_progresivamente():
    """La query de 6 terminos que devolvia 0 resultados."""
    original = "linear attention hybrid mamba language model"
    reducidas = list(relevance.degradar_query(original))

    assert reducidas, "deberia generar reintentos"
    largos = [len(q.split()) for q in reducidas]
    assert largos == sorted(largos, reverse=True), "cada reintento debe ser mas corto"
    assert largos[0] == 5 and largos[-1] == 1
    # Conserva los terminos informativos, tira los genericos primero.
    assert "attention" in reducidas[-1]


def test_degradar_query_de_un_termino_no_genera_nada():
    assert list(relevance.degradar_query("mamba")) == []
    assert list(relevance.degradar_query("the")) == []


# ── KV cache desde config.json ──────────────────────────────────────────

def test_kv_bytes_por_token_gqa():
    """Llama-3.1-8B: 32 capas, 8 cabezas KV, head_dim 128 -> 131072 B/token fp16."""
    m = ModelContent(
        model_id="meta-llama/Llama-3.1-8B", model_url="", author="", descripcion="",
        card="", downloads=0, likes=0, pipeline_tag="",
        config={
            "num_hidden_layers": 32,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "hidden_size": 4096,
            "max_position_embeddings": 131072,
        },
    )
    assert m.kv_bytes_por_token() == 32 * 8 * 128 * 2 * 2 == 131072
    assert m.kv_gb(131072) == pytest.approx(16.0, rel=1e-3)
    assert m.contexto_declarado() == 131072
    assert "GQA 32:8" in m.arquitectura()


def test_kv_bytes_usa_head_dim_explicito_si_existe():
    """Cuando head_dim no es hidden_size/heads hay que respetar el del config."""
    m = ModelContent(
        model_id="x/y", model_url="", author="", descripcion="", card="",
        downloads=0, likes=0, pipeline_tag="",
        config={
            "num_hidden_layers": 2, "num_attention_heads": 4,
            "num_key_value_heads": 2, "hidden_size": 64, "head_dim": 256,
        },
    )
    assert m.kv_bytes_por_token() == 2 * 2 * 256 * 2 * 2


def test_kv_bytes_none_sin_config():
    m = ModelContent(model_id="x/y", model_url="", author="", descripcion="",
                     card="", downloads=0, likes=0, pipeline_tag="", config={})
    assert m.kv_bytes_por_token() is None
    assert m.kv_gb(1000) is None


def test_gguf_se_detecta_por_los_archivos():
    m = ModelContent(model_id="x/y", model_url="", author="", descripcion="",
                     card="", downloads=0, likes=0, pipeline_tag="",
                     archivos=["README.md", "modelo-Q4_K_M.gguf"])
    assert m.tiene_gguf()
    m.archivos = ["README.md", "model.safetensors"]
    assert not m.tiene_gguf()


# ── Planificador de queries ─────────────────────────────────────────────

def test_planificador_traduce_y_acorta():
    """Una pregunta larga en espanol debe salir como queries cortas en ingles."""
    queries = planificar_deterministico(
        "que modelo pequeno puede manejar el maximo contexto posible", n=5
    )
    assert len(queries) == 5
    for q in queries:
        assert len(q.split()) <= 5, f"'{q}' es demasiado larga, la API hace AND"
        assert q == q.lower()
    junto = " ".join(queries)
    assert "context" in junto and "model" in junto, "debio traducir del espanol"
    assert "modelo" not in junto and "contexto" not in junto


def test_planificador_cubre_facetas_distintas():
    queries = planificar_deterministico("small model long context", n=4)
    assert len(set(queries)) == len(queries), "las queries no deben repetirse"


def test_planificador_sin_terminos_utiles():
    assert planificar_deterministico("de la que", n=3) == []


def test_planificador_lleva_sustantivo_y_modificador():
    """Solo modificadores ('small maximum') no busca nada util."""
    queries = planificar_deterministico("modelo pequeno con maximo contexto", n=1)
    nucleo = queries[0].split()
    assert "model" in nucleo or "context" in nucleo, "falta el sustantivo"
    assert "small" in nucleo, "falta el modificador"


# ── Pregunta en espanol, resultados en ingles ───────────────────────────

PREGUNTA_ES = "que modelo pequeno maneja mas contexto por byte de memoria en CPU"


def test_terminos_de_busqueda_traduce_la_pregunta():
    terminos = terminos_de_busqueda(PREGUNTA_ES)
    assert "model" in terminos and "small" in terminos and "context" in terminos
    assert "modelo" not in terminos and "contexto" not in terminos


RELEVANTE_EN = ("rwandantechy/EdgeAI_SmallOpen_LLMs curated repository for benchmarking "
                "small open source language models optimized for edge CPU low memory")
POPULAR_AJENO = "cirosantilli/china-dictatorship Anti Chinese government propaganda"


def test_traducir_la_pregunta_sube_la_cobertura_real():
    """
    Lo que aporta traducir: sin ello la mayoria de los terminos de una
    pregunta en espanol no matchea nada de un resultado en ingles, aunque
    'cpu' y 'byte' coincidan por casualidad en los dos idiomas.
    """
    crudos     = relevance.tokenizar(PREGUNTA_ES)
    traducidos = terminos_de_busqueda(PREGUNTA_ES)
    assert (relevance.cobertura(traducidos, RELEVANTE_EN)
            > relevance.cobertura(crudos, RELEVANTE_EN))


def test_pregunta_en_espanol_no_deja_ganar_al_popular_irrelevante():
    """
    La regresion medida: 'china-dictatorship' (3106 estrellas) encabezaba una
    busqueda de modelos de lenguaje pequenos para CPU. Debe perder con la
    pregunta traducida y tambien sin traducir.
    """
    for terminos in (relevance.tokenizar(PREGUNTA_ES), terminos_de_busqueda(PREGUNTA_ES)):
        assert (relevance.puntuar(terminos, RELEVANTE_EN, 3)
                > relevance.puntuar(terminos, POPULAR_AJENO, 3106))


def test_popularidad_nunca_compensa_un_termino_de_menos():
    """
    Invariante del scoring. Sin ella, con preguntas largas la cobertura se
    diluye (cada termino vale poco) y un repo famoso y ajeno gana igual.
    """
    terminos = ["small", "model", "context", "memory", "cpu",
                "window", "quality", "byte", "inference", "long"]
    # Acierta 2 de 10 terminos y no lo conoce nadie.
    poco_pop = relevance.puntuar(terminos, "small model", 0)
    # Acierta 1 de 10 y tiene 10 millones de estrellas.
    muy_pop  = relevance.puntuar(terminos, "small", 10_000_000)
    assert poco_pop > muy_pop, "un termino mas debe ganarle a cualquier popularidad"


def test_texto_gigante_no_gana_por_acumular_coincidencias():
    """
    La descripcion de GitHub de 'china-dictatorship' tiene 64.765 caracteres.
    Sin tope de longitud matcheaba 5 de 10 terminos por azar y encabezaba la
    busqueda. Un texto largo y ajeno no puede ganarle a uno corto y al tema.
    """
    terminos = terminos_de_busqueda(PREGUNTA_ES)

    # Documento enorme: los terminos aparecen, pero tarde y sin relacion.
    relleno = "propaganda politica y noticias varias. " * 400
    gigante = "cirosantilli/china-dictatorship " + relleno + \
              " model small window quality cpu"
    assert len(gigante) > 10_000

    corto = "EdgeAI small language models for CPU with low memory context window"

    assert relevance.cobertura(terminos, corto) > relevance.cobertura(terminos, gigante)
    assert relevance.puntuar(terminos, corto, 3) > relevance.puntuar(terminos, gigante, 3106)


def test_resultado_sin_ningun_termino_se_descarta():
    traducidos = terminos_de_busqueda(PREGUNTA_ES)
    assert relevance.cobertura(traducidos, "Anti Chinese government propaganda") == 0.0
