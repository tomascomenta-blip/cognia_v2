"""
tests/test_compilador_especificacion.py
=======================================
Guardianes de `cognia/compilador/especificacion.py` (EL PLANO del compilador
de herramientas).

QUE SE EXAMINA AQUI, y por que estas cosas y no otras: los tres modos en los
que una espec mala rompe algo AGUAS ABAJO y no se nota hasta que es tarde.

  1. Un NOMBRE ya usado. El injertador aborta y deja al duenio con un
     "motivo" en vez de una herramienta; peor todavia, un nombre que colisiona
     por prefijo se despacha por la rama equivocada.
  2. Una CATEGORIA sin hueco. Pone roja la suite entera (tope de 25 por
     categoria) sin tocar el comando nuevo para nada, y dos categorias estan
     a 25/25 HOY.
  3. Una espec SIN CRITERIOS. Compila, injerta, y produce una herramienta que
     nadie puede declarar terminada: solo "parece que anda".

Y la trampa que costo suites rojas de verdad (receta.TRAMPAS): la descripcion
cuya primera frase lleva 'tarea', 'agente', 'plan' o 'paso' se va sola a
"Agente y tareas", que esta llena.

TODO CORRE SIN MODELO. El `orch` se inyecta por parametro, como hace el resto
del repo: un objeto de test con `infer()` que devuelve lo que el examen
necesita (vacio, basura o buena respuesta). Asi se prueba el camino de
degradacion -- que es el que de verdad se usa, porque el razonador local con
presupuesto grande no emite nada -- sin cargar 27B de pesos.
"""

import json
from types import SimpleNamespace

import pytest

from cognia.compilador import receta as rec
from cognia.compilador import especificacion as esp


# ── Textos de ejemplo: pedidos como los teclea el duenio ─────────────────────
TEXTOS = [
    "hazme una herramienta que me diga cuanto ocupa cada carpeta del escritorio",
    "quiero un comando que busque notas duplicadas en mi memoria",
    "una utilidad que me resuma el historial de la sesion de hoy",
    "necesito ver la temperatura de la GPU y la VRAM libre",
    "dime que paginas web visite ultimamente y guarda el reporte",
    "algo que exporte mis metas a un fichero",
    "un comando que compare dos ficheros de configuracion",
]


class OrchFalso:
    """Un `orch` de mentira que ademas GUARDA como se le llamo.

    Guardar la llamada no es decorado: el fallo medido del razonador local es
    que con presupuesto grande se va a razonar y no emite nada, asi que el
    examen tiene que poder comprobar que el modulo pide POCO. Un mock que solo
    devuelve texto no cazaria una regresion de max_tokens.
    """

    def __init__(self, salida="", excepcion=None):
        self.salida = salida
        self.excepcion = excepcion
        self.llamadas = []

    def infer(self, prompt, max_tokens=None, temperature=None):
        self.llamadas.append({"prompt": prompt, "max_tokens": max_tokens,
                              "temperature": temperature})
        if self.excepcion is not None:
            raise self.excepcion
        return SimpleNamespace(text=self.salida)


def _validador_con_ocupados(*ocupados):
    """Un validador de nombres igual al de la receta pero con `ocupados` ya
    dados de alta. Se inyecta por parametro para poder probar la colision sin
    tener que injertar un comando de verdad en cli.py."""
    def validador(cmd):
        if cmd in ocupados:
            return False, "ya existe un comando %s" % cmd
        return rec.validar_nombre(cmd)
    return validador


# ── De un texto sale una espec VALIDA ────────────────────────────────────────

@pytest.mark.parametrize("texto", TEXTOS)
def test_de_cada_texto_sale_una_espec_valida(texto):
    espec = esp.desde_texto(texto)
    assert esp.validar(espec) == [], "espec invalida para %r" % texto


@pytest.mark.parametrize("texto", TEXTOS)
def test_el_nombre_elegido_esta_libre_en_el_repo_real(texto):
    """La regla dura: no se devuelve una espec con un nombre ya usado."""
    espec = esp.desde_texto(texto)
    ok, motivo = rec.validar_nombre(espec.cmd)
    assert ok, "%s no vale: %s" % (espec.cmd, motivo)
    assert espec.cmd not in rec.catalogo()


@pytest.mark.parametrize("texto", TEXTOS)
def test_el_nombre_casa_con_el_handler(texto):
    """`nombre` es el de `_slash_<nombre>`, o sea un identificador de Python:
    '/mapa-codigo' se sirve con `_slash_mapa_codigo` (asi esta en cli.py)."""
    espec = esp.desde_texto(texto)
    assert espec.nombre == espec.cmd.lstrip("/").replace("-", "_")
    assert espec.nombre.isidentifier()


# ── Colision de nombres ──────────────────────────────────────────────────────

def test_un_nombre_colisionado_se_resuelve_con_otro_con_sentido():
    texto = TEXTOS[0]           # ... cuanto ocupa cada carpeta del escritorio
    libre = esp.desde_texto(texto)
    assert libre.cmd == "/carpeta"

    ocupado = esp.desde_texto(
        texto, validador_nombre=_validador_con_ocupados("/carpeta", "/carpetas"))
    assert ocupado.cmd not in ("/carpeta", "/carpetas")
    # No un sufijo numerico: el siguiente candidato es un compuesto con la
    # otra palabra del pedido, que sigue diciendo lo que hace el comando.
    assert ocupado.cmd == "/carpeta-escritorio"
    assert any("desambiguado" in a for a in ocupado.avisos)


def test_el_plural_de_desambiguacion_es_una_palabra_de_verdad():
    """El plural ingenuo (nombre + 's') daba '/historials'. El nombre del
    comando lo lee el duenio en /ayuda todos los dias."""
    espec = esp.desde_texto(
        "una utilidad que me resuma el historial de la sesion de hoy",
        validador_nombre=_validador_con_ocupados("/historial"))
    assert espec.cmd == "/historiales"


def test_un_nombre_largo_no_se_queda_sin_candidatos():
    """`_sanear_nombre` corta a TOPE_NOMBRE por la DERECHA, asi que con una
    base larga el corte se comia el SUFIJO y los 17 candidatos colapsaban en
    UNO: `_candidatos('resumen-de-carpetas', ...)` devolvia una sola cosa y
    `elegir_nombre` contestaba 'ningun nombre quedo libre' con 17 nombres
    libres delante. Pasa con cualquier nombre largo propuesto por el modelo,
    que es de donde salen los nombres compuestos."""
    cands = esp._candidatos("resumen-de-carpetas", "resumen de carpetas grandes")
    assert len(cands) >= 10, cands
    assert len(set(cands)) == len(cands), "candidatos repetidos"
    for n in cands:
        assert len(n) <= esp.TOPE_NOMBRE, n
        ok, _ = rec.validar_nombre("/" + n)
        assert ok, n
    cmd, avisos = esp.elegir_nombre(
        "resumen-de-carpetas", "",
        validador=_validador_con_ocupados("/resumen-de-carpetas"))
    assert cmd and cmd != "/resumen-de-carpetas"
    assert any("desambiguado" in a for a in avisos)


def test_ningun_candidato_lleva_la_palabra_que_lo_manda_a_la_categoria_llena():
    """El nombre tambien lo lee `ayuda.clasificar`. '/traspaso' y
    '/tareas-viejas' no son 'paso' ni 'tareas', pero se autoclasifican en la
    categoria llena igual: la regla tiene que ser por SUBCADENA y no una lista
    de palabras enteras."""
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    for base in ("traspaso", "tareas-viejas", "plan", "paso"):
        for n in esp._candidatos(base, "el traspaso de las tareas del plan"):
            assert ayuda.clasificar("/" + n, "") != "Agente y tareas", n


def test_si_no_queda_ningun_nombre_libre_la_espec_se_marca_invalida():
    """Nunca se devuelve una espec con un nombre usado: si no queda ninguno,
    el aviso lo dice y validar() la rechaza (que es lo que impide injertarla)."""
    todo_ocupado = lambda cmd: (False, "ya existe un comando %s" % cmd)
    espec = esp.desde_texto(TEXTOS[0], validador_nombre=todo_ocupado)
    assert any("ningun nombre" in a for a in espec.avisos)
    problemas = esp.validar(espec, validador_nombre=todo_ocupado)
    assert any("no vale" in p for p in problemas)


# ── Categoria: solo de las que TIENEN hueco, y la mas afin ───────────────────

@pytest.mark.parametrize("texto", TEXTOS)
def test_la_categoria_siempre_esta_entre_las_que_tienen_hueco(texto):
    libres = rec.categorias_con_hueco()
    espec = esp.desde_texto(texto)
    assert espec.categoria in libres, (
        "%s cayo en %r, que no tiene hueco" % (espec.cmd, espec.categoria))


def test_la_categoria_se_elige_por_afinidad_y_no_por_holgura():
    """La lista de la receta viene ordenada por HUECOS, no por sentido. Si se
    cogiera la primera, una herramienta de ficheros acabaria en 'Permisos del
    agente' solo porque le sobran sitios."""
    libres = rec.categorias_con_hueco()
    espec = esp.desde_texto(TEXTOS[0])
    assert espec.categoria == "Codigo y ficheros"
    if libres and libres[0] == espec.categoria:
        # El dia que la categoria afin sea ademas la mas holgada, este test
        # deja de distinguir las dos politicas: mejor decirlo que dar por
        # bueno un examen que ya no examina nada.
        pytest.skip("la categoria afin es hoy tambien la mas holgada")


def test_sin_afinidad_se_elige_por_holgura_pero_se_avisa():
    espec = esp.desde_texto("una cosa rara que haga zzzqqq con wwwxxx",
                            categorias_libres=["Metas y seguimiento",
                                               "Codigo y ficheros"])
    assert espec.categoria == "Metas y seguimiento"
    assert any("holgura" in a for a in espec.avisos)


def test_sin_categorias_libres_la_espec_no_pasa_validar():
    espec = esp.desde_texto(TEXTOS[0], categorias_libres=[])
    assert espec.categoria == ""
    problemas = esp.validar(espec, categorias_libres=[])
    assert any("categoria" in p for p in problemas)


def test_validar_caza_una_categoria_sin_hueco_aunque_no_quede_NINGUNA():
    """El test de arriba pasaba por el motivo equivocado: la espec sale con la
    categoria VACIA, o sea que salta el aviso de 'categoria vacia' y el
    chequeo del HUECO no llega a correr nunca. Con una categoria PUESTA y la
    lista de libres vacia, `validar()` devolvia [] -- una fase no ejecutada
    contando como aprobada, y justo la que evita el desborde de categoria que
    pone roja la suite entera."""
    espec = esp.desde_texto(TEXTOS[0])
    assert espec.categoria == "Codigo y ficheros"
    problemas = esp.validar(espec, categorias_libres=[])
    assert any("no tiene hueco" in p for p in problemas), problemas
    assert esp.validar(espec, categorias_libres=["Codigo y ficheros"]) == []


# ── La trampa de las palabras prohibidas ─────────────────────────────────────

TEXTOS_TRAMPA = [
    "un comando que me recuerde los pasos del plan de la tarea del agente",
    "quiero ver el plan de cada tarea que dejo el agente anoche",
    "algo que numere paso a paso lo que hizo el agente",
]


@pytest.mark.parametrize("texto", TEXTOS + TEXTOS_TRAMPA)
def test_la_descripcion_nunca_cae_en_la_trampa(texto):
    """'tarea', 'agente', 'plan' o 'paso' en la PRIMERA FRASE mandan el
    comando a 'Agente y tareas', que esta a 25/25: una palabra mal elegida
    pone roja la suite sin tocar nada mas (receta.TRAMPAS)."""
    espec = esp.desde_texto(texto)
    assert esp.cae_en_trampa(espec.descripcion) == "", espec.descripcion
    assert esp.validar(espec) == []


@pytest.mark.parametrize("texto", TEXTOS_TRAMPA)
def test_el_clasificador_real_no_manda_la_descripcion_a_la_categoria_llena(texto):
    """El examen de verdad no es mi regex: es el clasificador de
    harness/ayuda, que es quien decide. Se le pregunta con un nombre que no
    casa con ningun patron, que es como veria un comando recien nacido."""
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    espec = esp.desde_texto(texto)
    cat = ayuda.clasificar("/zzz-comando-que-no-existe", espec.descripcion)
    assert cat in rec.categorias_con_hueco() or cat == "Otros", (
        "la descripcion %r se clasifica sola en %r" % (espec.descripcion, cat))
    assert any("prohibida" in a or "'Agente y tareas'" in a
               for a in espec.avisos)


def test_validar_caza_una_descripcion_con_palabra_prohibida():
    espec = esp.desde_texto(TEXTOS[0])
    espec.descripcion = "Lista los pasos de cada carpeta. Uso: /carpeta [ver]"
    problemas = esp.validar(espec)
    assert any("Agente y tareas" in p for p in problemas)


@pytest.mark.parametrize("texto", TEXTOS_TRAMPA)
def test_limpiar_la_trampa_no_reescribe_el_nombre_del_comando(texto):
    """Regresion de un bug REAL cazado tecleando los ejemplos del duenio: la
    sustitucion se hacia sobre la descripcion entera, o sea tambien sobre el
    'Uso: /pasos [...]' de dentro, y el comando /pasos quedaba anunciado como
    /tramos. Una plantilla de uso que nombra un comando inexistente es peor
    que no tenerla: el duenio la teclea y no pasa nada."""
    espec = esp.desde_texto(texto)
    assert "Uso: %s [" % espec.cmd in espec.descripcion, espec.descripcion


@pytest.mark.parametrize("texto", TEXTOS + TEXTOS_TRAMPA)
def test_el_nombre_del_comando_tampoco_lleva_palabra_prohibida(texto):
    """`ayuda.clasificar()` mira la descripcion Y el nombre. Un comando
    llamado '/paso' se autoclasifica en la categoria llena mientras nadie le
    de de alta su patron exacto."""
    espec = esp.desde_texto(texto)
    partes = espec.cmd.lstrip("/").split("-")
    assert not [p for p in partes if p in
                ("tarea", "tareas", "agente", "agentes",
                 "plan", "planes", "paso", "pasos")], espec.cmd


def test_cae_en_trampa_mira_LO_MISMO_QUE_EL_CLASIFICADOR():
    """Este test decia lo contrario y estaba MAL, con el clasificador real de
    testigo: `ayuda.clasificar` hace `normalizar(descripcion) + " " + nombre`
    y busca la clave por subcadena en TODO eso, o sea que lo que va detras del
    'Uso:' -- y el propio nombre del comando -- si decide categoria.

        clasificar("/x", "Mide carpetas. Uso: /x [tarea | estado]")
            -> 'Agente y tareas'   (25/25)

    Mirar solo la cabeza dejaba pasar especs que `validar()` daba por buenas y
    que ponian roja la suite igual. Se comprueba contra el clasificador de
    verdad y no contra mi idea de el.
    """
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    sucias = ["Mide carpetas. Uso: /x [tarea | estado]",
              "Mide carpetas. Y lista la tarea de cada una. Uso: /x [ver]",
              "Mide la tarea. Uso: /x [ver]"]
    for d in sucias:
        assert esp.cae_en_trampa(d), d
        assert ayuda.clasificar("/x", d) == "Agente y tareas", d
    limpia = "Mide carpetas. Uso: /x [ver | estado]"
    assert esp.cae_en_trampa(limpia) == ""
    assert ayuda.clasificar("/x", limpia) != "Agente y tareas"


def test_la_trampa_fuera_de_la_primera_frase_tambien_se_caza():
    """Regresion del fallo medido (2026-08-31): un pedido normal del duenio
    con un punto en medio metia la palabra prohibida en la SEGUNDA frase; la
    espec salia con `validar() == []` y el clasificador real la mandaba a la
    categoria llena."""
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    espec = esp.desde_texto("hazme una herramienta que mida las carpetas del "
                            "escritorio. y que liste la tarea de cada una")
    assert esp.cae_en_trampa(espec.descripcion, espec.cmd) == ""
    assert esp.validar(espec) == []
    cat = ayuda.clasificar(espec.cmd, espec.descripcion)
    assert cat != "Agente y tareas", espec.descripcion


def test_un_nombre_del_modelo_con_la_palabra_dentro_no_se_usa():
    """La lista de palabras ENTERAS dejaba pasar '/tareas-viejas': no es
    'tareas', pero el clasificador lo lee por subcadena y se lo lleva a la
    categoria llena igual."""
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    orch = OrchFalso("nombre: tareas-viejas\nfrase: revisa lo pendiente")
    espec = esp.desde_texto("hazme algo que mire mis notas de ayer", orch=orch)
    assert "tarea" not in espec.cmd
    assert esp.validar(espec) == []
    assert ayuda.clasificar(espec.cmd, espec.descripcion) != "Agente y tareas"
    assert any("se ignora" in a for a in espec.avisos)


def test_la_palabra_prohibida_dentro_de_otra_no_deja_la_espec_invalida():
    """'traspaso' lleva 'paso' dentro: el sinonimo no lo arregla y el nombre
    tampoco se salva. Antes salia una espec que `validar()` rechazaba y sin
    ninguna salida; ahora se cae al nombre generico, que es feo pero VALIDO, y
    se avisa."""
    ayuda = pytest.importorskip("cognia.harness.ayuda")
    espec = esp.desde_texto("quiero ver el traspaso de pasos de ayer")
    assert esp.validar(espec) == [], espec.descripcion
    assert esp.cae_en_trampa(espec.descripcion, espec.cmd) == ""
    assert ayuda.clasificar(espec.cmd, espec.descripcion) != "Agente y tareas"


# ── Criterios: sin postcondicion no hay herramienta ──────────────────────────

@pytest.mark.parametrize("texto", TEXTOS)
def test_siempre_hay_criterios_y_todos_invocan_el_comando(texto):
    espec = esp.desde_texto(texto)
    assert espec.criterios, "una herramienta sin postcondicion no se evalua"
    for c in espec.criterios:
        assert c["invocacion"].startswith(espec.cmd)
        assert c["espera"].strip()


def test_una_espec_sin_criterios_la_caza_validar():
    espec = esp.desde_texto(TEXTOS[0])
    assert esp.validar(espec) == []
    espec.criterios = []
    problemas = esp.validar(espec)
    assert any("criterios" in p for p in problemas)


def test_validar_caza_un_criterio_vacio_o_de_otro_comando():
    espec = esp.desde_texto(TEXTOS[0])
    espec.criterios = [
        {"invocacion": "/otro-comando ver", "espera": "algo"},
        {"invocacion": "%s ver" % espec.cmd, "espera": "   "},
    ]
    problemas = esp.validar(espec)
    assert any("no el comando" in p for p in problemas)
    assert any("sin 'espera'" in p for p in problemas)


def test_validar_caza_un_criterio_de_otro_comando_con_el_mismo_prefijo():
    """`invoc.startswith(cmd)` daba por bueno '/carpetas-otro ver' como
    criterio de '/carpetas'. Es OTRO comando: el evaluador lo teclearia en el
    REPL y estaria midiendo otra cosa, y el criterio contaria igual. En un
    modulo que existe por la colision de PREFIJOS, comparar por prefijo era el
    error de siempre."""
    espec = esp.desde_texto(TEXTOS[0])
    espec.criterios = [{"invocacion": espec.cmd + "-otro ver", "espera": "x"}]
    assert any("no el comando" in p for p in esp.validar(espec))
    espec.criterios = [{"invocacion": espec.cmd, "espera": "x"},
                       {"invocacion": espec.cmd + " estado", "espera": "estado"}]
    assert not [p for p in esp.validar(espec) if "no el comando" in p]


@pytest.mark.parametrize("texto", TEXTOS)
def test_hay_puerta_de_diagnostico(texto):
    """CLAUDE.md, regla del CLI punto 4: toda capacidad necesita un
    '/<cmd> estado' que diga si esta activa y cual fue la ultima degradacion.
    Sin el, 'no lo cablearon' y 'se rompio' se ven igual desde fuera."""
    espec = esp.desde_texto(texto)
    assert "estado" in [s["nombre"] for s in espec.subcomandos]
    assert any(c["invocacion"] == "%s estado" % espec.cmd
               for c in espec.criterios)


def test_validar_caza_la_falta_del_subcomando_estado():
    espec = esp.desde_texto(TEXTOS[0])
    espec.subcomandos = [{"nombre": "ver", "args": "", "que": "ve"}]
    assert any("estado" in p for p in esp.validar(espec))


# ── El camino sin modelo, que es el que se usa ───────────────────────────────

def test_sin_orch_la_espec_sale_igual_y_lo_dice():
    espec = esp.desde_texto(TEXTOS[0], orch=None)
    assert esp.validar(espec) == []
    assert any("sin modelo" in a for a in espec.avisos), (
        "una espec derivada por reglas tiene que declararse como tal: 'no "
        "habia modelo' no puede verse igual que 'el modelo decidio esto'")


def test_un_texto_vacio_no_produce_espec():
    for vacio in ("", "   ", None):
        with pytest.raises(ValueError):
            esp.desde_texto(vacio)


# ── El modelo: se usa si contesta, y se degrada si no ────────────────────────

def test_el_modelo_bautiza_el_comando_cuando_contesta_bien():
    orch = OrchFalso("nombre: tamanos\nfrase: cuanto ocupa cada carpeta del disco")
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert espec.cmd.startswith("/tamanos")
    assert espec.descripcion.startswith("Cuanto ocupa cada carpeta del disco")
    assert esp.validar(espec) == []
    assert not any("sin modelo" in a for a in espec.avisos)


def test_el_razonador_mudo_degrada_a_reglas_y_lo_avisa():
    """EL fallo medido (2026-08-30): el razonador se va a razonar y devuelve
    CERO salida. No es reintentable con mas presupuesto -- subirlo lo empeora
    -- asi que hay que salir por el camino deterministico y decirlo."""
    orch = OrchFalso("")
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert espec.cmd == "/carpeta"
    assert esp.validar(espec) == []
    assert any("vacio" in a for a in espec.avisos)


def test_el_modelo_fuera_de_formato_degrada_a_reglas():
    orch = OrchFalso("Claro! Aqui tienes una idea genial para tu comando :)")
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert espec.cmd == "/carpeta"
    assert esp.validar(espec) == []
    assert any("formato" in a for a in espec.avisos)


def test_el_modelo_que_lanza_no_tumba_la_especificacion():
    orch = OrchFalso(excepcion=RuntimeError("llama.cpp se cayo"))
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert esp.validar(espec) == []
    assert any("RuntimeError" in a for a in espec.avisos)


def test_al_modelo_se_le_pide_poco_y_corto():
    """Guardian de la regresion cara: presupuesto grande = cero salida."""
    orch = OrchFalso("nombre: tamanos\nfrase: cuanto ocupa cada carpeta")
    esp.desde_texto(TEXTOS[0], orch=orch)
    assert len(orch.llamadas) == 1, "una sola llamada por espec"
    llamada = orch.llamadas[0]
    assert llamada["max_tokens"] <= 400
    assert len(llamada["prompt"]) < 700
    assert llamada["temperature"] <= 0.5


def test_un_nombre_del_modelo_que_colisiona_tambien_se_desambigua():
    orch = OrchFalso("nombre: memoria\nfrase: cuanto ocupa cada carpeta")
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert espec.cmd != "/memoria"          # /memoria* ya existe en el CLI
    ok, _ = rec.validar_nombre(espec.cmd)
    assert ok


def test_una_frase_del_modelo_con_palabra_prohibida_se_limpia():
    orch = OrchFalso("nombre: escritorio\nfrase: lista los pasos de cada tarea")
    espec = esp.desde_texto(TEXTOS[0], orch=orch)
    assert esp.cae_en_trampa(espec.descripcion) == ""
    assert esp.validar(espec) == []


# ── Cubo, modulo de apoyo y demas campos del contrato ────────────────────────

@pytest.mark.parametrize("texto", TEXTOS)
def test_el_cubo_es_uno_de_los_tres(texto):
    espec = esp.desde_texto(texto)
    assert espec.cubo in esp.CUBOS_VALIDOS


def test_el_modulo_de_apoyo_apunta_al_sitio_correcto():
    """La logica que recorre el disco NO cabe en el handler: cli.py son 23.000
    lineas y ahi dentro no se puede testear sola."""
    espec = esp.desde_texto(TEXTOS[0])
    assert espec.modulo_apoyo == "cognia/herramientas/%s.py" % espec.nombre
    assert esp.validar(espec) == []


def test_validar_caza_un_modulo_de_apoyo_fuera_de_sitio():
    espec = esp.desde_texto(TEXTOS[0])
    espec.modulo_apoyo = "cognia/cli.py"
    assert any("modulo_apoyo" in p for p in esp.validar(espec))


def test_pasa_ai_solo_cuando_hace_falta_el_modelo():
    con_ia = esp.desde_texto("una utilidad que me resuma el historial de hoy")
    sin_ia = esp.desde_texto("necesito ver la temperatura de la GPU")
    assert con_ia.pasa_ai is True
    assert sin_ia.pasa_ai is False


def test_la_descripcion_es_una_linea_y_sin_comillas_dobles():
    """_CMD_DESCRIPTIONS se lee con ast.literal_eval: un valor que no sea un
    literal limpio rompe TRES tests a la vez (receta.TRAMPAS)."""
    for texto in TEXTOS:
        espec = esp.desde_texto(texto)
        assert "\n" not in espec.descripcion
        assert '"' not in espec.descripcion
        assert len(espec.descripcion) <= esp.TOPE_DESCRIPCION
        assert espec.cmd in espec.descripcion   # lleva su plantilla de uso


def test_que_hace_no_puede_cerrar_el_docstring_del_handler():
    """`que_hace` acaba dentro del docstring de _slash_<nombre>. Una comilla
    doble del texto del duenio cerraria el triple-quote y dejaria cli.py sin
    compilar -- y el injerto solo hace rollback si lo detecta."""
    espec = esp.desde_texto('hazme algo que mida la carpeta "Mis documentos"')
    assert '"' not in espec.que_hace
    assert espec.que_hace.strip()


def test_una_ruta_de_windows_no_deja_cli_sin_compilar():
    r"""Regresion del fallo MAS caro que habia aqui. El injertador escribe la
    descripcion tal cual dentro de `    "/cmd":  "<descripcion>",` y `que_hace`
    dentro del docstring del handler. Un pedido normalisimo para una
    herramienta de carpetas --

        hazme algo que mida la carpeta C:\Users\nuevo del escritorio

    -- metia la barra invertida en las dos, y `C:\Users` es un `\U`: cli.py
    deja de compilar y con el se va el REPL entero. `validar()` decia que la
    espec estaba perfecta. Se comprueba con ast, que es como lo leen los
    guardianes."""
    import ast
    espec = esp.desde_texto(
        "hazme algo que mida la carpeta C:\\Users\\nuevo del escritorio")
    assert esp.validar(espec) == []
    assert "\\" not in espec.descripcion
    assert "\\" not in espec.que_hace

    linea = '    "%s":  "%s",' % (espec.cmd, espec.descripcion)
    ast.parse("_CMD_DESCRIPTIONS = {\n%s\n}" % linea)      # como el catalogo
    ast.parse('def _slash_%s(arg: str = ""):\n    """%s"""\n'
              % (espec.nombre, espec.que_hace))            # como el handler


def test_validar_caza_la_ruta_de_windows_en_una_espec_de_fuera():
    """La espec viaja por fichero y por prompt: la puede escribir otro. El
    chequeo no puede vivir solo en `desde_texto`."""
    espec = esp.desde_texto(TEXTOS[0])
    espec.descripcion = "Mide C:\\Users. Uso: %s [ver | estado]" % espec.cmd
    assert any("barra invertida" in p for p in esp.validar(espec))
    espec = esp.desde_texto(TEXTOS[0])
    espec.que_hace = "Mide C:\\Users\\nuevo."
    assert any("barra invertida" in p for p in esp.validar(espec))


def test_validar_rechaza_lo_que_no_es_una_espec():
    assert esp.validar({"cmd": "/x"}) == ["no es una Espec: 'dict'"]


def test_validar_caza_el_cubo_inventado():
    espec = esp.desde_texto(TEXTOS[0])
    espec.cubo = "EXPERIMENTAL"
    assert any("cubo" in p for p in esp.validar(espec))


def test_la_espec_encaja_con_lo_que_pide_el_injertador():
    """La espec existe para alimentar al injertador. Si manana le cambian un
    parametro de sitio, el fallo tiene que salir AQUI y no a mitad de un
    injerto sobre cli.py, que es el fichero peligroso. No se injerta nada:
    solo se comprueba la firma y la forma del handler que exige."""
    import inspect
    import re as _re
    injertador = pytest.importorskip("cognia.compilador.injertador")

    firma = inspect.signature(injertador.injertar).parameters
    for campo in ("cmd", "nombre", "descripcion", "cubo", "categoria",
                  "pasa_ai"):
        assert campo in firma, "injertar() ya no acepta %r" % campo

    # Lo que habia aqui era una TAUTOLOGIA: el test se construia el handler
    # a partir de `espec.nombre` y luego comprobaba que casaba con un regex
    # hecho con `espec.nombre`. Pasaba con cualquier cosa y el codigo bajo
    # prueba no llegaba a correr. Lo que si examina algo es meter los campos
    # de la espec en las PLANTILLAS REALES de los 5 sitios (receta.SITIOS) y
    # comprobar que lo que sale es Python que compila: eso es literalmente
    # lo que el injertador va a escribir dentro de cli.py.
    import ast
    import textwrap
    espec = esp.desde_texto(TEXTOS[0])
    campos = {"cmd": espec.cmd, "nombre": espec.nombre,
              "descripcion": espec.descripcion, "relleno": "  "}
    piezas = {}
    for sitio in rec.SITIOS:
        try:
            piezas[sitio["clave"]] = sitio["forma"].format(**campos)
        except KeyError as e:
            pytest.fail("el sitio %r pide un campo que la espec no tiene: %s"
                        % (sitio["clave"], e))

    ast.parse("_CMD_DESCRIPTIONS = {\n%s\n}" % piezas["descripcion"])
    ast.parse("%s\n    pass\n" % piezas["funcion"])
    ast.parse("if False:\n    pass\n%s"
              % textwrap.dedent(piezas["despacho"]))
    assert espec.nombre.isidentifier()
    assert _re.match(r"^def _slash_%s\(" % _re.escape(espec.nombre),
                     piezas["funcion"]), (
        "el nombre %r no sirve para el handler que exige el injertador"
        % espec.nombre)
    # los tres cubos que el injertador acepta, cableados alli mismo
    assert espec.cubo in ("NUCLEO", "AVANZADO", "LABORATORIO")


# ── La cache de las consultas a la receta ────────────────────────────────────
#
# MEDIDO: cada llamada a la receta lee cli.py (23.000 lineas) y lo pasa por
# ast.parse -- 2,3 s. Elegir nombre prueba hasta 17 candidatos, o sea 40 s
# para bautizar un comando. La cache es correcta solo si se invalida cuando
# cli.py cambia, que es justo lo que pasa DESPUES de un injerto.

def test_la_cache_da_la_misma_respuesta_que_la_receta_cruda():
    for cmd in ("/ayuda", "/zzz-comando-que-no-existe", "/MAL", "/x"):
        assert esp.validar_nombre_repo(cmd) == rec.validar_nombre(cmd), cmd
    assert esp.categorias_libres_repo() == rec.categorias_con_hueco()


def test_la_huella_es_estable_y_cambia_con_el_fichero():
    """La clave de la cache es (mtime_ns, tamanio): estable mientras el
    fichero no cambia, distinta en cuanto cambia. Un fichero que no se puede
    medir da None, que NO es una clave: es la orden de saltarse la cache.

    Antes daba (0, 0), y eso es lo peor de los dos mundos: una clave
    perfectamente estable, o sea que el segundo fallo se servia de lo cacheado
    en el primero -- exactamente el 'fingir que nada cambio' que el log decia
    estar evitando."""
    assert esp._huella(rec.CLI) == esp._huella(rec.CLI)
    assert esp._huella(rec.CLI) != esp._huella(rec.AYUDA)
    assert esp._huella("no-existe-en-el-repo.py") is None
    assert esp._huella(rec.CLI, "no-existe-en-el-repo.py") is None


def test_sin_huella_se_responde_sin_cache_y_no_se_cachea_basura(monkeypatch):
    """Si no se puede tomar la huella, la respuesta sale de la receta CRUDA.
    Cachear bajo una clave constante seria servir un catalogo rancio justo
    despues de un injerto, que es cuando cli.py acaba de cambiar."""
    llamadas = []
    crudo_nombre = rec.validar_nombre
    crudo_cats = rec.categorias_con_hueco

    monkeypatch.setattr(esp, "_huella", lambda *a: None)
    monkeypatch.setattr(rec, "validar_nombre",
                        lambda cmd: (llamadas.append(cmd), crudo_nombre(cmd))[1])
    monkeypatch.setattr(rec, "categorias_con_hueco",
                        lambda *a, **k: (llamadas.append("cats"),
                                         crudo_cats(*a, **k))[1])

    assert esp.validar_nombre_repo("/ayuda") == crudo_nombre("/ayuda")
    assert esp.validar_nombre_repo("/ayuda") == crudo_nombre("/ayuda")
    assert esp.categorias_libres_repo() == crudo_cats()
    assert llamadas.count("/ayuda") == 2, "la segunda salio de una cache que no debia existir"
    assert "cats" in llamadas


# ── Serializacion: la espec viaja por fichero y por prompt ───────────────────

@pytest.mark.parametrize("texto", TEXTOS)
def test_ida_y_vuelta_por_dict_y_por_json(texto):
    espec = esp.desde_texto(texto)
    d = esp.a_dict(espec)
    assert json.loads(json.dumps(d)) == d      # JSON-able de verdad
    assert esp.de_dict(d) == espec


def test_de_dict_tolera_lo_que_falta_y_lo_que_sobra():
    """Tolerante a proposito: una clave de mas no puede hacer explotar la
    carga. Lo que este mal lo dice validar(), que es quien tiene la lista."""
    espec = esp.de_dict({"cmd": "/x", "sobra": 1})
    assert espec.cmd == "/x"
    assert espec.criterios == [] and espec.avisos == []
    assert espec.cubo == esp.CUBO_DEFECTO
    assert esp.validar(espec)                  # invalida, pero sin reventar


def test_a_dict_y_de_dict_rechazan_el_tipo_equivocado():
    with pytest.raises(TypeError):
        esp.a_dict({"cmd": "/x"})
    with pytest.raises(TypeError):
        esp.de_dict("no soy un dict")
