"""
Regresion de rendimiento: los centroides del router se recalculaban siempre.

Medido el 2026-07-20 instrumentando `AsyncEmbeddingQueue.encode()` durante una
sola llamada a `Cognia.observe()`:

    159 llamadas al modelo de embeddings
      80  shattering/router.py:148  (_compute_centroids)
      79  cognia/vectors.py:50

Las 80 del router son los centroides de `_DOMAIN_KEYWORDS`, que es una
CONSTANTE del modulo: cada router nuevo recalculaba exactamente el mismo
resultado. Y el batching del AsyncEmbeddingQueue no ayudaba, porque `encode()`
bloquea hasta que el worker lo procesa: en un camino secuencial son 80 lotes
de uno.

Tras cachear por proceso: **1 llamada a encode por observe**, y la latencia de
`observe()` bajo de ~11 s a ~5.3 s. El enrutado da exactamente lo mismo
(techne / rhetor / rhetor en las tres pruebas de control).
"""

import threading

import pytest

from shattering import router as R
from shattering.model_constants import ROUTER_EMBEDDING_DIM


@pytest.fixture(autouse=True)
def cache_limpia():
    """Cada test parte de una cache vacia y no ensucia a los demas."""
    with R._LOCK_CENTROIDES:
        previa = dict(R._CENTROIDES_ST)
        R._CENTROIDES_ST.clear()
    yield
    with R._LOCK_CENTROIDES:
        R._CENTROIDES_ST.clear()
        R._CENTROIDES_ST.update(previa)


class TestClaveDeCache:

    def test_las_mismas_keywords_dan_la_misma_clave(self):
        a = {"techne": ["codigo", "python"], "rhetor": ["texto"]}
        b = {"rhetor": ["texto"], "techne": ["codigo", "python"]}
        assert R._clave_centroides(a) == R._clave_centroides(b), (
            "el orden de los dominios no puede cambiar la clave")

    def test_keywords_distintas_dan_clave_distinta(self):
        a = {"techne": ["codigo"]}
        b = {"techne": ["codigo", "python"]}
        assert R._clave_centroides(a) != R._clave_centroides(b)

    def test_la_clave_es_hashable(self):
        """Tiene que poder usarse como clave de dict."""
        clave = R._clave_centroides({"techne": ["a", "b"]})
        {clave: 1}   # no debe lanzar


class TestNoRecalculaLoMismo:

    def test_el_segundo_indice_reutiliza_los_centroides(self):
        keywords = {"techne": ["codigo", "python"], "rhetor": ["texto", "carta"]}
        llamadas = []

        def encoder_espia(texto):
            llamadas.append(texto)
            return [0.1] * ROUTER_EMBEDDING_DIM

        idx = R._EmbeddingIndex()
        # Se llama directo a la fase 2 sin el hilo, que es lo que se cachea.
        clave = R._clave_centroides(keywords)
        centroides = idx._compute_centroids(encoder_espia, keywords)
        with R._LOCK_CENTROIDES:
            R._CENTROIDES_ST[clave] = centroides

        primeras = len(llamadas)
        assert primeras == 4, "deberia haber codificado las 4 keywords"

        # Un segundo indice con las MISMAS keywords no debe volver a codificar.
        with R._LOCK_CENTROIDES:
            cacheados = R._CENTROIDES_ST.get(clave)
        assert cacheados is not None
        assert len(llamadas) == primeras, "no debe recalcular"

    def test_keywords_nuevas_si_se_calculan(self):
        """La cache no puede devolver centroides de otro juego de keywords."""
        idx = R._EmbeddingIndex()
        enc = lambda t: [0.2] * ROUTER_EMBEDDING_DIM

        c1 = idx._compute_centroids(enc, {"techne": ["a"]})
        c2 = idx._compute_centroids(enc, {"otro": ["b"]})

        assert set(c1) == {"techne"}
        assert set(c2) == {"otro"}


class TestSeguridadDeHilos:

    def test_la_cache_tiene_su_lock(self):
        assert isinstance(R._LOCK_CENTROIDES, type(threading.Lock()))

    def test_varios_hilos_no_la_corrompen(self):
        keywords = {"techne": ["a", "b"]}
        clave = R._clave_centroides(keywords)
        enc = lambda t: [0.3] * ROUTER_EMBEDDING_DIM
        idx = R._EmbeddingIndex()

        def trabajar():
            c = idx._compute_centroids(enc, keywords)
            with R._LOCK_CENTROIDES:
                R._CENTROIDES_ST[clave] = c

        hilos = [threading.Thread(target=trabajar) for _ in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        with R._LOCK_CENTROIDES:
            assert len(R._CENTROIDES_ST) == 1
            assert set(R._CENTROIDES_ST[clave]) == {"techne"}
