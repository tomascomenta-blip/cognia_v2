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
    dijo hace tres turnos."""
    faltantes = faltantes_por_tipo(
        "hazme un script que ordene ficheros",
        contexto="Ultimos turnos:\ntu: todo lo mio va en Python")
    assert "stack" not in _ids(faltantes)


def test_faltantes_no_pregunta_la_fuente_si_el_texto_trae_el_fichero():
    """El .csv escrito por el usuario ES la respuesta a 'donde estan los datos'."""
    assert "fuente" not in _ids(faltantes_por_tipo("analiza ventas.csv y dame la media"))
    assert "fuente" in _ids(faltantes_por_tipo("analiza mis datos de ventas"))


def test_faltantes_tipo_sin_decisiones_devuelve_lista_vacia():
    assert faltantes_por_tipo("hola que tal") == []
    assert faltantes_por_tipo("lo que sea", "otro") == []


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


def test_reunir_un_proveedor_vacio_no_aparece_en_secciones():
    """"No hay" no deja aviso; solo "no se pudo" lo deja."""
    ctx = reunir("arregla el bug", secciones=("entorno", "conversacion", "memorias"),
                 proveedores={"entorno": _prov(""),
                              "conversacion": _prov("   \n  "),
                              "memorias": _prov("- ya paso algo asi")})
    assert list(ctx.secciones) == ["memorias"]
    assert ctx.avisos == []
    assert ctx.recortadas == []


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


# -- humo contra los proveedores REALES ---------------------------------------

def test_humo_reunir_real_es_rapido_en_caliente():
    """Esto corre entre el Enter del usuario y el envio al modelo: el camino
    caliente (segunda llamada del proceso, con `rag` ya descalificado en frio)
    tiene que costar segundos de un digito bajo, no diez."""
    reunir("arregla el bug del login")               # paga los imports y el arranque
    inicio = time.monotonic()
    ctx = reunir("escribe un correo para pedir un aumento")
    tardado = time.monotonic() - inicio
    assert tardado < 3.0, f"reunir() en caliente tardo {tardado:.2f}s: {ctx.avisos}"
    assert ctx.tipo_tarea == "escritura"
    assert ctx.chars <= CM.PRESUPUESTO_CHARS
    # 'rag' es caro en frio: no se pide, se calienta en segundo plano y se
    # DICE que no se pidio.
    assert "rag" in ctx.recortadas or "rag" in ctx.secciones
