# -*- coding: utf-8 -*-
"""
tests/test_clases_vista_viva.py
===============================
La pagina que el duenio mira mientras le dan clase (cognia/clases/vista_viva.py)
contra documentos REALES en disco.

Nada de mocks: se escriben bloques de verdad con `documento.py` (que apenda su
diario, hace fsync y emite el evento del bus) y se comprueba lo que sale del
HTML y lo que queda en el modelo. Un test que le pasara un dict a mano a
render_html no habria cazado ninguno de los fallos que importan.

LOS SEIS DE LA CASA. Los primeros seis tests son los mismos invariantes que
vigila `tests/test_clases_vista.py` (cero CDN, cero HTML crudo asignado, script
ASCII, escape del JSON, U+2028 y titulo escapado), copiados a proposito: son
reglas de la CASA y cada pagina nueva tiene que traerlas puestas, no heredarlas
de que alguien se acuerde.

Y LOS DE ESTA PAGINA, que van casi todos de LO MISMO -- no perderle al
duenio nada de lo que tiene puesto:
  - un evento que llega mientras el duenio escribe NO destruye su textarea
    (el bug medido en cognia/oficina/server.py:121, que aqui seria mortal
    porque esta pagina recibe eventos cada pocos segundos);
  - abrir otro bloque NO deja dos editores abiertos, y el "reintentar" del
    banner manda el texto de un bloque a SU id y no al de al lado (el fallo
    de perdida de trabajo que se arreglo el 2026-08-31);
  - un evento no le quita la SELECCION ni le mueve el SCROLL;
  - al irse la pestania no queda ni un timer ni el EventSource, y el banner de
    reconexion ni tapa ni borra el aviso de lo que no se pudo guardar;
  - corregir un bloque lo FIJA, y desde ese momento la IA no lo reescribe;
  - la pagina se genera con el cuaderno vacio sin reventar.

LOS QUE IMPORTAN SON E2E DE VERDAD, con Chromium por playwright: la unica
forma de demostrar que un cursor (o una seleccion, o un scroll) sobrevive es
teclear y mirarlo. La puerta de escritura la sirve el manejador REAL
(`vv.aplicar_accion`) por una ruta interceptada, porque el transporte todavia
no la abre. Se saltan solos si no hay playwright o no hay navegador instalado.
Para excluirlos en CI:

    pytest tests/test_clases_vista_viva.py -k "not e2e"

AISLAMIENTO. COGNIA_CLASES_DIR se desvia a tmp_path en un fixture autouse y se
COMPRUEBA el desvio: sin eso estos tests escribirian documentos de mentira
dentro del cuaderno real del duenio, que es justo lo que este modulo existe
para ensenniar.
"""

import base64
import contextlib
import json
import re
import struct
import time
import zlib

import pytest

from cognia.clases import almacen as alm
from cognia.clases import documento as doc
from cognia.clases import vista_viva as vv


# ── aislamiento ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, los asserts seguirian
    # pasando mientras se escribe en el cuaderno de verdad.
    assert alm.raiz() in (raiz, raiz.resolve())
    yield


# ── material real ────────────────────────────────────────────────────────────

XSS = "</script><img onerror=alert(1) src=x>"

# Los dos terminadores de linea de JavaScript, escritos como \uXXXX y no
# pegados crudos: un U+2028 literal en el fuente de un test es invisible en el
# editor y no sobrevive a un round-trip por una codificacion que no sea utf-8,
# asi que el test se volveria verde por haber perdido su propio veneno.
LS, PS = "\u2028", "\u2029"
PEGADO_DE_UN_PDF = "copiado del PDF:" + LS + "segunda linea" + PS + "y otra"

# Un apunte como los que se pegan de verdad: un trozo de codigo entre acentos
# graves y palabras con tilde. Los dos caracteres van escritos como \uXXXX por
# lo mismo que LS y PS: pegados crudos dependerian de que el fichero viaje en
# utf-8 y el test se volveria verde por haber perdido su propio veneno.
BT = "\u0060"
APUNTE_CON_CODIGO = ("el profe escribio " + BT + "v = e/t" + BT +
                     " y hablo de la aceleraci\u00f3n y la energ\u00eda")

# Markdown en linea con todo lo que puede salir mal a la vez: las marcas que
# hay que pintar, una etiqueta escrita dentro, un enlace que no es web y un
# asterisco suelto que no cierra nada.
MARKDOWN_HOSTIL = (
    "La **segunda ley de Newton** relaciona *fuerza* y " + BT + "masa" + BT +
    ", ver [la ficha](https://ejemplo.invalid/newton), "
    "[no](javascript:alert(1)), <script>alert(2)</script>, </b>, "
    "2*3 y *sin cerrar")

MATERIA = "Fisica"


def _png_rojo() -> bytes:
    """Un PNG 1x1 valido de verdad (cabecera + IHDR + IDAT + IEND con sus
    CRC). Se fabrica en vez de traer un binario al repo."""
    def trozo(tipo, datos):
        cuerpo = tipo + datos
        return (struct.pack(">I", len(datos)) + cuerpo +
                struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr) +
            trozo(b"IDAT", idat) + trozo(b"IEND", b""))


def _documento(materia=MATERIA):
    """Un documento como el que deja el refinado: escrito por la IA, con una
    nota que trae HTML dentro y otra pegada de un PDF."""
    doc.aniadir_ia(materia, doc.TIPO_TITULO, "Movimiento rectilineo uniforme")
    doc.aniadir_ia(materia, doc.TIPO_PARRAFO,
                   "La velocidad media es el espacio entre el tiempo.")
    doc.aniadir_ia(materia, doc.TIPO_LISTA, "- v = e/t\n- t = e/v")
    doc.aniadir_ia(materia, doc.TIPO_PARRAFO, XSS)
    doc.aniadir_ia(materia, doc.TIPO_EXAMEN, PEGADO_DE_UN_PDF)
    return materia


def _pagina(materia=MATERIA, ctx=None, **kw):
    ctx = ctx or {"token": "T0K3N", "eventos": "/eventos?t=T0K3N",
                  "estado": "/estado?t=T0K3N", "adj": "/adj"}
    return vv.render_html(vv.construir(materia), ctx=ctx, **kw)


def _script(doc_html: str) -> str:
    return doc_html.split("<script>", 1)[1].split("</script>", 1)[0]


# Las tres lineas que llevan los DATOS embebidos: el documento del duenio, el
# ctx del transporte y la tabla de tipos. json.dumps no mete saltos de linea,
# asi que cada una ocupa exactamente una linea y se puede apartar entera.
_LINEAS_DE_DATOS = re.compile(r"^var (?:D|C|TIPOS) = .*;$", re.MULTILINE)


def _codigo_js(doc_html: str) -> str:
    """El <script> SIN los literales de datos: el JavaScript que se ejecuta.

    Las reglas de "ni un acento grave" y "solo ASCII" son sobre el CODIGO --
    lo que puede dar SyntaxError y dejar la pagina muda. Los apuntes del
    duenio viajan escapados dentro de un literal JSON y ahi un acento grave o
    una tilde no rompen nada: mirarlos tambien ponia el guardian rojo el dia
    que alguien pegara un trozo de codigo en una nota.
    """
    cuerpo = _script(doc_html)
    codigo, n = _LINEAS_DE_DATOS.subn("", cuerpo)
    assert n == 3, "esperaba 3 lineas de datos embebidos, encontre %d" % n
    return codigo


def _datos_de(doc_html: str) -> dict:
    """El JSON que la pagina lleva dentro, sacado del propio HTML.

    Se parsea TAL CUAL, sin deshacer ningun escape antes: los \\u003c y los
    \\u2028 son escapes JSON legales y quien tiene que aceptarlos es el parser
    -- revertirlos a mano seria comprobar el replace del test en vez del
    literal que va a leer el navegador.
    """
    m = re.search(r"var D = (\{.*?\});\n", doc_html, re.DOTALL)
    assert m, "no encontre los datos embebidos"
    return json.loads(m.group(1))


# ── los seis de la casa ──────────────────────────────────────────────────────

def test_la_pagina_no_pide_red_ni_ficheros_de_al_lado():
    """Cero CDN: la pagina se sirve en 127.0.0.1 con las notas del duenio y no
    puede ir a buscar un byte a ningun sitio. Se comprueba tambien que no
    quede ni un `url(...)` de CSS que no sea una referencia interna: por ahi
    entrarian una fuente o una imagen remotas sin tocar ningun <link>."""
    _documento()
    pagina = _pagina()
    assert "http://" not in pagina
    assert "https://" not in pagina
    assert "<link " not in pagina
    assert "<script src" not in pagina
    assert re.findall(r"url\((?!#)", pagina) == []
    # El cerebrito va INLINE y sin xmlns (dentro de text/html no hace falta):
    # ese xmlns es la unica cadena http del asset y por eso se le quita.
    assert "<svg" in pagina and "xmlns" not in pagina


def test_la_pagina_no_asigna_html_crudo_a_ningun_nodo():
    """Todo el DOM se construye clonando <template> y poniendo textContent /
    setAttribute. El literal no puede aparecer NI EN UN COMENTARIO: asi el
    test no se puede volver verde escribiendo la palabra en otro sitio."""
    _documento()
    pagina = _pagina()
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                      "document.write"):
        assert prohibido not in pagina, prohibido
    assert "<template" in pagina


def test_el_bloque_script_es_ascii_puro():
    """REGLAS_HTML_TEMPLATE_PYTHON.md, regla 2: un solo caracter no-ASCII en
    el <script> puede dar SyntaxError segun como viaje el fichero, y el
    sintoma es la pagina entera muda. Y ni un acento grave: las plantillas de
    cadena de JS no se usan en esta casa. Se mira el CODIGO (ver _codigo_js):
    lo que va escapado dentro de un literal JSON son datos del duenio."""
    _documento()
    pagina = _pagina()
    assert pagina.count("<script>") == 1 and pagina.count("</script>") == 1
    codigo = _codigo_js(pagina)
    malos = [(i, ch) for i, ch in enumerate(codigo) if ord(ch) > 127]
    assert malos == [], malos[:5]
    assert "`" not in codigo


def test_un_apunte_con_acentos_graves_no_pone_rojo_al_guardian_del_script():
    """El guardian de arriba vigilaba el bloque ENTERO, JSON incluido.

    O sea que se ponia rojo el dia que el duenio pegara en una nota un trozo
    de codigo entre acentos graves, o escribiera "aceleracion" con tilde: dos
    cosas normalisimas en unos apuntes, ninguna de las cuales puede dejar la
    pagina muda -- viajan escapadas dentro de un literal JSON. La regla es
    sobre el JavaScript que se ejecuta, y este test fija esa frontera.
    """
    doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO, APUNTE_CON_CODIGO)
    pagina = _pagina()
    codigo = _codigo_js(pagina)
    assert [c for c in codigo if ord(c) > 127] == []
    assert "`" not in codigo
    # Y no pasa por haberle mangado el apunte: el veneno SIGUE en la pagina y
    # el texto vuelve entero del parser.
    assert "`" in _script(pagina)
    assert APUNTE_CON_CODIGO in [b["texto"] for b in _datos_de(pagina)["bloques"]]


def test_el_xss_de_un_apunte_no_escapa_del_script():
    """El caso que ya quemo a este repo: escapar solo '</' NO basta. Un
    '<script' o un '<!--' meten al tokenizador en 'script data escaped' y
    desde ahi el </script> de la plantilla ya no cierra nada."""
    _documento()
    pagina = _pagina()
    assert XSS not in pagina
    assert "</script><img" not in pagina
    assert "<img onerror" not in pagina
    # El dato NO se pierde: sigue entero, escapado, dentro del literal JSON.
    assert XSS.replace("<", "\\u003c") in pagina
    # Y dentro del bloque no queda NI UN cierre de etiqueta: ese es el
    # invariante real, no la ausencia de una carga concreta.
    assert "</" not in _script(pagina)
    # El texto vuelve a salir IDENTICO del parser: el escape cambia como
    # viaja, no lo que el duenio escribio.
    textos = [b["texto"] for b in _datos_de(pagina)["bloques"]]
    assert XSS in textos


def test_un_separador_de_linea_de_js_no_deja_la_pagina_muda():
    """U+2028 y U+2029 son terminadores de LINEA para JavaScript y
    json.dumps(ensure_ascii=False) los deja crudos: uno dentro del literal
    parte `var D = {...};` por la mitad y la pagina se queda muda. No es de
    laboratorio -- sale al pegar texto de un PDF, que es de donde vienen la
    mitad de los apuntes."""
    _documento()
    pagina = _pagina()
    cuerpo = _script(pagina)
    assert LS not in cuerpo and PS not in cuerpo
    assert "\\u2028" in pagina and "\\u2029" in pagina   # escapados, no borrados
    textos = [b["texto"] for b in _datos_de(pagina)["bloques"]]
    assert PEGADO_DE_UN_PDF in textos


def test_el_titulo_se_escapa_y_la_sustitucion_es_de_UNA_pasada():
    """En <title> manda el escape de HTML. Y los placeholders se sustituyen en
    una sola pasada: encadenar .replace() deja que lo ya sustituido se
    reinterprete, y un titulo con '__DATOS__' dentro se comeria el JSON entero
    (el bug que ya se pago en flujoteca_view)."""
    _documento()
    pagina = _pagina(titulo="Fisica </title><script>alert(1)</script> __DATOS__")
    assert "</title><script>" not in pagina
    assert "&lt;/title&gt;" in pagina
    assert pagina.count("<script>") == 1
    # El JSON sigue siendo JSON: el '__DATOS__' del titulo no se sustituyo por
    # segunda vez ni se comio nada.
    assert _datos_de(pagina)["materia"] == MATERIA


# ── los de esta pagina ───────────────────────────────────────────────────────

def test_el_cuaderno_vacio_se_genera_sin_reventar():
    """Sin un solo documento en disco la pagina tiene que salir igual, y
    DECIRLO. Una pagina que revienta con el cuaderno vacio es una pagina que
    solo funciona en la maquina de quien la escribio."""
    datos = vv.construir()
    assert datos["materias"] == [] and datos["bloques"] == []
    assert datos["materia"] == ""
    pagina = vv.render_html(datos)
    assert pagina.startswith("<!doctype html>")
    assert pagina.rstrip().endswith("</html>")
    assert "Todavia no hay ningun documento" in pagina
    # Y con una materia que no existe tampoco: se dice y se sigue.
    datos = vv.construir("Latin")
    assert any("Latin" in a for a in datos["avisos"])
    assert vv.render_html(datos)


def test_corregir_un_bloque_lo_FIJA_y_la_ia_deja_de_tocarlo():
    """La promesa central del producto, comprobada de punta a punta.

    Falla si la puerta de escritura de la pagina entrara por `escribir_ia`
    (que es lo comodo: no lanza y devuelve un informe): el bloque quedaria
    suelto, el refinado se lo comeria en la siguiente pasada y el duenio veria
    desaparecer su correccion sin un solo error por ningun lado.
    """
    _documento()
    r = vv.aplicar_accion({"accion": "editar", "materia": MATERIA,
                           "id": "b0002", "texto": "OJO: el profe dijo otra cosa"})
    assert r["ok"] and r["fijado"] is True

    b = doc.abrir(MATERIA, crear=False).bloque("b0002")
    assert b.fijado is True and b.origen == doc.ORIGEN_DUENIO
    assert b.texto == "OJO: el profe dijo otra cosa"

    # Y ahora la IA no puede: ni reescribirlo ni borrarlo, y queda anotado.
    assert doc.escribir_ia(MATERIA, "b0002", texto="la IA lo pisa")["ok"] is False
    assert doc.borrar_ia(MATERIA, "b0002")["ok"] is False
    assert doc.abrir(MATERIA, crear=False).bloque("b0002").texto == \
        "OJO: el profe dijo otra cosa"
    assert len(doc.respetados(MATERIA)) == 2


def test_lo_fijado_se_VE_en_la_pagina():
    """La regla de oro tiene que verse, no solo cumplirse: si el duenio no
    distingue lo suyo de lo de la IA, la promesa no la compra nadie."""
    _documento()
    vv.aplicar_accion({"accion": "editar", "materia": MATERIA, "id": "b0002",
                       "texto": "mio"})
    datos = vv.construir(MATERIA)
    assert datos["n_fijados"] == 1
    fijados = [b for b in datos["bloques"] if b["fijado"]]
    assert [b["id"] for b in fijados] == ["b0002"]
    pagina = vv.render_html(datos)
    # La marca existe de verdad en la hoja de estilo y en la plantilla, no
    # solo en el dato.
    assert ".bl.fijado" in pagina and 'class="candado"' in pagina


def test_una_accion_desconocida_lo_dice_en_vez_de_callarse():
    r = vv.aplicar_accion({"accion": "volar"})
    assert r["ok"] is False
    assert "volar" in r["error"] and "editar" in r["error"]
    # Y una peticion que no es ni un objeto tampoco revienta el handler.
    assert vv.aplicar_accion("editar")["ok"] is False


def test_un_error_de_documento_vuelve_como_motivo_y_no_como_traceback():
    """Al otro lado hay un handler HTTP: una excepcion aqui es un 500 mudo en
    el que el duenio no distingue "no se pudo" de "no esta cableado"."""
    _documento()
    r = vv.aplicar_accion({"accion": "editar", "materia": MATERIA,
                           "id": "b9999", "texto": "x"})
    assert r["ok"] is False and "b9999" in r["error"]
    r = vv.aplicar_accion({"accion": "tipo", "materia": MATERIA, "id": "b0001",
                           "tipo": "cancion"})
    assert r["ok"] is False and "cancion" in r["error"]


def test_cambiar_el_tipo_conserva_texto_meta_y_SITIO():
    """El modelo no tiene operacion de tipo, asi que se hace con borrar +
    aniadir. Lo que no puede cambiar es lo que el duenio ve: el texto y el
    sitio. El id SI cambia (los ids no se reciclan) y por eso se devuelve."""
    _documento()
    antes = [b.id for b in doc.abrir(MATERIA, crear=False).bloques]
    r = vv.aplicar_accion({"accion": "tipo", "materia": MATERIA,
                           "id": antes[1], "tipo": doc.TIPO_CITA})
    assert r["ok"] and r["id"] != antes[1]
    bloques = doc.abrir(MATERIA, crear=False).bloques
    assert [b.id for b in bloques][0] == antes[0]
    assert bloques[1].tipo == doc.TIPO_CITA
    assert bloques[1].texto == "La velocidad media es el espacio entre el tiempo."
    assert [b.id for b in bloques][2:] == antes[2:]


def test_la_formula_guarda_el_png_y_CONSERVA_el_latex():
    """El latex crudo se queda en el bloque a proposito: es lo que se corrige
    cuando el subindice esta mal y es lo que encuentra `documento.buscar`. Un
    bloque que solo llevara el PNG seria una imagen muerta dentro de unos
    apuntes que se buscan por texto."""
    pytest.importorskip("matplotlib")
    _documento()
    r = vv.aplicar_accion({"accion": "formula", "materia": MATERIA,
                           "latex": r"v = \frac{e}{t}"})
    assert r["ok"], r.get("error")
    b = [x for x in r["bloques"] if x["tipo"] == doc.TIPO_FORMULA][0]
    assert b["texto"] == r"v = \frac{e}{t}"
    assert b["meta"]["latex"] == r"v = \frac{e}{t}"
    ruta = alm.ruta_adjunto(b["jornada"], b["adjunto"])
    assert ruta.is_file() and ruta.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # Y el buscador del modelo lo encuentra por el latex.
    assert [x.id for x in doc.buscar(MATERIA, "frac")] == [b["id"]]


def test_una_imagen_pegada_se_guarda_como_adjunto_y_se_sirve_por_adj():
    """El portapapeles manda un data: URI. Acaba en `almacen.copiar_adjunto`
    como cualquier otra foto -- una segunda forma de nombrar adjuntos acabaria
    con dos convenciones en la misma carpeta."""
    _documento()
    uri = "data:image/png;base64," + base64.b64encode(_png_rojo()).decode("ascii")
    r = vv.aplicar_accion({"accion": "imagen", "materia": MATERIA,
                           "datos": uri, "texto": "la pizarra"})
    assert r["ok"], r.get("error")
    b = [x for x in r["bloques"] if x["tipo"] == doc.TIPO_IMAGEN][0]
    assert alm.ruta_adjunto(b["jornada"], b["adjunto"]).read_bytes() == _png_rojo()
    # La pagina la pinta con una ruta de ESTE servidor, no con base64: por eso
    # existe /adj y por eso esta pagina no tiene topes de embebido.
    pagina = _pagina()
    assert "data:image/png;base64" not in pagina
    assert b["adjunto"] in pagina

    # Lo que el cuaderno no sabe ensenniar se rechaza CON MOTIVO.
    malo = vv.aplicar_accion({"accion": "imagen", "materia": MATERIA,
                              "datos": "data:application/pdf;base64,AAAA"})
    assert malo["ok"] is False and "pdf" in malo["error"]


def test_un_adjunto_que_falta_se_avisa_en_su_bloque():
    """El fallo tipico de esta casa es el vacio silencioso: una imagen que no
    esta y no se explica es exactamente eso."""
    doc.aniadir_ia(MATERIA, doc.TIPO_IMAGEN, "la que se perdio",
                   meta={"adjunto": "no_existe.png", "jornada": "2026-08-30"})
    datos = vv.construir(MATERIA)
    assert "no_existe.png" in datos["bloques"][0]["aviso"]
    assert "no_existe.png" in vv.render_html(datos)


def test_la_pagina_dice_cuanto_hace_que_cerro_el_ultimo_trozo():
    """Tiempo real HONESTO: la latencia minima son los 30 s del trozo mas lo
    que tarde Whisper, asi que un punto verde a secas seria mentira."""
    jornada = "2026-08-30"
    alm.apendar(alm.dir_jornada(jornada) / alm.TRANSCRIPCION,
                {"t": 0.0, "texto": "hoy vemos el efecto Doppler"})
    datos = vv.construir()
    assert datos["ultimo_trozo"] > 0
    assert abs(datos["ultimo_trozo"] - time.time()) < 60
    assert datos["segundos_trozo"] >= 5.0
    pagina = vv.render_html(datos)
    assert "el ultimo trozo cerro hace " in pagina
    assert "EventSource" in pagina          # SSE nativo, sin libreria


def test_render_es_el_gancho_que_espera_servidor_vivo():
    """`fijar_pagina` promete `render(ctx) -> str` con las URLs ya montadas.
    Si la firma no encaja, el transporte sirve el placeholder y el cuaderno
    no aparece nunca."""
    from cognia.clases import servidor_vivo as sv
    _documento()
    try:
        sv.fijar_pagina(vv.render)
        assert sv.estado()["pagina_inyectada"] is True
        ctx = {"base": "http://127.0.0.1:1", "token": "abc", "puerto": 1,
               "eventos": "/eventos?t=abc", "estado": "/estado?t=abc",
               "adj": "/adj", "materia": MATERIA}
        pagina = vv.render(ctx)
        assert "Movimiento rectilineo uniforme" in pagina
        # El token viaja para que el SSE y los adjuntos pasen el guardia (un
        # EventSource no puede poner cabeceras: sin ?t= no hay directo).
        ctx_pagina = json.loads(re.search(r"var C = (\{.*?\});\n", pagina).group(1))
        assert ctx_pagina["token"] == "abc"
        assert ctx_pagina["eventos"] == "/eventos?t=abc"
        assert ctx_pagina["accion"] == vv.RUTA_ACCION
    finally:
        sv.fijar_pagina(None)


def test_todo_tipo_del_modelo_tiene_su_etiqueta_en_la_pagina():
    """El selector de tipo es el punto de extension de la pagina. Un tipo que
    exista en el modelo y no este aqui no se podria elegir NI SE VERIA como lo
    que es: exactamente el fallo que `documento.TIPOS` documenta al explicar
    por que la lista es cerrada."""
    en_la_pagina = [t for t, _ in vv.TIPOS_VISIBLES]
    assert sorted(en_la_pagina) == sorted(doc.TIPOS)
    etiquetas = [e for _, e in vv.TIPOS_VISIBLES]
    assert all(e and e[0].isupper() for e in etiquetas)


def test_la_puerta_de_diagnostico_dice_que_hay_y_que_falta():
    """CLAUDE.md: un subsistema que se calla y uno que no esta cableado no
    pueden verse igual desde fuera."""
    _documento()
    e = vv.estado(MATERIA)
    assert e["materia"] == MATERIA and e["bloques"] == 5
    assert "editar" in e["acciones"] and "formula" in e["acciones"]
    assert isinstance(e["mates"]["ok"], bool) and e["mates"]["motivo"]
    assert "ultimo_fallo" in e


def test_export_escribe_la_pagina_sin_abrir_navegador(tmp_path, monkeypatch):
    _documento()
    import webbrowser

    def _prohibido(*a, **k):
        raise AssertionError("export(open_browser=False) no puede abrir nada")
    monkeypatch.setattr(webbrowser, "open", _prohibido)

    destino = tmp_path / "salida" / "vivo.html"
    ruta = vv.export(path=destino, materia=MATERIA, open_browser=False)
    assert ruta == destino and destino.is_file()
    assert "Movimiento rectilineo uniforme" in destino.read_text(encoding="utf-8")


# ── el e2e: el cursor sobrevive a los eventos ────────────────────────────────

def _arrancar_servidor():
    """Levanta el transporte con esta pagina inyectada. Devuelve (sv, url)."""
    from cognia.clases import servidor_vivo as sv
    sv.fijar_pagina(vv.render)
    datos = sv.arrancar(abrir_navegador=False, timeout_s=5.0)
    return sv, datos["url"] + "&materia=" + MATERIA


def test_e2e_un_evento_no_destruye_el_textarea_que_el_duenio_esta_usando():
    """EL TEST QUE JUSTIFICA LA ARQUITECTURA DE ESTA PAGINA.

    `cognia/oficina/server.py:121` reconstruye su panel cada 2 s y le borra al
    usuario lo que esta tecleando. Esta pagina recibe eventos cada pocos
    segundos, asi que el mismo error seria mortal. Aqui se teclea de verdad en
    Chromium, se mete el cursor EN MEDIO del texto, y mientras tanto la IA
    escribe otro bloque (un `aniadir_ia` real, que apenda al diario y emite
    "clase.entrada"). Al final tiene que seguir todo: el foco, el texto y la
    posicion del cursor.

    Falla en cuanto alguien cambie `pintar()` por un repintado completo
    (vaciar el contenedor y volver a crear los nodos), que es exactamente la
    tentacion que este fichero existe para impedir.

    No corre en CI (necesita navegador): pytest -k "not e2e".
    """
    sync_playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="sin playwright no hay navegador que teclee").sync_playwright

    _documento()
    sv, url = _arrancar_servidor()
    errores = []
    try:
        with sync_playwright() as p:
            try:
                navegador = p.chromium.launch()
            except Exception as exc:                # noqa: BLE001 - se reporta
                pytest.skip("sin Chromium instalado para playwright: %s" % exc)
            pagina = navegador.new_page()
            pagina.on("pageerror", lambda e: errores.append(str(e)))
            pagina.on("console", lambda m: errores.append(m.text)
                      if m.type == "error" else None)
            pagina.goto(url, wait_until="load")
            pagina.wait_for_selector(".bl")
            assert pagina.locator(".bl").count() == 5

            # El duenio abre el segundo bloque y lo corrige a medias.
            pagina.locator('.bl[data-id="b0002"] .vista').click()
            area = pagina.locator('.bl[data-id="b0002"] textarea.ed')
            area.wait_for(state="visible")
            area.click()
            pagina.keyboard.press("End")
            pagina.keyboard.type(" OJO: el profe dijo otra")
            # ...y deja el cursor EN MEDIO, que es donde de verdad duele
            # perderlo.
            for _ in range(5):
                pagina.keyboard.press("ArrowLeft")
            antes = pagina.evaluate(
                "() => { const t = document.querySelector('.bl[data-id=\"b0002\"] "
                "textarea.ed'); return {v: t.value, s: t.selectionStart, "
                "foco: document.activeElement === t}; }")
            assert antes["foco"] is True
            assert antes["v"].endswith(" OJO: el profe dijo otra")

            # Y AHORA la IA escribe. Es una escritura real: diario + fsync +
            # evento del bus + SSE.
            doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO,
                           "la IA sigue escribiendo mientras tu corriges")
            pagina.wait_for_function("() => document.querySelectorAll('.bl').length === 6",
                                     timeout=10000)

            despues = pagina.evaluate(
                "() => { const t = document.querySelector('.bl[data-id=\"b0002\"] "
                "textarea.ed'); return t ? {v: t.value, s: t.selectionStart, "
                "foco: document.activeElement === t} : null; }")
            assert despues is not None, "el evento se llevo por delante el textarea"
            assert despues["foco"] is True, "el evento le quito el foco al duenio"
            assert despues["v"] == antes["v"], "el evento piso lo que se estaba escribiendo"
            assert despues["s"] == antes["s"], "el evento movio el cursor"
            assert pagina.locator('.bl[data-id="b0002"].editando').count() == 1, \
                "el evento repinto el bloque abierto y le quito su estado de edicion"

            # El bloque nuevo si esta pintado: el directo funciona de verdad.
            assert "la IA sigue escribiendo" in pagina.locator("#doc").inner_text()

            # SEGUNDA MITAD DEL CONTRATO: la IA quiere cambiar EL BLOQUE QUE
            # EL DUENIO TIENE ABIERTO. No se pisa: se encola y se avisa.
            assert doc.escribir_ia(MATERIA, "b0002",
                                   texto="la IA reescribe el parrafo")["ok"] is True
            pagina.wait_for_selector('.bl[data-id="b0002"] .cola:not([hidden])',
                                     timeout=10000)
            aviso = pagina.locator('.bl[data-id="b0002"] .cola').inner_text()
            assert "mientras lo corregias" in aviso
            final = pagina.evaluate(
                "() => { const t = document.querySelector('.bl[data-id=\"b0002\"] "
                "textarea.ed'); return t ? {v: t.value, s: t.selectionStart} : null; }")
            assert final is not None, "la reescritura de la IA borro el editor"
            assert final["v"] == antes["v"], "la IA piso lo que el duenio escribia"
            assert final["s"] == antes["s"]
            assert "la IA reescribe el parrafo" not in \
                pagina.locator('.bl[data-id="b0002"]').inner_text()
            navegador.close()
    finally:
        sv.parar()
        sv.fijar_pagina(None)
    assert errores == [], "la pagina dio errores de JavaScript: %s" % errores


# ── el e2e del EDITOR: lo que el duenio teclea no se pierde ni cambia de sitio

def _puerta_de_escritura(pagina, registro, rota=False):
    """Intercepta POST /accion y lo contesta con el manejador REAL de la pagina.

    Se intercepta en el navegador para poder CONTAR lo que sale y para poder
    contestar que NO (`rota=True`, un 404 de solo lectura, que es el caso donde
    vivia el fallo de los dos editores): un servidor que acepta todo no deja
    probar lo que pasa cuando no acepta. Lo que se responde no es un mock del
    resultado sino `vv.aplicar_accion` entero, escribiendo en el cuaderno de
    tmp_path.

    El comodin del final del patron NO sobra: la ruta que la pagina usa lleva
    el token en la query (`/accion?t=...`), y sin el la peticion se le escapa
    al interceptor y acaba en el servidor de verdad -- con `registro` vacio y
    el test fallando por donde no es.
    """
    def manejar(ruta):
        cuerpo = json.loads(ruta.request.post_data or "{}")
        registro.append(cuerpo)
        if rota:
            ruta.fulfill(status=404, content_type="application/json",
                         body=json.dumps({"ok": False,
                                          "error": "este servidor es de SOLO LECTURA"}))
            return
        ruta.fulfill(status=200, content_type="application/json",
                     body=json.dumps(vv.aplicar_accion(cuerpo)))
    pagina.route("**" + vv.RUTA_ACCION + "*", manejar)


def _esperar(pagina, cond, que, ms=8000):
    """Espera a una condicion de PYTHON (las peticiones interceptadas, el
    modelo en disco) sin dormir el bucle del navegador: `wait_for_timeout`
    sigue atendiendo las rutas interceptadas, un `time.sleep` no."""
    fin = time.time() + ms / 1000.0
    while time.time() < fin:
        if cond():
            return
        pagina.wait_for_timeout(50)
    raise AssertionError(que)


def _esperar_banner(pagina, texto, ms=10000):
    """Espera a que el banner DIGA lo que se espera.

    La peticion interceptada y el banner que sale de su respuesta son dos
    momentos distintos: comprobar el texto justo despues de ver salir la
    peticion es una carrera que gana el test unas veces si y otras no.
    """
    pagina.wait_for_function(
        "(t) => { var b = document.querySelector('#banner'); "
        "return !b.hidden && b.textContent.indexOf(t) >= 0; }",
        arg=texto, timeout=ms)


@contextlib.contextmanager
def _cuaderno_en_chromium():
    """Transporte + Chromium + una pagina nueva, y todo cerrado al salir.

    Devuelve (pagina, url, errores). La pagina NO esta cargada todavia: cada
    test instala sus rutas ANTES del goto, que es la unica forma de probar la
    puerta de escritura (que el transporte aun no abre) y la caida del SSE.
    """
    sync_playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="sin playwright no hay navegador que teclee").sync_playwright
    sv, url = _arrancar_servidor()
    errores = []
    try:
        with sync_playwright() as p:
            try:
                navegador = p.chromium.launch()
            except Exception as exc:                # noqa: BLE001 - se reporta
                pytest.skip("sin Chromium instalado para playwright: %s" % exc)
            pagina = navegador.new_page()
            pagina.on("pageerror", lambda e: errores.append(str(e)))
            try:
                yield pagina, url, errores
            finally:
                navegador.close()
    finally:
        sv.parar()
        sv.fijar_pagina(None)


def test_e2e_abrir_otro_bloque_no_deja_DOS_editores_ni_guarda_donde_no_es():
    """EL FALLO MAS CARO QUE PODIA TENER ESTA PAGINA: perder trabajo del duenio.

    `abrirEditor` llamaba a `cerrarEditor(true)` --que es ASINCRONO en cuanto
    hay texto cambiado, porque sale una peticion-- y seguia adelante sin
    esperarlo. Quedaban DOS textareas vivos y UN solo par de variables
    (S.editando / S.area) para los dos, asi que el boton "reintentar" del
    banner leia las del ULTIMO editor y acababa mandando su texto al id del
    otro. Se reproduce con la puerta que hay hoy de verdad (404 de solo
    lectura), que es justo cuando sale ese banner.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        peticiones = []
        _puerta_de_escritura(pagina, peticiones, rota=True)
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")

        pagina.locator('.bl[data-id="b0002"] .vista').click()
        pagina.locator('.bl[data-id="b0002"] textarea.ed').wait_for(state="visible")
        pagina.keyboard.press("End")
        pagina.keyboard.type(" MIO")
        mio = pagina.locator('.bl[data-id="b0002"] textarea.ed').input_value()

        # Y sin guardar (el servidor no deja), se va a corregir OTRO bloque.
        pagina.locator('.bl[data-id="b0003"] .vista').click()
        _esperar(pagina, lambda: len(peticiones) == 1,
                 "el clic en otro bloque ni siquiera intento guardar el primero")
        _esperar_banner(pagina, "No se pudo guardar")

        # 1) NUNCA dos editores abiertos a la vez.
        assert pagina.locator("textarea.ed").count() == 1, \
            "quedaron dos editores abiertos: el texto de uno acaba en el otro"
        assert pagina.locator('.bl[data-id="b0002"] textarea.ed').count() == 1
        # 2) el texto del duenio sigue donde lo dejo.
        assert pagina.locator('.bl[data-id="b0002"] textarea.ed').input_value() == mio
        assert pagina.evaluate("() => S.editando") == "b0002"

        # 3) y el "reintentar" del banner manda ESE texto a ESE bloque.
        del peticiones[:]
        pagina.locator("#banner button").click()
        _esperar(pagina, lambda: len(peticiones) == 1,
                 "el reintento del banner no mando nada")
        assert peticiones[0]["id"] == "b0002", \
            "el reintento guardo en el bloque equivocado: %r" % (peticiones[0],)
        assert peticiones[0]["texto"] == mio
    assert errores == [], errores


def test_e2e_el_editor_siguiente_se_abre_DESPUES_de_que_el_anterior_guarde():
    """La otra mitad del mismo fallo, con la puerta de escritura cableada.

    Aqui el guardado SI sale bien, y volvia tarde: `cerrarDeVerdad` apagaba
    S.editando / S.area, que para entonces ya eran del editor RECIEN ABIERTO.
    Quedaba un textarea en pantalla que ya no era de nadie: lo que se tecleara
    ahi no habia forma de guardarlo por ningun camino. Se comprueba el orden
    real -- primero se guarda (y queda fijado en el modelo), despues se abre
    el otro, y el que queda abierto es el que la pagina cree que tiene.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        peticiones = []
        _puerta_de_escritura(pagina, peticiones)
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")

        pagina.locator('.bl[data-id="b0002"] .vista').click()
        pagina.locator('.bl[data-id="b0002"] textarea.ed').wait_for(state="visible")
        pagina.keyboard.press("End")
        pagina.keyboard.type(" MIO")
        pagina.locator('.bl[data-id="b0003"] .vista').click()

        _esperar(pagina,
                 lambda: pagina.locator('.bl[data-id="b0003"] textarea.ed').count() == 1,
                 "el segundo editor no llego a abrirse detras del guardado")
        assert pagina.locator("textarea.ed").count() == 1
        assert pagina.evaluate("() => S.editando") == "b0003", \
            "el editor abierto quedo desconectado del estado: no se podria guardar"
        # Y lo del primero esta guardado y FIJADO en el modelo de verdad.
        b = doc.abrir(MATERIA, crear=False).bloque("b0002")
        assert b.texto.endswith(" MIO") and b.fijado is True
        assert [q["accion"] for q in peticiones] == ["editar"]
    assert errores == [], errores


def test_e2e_lo_que_escribe_la_IA_arriba_no_le_mueve_el_texto_al_duenio():
    """El scroll tambien es algo que el duenio tiene puesto.

    La IA escribe mientras el duenio lee: si el bloque nuevo entra POR ENCIMA
    de lo que esta mirando y nadie corrige el scroll, el texto le salta hacia
    abajo a media frase. Se mide un bloque concreto antes y despues del
    evento; la referencia se elige mirando la pantalla, no a ojo.
    """
    _documento()
    for i in range(24):
        doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO,
                       "relleno %02d -- " % i + "palabras de clase " * 12)
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.set_viewport_size({"width": 900, "height": 520})
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        n = pagina.locator(".bl").count()
        pagina.evaluate("() => { document.querySelector('main').scrollTop = 900; }")
        ref = pagina.evaluate("""() => {
          var sc = document.querySelector('main'), y = sc.getBoundingClientRect().top;
          var hijos = document.querySelectorAll('#doc .bl');
          for(var i = 0; i < hijos.length; i++){
            var r = hijos[i].getBoundingClientRect();
            if(r.top >= y) return {id: hijos[i].getAttribute('data-id'), y: r.top};
          }
          return null;
        }""")
        assert ref, "el documento de prueba no llego a hacer scroll"

        doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO, "la IA escribe ARRIBA del todo",
                       al_principio=True)
        pagina.wait_for_function(
            "() => document.querySelectorAll('.bl').length === %d" % (n + 1),
            timeout=10000)
        ahora = pagina.evaluate(
            "(id) => document.querySelector('.bl[data-id=\"' + id + '\"]')"
            ".getBoundingClientRect().top", ref["id"])
        assert abs(ahora - ref["y"]) <= 2, \
            "el bloque nuevo le movio el texto %d px" % round(ahora - ref["y"])
    assert errores == [], errores


def test_e2e_un_evento_no_le_quita_al_duenio_lo_que_tiene_SELECCIONADO():
    """La seleccion tambien es trabajo suyo.

    El duenio esta copiando de sus apuntes mientras la IA escribe: repintar el
    bloque que tiene senialado se la borra de las manos. El repintado se
    APLAZA hasta que la suelte -- y entonces entra, porque aplazar no puede
    convertirse en quedarse viejo para siempre (eso seria el otro fallo de
    esta casa, el vacio silencioso).
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        pagina.evaluate("""() => {
          var v = document.querySelector('.bl[data-id="b0002"] .vista');
          var r = document.createRange();
          r.selectNodeContents(v);
          var s = window.getSelection();
          s.removeAllRanges();
          s.addRange(r);
        }""")
        antes = pagina.evaluate("() => window.getSelection().toString()")
        assert "velocidad media" in antes

        assert doc.escribir_ia(MATERIA, "b0002",
                               texto="la IA reescribe el parrafo")["ok"] is True
        # El bloque que llega DESPUES sincroniza: cuando este pintado, el
        # evento del b0002 ya paso por la pagina.
        doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO, "y la IA sigue escribiendo")
        pagina.wait_for_function("() => document.querySelectorAll('.bl').length === 6",
                                 timeout=10000)
        assert pagina.evaluate("() => window.getSelection().toString()") == antes, \
            "el repintado se llevo por delante la seleccion del duenio"
        assert "la IA reescribe" not in \
            pagina.locator('.bl[data-id="b0002"]').inner_text()

        # Y al soltarla, el bloque se pone al dia solo.
        pagina.evaluate("() => window.getSelection().removeAllRanges()")
        pagina.wait_for_function(
            "() => document.querySelector('.bl[data-id=\"b0002\"]')"
            ".textContent.indexOf('la IA reescribe') >= 0", timeout=5000)
    assert errores == [], errores


def test_e2e_al_irse_la_pestania_no_queda_ni_un_timer_ni_el_eventsource():
    """Una pestania que se va no puede dejar nada corriendo: el EventSource
    abierto deja un hilo del servidor esperando con su cola creciendo, y los
    intervalos siguen pidiendo estado a un servidor que ya no mira nadie. Que
    los temporizadores esten EN EL ESTADO no es un detalle de estilo: lo que
    no se guarda no se puede parar."""
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        pagina.wait_for_function("() => S.conectado === true", timeout=10000)
        vivo = pagina.evaluate("() => ({es: !!S.es, directo: !!S.tDirecto, "
                               "estado: !!S.tEstado})")
        assert vivo == {"es": True, "directo": True, "estado": True}, \
            "los temporizadores no estan en el estado: nadie puede pararlos"
        pagina.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
        muerto = pagina.evaluate("() => ({es: !!S.es, directo: !!S.tDirecto, "
                                 "estado: !!S.tEstado, conectado: S.conectado})")
        assert muerto == {"es": False, "directo": False, "estado": False,
                          "conectado": False}
    assert errores == [], errores


def test_e2e_el_banner_de_reconexion_no_abre_dos_eventsource():
    """Dos clics en "reintentar ahora" son UN reintento.

    Sin guardia, el segundo clic cerraba el EventSource que acababa de abrir
    el primero y abria otro: dos conexiones contra el mismo servidor, dos
    colas por cliente y cada operacion del diario aplicada dos veces. Aqui el
    SSE se corta de verdad (la ruta se aborta) para que el banner salga solo,
    y se cuentan los EventSource que la pagina construye.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.route("**/eventos**", lambda ruta: ruta.abort())
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector("#banner:not([hidden])")
        assert "Se corto la conexion" in pagina.locator("#banner").inner_text()
        # El reintento programado se aparta para que lo unico que cuente sean
        # los clics del duenio.
        pagina.evaluate("() => { if(S.tReintento){ clearTimeout(S.tReintento); "
                        "S.tReintento = null; } }")
        pagina.evaluate("() => { window.__n = 0; var V = EventSource; "
                        "window.EventSource = function(u){ window.__n++; "
                        "return new V(u); }; }")
        pagina.evaluate("() => { var b = document.querySelector('#banner button'); "
                        "b.click(); b.click(); }")
        assert pagina.evaluate("() => window.__n") == 1, \
            "el banner abrio mas de un EventSource a la vez"
    assert errores == [], errores


def test_e2e_una_caida_del_SSE_no_borra_el_aviso_de_lo_que_no_se_pudo_guardar():
    """Hay UN banner y varias cosas que contar, y una de ellas lleva DENTRO el
    boton que recupera el texto del duenio.

    Antes, cualquier corte del SSE (o la reconexion, que hacia
    `quitarBanner()` a secas) tapaba o borraba ese aviso: el texto seguia en
    el textarea pero se quedaba sin puerta, y el duenio no tenia forma de
    saber que su correccion no estaba guardada. El estado de la conexion no se
    pierde por eso: sigue en la barra de directo, que es donde no estorba.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        peticiones = []
        _puerta_de_escritura(pagina, peticiones, rota=True)
        pagina.route("**/eventos**", lambda ruta: ruta.abort())
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        pagina.wait_for_selector("#banner:not([hidden])")
        assert "Se corto la conexion" in pagina.locator("#banner").inner_text()

        pagina.locator('.bl[data-id="b0002"] .vista').click()
        pagina.locator('.bl[data-id="b0002"] textarea.ed').wait_for(state="visible")
        pagina.keyboard.press("End")
        pagina.keyboard.type(" MIO")
        pagina.keyboard.press("Control+Enter")
        _esperar(pagina, lambda: len(peticiones) == 1, "el Ctrl+Enter no guardo")
        _esperar_banner(pagina, "No se pudo guardar")

        # Y ahora el SSE se vuelve a caer encima: el aviso del guardado NO se va.
        pagina.evaluate("() => reintentarYa()")
        pagina.wait_for_function("() => S.espera > 0", timeout=10000)
        assert "No se pudo guardar" in pagina.locator("#banner").inner_text(), \
            "la caida del SSE tapo el aviso del texto sin guardar"
        assert "sin conexion" in pagina.locator("#directo").inner_text()

        # Y el boton sigue siendo el que recupera el texto del duenio.
        del peticiones[:]
        pagina.locator("#banner button").click()
        _esperar(pagina, lambda: len(peticiones) == 1, "el reintento no mando nada")
        assert peticiones[0]["id"] == "b0002"
        assert peticiones[0]["texto"].endswith(" MIO")
    assert errores == [], errores


# ── el e2e del PULIDO: lo que el duenio ve al mirar la pagina ────────────────

def test_e2e_el_banner_apagado_no_pinta_ni_una_franja():
    """La franja fantasma. `#banner{display:flex}` lleva especificidad de ID y
    le GANA al `[hidden]{display:none}` de la hoja del navegador: el banner
    apagado se seguia pintando SIEMPRE como una franja vacia de 19 px con su
    linea de borde (crema en claro, verde oliva en oscuro) entre la barra de
    directo y la de herramientas. Parecia un fallo de pintado y no habia forma
    de quitarla, porque quien la ponia era la propia hoja de la pagina.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        medida = pagina.evaluate("""() => {
          const b = document.querySelector('#banner');
          b.hidden = true;
          const r = b.getBoundingClientRect();
          return {display: getComputedStyle(b).display, alto: Math.round(r.height)};
        }""")
        assert medida["display"] == "none", \
            "el banner oculto sigue con display %s" % medida["display"]
        assert medida["alto"] == 0, "el banner oculto ocupa %s px" % medida["alto"]
    assert errores == [], errores


def test_e2e_la_botonera_no_tapa_lo_que_el_duenio_escribe():
    """La botonera estaba en position:absolute ENCIMA del bloque, asi que al
    corregir un parrafo el final de la primera linea desaparecia detras del
    desplegable de tipo: se leia "La aceleracion es propor..." y ahi se
    cortaba.

    Se comprueba lo unico que importa -- que las dos cajas no se tocan -- y se
    comprueba DOS veces: con la botonera de hoy y con una botonera mas alta y
    mas ancha metida a mano. Un arreglo a base de reservar 24 px de hueco
    pasaria la primera y fallaria la segunda, que es justo lo que volveria a
    romperse el dia que la botonera creciera un boton.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        _puerta_de_escritura(pagina, [])
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        pagina.locator('.bl[data-id="b0002"] .vista').click()
        pagina.locator('.bl[data-id="b0002"] textarea.ed').wait_for(state="visible")

        medir = """() => {
          const bl = document.querySelector('.bl[data-id="b0002"]');
          const u = bl.querySelector('.util').getBoundingClientRect();
          const t = bl.querySelector('textarea.ed').getBoundingClientRect();
          return {solapan: !(u.right <= t.left || u.left >= t.right ||
                             u.bottom <= t.top || u.top >= t.bottom),
                  util: [u.left, u.top, u.right, u.bottom],
                  area: [t.left, t.top, t.right, t.bottom]};
        }"""
        antes = pagina.evaluate(medir)
        assert antes["solapan"] is False, \
            "la botonera %r tapa el textarea %r" % (antes["util"], antes["area"])

        # Y ahora la botonera crece: dos botones mas y el doble de alto.
        pagina.evaluate("""() => {
          const u = document.querySelector('.bl[data-id="b0002"] .util');
          for(let i = 0; i < 2; i++){
            const b = document.createElement('button');
            b.textContent = 'otro boton mas';
            b.style.height = '44px';
            u.appendChild(b);
          }
        }""")
        despues = pagina.evaluate(medir)
        assert despues["solapan"] is False, \
            "con la botonera mas grande vuelve a tapar: %r sobre %r" \
            % (despues["util"], despues["area"])
    assert errores == [], errores


def test_e2e_el_markdown_en_linea_se_pinta_y_lo_hostil_se_lee_como_texto():
    """Lo primero que ve el duenio era "La **segunda ley de Newton**
    relaciona...", con sus asteriscos: pintarVista metia el texto con
    textContent y el bloque guarda markdown CRUDO.

    La trampa es que la regla de la casa prohibe el HTML crudo, y con razon:
    aqui se pinta creando NODOS. Asi que se prueba con contenido hostil de
    verdad -- una etiqueta escrita dentro del apunte, un cierre suelto, un
    enlace javascript: y un asterisco que no cierra nada -- y nada de eso
    puede acabar siendo marcado ni desaparecer de la pantalla.
    """
    _documento()
    bid = doc.aniadir_ia(MATERIA, doc.TIPO_PARRAFO, MARKDOWN_HOSTIL).id
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector('.bl[data-id="%s"]' % bid)
        v = pagina.evaluate("""(id) => {
          const v = document.querySelector('.bl[data-id="' + id + '"] .vista');
          const a = v.querySelector('a');
          return {negritas: Array.from(v.querySelectorAll('strong')).map(x => x.textContent),
                  cursivas: Array.from(v.querySelectorAll('em')).map(x => x.textContent),
                  codigos: Array.from(v.querySelectorAll('code')).map(x => x.textContent),
                  enlace: a ? {href: a.getAttribute('href'), texto: a.textContent,
                               target: a.getAttribute('target'),
                               rel: a.getAttribute('rel')} : null,
                  enlaces: v.querySelectorAll('a').length,
                  etiquetas_metidas: v.querySelectorAll('script, b, img').length,
                  texto: v.textContent};
        }""", bid)

        # Las marcas se PINTAN, y sus marcas ya no se leen.
        assert v["negritas"] == ["segunda ley de Newton"]
        assert v["cursivas"] == ["fuerza"]
        assert v["codigos"] == ["masa"]
        assert "**segunda" not in v["texto"] and "*fuerza*" not in v["texto"]

        # El enlace es un enlace de verdad, y se abre fuera sin llevarse la
        # pagina puesta (rel=noopener).
        assert v["enlace"]["href"] == "https://ejemplo.invalid/newton"
        assert v["enlace"]["texto"] == "la ficha"
        assert v["enlace"]["target"] == "_blank"
        assert "noopener" in v["enlace"]["rel"]

        # Y lo hostil se LEE, no se ejecuta ni se borra: un javascript: no es
        # un enlace, una etiqueta escrita es texto, y el asterisco suelto se
        # queda donde el duenio lo puso.
        assert v["enlaces"] == 1, "se pinto un enlace que no es web"
        assert v["etiquetas_metidas"] == 0, "un apunte acabo siendo marcado"
        assert "[no](javascript:alert(1))" in v["texto"]
        assert "<script>alert(2)</script>" in v["texto"]
        assert "</b>" in v["texto"]
        assert "2*3 y *sin cerrar" in v["texto"]
    assert errores == [], errores


def _con_png(jornada, nombre):
    """Deja un PNG de verdad en los adjuntos de una jornada y da su nombre."""
    ruta = alm.ruta_adjunto(jornada, nombre)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(_png_rojo())
    return nombre


def test_e2e_en_tema_oscuro_una_grafica_no_es_un_rectangulo_blanco():
    """matplotlib guarda TINTA OSCURA SOBRE PAPEL BLANCO y `mates.py` no es de
    esta pagina, asi que en tema oscuro una grafica eran 775x537 px de blanco
    deslumbrando sobre un fondo #0d1117. Se arregla donde se sabe que tema
    hay: invirtiendo el PNG. Solo el de formula y grafica -- una FOTO
    invertida seria un negativo -- y nunca al imprimir, que el papel es blanco
    tenga el tema que tenga.
    """
    jornada = "2026-08-30"
    doc.aniadir_ia(MATERIA, doc.TIPO_GRAFICA, "sin(x)/x",
                   meta={"png": _con_png(jornada, "grafica_0001.png"),
                         "jornada": jornada, "expresion": "sin(x)/x"})
    doc.aniadir_ia(MATERIA, doc.TIPO_IMAGEN, "la pizarra",
                   meta={"adjunto": _con_png(jornada, "pegada_0001.png"),
                         "jornada": jornada})
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl.tipo-grafica img")
        filtros = """() => ({
          grafica: getComputedStyle(document.querySelector('.bl.tipo-grafica .vista img')).filter,
          foto: getComputedStyle(document.querySelector('.bl.tipo-imagen .vista img')).filter
        })"""
        pagina.evaluate("() => document.documentElement.setAttribute('data-tema', 'oscuro')")
        oscuro = pagina.evaluate(filtros)
        assert "invert" in oscuro["grafica"], \
            "la grafica sigue siendo papel blanco en tema oscuro (%s)" % oscuro["grafica"]
        assert oscuro["foto"] == "none", \
            "la foto salio invertida, o sea en negativo (%s)" % oscuro["foto"]

        pagina.evaluate("() => document.documentElement.setAttribute('data-tema', 'claro')")
        assert pagina.evaluate(filtros)["grafica"] == "none", \
            "en tema claro no hay nada que invertir"

        # Y al imprimir manda el papel, no el tema.
        pagina.evaluate("() => document.documentElement.setAttribute('data-tema', 'oscuro')")
        pagina.emulate_media(media="print")
        assert pagina.evaluate(filtros)["grafica"] == "none", \
            "la hoja saldria con la grafica en negativo"
        pagina.emulate_media(media="screen")
    assert errores == [], errores


def test_e2e_en_una_pantalla_estrecha_el_cromo_deja_sitio_al_documento():
    """A 390 px el cromo se comia mas de media pantalla: cabecera de 151 px
    partida en tres filas, barra de directo, y una barra de herramientas de
    142 px (casi toda la frase de ayuda envolviendose). Al documento le
    quedaban 203 px de 740: dos bloques y medio, y con scroll seguian siendo
    dos bloques y medio, porque el cromo no scrollea.

    Y el separador "|" de la barra se quedaba huerfano colgando al final de
    una fila, que es lo que pasa cuando un separador y lo que separa son dos
    elementos sueltos en un contenedor que se envuelve.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.set_viewport_size({"width": 390, "height": 740})
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        alto = pagina.evaluate("""() => {
          document.querySelector('#banner').hidden = true;
          return Math.round(document.querySelector('main').getBoundingClientRect().height);
        }""")
        assert alto >= 0.55 * 740, \
            "a 390x740 al documento solo le quedan %d px de 740" % alto

        # El separador nunca cierra una fila: el ultimo elemento pintado de
        # cada fila de la barra tiene que ser algo que se pueda pulsar o leer.
        ultimos = """() => {
          const filas = {};
          Array.from(document.querySelector('#barra').children).forEach(c => {
            const r = c.getBoundingClientRect();
            if(!r.width || !r.height) return;
            const y = Math.round(r.top);
            if(!filas[y] || filas[y].right < r.right) filas[y] = {right: r.right, cl: c.className};
          });
          return Object.keys(filas).map(y => filas[y].cl);
        }"""
        for ancho in (390, 760, 1280):
            pagina.set_viewport_size({"width": ancho, "height": 740})
            colas = pagina.evaluate(ultimos)
            assert not [c for c in colas if "sep" in c], \
                "a %d px una fila de la barra acaba en el separador: %r" % (ancho, colas)
    assert errores == [], errores


def test_e2e_ni_la_cabecera_ni_la_barra_fingen_un_sticky_que_no_scrollea():
    """`header{position:sticky;top:0}` y `#barra{top:47px}` eran codigo muerto
    CON EL NUMERO MAL: el que scrollea es <main>, no el body, asi que ni la
    cabecera ni la barra tienen contra que pegarse -- ya se quedan fijas por
    ser hermanas de main en un flex column. No se veia hoy; se habria visto
    (con 47 px de salto) el dia que alguien tocara el layout.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        v = pagina.evaluate("""() => {
          const e = document.scrollingElement;
          return {header: getComputedStyle(document.querySelector('header')).position,
                  barra: getComputedStyle(document.querySelector('#barra')).position,
                  scrollea_el_body: e.scrollHeight > e.clientHeight + 1,
                  scrollea_main: getComputedStyle(document.querySelector('main')).overflowY};
        }""")
        assert v["scrollea_el_body"] is False, \
            "si el body scrollea, el sticky de la cabecera si haria falta"
        assert v["scrollea_main"] == "auto"
        assert v["header"] == "static", "la cabecera finge un sticky (%s)" % v["header"]
        assert v["barra"] == "static", "la barra finge un sticky (%s)" % v["barra"]
    assert errores == [], errores


def test_e2e_si_el_navegador_bloquea_el_almacenamiento_el_tema_lo_dice():
    """Los dos catch mudos de localStorage eran la regla de la casa aplicada
    al reves: con el almacenamiento bloqueado (ventana privada, politica de
    cookies) el boton de Tema dejaba de recordar la eleccion y no lo decia ni
    por consola. "No lo cablearon" y "se rompio" no pueden verse igual, y
    aqui ni siquiera se veian.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        avisos = []
        pagina.on("console",
                  lambda m: avisos.append(m.text) if m.type == "warning" else None)
        pagina.add_init_script(
            "Object.defineProperty(Storage.prototype, 'setItem', {value: "
            "function(){ throw new Error('almacenamiento bloqueado'); }});")
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector(".bl")
        pagina.locator("#b-tema").click()

        # El tema SI cambia (la eleccion vale para esta pantalla)...
        assert pagina.evaluate(
            "() => document.documentElement.getAttribute('data-tema')") in ("claro", "oscuro")
        # ...pero la pagina dice que no lo va a recordar, y por que.
        pagina.wait_for_selector("#toast.visible", timeout=5000)
        dicho = pagina.locator("#toast").inner_text()
        assert "no deja guardar el tema" in dicho, dicho
        assert "almacenamiento bloqueado" in dicho, dicho
        assert [a for a in avisos if "no deja guardar el tema" in a], avisos
    assert errores == [], errores


def test_e2e_el_contador_del_banner_de_reconexion_descuenta_de_verdad():
    """El banner decia "Reintentando en 2 s" y ahi se quedaba: un numero
    congelado en una pagina que ya parece parada. O es un reloj de verdad o no
    dice segundos -- que es la misma promesa que hace la barra de directo.

    El reintento va con retroceso exponencial (2, 4, 8...), asi que un texto
    que no descuenta NUNCA puede llegar a decir "en 3 s": eso es lo que se
    espera aqui, con el SSE cortado de verdad.
    """
    _documento()
    with _cuaderno_en_chromium() as (pagina, url, errores):
        pagina.route("**/eventos**", lambda ruta: ruta.abort())
        pagina.goto(url, wait_until="load")
        pagina.wait_for_selector("#banner:not([hidden])")
        assert "Se corto la conexion" in pagina.locator("#banner").inner_text()
        pagina.wait_for_function(
            "() => { const b = document.querySelector('#banner'); "
            "return !b.hidden && b.textContent.indexOf('Reintentando en 3 s') >= 0; }",
            timeout=20000)
        # Y el boton que va al lado sigue estando: el texto se reescribe, el
        # banner no se reconstruye.
        assert pagina.locator("#banner button").count() == 1
    assert errores == [], errores
