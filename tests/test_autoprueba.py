# -*- coding: utf-8 -*-
"""
test_autoprueba.py — Regresion del auto-E2E de productos (cognia/autoprueba.py).

Cada test corresponde a un caso que la biblioteca real tiene o tuvo:

  - un producto sano (compila, arranca, tiene cuerpo y doc) -> 10/10
  - uno con SyntaxError: Python NO imprime "Traceback" para eso, solo
    "SyntaxError:". Buscar unicamente "Traceback" daba falso verde y esto
    ya nos mordio hoy. -> test_producto_que_no_compila / test_syntax_error_en_runtime
  - uno que revienta DENTRO del if __name__ == "__main__": el import pasa y el
    arranque falla. Verifica ademas que la fase 'importa' NO ejecuta el main.
  - un stub: main.py con una linea (caso real: cognia_game/main.py es
    literalmente print("hello") al lado del game.py de verdad).
  - un interactivo: pide input() con stdin cerrado, y otro con bucle infinito.
    Ninguno de los dos es un fallo: son la prueba de que arranco.

Los productos son de mentira y viven en tmp_path: no se toca la biblioteca real.
"""

import json

import pytest

from cognia.autoprueba import (
    descubrir_productos,
    evaluar_producto,
    probar_producto,
    probar_todos,
    slash_autoprueba,
)

# ── Productos de mentira ───────────────────────────────────────────────────────

BUENO = '''"""Contador de palabras de un texto de ejemplo."""


def contar_palabras(texto):
    """Devuelve cuantas palabras tiene el texto."""
    return len(texto.split())


def main():
    frase = "contador de palabras sobre un texto de ejemplo"
    print("palabras:", contar_palabras(frase))
    print("letras:", len(frase))


if __name__ == "__main__":
    main()
'''

NO_COMPILA = '''def main(
    print("le falta el parentesis de cierre")
    x = 1
    y = 2
    return x + y
'''

REVIENTA = '''def dividir(a, b):
    return a / b


def main():
    print("arrancando")
    print(dividir(1, 0))


if __name__ == "__main__":
    main()
'''

STUB = '''def hacer():
    pass
'''

INTERACTIVO = '''def main():
    nombre = input("nombre? ")
    print("hola", nombre)


if __name__ == "__main__":
    main()
'''

INTERACTIVO_SIN_GUARDA = '''print("bienvenido al juego")
nombre = input("nombre? ")
print("hola", nombre)
'''

BUCLE = '''import time

if __name__ == "__main__":
    print("dibujando")
    while True:
        time.sleep(0.05)
'''


def _armar_biblioteca(tmp_path, productos, index=None):
    """Crea una carpeta generated_programs de mentira. productos: {carpeta: {archivo: texto}}."""
    base = tmp_path / "generated_programs"
    base.mkdir()
    for carpeta, archivos in productos.items():
        d = base / carpeta
        d.mkdir()
        for nombre, contenido in archivos.items():
            (d / nombre).write_text(contenido, encoding="utf-8")
    (base / "index.json").write_text(json.dumps(index or []), encoding="utf-8")
    return base


def _uno(base, carpeta):
    """Descubre y devuelve el producto de esa carpeta."""
    prods = [p for p in descubrir_productos(base) if p["directorio"].endswith(carpeta)]
    assert prods, f"no se descubrio {carpeta}"
    return prods[0]


def _probar(base, carpeta, timeout=4):
    prod = _uno(base, carpeta)
    res  = probar_producto(prod, timeout_arranque=timeout, timeout_import=timeout)
    return prod, res, evaluar_producto(prod, res)


# ── Descubrimiento ─────────────────────────────────────────────────────────────

def test_descubre_entrypoint_main_py(tmp_path):
    # main.py manda aunque haya otros .py: es la convencion del pipeline.
    base = _armar_biblioteca(tmp_path, {"p": {"main.py": BUENO, "otro.py": STUB}})
    prod = _uno(base, "p")
    assert prod["entrypoint"].endswith("main.py")
    assert len(prod["archivos_py"]) == 2


def test_descubre_entrypoint_unico_py(tmp_path):
    base = _armar_biblioteca(tmp_path, {"p": {"program.py": BUENO}})
    assert _uno(base, "p")["entrypoint"].endswith("program.py")


def test_descubre_entrypoint_por_guarda_main(tmp_path):
    # Sin main.py y con varios .py, gana el que tiene if __name__ == "__main__".
    base = _armar_biblioteca(tmp_path, {"p": {"aaa_lib.py": STUB, "zzz_app.py": BUENO}})
    assert _uno(base, "p")["entrypoint"].endswith("zzz_app.py")


def test_carpeta_sin_codigo_es_producto_vacio(tmp_path):
    # Caso real: 12 carpetas de la biblioteca solo tienen input_images/.
    base = _armar_biblioteca(tmp_path, {"p": {}})
    (base / "p" / "input_images").mkdir()
    prod = _uno(base, "p")
    assert prod["lenguaje"] == "vacio" and prod["entrypoint"] is None
    res = probar_producto(prod)
    assert res["fallo_duro"] == "sin_codigo"
    assert evaluar_producto(prod, res)["puntaje"] == 0.0


def test_el_disco_manda_sobre_el_index(tmp_path):
    # El index real tiene 9 entradas cuyas carpetas ya no existen: si lo usaramos
    # como catalogo probariamos fantasmas.
    base = _armar_biblioteca(
        tmp_path, {"real": {"program.py": BUENO}},
        index=[{"id": "fantasma", "directory": "no_existe", "description": "x"}])
    ids = [p["id"] for p in descubrir_productos(base)]
    assert ids == ["real"] and "fantasma" not in ids


# ── Un producto de cada clase ──────────────────────────────────────────────────

def test_producto_bueno_saca_diez(tmp_path):
    base = _armar_biblioteca(
        tmp_path,
        {"bueno": {"program.py": BUENO,
                   "README.md": "Contador de palabras. Corre con python program.py y muestra el conteo."}},
        index=[{"id": "bueno", "directory": "bueno", "title": "Contador",
                "description": "Un contador de palabras sobre un texto de ejemplo."}])
    prod, res, ev = _probar(base, "bueno")

    assert res["fallo_duro"] is None
    assert res["fases"]["compila"]["ok"] and res["fases"]["compila"]["compilan"] == 1
    assert res["fases"]["importa"]["ok"] is True
    assert res["fases"]["arranca"]["ok"] is True
    assert "palabras: 8" in res["fases"]["arranca"]["stdout"]
    assert ev["desglose"] == {"compila": 3.0, "arranca": 3.0, "sin_stubs": 2.0,
                              "documentacion": 1.0, "coincide_descripcion": 1.0}
    assert ev["puntaje"] == 10.0


def test_producto_que_no_compila(tmp_path):
    base = _armar_biblioteca(tmp_path, {"roto": {"program.py": NO_COMPILA}})
    prod, res, ev = _probar(base, "roto")

    assert res["fallo_duro"] == "compila"
    assert res["fases"]["compila"]["ok"] is False
    assert res["fases"]["compila"]["compilan"] == 0
    # Se corta la cadena: no tiene sentido importar algo que no parsea.
    assert res["fases"]["importa"]["ok"] is None
    assert res["fases"]["arranca"]["ok"] is None
    assert ev["desglose"]["compila"] == 0.0
    assert ev["desglose"]["arranca"] == 0.0
    assert ev["puntaje"] < 4.0


def test_producto_que_revienta_al_arrancar(tmp_path):
    base = _armar_biblioteca(
        tmp_path, {"revienta": {"program.py": REVIENTA}},
        index=[{"id": "revienta", "directory": "revienta",
                "description": "divide numeros"}])
    prod, res, ev = _probar(base, "revienta")

    # El import pasa porque el crash vive dentro de la guarda __main__: eso
    # prueba que la fase 'importa' no corre el main.
    assert res["fases"]["importa"]["ok"] is True
    assert res["fallo_duro"] == "arranca"
    assert res["fases"]["arranca"]["ok"] is False
    assert "ZeroDivisionError" in res["fases"]["arranca"]["stderr"]
    assert ev["desglose"]["compila"] == 3.0
    assert ev["desglose"]["arranca"] == 0.0
    assert ev["puntaje"] <= 7.0


def test_producto_stub(tmp_path):
    base = _armar_biblioteca(tmp_path, {"hueco": {"program.py": STUB}})
    prod, res, ev = _probar(base, "hueco")

    # Corre y sale con 0, pero no hace nada: el puntaje tiene que verlo.
    assert res["fases"]["arranca"]["ok"] is True
    assert res["fases"]["sin_stubs"]["ok"] is False
    assert res["fases"]["sin_stubs"]["funciones_huecas"] == ["hacer"]
    assert res["fases"]["sin_stubs"]["vacios"]     # <5 lineas utiles
    assert ev["desglose"]["sin_stubs"] == 0.0
    assert ev["desglose"] == {"compila": 3.0, "arranca": 3.0, "sin_stubs": 0.0,
                              "documentacion": 0.0, "coincide_descripcion": 0.0}
    assert ev["puntaje"] == 6.0


def test_marcador_todo_baja_a_medio_punto(tmp_path):
    codigo = BUENO.replace('print("letras:", len(frase))',
                           'print("letras:", len(frase))  # TODO: soportar acentos')
    base = _armar_biblioteca(tmp_path, {"todo": {"program.py": codigo}})
    prod, res, ev = _probar(base, "todo")
    assert res["fases"]["sin_stubs"]["marcadores"] == 1
    assert ev["desglose"]["sin_stubs"] == 1.0   # senal leve, no vacio


# ── Interactivos: timeout NO es fallo ──────────────────────────────────────────

def test_interactivo_ahora_se_ejecuta_de_verdad_con_guion(tmp_path):
    """CAMBIO DE COMPORTAMIENTO 2026-08-29 (era test_interactivo_con_stdin_cerrado).

    Antes este producto "arrancaba" muriendo de EOFError sin ejecutar una sola
    linea de su logica, y se le daban los 3 puntos igual. Ahora se le TECLEA un
    guion derivado de su propio prompt ("nombre? " -> "Cognia"), asi que llega
    al final: el stderr esta LIMPIO y el stdout trae el resultado.
    """
    base = _armar_biblioteca(tmp_path, {"juego": {"program.py": INTERACTIVO}})
    prod, res, ev = _probar(base, "juego")
    arr = res["fases"]["arranca"]
    assert arr["ok"] is True, arr["detalle"]
    assert arr["origen_guion"] == "derivado" and arr["guion"][0] == "Cognia"
    assert "EOFError" not in arr["stderr"]        # ya no muere de teclado
    assert "hola Cognia" in arr["stdout"]         # EJECUTO su logica
    # Brazo B: la MISMA corrida con otro nombre saluda a otro -> stdout distinto.
    assert arr["no_reacciona"] is False
    assert arr["brazo_b"]["guion"][0] == "Zenta"
    assert "hola Zenta" in arr["brazo_b"]["stdout"]
    assert "hola Cognia" not in arr["brazo_b"]["stdout"]
    assert ev["desglose"]["arranca"] == 3.0


def test_interactivo_sin_guarda_main_no_falla_al_importar(tmp_path):
    # BUG REAL cazado en la primera corrida sobre la biblioteca (2026-07-23):
    # royal_favors, stem_encryptor, decent_dilemma y reaction_diffusion_simulator
    # tienen el input() al nivel del modulo, sin guarda __main__. La fase
    # 'importa' los ejecutaba, moria con EOFError y los marcaba fallo duro:
    # royal_favors sacaba 6.0 en vez de 9.0. Es culpa de la prueba, no del
    # producto.
    base = _armar_biblioteca(tmp_path, {"juego2": {"program.py": INTERACTIVO_SIN_GUARDA}})
    prod, res, ev = _probar(base, "juego2")
    assert res["fases"]["importa"]["ok"] is True, res["fases"]["importa"]["detalle"]
    assert res["fases"]["arranca"]["ok"] is True
    assert res["fallo_duro"] is None
    assert ev["desglose"]["arranca"] == 3.0


def test_bucle_infinito_cuenta_como_arranco(tmp_path):
    base = _armar_biblioteca(tmp_path, {"loop": {"program.py": BUCLE}})
    prod = _uno(base, "loop")
    res = probar_producto(prod, timeout_arranque=2, timeout_import=2)
    assert res["fases"]["arranca"]["timeout"] is True
    assert res["fases"]["arranca"]["ok"] is True
    assert res["fallo_duro"] is None


def test_syntax_error_en_runtime_sin_traceback(tmp_path):
    # Un SyntaxError del script principal NO imprime "Traceback": si solo
    # buscaramos esa palabra, este producto pasaria como verde.
    base = _armar_biblioteca(tmp_path, {"sx": {"main.py": NO_COMPILA}})
    prod = _uno(base, "sx")
    salida = probar_producto(prod, timeout_arranque=4, timeout_import=4)
    assert "Traceback" not in (salida["fases"]["compila"].get("errores") or [""])[0]
    assert salida["fallo_duro"] == "compila"


# ── Reporte agregado ───────────────────────────────────────────────────────────

def test_probar_todos_agrega_y_ordena(tmp_path):
    base = _armar_biblioteca(
        tmp_path,
        {"bueno":    {"program.py": BUENO,
                      "README.md": "Contador de palabras: corre y muestra el conteo del texto."},
         "roto":     {"program.py": NO_COMPILA},
         "revienta": {"program.py": REVIENTA}},
        index=[{"id": "bueno", "directory": "bueno", "title": "Contador",
                "description": "Un contador de palabras sobre un texto de ejemplo."}])
    rep = probar_todos(base=base, timeout_arranque=4)

    assert rep["total"] == 3
    assert rep["compilan"] == 2      # roto no compila
    assert rep["arrancan"] == 1      # solo el bueno
    assert rep["top"]["id"] == "bueno" and rep["top"]["puntaje"] == 10.0
    assert rep["peor"]["id"] == "roto"
    assert 0 < rep["puntaje_medio"] < 10
    assert "compila" in rep["peor"]["motivo"]


def test_limite_y_filtro(tmp_path):
    base = _armar_biblioteca(tmp_path, {"uno": {"program.py": BUENO},
                                        "dos": {"program.py": BUENO},
                                        "tres": {"program.py": BUENO}})
    assert probar_todos(base=base, limite=2)["total"] == 2
    rep = probar_todos(base=base, filtro="tre")
    assert rep["total"] == 1 and rep["evaluaciones"][0]["id"] == "tres"


def test_solo_codigo_saltea_carpetas_de_assets(tmp_path):
    base = _armar_biblioteca(tmp_path, {"con": {"program.py": BUENO}, "sin": {}})
    (base / "sin" / "input_images").mkdir()
    assert probar_todos(base=base)["total"] == 2
    rep = probar_todos(base=base, solo_codigo=True)
    assert rep["total"] == 1 and rep["sin_codigo"] == 0


def test_slash_autoprueba_parsea_args_e_imprime(tmp_path, capsys):
    # Es el cuerpo listo para engancharse a /autoprueba en cli.py (cli.py no se toca).
    base = _armar_biblioteca(tmp_path, {"uno": {"program.py": BUENO},
                                        "dos": {"program.py": STUB}})
    rep = slash_autoprueba("1", base=base)
    salida = capsys.readouterr().out
    assert rep["total"] == 1 and "limite 1" in salida and "/10" in salida

    rep2 = slash_autoprueba("dos", base=base)
    assert rep2["total"] == 1 and rep2["evaluaciones"][0]["id"] == "dos"


def test_biblioteca_inexistente_no_explota(tmp_path):
    assert descubrir_productos(tmp_path / "no_existe") == []
    assert probar_todos(base=tmp_path / "no_existe")["total"] == 0


# ── Contrato GENERICO de una pagina + gate de pixeles ─────────────────────────
#
# Estos SI abren un navegador de verdad (Playwright/chromium) y pilotan la
# pagina: cuentan controles, los clican, pulsan teclas y comparan PIXELES entre
# capturas. Son la unica forma de distinguir "el HTML es valido" de "la pagina
# hace algo". El contrato es GENERICO a proposito: la memoria de esta casa mide
# que el contrato "por idea" esta al nivel del azar y reprueba el 88-94% de las
# paginas SANAS, asi que aqui hay dos casos SANOS por cada caso roto.

pytest.importorskip("playwright.sync_api", reason="el contrato generico necesita Playwright")

from cognia.autoprueba import _contrato_web, parece_juego   # noqa: E402

_ESTILO = ("body{background:#102030;color:#eee;font-family:sans-serif;margin:0;padding:20px}"
           ".b{width:60px;height:30px;background:#4af;margin:8px}")

PAGINA_VIVA = f"""<!DOCTYPE html><html><head><title>Contador</title><style>{_ESTILO}</style></head>
<body><h1>Contador de clics</h1><div class="b"></div>
<button onclick="document.getElementById('n').textContent=+document.getElementById('n').textContent+1">mas</button>
<span id="n">0</span>
<p>una pagina normal, con texto suficiente para que el lienzo no sea uniforme.</p>
</body></html>"""

PAGINA_MUERTA = f"""<!DOCTYPE html><html><head><title>Panel</title><style>{_ESTILO}</style></head>
<body><h1>Panel</h1>
<button>uno</button><button>dos</button><button>tres</button>
<p>solo texto: ningun boton hace nada y la pagina no se anima sola.</p>
<p>segunda linea para que el lienzo tenga variacion de luminancia.</p>
</body></html>"""

PAGINA_NEGRA = """<!DOCTYPE html><html><head><title>Negra</title>
<style>html,body{background:#000;margin:0;height:100%}button{opacity:0}</style></head>
<body><button onclick="void 0">x</button></body></html>"""

_JUEGO = """<!DOCTYPE html><html><head><title>Juego</title>
<style>body{{margin:0;background:#111}}canvas{{display:block}}</style></head>
<body><canvas id="c" width="1000" height="700"></canvas><script>
var ctx=document.getElementById('c').getContext('2d'); var x=0, boost=0;
{escucha}
function loop(){{ x=(x+{paso}+boost)%900; if(boost>0){{boost=Math.max(0,boost-2);}}
 ctx.fillStyle='#111'; ctx.fillRect(0,0,1000,700);
 ctx.fillStyle='#0f0'; ctx.fillRect(x,300,140,140); requestAnimationFrame(loop);}} loop();
</script></body></html>"""

JUEGO_SORDO = _JUEGO.format(escucha="", paso=11)
JUEGO_VIVO = _JUEGO.format(
    escucha="document.addEventListener('keydown', function(e){ boost=340; });", paso=2)


def _prod_html(tmp_path, nombre, html):
    d = tmp_path / nombre
    d.mkdir()
    (d / "index.html").write_text(html, encoding="utf-8")
    return {"id": nombre, "title": nombre.replace("_", " "), "description": "",
            "directorio": str(d), "entrypoint": str(d / "index.html"),
            "lenguaje": "html", "archivos_py": []}


def test_contrato_aprueba_una_pagina_SANA(tmp_path):
    """Caso sano: un boton que cambia el DOM basta. No se exige nada mas."""
    prod = _prod_html(tmp_path, "viva", PAGINA_VIVA)
    r = _contrato_web(prod, PAGINA_VIVA)
    assert r["corrio"] is True, r["detalle"]
    assert r["ok"] is True, r["detalle"]
    assert r["clicables"] >= 1 and r["clics"] >= 1
    assert r["cambio_dom"] is True
    assert r["pixeles_ok"] is True


def test_contrato_reprueba_una_pagina_con_TODOS_los_controles_muertos(tmp_path):
    """Tres botones, tres clics, y el innerHTML del body no se mueve un byte."""
    prod = _prod_html(tmp_path, "muerta", PAGINA_MUERTA)
    r = _contrato_web(prod, PAGINA_MUERTA)
    assert r["corrio"] is True and r["ok"] is False
    assert r["clicables"] == 3 and r["clics"] == 3
    assert r["cambio_dom"] is False and r["anima_sola"] is False
    assert "NINGUNO hace nada" in r["detalle"]


def test_gate_de_pixeles_rechaza_la_pagina_en_negro(tmp_path):
    """Un frame negro no se puntua: se rechaza con motivo (regla de frames_gate)."""
    prod = _prod_html(tmp_path, "negra", PAGINA_NEGRA)
    r = _contrato_web(prod, PAGINA_NEGRA)
    assert r["corrio"] is True and r["ok"] is False
    assert r["pixeles_ok"] is False
    assert "GATE DE PIXELES" in r["detalle"]
    assert "NEGRO" in r["detalle"] or "UNIFORME" in r["detalle"]


def test_juego_que_se_mueve_igual_sin_tocar_nada_NO_responde(tmp_path):
    """El patron BASE vs ACTIVO de AGF, con su margen 1.15."""
    prod = _prod_html(tmp_path, "juego_sordo", JUEGO_SORDO)
    assert parece_juego(prod, JUEGO_SORDO) is True
    r = _contrato_web(prod, JUEGO_SORDO)
    assert r["corrio"] is True and r["ok"] is False, r["detalle"]
    assert r["anima_sola"] is True
    assert r["responde_input"] is False
    assert r["actividad_activo"] <= r["actividad_base"] * 1.15
    assert "NO RESPONDE AL INPUT" in r["detalle"]


def test_el_mismo_juego_escuchando_el_teclado_SI_pasa(tmp_path):
    """El contrafactual: identico salvo el addEventListener('keydown')."""
    prod = _prod_html(tmp_path, "juego_vivo", JUEGO_VIVO)
    r = _contrato_web(prod, JUEGO_VIVO)
    assert r["corrio"] is True and r["ok"] is True, r["detalle"]
    assert r["anima_sola"] is True and r["responde_input"] is True
    assert r["actividad_activo"] > r["actividad_base"] * 1.15


DASHBOARD_ANIMADO = """<!DOCTYPE html><html><head><title>Simulacion de inversiones</title>
<style>body{margin:0;background:#0b1220;color:#dfe}
.barra{height:24px;background:#3c9;margin:6px;animation:mover 1.4s infinite alternate}
@keyframes mover{from{width:40px}to{width:820px}}</style></head>
<body><h1>Cartera en vivo</h1>
<div class="barra"></div><div class="barra"></div><div class="barra"></div>
<p>panel que se refresca solo; no tiene controles ni escucha el teclado.</p>
</body></html>"""


def test_un_DASHBOARD_animado_sin_controles_NO_es_un_juego_sordo(tmp_path):
    """
    FALSO ROJO MEDIDO (2026-08-29). Con el gate de juego aplicado a todo lo que
    "parece juego por codigo", investment_dashboard_simulation_01 y _02 —dos
    dashboards reales de la biblioteca— reprobaban por 0,0497 contra 0,0507: un
    2%, dentro del ruido de un diff de pixeles. Una pagina que se anima sola y
    no tiene NI un control NI un addEventListener no ignora la entrada: no tiene
    por donde oirla. Tras este guardarrail: 0 de 34 paginas reales reprobadas.
    """
    prod = _prod_html(tmp_path, "simulacion_de_inversiones", DASHBOARD_ANIMADO)
    r = _contrato_web(prod, DASHBOARD_ANIMADO)
    assert r["corrio"] is True
    assert r["gate_juego"]["aplica"] is False, r["gate_juego"]["motivo"]
    assert r["anima_sola"] is True and r["clicables"] == 0
    assert r["ok"] is True, r["detalle"]


def test_el_contrato_se_puede_apagar_y_lo_DICE(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_CONTRATO_WEB", "0")
    prod = _prod_html(tmp_path, "viva", PAGINA_VIVA)
    r = _contrato_web(prod, PAGINA_VIVA)
    assert r["corrio"] is False and r["ok"] is True
    assert "desactivado" in r["detalle"]
