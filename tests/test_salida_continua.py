"""
Tests de cognia/agent/salida_continua.py — la salida que no se trunca.

Todo con un backend FALSO: el modulo es aritmetica de strings + un callback,
no habla por red. Lo que se fija aqui es lo que fallaba en las sesiones reales
(chat_history id 1071 y 1061): un corte por tope tiraba lo generado y volvia a
empezar, y el prompt de la continuacion crecia hasta desbordar la ventana.
"""

import pytest

from cognia.agent import salida_continua as sc


# ── backend falso ──────────────────────────────────────────────────────────
class Falso:
    """Emite tramos de una lista. El ultimo para 'stop'; los demas, 'limit'."""

    def __init__(self, tramos, razones=None):
        self.tramos = list(tramos)
        self.razones = list(razones) if razones else (
            ["limit"] * (len(tramos) - 1) + ["stop"])
        self.entradas = []          # la cola recibida en cada llamada
        self.chunks = []
        self.last_stop_reason = None
        self._i = 0

    def pedir(self, cola, chunk):
        self.entradas.append(cola)
        self.chunks.append(chunk)
        i = min(self._i, len(self.tramos) - 1)
        self._i += 1
        self.last_stop_reason = self.razones[min(i, len(self.razones) - 1)]
        # token a token, como el stream real
        return iter(list(self.tramos[i]))

    def parada(self):
        return self.last_stop_reason


def correr(falso, chunk=100, **kw):
    return "".join(sc.stream_continuo(falso.pedir, falso.parada, chunk, **kw))


# ── solape (la costura) ────────────────────────────────────────────────────
def test_solape_detecta_la_repeticion_larga():
    acc = "el juego se dibuja en un canvas de 800x600 pixeles"
    trozo = " en un canvas de 800x600 pixeles y el bucle corre a 60 fps"
    n = sc.solape(acc, trozo)
    assert n == len(" en un canvas de 800x600 pixeles")
    assert acc + trozo[n:] == (
        "el juego se dibuja en un canvas de 800x600 pixeles y el bucle "
        "corre a 60 fps")


def test_solape_ignora_las_coincidencias_cortas():
    # Un espacio o una coma coinciden con el principio de casi todo: recortar
    # por ahi se comeria texto bueno.
    assert sc.solape("hola mundo,", ", pero no") == 0
    assert sc.solape("una linea\n", "\notra cosa") == 0


def test_solape_vacios_y_sin_costura():
    assert sc.solape("", "algo") == 0
    assert sc.solape("algo", "") == 0
    assert sc.solape("aaaaaaaaaaaaaaaaaa", "zzzzzzzzzzzzzzzzzz") == 0


# ── reencuentro (la repeticion que solape() no ve) ─────────────────────────
def test_reencuentro_caza_la_reescritura_medida_en_real():
    # Caso literal de la corrida contra llama3.2:3b: el tramo nuevo reescribe
    # la frase entera y vuelve a pasar por el final de lo acumulado.
    acc = "10. Instala la conexion a Internet y las antenas de"
    trozo = ("11. Instala la conexion a Internet y las antenas de"
             " radio, asegurandote de que esten seguras.")
    n = sc.reencuentro(acc, trozo)
    assert n > 0
    assert (acc + trozo[n:]).endswith(
        "y las antenas de radio, asegurandote de que esten seguras.")
    assert "11. Instala" not in acc + trozo[n:]


def test_reencuentro_no_dispara_sin_el_ancla():
    acc = "un texto que termina de una forma bien concreta y larga"
    assert sc.reencuentro(acc, "otro texto completamente distinto") == 0


def test_reencuentro_ignora_un_ancla_de_puro_blanco():
    assert sc.reencuentro(" " * 60, "   texto nuevo") == 0


def test_reencuentro_solo_mira_la_cabeza_del_tramo():
    acc = "x" * 39 + "ANCLA-FINAL-DEL-ACUMULADO-QUE-ES-LARGA"
    trozo = "z" * 900 + acc[-40:] + " cola"
    assert sc.reencuentro(acc, trozo) == 0     # reaparece fuera de la ventana


def test_recorte_prueba_las_dos_costuras():
    # literal
    assert sc.recorte("el bucle corre a 60 fps", " a 60 fps y pinta") == 0
    assert sc.recorte("el bucle corre a 60 fps",
                      "corre a 60 fps y pinta") == len("corre a 60 fps")
    # reescritura
    acc = "el jugador salta sobre la plataforma mas alta del nivel"
    assert sc.recorte(acc, "el heroe salta sobre la plataforma mas alta "
                           "del nivel y cae al agua") > 0
    # nada que recortar
    assert sc.recorte("una cosa", " y otra cosa distinta") == 0


# ── cola de re-anclaje (la compactacion) ───────────────────────────────────
def test_cola_corta_devuelve_el_texto_entero_sin_marca():
    assert sc.cola_de("dos lineas\ncortas", limite=100) == "dos lineas\ncortas"


def test_cola_larga_se_recorta_y_se_marca():
    texto = "x" * 500 + "\n" + "y" * 500
    cola = sc.cola_de(texto, limite=200)
    assert cola.startswith("[...]")
    assert len(cola) <= 200 + len("[...]\n")
    assert cola.endswith("yyy")


def test_cola_de_una_sola_linea_larga_no_se_pierde():
    # HTML minificado: no hay salto de linea donde cortar limpio.
    texto = "<!DOCTYPE html>" + "z" * 1000
    cola = sc.cola_de(texto, limite=100)
    assert cola.startswith("[...]")
    assert cola.endswith("z" * 50)


# ── el bucle ───────────────────────────────────────────────────────────────
def test_un_solo_tramo_cuando_el_modelo_termina():
    f = Falso(["respuesta entera."], razones=["stop"])
    assert correr(f) == "respuesta entera."
    assert len(f.entradas) == 1
    assert f.entradas[0] is None     # None = arranque, no "continua desde ''"


def test_el_corte_por_tope_encadena_y_no_pierde_lo_generado():
    # Esto es id 1071: antes el primer tramo se tiraba a la basura.
    f = Falso(["primera parte ", "segunda parte ", "y final."])
    assert correr(f) == "primera parte segunda parte y final."
    assert len(f.entradas) == 3


def test_la_continuacion_recibe_la_cola_de_lo_ya_dicho():
    f = Falso(["arranque del texto", " y su continuacion"])
    correr(f)
    assert f.entradas[1].endswith("arranque del texto")


def test_la_costura_no_duplica_lo_repetido():
    f = Falso(["el bucle corre a 60 fps",
               "el bucle corre a 60 fps y pinta el canvas"])
    assert correr(f) == "el bucle corre a 60 fps y pinta el canvas"


def test_el_prompt_de_la_continuacion_no_crece_con_la_respuesta():
    # La razon de que la salida pueda ser "infinita" con una ventana fija.
    largo = "linea de texto para llenar la ventana\n" * 200
    f = Falso([largo, largo, largo, "fin."])
    correr(f, cola=500)
    for cola in f.entradas[1:]:
        assert len(cola) <= 500 + len("[...]\n")


def test_para_cuando_el_tramo_solo_trae_blancos():
    # Emitio algo (blancos), o sea que no es el caso "se fue en razonar":
    # insistir solo repetiria.
    f = Falso(["algo de texto", "   ", "nunca se pide"],
              razones=["limit", "limit", "limit"])
    assert correr(f) == "algo de texto   "
    assert len(f.entradas) == 2


# ── el tramo que se va entero en razonamiento (id 1071) ────────────────────
def test_el_tramo_sin_respuesta_no_para_el_turno():
    # Medido contra el server real (Qwen3.8-27B, 2026-08-31): finish='limit'
    # con CERO chars de content porque el presupuesto se fue pensando. Pararse
    # ahi es entregar la nada; hay que insistir.
    f = Falso(["", "", "aqui va por fin la respuesta."],
              razones=["limit", "limit", "stop"])
    assert correr(f) == "aqui va por fin la respuesta."
    assert len(f.entradas) == 3


def test_al_insistir_sin_texto_la_cola_va_vacia_no_None():
    # "" != None: el llamador tiene que poder pedir "responde YA" en vez de
    # repetir el turno original tal cual (que volveria a pensar lo mismo).
    f = Falso(["", "por fin"], razones=["limit", "stop"])
    correr(f)
    assert f.entradas[0] is None
    assert f.entradas[1] == ""


def test_sin_texto_max_limita_la_insistencia():
    f = Falso(["", "", "", "", ""], razones=["limit"] * 5)
    correr(f, sin_texto_max=2)
    assert len(f.entradas) == 3      # el arranque + 2 insistencias


def test_sin_texto_se_reinicia_cuando_vuelve_a_escribir():
    f = Falso(["", "escribe algo", "", "y termina."],
              razones=["limit", "limit", "limit", "stop"])
    assert correr(f, sin_texto_max=1) == "escribe algoy termina."
    assert len(f.entradas) == 4


def test_para_cuando_el_modelo_repite_el_mismo_tramo():
    # Tramo corto (por debajo de SOLAPE_MIN): la costura no lo toca -- un
    # solape de 5 chars no se cree -- y quien corta es el freno de repeticion.
    f = Falso(["bucle", "bucle", "bucle", "bucle"],
              razones=["limit"] * 4)
    salida = correr(f)
    assert len(f.entradas) == 2      # se para en cuanto se repite
    assert salida == "buclebucle"


def test_el_tramo_repetido_largo_lo_borra_la_costura_y_para():
    linea = "y entonces el jugador salta sobre la plataforma"
    f = Falso([linea, linea, linea], razones=["limit"] * 3)
    # El segundo tramo es solape puro: no aporta nada -> se para sin duplicar.
    assert correr(f) == linea
    assert len(f.entradas) == 2


# ── freno de bucle (el que protege el modo "sin tope") ─────────────────────
BLOQUE = (
    "35. Verifica que todos los accesorios esten en su lugar y que no haya "
    "cables sueltos o conexiones expuestas, revisando una por una todas las "
    "conexiones del equipo antes de dormir alli. 36. Verifica que la "
    "iluminacion sea adecuada y segura, y que no haya riesgo de incendio. "
    "37. Verifica que los pasillos esten libres de obstaculos. ")


def test_en_bucle_ve_el_bloque_reemitido():
    assert len(BLOQUE) >= sc.BUCLE_HUELLA
    assert sc.en_bucle(BLOQUE + "texto intermedio distinto " + BLOQUE)


def test_en_bucle_no_dispara_en_texto_normal():
    prosa = " ".join(f"frase numero {i} con su contenido propio y distinto."
                     for i in range(120))
    assert not sc.en_bucle(prosa)
    assert not sc.en_bucle("")
    assert not sc.en_bucle("corto")
    assert not sc.en_bucle(" " * 2000)


def test_en_bucle_ignora_el_eco_lejano():
    bloque = "z" * (sc.BUCLE_HUELLA + 5)
    lejos = bloque + "y" * (sc.BUCLE_VENTANA + 5000) + bloque
    assert not sc.en_bucle(lejos)


def test_el_bucle_corta_la_generacion_sin_tope():
    # Reproduce lo medido: el modelo sigue emitiendo bloques ya escritos.
    bloque = ("paso repetido con suficiente texto como para pasar de la "
              "huella de trescientos caracteres que usa el detector de "
              "bucles, escrito con calma para llegar de sobra al limite "
              "y poder afirmar que esto es una vuelta y no una casualidad. ")
    f = Falso([bloque, "un poco de texto distinto por el medio ", bloque,
               bloque, bloque], razones=["limit"] * 5)
    correr(f, rondas_max=0, tope_total=0)   # sin ningun tope de tramos
    assert len(f.entradas) < 5              # lo corta el freno de bucle


def test_rondas_max_es_un_freno_duro():
    f = Falso(["a" * 30, "b" * 30, "c" * 30, "d" * 30],
              razones=["limit"] * 4)
    correr(f, rondas_max=2)
    assert len(f.entradas) == 2


def test_tope_total_en_tokens_corta():
    f = Falso(["x" * 400, "y" * 400, "z" * 400], razones=["limit"] * 3)
    # ~4 chars/token: 400 chars son ~100 tokens -> con tope 150 se para al 2o.
    correr(f, tope_total=150)
    assert len(f.entradas) == 2


def test_sin_tope_total_por_defecto():
    assert sc.TOPE_TOTAL == 0


def test_el_chunk_es_el_mismo_en_todos_los_tramos():
    # El tope de tokens deja de ser el techo de la RESPUESTA y pasa a ser el
    # tamano del tramo: no hay rampa (x2, x4...) que regenere lo mismo.
    f = Falso(["uno ", "dos ", "tres"])
    correr(f, chunk=777)
    assert f.chunks == [777, 777, 777]


def test_on_tramo_recibe_el_avance():
    vistos = []
    f = Falso(["hola ", "mundo"])
    correr(f, on_tramo=lambda r, n, t: vistos.append((r, n, t)))
    assert vistos == [(1, 5, 5), (2, 5, 10)]


def test_on_tramo_que_lanza_no_rompe_el_stream():
    def explota(*_a):
        raise RuntimeError("el aviso del CLI fallo")
    f = Falso(["hola ", "mundo"])
    assert correr(f, on_tramo=explota) == "hola mundo"


def test_ctrl_c_del_backend_sube_al_llamador():
    def pedir(_cola, _chunk):
        yield "empieza"
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        list(sc.stream_continuo(pedir, lambda: "limit", 100))


# ── mensajes de continuacion ───────────────────────────────────────────────
def test_continuacion_mensajes_no_muta_el_original():
    base = [{"role": "user", "content": "hazme un juego"}]
    out = sc.continuacion_mensajes(base, "lo que llevaba escrito")
    assert len(base) == 1
    assert out[-2] == {"role": "assistant", "content": "lo que llevaba escrito"}
    assert out[-1]["role"] == "user"
    assert "EXACTAMENTE" in out[-1]["content"]


def test_continuacion_sin_cola_no_mete_un_asistente_vacio():
    # Un turno de asistente con content "" lo renderizan algunas plantillas
    # como un turno YA CERRADO: el modelo creeria que ya respondio.
    base = [{"role": "user", "content": "hazme un juego"}]
    out = sc.continuacion_mensajes(base, "")
    assert [m["role"] for m in out] == ["user", "user"]
    assert "AHORA" in out[-1]["content"]


# ── puertas de configuracion ───────────────────────────────────────────────
def test_activa_por_defecto():
    assert sc.activa({}, {}) is True


def test_la_env_manda_sobre_la_config():
    assert sc.activa({"salida_continua": "on"}, {sc.ENV_ACTIVA: "0"}) is False
    assert sc.activa({"salida_continua": "off"}, {sc.ENV_ACTIVA: "1"}) is True


def test_config_apaga():
    assert sc.activa({"salida_continua": "off"}, {}) is False


def test_limites_por_defecto_y_desde_env():
    assert sc.limites({}, {}) == (sc.RONDAS_MAX, 0)
    assert sc.limites({}, {sc.ENV_RONDAS: "5", sc.ENV_TOPE: "9000"}) == (5, 9000)
    # Basura -> el default, nunca una excepcion.
    assert sc.limites({}, {sc.ENV_RONDAS: "manzana"}) == (sc.RONDAS_MAX, 0)
    # 0 explicito = sin tope, y se respeta.
    assert sc.limites({}, {sc.ENV_RONDAS: "0"}) == (0, 0)


# ── tamano del tramo (puerta /ventana continuo tramo) ──────────────────────
def test_tramo_por_defecto_es_el_de_esfuerzo():
    assert sc.tramo(12000, {}, {}) == 12000


def test_tramo_override_por_env_y_por_config():
    assert sc.tramo(12000, {}, {sc.ENV_TRAMO: "800"}) == 800
    assert sc.tramo(12000, {"salida_continua_tramo": 900}, {}) == 900
    # 0 = "usa el de /esfuerzo"
    assert sc.tramo(12000, {"salida_continua_tramo": 0}, {}) == 12000


def test_tramo_respeta_un_piso_y_no_revienta_con_basura():
    assert sc.tramo(12000, {}, {sc.ENV_TRAMO: "1"}) == sc.TRAMO_MIN
    assert sc.tramo(12000, {}, {sc.ENV_TRAMO: "melon"}) == 12000
    assert sc.tramo(None, {}, {}) == sc.TRAMO_MIN
