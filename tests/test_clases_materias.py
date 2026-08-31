"""
tests/test_clases_materias.py
=============================
Deteccion de cambio de asignatura (cognia/clases/materias.py) contra una tira
SINTETICA de la que aqui se conoce la verdad.

POR QUE SINTETICA Y NO UNA JORNADA REAL. Porque la pregunta que hay que
responder es "donde estan los cortes de verdad", y de una grabacion real no se
sabe: habria que etiquetarla a mano y el test mediria la etiqueta. Aqui los
tres bloques (matematicas / historia / biologia) se generan con vocabularios
casi disjuntos, duraciones conocidas y pausas de cambio de aula, asi que el
error de cada corte se mide EN SEGUNDOS contra la verdad.

Lo que de verdad decide si el detector sirve no son los aciertos, son los
CONTRAFACTUALES -- cortar de mas es el fallo caro:
  (a) una sola materia seguida no puede producir ningun corte;
  (b) el profesor cambiando de ejemplo tres minutos (la pizza) dentro de
      matematicas tampoco;
  (c) con horario dado, los cortes caen en el horario;
  (d) sin materias conocidas y sin modelo sigue detectando, y lo DICE en
      "por" (para que "no lo cablearon" no se vea igual que "se rompio").

AISLAMIENTO. COGNIA_CLASES_DIR va a tmp_path en TODOS los tests: sin eso
escribirian en ~/.cognia/clases, el cuaderno real del duenio. Y
`materias.olvidar_cache()` se llama entre casos porque el vocabulario
aprendido vive en el modulo y sobrevive al cambio de directorio.
"""

import pytest

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua
from cognia.clases import materias as mat
from cognia.clases.cuaderno import Entrada, TIPO_TRANSCRIPCION, TIPO_NOTA


# ── La tira sintetica ────────────────────────────────────────────────────────

MATE = [
    "la derivada de una funcion polinomica se obtiene bajando el exponente",
    "la pendiente de la recta tangente coincide con la derivada en ese punto",
    "el limite del cociente incremental cuando el incremento tiende a cero",
    "para derivar un producto multiplicamos la primera por la derivada",
    "la segunda derivada indica si la curvatura es concava o convexa",
    "los maximos aparecen donde la derivada se anula y cambia de signo",
    "la exponencial es la unica funcion cuya derivada coincide consigo misma",
    "aplicamos la regla de la cadena al derivar una composicion",
]
HISTORIA = [
    "el tratado de versalles impuso reparaciones durisimas a alemania",
    "la revolucion industrial convirtio al campesinado britanico en obreros",
    "las trincheras del frente occidental alargaron el conflicto por desgaste",
    "el imperio austrohungaro se desmembro en varios estados nacionales",
    "la crisis del veintinueve arrastro a europa al paro masivo y al fascismo",
    "el congreso de viena repartio el mapa europeo entre las potencias",
    "la sociedad de naciones nacio debil sin estados unidos dentro",
    "el nacionalismo balcanico fue la chispa del atentado de sarajevo",
]
BIOLOGIA = [
    "la membrana plasmatica regula el intercambio con el medio externo",
    "las mitocondrias producen energia mediante respiracion celular aerobica",
    "el nucleo guarda el material genetico enrollado en cromatina",
    "la fotosintesis ocurre en los cloroplastos gracias a la clorofila",
    "los ribosomas traducen el mensajero en cadenas de aminoacidos",
    "la mitosis reparte una copia identica del genoma a cada hija",
    "las enzimas rebajan la energia de activacion del metabolismo",
    "el aparato de golgi empaqueta las proteinas antes de exportarlas",
]
# La digresion: el mismo profesor de matematicas, tres minutos hablando de
# repartir una pizza. Vocabulario TAN disjunto del de las derivadas como el de
# historia -- es justo el caso que hunde a un detector de ventana contra
# ventana.
PIZZA = [
    "imaginad que repartimos una pizza entera entre varios comensales",
    "si llegan mas amigos hambrientos la racion de cada comensal encoge",
    "el repartidor tarda media hora larga en subir hasta nuestro portal",
    "discutimos si conviene pedir dos medianas o una familiar grande",
]

DURACION_ENTRADA = 10.0    # trozos de 10 s, como los que escribe la captura
PAUSA_AULA = 300.0         # cinco minutos de cambio de aula entre clases


def tira(segmentos):
    """(entradas, inicios) a partir de [(frases, duracion, pausa_antes)].

    `inicios[i]` es el segundo exacto en que arranca el segmento i: esa es la
    VERDAD contra la que se mide el error de cada corte. Las entradas duran
    DURACION_ENTRADA con un segundo de hueco, que es la forma real de la
    transcripcion (trozos de audio consecutivos).
    """
    entradas, inicios, t = [], [], 0.0
    for frases, duracion, pausa in segmentos:
        t += pausa
        inicios.append(t)
        fin = t + duracion
        k = 0
        while t < fin:
            entradas.append(Entrada(t=t, tipo=TIPO_TRANSCRIPCION,
                                    texto=frases[k % len(frases)],
                                    t_fin=t + DURACION_ENTRADA - 1.0,
                                    fuente="micro"))
            t += DURACION_ENTRADA
            k += 1
    return entradas, inicios


def jornada_tres_materias():
    """Tres clases de 20 min con cambio de aula entre ellas."""
    return tira([(MATE, 1200.0, 0.0),
                 (HISTORIA, 1200.0, PAUSA_AULA),
                 (BIOLOGIA, 1200.0, PAUSA_AULA)])


def error_de_cortes(cortes, verdad):
    """El error en segundos de cada corte contra su verdad mas cercana."""
    return [min(abs(float(c["t"]) - v) for v in verdad) for c in cortes]


@pytest.fixture(autouse=True)
def cuaderno_aislado(tmp_path, monkeypatch):
    """Raiz del cuaderno en tmp_path + medida lexica + cache limpia.

    Los embeddings se apagan por defecto a proposito: cargar
    sentence-transformers cuesta ~8 s y hace el veredicto dependiente de que
    el paquete este instalado. El camino con embeddings tiene su propio test,
    marcado y explicito.
    """
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIA_CLASES_SIN_EMBEDDINGS", "1")
    mat.olvidar_cache()
    yield
    mat.olvidar_cache()


# ── Cortes: donde caen ───────────────────────────────────────────────────────

def test_tres_bloques_cortes_con_error_menor_de_30s():
    entradas, verdad = jornada_tres_materias()
    cortes = mat.detectar(entradas)

    assert [c["t"] for c in cortes] == sorted(c["t"] for c in cortes)
    assert cortes[0]["t"] == 0.0
    assert len(cortes) == 3, [c["t"] for c in cortes]
    errores = error_de_cortes(cortes, verdad)
    assert max(errores) <= 30.0, errores


def test_solo_silencio_acierta_los_tres_cortes():
    """La senial de silencio medida SOLA (deriva apagada). Es la linea base:
    lo que aporte la deriva se mide contra esto."""
    entradas, verdad = jornada_tres_materias()
    cortes = mat.detectar(entradas, pistas={"senales": {"deriva": False}})

    assert len(cortes) == 3, [c["t"] for c in cortes]
    # Sin nada que inferir: el corte cae en el primer segundo de habla nuevo.
    assert error_de_cortes(cortes, verdad) == [0.0, 0.0, 0.0]
    assert "deriva apagada" in cortes[1]["por"]


def test_solo_deriva_acierta_sin_ninguna_pausa():
    """La otra mitad: sin silencios (bloques pegados) y con la senial de
    silencio apagada, la deriva de vocabulario sola tiene que encontrarlos."""
    entradas, verdad = tira([(MATE, 1200.0, 0.0),
                             (HISTORIA, 1200.0, 0.0),
                             (BIOLOGIA, 1200.0, 0.0)])
    cortes = mat.detectar(entradas, pistas={"senales": {"silencio": False}})

    assert len(cortes) == 3, [c["t"] for c in cortes]
    errores = error_de_cortes(cortes, verdad)
    assert max(errores) <= 30.0, errores
    assert "vocabulario nuevo sostenido" in cortes[1]["por"]


# ── Contrafactuales: lo que NO tiene que cortar ──────────────────────────────

def test_una_sola_materia_seguida_no_produce_cortes():
    entradas, _ = tira([(MATE, 3600.0, 0.0)])
    cortes = mat.detectar(entradas)
    assert len(cortes) == 1, [c["t"] for c in cortes]
    assert cortes[0]["t"] == 0.0
    # `len(cortes) == 1` NO basta y por si solo este test pasaria por el
    # motivo equivocado: dos bloques de la MISMA materia se funden
    # (`_fundir`), asi que un corte de mas aqui saldria contado como uno solo.
    # Lo que lo hace falsable es que la fusion se declara en "por".
    assert "fundido" not in cortes[0]["por"], cortes[0]["por"]


def test_cambio_de_ejemplo_dentro_de_la_materia_no_corta():
    """La pizza: 3 min de vocabulario ajeno en mitad de matematicas.

    Es el falso positivo que mata al detector ingenuo, y ademas por partida
    doble: al ENTRAR en la digresion (vocabulario nuevo) y al SALIR (vuelve
    otro vocabulario). Ninguno de los dos puede producir corte.
    """
    entradas, inicios = tira([(MATE, 900.0, 0.0),
                              (PIZZA, 180.0, 0.0),
                              (MATE, 900.0, 0.0)])
    cortes = mat.detectar(entradas)
    assert len(cortes) == 1, [(c["t"], c["por"]) for c in cortes]
    # Igual que arriba: el corte espurio al entrar o al salir de la pizza
    # daria otra vez "Tema: derivada, ..." y `_fundir` lo taparia. Sin esta
    # linea, el contrafactual mas importante del fichero no puede fallar.
    assert "fundido" not in cortes[0]["por"], cortes[0]["por"]


def test_pausa_corta_dentro_de_clase_no_corta():
    """El profesor escribe 40 s en la pizarra sin hablar: por debajo de
    SILENCIO_MINIMO, no es evidencia de nada."""
    entradas, _ = tira([(MATE, 900.0, 0.0), (MATE, 900.0, 40.0)])
    assert mat.senal_silencio(entradas) == []
    cortes = mat.detectar(entradas)
    assert len(cortes) == 1
    assert "fundido" not in cortes[0]["por"], cortes[0]["por"]


def test_dos_horas_de_la_misma_materia_con_recreo_se_funden():
    """Clase doble con recreo: el silencio SI es evidencia (y se detecta),
    pero las dos mitades se llaman igual, asi que el cuaderno tiene que
    ensenar UNA sesion y no dos."""
    entradas, _ = tira([(MATE, 1500.0, 0.0), (MATE, 1500.0, 900.0)])
    # El contrafactual esta en esta linea: la evidencia de corte EXISTE (hay
    # un hueco de 15 min y la senial lo ve). Lo que no existe es la segunda
    # materia, y por eso el cuaderno tiene que ensenar una sola sesion.
    assert len(mat.senal_silencio(entradas)) == 1
    cortes = mat.detectar(entradas)
    assert len(cortes) == 1, [(c["t"], c["materia"]) for c in cortes]
    # Y la sesion unica NO es "aqui no paso nada": el corte existio y se
    # fundio, y el cuaderno lo dice. Es la contraparte exacta de los tres
    # contrafactuales de arriba, donde esta misma palabra no puede aparecer.
    assert "fundido con el bloque de 2400s" in cortes[0]["por"], cortes[0]["por"]


# ── Horario ──────────────────────────────────────────────────────────────────

def test_con_horario_los_cortes_caen_en_el_horario():
    entradas, verdad = jornada_tres_materias()
    # El horario del duenio, con el desfase tipico: el timbre no coincide con
    # el segundo en que el profesor empieza a hablar.
    horario = [{"materia": "Matematicas", "desde": 0.0, "hasta": 1200.0},
               {"materia": "Historia", "desde": verdad[1] - 120.0,
                "hasta": verdad[1] + 1100.0},
               {"materia": "Biologia", "desde": verdad[2] + 90.0,
                "hasta": verdad[2] + 1300.0}]
    cortes = mat.detectar(entradas, pistas={"horario": horario})

    assert [c["materia"] for c in cortes] == ["Matematicas", "Historia",
                                              "Biologia"]
    for corte, franja in zip(cortes, horario):
        assert abs(corte["t"] - max(0.0, franja["desde"])) <= mat.TOLERANCIA_HORARIO
        assert "horario" in corte["por"]
    # Y manda: pegado al silencio real, el corte queda EXACTO aunque la franja
    # del duenio estuviera desplazada dos minutos.
    assert error_de_cortes(cortes, verdad) == [0.0, 0.0, 0.0]
    assert cortes[1]["confianza"] >= 0.9


def test_horario_apagado_no_se_usa():
    entradas, verdad = jornada_tres_materias()
    horario = [{"materia": "Latin", "desde": 600.0, "hasta": 1200.0}]
    cortes = mat.detectar(entradas, pistas={"horario": horario,
                                            "senales": {"horario": False}})
    assert all(c["materia"] != "Latin" for c in cortes)
    assert max(error_de_cortes(cortes, verdad)) <= 30.0


def test_franja_de_horario_rota_no_tumba_la_deteccion():
    """Un horario a medio escribir degrada con motivo, no revienta la
    jornada: la franja mala se salta y las buenas siguen mandando."""
    entradas, verdad = jornada_tres_materias()
    horario = [{"materia": "Matematicas", "desde": 0.0, "hasta": 1200.0},
               {"materia": "Historia", "desde": "a las diez", "hasta": None},
               {"materia": "Biologia", "desde": verdad[2], "hasta": 9999.0}]
    cortes = mat.detectar(entradas, pistas={"horario": horario})
    assert [c["materia"] for c in cortes] == ["Matematicas", "Biologia"]


def test_un_hasta_ilegible_no_tira_la_franja_entera():
    """Degradar SOLO lo que se rompio. `hasta` no lo lee nadie (el limite de
    un bloque lo pone el `desde` de la franja siguiente), asi que un final mal
    escrito no puede borrar del horario una clase que el duenio SI declaro:
    el hueco se lo tragaba la materia anterior extendiendose sobre ella.
    """
    entradas, verdad = jornada_tres_materias()
    horario = [{"materia": "Matematicas", "desde": 0.0, "hasta": 1200.0},
               {"materia": "Historia", "desde": verdad[1], "hasta": "las once"},
               {"materia": "Biologia", "desde": verdad[2], "hasta": 9999.0}]
    franjas = mat.senal_horario({"horario": horario}, 4200.0)
    assert [f["materia"] for f in franjas] == ["Matematicas", "Historia",
                                               "Biologia"]
    cortes = mat.detectar(entradas, pistas={"horario": horario})
    assert [c["materia"] for c in cortes] == ["Matematicas", "Historia",
                                              "Biologia"]
    # Y sin `desde` utilizable si se descarta: ese es el unico campo que manda.
    solo_desde_roto = [{"materia": "Latin", "desde": "a las diez"}]
    assert mat.senal_horario({"horario": solo_desde_roto}, 4200.0) == []


# ── Sin materias, sin historial y sin modelo ─────────────────────────────────

def test_sin_materias_ni_orch_funciona_y_lo_dice_en_por():
    entradas, verdad = jornada_tres_materias()
    cortes = mat.detectar(entradas, materias_conocidas=None, orch=None)

    assert len(cortes) == 3
    assert max(error_de_cortes(cortes, verdad)) <= 30.0
    for c in cortes:
        assert "sin materias conocidas" in c["por"]
        assert "lexica" in c["por"]          # la medida usada, declarada
    # Y aun asi el cuaderno no queda mudo: cada bloque lleva sus terminos.
    assert cortes[0]["materia"].startswith("Tema: ")
    assert "derivada" in cortes[0]["materia"]
    assert cortes[0]["confianza"] < 0.7      # honesto: no sabe la asignatura


def test_nombrar_sin_nada_devuelve_tema_con_los_terminos():
    materia, conf = mat.nombrar(" ".join(BIOLOGIA))
    assert materia.startswith("Tema: ")
    assert conf <= 0.2


def test_jornada_vacia_devuelve_el_corte_cero():
    cortes = mat.detectar([])
    assert cortes == [{"t": 0.0, "materia": "Sin clasificar",
                       "confianza": 0.0, "por": "jornada vacia"}]


# ── Vocabulario aprendido del cuaderno ───────────────────────────────────────

def escribir_jornada_pasada(nombre, bloques):
    """Un dia ya cerrado en el cuaderno: transcripcion + cortes. Se escribe
    por el almacen de verdad (no a mano) para que lo lea `cuaderno.cuaderno()`
    igual que en produccion."""
    d = alm.dir_jornada(nombre)
    t = 0.0
    cortes = []
    for materia, frases in bloques:
        cortes.append({"t": t, "materia": materia, "confianza": 1.0,
                       "por": "manual"})
        for _ in range(4):
            for frase in frases:
                alm.apendar(d / alm.TRANSCRIPCION,
                            {"t": t, "t_fin": t + 9.0, "texto": frase,
                             "tipo": TIPO_TRANSCRIPCION, "fuente": "micro"})
                t += 10.0
    for c in cortes:
        alm.apendar(d / alm.CORTES, c)
    alm.guardar_json(d / alm.JORNADA, {"nombre": nombre, "estado": "cerrada",
                                       "segundos": t})


def test_vocabulario_propio_se_aprende_del_cuaderno():
    escribir_jornada_pasada("2026-08-20", [("Matematicas", MATE),
                                           ("Historia", HISTORIA),
                                           ("Biologia", BIOLOGIA)])
    mat.olvidar_cache()
    vocab = mat.vocabulario_de_materias()

    assert set(vocab) == {"Matematicas", "Historia", "Biologia"}
    assert "derivada" in vocab["Matematicas"]
    assert "versalles" in vocab["Historia"]
    assert "mitocondrias" in vocab["Biologia"]
    # Lo que dicen las tres clases no puede ser propio de ninguna.
    assert "derivada" not in vocab["Historia"]


def test_con_historial_los_bloques_reciben_su_nombre_de_verdad():
    escribir_jornada_pasada("2026-08-20", [("Matematicas", MATE),
                                           ("Historia", HISTORIA),
                                           ("Biologia", BIOLOGIA)])
    cua.declarar_materias(["Matematicas", "Historia", "Biologia"])
    mat.olvidar_cache()

    entradas, verdad = jornada_tres_materias()
    cortes = mat.detectar(entradas,
                          materias_conocidas=cua.materias_conocidas())

    assert [c["materia"] for c in cortes] == ["Matematicas", "Historia",
                                              "Biologia"]
    assert max(error_de_cortes(cortes, verdad)) <= 30.0
    assert min(c["confianza"] for c in cortes) >= 0.6


def test_el_cuaderno_parte_la_jornada_por_los_cortes_detectados():
    """De punta a punta: lo que escribe este modulo tiene que producir las
    tres sesiones del cuaderno. Un corte que `cuaderno.sesiones_de` no sepa
    leer no vale para nada aunque el test de arriba este verde."""
    escribir_jornada_pasada("2026-08-20", [("Matematicas", MATE),
                                           ("Historia", HISTORIA),
                                           ("Biologia", BIOLOGIA)])
    cua.declarar_materias(["Matematicas", "Historia", "Biologia"])
    mat.olvidar_cache()

    entradas, _ = jornada_tres_materias()
    d = alm.dir_jornada("2026-08-31")
    for e in entradas:
        alm.apendar(d / alm.TRANSCRIPCION, e.a_dict())
    alm.guardar_json(d / alm.JORNADA, {"nombre": "2026-08-31",
                                       "estado": "cerrada",
                                       "segundos": entradas[-1].t_fin})
    mat.olvidar_cache()
    for corte in mat.detectar(entradas,
                              materias_conocidas=cua.materias_conocidas()):
        alm.apendar(d / alm.CORTES, corte)

    sesiones = cua.sesiones_de("2026-08-31")
    assert [s.materia for s in sesiones] == ["Matematicas", "Historia",
                                             "Biologia"]
    assert all(s.duracion > 1000.0 for s in sesiones)
    assert "derivada" in sesiones[0].texto_dicho()
    assert "derivada" not in sesiones[1].texto_dicho()


# ── El modelo local (dependencia externa, guionizada) ────────────────────────

class _Respuesta:
    def __init__(self, text):
        self.text = text


class _OrchGuionizado:
    """El orquestador NO es lo que se prueba aqui: es la dependencia. Se le da
    un guion (como en tests/test_agent_loop_wires.py) para poder comprobar
    tres cosas que con el modelo real no serian reproducibles: que se le
    pregunta SOLO cuando el camino deterministico duda, que se le acota el
    presupuesto, y que su respuesta se valida contra la lista."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def infer(self, prompt, **kw):
        self.llamadas.append((prompt, kw))
        return _Respuesta(self.respuestas.pop(0) if self.respuestas else "")


def test_al_modelo_se_le_pregunta_con_presupuesto_acotado():
    orch = _OrchGuionizado(["Historia"])
    materia, conf = mat.nombrar(" ".join(HISTORIA),
                                materias_conocidas=["Matematicas", "Historia"],
                                orch=orch)
    assert materia == "Historia"
    assert conf >= 0.7
    prompt, kw = orch.llamadas[0]
    # Acotado, pero no de menos: el cerebro de la casa es un razonador y con
    # max_tokens=16 devuelve el content VACIO porque se lo gasta pensando
    # (medido contra :8080 el 2026-08-31; ver MAX_TOKENS_NOMBRE). El limite
    # de arriba es para que nadie le abra el presupuesto a lo bruto.
    assert 96 <= kw["max_tokens"] <= 256
    assert kw["temperature"] == 0.0
    assert "Historia" in prompt and len(prompt) < 1500


def test_la_cadena_de_pensamiento_no_decide_por_el_modelo():
    """El cerebro de la casa es un RAZONADOR: escribe lo que descarta antes de
    responder, en el mismo campo (por eso MAX_TOKENS_NOMBRE=160). Aqui el
    modelo considera Matematicas, la rechaza en voz alta y responde Historia.

    Leyendo "la primera materia de la lista que aparezca" el modulo devolvia
    Matematicas -- la que el modelo acababa de descartar -- y con confianza
    0.7, o sea firmando una asignatura equivocada en el cuaderno.
    """
    orch = _OrchGuionizado(["Podria ser Matematicas por las formulas, pero el "
                            "texto habla de trincheras y de Versalles.\n"
                            "Historia"])
    materia, conf = mat.nombrar(" ".join(HISTORIA),
                                materias_conocidas=["Matematicas", "Historia"],
                                orch=orch)
    assert materia == "Historia", materia
    assert conf >= 0.7


def test_la_conclusion_manda_aunque_vaya_en_la_misma_linea():
    """Sin salto de linea que separe la conclusion: entonces vale la ULTIMA
    mencion, que es donde el razonador aterriza.

    La lista va con Historia PRIMERA a proposito: con el orden al reves este
    test pasaria tambien leyendo por el principio, o sea por el motivo
    equivocado. Lo que tiene que decidir es la posicion en el TEXTO, no la
    posicion en `materias_conocidas`.
    """
    orch = _OrchGuionizado(["descarto Historia, no hay fechas; es Matematicas"])
    materia, _ = mat.nombrar(" ".join(MATE),
                             materias_conocidas=["Historia", "Matematicas"],
                             orch=orch)
    assert materia == "Matematicas", materia


def test_respuesta_del_modelo_fuera_de_la_lista_se_descarta():
    orch = _OrchGuionizado(["creo que estan dando Filosofia del Derecho"])
    materia, _ = mat.nombrar(" ".join(BIOLOGIA),
                             materias_conocidas=["Matematicas", "Historia"],
                             orch=orch)
    assert materia.startswith("Tema: ")


def test_al_modelo_no_se_le_pregunta_si_el_lexico_ya_esta_seguro():
    escribir_jornada_pasada("2026-08-20", [("Biologia", BIOLOGIA),
                                           ("Historia", HISTORIA)])
    mat.olvidar_cache()
    orch = _OrchGuionizado(["Historia"])
    materia, _ = mat.nombrar(" ".join(BIOLOGIA),
                             materias_conocidas=["Biologia", "Historia"],
                             orch=orch)
    assert materia == "Biologia"
    assert orch.llamadas == []


def test_un_modelo_que_revienta_no_tumba_el_nombrado():
    class _OrchRoto:
        def infer(self, prompt, **kw):
            raise RuntimeError("backend caido")

    materia, conf = mat.nombrar(" ".join(MATE),
                                materias_conocidas=["Latin", "Filosofia"],
                                orch=_OrchRoto())
    assert materia.startswith("Tema: ")
    assert conf <= 0.2


# ── Entradas del usuario y formatos ──────────────────────────────────────────

def test_las_notas_del_usuario_no_mueven_los_cortes():
    """Una nota escrita a mano son cuatro palabras: si contara como habla,
    el corte se iria al segundo en que el duenio saco la foto."""
    entradas, verdad = jornada_tres_materias()
    entradas.append(Entrada(t=650.0, tipo=TIPO_NOTA,
                            texto="mitocondrias examen versalles",
                            fuente="usuario", importante=True))
    entradas.sort(key=lambda e: e.t)
    cortes = mat.detectar(entradas)
    assert len(cortes) == 3
    assert max(error_de_cortes(cortes, verdad)) <= 30.0


def test_acepta_los_dicts_crudos_del_jsonl():
    entradas, verdad = jornada_tres_materias()
    cortes = mat.detectar([e.a_dict() for e in entradas])
    assert len(cortes) == 3
    assert max(error_de_cortes(cortes, verdad)) <= 30.0


def test_las_tildes_del_asr_no_parten_el_vocabulario():
    assert mat.terminos("la función y la funcion") == ["funcion", "funcion"]


# ── El camino con embeddings (si el backend real esta vivo) ──────────────────

def test_con_embeddings_reales_los_cortes_siguen_donde_toca(monkeypatch):
    """Mismo veredicto por el otro camino de medida. No se salta con un
    skipif por variable de entorno (eso es un test que no corre nunca): se
    salta solo si sentence-transformers NO esta instalado, que es la unica
    razon legitima."""
    monkeypatch.delenv("COGNIA_CLASES_SIN_EMBEDDINGS", raising=False)
    if not mat.embeddings_activos():
        pytest.skip("sin sentence-transformers: la deriva solo puede ser lexica")

    entradas, verdad = tira([(MATE, 1200.0, 0.0),
                             (HISTORIA, 1200.0, 0.0),
                             (BIOLOGIA, 1200.0, 0.0)])
    cortes = mat.detectar(entradas, pistas={"senales": {"silencio": False}})
    assert len(cortes) == 3, [(c["t"], c["por"]) for c in cortes]
    assert max(error_de_cortes(cortes, verdad)) <= 60.0
    assert "embeddings" in cortes[1]["por"]
    # "embeddings" a secas lo escribia el modulo tambien cuando la medida
    # habia caido a lexico (ver el test de abajo): esta linea es la que
    # distingue "se midio con embeddings" de "se dijo que si".
    assert "el backend de embeddings fallo" not in cortes[1]["por"]


def test_si_el_backend_semantico_muere_el_por_no_dice_embeddings(monkeypatch):
    """El campo "por" es lo unico que separa "no lo cablearon" de "se
    rompio", y aqui mentia. Con el backend semantico VIVO al arrancar pero
    muerto al pedir vectores, `senal_deriva` cae a lexico -- correctamente y
    con warning -- pero `detectar` seguia escribiendo "deriva embeddings" en
    cada corte, atribuyendo el corte a un umbral (0.75) que no se aplico: el
    que decidio fue UMBRAL_COBERTURA=0.30. Un test que solo mirase
    `"embeddings" in por` no puede cazar esto, porque pasa en los dos casos.
    """
    monkeypatch.setattr(mat, "embeddings_activos", lambda: True)
    monkeypatch.setattr(mat, "_vector", lambda texto: None)

    entradas, verdad = tira([(MATE, 1200.0, 0.0),
                             (HISTORIA, 1200.0, 0.0),
                             (BIOLOGIA, 1200.0, 0.0)])
    cortes = mat.detectar(entradas, pistas={"senales": {"silencio": False}})

    assert len(cortes) == 3, [(c["t"], c["por"]) for c in cortes]
    assert max(error_de_cortes(cortes, verdad)) <= 30.0
    for c in cortes:
        assert "deriva embeddings" not in c["por"], c["por"]
        assert "el backend de embeddings fallo" in c["por"], c["por"]
    assert "deriva lexica" in cortes[1]["por"]


def test_la_deriva_declara_la_medida_que_uso_de_verdad(monkeypatch):
    """`senal_deriva` deja el modo REAL en `informe`, tambien cuando no
    devuelve ninguna frontera: si solo se pudiera leer de la lista, una
    jornada sin cortes no podria declarar que la medida se degrado."""
    monkeypatch.setattr(mat, "_vector", lambda texto: None)
    entradas, _ = tira([(MATE, 1200.0, 0.0)])
    informe = {}
    mat.senal_deriva(entradas, modo="embeddings", informe=informe)
    assert informe["modo"] == "lexica"

    informe = {}
    mat.senal_deriva(entradas, modo="lexica", informe=informe)
    assert informe["modo"] == "lexica"
