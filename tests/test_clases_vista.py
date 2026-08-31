# -*- coding: utf-8 -*-
"""
tests/test_clases_vista.py
==========================
El cuaderno virtual (cognia/clases/vista.py) contra un cuaderno REAL en disco.

Nada de mocks: se fabrica una jornada de verdad con sus JSONL, un PNG valido
byte a byte y un WAV escrito con el modulo `wave`, y se comprueba lo que sale
del HTML. Un test que le pasara un dict a mano a render_html no habria cazado
ninguno de los fallos que importan (el adjunto que no esta, el corte de
materia, la clave de apuntes que cambia de nombre).

AISLAMIENTO. COGNIA_CLASES_DIR se fija a un tmp_path en un fixture autouse:
sin eso estos tests escribirian jornadas de mentira DENTRO del cuaderno real
del duenio (`~/.cognia/clases`), que es justo lo que este modulo existe para
enseniar. El fixture ademas COMPRUEBA el desvio antes de dejar correr el test,
porque un setenv que no llega es indistinguible de un test que pasa.
"""

import base64
import json
import math
import re
import struct
import time
import wave
import zlib

import pytest

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua
from cognia.clases import vista


# ── aislamiento ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, los asserts de abajo
    # seguirian pasando mientras se escribe en el cuaderno de verdad.
    assert alm.raiz() == raiz.resolve() or alm.raiz() == raiz
    # Los topes son estado de MODULO: un test que los baje para probar el
    # enlace los dejaria bajos para todos los que corran despues.
    monkeypatch.setattr(vista, "TOPE_ADJUNTO", vista.TOPE_ADJUNTO)
    monkeypatch.setattr(vista, "TOPE_TOTAL", vista.TOPE_TOTAL)
    yield


# ── material real ────────────────────────────────────────────────────────────

def _png_rojo() -> bytes:
    """Un PNG 1x1 valido de verdad (cabecera + IHDR + IDAT + IEND con sus
    CRC). Se fabrica en vez de traer un fichero al repo para que el test no
    dependa de ningun binario versionado."""
    def trozo(tipo, datos):
        cuerpo = tipo + datos
        return (struct.pack(">I", len(datos)) + cuerpo +
                struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)   # 1x1, 8 bits, RGB
    idat = zlib.compress(b"\x00\xff\x00\x00")             # filtro 0 + pixel rojo
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr) +
            trozo(b"IDAT", idat) + trozo(b"IEND", b""))


def _wav_tono(ruta, ms=120, hz=440):
    """Un WAV mono de 8 kHz con un tono. Escrito con `wave`, no inventado:
    si el fichero no fuera un WAV legal el <audio> del cuaderno tampoco lo
    seria."""
    marcos = int(8000 * ms / 1000)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / 8000)))
            for i in range(marcos)))


XSS = "</script><img onerror=alert(1) src=x>"

# Los dos terminadores de linea de JavaScript, escritos como \uXXXX y no
# pegados crudos: un U+2028 literal en el fuente de un test es invisible en el
# editor y no sobrevive a un round-trip por una codificacion que no sea utf-8,
# asi que el test se volveria verde por haber perdido su propio veneno.
LS, PS = "\u2028", "\u2029"          # LINE / PARAGRAPH SEPARATOR
PEGADO_DE_UN_PDF = "copiado del PDF:" + LS + "segunda linea" + PS + "y otra"


# La jornada se llama por su fecha ISO y el epoch tiene que ser ESE dia a esa
# hora: si no cuadraran, la cabecera de la sesion ensenaria un dia y la etiqueta
# de la jornada otro, y ningun test lo notaria.
INICIO = time.mktime((2026, 8, 30, 8, 15, 0, 0, 0, -1))


def _fabricar(jornada="2026-08-30", inicio_epoch=INICIO):
    """Una jornada completa: dos materias, apuntes, foto, clip, nota
    importante y una nota con un intento de XSS dentro."""
    d = alm.dir_jornada(jornada)

    cua.guardar_jornada(cua.Jornada(nombre=jornada, inicio_epoch=inicio_epoch,
                                    estado="cerrada", segundos=5400.0))

    for c in ({"t": 0.0, "materia": "Fisica", "confianza": 0.91, "por": "manual"},
              {"t": 2700.0, "materia": "Matematicas", "confianza": 0.62,
               "por": "deriva"}):
        alm.apendar(d / alm.CORTES, c)

    for t, texto in ((10.0, "Hoy vemos el efecto Doppler y la ecuacion de ondas."),
                     (600.0, "La frecuencia aparente sube cuando la fuente se acerca."),
                     (2750.0, "Pasamos a derivadas: la regla de la cadena."),
                     (3600.0, "Un ejemplo con funciones compuestas.")):
        alm.apendar(d / alm.TRANSCRIPCION,
                    {"t": t, "t_fin": t + 20.0, "texto": texto, "fuente": "sistema"})

    (d / alm.DIR_ADJUNTOS).mkdir(parents=True, exist_ok=True)
    (d / alm.DIR_ADJUNTOS / "pizarra_0001.png").write_bytes(_png_rojo())
    _wav_tono(d / alm.DIR_ADJUNTOS / "clip_0001.wav")

    entradas = [
        {"t": 300.0, "tipo": cua.TIPO_NOTA, "fuente": "usuario",
         "texto": "ESTO ENTRA EN EL EXAMEN: la formula del corrimiento",
         "importante": True},
        {"t": 700.0, "tipo": cua.TIPO_IMAGEN, "fuente": "usuario",
         "adjunto": "pizarra_0001.png", "texto": "la pizarra con el esquema"},
        {"t": 900.0, "tipo": cua.TIPO_AUDIO, "fuente": "usuario",
         "adjunto": "clip_0001.wav", "texto": "como lo explico al final",
         "t_fin": 900.12},
        {"t": 1200.0, "tipo": cua.TIPO_NOTA, "fuente": "usuario", "texto": XSS},
        {"t": 3000.0, "tipo": cua.TIPO_NOTA, "fuente": "usuario",
         "texto": "los ejercicios 4 y 5 para el viernes"},
        {"t": 3200.0, "tipo": cua.TIPO_IMAGEN, "fuente": "usuario",
         "adjunto": "no_existe.png", "texto": "foto que se perdio"},
    ]
    for e in entradas:
        alm.apendar(d / alm.ENTRADAS, e)

    alm.guardar_json(d / alm.APUNTES, {
        "0": {"titulo": "Efecto Doppler",
              "resumen": "Como cambia la frecuencia percibida con el movimiento.",
              "puntos_clave": ["la fuente que se acerca sube la frecuencia",
                               "la que se aleja la baja"],
              "formulas": ["f' = f (v +- vo) / (v -+ vs)"],
              "examen": ["el corrimiento con fuente en movimiento"],
              "deberes": ["problemas 12 a 15"],
              "bibliografia": "Tipler, capitulo 15"},
        "1": {"titulo": "Regla de la cadena",
              "resumen": "Derivada de funciones compuestas.",
              "claves": ["(f o g)' = f'(g) * g'"]},
    })
    return jornada


def _datos_de(doc: str) -> dict:
    """El JSON que la pagina lleva dentro, sacado del propio HTML.

    Se parsea con json.loads TAL CUAL, sin deshacer antes ningun escape: los
    \\u003c / \\u2028 son escapes JSON legales, y quien tiene que aceptarlos
    es el parser -- si el test los revirtiera a mano estaria comprobando su
    propio replace en vez del literal que va a leer el navegador.
    """
    m = re.search(r"const D = (\{.*?\});\n", doc, re.DOTALL)
    assert m, "no encontre los datos embebidos"
    return json.loads(m.group(1))


# ── construir ────────────────────────────────────────────────────────────────

def test_construir_agrupa_por_materia_con_horas():
    _fabricar()
    datos = vista.construir()
    nombres = [m["nombre"] for m in datos["materias"]]
    assert sorted(nombres) == ["Fisica", "Matematicas"]
    assert datos["total_sesiones"] == 2
    for m in datos["materias"]:
        assert m["n"] == 1
        assert m["segundos"] > 0
        assert m["horas"]            # '45 min', '1 h 05 min'...


def test_construir_filtra_por_materia():
    _fabricar()
    datos = vista.construir(materias=["Fisica"])
    assert [m["nombre"] for m in datos["materias"]] == ["Fisica"]


def test_apuntes_se_leen_con_alias_y_no_pierden_claves_desconocidas():
    _fabricar()
    datos = vista.construir(materias=["Fisica"])
    ap = datos["materias"][0]["sesiones"][0]["apuntes"]
    # 'puntos_clave' es un alias de 'claves': una tabla de un solo nombre
    # habria dejado la ficha vacia sin decir nada.
    assert len(ap["claves"]) == 2
    assert ap["formulas"] and ap["examen"] and ap["deberes"]
    otros = {o["k"] for o in ap["otros"]}
    assert "bibliografia" in otros, "una clave no prevista no puede desaparecer"


def test_la_fecha_y_las_horas_salen_del_reloj_de_la_jornada():
    _fabricar()
    s = vista.construir(materias=["Fisica"])["materias"][0]["sesiones"][0]
    assert "30/08/2026" in s["fecha"] and "domingo" in s["fecha"]
    assert s["hora"] == "08:15"                    # inicio_epoch + t0(0 s)
    # La primera entrada del usuario esta a 300 s del arranque: 08:20 y +05:00.
    primera = s["linea"][0]
    assert primera["hora"] == "08:20" and primera["marca"] == "+05:00"


def test_sin_reloj_de_jornada_la_hora_no_se_inventa():
    """Una jornada sin inicio_epoch (importada, o cerrada a lo bruto) no
    permite reconstruir la hora de pared. Se cae al nombre para la fecha y se
    deja la hora VACIA: poner las 00:00 seria dar por buena una hora falsa."""
    _fabricar(inicio_epoch=0.0)
    s = vista.construir(materias=["Fisica"])["materias"][0]["sesiones"][0]
    assert "30/08/2026" in s["fecha"]
    assert s["hora"] == ""
    assert s["linea"][0]["marca"] == "+05:00"      # el desplazamiento SI existe


def test_transcripcion_va_aparte_de_la_linea_de_tiempo():
    _fabricar()
    s = vista.construir(materias=["Fisica"])["materias"][0]["sesiones"][0]
    assert s["n_dicho"] == 2                       # lo transcrito antes del corte
    tipos = {e["tipo"] for e in s["linea"]}
    assert cua.TIPO_TRANSCRIPCION not in tipos
    # El heno va en minusculas: la busqueda del navegador compara asi.
    assert "doppler" in s["busca"], "el buscador tiene que alcanzar lo dicho"


# ── el HTML ──────────────────────────────────────────────────────────────────

def test_html_contiene_las_dos_materias():
    _fabricar()
    doc = vista.render_html(vista.construir())
    assert "Fisica" in doc
    assert "Matematicas" in doc
    assert doc.startswith("<!doctype html>")
    assert doc.rstrip().endswith("</html>")


def test_la_imagen_viaja_embebida_como_data_uri():
    _fabricar()
    doc = vista.render_html(vista.construir())
    assert "data:image/png;base64," in doc
    m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", doc)
    assert m, "no hay data URI de imagen en la pagina"
    # No basta con que la cadena este: tiene que ser EL png, entero.
    assert base64.b64decode(m.group(1)) == _png_rojo()


def test_el_clip_va_como_audio_reproducible():
    _fabricar()
    doc = vista.render_html(vista.construir())
    assert "<audio" in doc and "controls" in doc
    assert "data:audio/wav;base64," in doc
    m = re.search(r"data:audio/wav;base64,([A-Za-z0-9+/=]+)", doc)
    crudo = base64.b64decode(m.group(1))
    assert crudo[:4] == b"RIFF" and crudo[8:12] == b"WAVE"


def test_la_nota_importante_va_marcada():
    _fabricar()
    s = vista.construir(materias=["Fisica"])["materias"][0]["sesiones"][0]
    importantes = [e for e in s["linea"] if e["importante"]]
    assert len(importantes) == 1
    assert "EXAMEN" in importantes[0]["texto"]
    doc = vista.render_html(vista.construir())
    # La marca visual existe de verdad en la hoja de estilo, no solo en el dato.
    assert ".ent.imp" in doc


def test_el_xss_no_escapa_del_script():
    """El caso que ya quemo a este repo: escapar solo '</' NO basta."""
    _fabricar()
    doc = vista.render_html(vista.construir())
    # Ni la etiqueta viva ni el cierre de script inyectado aparecen crudos.
    assert XSS not in doc
    assert "</script><img" not in doc
    assert "<img onerror" not in doc
    # El dato NO se pierde: sigue entero, escapado, dentro del literal JSON.
    # (Que quede 'onerror=alert(1) src=x>' como texto es inofensivo: sin un
    # '<' delante ningun tokenizador abre etiqueta ninguna.)
    assert XSS.replace("<", "\\u003c") in doc
    # Un solo bloque <script> en toda la pagina: si la nota hubiera cerrado el
    # suyo, aqui habria mas de un cierre.
    assert doc.count("</script>") == 1
    assert doc.count("<script>") == 1
    # Y dentro del bloque no queda NI UN cierre de etiqueta: ese es el
    # invariante real, no la ausencia de una carga concreta.
    cuerpo = doc.split("<script>", 1)[1].split("</script>", 1)[0]
    assert "</" not in cuerpo


def test_un_separador_de_linea_de_js_no_deja_la_pagina_muda():
    """U+2028 y U+2029 son terminadores de LINEA para JavaScript, y
    json.dumps(ensure_ascii=False) los deja crudos. Uno dentro del literal
    parte la sentencia `const D = {...};` por la mitad y la pagina entera se
    queda muda -- el mismo desenlace que el '</script', por otra puerta.

    No es un caso de laboratorio: U+2028 sale al pegar texto de un PDF.
    """
    _fabricar()
    d = alm.dir_jornada("2026-08-30")
    alm.apendar(d / alm.ENTRADAS,
                {"t": 1500.0, "tipo": cua.TIPO_NOTA, "fuente": "usuario",
                 "texto": PEGADO_DE_UN_PDF})

    doc = vista.render_html(vista.construir())
    cuerpo = doc.split("<script>", 1)[1].split("</script>", 1)[0]
    assert LS not in cuerpo and PS not in cuerpo
    assert "\\u2028" in doc and "\\u2029" in doc     # escapados, no borrados
    # Y el texto del duenio sigue entero cuando el navegador lo parsea.
    textos = [e["texto"] for m in _datos_de(doc)["materias"]
              for s in m["sesiones"] for e in s["linea"]]
    assert PEGADO_DE_UN_PDF in textos


def test_el_titulo_tambien_se_escapa():
    doc = vista.render_html(vista.construir(), titulo='Fisica </title><script>alert(1)</script>')
    assert "</title><script>" not in doc
    assert "&lt;/title&gt;" in doc


def test_los_datos_embebidos_son_json_valido():
    """Si el escape rompiera el literal, la pagina cargaria muda. Se recupera
    el JSON de la propia pagina y se parsea."""
    _fabricar()
    recuperado = _datos_de(vista.render_html(vista.construir()))
    assert recuperado["total_sesiones"] == 2
    # Y el dato escapado vuelve a salir IDENTICO del parser: el escape no
    # puede cambiar lo que el duenio escribio, solo como viaja.
    textos = [e["texto"] for m in recuperado["materias"]
              for s in m["sesiones"] for e in s["linea"]]
    assert XSS in textos


# ── degradaciones visibles ───────────────────────────────────────────────────

def test_un_adjunto_que_falta_avisa_y_no_revienta():
    _fabricar()
    datos = vista.construir()
    avisos = " | ".join(datos["avisos"])
    assert "no_existe.png" in avisos and "ya no esta en disco" in avisos
    doc = vista.render_html(datos)
    assert "no_existe.png" in doc            # el aviso se VE en la pagina


def test_un_adjunto_demasiado_grande_se_enlaza_en_vez_de_embeber(monkeypatch):
    _fabricar()
    monkeypatch.setattr(vista, "TOPE_ADJUNTO", 10)   # cualquier cosa pasa el tope
    datos = vista.construir(materias=["Fisica"])
    img = [e for e in datos["materias"][0]["sesiones"][0]["linea"]
           if e["tipo"] == cua.TIPO_IMAGEN][0]
    assert img["src"] == "", "no puede embeberse si pasa el tope"
    assert img["enlace"].startswith("file://")
    assert "tope por adjunto" in img["aviso"]
    assert "data:image/png" not in vista.render_html(datos)


def test_el_pie_anuncia_los_bytes_que_la_pagina_pesa_de_verdad():
    """`bytes_embebidos` es lo que el pie le promete al duenio antes de mandar
    el cuaderno por correo. Tiene que ser lo que las fotos y el audio OCUPAN
    EN EL HTML, no el tamanio de los ficheros de origen: base64 engorda 4/3, y
    contar el origen hacia que la pagina se anunciara un ~35% mas ligera de lo
    que pesa. En un curso con 60 MB de fotos eso son 20 MB de mentira, justo
    en el numero que existe para saber si el correo va a rebotar.
    """
    _fabricar()
    datos = vista.construir()
    doc = vista.render_html(datos)
    en_la_pagina = sum(len(u) for u in
                       re.findall(r"data:[a-z/]+;base64,[A-Za-z0-9+/=]+", doc))
    assert en_la_pagina > 0
    assert datos["bytes_embebidos"] == en_la_pagina
    # Y no es que coincidan por casualidad siendo iguales al origen: el
    # original es sensiblemente mas chico.
    origen = len(_png_rojo())
    assert datos["bytes_embebidos"] > origen * 4 // 3


def test_el_presupuesto_total_se_mide_en_bytes_de_PAGINA(monkeypatch):
    """Tope justo en el tamanio del PNG de origen. Contando origen cabria (no
    lo pasa); contando lo que aniade al HTML no cabe. Este test fija la UNIDAD
    de TOPE_TOTAL, que es lo que se puede volver a torcer sin que nada chille.
    """
    _fabricar()
    monkeypatch.setattr(vista, "TOPE_TOTAL", len(_png_rojo()))
    datos = vista.construir(materias=["Fisica"])
    img = [e for e in datos["materias"][0]["sesiones"][0]["linea"]
           if e["tipo"] == cua.TIPO_IMAGEN][0]
    assert img["src"] == "", "el data: URI pasa el tope aunque el fichero no"
    assert img["enlace"].startswith("file://")
    assert datos["bytes_embebidos"] == 0


def test_el_presupuesto_total_tambien_corta(monkeypatch):
    _fabricar()
    monkeypatch.setattr(vista, "TOPE_TOTAL", 1)
    datos = vista.construir(materias=["Fisica"])
    assert datos["bytes_embebidos"] == 0
    avisos = " | ".join(datos["avisos"])
    assert "tope" in avisos


def test_el_sello_de_generacion_entra_por_parametro():
    """El instante se INYECTA, como en olvido.py. Sin esto `construir()` no es
    una funcion de sus datos: el mismo cuaderno da un HTML distinto cada
    minuto y ningun test puede fijar la pagina. Y el reloj de pared en un test
    es una bomba de relojeria (otro huso, otro dia, otro resultado).
    """
    _fabricar()
    datos = vista.construir(ahora=INICIO)
    assert datos["generado"] == time.strftime("%d/%m/%Y %H:%M",
                                              time.localtime(INICIO))
    assert datos["generado"] in vista.render_html(datos)
    # Con el mismo dato de entrada, la pagina sale byte a byte igual.
    assert vista.render_html(datos) == vista.render_html(datos)
    # Y render_html no pisa el sello que ya trae el dict.
    from datetime import datetime
    otro = vista.construir(ahora=datetime.fromtimestamp(INICIO + 7200))
    assert otro["generado"] != datos["generado"]


def test_cuaderno_vacio_se_abre_igual_y_lo_dice():
    datos = vista.construir()
    assert datos["materias"] == [] and datos["total_sesiones"] == 0
    doc = vista.render_html(datos)
    assert "El cuaderno esta vacio todavia" in doc


# ── export ───────────────────────────────────────────────────────────────────

def test_export_escribe_el_fichero_sin_abrir_navegador(tmp_path, monkeypatch):
    _fabricar()
    import webbrowser

    def _prohibido(*a, **k):
        raise AssertionError("export(open_browser=False) no puede abrir nada")
    monkeypatch.setattr(webbrowser, "open", _prohibido)

    destino = tmp_path / "salida" / "cuaderno.html"
    ruta = vista.export(path=destino, open_browser=False)
    assert ruta == destino
    assert destino.is_file()
    doc = destino.read_text(encoding="utf-8")
    assert len(doc) > 4000
    assert "Fisica" in doc and "Matematicas" in doc
    assert "data:image/png;base64," in doc


def test_export_no_pide_red_ni_ficheros_de_al_lado(tmp_path, monkeypatch):
    """Autocontenido de verdad: cero URLs externas y cero CDN.

    OJO CON COMO SE MIDE. La version anterior de este test recorria
    re.findall(r'(?:src|href)="..."', doc) -- y esa lista es SIEMPRE VACIA,
    porque la pagina no tiene ni un src ni un href estatico: todos los pone el
    JS con setAttribute desde el JSON embebido. El bucle no se ejecutaba nunca
    y el test pasaba dijera lo que dijera el assert de dentro. Se comprueban
    las URLs donde de verdad viven: las del JSON.
    """
    _fabricar()
    # Un adjunto que NO se sabe embeber, para que la pagina lleve tambien la
    # otra clase de URL: la file:// del enlace. Sin el, todos los 'enlace' del
    # JSON salen vacios y el bucle de abajo solo mira los data:, que es medio
    # test -- un CDN colado por la rama del enlace pasaria sin que chille.
    d = alm.dir_jornada("2026-08-30")
    (d / alm.DIR_ADJUNTOS / "esquema_0001.tiff").write_bytes(b"II*\x00nada")
    alm.apendar(d / alm.ENTRADAS,
                {"t": 1100.0, "tipo": cua.TIPO_IMAGEN, "fuente": "usuario",
                 "adjunto": "esquema_0001.tiff", "texto": "el esquema en TIFF"})

    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: None)
    doc = vista.export(path=tmp_path / "c.html", open_browser=False).read_text(encoding="utf-8")

    assert "http://" not in doc and "https://" not in doc
    assert "<link " not in doc and "<script src" not in doc
    assert "url(" not in doc              # ninguna fuente ni imagen de CSS
    # La ausencia de atributos estaticos es el invariante que hacia vacuo al
    # bucle: se afirma a proposito, para que si alguien mete un src="..." en
    # una plantilla este test lo cace en vez de quedarse mudo.
    assert re.findall(r'(?:src|href)="([^"]*)"', doc) == []

    urls = []
    for m in _datos_de(doc)["materias"]:
        for s in m["sesiones"]:
            for e in s["linea"]:
                urls += [e["src"], e["enlace"]]
    # Las dos ramas tienen que estar representadas o el bucle no prueba nada.
    assert any(u.startswith("data:") for u in urls), "ningun adjunto embebido"
    assert any(u.startswith("file:") for u in urls), "ningun adjunto enlazado"
    for u in urls:
        assert u == "" or u.startswith(("data:", "file:", "#")), u
