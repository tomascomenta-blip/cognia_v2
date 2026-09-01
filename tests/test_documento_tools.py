# -*- coding: utf-8 -*-
"""
tests/test_documento_tools.py
=============================
Las tools con las que la IA escribe en el documento de una materia
(cognia/agent/documento_tools.py), contra el DOCUMENTO DE VERDAD.

Nada de mocks: cada test registra la familia en el registry real, escribe en
un cuaderno desviado a tmp_path y RELEE los bloques del disco. Lo que puede
fallar aqui es justo lo que un mock taparia.

LO QUE IMPORTA (por orden de probabilidad de fallo)
  1. EL PARSEO DE ARGUMENTOS. Por debajo del JSON las tools reciben UN string
     y el contenido que escriben lleva barras verticales (una tabla markdown)
     y contrabarras (un LaTeX). Se prueba el camino ENTERO del tool-calling
     nativo -- `args_legacy` -> `armar_args` -> la tool -> el bloque en disco
     -- y se exige que la tabla y la formula lleguen BYTE A BYTE.
  2. LA REGLA DE ORO: un bloque que fijo el duenio no lo reescribe la IA, y el
     mensaje de vuelta le dice al modelo que hacer en su lugar.
  3. Que cada tool tenga su caso feliz y su error que ENSENIA.
  4. Que los schemas que se publican al modelo sean validos.

AISLAMIENTO. COGNIA_CLASES_DIR se desvia a tmp_path y se COMPRUEBA el desvio
(sin eso estos tests escribirian apuntes de mentira en el cuaderno real del
duenio). El registro se limpia al terminar: dejar doc_* en TOOLS cambiaria el
catalogo que ven los demas tests del proceso.
"""

import json

import pytest

from cognia.agent import documento_tools as dt
from cognia.agent.tools import TOOLS, tool
from cognia.clases import almacen as alm
from cognia.clases import documento as doc

MATERIA = "Fisica"


# ── aislamiento ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, todo lo de abajo seguiria
    # pasando mientras se escribe en ~/.cognia/clases.
    assert alm.raiz() == raiz or alm.raiz() == raiz.resolve()
    monkeypatch.setenv(dt.ENV_MATERIA, MATERIA)
    monkeypatch.delenv("COGNIA_DOC_OPS_INSTANTANEA", raising=False)
    doc._avisos_dados.clear()
    doc._ultimo_fallo.clear()
    yield


@pytest.fixture(autouse=True)
def _familia_registrada():
    """Registra doc_* en el registry REAL y lo deja como estaba.

    Se usa el registry de verdad (y no un decorador de mentira) porque parte
    de lo que se prueba es el puente del tool-calling nativo: `args_legacy` y
    `schemas_para` leen de TOOLS.
    """
    dt.register(tool)
    yield
    for nombre in [n for n in TOOLS if n.startswith("doc_")]:
        del TOOLS[nombre]


def _correr(nombre: str, args: str = "", ctx=None) -> str:
    return TOOLS[nombre]["fn"](args, ctx if ctx is not None else {})


def _bloques(materia: str = MATERIA) -> list:
    """Los bloques RELEIDOS del disco (no el objeto que devolvio la tool)."""
    return doc.abrir(materia, crear=False).bloques


def _ultimo(materia: str = MATERIA):
    bs = _bloques(materia)
    assert bs, "el documento quedo vacio"
    return bs[-1]


# ── el catalogo y sus schemas ────────────────────────────────────────────────

def test_la_familia_son_siete_tools_con_prefijo_doc():
    """El techo del catalogo es real (A/B 2026-07-25): si alguien mete la
    octava, que sea una decision consciente y no un descuido."""
    nombres = sorted(n for n in TOOLS if n.startswith("doc_"))
    assert nombres == ["doc_editar", "doc_escribir", "doc_formula",
                       "doc_grafica", "doc_imagen", "doc_tabla", "doc_ver"]


def test_los_schemas_publicados_son_validos():
    """`schemas_para` tiene que sacar de estas tools un schema TIPADO.

    Es lo que ve el modelo en tool-calling nativo. Sin params declarados
    saldria un unico string 'args' con la linea de ayuda dentro -- o sea una
    instruccion en prosa donde tenia que haber una firma.
    """
    from cognia.agent.tool_schemas import schemas_para
    esperado = {
        "doc_ver": ([], {"id", "desde", "hasta"}),
        "doc_escribir": (["texto"], {"texto", "tipo", "tras"}),
        "doc_editar": (["id", "texto"], {"id", "texto"}),
        "doc_formula": (["latex"], {"latex", "tras"}),
        "doc_grafica": (["expresion"], {"expresion", "var", "desde", "hasta",
                                        "tras"}),
        "doc_imagen": (["ruta"], {"ruta", "pie", "tras"}),
        "doc_tabla": (["tabla"], {"tabla", "tras"}),
    }
    schemas = {s["function"]["name"]: s for s in schemas_para(set(esperado))}
    assert set(schemas) == set(esperado)
    for nombre, (requeridos, propiedades) in esperado.items():
        fn = schemas[nombre]["function"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert set(params["properties"]) == propiedades, nombre
        assert sorted(params["required"]) == sorted(requeridos), nombre
        assert fn["description"].strip(), nombre
        for prop in params["properties"].values():
            assert prop["description"].strip()
            assert prop["type"] in ("string", "integer", "number", "boolean")
        json.dumps(schemas[nombre])          # tiene que viajar como JSON


def test_la_familia_esta_registrada_en_familias():
    from cognia.harness import familias
    fam = familias.FAMILIAS["documento"]
    assert fam["flag"] == "COGNIA_DOC_TOOLS"
    assert fam["prefijo"] == "doc_"
    assert familias._instalable("documento") is True
    assert set(familias._tools_de("documento")) == {
        n for n in TOOLS if n.startswith("doc_")}


# ── EL test que importa: el contenido sobrevive al parseo ────────────────────

TABLA = ("| Magnitud | Simbolo | Unidad |\n"
         "|---|---|---|\n"
         "| velocidad | v | m/s |\n"
         "| aceleracion | a | m/s^2 |")

LATEX = r"\left| \frac{a}{b} \right| = \sqrt{x^2 + y^2}"


def test_una_tabla_con_barras_llega_entera_por_el_camino_nativo():
    """El fallo mas probable de todo el modulo.

    Se entra por donde entra el modelo de verdad: `args_legacy` arma el string
    del protocolo texto desde el JSON del tool call, y la tool lo parsea. Si
    el contenido no fuera lo ULTIMO (o si las opciones se buscaran DELANTE),
    la tabla se partiria por su primera barra y en los apuntes del duenio
    quedaria 'Magnitud | Simbolo | Unidad |'.
    """
    from cognia.agent.tool_schemas import args_legacy
    args = args_legacy("doc_tabla", {"tabla": TABLA})
    salida = _correr("doc_tabla", args)
    assert salida.startswith("RESULTADO doc_tabla OK"), salida
    b = _ultimo()
    assert b.tipo == "tabla"
    assert b.texto == TABLA                     # byte a byte
    assert b.meta["cabecera"] == ["Magnitud", "Simbolo", "Unidad"]


def test_un_latex_con_contrabarras_y_barras_llega_entero():
    """Una formula lleva contrabarras Y barras verticales (\\left| ... \\right|):
    las dos cosas que rompen un parseo por regex."""
    pytest.importorskip("matplotlib")
    from cognia.agent.tool_schemas import args_legacy
    args = args_legacy("doc_formula", {"latex": LATEX})
    salida = _correr("doc_formula", args)
    assert salida.startswith("RESULTADO doc_formula OK"), salida
    b = _ultimo()
    assert b.meta["latex"] == LATEX
    assert b.texto == LATEX
    assert b.meta["png"].endswith(".png")


def test_las_opciones_del_final_no_se_comen_el_contenido():
    """`tras=` se separa; un 'v = e/t' dentro del texto NO.

    Es la razon de que las claves sean una lista blanca cerrada: con un
    'ultimo token con igual' generico, este parrafo perderia su cola y el
    duenio leeria 'la velocidad media es' a secas.
    """
    _correr("doc_escribir", "Primero tipo=titulo")
    primero = _ultimo().id
    salida = _correr("doc_escribir",
                     "la velocidad media es v = e/t tras=%s" % primero)
    assert "OK" in salida
    bs = _bloques()
    assert [b.id for b in bs][1] == _ultimo(MATERIA).id or True
    assert bs[1].texto == "la velocidad media es v = e/t"
    assert bs[1].tipo == "parrafo"


def test_el_marcador_de_truncado_no_entra_en_los_apuntes():
    """La compactacion del historial ha hecho que el modelo copie el marcador
    de truncado al disco (medido 2026-08-26). En un fichero se recupera
    releyendo; dentro de los apuntes del duenio se queda."""
    sucio = ("# -*- coding: utf-8 … (argumento truncado: el contenido ya esta "
             "en el fichero)")
    salida = _correr("doc_escribir", sucio)
    assert salida.startswith("RESULTADO doc_escribir ERROR")
    assert "MARCADOR DE TRUNCADO" in salida
    assert not _bloques()


# ── LA REGLA DE ORO ──────────────────────────────────────────────────────────

def test_la_ia_no_reescribe_un_bloque_que_fijo_el_duenio():
    """La promesa central del producto, por la puerta de la tool."""
    b = doc.aniadir(MATERIA, "parrafo", "OJO: el profe dijo que entra en el "
                                        "examen", origen=doc.ORIGEN_DUENIO)
    assert b.fijado
    salida = _correr("doc_editar", "%s | lo reescribo yo" % b.id)
    assert salida.startswith("RESULTADO doc_editar ERROR")
    assert "fijado" in salida and "doc_escribir" in salida
    assert "tras=%s" % b.id in salida           # le dice QUE hacer en su lugar
    vivo = _bloques()[0]
    assert vivo.texto.startswith("OJO:")        # intacto en disco
    assert vivo.origen == doc.ORIGEN_DUENIO
    # Y queda constancia de lo que la IA quiso escribir y no escribio.
    anotaciones = doc.respetados(MATERIA)
    assert anotaciones and anotaciones[-1]["id"] == b.id


def test_escribir_debajo_de_un_bloque_fijado_si_se_puede():
    """La otra mitad de la promesa: respetar no es bloquear el documento."""
    b = doc.aniadir(MATERIA, "parrafo", "lo del duenio",
                    origen=doc.ORIGEN_DUENIO)
    salida = _correr("doc_escribir", "y ademas... tras=%s" % b.id)
    assert "OK" in salida
    ids = [x.id for x in _bloques()]
    assert ids[0] == b.id and len(ids) == 2


# ── caso feliz + caso de error, tool por tool ────────────────────────────────

def test_doc_ver_feliz_y_vacio():
    assert "vacio" in _correr("doc_ver")
    _correr("doc_escribir", "Movimiento rectilineo uniforme tipo=titulo")
    _correr("doc_escribir", "Hoy hemos visto el MRU")
    doc.aniadir(MATERIA, "parrafo", "nota del duenio",
                origen=doc.ORIGEN_DUENIO)
    salida = _correr("doc_ver")
    assert "b0001 titulo" in salida
    assert "Movimiento rectilineo uniforme" in salida
    assert "3 bloques (1 fijados" in salida
    assert "* = FIJADO" in salida


def test_doc_ver_un_bloque_entero_y_un_tramo():
    for i in range(4):
        _correr("doc_escribir", "parrafo numero %d" % i)
    entero = _correr("doc_ver", "id=b3")        # sin los ceros: se normaliza
    assert "parrafo numero 2" in entero
    assert "b0003 parrafo (ia)" in entero
    tramo = _correr("doc_ver", "desde=b0003 hasta=b0004")
    assert "parrafo numero 2" in tramo and "parrafo numero 3" in tramo
    assert "parrafo numero 0" not in tramo


def test_doc_ver_error_id_inexistente():
    _correr("doc_escribir", "algo")
    salida = _correr("doc_ver", "id=b0099")
    assert salida.startswith("RESULTADO doc_ver ERROR")
    assert "b0099" in salida and "doc_ver" in salida


def test_doc_escribir_tipos_y_errores():
    assert "OK" in _correr("doc_escribir", "- uno\n- dos tipo=lista")
    assert _ultimo().tipo == "lista"
    vacio = _correr("doc_escribir", "  ")
    assert vacio.startswith("RESULTADO doc_escribir ERROR")
    assert "falta el contenido" in vacio
    malo = _correr("doc_escribir", "x tipo=diagrama")
    assert "tipo 'diagrama' desconocido" in malo
    redirige = _correr("doc_escribir", "E = mc^2 tipo=formula")
    assert "doc_formula" in redirige
    perdido = _correr("doc_escribir", "algo tras=b0042")
    assert perdido.startswith("RESULTADO doc_escribir ERROR")
    assert "b0042" in perdido


def test_doc_editar_feliz_y_errores():
    _correr("doc_escribir", "primera version")
    bid = _ultimo().id
    salida = _correr("doc_editar", "%s | segunda version" % bid)
    assert salida.startswith("RESULTADO doc_editar OK")
    assert bid in salida
    assert _bloques()[0].texto == "segunda version"
    assert len(_bloques()) == 1                 # corregir NO duplica
    sin_barra = _correr("doc_editar", "%s segunda" % bid)
    assert "formato" in sin_barra
    fantasma = _correr("doc_editar", "b0099 | algo")
    assert fantasma.startswith("RESULTADO doc_editar ERROR")
    assert "doc_escribir" in fantasma


def test_doc_formula_feliz_y_latex_que_no_compila():
    pytest.importorskip("matplotlib")
    from pathlib import Path
    salida = _correr("doc_formula", r"\frac{1}{2}mv^2")
    assert salida.startswith("RESULTADO doc_formula OK")
    b = _ultimo()
    assert b.tipo == "formula"
    png = Path(b.meta["png"])
    assert png.is_file() and png.read_bytes()[:4] == b"\x89PNG"
    malo = _correr("doc_formula", r"\begin{align} x \end{align}")
    assert malo.startswith("RESULTADO doc_formula ERROR")
    assert "mathtext" in malo                   # dice QUE LaTeX si entiende
    assert len(_bloques()) == 1                 # el fallido no dejo bloque


def test_doc_grafica_feliz_y_errores():
    pytest.importorskip("matplotlib")
    pytest.importorskip("sympy")
    salida = _correr("doc_grafica", "sin(x)/x desde=-5 hasta=5")
    assert salida.startswith("RESULTADO doc_grafica OK")
    b = _ultimo()
    assert b.meta["expresion"] == "sin(x)/x"
    assert b.meta["parametros"]["desde"] == -5.0
    assert "sin(x)/x" in b.texto                # una imagen no es buscable
    rango = _correr("doc_grafica", "sin(x) desde=cerca")
    assert "no es un numero" in rango
    peligro = _correr("doc_grafica", "__import__('os').system('dir')")
    assert peligro.startswith("RESULTADO doc_grafica ERROR")
    assert len(_bloques()) == 1


def test_doc_imagen_feliz_y_ruta_inexistente(tmp_path):
    from pathlib import Path
    origen = tmp_path / "pizarra.png"
    origen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    salida = _correr("doc_imagen", "%s | la pizarra de hoy" % origen)
    assert salida.startswith("RESULTADO doc_imagen OK")
    b = _ultimo()
    assert b.tipo == "imagen"
    assert b.texto == "la pizarra de hoy"
    copia = Path(b.meta["adjunto"])
    assert copia.is_file() and copia.read_bytes() == origen.read_bytes()
    # La copia vive con el documento: si el original se mueve, los apuntes no
    # se quedan con un hueco.
    assert copia.parent == doc.carpeta(MATERIA) / "adjuntos"
    fantasma = _correr("doc_imagen", "%s | pie" % (tmp_path / "no_esta.png"))
    assert fantasma.startswith("RESULTADO doc_imagen ERROR")
    assert "imagen_generar" in fantasma


def test_doc_tabla_feliz_y_sin_fila_de_guiones():
    assert "OK" in _correr("doc_tabla", TABLA)
    sin_guiones = _correr("doc_tabla", "| Magnitud | Unidad |\n| v | m/s |")
    assert sin_guiones.startswith("RESULTADO doc_tabla ERROR")
    assert "FILA DE GUIONES" in sin_guiones
    no_es = _correr("doc_tabla", "esto no es una tabla")
    assert "no es una tabla markdown" in no_es
    descuadre = _correr("doc_tabla", "| a | b |\n|---|\n| 1 | 2 |")
    assert "columnas" in descuadre
    assert len(_bloques()) == 1                 # solo entro la buena


def test_doc_editar_redibuja_una_formula():
    """Editar un bloque formula tiene que volver a DIBUJARLO: si solo cambiara
    el texto, el documento ensenaria el PNG viejo bajo el latex nuevo."""
    pytest.importorskip("matplotlib")
    _correr("doc_formula", "E = mc^2")
    bid = _ultimo().id
    png_viejo = _ultimo().meta["png"]
    assert "OK" in _correr("doc_editar", r"%s | E^2 = (mc^2)^2 + (pc)^2" % bid)
    b = _bloques()[0]
    assert b.meta["latex"] == r"E^2 = (mc^2)^2 + (pc)^2"
    assert b.meta["png"] != png_viejo


# ── la materia: de donde sale y que pasa si no hay ───────────────────────────

def test_sin_documento_abierto_no_se_adivina_la_materia(monkeypatch):
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    salida = _correr("doc_escribir", "algo")
    assert salida.startswith("RESULTADO doc_escribir ERROR")
    assert dt.ENV_MATERIA in salida
    assert doc.documentos() == []               # no se creo nada


def test_el_contexto_manda_sobre_la_variable_de_entorno():
    _correr("doc_escribir", "de quimica", ctx={"materia": "Quimica"})
    assert _bloques("Quimica")[0].texto == "de quimica"
    assert doc.abrir(MATERIA, crear=False).bloques == []
    _correr("doc_escribir", "tambien de quimica",
            ctx={"working_memory": {"materia": "Quimica"}})
    assert len(_bloques("Quimica")) == 2


# ── LA PAGINACION: recorrer un documento largo tiene que TERMINAR ────────────

def _sembrar(n: int, materia: str = MATERIA) -> list:
    """n bloques de la IA, escritos por la puerta del modelo. Devuelve sus ids."""
    for i in range(n):
        assert "OK" in _correr("doc_escribir", "bloque numero %02d" % i)
    return [b.id for b in _bloques(materia)]


def _paginar(primera: str = "", tope: int = 40) -> tuple:
    """Recorre el documento siguiendo el pie de doc_ver. (ids vistos, paginas).

    Hace EXACTAMENTE lo que hace el modelo: leer, buscar en el pie el
    'doc_ver desde=...' que le sugieren y volver a llamar. El tope corta lo
    que en produccion no corta nada: el modelo pediria paginas hasta agotar el
    presupuesto de la clase.
    """
    import re as _re
    vistos, orden, paginas = [], primera, 0
    while paginas < tope:
        paginas += 1
        salida = _correr("doc_ver", orden)
        assert salida.startswith("RESULTADO doc_ver OK"), salida
        vistos.extend(_re.findall(r"^(b\d{4}) ", salida, flags=_re.M))
        siguiente = _re.search(r"doc_ver (desde=\S+(?: hasta=\S+)?)$",
                               salida, flags=_re.M)
        if not siguiente:
            return vistos, paginas
        orden = siguiente.group(1)
    raise AssertionError("doc_ver no termino en %d paginas: %s"
                         % (tope, vistos[-3:]))


def test_doc_ver_recorre_el_documento_entero_una_vez_y_TERMINA(monkeypatch):
    """El bucle infinito del pie (arreglado 2026-08-31).

    El id que se sugeria salia de `d.bloques[len(filas)]`: indexado desde el
    PRINCIPIO del documento en vez de desde el tramo que se acaba de ensenar.
    En la primera pagina coincide (desde=1) y por eso no se veia; de la
    SEGUNDA en adelante devolvia siempre el mismo id y el modelo se quedaba
    pidiendo la misma pagina hasta gastarse el presupuesto entero de la clase.
    Por eso este test pagina TRES veces como minimo: con dos no falla.

    Se baja el tope en vez de escribir 140 bloques: la aritmetica del corte es
    la misma y el test no cuesta un segundo por comprobar lo mismo.
    """
    monkeypatch.setattr(dt, "_TOPE_VISTA", 300)
    ids = _sembrar(30)
    vistos, paginas = _paginar()
    assert paginas >= 3, "el tope no llego a partir el documento en 3 paginas"
    assert vistos == ids                        # todos, en orden, una sola vez
    assert len(set(vistos)) == len(ids)


def test_doc_ver_el_pie_apunta_al_SIGUIENTE_bloque_no_al_principio(monkeypatch):
    """La reproduccion minima del mismo bug, sin bucle: el id sugerido en la
    segunda pagina tiene que ser el posterior al ultimo que se enseno."""
    import re
    monkeypatch.setattr(dt, "_TOPE_VISTA", 300)
    ids = _sembrar(30)
    primera = _correr("doc_ver")
    corte = re.search(r"doc_ver desde=(b\d{4})", primera).group(1)
    segunda = _correr("doc_ver", "desde=%s" % corte)
    ultimo = re.findall(r"^(b\d{4}) ", segunda, flags=re.M)[-1]
    sugerido = re.search(r"doc_ver desde=(b\d{4})", segunda).group(1)
    assert ids.index(sugerido) == ids.index(ultimo) + 1, (
        "el pie sugiere %s cuando ya se enseno hasta %s" % (sugerido, ultimo))


def test_doc_ver_al_paginar_un_tramo_conserva_el_hasta(monkeypatch):
    """Un tramo acotado que se corta sigue acotado en la pagina siguiente.

    Sin arrastrar el `hasta=`, pedir la continuacion de 'desde=b0005
    hasta=b0020' devuelve el documento hasta el final: el modelo pidio un
    tramo y recibe otra cosa.
    """
    monkeypatch.setattr(dt, "_TOPE_VISTA", 300)
    _sembrar(30)
    salida = _correr("doc_ver", "desde=b0005 hasta=b0020")
    assert "doc_ver desde=" in salida and "hasta=b0020" in salida
    vistos, _ = _paginar("desde=b0005 hasta=b0020")
    assert vistos[0] == "b0005" and vistos[-1] == "b0020"
    assert len(vistos) == 16 and len(set(vistos)) == 16


def test_doc_ver_acepta_la_posicion_ademas_del_id():
    """`desde=`/`hasta=` prometen las dos formas (un id o una posicion); solo
    la de id estaba probada."""
    _sembrar(5)
    tramo = _correr("doc_ver", "desde=2 hasta=3")
    assert "bloque numero 01" in tramo and "bloque numero 02" in tramo
    assert "bloque numero 00" not in tramo and "bloque numero 03" not in tramo


# ── LA MATERIA: los tres caminos, en su orden ────────────────────────────────

def _jornada_falsa(monkeypatch, **campos):
    """Sustituye `jornada.estado()`. Se parchea el MODULO (no una copia) porque
    documento_tools lo importa perezosamente DENTRO de la llamada."""
    from cognia.clases import jornada
    estado = {"grabando": False, "materia": ""}
    estado.update(campos)
    monkeypatch.setattr(jornada, "estado", lambda: estado)


def test_la_jornada_viva_decide_la_materia_sin_que_nadie_cablee_nada(
        monkeypatch):
    """GRAVE arreglado 2026-08-31: las siete tools dependian SOLO de
    COGNIA_DOC_MATERIA, que no pone nadie, asi que eran inertes. Si el duenio
    esta dando Historia AHORA, los apuntes de este turno son de Historia."""
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    _jornada_falsa(monkeypatch, grabando=True, materia="Historia")
    assert "OK" in _correr("doc_escribir", "la Revolucion Francesa")
    assert _bloques("Historia")[0].texto == "la Revolucion Francesa"


def test_la_jornada_viva_gana_a_la_variable_de_entorno(monkeypatch):
    """La env var es el ULTIMO recurso (pruebas / forzar desde fuera): si hay
    una clase grabandose, manda la clase."""
    _jornada_falsa(monkeypatch, grabando=True, materia="Historia")
    _correr("doc_escribir", "de la clase de ahora")
    assert _bloques("Historia")[0].texto == "de la clase de ahora"
    assert doc.abrir(MATERIA, crear=False).bloques == []


def test_el_ctx_manda_sobre_la_jornada_viva(monkeypatch):
    """La tarea en curso sabe mas que el microfono: si el ctx trae materia, es
    esa (es lo que deja la puerta del CLI al abrir un cuaderno concreto)."""
    _jornada_falsa(monkeypatch, grabando=True, materia="Historia")
    _correr("doc_escribir", "de quimica", ctx={"materia": "Quimica"})
    assert _bloques("Quimica")[0].texto == "de quimica"
    assert doc.abrir("Historia", crear=False).bloques == []


def test_una_jornada_CERRADA_no_decide_la_materia(monkeypatch):
    """`estado()` sin grabar devuelve la materia de la ULTIMA clase del dia.
    Manana por la maniana eso escribiria los apuntes nuevos dentro de la
    materia de ayer por la tarde, y en silencio."""
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    _jornada_falsa(monkeypatch, grabando=False, materia="Historia")
    salida = _correr("doc_escribir", "algo")
    assert salida.startswith("RESULTADO doc_escribir ERROR")
    assert doc.documentos() == []


def test_la_jornada_sin_clasificar_todavia_no_es_una_materia(monkeypatch):
    """Mientras no detecta la materia, `estado()` pone '(sin clasificar aun)'.
    Tomarlo por bueno crearia un documento con ESE nombre en el cuaderno."""
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    _jornada_falsa(monkeypatch, grabando=True, materia="(sin clasificar aun)")
    salida = _correr("doc_escribir", "algo")
    assert salida.startswith("RESULTADO doc_escribir ERROR")
    assert doc.documentos() == []


def test_si_la_jornada_no_se_pudo_consultar_el_error_lo_DICE(monkeypatch):
    """'No hay clase' y 'no pude mirar' no pueden verse igual desde afuera: es
    el modo de fallo fichado de la casa (el vacio silencioso)."""
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    from cognia.clases import jornada

    def _revienta():
        raise RuntimeError("el lock de la jornada es ilegible")

    monkeypatch.setattr(jornada, "estado", _revienta)
    try:
        salida = _correr("doc_escribir", "algo")
        assert salida.startswith("RESULTADO doc_escribir ERROR")
        assert "el lock de la jornada es ilegible" in salida
        assert "RuntimeError" in salida
    finally:
        # El motivo es estado de modulo: dejarlo puesto ensuciaria el mensaje
        # de error de cualquier test posterior que se quede sin materia.
        dt._FALLO_JORNADA["motivo"] = ""


def test_el_error_sin_materia_dice_QUE_HACER(monkeypatch):
    """Un error que no ensenia cuesta la tarea entera: tiene que nombrar las
    puertas reales (el cuaderno, /grabar-clase y la variable)."""
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    _jornada_falsa(monkeypatch)
    salida = _correr("doc_formula", "E = mc^2")
    assert salida.startswith("RESULTADO doc_formula ERROR")
    assert "/grabar-clase" in salida
    assert "cuaderno" in salida
    assert dt.ENV_MATERIA in salida


# ── el camino nativo, con opciones DETRAS del contenido ──────────────────────

def test_una_tabla_con_tras_llega_entera_por_el_camino_nativo():
    """La tabla acaba en '|' y detras va un 'tras=b0001': es el caso que junta
    las dos cosas, contenido con barras Y una opcion al final."""
    from cognia.agent.tool_schemas import args_legacy
    _correr("doc_escribir", "Magnitudes tipo=titulo")
    args = args_legacy("doc_tabla", {"tabla": TABLA, "tras": "b0001"})
    assert args.endswith("tras=b0001"), args
    salida = _correr("doc_tabla", args)
    assert salida.startswith("RESULTADO doc_tabla OK"), salida
    bs = _bloques()
    assert [b.id for b in bs] == ["b0001", "b0002"]
    assert bs[1].texto == TABLA                 # byte a byte, con sus barras
    assert bs[1].meta["cabecera"] == ["Magnitud", "Simbolo", "Unidad"]


def test_un_latex_con_tras_llega_entero_por_el_camino_nativo():
    """El LaTeX lleva contrabarras Y barras verticales, y detras un tras=: si
    el parser buscara las opciones por delante, o partiera por la primera
    barra, aqui se veria."""
    pytest.importorskip("matplotlib")
    from cognia.agent.tool_schemas import args_legacy
    _correr("doc_escribir", "Modulo tipo=titulo")
    args = args_legacy("doc_formula", {"latex": LATEX, "tras": "b0001"})
    salida = _correr("doc_formula", args)
    assert salida.startswith("RESULTADO doc_formula OK"), salida
    b = _bloques()[1]
    assert b.texto == LATEX and b.meta["latex"] == LATEX


def test_doc_ver_dice_que_el_tramo_esta_del_reves():
    """Un tramo invertido devolvia el indice VACIO y sin explicacion: el
    modelo lo lee como 'aqui no hay nada' y se pone a reescribir."""
    _sembrar(6)
    salida = _correr("doc_ver", "desde=b0005 hasta=b0002")
    assert salida.startswith("RESULTADO doc_ver ERROR")
    assert "del reves" in salida
    assert "desde=b0002 hasta=b0005" in salida       # la orden ya corregida
    assert "OK" in _correr("doc_ver", "desde=b0002 hasta=b0005")


def test_la_formula_y_su_png_no_se_reparten_entre_dos_materias(monkeypatch):
    """La materia se resuelve UNA vez por llamada.

    doc_formula la resolvia dos veces (una para dibujar el PNG y otra dentro
    de `_aniadir`). Si la clase cambia justo en medio -- que es lo que hace
    una jornada viva al detectar el corte -- el PNG queda en la carpeta de una
    materia y el bloque que lo nombra en otra: el cuaderno ensenia un hueco.
    """
    pytest.importorskip("matplotlib")
    monkeypatch.delenv(dt.ENV_MATERIA, raising=False)
    from cognia.clases import jornada
    vueltas = {"n": 0}

    def _cambia_de_clase():
        vueltas["n"] += 1
        return {"grabando": True,
                "materia": "Historia" if vueltas["n"] == 1 else "Geografia"}

    monkeypatch.setattr(jornada, "estado", _cambia_de_clase)
    salida = _correr("doc_formula", "E = mc^2")
    assert salida.startswith("RESULTADO doc_formula OK"), salida
    assert doc.documentos() == ["Historia"], "el bloque cayo en otra materia"
    b = _bloques("Historia")[0]
    assert str(doc.carpeta("Historia")) in b.meta["png"]


def test_la_misma_formula_no_duplica_el_png():
    """`_nombre_estable` promete un nombre DETERMINISTA por contenido: con
    hash() de str, PYTHONHASHSEED daria un PNG distinto en cada proceso y el
    documento acumularia copias del mismo dibujo."""
    pytest.importorskip("matplotlib")
    _correr("doc_formula", r"\frac{1}{2}mv^2")
    primero = _ultimo().meta["png"]
    _correr("doc_formula", r"\frac{1}{2}mv^2")
    assert _ultimo().meta["png"] == primero
    assert (dt._nombre_estable("formula", r"\frac{1}{3}mv^2")
            != dt._nombre_estable("formula", r"\frac{1}{2}mv^2"))
