"""
Tests de las firmas tipadas de A4 (cognia/agent/firmas.py, 2026-08-13).

EL BUG QUE CUBREN: ``tool_schemas.schemas_para`` publicaba, para toda tool sin
``params`` en el decorador, un unico parametro string ``args`` con la LINEA DE
AYUDA metida adentro como descripcion. En tool-calling nativo el modelo recibia
una INSTRUCCION EN PROSA donde el protocolo le prometia una firma tipada.
Medido en el venv el 2026-08-13: 55 tools, 16 genericas (abrir, buscar_en_repo,
code_grafo, contratos, crear_flujo, crear_herramienta, cuaderno, docs_libreria,
docs_repo, ejecutar_flujo, kg_agregar, kg_buscar, plan, preguntar_repo,
repo_map, revertir_herramienta).

Los tres frentes:
 1. ``test_ninguna_tool_queda_generica`` — la TRAMPA anti-recaida: si alguien
    agrega una tool nueva sin firma, este test la caza. Fallaba con 16 antes
    del fix.
 2. Round-trip: ``args_legacy(nombre, ejemplo)`` da EXACTAMENTE el string que
    la linea de ayuda de esa tool documenta. Un armador que no reconstruye el
    formato real es peor que el generico: la tool falla en silencio.
 3. Re-parseo con el codigo REAL de produccion (``tools._partir`` y los mismos
    ``re.split`` que usa cada tool): el string armado se vuelve a partir y
    tiene que devolver los campos originales.

CONTRAFACTUAL (el numero, medido, no declarado). Con ``FIRMAS`` vaciado en
memoria — que es el estado EXACTO previo a A4, porque con el dict vacio la
rama nueva de ``args_legacy`` es un no-op — este fichero da **12 failed, 25
passed** (37 tests, 2026-08-13)::

    venv312\\Scripts\\python.exe -c "import cognia.agent.tool_schemas as ts; \\
        ts.FIRMAS={}; import pytest; \\
        raise SystemExit(pytest.main(['tests/test_firmas_tipadas.py','-q']))"

CORRECCION DE LA BITACORA: el mensaje del commit 4edbad64 anoto '11 failed,
23 passed'. Esa cifra salio de un run ANTERIOR a agregar
``test_args_pelado_sigue_pasando_derecho`` (el 12o fallo) y no cuadraba con
los 35 tests que el mismo mensaje reporta. El fix no cambia: solo el numero.
Los dos tests de la regresion de nombres improvisados PASAN con FIRMAS={} a
proposito — sin firmas todo cae al join de ultimo recurso, que es justo el
comportamiento que restauran.
"""
import re

import pytest

from cognia.agent.firmas import FIRMAS
from cognia.agent.tool_schemas import (_SIN_ARGS, _TIPADAS, args_legacy,
                                       schemas_para)
from cognia.agent.tools import TOOLS


# ── 1. La trampa: ninguna tool puede volver a caer en el generico ───────────

def test_ninguna_tool_queda_generica():
    """El generico publica {'args': <linea de ayuda en prosa>}. Cero, siempre.

    Este es el test que impide la recaida: una tool nueva sin firma tipada
    (ni ``params`` en su decorador, ni entrada en FIRMAS/_TIPADAS/_SIN_ARGS)
    lo rompe y obliga a declararla."""
    genericas = [s["function"]["name"] for s in schemas_para()
                 if list(s["function"]["parameters"].get("properties", {}))
                 == ["args"]]
    assert genericas == [], (
        f"{len(genericas)} tools siguen publicando prosa en vez de una firma: "
        f"{genericas}. Agregales una entrada en cognia/agent/firmas.py")


def test_las_16_medidas_tienen_firma():
    """Las 16 medidas el 2026-08-13 siguen cubiertas (no se cayo ninguna)."""
    esperadas = {
        "abrir", "buscar_en_repo", "code_grafo", "contratos", "crear_flujo",
        "crear_herramienta", "cuaderno", "docs_libreria", "docs_repo",
        "ejecutar_flujo", "kg_agregar", "kg_buscar", "plan", "preguntar_repo",
        "repo_map", "revertir_herramienta"}
    assert esperadas <= set(FIRMAS), esperadas - set(FIRMAS)


# ── 2. Coherencia de FIRMAS con el registry ─────────────────────────────────

def test_firmas_solo_de_tools_reales():
    """Una firma de una tool que no existe es letra muerta que nadie nota."""
    fantasmas = sorted(set(FIRMAS) - set(TOOLS))
    assert fantasmas == [], fantasmas


def test_firmas_no_se_solapan_con_las_tipadas():
    """Dos fuentes para la misma tool = una de las dos se ignora en silencio."""
    assert set(FIRMAS) & set(_TIPADAS) == set()
    assert set(FIRMAS) & set(_SIN_ARGS) == set()


def test_firmas_no_pisan_params_del_registry():
    """Si la tool DECLARA su firma en el decorador, esa es la fuente de verdad.

    schemas_para consulta FIRMAS antes que ``spec['params']``, asi que una
    tool con las dos cosas publicaria la de aca y la del decorador quedaria
    muerta. Cuando eso pase, hay que borrar la entrada de FIRMAS."""
    conflicto = sorted(n for n in FIRMAS if (TOOLS.get(n) or {}).get("params"))
    assert conflicto == [], (
        f"estas tools ya declaran params en su decorador: {conflicto}; "
        "borra su entrada de cognia/agent/firmas.py")


def test_requeridos_estan_en_properties():
    for nombre, (props, req, _armador) in FIRMAS.items():
        faltan = [r for r in req if r not in props]
        assert faltan == [], f"{nombre}: requeridos sin propiedad: {faltan}"


def test_schemas_publican_la_firma_declarada():
    """Lo que sale por schemas_para es literalmente lo de FIRMAS."""
    publicados = {s["function"]["name"]: s["function"]["parameters"]
                  for s in schemas_para()}
    for nombre, (props, req, _armador) in FIRMAS.items():
        assert publicados[nombre] == {"type": "object", "properties": props,
                                      "required": req}, nombre


# ── 3. Round-trip: el armador reconstruye el string que run_tool espera ─────

# (tool, argumentos JSON del tool call, string legacy EXACTO que documenta su
# linea de ayuda). Verificado contra el parseo real de cada tool.
CASOS = [
    # abrir <url-o-ruta-o-app>
    ("abrir", {"objetivo": "  https://youtube.com "}, "https://youtube.com"),
    # docs_repo <owner> <repo>  (separador ESPACIO: _partir)
    ("docs_repo", {"owner": "anthropics", "repo": "anthropic-sdk-python"},
     "anthropics anthropic-sdk-python"),
    # preguntar_repo <owner/repo> <pregunta>
    ("preguntar_repo", {"repo": "psf/requests",
                        "pregunta": "como se hace retry?"},
     "psf/requests como se hace retry?"),
    # docs_libreria <nombre> <tema>  (tema opcional)
    ("docs_libreria", {"nombre": "fastapi", "tema": "dependencias"},
     "fastapi dependencias"),
    ("docs_libreria", {"nombre": "polars"}, "polars"),
    # buscar_en_repo <owner> <repo> <query>
    ("buscar_en_repo", {"owner": "psf", "repo": "requests", "query": "Session"},
     "psf requests Session"),
    # repo_map [terminos]
    ("repo_map", {"terminos": "tool calling"}, "tool calling"),
    ("repo_map", {}, ""),
    # code_grafo <modulo-o-simbolo>
    ("code_grafo", {"objeto": "cognia.agent.loop"}, "cognia.agent.loop"),
    # cuaderno <nota|fuente|consultar|ver> | <texto/ruta/pregunta>
    ("cuaderno", {"subcomando": "nota", "texto": "el backend vive en :8080"},
     "nota | el backend vive en :8080"),
    ("cuaderno", {"subcomando": "ver"}, "ver"),
    # kg_buscar <concepto>
    ("kg_buscar", {"concepto": "Qwythos"}, "Qwythos"),
    # kg_agregar <sujeto> | <relacion> | <objeto>
    ("kg_agregar", {"sujeto": "Cognia", "relacion": "usa", "objeto": "llama.cpp"},
     "Cognia | usa | llama.cpp"),
    # contratos <plan> | <firmas> | <ruta.py o codigo> | <asserts>
    ("contratos", {"plan": "sumar dos numeros", "design": "def suma(a, b)",
                   "codigo": "sol.py", "asserts": "assert suma(1, 2) == 3"},
     "sumar dos numeros | def suma(a, b) | sol.py | assert suma(1, 2) == 3"),
    # crear_herramienta <nombre> | <proposito> | <test_input> | <esperado>
    ("crear_herramienta", {"nombre": "rot13", "proposito": "cifra rot13",
                           "test_input": "abc", "resultado_esperado": "nop"},
     "rot13 | cifra rot13 | abc | nop"),
    # revertir_herramienta <nombre> | <version>
    ("revertir_herramienta", {"nombre": "rot13", "version": "0.1.0"},
     "rot13 | 0.1.0"),
    # plan [ver | crear <lista> | marcar <n> <estado>]
    ("plan", {"subcomando": "ver"}, "ver"),
    ("plan", {"subcomando": "crear", "pasos": "1. leer\n2. escribir"},
     "crear 1. leer\n2. escribir"),
    ("plan", {"subcomando": "marcar", "n": 2, "estado": "hecho"},
     "marcar 2 hecho"),
    # crear_flujo <descripcion>
    ("crear_flujo", {"descripcion": "bajar el csv y graficarlo"},
     "bajar el csv y graficarlo"),
    # ejecutar_flujo [nombre|ruta]
    ("ejecutar_flujo", {"flujo": "mi.flujo.json"}, "mi.flujo.json"),
    ("ejecutar_flujo", {}, ""),
]


@pytest.mark.parametrize("nombre,argumentos,esperado", CASOS,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(CASOS)])
def test_round_trip_args_legacy(nombre, argumentos, esperado):
    assert args_legacy(nombre, argumentos) == esperado


def test_hay_un_caso_por_tool_con_firma():
    """Una firma sin caso de round-trip es un armador sin verificar."""
    sin_caso = sorted(set(FIRMAS) - {c[0] for c in CASOS})
    assert sin_caso == [], sin_caso


# ── 4. Re-parseo con el codigo REAL de produccion ───────────────────────────

def test_reparseo_con_partir_real():
    """El separador de estas 4 es ESPACIO, no '|': lo decide tools._partir.

    Si un armador metiera un '|' (el reflejo natural en este modulo), _partir
    lo dejaria pegado al primer campo y la tool llamaria al MCP con basura.
    Se re-parte con la funcion de produccion, no con una copia."""
    from cognia.agent.tools import _partir

    owner, repo = _partir(args_legacy("docs_repo",
                                      {"owner": "psf", "repo": "requests"}), 2)
    assert (owner, repo) == ("psf", "requests")

    r, preg = _partir(args_legacy("preguntar_repo",
                                  {"repo": "psf/requests",
                                   "pregunta": "como se hace retry?"}), 2)
    assert (r, preg) == ("psf/requests", "como se hace retry?")

    nom, tema = _partir(args_legacy("docs_libreria",
                                    {"nombre": "fastapi",
                                     "tema": "dependencias y Depends"}), 2)
    assert (nom, tema) == ("fastapi", "dependencias y Depends")
    # sin tema: la tool cae a `tema or nombre`, y el 2o campo queda vacio
    assert _partir(args_legacy("docs_libreria", {"nombre": "polars"}), 2) \
        == ["polars", ""]

    o, rp, q = _partir(args_legacy("buscar_en_repo",
                                   {"owner": "psf", "repo": "requests",
                                    "query": "retry con backoff"}), 3)
    assert (o, rp, q) == ("psf", "requests", "retry con backoff")


def test_reparseo_de_las_separadas_por_pipe():
    """Mismos ``re.split`` que tools.py:1585/2093/2146/2177/1513."""
    # kg_agregar: split SIN maxsplit, exige exactamente 3
    partes = re.split(r"\s*\|\s*", args_legacy(
        "kg_agregar", {"sujeto": "Cognia", "relacion": "usa",
                       "objeto": "llama.cpp"}))
    assert partes == ["Cognia", "usa", "llama.cpp"]

    # contratos: maxsplit=3, el 4o campo (asserts) tolera '|' interno
    partes = re.split(r"\s*\|\s*", args_legacy(
        "contratos", {"plan": "p", "design": "def f(x)", "codigo": "s.py",
                      "asserts": "assert f(1) | True"}), maxsplit=3)
    assert partes == ["p", "def f(x)", "s.py", "assert f(1) | True"]

    # crear_herramienta: maxsplit=3, 4 partes no vacias
    partes = re.split(r"\s*\|\s*", args_legacy(
        "crear_herramienta", {"nombre": "rot13", "proposito": "cifra",
                              "test_input": "abc",
                              "resultado_esperado": "nop"}), maxsplit=3)
    assert partes == ["rot13", "cifra", "abc", "nop"]

    # revertir_herramienta: maxsplit=1
    partes = re.split(r"\s*\|\s*", args_legacy(
        "revertir_herramienta", {"nombre": "rot13", "version": "0.1.0"}),
        maxsplit=1)
    assert partes == ["rot13", "0.1.0"]

    # cuaderno: maxsplit=1, el texto se queda con el resto (incluidos '|')
    crudo = args_legacy("cuaderno", {"subcomando": "nota",
                                     "texto": "a | b | c"})
    partes = re.split(r"\s*\|\s*", crudo.strip(), maxsplit=1)
    assert partes == ["nota", "a | b | c"]
    # 'ver' sin texto: un solo trozo, subcomando limpio
    assert re.split(r"\s*\|\s*",
                    args_legacy("cuaderno", {"subcomando": "ver"}).strip(),
                    maxsplit=1) == ["ver"]


def test_reparseo_de_plan():
    """plan_artifact.py:138 -> split(None, 1); 'marcar' vuelve a partir."""
    sub, resto = (args_legacy("plan", {"subcomando": "crear",
                                       "pasos": "1. leer\n2. escribir"})
                  .strip().split(None, 1))
    assert sub == "crear"
    from cognia.agent.plan_artifact import parse_pasos
    assert parse_pasos(resto) == ["leer", "escribir"]

    sub, resto = args_legacy(
        "plan", {"subcomando": "marcar", "n": 2, "estado": "hecho"}
    ).strip().split(None, 1)
    assert sub == "marcar"
    mp = resto.split(None, 1)
    assert mp[0].isdigit() and mp == ["2", "hecho"]

    # 'ver' sin resto: split devuelve un solo trozo (la tool cae al default)
    assert args_legacy("plan", {"subcomando": "ver"}).strip().split(None, 1) \
        == ["ver"]


def test_args_pelado_sigue_pasando_derecho():
    """REGRESION de este mismo cambio: al tipar las 16, el armador se comia el
    passthrough de ``{"args": "<string de siempre>"}``.

    Un modelo que no leyo el schema (o un llamador legacy: el protocolo texto
    lleva anios mandando el string crudo) manda 'args' pelado. Antes de A4 eso
    funcionaba; con la firma nueva el armador no encontraba ninguna propiedad y
    devolvia '' — la tool se quedaba SIN argumentos, que es peor que
    equivocarse porque ni puede explicar que falto. Lo detecto
    tests/test_agente_nativo.py::test_args_legacy_reconstruye_formato_pipe."""
    assert args_legacy("cuaderno", {"args": "consultar tema"}) == "consultar tema"
    assert args_legacy("kg_agregar", {"args": "a | usa | b"}) == "a | usa | b"
    # pero si vienen las propiedades declaradas, MANDA la firma (aunque el
    # modelo mande 'args' de yapa)
    assert args_legacy("cuaderno", {"subcomando": "nota", "texto": "x",
                                    "args": "basura"}) == "nota | x"


def test_armador_tolera_dict_incompleto():
    """args_legacy es tolerante por diseno: nunca lanza, deja que la tool
    reporte el error de formato (ese error vuelve al modelo como turno tool).

    Vale para TODAS las firmas: el modelo improvisa nombres de argumento.
    OJO: esto solo fija que no LANZA. Que el contenido no se pierda lo fija
    ``test_nombres_improvisados_no_dan_llamada_vacia`` — este test pasaba
    igual con el agujero abierto (devolvia ' |  | ', que es un str)."""
    for nombre in FIRMAS:
        assert isinstance(args_legacy(nombre, {}), str), nombre
        assert isinstance(args_legacy(nombre, {"zaraza": 1}), str), nombre


def test_nombres_improvisados_no_dan_llamada_vacia():
    """REGRESION medida el 2026-08-13 por el verificador adversarial.

    La rama de FIRMAS devolvia el armado AUNQUE saliera vacio, saltandose el
    ``' | '.join`` final. Cuando el modelo improvisa los nombres de las claves
    (le pasa con schemas que no leyo del todo), el armador solo encuentra
    defaults vacios y publica el ESQUELETO del formato: kg_agregar daba
    'a | usa | b' antes de A4 y paso a ' |  | '; code_grafo daba 'cognia.cli'
    y paso a ''. Es el MISMO modo de fallo que la rama de params ya guardaba
    en tool_schemas.py:394 (y que fija
    test_harness_schemas_nativos::test_argumentos_con_nombres_inventados_
    no_dan_llamada_vacia para ``borrar_archivo``): una tool sin argumentos ni
    siquiera puede explicar que falto."""
    # los tres casos EXACTOS que midio el verificador
    assert args_legacy("kg_agregar", {"subject": "a", "relation": "usa",
                                      "object": "b"}) == "a | usa | b"
    assert args_legacy("code_grafo", {"modulo": "cognia.cli"}) == "cognia.cli"
    assert args_legacy("contratos", {"p": "x", "d": "y", "c": "z",
                                     "a": "w"}) == "x | y | z | w"


def test_ninguna_firma_se_traga_el_unico_valor():
    """La trampa general de lo de arriba, para las 16 (y las que vengan).

    Si el modelo manda UN solo par con la clave equivocada, ese valor tiene
    que llegar a la tool por el join de ultimo recurso.
    'plan' queda fuera a proposito: su armador tiene un default LEGITIMO
    ('ver' es el subcomando por defecto documentado), asi que gana el armado
    y no cae al join. Es el comportamiento previo a A4 tambien."""
    for nombre in FIRMAS:
        if nombre == "plan":
            continue
        assert args_legacy(nombre, {"clave_inventada": "VALOR"}) == "VALOR", (
            f"{nombre} se comio el valor: el armador salio vacio y no cayo al "
            "join de tool_schemas.py:400")
