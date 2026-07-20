"""
tests/test_analogy_engine.py
============================
Tests del motor de analogias transversales (cognia/reasoning/analogy_engine.py).

find_analogies se prueba con un orchestrator FAKE (doble de test, NO mock de
produccion): solo necesita .infer() devolviendo un objeto con .text, que es por
donde creative_generate habla con el backend. _parse_analogies se prueba directo
sobre strings.
"""

import cognia.reasoning.analogy_engine as ae


# ── _parse_analogies ─────────────────────────────────────────────────────────

_TRES_BLOQUES = (
    "DOMINIO: biologia\n"
    "ANALOGIA: el sistema inmune satura sus recursos ante demasiados antigenos\n"
    "SOLUCION: prioriza amenazas y descarta lo redundante\n"
    "ADAPTACION: priorizar tokens relevantes y descartar contexto redundante\n"
    "---\n"
    "DOMINIO: economia\n"
    "ANALOGIA: un mercado se satura de oferta y baja el valor de cada unidad\n"
    "SOLUCION: regula la oferta y segmenta la demanda\n"
    "ADAPTACION: regular cuanto contexto entra y segmentarlo por relevancia\n"
    "---\n"
    "DOMINIO: logistica\n"
    "ANALOGIA: un deposito se llena y bloquea el flujo de mercaderia\n"
    "SOLUCION: rota stock viejo y usa un buffer de transito\n"
    "ADAPTACION: rotar contexto viejo y mantener un buffer de trabajo acotado\n"
    "---\n"
)


def test_parse_tres_bloques_bien_formados():
    bloques = ae._parse_analogies(_TRES_BLOQUES, ["biologia", "economia", "logistica"])
    assert len(bloques) == 3
    assert [b["dominio"] for b in bloques] == ["biologia", "economia", "logistica"]
    assert bloques[0]["analogia"].startswith("el sistema inmune")
    assert bloques[0]["solucion"].startswith("prioriza amenazas")
    assert bloques[0]["adaptacion"].startswith("priorizar tokens")


def test_parse_claves_acentos_y_mayusculas():
    # Claves en mayus/minus mezcladas y con acentos: deben casar igual.
    text = (
        "Dominio: fisica\n"
        "Analogía: un sistema se sobrecarga de energia y disipa mal el calor\n"
        "SOLUCIÓN: agrega disipadores y limita la entrada de energia\n"
        "adaptación: limitar la entrada de contexto y 'disipar' lo viejo\n"
    )
    bloques = ae._parse_analogies(text, ["fisica"])
    assert len(bloques) == 1
    assert bloques[0]["dominio"] == "fisica"
    assert bloques[0]["adaptacion"].startswith("limitar la entrada")


def test_parse_bloque_incompleto_sin_adaptacion_descartado():
    # Bloque 2 no tiene ADAPTACION -> se descarta; solo sobrevive el bloque 1.
    text = (
        "DOMINIO: biologia\n"
        "ANALOGIA: una celula acumula desechos hasta intoxicarse\n"
        "SOLUCION: autofagia, recicla lo que ya no sirve\n"
        "ADAPTACION: reciclar/descartar contexto que ya no aporta\n"
        "---\n"
        "DOMINIO: economia\n"
        "ANALOGIA: inflacion por exceso de dinero circulante\n"
        "SOLUCION: subir tasas para retirar circulante\n"
        "---\n"
    )
    bloques = ae._parse_analogies(text, ["biologia", "economia"])
    assert len(bloques) == 1
    assert bloques[0]["dominio"] == "biologia"


def test_parse_separador_por_dominio_sin_guiones():
    # Sin lineas '---': la nueva clave DOMINIO arranca el bloque siguiente.
    text = (
        "DOMINIO: ecologia\n"
        "ANALOGIA: un ecosistema se desborda por una especie invasora\n"
        "SOLUCION: introduce un control que equilibra la poblacion\n"
        "ADAPTACION: introducir un control que pode el contexto que mas crece\n"
        "DOMINIO: psicologia\n"
        "ANALOGIA: la mente se satura de estimulos y pierde foco\n"
        "SOLUCION: filtra estimulos y agrupa en chunks\n"
        "ADAPTACION: filtrar y agrupar el contexto en chunks manejables\n"
    )
    bloques = ae._parse_analogies(text, ["ecologia", "psicologia"])
    assert len(bloques) == 2
    assert [b["dominio"] for b in bloques] == ["ecologia", "psicologia"]


def test_parse_dominio_implicito_por_posicion():
    # El modelo omite DOMINIO: se asigna por posicion desde expected_domains.
    text = (
        "ANALOGIA: un rio crece y desborda el cauce\n"
        "SOLUCION: construye compuertas y canales de alivio\n"
        "ADAPTACION: derivar el exceso de contexto a un almacen secundario\n"
    )
    bloques = ae._parse_analogies(text, ["ingenieria"])
    assert len(bloques) == 1
    assert bloques[0]["dominio"] == "ingenieria"


def test_parse_vacio():
    assert ae._parse_analogies("", ["biologia"]) == []
    assert ae._parse_analogies("texto suelto sin estructura", ["biologia"]) == []


# ── doble de test ────────────────────────────────────────────────────────────

class _FakeOrchestrator:
    """Doble de test: infer() devuelve objetos con .text segun una cola de payloads.

    Acepta un payload fijo (str) o una lista de payloads (uno por llamada). Cuando
    se agota la lista, repite el ultimo (sirve para 'siempre lo mismo').
    """

    class _R:
        def __init__(self, text):
            self.text = text

    def __init__(self, payloads):
        self._queue = [payloads] if isinstance(payloads, str) else list(payloads)
        self.calls = 0

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        self.calls += 1
        if not self._queue:
            return self._R("")
        text = self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]
        return self._R(text)


# Esencia (1a llamada de find_analogies) + bloques (2a llamada). El FAKE consume
# una frase de esencia primero y luego el payload de analogias.
_ESENCIA = "Un recurso compartido se sobrecarga y degrada su rendimiento."


# ── find_analogies ───────────────────────────────────────────────────────────

def test_find_analogies_tres_bloques_dominios_correctos():
    # 1a llamada = esencia, 2a = los tres bloques bien formados.
    fake = _FakeOrchestrator([_ESENCIA, _TRES_BLOQUES])
    res = ae.find_analogies(fake, "el contexto del modelo se satura", k=3)
    assert len(res) == 3
    # Los dominios devueltos son los que el modelo escribio en cada bloque.
    assert [b["dominio"] for b in res] == ["biologia", "economia", "logistica"]
    assert all(b["analogia"] and b["adaptacion"] for b in res)


def test_find_analogies_reintento_rescata():
    # esencia, luego basura (1a generacion en server frio), luego bloques validos.
    fake = _FakeOrchestrator([_ESENCIA, "ruido sin estructura alguna util", _TRES_BLOQUES])
    res = ae.find_analogies(fake, "problema con server frio", k=3)
    assert len(res) == 3
    # esencia(1) + generacion fallida(1) + reintento(1) = 3 llamadas.
    assert fake.calls == 3


def test_find_analogies_fallo_total_es_lista_vacia():
    # El FAKE nunca devuelve bloques utiles -> [] tras el reintento (honesto).
    fake = _FakeOrchestrator("nunca hay bloques estructurados en esta respuesta larga")
    res = ae.find_analogies(fake, "problema irresoluble para el fake", k=3)
    assert res == []


def test_find_analogies_sin_orchestrator_es_vacio():
    assert ae.find_analogies(None, "cualquier problema") == []


def test_find_analogies_problem_vacio_es_vacio():
    fake = _FakeOrchestrator([_ESENCIA, _TRES_BLOQUES])
    assert ae.find_analogies(fake, "   ") == []
    assert fake.calls == 0  # cortocircuito: no llama al backend


def test_find_analogies_clamp_k():
    # k fuera de [2,6] se clampea; _pick_domains entrega esa cantidad de dominios.
    assert ae._pick_domains("problema X", 2) == ae._pick_domains("problema X", 2)
    assert len(ae._pick_domains("otro", 6)) == 6
    # Determinismo: mismo problema -> mismo set de dominios.
    a = ae._pick_domains("contexto saturado", 4)
    b = ae._pick_domains("contexto saturado", 4)
    assert a == b
    assert len(set(a)) == 4  # diversos (sin repetir)
