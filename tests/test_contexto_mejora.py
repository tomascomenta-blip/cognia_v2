# -*- coding: utf-8 -*-
"""
Tests del contexto que se le pasa al mejorador de prompts
(cognia/harness/contexto_mejora.py).

Fija lo que el modulo promete y lo que ya se le rompio una vez: que el tipo de
tarea se decida por PALABRA y no por substring, que una senal exclusiva pese
mas que una compartida, que no se pregunte por decisiones que el usuario ya
tomo, y que reunir() no lance NUNCA -- ni con proveedores que explotan, ni con
proveedores lentos, ni con un presupuesto que no da para todas las secciones.

Los proveedores se INYECTAN por `proveedores=` (el parametro que el modulo ya
expone): nada de parchear el sistema entero para no tocar disco.
"""

import time

import pytest

from cognia.harness import contexto_mejora as CM
from cognia.harness.contexto_mejora import (
    SECCIONES, faltantes_por_tipo, reunir, tipo_de_tarea)


@pytest.fixture(autouse=True)
def coste_de_proceso_limpio():
    """El coste medido y la marca de calentamiento son de PROCESO: un test que
    inyecta un proveedor lento no puede dejar descalificado al real."""
    coste = dict(CM._COSTE_MS)
    calentando = set(CM._CALENTANDO)
    yield
    CM._COSTE_MS.clear()
    CM._COSTE_MS.update(coste)
    CM._CALENTANDO.clear()
    CM._CALENTANDO.update(calentando)


# -- tipo_de_tarea ------------------------------------------------------------

# Banco de frases con su tipo. Las tres primeras son las que MOTIVARON el
# codigo actual (empate roto por especificidad + limite de palabra); el resto
# cubre las cinco categorias y el 'otro'.
BANCO_TIPOS = [
    # 'analiza' (investigacion) y 'csv' (datos) pesan 1,0 y empatan: gana la
    # categoria que exige un objeto concreto, que va primero en la tabla.
    ("analiza el csv de ventas", "datos"),
    # 'compara' no puede leerse como el 'para' de otra categoria.
    ("compara react y vue", "investigacion"),
    # ... ni el 'para' de "correo PARA pedir" convertir esto en una accion.
    ("escribe un correo para pedir un aumento", "escritura"),
    ("arregla el bug de la funcion de login", "codigo"),
    ("hazme un script en python que ordene ficheros", "codigo"),
    ("crea una pagina web con react", "codigo"),
    ("refactoriza el modulo de memoria", "codigo"),
    ("redacta un articulo sobre el cambio climatico", "escritura"),
    ("traduce este texto al ingles", "escritura"),
    ("resume la reunion de ayer", "escritura"),
    ("investiga el estado del arte en cuantizacion", "investigacion"),
    ("como funciona el protocolo mcp", "investigacion"),
    ("por que se cae el servidor", "investigacion"),
    ("entrena un modelo de prediccion con el dataset", "datos"),
    ("haz un grafico de la correlacion entre las columnas", "datos"),
    ("borra los ficheros temporales de la carpeta descargas", "accion"),
    ("mueve las fotos de este mes a otra carpeta", "accion"),
    ("abre el navegador", "accion"),
    ("hola que tal", "otro"),
    ("que tal el clima hoy", "otro"),
]


@pytest.mark.parametrize("frase,esperado", BANCO_TIPOS)
def test_tipo_de_tarea_banco(frase, esperado):
    assert tipo_de_tarea(frase) == esperado


def test_tipo_de_tarea_ignora_tildes_y_mayusculas():
    """El usuario escribe 'Analizá' y el clasificador ve 'analiza'."""
    assert tipo_de_tarea("Analizá el CSV de ventas") == "datos"


def test_tipo_de_tarea_texto_vacio_es_otro():
    assert tipo_de_tarea("") == "otro"
    assert tipo_de_tarea(None) == "otro"


# -- _casa: regresion del bug de substring ------------------------------------

def test_casa_no_cuenta_para_dentro_de_otra_palabra():
    """El bug que rompia dos de las tres frases del banco: 'para' casaba por
    `in` dentro de 'comPARA' y de 'sePARAdo'."""
    assert CM._casa("para", "compara react y vue") is False
    assert CM._casa("para", "el fichero esta separado en dos") is False
    assert CM._casa("para", "un correo para el jefe") is True


def test_casa_no_cuenta_test_dentro_de_contexto_ni_web_dentro_de_webhook():
    assert CM._casa("test", "contexto") is False
    assert CM._casa("test", "el contexto del modulo") is False
    assert CM._casa("web", "configura el webhook") is False
    assert CM._casa("test", "escribe un test para esto") is True
    assert CM._casa("web", "una web sencilla") is True


def test_casa_respeta_la_puntuacion_como_limite():
    """El limite es alfanumerico, no espacio: 'python.' o '(python)' cuentan."""
    assert CM._casa("python", "hazlo en python.") is True
    assert CM._casa("python", "hazlo en (python)") is True
    assert CM._casa("python", "usa python3") is False


def test_casa_deja_pasar_extensiones_y_comodines():
    """Regresion del efecto colateral del limite: una senal que EMPIEZA por
    punto ('.csv') o ACABA en punto ('*.') no puede exigir limite por ese
    lado, o no casa jamas donde de verdad aparece."""
    assert CM._casa(".csv", "analiza ventas.csv") is True
    assert CM._casa("*.", "borra los *.tmp") is True
    assert CM._casa(".csv", "analiza ventas.csvx") is False


# -- _peso_senal --------------------------------------------------------------

def test_peso_senal_exclusiva_pesa_mas_que_compartida(monkeypatch):
    """La tabla real no tiene hoy ninguna senal repetida, asi que la rama de
    la senal compartida solo se puede ejercitar con una tabla inyectada."""
    monkeypatch.setattr(CM, "_SENALES_TIPO", (
        ("datos", ("csv", "modelo")),
        ("codigo", ("script", "modelo")),
    ))
    assert CM._peso_senal("csv") == 1.0
    assert CM._peso_senal("modelo") == 0.5
    assert CM._peso_senal("modelo") < CM._peso_senal("csv")


def test_peso_senal_de_dos_palabras_pesa_mas():
    """'base de datos' casa por accidente muchisimo menos que 'api'."""
    assert CM._peso_senal("base de datos") > CM._peso_senal("api")
    assert CM._peso_senal("estado del arte") == pytest.approx(1.4)


def test_peso_senal_de_dos_palabras_desempata_una_frase_real():
    """Es lo que hace que 'por que se cae el servidor' no sea codigo: 'por
    que' (1,4) le gana a 'servidor' (1,0)."""
    assert tipo_de_tarea("por que se cae el servidor") == "investigacion"


# -- faltantes_por_tipo -------------------------------------------------------

def _ids(faltantes):
    return [f["id"] for f in faltantes]


def test_faltantes_pregunta_el_stack_cuando_nadie_lo_dijo():
    faltantes = faltantes_por_tipo("hazme un script que ordene mis ficheros")
    assert "stack" in _ids(faltantes)
    stack = [f for f in faltantes if f["id"] == "stack"][0]
    assert stack["tipo"] == "unica" and stack["opciones"]


def test_faltantes_no_pregunta_el_stack_si_el_texto_lo_dice():
    faltantes = faltantes_por_tipo("hazme un script en Python que ordene ficheros")
    assert "stack" not in _ids(faltantes)


def test_faltantes_no_pregunta_el_stack_si_lo_dijo_el_contexto():
    """La encuesta invasiva empieza justo aqui: preguntarle otra vez algo que
    dijo hace tres turnos.

    ENMIENDA 2026-08-29 (PEDIDO 5.4): el fixture pasa ahora lo que de verdad
    recibe esta funcion desde reunir() -- SOLO la seccion 'conversacion', o
    sea lo que el usuario DIJO. Antes reunir() le pasaba `ctx.bloque` entero
    (1800 chars con entorno, artefactos, memorias y rag dentro) y eso hacia el
    filtro demasiado agresivo en la direccion contraria: apagaba preguntas que
    nadie habia contestado. Lo cubre
    test_reunir_no_da_por_dicho_lo_que_solo_esta_en_el_entorno."""
    faltantes = faltantes_por_tipo(
        "hazme un script que ordene ficheros",
        contexto="Ultimos turnos:\ntu: todo lo mio va en Python")
    assert "stack" not in _ids(faltantes)


def test_faltantes_no_pregunta_la_fuente_si_el_texto_trae_el_fichero():
    """El .csv escrito por el usuario ES la respuesta a 'donde estan los datos'."""
    assert "fuente" not in _ids(faltantes_por_tipo("analiza ventas.csv y dame la media"))
    assert "fuente" in _ids(faltantes_por_tipo("analiza mis datos de ventas"))


def test_faltantes_tipo_otro_tiene_huecos_genericos():
    """ENMIENDA 2026-08-29 (PEDIDO 5.4). Este test se llamaba
    test_faltantes_tipo_sin_decisiones_devuelve_lista_vacia y exigia
    _FALTANTES['otro'] == []. Ese vacio ERA la segunda causa del bug que
    reporto el dueno ("el mejorador no hace las encuestas"): tipo_de_tarea()
    devuelve 'otro' para todo lo que no case con su tabla de palabras, y con
    faltantes=[] la puerta 3 de encuesta.vale_la_pena cerraba con "no hay
    decisiones sin tomar detectables". Medido sobre 21 pedidos cortos tipicos:
    5 morian exactamente aqui, entre ellos 'quiero ponerme en forma' -- que es
    el EJEMPLO 1 del propio system del reformulador.

    El comportamiento viejo era el que apagaba la encuesta, asi que lo que
    cambia es el test, no el codigo. Lo que se fija ahora: 'otro' pregunta lo
    unico que aplica a CUALQUIER tarea (para que es, en que forma, hasta
    donde), nunca nada especifico de un dominio que no se detecto."""
    ids = _ids(faltantes_por_tipo("lo que sea", "otro"))
    assert ids == ["proposito", "formato_salida", "alcance"]
    assert _ids(faltantes_por_tipo("hola que tal")) == ids


def test_faltantes_de_otro_respetan_lo_que_el_usuario_ya_dijo():
    """Los tres huecos genericos NO son un formulario fijo: si el pedido ya
    dice para que es o en que formato lo quiere, esa pregunta no se hace. Es
    la regla 1 de encuesta.py y sigue mandando tambien en 'otro'."""
    dicho = faltantes_por_tipo("quiero algo para presentarlo en una tabla",
                               "otro")
    assert "proposito" not in _ids(dicho)      # "para " lo cubre
    assert "formato_salida" not in _ids(dicho)  # "tabla" lo cubre


def test_faltantes_de_otro_no_inventan_preguntas_de_dominio():
    """Si no se detecto el tipo, preguntar por el 'stack' o por el 'tono'
    seria inventarle un dominio al pedido."""
    ids = _ids(faltantes_por_tipo("ayudame con el proyecto", "otro"))
    for ajeno in ("stack", "destino", "tono", "largo", "audiencia", "fuente"):
        assert ajeno not in ids


def test_faltantes_respeta_el_tipo_pasado_a_mano():
    """El tipo se pasa desde reunir() ya calculado: no se recalcula."""
    assert _ids(faltantes_por_tipo("hola", "escritura")) == ["audiencia", "tono", "largo"]


# -- reunir: proveedores inyectados -------------------------------------------

def _prov(valor):
    return lambda texto, st: valor


def _explota(texto, st):
    raise RuntimeError("disco muerto")


def test_reunir_un_proveedor_que_lanza_deja_aviso_y_no_tumba_al_resto():
    ctx = reunir("arregla el bug", secciones=("entorno", "conversacion"),
                 proveedores={"entorno": _explota,
                              "conversacion": _prov("tu: seguimos con el login")})
    assert list(ctx.secciones) == ["conversacion"]
    assert len(ctx.avisos) == 1
    aviso = ctx.avisos[0]
    assert aviso.startswith("entorno:") and "RuntimeError" in aviso
    assert "disco muerto" in aviso
    # Fallar no es lo mismo que no caber: 'recortadas' no se ensucia.
    assert ctx.recortadas == []
    assert "seguimos con el login" in ctx.bloque
    # Y el nombre pelado tambien queda, para no tener que parsear la prosa.
    assert ctx.fallidas == ["entorno"]
    assert ctx.estado_de("entorno") == "fallo"
    assert ctx.estado_de("conversacion") == "incluida"


def test_reunir_un_proveedor_vacio_no_aparece_en_secciones():
    """"No hay" no deja aviso; solo "no se pudo" lo deja.

    ENMENDADO 2026-08-29. El test decia la verdad a medias y por eso dejo
    pasar el bug: comprobaba que un proveedor vacio no ensuciara `secciones`,
    `avisos` ni `recortadas`... que es exactamente lo que hacia el `if valor:`
    de la linea 576 -- tirarlo A LA BASURA. Con esas tres listas limpias, una
    seccion que contesto "no hay nada" era INDISTINGUIBLE de una que nunca se
    pidio, y medido en esta maquina eran 5 de los 8 proveedores reales.

    Lo que se exige ahora es lo que faltaba: que "no hay" sea una RESPUESTA
    registrada (`vacias`), distinta de "no se pudo" (`avisos`/`fallidas`) y
    distinta de "no se pidio" (`recortadas`). Las tres aserciones viejas
    siguen aqui: no se relajo nada, se anadio el rastro que faltaba."""
    ctx = reunir("arregla el bug", secciones=("entorno", "conversacion", "memorias"),
                 proveedores={"entorno": _prov(""),
                              "conversacion": _prov("   \n  "),
                              "memorias": _prov("- ya paso algo asi")})
    assert list(ctx.secciones) == ["memorias"]
    assert ctx.avisos == []
    assert ctx.recortadas == []
    # Lo nuevo: los dos vacios CONSTAN, y se distinguen de un fallo.
    assert ctx.vacias == ["entorno", "conversacion"]
    assert ctx.fallidas == []
    assert ctx.estado_de("entorno") == "sin_datos"
    assert ctx.estado_de("conversacion") == "sin_datos"
    assert ctx.estado_de("memorias") == "incluida"
    assert ctx.a_dict()["vacias"] == ["entorno", "conversacion"]


def test_ninguna_seccion_pedida_desaparece_sin_dejar_rastro():
    """EL CRITERIO. Para cada seccion pedida hay SIEMPRE una respuesta a "que
    paso con esta seccion", y las cinco vias son excluyentes.

    Es el invariante que la cabecera del modulo declara ("un contexto
    incompleto en silencio es indistinguible de un contexto vacio") y que el
    codigo incumplia: el que devolvia "" se caia del mundo entero."""
    def _lento(texto, st):
        time.sleep(0.08)
        return "esto tardo"

    ctx = reunir("arregla el bug", presupuesto_ms=40, presupuesto_chars=60,
                 secciones=SECCIONES,
                 proveedores={"entorno": _prov("A" * 50),      # entra
                              "conversacion": _prov("B" * 50),  # no cabe
                              "restricciones": _prov(""),       # no hay
                              "artefactos": _explota,           # no se pudo
                              "recetas": _lento,                # gasta el tope
                              # y de aqui abajo ya no se pide ninguna
                              "skills": _prov("x"),
                              "memorias": _prov("y"),
                              "rag": _prov("z")})
    estados = {n: ctx.estado_de(n) for n in SECCIONES}
    assert estados == {"entorno": "incluida",
                       "conversacion": "sin_sitio",
                       "restricciones": "sin_datos",
                       "artefactos": "fallo",
                       # se recolecto (el lento SI corrio) pero no cabia
                       "recetas": "sin_sitio",
                       "skills": "no_pedida",
                       "memorias": "no_pedida",
                       "rag": "no_pedida"}
    # Ni una sola se quedo sin via, y ninguna esta en dos a la vez.
    apariciones = (list(ctx.secciones) + ctx.vacias + ctx.fallidas
                   + [n for n in ctx.recortadas if n not in ctx.secciones])
    assert sorted(apariciones) == sorted(SECCIONES)


def test_una_seccion_pedida_sin_proveedor_tampoco_se_evapora():
    """Un nombre que no existe se caia del filtro de `pedidas` y no aparecia
    en ningun sitio: un error de tecleo en `secciones=` se veia igual que una
    seccion sin datos."""
    ctx = reunir("arregla el bug", secciones=("entorno", "inventada"),
                 proveedores={"entorno": _prov("aqui")})
    assert ctx.estado_de("inventada") == "fallo"
    assert ctx.avisos == ["inventada: sin proveedor registrado"]
    assert ctx.estado_de("no_la_pedi") == "fuera_de_lista"


def test_reunir_el_presupuesto_recorta_secciones_enteras():
    """Media seccion es peor que ninguna: una lista de artefactos cortada se
    lee como si esos fueran todos los que hay."""
    largo = "A" * 300
    otro = "B" * 300
    ctx = reunir("arregla el bug", presupuesto_chars=320,
                 secciones=("entorno", "conversacion"),
                 proveedores={"entorno": _prov(largo), "conversacion": _prov(otro)})
    # Las dos se recolectaron; solo la de menos prioridad se quedo fuera.
    assert set(ctx.secciones) == {"entorno", "conversacion"}
    assert ctx.recortadas == ["conversacion"]
    assert largo in ctx.bloque          # entera, no a medias
    assert "B" not in ctx.bloque
    assert ctx.chars == len(ctx.bloque) <= 320


def test_reunir_el_bloque_sigue_el_orden_de_SECCIONES():
    """Se pidan como se pidan, primero va lo que desambigua el pedido."""
    ctx = reunir("arregla el bug",
                 secciones=("memorias", "conversacion", "entorno"),
                 proveedores={"entorno": _prov("trabajando en cognia_v2"),
                              "conversacion": _prov("tu: el login"),
                              "memorias": _prov("- de otra sesion")})
    posiciones = [ctx.bloque.index(CM._TITULOS[n] + ":")
                  for n in SECCIONES if n in ctx.secciones]
    assert posiciones == sorted(posiciones)
    assert ctx.bloque.startswith("Donde:")


def test_reunir_no_lanza_aunque_todos_los_proveedores_exploten():
    pedidas = ("entorno", "conversacion", "memorias")
    # Sin ninguna decision tomada en el texto: "para el jefe" ya contestaria
    # la de audiencia y este test no mira eso, mira que el contrato aguante.
    ctx = reunir("redacta un correo de despedida", secciones=pedidas,
                 proveedores={n: _explota for n in pedidas})
    assert ctx.bloque == "" and ctx.chars == 0
    assert ctx.secciones == {}
    assert len(ctx.avisos) == len(pedidas)
    assert ctx.fallidas == list(pedidas)
    assert all(ctx.estado_de(n) == "fallo" for n in pedidas)
    # El resto del contrato sigue en pie sin una sola seccion.
    assert ctx.tipo_tarea == "escritura"
    assert _ids(ctx.faltantes) == ["audiencia", "tono", "largo"]
    assert ctx.a_dict()["avisos"] == ctx.avisos


def test_reunir_pide_las_secciones_con_el_texto_del_usuario():
    """El proveedor recibe el texto tal cual y el estado con cwd/historial."""
    visto = {}

    def _espia(texto, st):
        visto["texto"] = texto
        visto["st"] = dict(st)
        return "ok"

    hist = [{"role": "user", "content": "hola"}]
    reunir("arregla el bug", secciones=("entorno",), proveedores={"entorno": _espia},
           historial=hist, cwd="C:/tmp")
    assert visto["texto"] == "arregla el bug"
    assert visto["st"] == {"historial": hist, "cwd": "C:/tmp"}


# -- reunir: presupuesto de TIEMPO --------------------------------------------

def test_reunir_el_presupuesto_de_tiempo_recorta_las_siguientes():
    """El tope no interrumpe al lento (no se puede, es sincrono): lo que hace
    es DEJAR DE PEDIR, y decir cuales no pidio."""
    def _lento(texto, st):
        time.sleep(0.12)
        return "tarde una eternidad"

    ctx = reunir("arregla el bug", presupuesto_ms=20,
                 secciones=("entorno", "conversacion", "memorias"),
                 proveedores={"entorno": _lento,
                              "conversacion": _prov("tu: el login"),
                              "memorias": _prov("- de otra sesion")})
    assert list(ctx.secciones) == ["entorno"]      # el lento SI se ejecuto
    assert ctx.recortadas == ["conversacion", "memorias"]
    assert ctx.avisos == []                        # recortar no es fallar
    assert ctx.ms >= 100


# -- la carrera con el hilo de calentamiento ----------------------------------

def test_una_seccion_cara_consta_gane_quien_gane_la_carrera():
    """El hilo de calentamiento escribe `_COSTE_MS[nombre]`, y ese global es
    la UNICA puerta que decide si `rag` se pide o se recorta. Que la llamada
    siguiente lo vea frio o caliente es una CARRERA con ese hilo.

    Reproducido antes del arreglo: 1a llamada recortadas=['rag']; a los 50 ms
    el hilo pone _COSTE_MS['rag']=0; 2a llamada, 'rag' se pide, devuelve "" y
    no queda ni en `secciones` ni en `recortadas` -- desaparecido.

    Aqui se fuerzan las DOS ramas de la carrera a mano (nada de dormir y
    cruzar los dedos) y se exige lo mismo de las dos: que `rag` conste. Que
    CAMBIE de estado esta bien -- calentar sirve para algo --; lo que no
    puede es evaporarse."""
    vacio = _prov("")

    # (a) gana el turno: el hilo no ha anotado nada todavia.
    CM._COSTE_MS.pop("rag", None)
    CM._CALENTANDO.add("rag")          # que no arranque un hilo de verdad
    frio = reunir("arregla el bug", secciones=("rag",), proveedores={"rag": vacio})
    assert frio.recortadas == ["rag"]
    assert frio.estado_de("rag") == "no_pedida"

    # (b) gana el hilo: ya anoto que en caliente cuesta 0 ms.
    CM._COSTE_MS["rag"] = 0
    caliente = reunir("arregla el bug", secciones=("rag",),
                      proveedores={"rag": vacio})
    assert caliente.secciones == {} and caliente.recortadas == []
    assert caliente.vacias == ["rag"]                 # ANTES: desaparecia
    assert caliente.estado_de("rag") == "sin_datos"

    # (c) y si en caliente SI trae algo, entra como cualquier otra.
    con_datos = reunir("arregla el bug", secciones=("rag",),
                       proveedores={"rag": _prov("indexado: cli.py")})
    assert con_datos.estado_de("rag") == "incluida"


def test_el_calentamiento_no_se_dispara_dos_veces_ni_desde_dos_hilos():
    """`_CALENTANDO` lo leen y lo escriben varios hilos, y el arranque que
    protege cuesta 7,4 s medidos: dispararlo dos veces es pagarlo dos veces.
    El test-and-set va dentro del lock, asi que 8 peticiones simultaneas
    arrancan UN solo calentamiento (y ese hace 2 llamadas: la que paga el
    arranque y la que mide en caliente)."""
    import threading

    CM._CALENTANDO.discard("rag")
    CM._COSTE_MS.pop("rag", None)
    llamadas = []
    barrera = threading.Barrier(8)

    def _fn(texto, st):
        llamadas.append(texto)
        return ""

    def _pide():
        barrera.wait(timeout=5)
        CM._calentar_en_fondo("rag", _fn)

    hilos = [threading.Thread(target=_pide) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=5)
    limite = time.monotonic() + 5
    while "rag" not in CM._COSTE_MS and time.monotonic() < limite:
        time.sleep(0.01)

    assert CM._COSTE_MS.get("rag") is not None, "el calentamiento no anoto coste"
    assert len(llamadas) == 2, f"se calento {len(llamadas) / 2:g} veces"


# -- humo contra los proveedores REALES ---------------------------------------

def test_humo_reunir_real_es_rapido_en_caliente():
    """Esto corre entre el Enter del usuario y el envio al modelo: el camino
    caliente (segunda llamada del proceso, con `rag` ya descalificado en frio)
    tiene que costar segundos de un digito bajo, no diez.

    ENMENDADO 2026-08-29. La ultima asercion era
        assert "rag" in ctx.recortadas or "rag" in ctx.secciones
    y estaba ROJA 3 de 3 en esta maquina. No era un test flaky: era el bug.
    Solo contemplaba DOS destinos para `rag` y el real era un tercero -- el
    hilo de calentamiento ganaba la carrera, `rag` se pedia, el indice no
    existe aqui, devolvia "" y el `if valor:` lo tiraba. La asercion vieja no
    tenia forma de expresar "contesto y no habia nada", asi que solo podia
    fallar.

    Lo que se exige ahora es mas fuerte, no mas debil, y es el criterio de
    verdad: NINGUNA de las 8 secciones puede quedar sin respuesta a "que paso
    contigo". Da igual quien gane la carrera; lo que no vale es el silencio."""
    reunir("arregla el bug del login")               # paga los imports y el arranque
    inicio = time.monotonic()
    ctx = reunir("escribe un correo para pedir un aumento")
    tardado = time.monotonic() - inicio
    assert tardado < 3.0, f"reunir() en caliente tardo {tardado:.2f}s: {ctx.avisos}"
    assert ctx.tipo_tarea == "escritura"
    assert ctx.chars <= CM.PRESUPUESTO_CHARS
    estados = {n: ctx.estado_de(n) for n in SECCIONES}
    sin_respuesta = [n for n, e in estados.items() if e == "fuera_de_lista"]
    assert sin_respuesta == [], f"secciones desaparecidas: {sin_respuesta} ({estados})"
    # 'rag' es la que motivo todo esto: cara en frio, se calienta en segundo
    # plano. Puede salir 'no_pedida' (el hilo aun no acabo), 'sin_datos' (ya
    # esta caliente y esta maquina no tiene indice) o 'incluida'. Lo que no
    # puede es faltar.
    assert estados["rag"] in ("no_pedida", "sin_datos", "incluida", "fallo")


# -- que contexto llega a faltantes_por_tipo desde reunir() (PEDIDO 5.4) -------

def test_reunir_no_da_por_dicho_lo_que_solo_esta_en_el_entorno():
    """TERCERA CAUSA del bug, la mas silenciosa. reunir() le pasaba a
    faltantes_por_tipo el BLOQUE ENTERO (hasta 1800 chars con entorno,
    artefactos, recetas, skills, memorias y rag). Las senales de cobertura son
    palabras como "python", "fichero", "carpeta", "servidor" o "local", que en
    el blob de la maquina aparecen casi seguro sin que el usuario las haya
    dicho nunca: medido, "hazme una pagina web" perdia 'proposito' y 'stack'
    -- se quedaba con 2 de 4 huecos -- solo por el contexto, y con menos
    contexto util la lista se vaciaba entera y la encuesta se apagaba sola.

    Que la maquina sea un proyecto Python no es una decision del usuario.
    Darla por dicha es atribuirle una eleccion que no tomo: el mismo fallo que
    este subsistema tiene prohibido cometer."""
    ctx = reunir("hazme un script que ordene ficheros",
                 proveedores={"entorno": lambda t, st: (
                     "trabajando en cognia_v2 (proyecto Python), "
                     "hay ficheros y carpetas en el servidor local")},
                 secciones=("entorno",))
    assert "proyecto Python" in ctx.bloque      # el contexto SI se le da al modelo
    assert "stack" in _ids(ctx.faltantes), (
        "el entorno de la maquina no puede contestar por el usuario")


def test_reunir_si_da_por_dicho_lo_que_esta_en_la_conversacion():
    """La otra mitad: lo que el usuario DIJO hace tres turnos sigue contando, y
    no se le vuelve a preguntar. La regla 1 de encuesta.py sigue en pie."""
    ctx = reunir("hazme un script que ordene ficheros",
                 proveedores={"conversacion": lambda t, st:
                              "tu: todo lo mio va en Python"},
                 secciones=("conversacion",))
    assert "stack" not in _ids(ctx.faltantes)


def test_reunir_de_un_pedido_no_clasificado_trae_huecos():
    """De punta a punta: el pedido que caia en 'otro' ahora llega a la encuesta
    con algo que preguntar."""
    ctx = reunir("ayudame con el proyecto", secciones=("conversacion",),
                 proveedores={"conversacion": lambda t, st: ""})
    assert ctx.tipo_tarea == "otro"
    assert _ids(ctx.faltantes) == ["proposito", "formato_salida", "alcance"]
