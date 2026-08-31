# -*- coding: utf-8 -*-
"""
tests/test_clases_apuntes.py
============================
Los apuntes SIN MODELO, que es el caso que el duenio va a tener casi siempre:
el camino extractivo tiene que cazar los deberes, la formula y el "esto entra
en el examen", conservar LITERAL lo que el escribio a mano, respetar el tope
al compactar y dejar la jornada guardada donde `cuaderno.sesiones_de` la
vuelve a encontrar.

AISLAMIENTO. COGNIA_CLASES_DIR se fija a un tmp_path en un fixture autouse:
sin eso estos tests escribirian en el cuaderno REAL del duenio. Ademas se
limpia COGNIA_COMPACT_CAP, que es estado de OTRO modulo (harness.compactacion
lo lee a call-time) y del que depende el presupuesto del resumen: con la
variable puesta en el entorno del duenio, los mismos apuntes darian resumenes
de largos distintos segun quien corriera la suite.
"""

import pytest

from cognia.clases import almacen as alm
from cognia.clases import apuntes as ap
from cognia.clases import cuaderno as cua


@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path / "clases"))
    monkeypatch.delenv("COGNIA_COMPACT_CAP", raising=False)
    monkeypatch.delenv("COGNIA_COMPACT", raising=False)


# Una clase de Fisica de verdad: el profesor divaga, define una magnitud,
# dicta una formula, manda deberes y avisa de lo que entra en el examen. Es
# el material del que tienen que salir los apuntes.
TRANSCRIPCION = [
    "Bueno, vamos a empezar. Buenos días a todos, sentaos y sacad el cuaderno "
    "que hoy tenemos bastante materia. Ayer nos quedamos en el movimiento "
    "rectilíneo uniforme y hoy vamos a cerrar el tema de la cinemática.",
    "A ver, el movimiento rectilíneo uniforme es el movimiento de un cuerpo "
    "que recorre una trayectoria recta con velocidad constante. Es decir, no "
    "hay aceleración, la velocidad no cambia ni de módulo ni de dirección.",
    "La velocidad media se define como el cociente entre el espacio recorrido "
    "y el tiempo empleado en recorrerlo. Apuntad eso tal cual, que es la "
    "definición que os voy a pedir.",
    "Entonces la fórmula es v = d / t, donde v es la velocidad, d es el "
    "espacio recorrido en metros y t es el tiempo en segundos. Vale, ¿lo veis? "
    "La velocidad se mide en metros por segundo.",
    "Si despejamos, el espacio recorrido es d = v * t, y el tiempo es "
    "t = d / v. Son la misma fórmula despejada, no os aprendáis tres cosas "
    "distintas porque es una sola.",
    "Vamos con un ejemplo. Un coche recorre ciento veinte kilómetros en dos "
    "horas. La velocidad media es ciento veinte partido por dos, sesenta "
    "kilómetros por hora. Fijaos en las unidades, que es donde se pierden "
    "casi todos los puntos en los exámenes.",
    "Ojo con una cosa, la velocidad media no es la media de las velocidades. "
    "Si vais a cien y luego a veinte, la velocidad media no es sesenta. Esto "
    "entra en el examen del viernes, que lo pregunto todos los años y todos "
    "los años cae alguien.",
    "El movimiento rectilíneo uniformemente acelerado lo empezamos la semana "
    "que viene, pero os adelanto que ahí la velocidad sí cambia y aparece la "
    "aceleración, que se define como la variación de la velocidad respecto "
    "del tiempo.",
    "Para mañana hacer los ejercicios 4 y 5 de la página 120, los de velocidad "
    "media, que son cortos. Y el 7 el que quiera nota, que ese ya es de "
    "unidades mezcladas.",
    "Nada más por hoy. La semana que viene traed la calculadora, que vamos a "
    "hacer cuentas con decimales. Hasta el jueves.",
]


def _sesion(materia="Fisica"):
    """Una Sesion armada a mano, con la transcripcion troceada como la deja
    la captura (un registro cada pocos segundos) y dos notas del duenio."""
    entradas = []
    t = 0.0
    for trozo in TRANSCRIPCION:
        entradas.append(cua.Entrada(t=t, tipo=cua.TIPO_TRANSCRIPCION,
                                    texto=trozo, t_fin=t + 60.0, fuente="sistema"))
        t += 60.0
    entradas.append(cua.Entrada(t=125.0, tipo=cua.TIPO_NOTA, fuente="usuario",
                                texto=NOTA_IMPORTANTE, importante=True))
    entradas.append(cua.Entrada(t=400.0, tipo=cua.TIPO_NOTA, fuente="usuario",
                                texto=NOTA_NORMAL))
    return cua.Sesion(materia=materia, t0=0.0, t1=t, jornada="2026-08-31",
                      entradas=entradas, por="manual")


NOTA_IMPORTANTE = "OJO: la media de velocidades NO es la velocidad media, repasarlo"
NOTA_NORMAL = "no me queda claro lo de despejar el tiempo, preguntar el jueves"


# ── El extractivo, sin modelo ────────────────────────────────────────────────

def test_claves_del_dict_son_exactamente_las_del_contrato():
    salida = ap.generar(_sesion(), orch=None)
    assert set(salida) == {"titulo", "resumen", "claves", "definiciones",
                           "formulas", "deberes", "dudas", "examen",
                           "chars_entrada", "chars_salida", "via", "aviso"}
    assert salida["via"] == ap.VIA_EXTRACTIVO
    assert "sin modelo" in salida["aviso"]
    assert salida["chars_entrada"] == len(_sesion().texto_dicho())
    assert salida["chars_salida"] > 0


def test_extractivo_caza_los_deberes():
    salida = ap.generar(_sesion(), orch=None)
    juntos = " ".join(salida["deberes"])
    assert "ejercicios 4 y 5" in juntos
    assert "página 120" in juntos


def test_extractivo_caza_la_formula():
    salida = ap.generar(_sesion(), orch=None)
    assert "v = d / t" in salida["formulas"]
    assert "d = v * t" in salida["formulas"]
    # Y NO se cuela la frase que solo habla de formulas ("son la misma fórmula
    # despejada..."): una lista de formulas con prosa dentro no se puede mirar
    # de un vistazo, que es para lo unico que sirve la seccion.
    assert all(len(f) < 40 for f in salida["formulas"]), salida["formulas"]


def test_extractivo_caza_el_aviso_de_examen():
    salida = ap.generar(_sesion(), orch=None)
    assert any("examen del viernes" in e for e in salida["examen"])


def test_extractivo_caza_la_definicion():
    salida = ap.generar(_sesion(), orch=None)
    terminos = " ".join(d["termino"] for d in salida["definiciones"]).lower()
    definiciones = " ".join(d["definicion"] for d in salida["definiciones"])
    assert "velocidad media" in terminos
    assert "cociente entre el espacio recorrido" in definiciones
    assert all(set(d) == {"termino", "definicion"} for d in salida["definiciones"])
    # El termino se corta por su determinante: sin eso salia "cambia y aparece
    # la aceleración, que" como si fuera el nombre del concepto.
    assert any(d["termino"].lower() == "la aceleración"
               for d in salida["definiciones"])


def test_titulo_y_resumen_no_quedan_vacios():
    salida = ap.generar(_sesion(), orch=None)
    assert salida["titulo"].startswith("Fisica")
    assert len(salida["resumen"]) > 40


# ── Lo que escribio el duenio ────────────────────────────────────────────────

def test_la_nota_importante_aparece_intacta_y_la_primera():
    salida = ap.generar(_sesion(), orch=None)
    assert NOTA_IMPORTANTE in salida["claves"] + salida["examen"]
    # Destacada = va delante de lo generado, sin prefijos ni reescritura.
    assert salida["claves"][0] == NOTA_IMPORTANTE


def test_las_notas_no_importantes_tambien_se_conservan_literales():
    """Se conservan enteras y van a la seccion donde el duenio las buscara:
    un "no me queda claro" es una duda, no una idea clave."""
    salida = ap.generar(_sesion(), orch=None)
    assert NOTA_NORMAL in salida["dudas"]
    assert salida["dudas"][0] == NOTA_NORMAL


def test_la_garantia_de_lo_importante_se_aplica_tambien_a_apuntes_ya_guardados():
    """Unos apuntes viejos (guardados antes de que el duenio marcara la nota)
    se releen sin regenerar, pero la nota importante tiene que aparecer igual."""
    s = _sesion()
    s.apuntes = {"titulo": "De ayer", "resumen": "resumen viejo", "claves": ["algo"],
                 "via": "extractivo"}
    salida = ap.generar(s, orch=None)
    assert salida["titulo"] == "De ayer"          # no se regenero
    assert salida["claves"][0] == NOTA_IMPORTANTE  # pero la garantia se aplico
    assert salida["formulas"] == []                # clave ausente -> lista, no KeyError


def test_forzar_regenera_los_apuntes_guardados():
    s = _sesion()
    s.apuntes = {"titulo": "De ayer", "claves": ["algo"]}
    salida = ap.generar(s, orch=None, forzar=True)
    assert salida["titulo"] != "De ayer"
    assert any("v = d / t" in f for f in salida["formulas"])


def test_sesion_sin_nada_dice_vacio_y_no_revienta():
    s = cua.Sesion(materia="Fisica", t0=0.0, t1=10.0)
    salida = ap.generar(s, orch=None)
    assert salida["via"] == ap.VIA_VACIO
    assert salida["aviso"]
    assert salida["claves"] == [] and salida["titulo"] == ""


def test_sesion_solo_con_notas_del_usuario_no_devuelve_hoja_en_blanco():
    s = cua.Sesion(materia="Historia", t0=0.0, t1=60.0, entradas=[
        cua.Entrada(t=5.0, tipo=cua.TIPO_NOTA, texto=NOTA_IMPORTANTE,
                    importante=True, fuente="usuario"),
        cua.Entrada(t=9.0, tipo=cua.TIPO_IMAGEN, adjunto="pizarra_0001.png",
                    fuente="usuario"),
    ])
    salida = ap.generar(s, orch=None)
    assert salida["via"] == ap.VIA_EXTRACTIVO
    assert NOTA_IMPORTANTE in salida["claves"]
    assert any("pizarra_0001.png" in c for c in salida["claves"])
    assert "sin transcripcion" in salida["aviso"]


# ── compactar ────────────────────────────────────────────────────────────────

def test_compactar_respeta_el_tope():
    texto = " ".join(TRANSCRIPCION)
    for tope in (120, 300, 700, 1500):
        salida = ap.compactar(texto, tope)
        assert len(salida) <= tope, (tope, len(salida))
        assert salida.strip()


def test_compactar_es_deterministico_y_conserva_el_orden():
    texto = " ".join(TRANSCRIPCION)
    a = ap.compactar(texto, 500)
    assert a == ap.compactar(texto, 500)
    # Las frases elegidas salen en el orden en que se dijeron, no por ranking.
    pos = [texto.find(f.strip()) for f in a.split(". ") if len(f.strip()) > 20]
    # El assert de orden es VACUO si la lista sale vacia (un dia que compactar
    # devuelva "" pasaria igual de verde): se exige que haya varias frases que
    # ordenar, que es lo unico que hace falsable la comprobacion de abajo.
    assert len(pos) >= 3, a
    assert all(p >= 0 for p in pos)
    assert pos == sorted(pos)


def test_compactar_con_tope_cero_o_texto_corto():
    assert ap.compactar("lo que sea", 0) == ""
    assert ap.compactar("  corto  ", 100) == "corto"


RELLENO = ("Bueno, vale, entonces claro, mira, venga, vamos, veis, bien, pues, "
           "eso, esto, ahora, vale")
DENSA = ("La velocidad media se define como el cociente entre el espacio "
         "recorrido y el tiempo empleado")


def test_compactar_elige_por_densidad_y_no_por_orden():
    """El que decide tiene que ser el RANKING, no el filtro de largo.

    La version anterior de este test usaba muletillas de una palabra ("Vale.",
    "Venga.") y comprobaba que no salieran: eso lo cumple `_frases`, que tira
    toda frase de menos de 12 chars ANTES de puntuar nada, asi que el test
    pasaba igual aunque `_puntuar` devolviera una constante -- medido: con
    `_puntuar` fijo la salida no cambiaba. Aqui las dos frases pasan el filtro
    de largo (89 y 93 chars), solo cabe UNA en el tope, y la de relleno va
    PRIMERA: si el ranking no ordena, gana ella y este test se pone rojo.
    """
    texto = RELLENO + ". " + DENSA + "."
    salida = ap.compactar(texto, len(DENSA) + 4)
    assert salida == DENSA, salida
    assert "venga" not in salida.lower()


# ── La jornada entera, persistida ────────────────────────────────────────────

def _sembrar_jornada(nombre="2026-08-31"):
    """Escribe una jornada en disco como la deja la captura: transcripcion en
    JSONL, una nota del usuario en entradas.jsonl y dos cortes de materia."""
    d = alm.dir_jornada(nombre)
    t = 0.0
    for trozo in TRANSCRIPCION:
        alm.apendar(d / alm.TRANSCRIPCION,
                    {"t": t, "t_fin": t + 60.0, "tipo": cua.TIPO_TRANSCRIPCION,
                     "texto": trozo, "fuente": "sistema"})
        t += 60.0
    alm.apendar(d / alm.ENTRADAS,
                {"t": 125.0, "tipo": cua.TIPO_NOTA, "texto": NOTA_IMPORTANTE,
                 "importante": True, "fuente": "usuario"})
    alm.apendar(d / alm.TRANSCRIPCION,
                {"t": t, "t_fin": t + 60.0, "tipo": cua.TIPO_TRANSCRIPCION,
                 "texto": "Pasamos a Historia. La Revolución Industrial se "
                          "define como el proceso de transformación económica "
                          "y social que arranca en Inglaterra a finales del "
                          "siglo XVIII. Para mañana leer las páginas 30 a 34.",
                 "fuente": "sistema"})
    alm.apendar(d / alm.CORTES, {"t": 0.0, "materia": "Fisica",
                                 "confianza": 0.9, "por": "manual"})
    alm.apendar(d / alm.CORTES, {"t": t, "materia": "Historia",
                                 "confianza": 0.8, "por": "deriva"})
    j = cua.cargar_jornada(nombre)
    j.segundos = t + 60.0
    j.estado = "cerrada"
    cua.guardar_jornada(j)
    return nombre


def test_generar_jornada_persiste_y_cuaderno_lo_relee():
    nombre = _sembrar_jornada()
    pasos = []
    salida = ap.generar_jornada(nombre, orch=None,
                                progreso=lambda i, n, m: pasos.append((i, n, m)))

    assert set(salida) == {"0", "1"}
    assert pasos == [(1, 2, "Fisica"), (2, 2, "Historia")]
    assert (alm.dir_jornada(nombre) / alm.APUNTES).exists()

    # Lo importante: lo que releen el resto de vistas del cuaderno.
    sesiones = cua.sesiones_de(nombre)
    assert [s.materia for s in sesiones] == ["Fisica", "Historia"]
    assert sesiones[0].apuntes["via"] == ap.VIA_EXTRACTIVO
    assert sesiones[0].apuntes["claves"][0] == NOTA_IMPORTANTE
    assert any("ejercicios 4 y 5" in d for d in sesiones[0].apuntes["deberes"])
    assert any("páginas 30 a 34" in d for d in sesiones[1].apuntes["deberes"])
    assert sesiones[1].apuntes["titulo"].startswith("Historia")


def test_generar_jornada_guarda_sesion_a_sesion():
    """El guardado es incremental: tras la PRIMERA sesion ya hay algo en
    disco. Guardar al final tiraria la manana entera si el portatil se
    suspende en la cuarta clase."""
    nombre = _sembrar_jornada()
    vistos = []

    def _mirar(i, n, materia):
        vistos.append(alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {})

    ap.generar_jornada(nombre, orch=None, progreso=_mirar)
    assert list(vistos[0]) == ["0"]
    assert list(vistos[1]) == ["0", "1"]


def test_un_callback_de_progreso_roto_no_tira_la_jornada():
    nombre = _sembrar_jornada()

    def _roto(i, n, materia):
        raise RuntimeError("la barra de progreso se cayo")

    salida = ap.generar_jornada(nombre, orch=None, progreso=_roto)
    assert set(salida) == {"0", "1"}


def test_generar_jornada_sin_jornada_no_revienta():
    assert ap.generar_jornada("no-existe", orch=None) == {}


# ── El parseo de lo que devuelve el modelo (sin modelo: es una funcion pura) ──

def test_parsear_ignora_la_deliberacion_del_razonador():
    """El modelo local razona en voz alta antes de responder (medido en este
    repo). El parseo por etiqueta es lo que sobrevive a eso."""
    crudo = ("Vamos a ver, el fragmento habla de cinemática, creo que lo mejor\n"
             "es sacar la definición y la fórmula. Espera, tambien hay deberes.\n"
             "CLAVE: el MRU tiene velocidad constante\n"
             "DEF: velocidad media | espacio recorrido entre tiempo empleado\n"
             "FORM: v = d / t\n"
             "DEBER: ejercicios 4 y 5 de la página 120\n"
             "EXAMEN: la media de velocidades no es la velocidad media\n"
             "- DUDA: despejar el tiempo\n")
    out = ap._parsear(crudo)
    assert out["claves"] == ["el MRU tiene velocidad constante"]
    assert out["definiciones"] == [{"termino": "velocidad media",
                                    "definicion": "espacio recorrido entre tiempo empleado"}]
    assert out["formulas"] == ["v = d / t"]
    assert out["deberes"] == ["ejercicios 4 y 5 de la página 120"]
    assert out["dudas"] == ["despejar el tiempo"]
    assert out["examen"]


def test_parsear_sin_etiquetas_devuelve_todo_vacio():
    """Es la seguridad que dispara la caida al extractivo: si el razonador se
    fue a pensar y no emitio nada util, no puede colar prosa como apuntes."""
    out = ap._parsear("Mmm, deja que lo piense. Creo que no hay nada relevante.")
    assert not any(out.values())


def test_se_quita_el_bloque_think_del_razonador():
    """Salida REAL del modelo local del duenio el 2026-08-31 pidiendole el
    titulo: sin quitar el <think>, el titulo de la sesion quedaba en
    '<think>' y el resumen se llevaba media deliberacion en ingles."""
    crudo = ("<think>\nThe user wants me to summarize physics notes in 3 short "
             "sentences. Let me craft 3 short sentences.\n</think>\n\n"
             "El tema central es el movimiento rectilíneo uniforme (MRU).")
    assert ap._sin_razonamiento(crudo) == ("El tema central es el movimiento "
                                           "rectilíneo uniforme (MRU).")


def test_una_respuesta_que_es_solo_razonamiento_cuenta_como_vacia():
    """Es el disparador de la caida al extractivo: el razonador que se va a
    pensar y agota el presupuesto sin emitir respuesta."""
    assert ap._sin_razonamiento("<think>\nmmm, a ver, esto es de cinemática") == ""
    assert ap._sin_razonamiento("</think>\nRespuesta") == "Respuesta"


def test_ventanas_trocean_con_solape_y_cubren_todo():
    texto = " ".join(TRANSCRIPCION * 6)
    trozos = ap._ventanas(texto, 800, 100)
    assert len(trozos) > 3
    assert all(len(t) <= 800 for t in trozos)
    # Sin solape, una definicion partida por la mitad se pierde en las dos
    # ventanas; se comprueba que la cola de una reaparece en la siguiente.
    assert trozos[0][-40:].strip() in trozos[1]
    # Y "cubren todo" se COMPRUEBA, no se anuncia en el nombre: un hueco entre
    # dos ventanas es transcripcion que el modelo no ve y que no chilla en
    # ningun sitio. Se rehace el texto pegando cada ventana desde donde acaba
    # la anterior; tiene que salir el original entero.
    rehecho = trozos[0]
    for t in trozos[1:]:
        corte = max((i for i in range(1, len(t) + 1) if rehecho.endswith(t[:i])),
                    default=0)
        assert corte > 0, "hueco entre ventanas: se perdio transcripcion"
        rehecho += t[corte:]
    assert rehecho.split() == texto.split()


# ── Regresiones de la revision adversarial del 2026-08-31 ────────────────────

class _Respuesta:
    def __init__(self, text):
        self.text = text


class _OrchFalso:
    """El modelo, sin modelo. Cuenta las llamadas: el tope de llamadas por
    sesion es una promesa del modulo y sin contarlas no se puede comprobar."""

    def __init__(self, respuesta="", resumen="", revienta=False):
        self.respuesta = respuesta
        # Por defecto MUDO en la llamada del resumen, que es lo medido con el
        # razonador local: se va a pensar y agota el presupuesto sin emitir.
        self.resumen = resumen
        self.revienta = revienta
        self.llamadas = []

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        self.llamadas.append(max_tokens)
        if self.revienta:
            raise RuntimeError("el servidor del modelo no responde")
        return _Respuesta(self.resumen if prompt.startswith("Resume")
                          else self.respuesta)


def test_regenerar_no_borra_nada_de_lo_que_ya_habia_en_apuntes_json():
    """LA LINEA DURA: no se borran datos del duenio.

    `apuntes.json` lo pinta `vista.py`, que acepta ortografias que este modulo
    no genera ('puntos_clave', 'tareas') y ENSENIA en 'otros' cualquier clave
    suelta. Hasta el 2026-08-31 `generar_jornada` reescribia cada entrada con
    el dict normalizado, o sea que una regeneracion de rutina -- sin `forzar`,
    la que hace el CLI -- dejaba el fichero sin esas claves, sin aviso y sin
    copia. Reproducido antes del fix: 'mis_notas' desaparecia del disco.
    """
    nombre = _sembrar_jornada()
    ruta = alm.dir_jornada(nombre) / alm.APUNTES
    alm.guardar_json(ruta, {"0": {
        "titulo": "Doppler",
        "puntos_clave": ["la fuente que se acerca sube la frecuencia"],
        "tareas": ["ejercicios 4 y 5"],
        "mis_notas": ["esto lo escribi yo a mano"],
    }})

    ap.generar_jornada(nombre, orch=None)

    en_disco = alm.leer_json(ruta, {})["0"]
    assert en_disco["mis_notas"] == ["esto lo escribi yo a mano"]
    assert en_disco["puntos_clave"] == ["la fuente que se acerca sube la frecuencia"]
    assert en_disco["tareas"] == ["ejercicios 4 y 5"]


def test_los_apuntes_viejos_se_leen_con_la_ortografia_que_la_vista_acepta():
    """Y ademas se MIGRAN: si la vista sabe leer 'puntos_clave' y aqui se
    ignorara, unos apuntes que se ven bien en el HTML volverian vacios de
    `generar()`."""
    s = _sesion()
    s.apuntes = {"titulo": "De ayer", "puntos_clave": ["el MRU no acelera"],
                 "tareas": ["los ejercicios 4 y 5"]}
    salida = ap.generar(s, orch=None)
    assert "el MRU no acelera" in salida["claves"]
    assert salida["deberes"] == ["los ejercicios 4 y 5"]
    # Y la lista devuelta no es la MISMA que la guardada en la sesion: quien
    # retoque los apuntes en pantalla no puede estar editando el disco.
    assert salida["deberes"] is not s.apuntes["tareas"]


def test_una_clase_larga_respeta_el_tope_de_llamadas_al_modelo():
    """_MAX_VENTANAS es un tope de TIEMPO del duenio (una jornada son 5-7
    sesiones). El presupuesto de pre-compactado no descontaba el solape, asi
    que 12 ventanas salian 13 -- 14 llamadas con la del resumen -- y el tope
    era un comentario, no una garantia."""
    largo = " ".join(TRANSCRIPCION * 30)
    assert len(largo) > 50000                      # una clase de 50 min de verdad
    entradas = [cua.Entrada(t=0.0, tipo=cua.TIPO_TRANSCRIPCION, texto=largo,
                            t_fin=3000.0, fuente="sistema")]
    s = cua.Sesion(materia="Fisica", t0=0.0, t1=3000.0, entradas=entradas)
    orch = _OrchFalso("CLAVE: el MRU tiene velocidad constante")

    salida = ap.generar(s, orch=orch)

    assert len(orch.llamadas) <= ap._MAX_VENTANAS + 1, len(orch.llamadas)
    assert salida["via"] == ap.VIA_MODELO
    assert "pre-compactada" in salida["aviso"]


def test_el_modelo_caido_no_se_lee_igual_que_el_modelo_mudo():
    """Los dos acaban en apuntes extractivos, pero uno se arregla levantando
    el servidor y el otro no. Si el 'aviso' dice lo mismo, el duenio no puede
    distinguirlos -- el vacio silencioso que este repo tiene prohibido."""
    caido = ap.generar(_sesion(), orch=_OrchFalso(revienta=True))
    mudo = ap.generar(_sesion(), orch=_OrchFalso("mmm, deja que lo piense"))

    assert caido["via"] == mudo["via"] == ap.VIA_EXTRACTIVO
    assert "fallo" in caido["aviso"] and "RuntimeError" in caido["aviso"]
    assert "fallo" not in mudo["aviso"]
    assert "vacias" in mudo["aviso"]


def test_con_modelo_lo_lexico_se_suma_y_el_resumen_dice_de_donde_sale():
    """El camino del modelo no tenia NI UN test (solo se probaban sus piezas
    sueltas). Se comprueba lo que el modulo promete: que un deber literal del
    profesor no se pierde porque el modelo no lo mencionara, y que un resumen
    que el modelo no escribio no se presenta como suyo."""
    orch = _OrchFalso("CLAVE: el MRU tiene velocidad constante\n"
                      "FORM: v = d / t\n")
    salida = ap.generar(_sesion(), orch=orch)

    assert salida["via"] == ap.VIA_MODELO
    assert any("ejercicios 4 y 5" in d for d in salida["deberes"])
    assert any("examen del viernes" in e for e in salida["examen"])
    assert salida["claves"][0] == NOTA_IMPORTANTE
    # El modelo devolvio etiquetas tambien a la llamada del resumen, o sea que
    # el resumen NO es suyo: tiene que decirse.
    assert "el resumen es extractivo" in salida["aviso"]
    # Y el presupuesto de esa llamada no puede estar en la banda muda medida.
    assert all(t >= 700 for t in orch.llamadas), orch.llamadas
