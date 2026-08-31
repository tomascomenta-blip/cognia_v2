"""
tests/test_compilador_generador.py
==================================
Examen de cognia/compilador/generador.py: el paso de la Espec al CODIGO.

QUE SE EXAMINA Y POR QUE. Este generador escribe codigo que acaba DENTRO de
cognia/cli.py, o sea dentro del bucle del REPL del duenio. Los dos fallos que
importan son: (1) que el handler generado no compile o no siga el patron que el
injertador exige, y (2) que el validador deje pasar un handler que puede tumbar
el REPL (except desnudo, raise que sube, helper inventado). Todo lo demas es
decoracion.

COMO SE EXAMINA. Sin modelo (el camino deterministico es el principal, no el
plan B) y CORRIENDO el codigo generado de verdad: no basta con que compile, asi
que hay un test que ejecuta el handler con los helpers del CLI inyectados por
parametro y mira lo que imprime en cada rama. Un `compile()` verde no distingue
un stub que habla de uno que se calla, y esa distincion es justo la que este
generador promete.

Las dependencias se inyectan (orquestador de mentira por parametro, helpers en
el namespace del exec): es como lo hace el resto del repo y evita tocar nada
de produccion.
"""

from __future__ import annotations

import contextlib
import sys

import pytest

from cognia.compilador import generador as gen


# ── Especs de examen ─────────────────────────────────────────────────────────
#
# Se declaran como objetos planos con los campos que el generador lee. No se
# importa especificacion.Espec a proposito: el generador lee la espec por
# atributos (con alias), y probarlo con objetos distintos es justo lo que
# demuestra que ese contrato aguanta. Si un dia Espec cambia un nombre de
# campo, el generador sigue funcionando y estos tests lo siguen cubriendo.

class EspecPlana:
    """Espec minima: los campos que el generador necesita, y nada mas."""

    def __init__(self, cmd, descripcion, subcomandos=(), criterios=(),
                 pasa_ai=False):
        self.cmd = cmd
        self.descripcion = descripcion
        self.subcomandos = list(subcomandos)
        self.criterios = list(criterios)
        self.pasa_ai = pasa_ai


ESPEC_AGENDA = EspecPlana(
    "/agenda-dia",
    "Agenda del dia: lista y aniade recordatorios del duenio",
    subcomandos=["hoy: lo que toca hoy", "aniadir: aniade una entrada"],
    criterios=["hoy -> hoy", "-> /agenda-dia"],
)

ESPEC_SIN_SUBS = EspecPlana(
    "/latidos",
    "Ensenia si los servidores de la flota responden",
)

ESPEC_CON_AI = EspecPlana(
    "/resumir-hoy",
    "Resume en dos lineas lo que se hizo hoy",
    subcomandos=[{"nombre": "corto", "que": "resumen de dos lineas"},
                 {"nombre": "largo", "que": "resumen con detalle"}],
    criterios=[{"entrada": "corto", "espera": "corto"}],
    pasa_ai=True,
)

# Una espec en forma de dict: el generador tiene que leerla igual, porque el
# compilador la puede recibir de un JSON y no de un objeto.
ESPEC_DICT = {
    "cmd": "/notas-rapidas",
    "descripcion": "Guarda y lista notas de una linea",
    "subcomandos": ["guardar", "listar"],
    "criterios": ["listar -> listar"],
}

TODAS = [ESPEC_AGENDA, ESPEC_SIN_SUBS, ESPEC_CON_AI, ESPEC_DICT]


def _nombre_de(espec):
    if isinstance(espec, dict):
        return espec["cmd"].lstrip("/").replace("-", "_")
    return espec.cmd.lstrip("/").replace("-", "_")


# ── El handler de plantilla ──────────────────────────────────────────────────

@pytest.mark.parametrize("espec", TODAS)
def test_el_handler_de_plantilla_compila(espec):
    """Si no compila, el injertador deja cli.py con sintaxis rota y el
    producto entero deja de arrancar. Es la comprobacion mas barata y la que
    mas cuesta si falta."""
    codigo = gen.plantilla_handler(espec)
    compile(codigo, "<handler>", "exec")


@pytest.mark.parametrize("espec", TODAS)
def test_el_handler_empieza_por_la_def_exacta(espec):
    """injertador.injertar() comprueba literalmente que el handler empiece por
    'def _slash_<nombre>(' y devuelve ok=False si no. O sea que esto no es
    estilo: es la condicion de entrada del injerto."""
    codigo = gen.plantilla_handler(espec)
    esperado = "def _slash_%s(" % _nombre_de(espec)
    assert codigo.startswith(esperado), codigo[:80]


def test_el_handler_con_ai_lleva_el_parametro_ai():
    """pasa_ai cambia la FIRMA, y el despacho del injertador pasa `ai` por
    posicion: si la firma no lo acepta, el comando revienta al teclearlo."""
    codigo = gen.plantilla_handler(ESPEC_CON_AI)
    assert codigo.startswith('def _slash_resumir_hoy(arg: str = "", ai=None)')


@pytest.mark.parametrize("espec", TODAS)
def test_validar_codigo_aprueba_su_propia_plantilla(espec):
    """La plantilla tiene que pasar su propio validador. Si no, el generador
    entrega handlers que el mismo rechaza -- que es la forma mas rapida de que
    alguien apague la validacion."""
    codigo = gen.plantilla_handler(espec)
    problemas = gen.validar_codigo(codigo, _nombre_de(espec))
    assert problemas == [], problemas


@pytest.mark.parametrize("espec", TODAS)
def test_el_handler_sigue_el_patron_de_la_casa(espec):
    """Los cinco puntos del sitio 2 de la receta, comprobados sobre el texto:
    docstring con punto de extension, import perezoso en try/except que degrada
    por _aviso_degradado, el strip del argumento y el Uso en el caso malo."""
    codigo = gen.plantilla_handler(espec)
    assert '"""' in codigo, "sin docstring"
    assert "PUNTO DE EXTENSION" in codigo
    assert "    try:\n        from " in codigo, "el import no es perezoso"
    assert "_aviso_degradado(" in codigo, "no degrada: se callaria al fallar"
    assert 'arg = (arg or "").strip()' in codigo
    assert "Uso: " in codigo, "el caso malo no dice el uso"


@pytest.mark.parametrize("espec", TODAS)
def test_el_handler_tiene_una_rama_por_subcomando(espec):
    codigo = gen.plantilla_handler(espec)
    campos = gen._campos(espec)
    for nom, _ in campos["subs"]:
        assert 'if bajo == "%s"' % nom in codigo, "falta la rama %s" % nom


# ── generar(): el contrato publico ───────────────────────────────────────────

@pytest.mark.parametrize("espec", TODAS)
def test_generar_sin_modelo_devuelve_el_contrato_entero(espec):
    """Las siete claves del contrato, con via='plantilla' cuando no hay orch.

    Sin orquestador NO se inventa nada: es la decision de diseno del fichero, y
    si un dia alguien pone ahi una llamada al modelo, este test lo caza."""
    res = gen.generar(espec, orch=None)
    assert set(res) == {"handler", "modulo", "ruta_modulo", "tests",
                        "ruta_tests", "via", "avisos"}
    assert res["via"] == "plantilla"
    assert res["handler"].startswith("def _slash_%s(" % _nombre_de(espec))
    assert res["ruta_modulo"].endswith("%s.py" % _nombre_de(espec))
    assert res["ruta_tests"] == "tests/test_cmd_%s.py" % _nombre_de(espec)
    assert isinstance(res["avisos"], list)


@pytest.mark.parametrize("espec", TODAS)
def test_el_modulo_de_apoyo_compila_y_funciona(espec):
    """El modulo no solo compila: se EJECUTA y se le pide cada subcomando.

    Se comprueba que el stub confiesa (implementado=False) en vez de fingir
    exito, que es la diferencia entre 'no lo cablearon' y 'se rompio' -- los
    dos estados que este repo tiene prohibido que se vean igual."""
    res = gen.generar(espec, orch=None)
    ns = {}
    exec(compile(res["modulo"], res["ruta_modulo"], "exec"), ns)
    campos = gen._campos(espec)
    assert set(ns["ACCIONES"]) == {n for n, _ in campos["subs"]}
    for nom, _ in campos["subs"]:
        r = ns["ejecutar"](nom, "")
        assert r["implementado"] is False, "un stub que dice estar implementado"
        assert nom in r["mensaje"] and "no esta implementada" in r["mensaje"]
    desconocido = ns["ejecutar"]("no-existe", "")
    assert "desconocido" in desconocido["mensaje"]
    est = ns["estado"]()
    assert est["comando"] == campos["cmd"]


@pytest.mark.parametrize("espec", TODAS)
def test_los_tests_generados_son_python_valido(espec):
    """Un fichero de tests que no parsea es un examen que nunca se ejecuta --
    y esa es una leccion cara de este repo (un skipif dejo un test sin correr
    nunca). Ademas se exige que prueben ALGO: nada de 'assert True'."""
    res = gen.generar(espec, orch=None)
    compile(res["tests"], res["ruta_tests"], "exec")
    texto = res["tests"]
    assert "assert True" not in texto, "examen de mentira"
    assert "importorskip" not in texto and "skipif" not in texto, \
        "un test que se salta solo no examina nada"
    assert "from cognia import cli" in texto, "no prueban el CLI de verdad"
    assert "capsys" in texto, "no miran la salida real"
    nombre = _nombre_de(espec)
    assert '_slash_%s' % nombre in texto
    # una funcion de test por subcomando + estado + uso + nunca-lanza
    for nom, _ in gen._campos(espec)["subs"]:
        assert "def test_%s_sub_%s(" % (nombre, nom) in texto
    assert "def test_%s_nunca_lanza(" % nombre in texto


def test_los_criterios_de_la_espec_acaban_en_asserts():
    """Los criterios son la postcondicion que pidio el duenio: si no aparecen
    en los tests generados, la herramienta se da por buena sin examinarla."""
    res = gen.generar(ESPEC_AGENDA, orch=None)
    assert "def test_agenda_dia_criterio_1(" in res["tests"]
    assert "def test_agenda_dia_criterio_2(" in res["tests"]
    assert "in out.lower()" in res["tests"]


def test_sin_criterios_lo_dice_en_avisos():
    """Un examen flojo es aceptable; uno flojo y CALLADO no."""
    res = gen.generar(ESPEC_SIN_SUBS, orch=None)
    assert any("criterios" in a for a in res["avisos"]), res["avisos"]


# ── El handler, CORRIDO de verdad ────────────────────────────────────────────

def _correr_handler(codigo: str, nombre: str, entradas):
    """Ejecuta el handler generado con los helpers del CLI inyectados.

    Los helpers se inyectan por parametro (aqui, por namespace del exec) igual
    que se inyectan las dependencias en el resto del repo: el handler generado
    los toma de los globals de cli.py, asi que darle unos globals con esos
    mismos nombres es correr el codigo TAL CUAL, no una version de mentira.
    """
    salida = []
    ns = {
        "_print_line": lambda t: salida.append(str(t)),
        "_show_response": lambda t, *a, **k: salida.append(str(t)),
        "_escape": lambda t: str(t),
        "_aviso_degradado": lambda via, detalle="", *a, **k:
            salida.append("DEGRADADO %s: %s" % (via, detalle)),
        "_load_config": lambda: {},
        "_save_config": lambda cfg: None,
        "_abrir_en_navegador": lambda *a, **k: False,
    }
    exec(compile(codigo, "<handler>", "exec"), ns)
    fn = ns["_slash_%s" % nombre]
    fuera = []
    for entrada in entradas:
        del salida[:]
        fn(entrada)
        fuera.append(" ".join(" ".join(salida).split()))
    return fuera


def test_el_handler_degrada_cuando_falta_el_modulo_de_apoyo():
    """El caso mas probable en produccion: el comando esta injertado y el
    modulo de apoyo todavia no se ha escrito. Tiene que AVISAR y volver, nunca
    lanzar -- una excepcion aqui se lleva por delante el REPL entero."""
    codigo = gen.plantilla_handler(ESPEC_AGENDA)
    salidas = _correr_handler(codigo, "agenda_dia", ["", "hoy", "basura"])
    for s in salidas:
        assert s.startswith("DEGRADADO agenda_dia:"), s
        assert "no importable" in s


@contextlib.contextmanager
def _apoyo_temporal(tmp_path):
    """Cuelga un tmp_path del paquete de apoyo y lo DESCUELGA TODO al salir.

    La carpeta va en un tmp_path que se cuelga del __path__ del paquete de
    destino: asi el import lo resuelve la maquinaria de imports de Python de
    verdad (no un sys.modules amaniado) y NO se escribe nada dentro del repo.

    Se contemplan los dos mundos a proposito: el paquete `generadas` puede
    existir ya (si alguien compilo una herramienta) o no existir todavia. Con
    un __init__.py dentro, es un paquete REGULAR y su __path__ manda sobre
    cualquier carpeta suelta -- medido aqui el 2026-08-31, colgar el tmp_path
    del paquete padre dejaba de funcionar en cuanto aparecia ese __init__.py.

    Y la limpieza es la mitad del asunto. Medido el 2026-08-31: borrar el
    modulo de sys.modules NO basta, porque el import tambien lo deja pegado
    como ATRIBUTO del paquete padre, y `from ...generadas import agenda_dia`
    en cualquier OTRO fichero de la suite se lo encuentra ahi -- apuntando a un
    tmp_path que pytest ya borro. Un test que le deja eso al de al lado es un
    test que rompe a otro; por eso aqui se restauran los tres sitios: sys.path,
    sys.modules y los atributos del paquete.
    """
    import importlib

    destino = tmp_path / "generadas"
    destino.mkdir()
    try:
        paquete = importlib.import_module(gen.PAQUETE_APOYO)
        colgado = str(destino)
    except ImportError:
        (destino / "__init__.py").write_text("", encoding="utf-8")
        paquete = importlib.import_module("cognia.compilador")
        colgado = str(tmp_path)

    modulos_antes = set(sys.modules)
    atributos_antes = set(vars(paquete))
    sys.path.insert(0, str(tmp_path))
    paquete.__path__.append(colgado)
    importlib.invalidate_caches()
    try:
        yield destino
    finally:
        paquete.__path__.remove(colgado)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        for mod in sorted(set(sys.modules) - modulos_antes):
            if mod.startswith(gen.PAQUETE_APOYO):
                del sys.modules[mod]
        for atr in sorted(set(vars(paquete)) - atributos_antes):
            delattr(paquete, atr)
        importlib.invalidate_caches()


def test_el_handler_corre_de_verdad_cada_rama(tmp_path):
    """El examen serio: se escribe el modulo de apoyo generado donde el handler
    lo va a buscar, y se teclea cada subcomando."""
    res = gen.generar(ESPEC_AGENDA, orch=None)
    with _apoyo_temporal(tmp_path) as destino:
        (destino / "agenda_dia.py").write_text(res["modulo"], encoding="utf-8")
        salidas = _correr_handler(res["handler"], "agenda_dia",
                                  ["", "hoy", "aniadir", "zzz-no-existe"])

    estado, hoy, aniadir, malo = salidas
    # nada de esto puede haber degradado: el modulo SI estaba
    for s in salidas:
        assert not s.startswith("DEGRADADO"), s
    assert "/agenda-dia" in estado and "sin implementar" in estado
    assert "hoy" in hoy and "no esta implementada" in hoy
    assert "aniadir" in aniadir and "no esta implementada" in aniadir
    assert "Uso:" in malo, "el caso malo no dijo el uso: %r" % malo


def test_correr_el_handler_no_deja_sucio_el_paquete_de_apoyo(tmp_path):
    """Estado global: lo que este fichero cuelga, este fichero lo descuelga.

    Sin esto, el modulo importado desde el tmp_path se queda pegado como
    atributo del paquete real y `from cognia.compilador.generadas import
    agenda_dia` en OTRO fichero de la suite devuelve un modulo cuyo fichero ya
    no existe. Medido el 2026-08-31: el sys.modules limpio no bastaba.
    """
    import importlib

    paquete = importlib.import_module(gen.PAQUETE_APOYO)
    modulos_antes = set(sys.modules)
    atributos_antes = set(vars(paquete))
    camino_antes = list(paquete.__path__)

    res = gen.generar(ESPEC_AGENDA, orch=None)
    with _apoyo_temporal(tmp_path) as destino:
        (destino / "agenda_dia.py").write_text(res["modulo"], encoding="utf-8")
        _correr_handler(res["handler"], "agenda_dia", ["hoy"])
        # control positivo: DENTRO del with el modulo si estaba importado, o
        # este test pasaria aunque el handler no hubiera importado nada.
        assert "cognia.compilador.generadas.agenda_dia" in sys.modules

    assert list(paquete.__path__) == camino_antes, "quedo un __path__ colgado"
    assert not [m for m in set(sys.modules) - modulos_antes
                if m.startswith(gen.PAQUETE_APOYO)], "quedo un modulo en sys.modules"
    assert set(vars(paquete)) - atributos_antes == set(), \
        "quedo el modulo pegado como atributo del paquete: otro fichero de la " \
        "suite se lo encontraria apuntando a un tmp_path ya borrado"


# ── El texto libre de la espec no puede romper lo generado ───────────────────

TEXTOS_HOSTILES = [
    'con """comillas triples""" dentro',
    'con "comillas dobles" dentro',
    "con una barra al final: C:" + chr(92) + "Users" + chr(92),
    "con un salto\nde linea en medio",
    "con [corchetes] de markup",
]


@pytest.mark.parametrize("texto", TEXTOS_HOSTILES)
def test_el_texto_libre_de_la_espec_no_rompe_lo_generado(texto):
    """La espec la escribe un modelo o llega de un JSON: su texto no es de
    fiar. Medido el 2026-08-31: una descripcion con comillas triples, con una
    comilla doble, con una barra invertida o con un salto de linea producia un
    handler / modulo / tests que NO COMPILAN -- y lo que no compila acaba
    dentro de cli.py y deja el producto sin arrancar."""
    espec = EspecPlana("/hostil", texto,
                       subcomandos=["hoy: %s" % texto],
                       criterios=["hoy -> %s" % texto])
    res = gen.generar(espec, orch=None)
    compile(res["handler"], "<handler>", "exec")
    compile(res["modulo"], res["ruta_modulo"], "exec")
    compile(res["tests"], res["ruta_tests"], "exec")
    assert gen.validar_codigo(res["handler"], "hostil") == []


def test_un_nombre_de_comando_con_comillas_no_se_cuela_en_el_codigo():
    """El cmd va a literales de los tres ficheros: si trae una comilla, lo
    generado no compila. Se limpia y se DICE, no se arregla en silencio."""
    res = gen.generar(EspecPlana('/raro"cmd', "descripcion normal"), orch=None)
    compile(res["handler"], "<handler>", "exec")
    assert '"' not in res["ruta_modulo"]
    assert any("caracteres que no pueden ir" in a for a in res["avisos"]), \
        res["avisos"]


# ── validar_codigo: lo que TIENE que rechazar ────────────────────────────────

_BASE = '''def _slash_prueba(arg: str = "") -> None:
    """Comando de prueba. PUNTO DE EXTENSION: ninguno."""
    try:
        from cognia.compilador import receta as _r
    except Exception as exc:
        _aviso_degradado("prueba", f"no importable: {exc}")
        return
    arg = (arg or "").strip()
%s    _print_line("[mod]prueba[/mod] " + _escape(str(_r.CLI)))
'''


def test_validar_acepta_un_handler_correcto():
    """Control positivo. Sin el, un validador que rechaza TODO pasaria todos
    los tests de rechazo y nadie se enteraria."""
    assert gen.validar_codigo(_BASE % "", "prueba") == []


def test_validar_caza_la_sintaxis_rota():
    problemas = gen.validar_codigo("def _slash_prueba(arg:\n    pass", "prueba")
    assert problemas and "sintaxis rota" in problemas[0]


def test_validar_caza_el_nombre_equivocado():
    """El injertador exige el nombre exacto y el despacho llama a ese nombre:
    un handler bien escrito con el nombre cambiado da un comando que existe en
    /ayuda y explota al teclearlo."""
    problemas = gen.validar_codigo(_BASE % "", "otro_nombre")
    assert any("_slash_otro_nombre" in p for p in problemas), problemas


def test_validar_caza_el_except_desnudo():
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        from cognia.compilador import receta as _r
    except:
        _aviso_degradado("prueba", "fallo")
        return
    _print_line(str(_r.CLI))
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("except desnudo" in p for p in problemas), problemas


def test_validar_caza_el_except_pass_mudo():
    """Prohibido por CLAUDE.md, y por el motivo medido: 'no lo cablearon' y
    'se rompio' no pueden verse igual desde afuera."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        from cognia.compilador import receta as _r
    except Exception:
        pass
    _print_line("hecho")
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("mudo" in p for p in problemas), problemas


def test_validar_caza_el_raise_sin_capturar():
    """Una excepcion que sube desde el handler tumba el REPL del duenio."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    arg = (arg or "").strip()
    if not arg:
        raise ValueError("hace falta un argumento")
    _print_line(arg)
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("raise sin capturar" in p for p in problemas), problemas


def test_validar_deja_pasar_un_raise_que_si_se_captura():
    """La regla es 'no puede ESCAPAR', no 'no puede haber raise': un raise
    dentro de un try que captura Exception no llega nunca al REPL."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        if not arg:
            raise ValueError("vacio")
        _print_line(arg)
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
'''
    assert gen.validar_codigo(codigo, "prueba") == []


def test_validar_caza_el_raise_ESCONDIDO_EN_UNA_FUNCION_AUXILIAR():
    """Meter el raise una funcion mas adentro NO lo hace inofensivo.

    Medido el 2026-08-31: este codigo pasaba la validacion entera y, corrido,
    LANZA -- o sea la sesion del duenio cayendose. La prueba lo corre para que
    no quede en teoria: primero se comprueba que revienta de verdad, y luego
    que el validador lo caza."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    def _comprobar(x):
        if not x:
            raise ValueError("hace falta un argumento")
        return x
    _print_line(_comprobar(arg))
'''
    ns = {"_print_line": lambda t: None}
    exec(compile(codigo, "<h>", "exec"), ns)
    with pytest.raises(ValueError):
        ns["_slash_prueba"]("")          # esto es el REPL cayendose
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("_comprobar" in p for p in problemas), problemas


def test_validar_caza_la_llamada_a_un_ayudante_que_lanza():
    """Lo mismo con el ayudante FUERA del handler (que es como lo escribe un
    modelo): el raise viaja por la pila hasta el REPL igual."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    _print_line(_ayuda(arg))


def _ayuda(x):
    if not x:
        raise ValueError("vacio")
    return x
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("_ayuda" in p and "sin proteger" in p for p in problemas), problemas


def test_validar_deja_pasar_al_ayudante_si_el_handler_se_protege():
    """La regla sigue siendo 'no puede ESCAPAR', no 'no puede haber raise': si
    la llamada va dentro de un try que captura, no llega al REPL."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        _print_line(_ayuda(arg))
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))


def _ayuda(x):
    if not x:
        raise ValueError("vacio")
    return x
'''
    assert gen.validar_codigo(codigo, "prueba") == []


def test_validar_mira_TAMBIEN_lo_que_hay_fuera_del_handler():
    """El codigo generado se pega ENTERO dentro de cli.py: un `except: pass`
    en un ayudante se traga el fallo igual, y un `raise` a nivel de modulo ni
    siquiera espera a que tecleen el comando -- sube al importar cli.py y deja
    el producto sin arrancar."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    _print_line(str(_ayuda(arg)))


def _ayuda(x):
    try:
        return int(x)
    except:
        pass
    return 0


if not _print_line:
    raise RuntimeError("cli mal cargado")
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("except desnudo" in p for p in problemas), problemas
    assert any("mudo" in p for p in problemas), problemas
    assert any("nivel de modulo" in p for p in problemas), problemas


def test_validar_caza_el_handler_MUDO():
    """Un comando que no imprime por ningun camino no esta entregado: desde
    fuera, mudo y roto se ven igual. Es el fallo tipico de este repo y la
    validacion lo dejaba pasar."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc. PUNTO DE EXTENSION: ninguno."""
    arg = (arg or "").strip()
    if arg == "hoy":
        pass
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("no imprime" in p for p in problemas), problemas


def test_validar_deja_usar_re_compile():
    """`re` esta en la allowlist justamente para buscar en un texto; rechazar
    `re.compile` como 'ejecucion dinamica' es un gate que prohibe el uso normal
    de lo que el mismo permite importar -- y esos acaban apagados. El peligro
    de verdad (builtins.compile) sigue cazado."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        import re
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
        return
    _print_line(str(re.compile(r"[a-z]+").findall(arg)))
'''
    assert gen.validar_codigo(codigo, "prueba") == []
    peligroso = codigo.replace("re.compile(", "__builtins__.compile(")
    assert gen.validar_codigo(peligroso, "prueba"), "builtins.compile paso el gate"


def test_validar_caza_el_helper_inventado():
    """El fallo mas caro: importa bien, compila bien y revienta la primera vez
    que el duenio teclea el comando."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    _mostrar_tabla_bonita(arg)
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("_mostrar_tabla_bonita" in p and "inexistente" in p
               for p in problemas), problemas


def test_validar_no_confunde_una_variable_local_con_un_helper():
    """Control: `_mod`, `_r` o `_cfg` los define el propio codigo. Un validador
    que los denuncia es un validador que nadie va a usar."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    _cfg = _load_config()
    _print_line(str(_cfg))
'''
    assert gen.validar_codigo(codigo, "prueba") == []


def test_validar_caza_el_import_perezoso_fuera_del_try():
    """Sin try/except, un modulo que no esta se lleva por delante el REPL."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    from cognia.compilador import receta as _r
    _print_line(str(_r.CLI))
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("fuera de try/except" in p for p in problemas), problemas


def test_validar_caza_los_imports_peligrosos():
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        import pickle
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
        return
    _print_line(str(pickle))
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("peligroso" in p for p in problemas), problemas


def test_validar_caza_la_ejecucion_dinamica():
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        resultado = eval(arg)
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
        return
    _print_line(str(resultado))
'''
    problemas = gen.validar_codigo(codigo, "prueba")
    assert any("eval" in p for p in problemas), problemas


def test_la_frontera_se_movio_donde_dice_el_comentario():
    """os / pathlib / json / subprocess son EXACTAMENTE lo que el duenio pidio
    que se permitiera: un comando existe para tocar la maquina, y un gate que
    no deja hacer nada acaba apagado. Quien los quite de la allowlist rompe
    este test y tiene que justificar por que."""
    codigo = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        import os
        import json
        import subprocess
        from pathlib import Path
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
        return
    _print_line(json.dumps({"dir": os.getcwd(), "casa": str(Path.home()),
                            "hay_git": bool(subprocess)}))
'''
    assert gen.validar_codigo(codigo, "prueba") == []


def test_un_import_raro_se_rechaza_salvo_que_se_justifique():
    """La allowlist no es una carcel: la salida existe y deja rastro escrito en
    la propia linea, que es donde lo va a leer quien revise el comando."""
    plantilla = '''def _slash_prueba(arg: str = "") -> None:
    """Doc."""
    try:
        import xml.etree.ElementTree as ET%s
    except Exception as exc:
        _aviso_degradado("prueba", str(exc))
        return
    _print_line(str(ET))
'''
    problemas = gen.validar_codigo(plantilla % "", "prueba")
    assert any("allowlist" in p for p in problemas), problemas
    justificado = plantilla % "  # justificado: el comando lee un .xml del duenio"
    assert gen.validar_codigo(justificado, "prueba") == []


def test_validar_exige_docstring_y_el_parametro_arg():
    sin_doc = '''def _slash_prueba(entrada: str = "") -> None:
    _print_line(entrada)
'''
    problemas = gen.validar_codigo(sin_doc, "prueba")
    assert any("docstring" in p for p in problemas), problemas
    assert any("'arg'" in p for p in problemas), problemas


# ── La via del modelo: siempre con camino de degradacion ─────────────────────
#
# El modelo local es un razonador y esta MEDIDO que con presupuesto grande se
# va a razonar y no emite NADA. Estos tests fijan que cada forma de fallar
# acabe en la plantilla Y en un aviso distinto: "no habia modelo", "devolvio
# vacio" y "devolvio codigo malo" se arreglan de tres maneras distintas, asi
# que no pueden verse iguales desde fuera.

class RespuestaFalsa:
    def __init__(self, text):
        self.text = text


class OrchDeExamen:
    """Orquestador inyectado por parametro: devuelve lo que se le diga y
    apunta con que presupuesto se le llamo."""

    def __init__(self, text):
        self._text = text
        self.llamadas = []

    def infer(self, prompt, max_tokens=None, temperature=None):
        self.llamadas.append({"prompt": prompt, "max_tokens": max_tokens,
                              "temperature": temperature})
        return RespuestaFalsa(self._text)


class OrchQueRevienta:
    def infer(self, prompt, max_tokens=None, temperature=None):
        raise RuntimeError("el backend no responde")


def test_el_modelo_que_devuelve_vacio_cae_en_la_plantilla():
    """El fallo MEDIDO el 2026-08-30: 52.535 chars de razonamiento y cero
    salida. Tiene que degradar, no quedarse sin handler."""
    orch = OrchDeExamen("")
    res = gen.generar(ESPEC_AGENDA, orch=orch)
    assert res["via"] == "plantilla"
    assert res["handler"].startswith("def _slash_agenda_dia(")
    assert any("VACIO" in a for a in res["avisos"]), res["avisos"]


def test_al_modelo_se_le_pide_poco_y_corto():
    """El presupuesto acotado no es un detalle: con max_tokens grande este
    modelo no emite nada. Si alguien lo sube, este test lo caza."""
    orch = OrchDeExamen("")
    gen.generar(ESPEC_AGENDA, orch=orch)
    llamada = orch.llamadas[0]
    assert llamada["max_tokens"] <= 1200, llamada["max_tokens"]
    assert len(llamada["prompt"]) < 1500, len(llamada["prompt"])


def test_el_modelo_que_devuelve_prosa_cae_en_la_plantilla():
    orch = OrchDeExamen("Claro, aqui tienes una explicacion de como lo haria.")
    res = gen.generar(ESPEC_AGENDA, orch=orch)
    assert res["via"] == "plantilla"
    assert any("sin bloque de codigo" in a for a in res["avisos"]), res["avisos"]


def test_el_modelo_que_devuelve_codigo_malo_cae_en_la_plantilla():
    """Un handler con except desnudo NO entra aunque lo escriba el modelo: la
    validacion manda sobre la via."""
    malo = ("```python\n"
            'def _slash_agenda_dia(arg: str = "") -> None:\n'
            '    """Doc."""\n'
            "    try:\n"
            "        import os\n"
            "    except:\n"
            "        return\n"
            "    _print_line(str(os))\n"
            "```")
    res = gen.generar(ESPEC_AGENDA, orch=OrchDeExamen(malo))
    assert res["via"] == "plantilla"
    assert any("no pasa la validacion" in a for a in res["avisos"]), res["avisos"]


def test_el_modelo_que_devuelve_un_handler_MUDO_cae_en_la_plantilla():
    """Un handler que compila, cumple la firma y no imprime NADA es el peor de
    todos: el duenio teclea el comando y no pasa nada, igual que si estuviera
    roto. Entraba como via='modelo' hasta el 2026-08-31."""
    mudo = ("```python\n"
            'def _slash_agenda_dia(arg: str = "") -> None:\n'
            '    """Agenda. PUNTO DE EXTENSION: ninguno."""\n'
            '    arg = (arg or "").strip()\n'
            '    if arg == "hoy":\n'
            "        pass\n"
            "```")
    res = gen.generar(ESPEC_AGENDA, orch=OrchDeExamen(mudo))
    assert res["via"] == "plantilla", res["avisos"]
    assert any("no imprime" in a for a in res["avisos"]), res["avisos"]


def test_el_modelo_que_revienta_cae_en_la_plantilla_y_lo_dice():
    res = gen.generar(ESPEC_AGENDA, orch=OrchQueRevienta())
    assert res["via"] == "plantilla"
    assert any("RuntimeError" in a for a in res["avisos"]), res["avisos"]


def test_el_modelo_que_acierta_si_entra_y_se_marca_como_modelo():
    """Control positivo de la via del modelo: si NADA pudiera venir del modelo,
    todos los tests de degradacion pasarian por el motivo equivocado."""
    bueno = ("Aqui tienes:\n```python\n"
             'def _slash_agenda_dia(arg: str = "") -> None:\n'
             '    """Agenda del dia. PUNTO DE EXTENSION: el dict de ramas."""\n'
             "    try:\n"
             "        from cognia.compilador import receta as _r\n"
             "    except Exception as exc:\n"
             '        _aviso_degradado("agenda_dia", f"no importable: {exc}")\n'
             "        return\n"
             '    arg = (arg or "").strip()\n'
             '    _print_line("[mod]/agenda-dia[/mod] " + _escape(str(_r.CLI)))\n'
             "```\n")
    res = gen.generar(ESPEC_AGENDA, orch=OrchDeExamen(bueno))
    assert res["via"] == "modelo", res["avisos"]
    assert "_r.CLI" in res["handler"]
    # los tests y el modulo NUNCA vienen del modelo: son estructura
    assert res["tests"] == gen.plantilla_tests(ESPEC_AGENDA)
    assert res["modulo"] == gen.plantilla_modulo(ESPEC_AGENDA)


def test_el_codigo_sin_valla_de_cierre_se_recupera():
    """Un razonador que se corta emite la valla de apertura y no la de cierre.
    Tirar esa respuesta entera seria perder codigo que compila."""
    cortado = ("```python\n"
               'def _slash_agenda_dia(arg: str = "") -> None:\n'
               '    """Doc. PUNTO DE EXTENSION: ninguno."""\n'
               '    arg = (arg or "").strip()\n'
               "    _print_line(_escape(arg))\n")
    res = gen.generar(ESPEC_AGENDA, orch=OrchDeExamen(cortado))
    assert res["via"] == "modelo", res["avisos"]


# ── La espec incompleta no se rellena en silencio ────────────────────────────

def test_una_espec_sin_descripcion_avisa():
    res = gen.generar(EspecPlana("/vacio-total", ""), orch=None)
    assert any("descripcion" in a for a in res["avisos"]), res["avisos"]
    compile(res["handler"], "<h>", "exec")


def test_un_nombre_que_ya_existe_se_avisa_contra_el_catalogo_real():
    """/ayuda existe en el repo: generar un comando con ese nombre tiene que
    avisar ANTES de llegar al injertador, donde el diagnostico ya es caro."""
    res = gen.generar(EspecPlana("/ayuda", "Otra ayuda"), orch=None)
    assert any("ya existe" in a for a in res["avisos"]), res["avisos"]
