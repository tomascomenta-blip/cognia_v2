# -*- coding: utf-8 -*-
"""
La vista HTML de la biblioteca de programas (program_creator/biblioteca_view).

Todo corre sobre bibliotecas FALSAS en tmp_path: la real vive en
cognia/program_creator/generated_programs y tiene 137 carpetas del dueno. Un
test que la tocara podria abrir 137 ventanas o borrar trabajo suyo.

Lo que se vigila aqui, y por que:
  - que la pagina sea autocontenida (se abre sin red y con el backend caido);
  - que el JSON embebido escape el cierre de script (esta biblioteca guarda
    HTML generado por Cognia: una descripcion con esa cadena reventaria la
    pagina entera y el fallo se veria como "la pagina esta en blanco");
  - que `export` no abra ventanas cuando no se le pide (e2e, CI, SSH, remoto);
  - que `resolver` acepte lo que el dueno va a teclear de verdad (el id, un
    prefijo, o el numero que ve en la tarjeta) y que un prefijo ambiguo diga
    que es ambiguo en vez de abrir cualquiera de los tres;
  - que el reparto html/python/vacio de `abrir_producto` sea el correcto:
    `webbrowser.open` sobre un `.py` no lo ejecuta, lo descarga.
"""
import json
import os
import subprocess
import webbrowser

import pytest

from cognia.program_creator import biblioteca_view as bv


@pytest.fixture(autouse=True)
def _sin_remoto(monkeypatch):
    """COGNIA_REMOTO apaga toda apertura. Si estuviera puesto en el entorno del
    que corre los tests, la mitad de este fichero pasaria por el motivo
    equivocado."""
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)


def _armar(tmp_path, productos, index=None):
    """Una generated_programs de mentira. productos: {carpeta: {fichero: texto}}."""
    base = tmp_path / "generated_programs"
    base.mkdir(exist_ok=True)
    for carpeta, ficheros in productos.items():
        d = base / carpeta
        d.mkdir()
        for nombre, contenido in ficheros.items():
            (d / nombre).write_text(contenido, encoding="utf-8")
    (base / "index.json").write_text(json.dumps(index or []), encoding="utf-8")
    return base


def _entrada(directorio, **extra):
    """Una entrada de index.json con los campos que exige StoredProgramMeta."""
    fila = {
        "id": directorio, "title": directorio.replace("_", " ").title(),
        "category": "categoria de prueba", "description": "descripcion del indice",
        "total_score": 7.5, "created_at": "2026-08-01T10:00:00",
        "directory": directorio,
    }
    fila.update(extra)
    return fila


# ── Datos ──────────────────────────────────────────────────────────────────────

def test_build_cruza_el_disco_con_el_indice(tmp_path):
    base = _armar(
        tmp_path,
        {"web": {"index.html": "<h1>hola</h1>"},
         "prog": {"main.py": "print(1)\n"},
         "assets": {"nota.txt": "solo imagenes"}},
        index=[_entrada("web", title="Panel web", puntaje_real=9.5,
                        verificado=True),
               _entrada("fantasma")],   # carpeta que ya no existe
    )
    data = bv.build_biblioteca_data(base)

    ids = {it["id"] for it in data["items"]}
    assert ids == {"web", "prog", "assets"}      # el disco manda: 3, no 2
    assert data["total"] == 3
    assert data["fantasmas"] == 1                # la entrada sin carpeta se cuenta
    assert data["en_index"] == 1

    porid = {it["id"]: it for it in data["items"]}
    assert porid["web"]["lenguaje"] == "html"
    assert porid["web"]["title"] == "Panel web"          # el titulo sale del indice
    assert porid["web"]["entrypoint"].endswith("index.html")
    assert porid["prog"]["lenguaje"] == "python"
    assert porid["prog"]["entrypoint"].endswith("main.py")
    assert porid["assets"]["lenguaje"] == "vacio"
    assert porid["assets"]["entrypoint"] == ""
    assert porid["prog"]["en_index"] is False            # huerfana, pero se lista

    # El indice 1..N viaja EN el dato: la pagina se reordena y el numero de la
    # tarjeta sigue siendo el que acepta /biblioteca abrir <n>.
    assert [it["n"] for it in data["items"]] == [1, 2, 3]
    assert porid["web"]["cmd_abrir"] == "/biblioteca abrir web"


def test_el_puntaje_nunca_se_inventa(tmp_path):
    """Regla dura de la casa (2026-07-25): un numero solo si se EJECUTO algo."""
    base = _armar(
        tmp_path,
        {"medido": {"main.py": "print(1)"}, "opinado": {"main.py": "print(1)"}},
        index=[_entrada("medido", puntaje_real=8.0, verificado=True),
               # total_score alto pero NADIE lo ejecuto: no puede salir un 9.9
               _entrada("opinado", total_score=9.9)],
    )
    porid = {it["id"]: it for it in bv.build_biblioteca_data(base)["items"]}
    assert "8.0" in porid["medido"]["puntaje"]
    assert porid["medido"]["puntaje_real"] == 8.0
    assert porid["opinado"]["puntaje"] == "sin verificar"
    assert porid["opinado"]["puntaje_real"] is None
    assert "9.9" not in json.dumps(porid["opinado"])


def test_biblioteca_vacia_no_explota(tmp_path):
    """Espejo de tests/test_autoprueba.py::test_biblioteca_inexistente_no_explota."""
    vacia = bv.build_biblioteca_data(tmp_path / "no_existe")
    assert vacia["total"] == 0 and vacia["items"] == []

    sin_carpetas = bv.build_biblioteca_data(_armar(tmp_path, {}))
    assert sin_carpetas["total"] == 0

    # Y la pagina se pinta igual: el estado vacio es una pantalla, no un crash.
    html = bv.render_html(vacia)
    assert "No hay ningun producto en disco" in html
    assert bv.resolver("1", base=tmp_path / "no_existe") is None


# ── La pagina ──────────────────────────────────────────────────────────────────

def test_render_autocontenido(tmp_path):
    base = _armar(tmp_path, {"web": {"index.html": "<b>x</b>"}},
                  index=[_entrada("web")])
    html = bv.render_html(bv.build_biblioteca_data(base))
    # Sin CDN ni recursos externos: se abre en un avion y con el backend caido.
    assert "http://" not in html and "https://" not in html
    assert "src=" not in html
    assert "<script>" in html and "web" in html          # datos embebidos


def test_render_escapa_el_titulo():
    html = bv.render_html({"total": 0, "items": []}, "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def _datos_embebidos(html):
    """El JSON que la pagina le da a `const DATOS`, ya parseado.

    Se parsea con `json.loads` a proposito: es el mismo trabajo que hace el
    navegador con el literal, asi que si el escape rompiera el dato (o lo
    dejara sin cerrar) esto reventaria aqui en vez de en una pestana.
    """
    linea = [l for l in html.splitlines() if l.startswith("const DATOS = ")][0]
    return json.loads(linea[len("const DATOS = "):].rstrip(";"))


def test_data_escapa_cierre_de_script(tmp_path):
    """Esta biblioteca guarda HTML que Cognia genero: no es un caso teorico.

    ENMENDADO 2026-08-29: antes exigia `"<\\\\/script" in html`, que era el
    escape viejo (`.replace("</", "<\\\\/")`). Ese escape era INSUFICIENTE
    (ver el test de abajo), y el que lo sustituye -- escapar TODOS los "<"
    como `\\u003c` -- ya no produce `<\\/script` en ningun sitio. Lo que se
    exige ahora es lo que de verdad importaba: que del dato no salga ni un
    "<" crudo y que el unico `</script>` de la pagina sea el de la plantilla.
    """
    base = _armar(tmp_path, {"malo": {"main.py": "print(1)",
                                      "description.txt": "</script><b>x"}})
    html = bv.render_html(bv.build_biblioteca_data(base))
    assert "\\u003c/script" in html
    # Y el bloque de datos no se cierra antes de tiempo.
    assert html.count("</script>") == 1
    assert "</script><b>x" not in html
    # El dato sobrevive entero: escapar no es perder.
    assert _datos_embebidos(html)["items"][0]["description"] == "</script><b>x"


def test_data_escapa_tambien_el_comentario_y_el_script_de_apertura(tmp_path):
    """El escape viejo (`"</"` -> `"<\\\\/"`) tapaba el CIERRE y nada mas.

    "<!--" y "<script" no llevan "</" y aun asi son los que rompen: meten al
    tokenizador de HTML en *script data escaped*, y en ese estado el
    `</script>` de la plantilla NO cierra el bloque -- se lo traga el script,
    el JS entero muere por error de sintaxis y la biblioteca sale con la
    barra de filtros pintada y CERO tarjetas. Confirmado en Chromium sobre el
    editor de flujos, que tenia el mismo escape.

    Que parezca vacia en vez de rota es lo peor del fallo: el dueno no va a
    sospechar de la `description` de un producto. Y aqui muchos productos SON
    paginas HTML generadas por Cognia, asi que este texto es el caso normal.
    """
    veneno = "una pagina: <!--<script>alert(1)</script>-- fin"
    base = _armar(tmp_path, {"malo": {"index.html": "<b>x</b>",
                                      "description.txt": veneno}})
    html = bv.render_html(bv.build_biblioteca_data(base))

    # Ni un "<" crudo del dato: ni el del comentario, ni el de la apertura.
    assert "<!--" not in html
    assert veneno not in html
    assert "\\u003c!--\\u003cscript" in html
    # El bloque de datos sigue siendo UNA sola linea y la pagina cierra una
    # sola vez: si el tokenizador se hubiera desviado, el `</script>` final
    # estaria dentro del literal.
    assert html.count("</script>") == 1
    assert html.rstrip().endswith("</script></body></html>")
    # Y el dato llega intacto al navegador.
    assert _datos_embebidos(html)["items"][0]["description"] == veneno


def test_render_no_usa_str_format():
    """Las llaves del CSS/JS reventarian un str.format; el contrato es .replace."""
    assert "{" in bv.HTML and "__DATA__" in bv.HTML and "__TITLE__" in bv.HTML
    html = bv.render_html({"total": 0, "items": []})
    assert "__DATA__" not in html and "__TITLE__" not in html


# ── export ─────────────────────────────────────────────────────────────────────

def test_export_respeta_open_browser(tmp_path, monkeypatch):
    abiertas = []
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertas.append(u) or True)
    base = _armar(tmp_path, {"web": {"index.html": "<b>x</b>"}})
    destino = tmp_path / "salida" / "biblioteca.html"

    ruta = bv.export(str(destino), open_browser=False, base=base)
    assert os.path.exists(ruta) and abiertas == []       # ni una ventana
    assert destino.read_text(encoding="utf-8").startswith("<!doctype html>")

    bv.export(str(destino), open_browser=True, base=base)
    assert len(abiertas) == 1 and abiertas[0].startswith("file:")


# ── resolver ───────────────────────────────────────────────────────────────────

def test_resolver_por_id_prefijo_e_indice(tmp_path):
    base = _armar(tmp_path, {"alfa_uno": {"main.py": "print(1)"},
                             "beta_dos": {"index.html": "<b>x</b>"}})
    orden = [it["id"] for it in bv.build_biblioteca_data(base)["items"]]

    assert bv.resolver("alfa_uno", base=base)["id"] == "alfa_uno"     # id exacto
    assert bv.resolver("ALFA_UNO", base=base)["id"] == "alfa_uno"     # sin importar caja
    assert bv.resolver("beta", base=base)["id"] == "beta_dos"         # prefijo
    assert bv.resolver("1", base=base)["id"] == orden[0]              # indice de la pagina
    assert bv.resolver("2", base=base)["id"] == orden[1]


def test_resolver_id_inexistente_devuelve_None(tmp_path):
    base = _armar(tmp_path, {"alfa_uno": {"main.py": "print(1)"}})
    assert bv.resolver("no_existe_nada", base=base) is None
    assert bv.resolver("", base=base) is None
    assert bv.resolver("99", base=base) is None                       # fuera de rango
    assert bv.resolver("al", base=base) is None                       # prefijo muy corto
    # Y el motivo se puede recuperar: "no existe" y "es ambiguo" piden cosas
    # distintas del dueno.
    assert "fuera de rango" in bv.resolver_detalle("99", base=base)["motivo"]
    assert "demasiado corto" in bv.resolver_detalle("al", base=base)["motivo"]


def test_resolver_prefijo_ambiguo_no_elige_al_azar(tmp_path):
    base = _armar(tmp_path, {"dashboard_01": {"index.html": "<b>1</b>"},
                             "dashboard_02": {"index.html": "<b>2</b>"}})
    assert bv.resolver("dashboard", base=base) is None
    det = bv.resolver_detalle("dashboard", base=base)
    assert "ambiguo" in det["motivo"]
    assert set(det["candidatos"]) == {"dashboard_01", "dashboard_02"}


# ── abrir ──────────────────────────────────────────────────────────────────────

def _dos_productos(tmp_path):
    base = _armar(tmp_path, {"web": {"index.html": "<b>x</b>"},
                             "prog": {"main.py": "print(1)"},
                             "assets": {"nota.txt": "nada"}})
    return {it["id"]: it for it in bv.build_biblioteca_data(base)["items"]}


def test_abrir_html_usa_webbrowser_y_py_usa_startfile(tmp_path, monkeypatch):
    """`webbrowser.open` sobre un `.py` no lo ejecuta: lo descarga o lo abre
    como texto en una pestana. Cada lenguaje va por su via."""
    navegador, so = [], []
    monkeypatch.setattr(webbrowser, "open", lambda u: navegador.append(u) or True)
    # Las dos vias del SO, para que el test valga en los tres sistemas.
    monkeypatch.setattr(os, "startfile", lambda p: so.append(p), raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: so.append(args[-1]))

    items = _dos_productos(tmp_path)

    r = bv.abrir_producto(items["web"])
    assert r["ok"] and r["que"] == "html" and r["abierto"]
    assert len(navegador) == 1 and navegador[0].startswith("file:")
    assert navegador[0].endswith("index.html") and so == []

    r = bv.abrir_producto(items["prog"])
    assert r["ok"] and r["que"] == "programa" and r["abierto"]
    assert len(so) == 1 and str(so[0]).endswith("main.py")
    assert len(navegador) == 1                    # el navegador NO se metio aqui

    # Sin ejecutable no se inventa uno: se abre la carpeta y se dice que es eso.
    r = bv.abrir_producto(items["assets"])
    assert r["ok"] and r["que"] == "carpeta"
    assert str(so[-1]).endswith("assets")


def test_bajo_remoto_no_abre_ventana(tmp_path, monkeypatch):
    """Una ventana en la maquina servidora no le sirve a quien esta al otro
    lado: se devuelve la RUTA y el CLI la imprime."""
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    abiertas = []
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertas.append(u) or True)
    monkeypatch.setattr(os, "startfile", lambda p: abiertas.append(p), raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: abiertas.append(args))

    items = _dos_productos(tmp_path)
    for clave in ("web", "prog", "assets"):
        r = bv.abrir_producto(items[clave])
        assert r["ok"] and r["abierto"] is False
        assert r["ruta"] and "remoto" in r["motivo"]
    assert abiertas == []

    # Y export tampoco: la ruta se devuelve igual.
    ruta = bv.export(str(tmp_path / "b.html"), open_browser=False,
                     base=tmp_path / "generated_programs")
    assert os.path.exists(ruta) and abiertas == []


def test_abrir_ruta_que_ya_no_existe_no_explota(tmp_path, monkeypatch):
    abiertas = []
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertas.append(u) or True)
    r = bv.abrir_producto({"lenguaje": "html", "entrypoint": str(tmp_path / "no.html"),
                           "directorio": ""})
    assert r["ok"] is False and "ya no existe" in r["motivo"] and abiertas == []
    assert bv.abrir_producto({})["ok"] is False
