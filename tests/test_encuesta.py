# -*- coding: utf-8 -*-
"""Tests de las encuestas contextuales (cognia/harness/encuesta.py).

Sin red y sin backend: `preparar()` recibe siempre `generar_fn` inyectado, que
es el punto de inyeccion que el propio modulo expone. Si algun test llega a la
red, es un bug del modulo (o del test).

El nucleo de lo que se prueba aqui no es el camino feliz sino la desconfianza:
la salida del modelo se sanea, la del usuario se respeta al pie de la letra
(saltar una pregunta no es lo mismo que descartar todas sus opciones) y
ninguna de las dos puede romper el turno.
"""
import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from cognia.harness import encuesta as en  # noqa: E402


def _generador(salida):
    """generar_fn que devuelve `salida` y guarda con que se le llamo."""
    llamadas = []

    def _fn(prompt, system):
        llamadas.append((prompt, system))
        return salida

    _fn.llamadas = llamadas
    return _fn


def _explota(exc):
    def _fn(prompt, system):
        raise exc
    return _fn


FALTANTES = [{"id": "stack", "tipo": "unica",
              "pregunta": "Con que tecnologia lo hacemos",
              "opciones": ["HTML y JS", "React", "Python"]},
             {"id": "alcance", "tipo": "abierta",
              "pregunta": "Que tiene que hacer"}]


# --------------------------------------------------------------- vale_la_pena

def test_vale_la_pena_texto_vacio():
    ok, motivo = en.vale_la_pena("")
    assert ok is False and motivo == "texto vacio"
    assert en.vale_la_pena("     ")[0] is False
    assert en.vale_la_pena(None)[0] is False


def test_vale_la_pena_comando_no_se_encuesta():
    # Un comando lo interpreta el CLI: preguntarle al usuario por el es ruido.
    assert en.vale_la_pena("/hacer un servidor")[0] is False
    assert en.vale_la_pena("!ls -la")[0] is False
    assert "comando" in en.vale_la_pena("/hacer un servidor")[1]


def test_vale_la_pena_pedido_largo_no_se_encuesta():
    largo = "quiero una web " + "x" * en.MAX_CHARS_PARA_PREGUNTAR
    ok, motivo = en.vale_la_pena(largo)
    assert ok is False and "largo" in motivo
    assert en.vale_la_pena("y" * (en.MAX_CHARS_PARA_PREGUNTAR - 1))[0] is True


def test_vale_la_pena_faltantes_vacios_no_se_encuesta():
    # faltantes=[] es "la semilla miro y no hay huecos"; faltantes=None es
    # "nadie miro". Solo la primera cierra la encuesta.
    ok, motivo = en.vale_la_pena("hazme una pagina web", faltantes=[])
    assert ok is False and "sin tomar" in motivo
    assert en.vale_la_pena("hazme una pagina web", faltantes=None)[0] is True


def test_vale_la_pena_pedido_corto_y_vago():
    ok, motivo = en.vale_la_pena("hazme una pagina web")
    assert ok is True and motivo == ""


# --------------------------------------------------------------- _extraer_json

def test_extraer_json_con_prosa_alrededor():
    bruto = ('Claro, aqui van las preguntas:\n'
             '{"preguntas": [{"id": "stack", "tipo": "abierta", '
             '"texto": "Con que lo hacemos"}]}\n'
             'Espero que te sirvan.')
    assert en._extraer_json(bruto)["preguntas"][0]["id"] == "stack"


def test_extraer_json_con_vallas_de_codigo():
    bruto = '```json\n{"preguntas": [], "nota": "nada"}\n```'
    assert en._extraer_json(bruto) == {"preguntas": [], "nota": "nada"}


def test_extraer_json_con_razonamiento_delante():
    # Los razonadores emiten <think> aunque se les apague.
    bruto = ('<think>El usuario no dijo el stack, pregunto por eso.</think>\n'
             '{"preguntas": [{"id": "a", "texto": "x"}]}')
    assert en._extraer_json(bruto)["preguntas"][0]["id"] == "a"


def test_extraer_json_con_basura():
    assert en._extraer_json("no tengo ni idea, lo siento") == {}
    assert en._extraer_json("") == {}
    assert en._extraer_json(None) == {}
    assert en._extraer_json('{"preguntas": [') == {}       # nunca cierra
    assert en._extraer_json("{esto no es json}") == {}     # cierra pero rompe


def test_extraer_json_dos_objetos_devuelve_solo_el_primero():
    # El cierre equilibrado existe justo por esto: un rfind('}') se tragaria
    # los dos objetos y json.loads devolveria {}.
    bruto = ('{"preguntas": [{"id": "a", "texto": "x"}]}\n'
             '{"preguntas": [{"id": "b", "texto": "y"}]}')
    salida = en._extraer_json(bruto)
    assert [p["id"] for p in salida["preguntas"]] == ["a"]


# ----------------------------------------------------------- sanear_preguntas

def test_sanear_forma_invalida():
    assert en.sanear_preguntas(None)[0] == []
    assert "objeto JSON" in en.sanear_preguntas("hola")[1]
    assert "clave" in en.sanear_preguntas({"otra": 1})[1]
    assert "no es una lista" in en.sanear_preguntas({"preguntas": "una"})[1]
    assert "no falta nada" in en.sanear_preguntas({"preguntas": []})[1]


def test_sanear_recorta_a_max_preguntas():
    crudo = {"preguntas": [{"id": "p%d" % i, "tipo": "abierta",
                            "texto": "pregunta numero %d" % i}
                           for i in range(6)]}
    preguntas, motivo = en.sanear_preguntas(crudo)
    assert motivo == ""
    assert len(preguntas) == en.MAX_PREGUNTAS
    # Se queda con las primeras, que es el orden de importancia del modelo.
    assert [p.id for p in preguntas] == ["p0", "p1", "p2"]


def test_sanear_tipo_inventado_degrada_a_abierta():
    # Perder la pregunta seria peor que perder el selector.
    crudo = {"preguntas": [{"id": "prio", "tipo": "ranking",
                            "texto": "Ordena estas cosas",
                            "opciones": ["velocidad", "coste"]}]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert len(preguntas) == 1
    assert preguntas[0].tipo == "abierta"
    assert preguntas[0].opciones == []


def test_sanear_cerrada_con_una_opcion_degrada_a_abierta():
    crudo = {"preguntas": [{"id": "stack", "tipo": "unica",
                            "texto": "Con que lo montamos",
                            "opciones": ["React"]}]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert preguntas[0].tipo == "abierta"
    assert preguntas[0].opciones == []


def test_sanear_quita_opciones_duplicadas_conservando_orden():
    crudo = {"preguntas": [{"id": "stack", "tipo": "unica",
                            "texto": "Con que lo montamos",
                            "opciones": ["React", "Vuejs", "React", "Svelte",
                                         "", None, "Vuejs"]}]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert preguntas[0].opciones == ["React", "Vuejs", "Svelte"]


def test_sanear_recorta_a_max_opciones():
    crudo = {"preguntas": [{"id": "stack", "tipo": "unica",
                            "texto": "Con que lo montamos",
                            "opciones": ["opcion%d" % i for i in range(9)]}]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert len(preguntas[0].opciones) == en.MAX_OPCIONES
    assert preguntas[0].opciones[0] == "opcion0"


def test_sanear_descarta_duplicadas_por_id():
    crudo = {"preguntas": [
        {"id": "stack", "tipo": "abierta", "texto": "Con que lo montamos"},
        {"id": "stack", "tipo": "abierta", "texto": "Y de fondo que usamos"},
        {"id": "plazo", "tipo": "abierta", "texto": "Para cuando lo quieres"}]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert [p.id for p in preguntas] == ["stack", "plazo"]


def test_sanear_descarta_texto_vacio_o_kilometrico():
    crudo = {"preguntas": [{"id": "a", "tipo": "abierta", "texto": "   "},
                           {"id": "b", "tipo": "abierta", "texto": "z" * 200},
                           {"id": "c", "tipo": "abierta", "texto": "vale esta"},
                           "no soy un dict"]}
    preguntas, _ = en.sanear_preguntas(crudo)
    assert [p.id for p in preguntas] == ["c"]


def test_sanear_sin_supervivientes_da_motivo():
    crudo = {"preguntas": [{"id": "a", "tipo": "abierta", "texto": ""}]}
    preguntas, motivo = en.sanear_preguntas(crudo)
    assert preguntas == [] and "filtros" in motivo


# -------------------------------------------------------------- _ya_respondida

def test_ya_respondida_por_el_enunciado():
    heno = "quiero desplegar el proyecto en railway"
    assert en._ya_respondida("Donde quieres desplegar el proyecto", [], heno)
    # Una sola palabra en comun no basta: el umbral es 2 y el 60%.
    assert not en._ya_respondida("Que presupuesto tiene el proyecto", [], heno)


def test_ya_respondida_por_una_opcion_en_el_contexto():
    # "Con que tecnologia" es generico, pero si React ya salio, sobra.
    heno = "el usuario ya monto el front con react"
    assert en._ya_respondida("Con que tecnologia lo hacemos",
                             ["Python", "React", "Otra cosa"], heno)


def test_sanear_descarta_la_pregunta_que_el_contexto_ya_contesta():
    crudo = {"preguntas": [
        {"id": "stack", "tipo": "unica", "texto": "Con que tecnologia",
         "opciones": ["React", "Python", "Rust"]},
        {"id": "alcance", "tipo": "abierta", "texto": "Cuantas pantallas"}]}
    preguntas, _ = en.sanear_preguntas(
        crudo, texto="hazme el panel",
        contexto="el usuario trabaja con React desde hace meses")
    assert [p.id for p in preguntas] == ["alcance"]


def test_sanear_ignora_tildes_al_comparar():
    # El contexto llega tal cual lo tecleo el usuario, con acentos.
    crudo = {"preguntas": [{"id": "stack", "tipo": "unica",
                            "texto": "Con que tecnologia",
                            "opciones": ["Python", "Rust"]}]}
    preguntas, _ = en.sanear_preguntas(
        crudo, contexto="el proyecto está escrito en Pythón")
    assert preguntas == []


# ------------------------------------------------------------------- preparar

def test_preparar_json_bueno_da_origen_modelo():
    gen = _generador('{"preguntas": [{"id": "uso", "tipo": "unica", '
                     '"texto": "Para que va a servir", '
                     '"opciones": ["Uso propio", "Un cliente"], '
                     '"porque": "cambia el alcance"}]}')
    enc = en.preparar("hazme una pagina web", generar_fn=gen)
    assert enc.ok is True
    assert enc.origen == "modelo"
    assert enc.motivo == "ok"
    assert [p.id for p in enc.preguntas] == ["uso"]
    assert enc.preguntas[0].opciones == ["Uso propio", "Un cliente"]
    assert enc.ms >= 0


def test_preparar_pasa_contexto_y_semilla_al_generador():
    gen = _generador('{"preguntas": []}')
    en.preparar("hazme una pagina web", contexto="ayer hablamos del blog",
                faltantes=FALTANTES, generar_fn=gen)
    prompt, system = gen.llamadas[0]
    assert "ayer hablamos del blog" in prompt
    assert "Con que tecnologia lo hacemos" in prompt   # la semilla, como pista
    assert "hazme una pagina web" in prompt
    assert "JSON" in system


def test_preparar_oserror_cae_a_la_semilla():
    # socket.timeout ES OSError: es el caso comun del backend saturado.
    enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                      generar_fn=_explota(OSError("conexion rechazada")))
    assert enc.ok is True
    assert enc.origen == "semilla"
    assert "timeout o red" in enc.motivo
    assert [p.id for p in enc.preguntas] == ["stack", "alcance"]


def test_preparar_basura_cae_a_la_semilla():
    enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                      generar_fn=_generador("pues no se, dime tu"))
    assert enc.ok is True
    assert enc.origen == "semilla"
    assert enc.preguntas[0].texto == "Con que tecnologia lo hacemos"


def test_preparar_sin_preguntas_no_cae_a_la_semilla():
    # Cero preguntas es la RESPUESTA a un pedido claro, no un fallo: si aqui
    # se cayera a la semilla, el modelo con el contexto delante quedaria
    # sobrescrito por una tabla de decisiones tipicas.
    enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                      generar_fn=_generador('{"preguntas": []}'))
    assert enc.ok is False
    assert enc.preguntas == []
    assert enc.origen == ""
    assert enc.motivo == "el modelo dice que no falta nada"


def test_preparar_no_vale_la_pena_no_llama_al_modelo():
    gen = _generador('{"preguntas": [{"id": "a", "texto": "x"}]}')
    enc = en.preparar("/hacer un servidor", generar_fn=gen)
    assert enc.ok is False and enc.origen == "" and gen.llamadas == []


def test_preparar_respeta_max_preguntas():
    crudo = ('{"preguntas": [{"id": "a", "texto": "primera cosa"}, '
             '{"id": "b", "texto": "segunda cosa"}]}')
    enc = en.preparar("hazme una pagina web", max_preguntas=1,
                      generar_fn=_generador(crudo))
    assert [p.id for p in enc.preguntas] == ["a"]


def test_preparar_nunca_lanza():
    # El contrato es que una encuesta jamas rompe el turno, pase lo que pase
    # con el generador inyectado.
    casos = [_explota(RuntimeError("boom")),
             _explota(KeyError("choices")),
             _explota(TimeoutError("tarde")),
             _generador(None),
             _generador(12345),                 # un generar_fn ajeno miente
             _generador({"preguntas": []})]
    for gen in casos:
        enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                          generar_fn=gen)
        assert isinstance(enc, en.Encuesta)
        assert enc.motivo


def test_preparar_generador_que_no_devuelve_texto():
    # Regresion: el saneo corre FUERA del try, asi que un generar_fn que
    # devuelve algo que no es texto reventaba el turno con AttributeError en
    # vez de caer a la semilla.
    for salida in (None, 12345, {"preguntas": []}, ["a"]):
        enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                          generar_fn=_generador(salida))
        assert enc.origen == "semilla"
        assert enc.motivo == "el backend no devolvio texto"
        assert [p.id for p in enc.preguntas] == ["stack", "alcance"]


def test_preparar_devuelve_dict_serializable():
    enc = en.preparar("hazme una pagina web", faltantes=FALTANTES,
                      generar_fn=_explota(OSError("no hay backend")))
    d = enc.a_dict()
    assert set(d) == {"ok", "preguntas", "motivo", "origen", "modelo", "ms",
                      "aviso"}
    assert d["preguntas"][0]["tipo"] == "unica"


# ----------------------------------------------------------------- incorporar

def _p(texto, opciones=None):
    return en.Pregunta(id="x", tipo="unica" if opciones else "abierta",
                       texto=texto, opciones=opciones or [])


def test_incorporar_saltada_no_aparece():
    # None es "la salte": atribuirle algo al usuario seria inventar.
    base = "hazme una pagina web"
    salida = en.incorporar(base, [(_p("Para que va a servir"), None)])
    assert salida == base


def test_incorporar_vacio_no_aparece():
    base = "hazme una pagina web"
    salida = en.incorporar(base, [(_p("Para que va a servir"), "   ")])
    assert salida == base


def test_incorporar_lista_vacia_con_opciones_si_aparece():
    # Descartar todas las opciones es informacion util, no es no contestar.
    pregunta = _p("Con que tecnologia?", ["React", "Vue", "Python"])
    salida = en.incorporar("hazme una pagina web", [(pregunta, [])])
    assert "ninguna de" in salida
    assert "React, Vue, Python" in salida
    assert "Detalles que el usuario aclaro" in salida


def test_incorporar_lista_vacia_sin_opciones_no_aparece():
    # Sin opciones que descartar, la lista vacia no dice nada.
    base = "hazme una pagina web"
    assert en.incorporar(base, [(_p("Que quieres"), [])]) == base


def test_incorporar_sin_respuestas_utiles_devuelve_el_texto_tal_cual():
    base = "  hazme una pagina web  "
    salida = en.incorporar(base, [(_p("Para que"), None),
                                  (_p("Y esto"), ""),
                                  (_p("Y lo otro"), [])])
    assert salida == "hazme una pagina web"
    assert "Detalles" not in salida
    assert en.incorporar(base, []) == "hazme una pagina web"
    assert en.incorporar(base, None) == "hazme una pagina web"


def test_incorporar_mezcla_respuestas():
    respuestas = [(_p("Para que va a servir?"), "para mi portfolio"),
                  (_p("Con que tecnologia?", ["React", "Vue"]), ["React"]),
                  (_p("Plazo?"), None),
                  (_p("Que secciones?", ["Blog", "Contacto"]), [])]
    salida = en.incorporar("hazme una pagina web", respuestas)
    lineas = salida.splitlines()
    assert lineas[0] == "hazme una pagina web"
    assert "- Para que va a servir: para mi portfolio" in lineas
    assert "- Con que tecnologia: React" in lineas
    assert "- Que secciones: ninguna de Blog, Contacto" in lineas
    assert "Plazo" not in salida


def test_incorporar_multiple_une_los_valores():
    pregunta = _p("Que secciones?", ["Blog", "Contacto", "Tienda"])
    salida = en.incorporar("hazme una web", [(pregunta, ["Blog", "Tienda"])])
    assert "- Que secciones: Blog, Tienda" in salida


def test_incorporar_pregunta_que_es_un_string():
    # El cableador puede pasar el enunciado pelado; no hay motivo para romper.
    salida = en.incorporar("hazme una web", [("Para que:", "para aprender")])
    assert "- Para que: para aprender" in salida


# ---------------------------------------------------------- contrato de pureza

def test_el_modulo_no_importa_el_cli():
    # PURO significa que se puede importar sin arrastrar el REPL: un import
    # del CLI aqui crearia un ciclo y ademas invitaria a imprimir.
    fuente = inspect.getsource(en)
    assert "import cognia.cli" not in fuente
    assert "from cognia import cli" not in fuente
    assert "from cognia.cli" not in fuente
    # Ni escondido dentro de una funcion: se mira el arbol, no solo el texto.
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            assert all(not a.name.startswith("cognia.cli") for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            assert (nodo.module or "") != "cognia.cli"


def test_el_modulo_no_imprime():
    # La otra mitad del contrato PURO: quien lo cablea decide como se muestra.
    fuente = inspect.getsource(en)
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            assert nodo.func.id != "print"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
