# -*- coding: utf-8 -*-
"""
test_autoprueba_descubre_anidados.py — /construir y /pulir dejan de ser invisibles.

POR QUE EXISTE (medido 2026-08-29): descubrir_productos() iteraba SOLO las
carpetas de primer nivel de generated_programs/. Como /construir escribe en
construidos/<slug>/index.html y /pulir en pulidos/<slug>/index.html, la
biblioteca veia UNA entrada 'construidos' de lenguaje 'vacio' y los 7 productos
de dentro no se probaban jamas: quedaban fuera del examen por construccion.

Y al reves: de las 138 carpetas de la biblioteca real, 68 son salidas de bancos
(b1_/b2_/b3_) que no son productos del dueno. Todas caian como 'vacio' y
arrastraban la media hacia abajo.

Los tests EJERCEN el descubrimiento y la prueba reales sobre ficheros de verdad
en tmp_path, y afirman sobre el catalogo que sale y sobre el veredicto medido.
"""

from pathlib import Path

import pytest

from cognia.autoprueba import (
    CAJONES_ANIDADOS,
    PREFIJOS_BANCO,
    descubrir_productos,
    probar_producto,
    probar_todos,
)
from cognia.program_creator.verificacion import verificar_al_crear

# La pagina lleva animacion propia porque revisar_html() (el criterio estatico
# que ya usaba el repo) exige que la pagina se mueva sola: sin eso reprueba
# antes de llegar a lo que estos tests miden.
PAGINA = """<!DOCTYPE html>
<html><head><title>Ventas</title>
<style>body{background:#123;color:#eee}
.barra{width:40px;height:20px;background:#4af;animation:crece 2s infinite}
@keyframes crece{from{width:20px}to{width:180px}}</style></head>
<body>
  <h1>Ventas mensuales</h1>
  <p>enero: 10</p><p>febrero: 20</p><p>marzo: 30</p>
  <div class="barra"></div>
  <button id="b" onclick="document.getElementById('t').textContent='tocado'">ver</button>
  <div id="t">nada</div>
  <script>console.log("ok");</script>
</body></html>
"""

SCRIPT = '''"""Programa de consola que no pide nada."""


def main():
    print("informe listo")
    print("filas: 3")


if __name__ == "__main__":
    main()
'''


def _base(tmp_path):
    base = tmp_path / "generated_programs"
    base.mkdir()
    (base / "index.json").write_text("[]", encoding="utf-8")
    return base


def _crear(base, ruta_rel, nombre, contenido):
    d = base / ruta_rel
    d.mkdir(parents=True, exist_ok=True)
    (d / nombre).write_text(contenido, encoding="utf-8")
    return d


# ── El descenso de un nivel ───────────────────────────────────────────────────

def test_descubre_los_productos_de_construidos_y_pulidos(tmp_path):
    base = _base(tmp_path)
    _crear(base, "construidos/dashboard_de_ventas", "index.html", PAGINA)
    _crear(base, "pulidos/landing_pulida", "index.html", PAGINA)
    _crear(base, "normal", "program.py", SCRIPT)

    prods = descubrir_productos(base)
    ids = sorted(p["id"] for p in prods)
    assert ids == ["construidos/dashboard_de_ventas", "normal", "pulidos/landing_pulida"]

    # El CAJON en si mismo ya no aparece como producto 'vacio'.
    assert not any(p["id"] in CAJONES_ANIDADOS for p in prods)
    # Y los de dentro tienen entrypoint real, que es lo que faltaba.
    anidado = next(p for p in prods if p["id"].startswith("construidos/"))
    assert anidado["lenguaje"] == "html"
    assert Path(anidado["entrypoint"]).name == "index.html"


def test_el_producto_anidado_se_PRUEBA_de_verdad(tmp_path, monkeypatch):
    """No basta con listarlo: tiene que pasar la bateria y tener veredicto."""
    monkeypatch.setenv("COGNIA_VERIFICAR_NAVEGADOR", "0")   # sin navegador: barato
    base = _base(tmp_path)
    _crear(base, "pulidos/landing_pulida", "index.html", PAGINA)
    prod = next(p for p in descubrir_productos(base) if "pulidos" in p["id"])
    res = probar_producto(prod)
    assert res["fases"]["compila"]["ok"] is True
    assert res["fallo_duro"] is None


def test_verificar_al_crear_alcanza_un_producto_anidado(tmp_path, monkeypatch):
    """El sello de /pulir se escribe sobre pulidos/<slug>, no sobre pulidos/."""
    monkeypatch.setenv("COGNIA_VERIFICAR_NAVEGADOR", "0")
    base = _base(tmp_path)
    d = _crear(base, "pulidos/landing_pulida", "index.html", PAGINA)
    ver = verificar_al_crear(d)
    assert ver["fallo_duro"] != "sin_producto"
    assert ver["lenguaje"] == "html"
    assert Path(ver["entrypoint"]).parent == d


def test_un_cajon_con_codigo_propio_sigue_siendo_producto(tmp_path):
    """Si alguien crea un producto llamado 'pulidos', no se vuelve invisible."""
    base = _base(tmp_path)
    _crear(base, "pulidos", "program.py", SCRIPT)
    _crear(base, "pulidos/algo", "index.html", PAGINA)
    ids = [p["id"] for p in descubrir_productos(base)]
    assert ids == ["pulidos"]              # manda su propio codigo


def test_cajon_vacio_no_aporta_nada(tmp_path):
    base = _base(tmp_path)
    (base / "construidos").mkdir()
    assert descubrir_productos(base) == []


# ── La exclusion de los bancos ────────────────────────────────────────────────

def test_las_carpetas_de_banco_no_son_productos(tmp_path):
    base = _base(tmp_path)
    for pref in PREFIJOS_BANCO:
        _crear(base, f"{pref}corrida_07", "program.py", SCRIPT)
    _crear(base, "producto_de_verdad", "program.py", SCRIPT)

    ids = [p["id"] for p in descubrir_productos(base)]
    assert ids == ["producto_de_verdad"]
    assert probar_todos(base=base, timeout_arranque=6)["total"] == 1


def test_los_bancos_tampoco_se_cuelan_por_dentro_de_un_cajon(tmp_path):
    base = _base(tmp_path)
    _crear(base, "construidos/b1_banco", "index.html", PAGINA)
    _crear(base, "construidos/pagina_real", "index.html", PAGINA)
    ids = [p["id"] for p in descubrir_productos(base)]
    assert ids == ["construidos/pagina_real"]


def test_una_carpeta_que_solo_empieza_parecido_no_se_excluye(tmp_path):
    """'b1_' excluye; 'b1juego' o 'banco_de_pruebas' NO."""
    base = _base(tmp_path)
    _crear(base, "b1juego", "program.py", SCRIPT)
    _crear(base, "banco_de_pruebas", "program.py", SCRIPT)
    _crear(base, "b1_salida", "program.py", SCRIPT)
    ids = sorted(p["id"] for p in descubrir_productos(base))
    assert ids == ["b1juego", "banco_de_pruebas"]
