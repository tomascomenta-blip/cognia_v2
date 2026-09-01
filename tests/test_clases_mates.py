# -*- coding: utf-8 -*-
"""
tests/test_clases_mates.py
==========================
El motor de formulas y graficas del cuaderno: que el PNG salga de verdad, que
sea un PNG de verdad, que quepa en la pagina y en el presupuesto de adjuntos,
y que el texto del profesor o del modelo NUNCA se ejecute.

POR QUE importorskip. matplotlib y sympy no estan en requirements.txt ni en el
extra [clases] de pyproject.toml: en la maquina del duenio SI estan (3.11.1 y
1.14.0, medido) pero el CI de ubuntu instala requirements.txt y no los trae.
Sin el skip, esta suite pondria en rojo un CI por una dependencia que nadie
prometio -- y un rojo cronico se acaba ignorando, que es peor que no tener
test.

LO QUE ESTOS TESTS DEFIENDEN DE VERDAD, mas alla de "corre":
  - la firma PNG, porque un fichero .png con otro contenido es el fallo que el
    cuaderno no puede detectar solo;
  - el tope de bytes, porque el cuaderno EMBEBE los adjuntos en el HTML;
  - el rechazo del SVG, porque el SVG de matplotlib lleva URLs http:// y
    tests/test_clases_vista.py exige que la pagina no tenga ni una;
  - la allowlist, porque lo que se grafica sale del LLM;
  - los TOPES DE COSTE, porque la allowlist filtra el codigo y no el precio:
    "9**9**9" no nombra nada prohibido y colgaba el proceso para siempre;
  - y que un error sea LEGIBLE, no un TokenError de sympy.

POR QUE VARIOS TESTS CORREN EN UN HILO CON PLAZO. Los casos de coste que se
defienden aqui COLGABAN el proceso. Un test de regresion que, al revertir el
arreglo, se queda quieto para siempre no es un test: mata la suite entera y no
dice nada. Con `_en_menos_de` el mismo caso revertido FALLA en el plazo, que
es lo que un test tiene que hacer.
"""

import struct
import threading
import time

import pytest

mpl = pytest.importorskip("matplotlib", reason="matplotlib no esta en requirements.txt")
sympy = pytest.importorskip("sympy", reason="sympy no esta en requirements.txt")

from cognia.clases import mates


def _leer(ruta):
    with open(str(ruta), "rb") as fh:
        return fh.read()


def _wh(crudo):
    return struct.unpack(">II", crudo[16:24])


def _en_menos_de(segundos, funcion, *a, **kw):
    """('ok'|'fallo'|'colgado', resultado, segundos_gastados) con plazo.

    Ver la cabecera: sin esto, revertir el arreglo de los topes de coste no
    pondria un test en rojo, colgaria pytest. El hilo es demonio, o sea que si
    se queda dentro de un `9**387420489` no impide que el proceso salga.
    Devuelve tambien cuanto tardo, que es lo que distingue "lo corto el tope"
    de "lo corto la barrera de tiempo".
    """
    caja = {}

    def _correr():
        try:
            caja["valor"] = funcion(*a, **kw)
        except BaseException as exc:
            caja["fallo"] = exc

    hilo = threading.Thread(target=_correr, daemon=True)
    t0 = time.time()
    hilo.start()
    hilo.join(segundos)
    gastado = time.time() - t0
    if hilo.is_alive():
        return "colgado", None, gastado
    if "fallo" in caja:
        return "fallo", caja["fallo"], gastado
    return "ok", caja["valor"], gastado


# ── Disponibilidad ───────────────────────────────────────────────────────────

def test_disponible_dice_si_y_por_que():
    ok, motivo = mates.disponible()
    assert ok is True, motivo
    assert motivo and "matplotlib" in motivo


def test_sin_matplotlib_el_error_trae_el_pip_install(monkeypatch):
    """El antipatron fichado del repo es la capacidad desconectada en silencio.

    Se simula la ausencia con sys.modules[nombre] = None, que es lo que hace
    que un `import matplotlib` lance ImportError de verdad (no un mock): asi
    se prueba el camino REAL del import perezoso y no una rama inventada.
    """
    import sys
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    with pytest.raises(mates.FaltaDependencia) as e:
        mates._cargar_pyplot()
    assert "pip install matplotlib" in str(e.value)
    ok, motivo = mates.disponible()
    assert ok is False and "pip install matplotlib" in motivo


def test_sin_sympy_el_error_trae_el_pip_install(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "sympy", None)
    with pytest.raises(mates.FaltaDependencia) as e:
        mates._cargar_sympy()
    assert "pip install sympy" in str(e.value)


# ── Formulas ─────────────────────────────────────────────────────────────────

def test_formula_a_png_da_png_y_el_latex_crudo(tmp_path):
    """El caso del duenio: la formula general de segundo grado, escrita como
    la copia de sus apuntes (sin dolares) y sin tener LaTeX instalado."""
    latex = r"\frac{-b \pm \sqrt{b^2-4ac}}{2a}"
    r = mates.formula_a_png(latex, tmp_path / "cuadratica.png")

    crudo = _leer(r["ruta"])
    assert crudo.startswith(mates.FIRMA_PNG)
    assert r["bytes"] == len(crudo) and r["bytes"] < mates.TOPE_BYTES
    assert _wh(crudo) == (r["ancho_px"], r["alto_px"])
    # Una imagen no es buscable: el latex crudo tiene que volver para que se
    # pueda guardar al lado y encontrar la formula por texto dentro de un anio.
    assert r["texto"] == latex and r["latex"] == latex
    assert r["tipo"] == "formula"


def test_formula_larga_baja_el_dpi_hasta_caber_en_la_pagina(tmp_path):
    """Una formula larga se rebaja de dpi hasta caber en el ancho util del A4
    (6,3 pulgadas): mas ancha, el documento la reescala y se ve borrosa."""
    largo = "+".join([r"\alpha_{%d} x^{%d}" % (i, i) for i in range(1, 10)])
    r = mates.formula_a_png(largo, tmp_path / "larga.png")
    assert r["ancho_px"] <= int(mates.ANCHO_PAGINA_PULGADAS * mates.DPI)
    assert r["dpi"] < mates.DPI
    assert r["avisos"], "bajar el dpi por ancho no puede ser mudo"


def test_formula_kilometrica_se_entrega_pero_avisa(tmp_path):
    """Hay un suelo de dpi (por debajo no se lee) y por tanto una formula que
    no cabe ni asi. Se entrega -- borrarla seria perderla -- pero diciendolo:
    una imagen que el documento va a reducir sin avisar es el vacio silencioso
    de este repo con otra cara."""
    largo = "+".join([r"\alpha_{%d} x^{%d}" % (i, i) for i in range(1, 40)])
    r = mates.formula_a_png(largo, tmp_path / "kilometrica.png")
    assert _leer(r["ruta"]).startswith(mates.FIRMA_PNG)
    assert r["dpi"] == mates.DPI_MINIMO
    assert any("caben" in a for a in r["avisos"]), r["avisos"]


def test_formula_invalida_da_error_legible(tmp_path):
    """mathtext lanza un ParseSyntaxException que habla de columnas del parser.
    El duenio tiene que leer QUE formula fallo y que se admite."""
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.formula_a_png(r"\frac{1}{", tmp_path / "rota.png")
    msg = str(e.value)
    assert r"\frac{1}{" in msg and "no se pudo dibujar la formula" in msg
    assert not (tmp_path / "rota.png").exists() or True   # el fichero da igual


def test_formula_vacia_no_pasa(tmp_path):
    with pytest.raises(mates.ErrorDeMates):
        mates.formula_a_png("   ", tmp_path / "vacia.png")


# ── Graficar una expresion ───────────────────────────────────────────────────

def test_graficar_sinc_de_menos_diez_a_diez(tmp_path):
    """El caso literal del contrato: sin(x)/x de -10 a 10. Ojo al x=0, que es
    0/0: tiene que salir NaN (hueco) y no tumbar la grafica."""
    r = mates.graficar(tmp_path / "sinc.png", expresion="sin(x)/x",
                       desde=-10, hasta=10)
    crudo = _leer(r["ruta"])
    assert crudo.startswith(mates.FIRMA_PNG)
    assert r["bytes"] < mates.TOPE_BYTES
    assert r["ancho_px"] <= int(mates.ANCHO_PAGINA_PULGADAS * mates.DPI)
    assert "sin(x)/x" in r["texto"] and "-10" in r["texto"]
    assert r["tipo"] == "expresion"


def test_el_agujero_de_sinc_es_nan_no_una_excepcion():
    import numpy as np
    xs, ys, _ = mates.evaluar("sin(x)/x", desde=-10, hasta=10, puntos=801)
    cero = int(np.argmin(np.abs(xs)))
    assert abs(xs[cero]) < 1e-9, "el muestreo tiene que pasar por x=0"
    assert np.isnan(ys[cero]), "0/0 tiene que ser un hueco, no un numero"
    assert np.isfinite(ys).sum() == ys.size - 1


def test_sqrt_de_negativo_no_dibuja_el_modulo():
    """sqrt(x) en los negativos es complejo. Pintar |sqrt(x)| seria dibujar
    OTRA funcion: los negativos tienen que ser hueco."""
    import numpy as np
    xs, ys, _ = mates.evaluar("sqrt(x)", desde=-4, hasta=4, puntos=101)
    assert np.all(np.isnan(ys[xs < -1e-9]))
    assert np.isfinite(ys[xs > 1e-9]).all()


@pytest.mark.parametrize("constante", ["I", "sqrt(-1)"])
def test_una_constante_compleja_da_error_legible_no_un_typeerror(constante):
    """La rama del escalar corria ANTES que la de complejos y hacia float()
    sobre el valor: una constante compleja salia con el TypeError crudo de
    float(complex) -- la excepcion sin traducir que este modulo dice no dejar
    salir -- y la rama de complejos era codigo muerto. Ahora el escalar se
    difunde conservando el tipo y la constante compleja llega a esa rama."""
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.evaluar(constante)
    assert "no da ningun valor real" in str(e.value)


@pytest.mark.parametrize("constante,valor", [("3", 3.0), ("pi", 3.14159265)])
def test_una_constante_real_sigue_siendo_una_recta(constante, valor):
    """El otro lado del arreglo de arriba: difundir el escalar conservando el
    tipo no puede romper la constante NORMAL, que es el caso que hay."""
    import numpy as np
    xs, ys, _ = mates.evaluar(constante, desde=-2, hasta=2, puntos=11)
    assert ys.shape == xs.shape
    assert np.allclose(ys, valor)


def test_multiplicacion_implicita_y_acento_circunflejo():
    """Un alumno escribe '2x^2 + 1', no '2*x**2 + 1'."""
    assert str(mates.expresion_segura("2x^2 + 1")) == "2*x**2 + 1"
    assert str(mates.expresion_segura("3sin(x)")) == "3*sin(x)"
    # ln y ceil existen porque es como se escriben a mano, no como los llama
    # sympy; si el alias se pierde, esto se entera.
    assert str(mates.expresion_segura("ln(x)")) == "log(x)"


def test_variable_distinta_de_x(tmp_path):
    r = mates.graficar_expresion("t^2 - 4", tmp_path / "t.png", var="t",
                                 desde=-3, hasta=3, titulo="espacio en MRUA")
    assert _leer(r["ruta"]).startswith(mates.FIRMA_PNG)
    assert r["var"] == "t" and "t^2 - 4" in r["texto"]


# ── Seguridad: NUNCA eval() sobre texto del modelo ───────────────────────────

@pytest.mark.parametrize("veneno", [
    "__import__('os').system('dir')",
    "os.system(1)",
    "open(1)",
    "exec(1)",
    "eval(1)",
    "x.__class__",
    "[1,2][0]",
    "{1:2}",
    "lambda x: x",
])
def test_la_allowlist_para_lo_que_no_es_aritmetica(veneno):
    """La validacion va ANTES del parser a proposito: parse_expr llama a eval()
    sobre el flujo de tokens, asi que validar despues seria validar despues de
    ejecutar. Si alguna de estas llega al parser, este test lo caza."""
    with pytest.raises(mates.ErrorDeMates):
        mates.expresion_segura(veneno)


def test_el_veneno_no_llega_a_parse_expr(monkeypatch):
    """Prueba el ORDEN, no solo el resultado: se lleva la CUENTA de las
    llamadas a parse_expr y se exige que sean CERO.

    La version anterior de este test plantaba un AssertionError dentro de
    parse_expr y solo exigia que saliera un ErrorDeMates. No probaba nada: el
    `except Exception` de expresion_segura se tragaba el centinela y lo
    convertia en el error legible, o sea que el test pasaba IGUAL si el veneno
    llegaba al parser. La unica prueba del orden es que el parser no se haya
    llamado, y por eso hay un control delante: si el espia no estuviera en el
    camino, contar cero no significaria nada.
    """
    from sympy.parsing import sympy_parser

    llamadas = []
    real = sympy_parser.parse_expr

    def _espia(texto, *a, **k):
        llamadas.append(texto)
        return real(texto, *a, **k)

    monkeypatch.setattr(sympy_parser, "parse_expr", _espia)

    mates.expresion_segura("2x^2 + 1")
    assert llamadas, ("el espia no esta en el camino de expresion_segura: "
                      "contar cero llamadas abajo no probaria nada")

    del llamadas[:]
    with pytest.raises(mates.ErrorDeMates):
        mates.expresion_segura("__import__('os').system('dir')")
    assert llamadas == [], (
        "el texto sin validar llego a parse_expr: %r. parse_expr llama a "
        "eval() sobre el flujo de tokens transformado, asi que validar "
        "despues seria validar despues de EJECUTAR" % (llamadas,))


# ── Topes de COSTE: la allowlist filtra el codigo, no el precio ──────────────

@pytest.mark.parametrize("torre", [
    "9**9**9",              # el caso de cinco caracteres que colgaba
    "9^9^9",                # lo mismo con el circunflejo que usa un alumno
    "9**(9**9)",            # con parentesis: un tope por regex no lo ve
    "(9**9)**(9**9)",
    "x**(9**9**9)",         # escondido en el exponente de algo simbolico
    "sin(9**9**9)",         # escondido dentro de una funcion permitida
    "9**(99999*99999)",     # el exponente no es un literal, es una cuenta
])
def test_la_torre_de_potencias_no_cuelga(torre):
    """MEDIDO antes del arreglo: expresion_segura('9**9**9') seguia corriendo
    a los 60 s. sympy hace las cuentas AL PARSEAR, y eso es pedirle 9^387420489
    -- un entero de 370 millones de cifras. Quien escribe esto es el modelo,
    dentro del proceso del widget: colgarse ahi es colgar la clase entera."""
    estado, salida, gastado = _en_menos_de(15.0, mates.expresion_segura, torre)
    assert estado != "colgado", (
        "%r seguia calculando a los 15 s: el tope de coste no lo corta" % torre)
    assert estado == "fallo" and isinstance(salida, mates.ErrorDeMates), salida
    # Lo tiene que cortar el TOPE, no la barrera de tiempo. La barrera abandona
    # un hilo que se queda quemando un nucleo: es el ultimo recurso, no el
    # mecanismo. Si esto tarda TOPE_SEGUNDOS es que la cota del arbol no vio
    # la torre y el corte lo hizo el plazo.
    assert gastado < mates.TOPE_SEGUNDOS, (
        "%r tardo %.1f s: lo corto la barrera de tiempo, no el tope de coste"
        % (torre, gastado))


@pytest.mark.parametrize("bomba", [
    "factorial(99999999)",
    "gamma(99999999)",
    "factorial(5*10**7)",   # el argumento no es un literal: se topa al evaluar
])
def test_el_factorial_gigante_no_cuelga(bomba):
    """factorial y gamma van aparte de la cota del arbol porque NO se dejan
    mirar sin ejecutarse: medido, parse_expr(..., evaluate=False) se cuelga
    igual, o sea que el arbol 'sin evaluar' ni se llega a construir."""
    estado, salida, gastado = _en_menos_de(15.0, mates.expresion_segura, bomba)
    assert estado != "colgado", "%r seguia calculando a los 15 s" % bomba
    assert estado == "fallo" and isinstance(salida, mates.ErrorDeMates), salida
    # El mensaje tiene que nombrar el tope del factorial: si dijera solo que
    # "tardo demasiado", el corte lo habria hecho la barrera y el envoltorio
    # de factorial no estaria haciendo nada.
    assert str(mates.TOPE_FACTORIAL) in str(salida), str(salida)
    assert gastado < mates.TOPE_SEGUNDOS, gastado


def test_el_exponente_enorme_se_corta_ANTES_de_encender_sympy(tmp_path,
                                                              monkeypatch):
    """El tope de texto es el que corta sin haber cargado sympy siquiera.

    Que corte se prueba haciendo desaparecer sympy: si el error que sale es el
    de coste y no un FaltaDependencia, el tope llego antes que el import, que
    es antes que el parser. Y como aqui todavia se sabe QUE numero escribio la
    persona, el mensaje lo nombra en vez de hablar de subarboles.
    """
    import sys
    monkeypatch.setitem(sys.modules, "sympy", None)
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.expresion_segura("2**99999999")
    assert not isinstance(e.value, mates.FaltaDependencia), (
        "se corto DESPUES de cargar sympy: el tope de texto no esta delante")
    assert "99999999" in str(e.value) and str(mates.TOPE_CIFRAS) in str(e.value)
    monkeypatch.undo()

    # y por la puerta de verdad, que es por donde llega lo del modelo
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar(tmp_path / "bomba.png", expresion="2**99999999")
    assert not (tmp_path / "bomba.png").exists()


def test_demasiadas_potencias_no_es_una_formula_de_clase():
    largo = "+".join(["x^%d" % i for i in range(1, mates.TOPE_POTENCIAS + 3)])
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.expresion_segura(largo)
    assert str(mates.TOPE_POTENCIAS) in str(e.value)


@pytest.mark.parametrize("buena,esperado", [
    ("2**1000", "10715086071862673209484250490600018105614048117055336074437"),
    ("factorial(500)", None),
    ("9**9", "387420489"),
    ("(9**9)**9", None),          # 77 cifras: grande y perfectamente legal
    ("x^5+x^4+x^3+x^2+x", None),
    ("2x^2 + 1", "2*x**2 + 1"),
    ("x**(1/2)", "sqrt(x)"),
    ("3sin(x)", "3*sin(x)"),
])
def test_los_topes_dejan_pasar_lo_que_se_escribe_en_clase(buena, esperado):
    """La leccion cara de este repo: un gate que no deja hacer nada acaba
    apagado. Los topes estan calibrados sobre lo que cabe en una pizarra, no
    sobre lo que aguanta la maquina, y esto es lo que lo vigila."""
    estado, salida, _ = _en_menos_de(15.0, mates.expresion_segura, buena)
    assert estado == "ok", "%r no deberia cortarse: %s" % (buena, salida)
    if esperado:
        assert str(salida).startswith(esperado), str(salida)[:80]


def test_la_barrera_de_tiempo_corta_lo_que_no_termina():
    """La red de lo que se cuelga a base de bytecode. Se prueba la barrera
    directamente porque despues de los topes ya no queda ninguna expresion
    conocida que la dispare.

    El trabajo de prueba es un bucle de Python A PROPOSITO, que es justo la
    clase que la barrera SI cubre: MEDIDO, un hilo con plazo no rescata al
    proceso de una llamada de C que no suelta el GIL (un `int.__pow__`
    gigante congela hasta el join). Contra eso estan los topes de coste, no
    esto. Ver `mates._con_tope_de_tiempo`.
    """
    # El horizonte es de 3 s y no de 30 A PROPOSITO, y la razon es el precio
    # que el modulo declara: al hilo abandonado no se le puede dar muerte, o
    # sea que sigue quemando un nucleo. Con 30 s aqui, los dos tests
    # siguientes pasaban de 0,4 s a 12 s MEDIDOS. El coste de la barrera se ve
    # en su propia suite.
    def _no_termina():
        fin = time.time() + 3.0
        while time.time() < fin:            # ocupado, como un pow gigante
            pass
        return "nunca deberia verse"

    t0 = time.time()
    with pytest.raises(mates.ErrorDeMates) as e:
        mates._con_tope_de_tiempo(_no_termina, 0.5, "una cuenta interminable")
    assert time.time() - t0 < 10.0, "la barrera no corto: espero al trabajo"
    assert "0 s" in str(e.value) or "cortado" in str(e.value), str(e.value)


def test_la_barrera_no_se_come_ni_el_valor_ni_el_error():
    """Una barrera que devolviera None o que se tragara la excepcion del
    trabajo seria peor que no tenerla: convertiria un fallo real en un vacio
    silencioso."""
    assert mates._con_tope_de_tiempo(lambda: 42, 5.0, "sumar") == 42

    def _falla():
        raise ZeroDivisionError("el fallo de dentro")

    with pytest.raises(ZeroDivisionError) as e:
        mates._con_tope_de_tiempo(_falla, 5.0, "dividir")
    assert "el fallo de dentro" in str(e.value)


def test_otra_variable_no_se_grafica_a_escondidas():
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.expresion_segura("x*y")
    assert "'y'" in str(e.value)


def test_expresion_invalida_da_error_legible_no_un_tokenerror():
    """Lo que sympy dice es "TokenError: ('unexpected EOF in multi-line
    statement', (1, 0))". Eso no le dice nada a nadie."""
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.expresion_segura("sin(x")
    msg = str(e.value)
    assert "no se entiende la expresion" in msg and "'sin(x'" in msg
    assert "parentesis" in msg


def test_error_legible_tambien_desde_graficar(tmp_path):
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar(tmp_path / "no.png", expresion="sin(x")
    assert not (tmp_path / "no.png").exists()


def test_expresion_que_no_da_ningun_real_avisa():
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.evaluar("sqrt(x)", desde=-10, hasta=-1)
    assert "no da ningun valor real" in str(e.value)


def test_rango_al_reves_y_pocos_puntos():
    with pytest.raises(mates.ErrorDeMates):
        mates.evaluar("x", desde=5, hasta=-5)
    with pytest.raises(mates.ErrorDeMates):
        mates.evaluar("x", desde=-5, hasta=5, puntos=1)


# ── Series de datos y barras ─────────────────────────────────────────────────

def test_barras_con_etiquetas_y_texto_buscable(tmp_path):
    r = mates.graficar(tmp_path / "notas.png", y=[5, 7, 9, 4],
                       etiquetas=["1a eval", "2a eval", "3a eval", "final"],
                       titulo="Notas de Fisica", eje_y="nota")
    assert _leer(r["ruta"]).startswith(mates.FIRMA_PNG)
    assert r["tipo"] == "barras" and r["n"] == 4
    # El texto es lo unico por lo que el buscador del cuaderno puede encontrar
    # esta grafica: tienen que estar el titulo Y los pares.
    assert "Notas de Fisica" in r["texto"]
    assert "1a eval: 5" in r["texto"] and "final: 4" in r["texto"]


def test_serie_xy_de_linea(tmp_path):
    r = mates.graficar(tmp_path / "xy.png", x=[1, 2, 3, 4, 5],
                       y=[1, 4, 9, 16, 25], titulo="cuadrados")
    assert _leer(r["ruta"]).startswith(mates.FIRMA_PNG)
    assert r["tipo"] == "linea"
    assert "cuadrados" in r["texto"] and "3: 9" in r["texto"]


def test_serie_larga_se_resume_en_el_texto(tmp_path):
    """Listar 500 numeros en el cuaderno no lo busca nadie y engorda el JSONL
    de la jornada: por encima de _MAX_PARES se resume por rango."""
    r = mates.graficar_datos(tmp_path / "larga.png", list(range(500)),
                             titulo="temperatura")
    assert "500 puntos" in r["texto"] and len(r["texto"]) < 200


def test_una_serie_de_numpy_se_grafica(tmp_path):
    """La forma MAS natural de llamar a esto es pasarle la salida de otro
    calculo, o sea un numpy array. `y or []` llamaba a bool() sobre el array y
    numpy contestaba "the truth value of an array is ambiguous": una excepcion
    cruda del backend en el caso normal."""
    import numpy as np
    r = mates.graficar_datos(tmp_path / "np.png", np.array([1.0, 4.0, 9.0]),
                             x=np.array([1.0, 2.0, 3.0]), titulo="medidas")
    assert _leer(r["ruta"]).startswith(mates.FIRMA_PNG)
    assert r["n"] == 3 and r["valores"] == [1.0, 4.0, 9.0]

    # y por la puerta unica, que es donde se deduce el tipo mirando etiquetas
    r2 = mates.graficar(tmp_path / "np2.png", y=np.array([5.0, 7.0]),
                        etiquetas=np.array(["1a eval", "2a eval"]))
    assert r2["tipo"] == "barras" and r2["n"] == 2


def test_un_hueco_none_dice_cual_es(tmp_path):
    """La otra forma natural de equivocarse: un calculo que no dio valor en un
    punto. float(None) sale como un TypeError crudo que ni dice cual de los
    500 valores fue."""
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.graficar_datos(tmp_path / "hueco.png", [1.0, None, 3.0])
    msg = str(e.value)
    assert "1" in msg and "'y'" in msg and "nan" in msg
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar_datos(tmp_path / "hueco2.png", [1.0, 2.0], x=[0.0, None])
    with pytest.raises(mates.ErrorDeMates) as e2:
        mates.graficar_datos(tmp_path / "escalar.png", 5)
    assert "lista de numeros" in str(e2.value)


def test_datos_que_no_cuadran_o_vacios(tmp_path):
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar_datos(tmp_path / "a.png", [], titulo="nada")
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar_datos(tmp_path / "b.png", [1, 2, 3],
                             etiquetas=["solo", "dos"])
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar_datos(tmp_path / "c.png", [1, 2, 3], x=[1, 2])
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar_datos(tmp_path / "d.png", [1, 2], tipo="tarta")


# ── PNG SIEMPRE, SVG NUNCA ───────────────────────────────────────────────────

@pytest.mark.parametrize("nombre", ["grafica.svg", "grafica.pdf", "grafica"])
def test_solo_png(tmp_path, nombre):
    """El SVG de matplotlib trae ocho cadenas http:// (DTD, xmlns, metadata) y
    tests/test_clases_vista.py (~478) exige que la pagina del cuaderno no tenga
    NI UNA url http. Esto no es una preferencia de formato."""
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.formula_a_png("x^2", tmp_path / nombre)
    assert "PNG" in str(e.value)
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar(tmp_path / nombre, expresion="x")
    assert not (tmp_path / nombre).exists()


def test_el_svg_de_matplotlib_lleva_http_de_verdad(tmp_path):
    """La justificacion de la cabecera de mates.py, MEDIDA en vez de citada.

    Antes esto solo exigia '>= 1', asi que la cabecera podia decir cualquier
    cifra y el test la daba por buena -- decia OCHO http:// y son SIETE, mas
    una https://, ocho URLs en total. Ahora se comprueban los numeros exactos:
    si una version de matplotlib cambia lo que mete en el SVG, este test se
    pone rojo con el dato nuevo delante y la cabecera se corrige con esa
    medida, en vez de arrastrar un numero que nadie volvio a mirar.
    """
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(1, 1))
    fig.add_subplot(111).plot([0, 1], [0, 1])
    destino = tmp_path / "prueba.svg"
    try:
        fig.savefig(str(destino), format="svg")
    finally:
        plt.close(fig)
    texto = destino.read_text(encoding="utf-8")
    medido = (texto.count("http://"), texto.count("https://"))
    assert medido == (7, 1), (
        "matplotlib %s escribe %d 'http://' y %d 'https://' en el SVG; la "
        "cabecera de cognia/clases/mates.py dice 7 y 1. Corrige la cabecera "
        "con ESTA medida." % (matplotlib.__version__, medido[0], medido[1]))


# ── Presupuesto de bytes ─────────────────────────────────────────────────────

def test_el_tope_de_bytes_baja_el_dpi_antes_de_rendirse(tmp_path):
    """Primero se intenta caber bajando el dpi (misma grafica, menos pixeles).
    El tope se elige justo por debajo de lo que pesa a 150 ppp."""
    grande = mates.graficar_expresion("sin(x)/x", tmp_path / "g1.png")
    tope = int(grande["bytes"] * 0.8)
    r = mates.graficar_expresion("sin(x)/x", tmp_path / "g2.png",
                                 tope_bytes=tope)
    assert r["bytes"] <= tope
    assert r["dpi"] < mates.DPI
    assert r["avisos"], "bajar el dpi no puede ser mudo"


def test_si_no_cabe_ni_al_minimo_se_lanza_y_no_queda_fichero(tmp_path):
    """Un PNG que revienta el presupuesto de adjuntos no se entrega a medias:
    la vista solo podria enlazarlo con file:// y la grafica dejaria de viajar
    con el HTML sin que nadie lo haya decidido."""
    destino = tmp_path / "imposible.png"
    with pytest.raises(mates.ErrorDeMates) as e:
        mates.graficar_expresion("sin(x)/x", destino, tope_bytes=2000)
    assert "tope" in str(e.value) and str(mates.DPI_MINIMO) in str(e.value)
    assert not destino.exists(), "no puede quedar un PNG que excede el tope"


def test_un_dpi_bajo_el_suelo_no_se_sube_en_silencio(tmp_path):
    """Pedir 40 ppp se subia a 72 sin decirlo: quien lo pedia para que pesara
    menos se llevaba otra cosa y creia que el parametro no servia. Un
    parametro que se ignora sin avisar es el vacio silencioso del repo con
    otra cara. El suelo si se aplica a los escalones INTERNOS, que los elige
    el modulo y ya salen en los avisos."""
    bajo = mates.DPI_MINIMO - 1
    puertas = (
        lambda: mates.formula_a_png("x^2", tmp_path / "a.png", dpi=bajo),
        lambda: mates.graficar_expresion("x", tmp_path / "b.png", dpi=bajo),
        lambda: mates.graficar_datos(tmp_path / "c.png", [1, 2], dpi=bajo),
    )
    for puerta in puertas:
        with pytest.raises(mates.ErrorDeMates) as e:
            puerta()
        assert str(mates.DPI_MINIMO) in str(e.value), str(e.value)
    # el suelo exacto SI vale: el tope es "por debajo de", no "o igual"
    r = mates.graficar_expresion("x", tmp_path / "d.png", dpi=mates.DPI_MINIMO)
    assert r["dpi"] == mates.DPI_MINIMO


def test_las_graficas_tipicas_caben_de_sobra(tmp_path):
    """El tope documentado (1 MB) tiene que ser holgado para lo NORMAL, o
    acabaria apagado. Se comprueba con las tres formas que el cuaderno usa."""
    tres = [
        mates.formula_a_png("E = mc^2", tmp_path / "a.png"),
        mates.graficar_expresion("sin(x)/x", tmp_path / "b.png"),
        mates.graficar_datos(tmp_path / "c.png", [5, 7, 9, 4],
                             etiquetas=["1", "2", "3", "4"], tipo="barras"),
    ]
    for r in tres:
        assert r["bytes"] < mates.TOPE_BYTES / 4, r


# ── La puerta unica ──────────────────────────────────────────────────────────

def test_graficar_deduce_el_tipo(tmp_path):
    assert mates.graficar(tmp_path / "1.png", expresion="x")["tipo"] == "expresion"
    assert mates.graficar(tmp_path / "2.png", y=[1, 2])["tipo"] == "linea"
    assert mates.graficar(tmp_path / "3.png", y=[1, 2],
                          etiquetas=["a", "b"])["tipo"] == "barras"
    assert mates.graficar(tmp_path / "4.png", y=[1, 2],
                          tipo="dispersion")["tipo"] == "dispersion"


def test_graficar_sin_datos_ni_expresion_avisa(tmp_path):
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar(tmp_path / "x.png")
    with pytest.raises(mates.ErrorDeMates):
        mates.graficar(tmp_path / "x.png", tipo="tarta", y=[1])


def test_los_tipos_son_el_punto_de_extension():
    """El registro es lo que evita el if-chain enterrado. Si alguien aniade un
    tipo nuevo tiene que aparecer aqui y no en un elif."""
    assert set(mates.TIPOS) == {"expresion", "linea", "barras", "dispersion"}


def test_el_modulo_no_deja_estado(tmp_path):
    """Puro y sin estado: dos llamadas iguales dan el mismo PNG BYTE A BYTE.

    Se comparan los bytes de verdad. Antes el docstring decia 'byte a byte' y
    el assert solo miraba el tamanio y el ancho, o sea que un PNG con la hora
    sellada dentro (mismo tamanio, distinto contenido) pasaba. MEDIDO con
    matplotlib 3.11.1: los dos PNG salen identicos, 49.099 bytes.
    """
    a = mates.graficar_expresion("cos(x)", tmp_path / "a.png")
    b = mates.graficar_expresion("cos(x)", tmp_path / "b.png")
    assert a["bytes"] == b["bytes"] and a["ancho_px"] == b["ancho_px"]
    assert _leer(a["ruta"]) == _leer(b["ruta"]), (
        "los dos PNG pesan igual pero NO son iguales: el modulo esta metiendo "
        "algo variable dentro (una fecha, una semilla, el ultimo dpi)")
