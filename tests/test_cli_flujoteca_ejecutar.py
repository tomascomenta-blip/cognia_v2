# -*- coding: utf-8 -*-
"""
tests/test_cli_flujoteca_ejecutar.py
===================================
`/flujoteca ejecutar <nombre> [prompt]` -- la puerta del CLI para CORRER un
flujo (PEDIDO 4 del plan 4.14.0).

POR QUE ESTE FICHERO EXISTE, y por que casi todo lo de aqui mira el DISCO.
La razon por la que "los workflows no entregan nada al final ni hacen nada en
mi PC" llego a produccion con 288 tests en verde es que TODOS los tests de
flujos usaban un `run_tool` falso que aceptaba cualquier cadena y ninguno
miraba el disco. Aqui la regla es la contraria:

  * el test que manda (`test_ejecutar_escribe_el_fichero_con_el_prompt`) va
    POR LA PUERTA DEL PRODUCTO (`cli._slash_flujoteca("ejecutar ...", ai)`),
    con el REGISTRO REAL de tools, y afirma sobre un fichero que EXISTE EN
    DISCO con el contenido del prompt;
  * la denegacion de permiso se prueba con el gate REAL de `borrar_archivo`
    (fichero fuera del workspace), no con un mock del mensaje;
  * los tests que leen texto impreso son red SECUNDARIA de esos dos.

Lo que se fija:
  1. los cuatro casos medidos de `_flujoteca_partir_nombre` (el subcomando no
     se vuelve un flujo fantasma; un nombre de dos palabras SIN prompt se
     resuelve; con prompt tambien; y un flujo llamado "editor de textos" no
     se come el subcomando);
  2. el fichero en disco con el contenido del prompt del CLI;
  3. el ctx que recibe el registro trae `confirm`, `_cancelado` y `_run_agent`
     (sin ellos, medido: las tools destructivas corren sin pedir permiso y un
     nodo `delegar_subtarea` contesta "delegacion no disponible");
  4. un `confirm` que DENIEGA imprime el motivo y el flujo sigue (nunca mudo,
     nunca bloqueado en silencio);
  5. `prompt_fijo` + argumento: avisa en amarillo y corre con la CONSTANTE;
  6. `prompt` variable sin argumento: corre con el default del nodo;
  7. un flujo VIEJO sin nodo de entrada corre igual y sugiere el arreglo;
  8. la salida trae el ENTREGABLE, la lista de FICHEROS y la raiz;
  9. el autocompletado de `/flujoteca ` no lista la biblioteca por pulsacion.

La seccion 8 del fichero recoge los cableados HERMANOS de la misma obra que
viven en `cognia/cli.py` y no tienen otro fichero de test propio: el comando
`/enrutador` (con su contexto acotado), el aviso de `sin_efecto` en
`/workflow` y el contrato de `/hacer` derivado AL ARRANCAR. Estan aqui porque
`cli.py` tiene un solo dueno y sus tests tambien.
"""

import os

import pytest

import cognia.cli as cli
from cognia.agent import flujoteca as ft


# ---------------------------------------------------------------------------
# Entorno: flujoteca, workspace del agente y cwd TEMPORALES
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    """Biblioteca y workspace en tmp_path. `COGNIA_AGENT_WORKSPACE` es lo que
    lee `dev_tools._root_actual()`, o sea DONDE escriben de verdad las tools:
    sin fijarlo, un test que escribe ficheros ensuciaria el repo."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(ws))
    monkeypatch.setenv("COGNIA_EFIMERO", "1")
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    monkeypatch.chdir(ws)
    cli._flujoteca_invalidar_completar()
    return tmp_path


@pytest.fixture
def salida(monkeypatch):
    """Todo lo que el comando imprime, en una lista de lineas."""
    lineas = []
    monkeypatch.setattr(cli, "_print_line",
                        lambda s, *a, **k: lineas.append(str(s)))
    monkeypatch.setattr(cli, "_show_response",
                        lambda t, *a, **k: lineas.append("RESP:" + str(t)))
    return lineas


def _guardar(nombre, nodos, **kw):
    return ft.guardar({"nombre": nombre, "nodos": nodos}, nombre=nombre,
                      nota="test", **kw)


def _escribe(prompt_args="", tool_entrada="prompt", fichero="nota.txt"):
    """Flujo de dos nodos: ENTRADA -> escribir_archivo con {{prompt}}."""
    return [
        {"id": "prompt", "tool": tool_entrada, "args": prompt_args,
         "wires": ["esc"]},
        {"id": "esc", "tool": "escribir_archivo",
         "args": f"{fichero} | {{{{prompt}}}}", "wires": []},
    ]


# ---------------------------------------------------------------------------
# 1. _flujoteca_partir_nombre -- los cuatro casos MEDIDOS
# ---------------------------------------------------------------------------

def test_un_subcomando_no_se_vuelve_un_flujo_fantasma():
    """"ejecutar" esta en `_FLUJOTECA_SUBCOMANDOS`, asi que el reparto simple
    no puede devolverlo como nombre de flujo.

    Medido ANTES del arreglo: `_flujoteca_partir_nombre("ejecutar pvz1 hola")`
    devolvia ('ejecutar', 'pvz1 hola') -- se inventaba un flujo llamado
    "ejecutar" y le mandaba la instruccion."""
    assert "ejecutar" in cli._FLUJOTECA_SUBCOMANDOS
    assert "correr" in cli._FLUJOTECA_SUBCOMANDOS
    _guardar("pvz1", _escribe())
    assert cli._flujoteca_partir_nombre("ejecutar pvz1 hola") == ("", "")


def test_el_texto_entero_es_un_nombre_de_dos_palabras():
    """Segundo agujero medido: `/flujoteca ejecutar Informe semanal` -- nombre
    de DOS palabras y sin prompt -- devolvia ('', '') y el CLI contestaba "no
    encuentro ningun flujo" sobre un flujo que SI existe."""
    _guardar("Informe semanal", _escribe())
    assert cli._flujoteca_partir_nombre("Informe semanal") == (
        "Informe semanal", "")


def test_nombre_de_dos_palabras_con_prompt_detras():
    _guardar("Informe semanal", _escribe())
    assert cli._flujoteca_partir_nombre("Informe semanal de ventas") == (
        "Informe semanal", "de ventas")


def test_un_flujo_llamado_editor_de_textos_no_se_come_el_subcomando():
    """El nombre REAL mas largo gana sobre el reparto por el primer hueco,
    pero un subcomando sin flujo homonimo no se inventa nada."""
    _guardar("editor de textos", _escribe())
    assert cli._flujoteca_partir_nombre("editor de textos ponle color") == (
        "editor de textos", "ponle color")
    assert cli._flujoteca_partir_nombre("editar cosa que no existe") == ("", "")


# ---------------------------------------------------------------------------
# 2. EL TEST QUE MANDA: el fichero existe en disco con el prompt del CLI
# ---------------------------------------------------------------------------

def test_ejecutar_escribe_el_fichero_con_el_prompt(entorno, salida):
    """Por la PUERTA DEL PRODUCTO, con el registro REAL de tools, y se mira
    EL DISCO. Este es el test que la casa no tenia."""
    _guardar("crear nota", _escribe(prompt_args="por defecto"))
    destino = entorno / "ws" / "nota.txt"
    assert not destino.exists()

    cli._slash_flujoteca("ejecutar crear nota hola mundo", None)

    assert destino.exists(), "\n".join(salida)
    assert destino.read_text(encoding="utf-8") == "hola mundo"


def test_correr_es_el_mismo_comando(entorno):
    _guardar("crear nota", _escribe(prompt_args="por defecto"))
    cli._slash_flujoteca("correr crear nota via correr", None)
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "via correr"


# ---------------------------------------------------------------------------
# 2b. LAS COMILLAS QUE EL DUENO TECLEA no acaban dentro del fichero
# ---------------------------------------------------------------------------

def test_las_comillas_tecleadas_no_acaban_dentro_del_fichero(entorno, salida):
    """El comando EXACTO del pedido del dueno, con las comillas puestas.

    MEDIDO antes del arreglo: `nivel.txt` quedaba con
    `'"un nivel con zombis nuevos"'` -- comillas incluidas. Sin comillas
    salia limpio. Importa porque el dueno escribio ese comando CON comillas
    en su propio pedido: es exactamente como lo va a teclear, y en el REPL no
    hay shell que se las quite."""
    _guardar("pvz1", _escribe(prompt_args="por defecto", fichero="nivel.txt"))

    cli._slash_flujoteca(
        'ejecutar pvz1 "un nivel con zombis nuevos"', None)

    destino = entorno / "ws" / "nivel.txt"
    assert destino.exists(), "\n".join(salida)
    assert destino.read_text(encoding="utf-8") == "un nivel con zombis nuevos"


def test_comillas_simples_igual_y_sin_comillas_sigue_limpio(entorno):
    _guardar("pvz1", _escribe(prompt_args="", fichero="nivel.txt"))
    destino = entorno / "ws" / "nivel.txt"

    cli._slash_flujoteca("ejecutar pvz1 'con comillas simples'", None)
    assert destino.read_text(encoding="utf-8") == "con comillas simples"

    cli._slash_flujoteca("ejecutar pvz1 sin comillas ningunas", None)
    assert destino.read_text(encoding="utf-8") == "sin comillas ningunas"


def test_una_comilla_suelta_y_las_interiores_se_respetan(entorno):
    """Solo se quita UN par que envuelva el argumento ENTERO. Un lado suelto
    no es un par, y las comillas de dentro son del texto del dueno."""
    _guardar("pvz1", _escribe(prompt_args="", fichero="nivel.txt"))
    destino = entorno / "ws" / "nivel.txt"

    cli._slash_flujoteca("ejecutar pvz1 dile 'hola' al usuario", None)
    assert destino.read_text(encoding="utf-8") == "dile 'hola' al usuario"

    cli._slash_flujoteca('ejecutar pvz1 "solo abre la comilla', None)
    assert destino.read_text(encoding="utf-8") == '"solo abre la comilla'


@pytest.mark.parametrize("entrada,esperado", [
    ('"un nivel con zombis nuevos"', "un nivel con zombis nuevos"),
    ("'un nivel con zombis nuevos'", "un nivel con zombis nuevos"),
    ("un nivel con zombis nuevos", "un nivel con zombis nuevos"),
    ('"un nivel a medias', '"un nivel a medias'),
    ('un nivel a medias"', 'un nivel a medias"'),
    ("dile 'hola' al usuario", "dile 'hola' al usuario"),
    ('"dile \'hola\' al usuario"', "dile 'hola' al usuario"),
    ('"a" y "b"', '"a" y "b"'),          # abre y cierra, pero no es UN par
    ('"', '"'),                          # una sola comilla no es un par
    ('""', ""),
    ("", ""),
])
def test_quitar_comillas_envolventes(entrada, esperado):
    assert cli._quitar_comillas_envolventes(entrada) == esperado


def test_la_salida_trae_el_entregable_los_ficheros_y_la_raiz(entorno, salida):
    """Literalmente lo que el dueno echa en falta: que diga QUE produjo,
    DONDE esta y en que raiz."""
    _guardar("crear nota", _escribe(prompt_args=""))
    cli._slash_flujoteca("ejecutar crear nota contenido medible", None)
    texto = "\n".join(salida)
    assert "RESP:" in texto                       # el entregable, entero
    assert "Ficheros: nota.txt" in texto
    assert str(entorno / "ws") in texto           # la raiz donde se escribio


# ---------------------------------------------------------------------------
# 3. El ctx: confirm, _cancelado y _run_agent llegan al registro
# ---------------------------------------------------------------------------

def test_el_ctx_de_flujos_trae_confirm_cancelado_y_run_agent():
    """`_ctx_agente` es la fabrica unica. Sin estas tres claves, medido: las
    tools destructivas corren sin pedir permiso, Ctrl-C no corta nada y un
    nodo `delegar_subtarea` (que ESTA en la paleta del editor) contesta
    "delegacion no disponible en este contexto"."""
    ctx = cli._ctx_agente(None, cli._print_line)
    assert ctx["confirm"] is cli._confirmar_accion
    assert ctx["_cancelado"] is cli._corte_pedido
    assert callable(ctx["_run_agent"])
    assert ctx["_delegation_max"] == cli._DELEGACION_MAX_DEFECTO
    assert ctx["_delegation_depth"] == 0
    assert ctx["_steps_remaining"] == 8


def test_ctx_tools_hereda_la_fabrica():
    """El ctx PELADO de `_ctx_tools` era el agujero: se lo comian todas las
    tools llamadas fuera del bucle del agente."""
    ctx = cli._ctx_tools(None)
    assert ctx["confirm"] is cli._confirmar_accion
    assert callable(ctx["_run_agent"])
    assert ctx["show_diff"] is False        # el pelado no pinta diffs


def test_el_ctx_llega_de_verdad_al_registro_de_tools(entorno, salida,
                                                     monkeypatch):
    """No basta con que la fabrica lo construya: tiene que LLEGAR. Se mide
    con el gate REAL de `borrar_archivo` sobre un fichero de FUERA del
    workspace, que es una de las dos ramas que consultan ctx['confirm']."""
    afuera = entorno / "afuera"
    afuera.mkdir()
    ajeno = afuera / "ajeno.txt"
    ajeno.write_text("no me borres", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(cli, "_confirmar_accion",
                        lambda kind, detalle: vistos.append(kind) or False)

    _guardar("limpiar fuera", [{"id": "del", "tool": "borrar_archivo",
                                "args": str(ajeno), "wires": []}])
    cli._slash_flujoteca("ejecutar limpiar fuera", None)

    assert vistos == ["borrado_fuera_del_workspace"], "\n".join(salida)
    assert ajeno.exists(), "el gate dijo NO y el fichero se borro igual"


def test_un_nodo_denegado_imprime_el_motivo_y_el_flujo_sigue(entorno, salida,
                                                             monkeypatch):
    """Cablear `confirm` sin decir nada convertiria "no hacen nada" en "se
    bloquean" -- y un nodo denegado devuelve TEXTO sin la palabra ERROR, asi
    que el motor lo cuenta como salida OK y se iria en silencio."""
    afuera = entorno / "afuera"
    afuera.mkdir()
    ajeno = afuera / "ajeno.txt"
    ajeno.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "_confirmar_accion", lambda kind, detalle: False)

    _guardar("dos pasos", [
        {"id": "del", "tool": "borrar_archivo", "args": str(ajeno),
         "wires": ["esc"]},
        {"id": "esc", "tool": "escribir_archivo", "args": "sigue.txt | ok",
         "wires": []},
    ])
    cli._slash_flujoteca("ejecutar dos pasos", None)

    texto = "\n".join(salida)
    assert "sin permiso" in texto, texto
    assert "del" in texto
    assert "/modo-permiso" in texto
    # ...y el flujo SIGUIO: el nodo de despues corrio igual.
    assert (entorno / "ws" / "sigue.txt").exists(), texto


# ---------------------------------------------------------------------------
# 4. La semantica del prompt ("que el prompt sea opcional")
# ---------------------------------------------------------------------------

def test_prompt_fijo_con_argumento_avisa_y_usa_la_constante(entorno, salida):
    """Ni lo ignora en silencio ni aborta: corre con la constante y lo dice."""
    _guardar("fijo", _escribe(prompt_args="LA CONSTANTE",
                              tool_entrada="prompt_fijo"))
    cli._slash_flujoteca("ejecutar fijo esto se ignora", None)

    texto = "\n".join(salida)
    assert "[warn_cl]" in texto and "FIJO" in texto, texto
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "LA CONSTANTE"


def test_prompt_fijo_sin_argumento_no_avisa_de_nada(entorno, salida):
    _guardar("fijo", _escribe(prompt_args="LA CONSTANTE",
                              tool_entrada="prompt_fijo"))
    cli._slash_flujoteca("ejecutar fijo", None)
    assert "FIJO" not in "\n".join(salida)
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "LA CONSTANTE"


def test_prompt_variable_sin_argumento_usa_el_default_del_nodo(entorno):
    """El prompt es OPCIONAL: sin argumento corre con el `args` del nodo."""
    _guardar("con default", _escribe(prompt_args="el default del nodo"))
    cli._slash_flujoteca("ejecutar con default", None)
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "el default del nodo"


def test_prompt_variable_sin_default_pregunta_una_vez(entorno, salida,
                                                      monkeypatch):
    """Default vacio -> se pregunta UNA vez. Y nunca aborta: sin TTY corre
    con la entrada vacia en vez de plantarse esperando a nadie."""
    preguntas = []
    monkeypatch.setattr(cli, "_flujoteca_pedir_prompt",
                        lambda nombre: preguntas.append(nombre) or "tecleado")
    _guardar("sin default", _escribe(prompt_args=""))
    cli._slash_flujoteca("ejecutar sin default", None)
    assert preguntas == ["sin default"]
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "tecleado"


def test_pedir_prompt_sin_tty_no_bloquea(monkeypatch):
    """La red de seguridad del punto de arriba, medida aparte: sin TTY no se
    llama a `input()` (que en un pipe daria EOFError o colgaria un daemon)."""
    from cognia.ux import selector as sel
    monkeypatch.setattr(sel, "hay_tty", lambda: False)
    monkeypatch.setattr("builtins.input",
                        lambda *a: pytest.fail("input() sin TTY"))
    assert cli._flujoteca_pedir_prompt("x") == ""


def test_el_argumento_no_crea_una_version_nueva(entorno):
    """El argumento gana EN MEMORIA (`ctx['prompt_flujo']`): ejecutar no es
    editar, y un flujo no puede acumular una version por cada corrida."""
    _guardar("con default", _escribe(prompt_args="el default"))
    antes = ft.versiones("con default")
    cli._slash_flujoteca("ejecutar con default otra cosa", None)
    assert ft.versiones("con default") == antes
    assert ft.cargar("con default")["nodos"][0]["args"] == "el default"


def test_flujo_viejo_sin_nodo_de_entrada_corre_y_sugiere(entorno, salida):
    """Los flujos del dueno son HISTORIAL: no se reescriben por ejecutarlos.
    Se simula uno de antes del PEDIDO 3 escribiendo la version en disco (que
    es como esta la del dueno), porque `guardar` ya asegura el nodo."""
    _guardar("viejo", _escribe(prompt_args="x"))
    ft._escribir_atomico(ft._ruta_version("viejo", 1), {
        "nombre": "viejo", "nodos": [
            {"id": "esc", "tool": "escribir_archivo",
             "args": "nota.txt | {{prompt}}", "wires": []}]})

    cli._slash_flujoteca("ejecutar viejo desde fuera", None)

    texto = "\n".join(salida)
    assert "no tiene nodo de entrada" in texto, texto
    assert "/flujoteca editar viejo" in texto
    # y el {{prompt}} de un flujo viejo funciona igual, sembrado como variable
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "desde fuera"


# ---------------------------------------------------------------------------
# 5. Bordes: sin nombre, nombre inexistente, flujo roto
# ---------------------------------------------------------------------------

def test_sin_nombre_no_inventa_nada(salida):
    cli._slash_flujoteca("ejecutar", None)
    texto = "\n".join(salida)
    assert "falta el nombre" in texto or "Uso:" in texto


def test_un_nombre_que_no_existe_lo_dice(salida):
    _guardar("existe", _escribe())
    cli._slash_flujoteca("ejecutar no existe este flujo", None)
    texto = "\n".join(salida)
    assert "no encuentro" in texto or "Uso:" in texto
    assert "Traceback" not in texto


def test_un_flujo_con_ciclo_se_dice_no_se_traga(entorno, salida):
    """`flows.ejecutar` valida y lanza FlowError; el comando lo cuenta en vez
    de morir mudo (el modo de fallo caro de esta casa es el vacio, no la
    excepcion)."""
    _guardar("ciclico", _escribe(prompt_args="x"), validar=False)
    ft._escribir_atomico(ft._ruta_version("ciclico", 1), {
        "nombre": "ciclico", "nodos": [
            {"id": "a", "tool": "leer_archivo", "args": "x", "wires": ["b"]},
            {"id": "b", "tool": "leer_archivo", "args": "y", "wires": ["a"]}]})
    cli._slash_flujoteca("ejecutar ciclico", None)
    texto = "\n".join(salida)
    assert "no llego a correr" in texto, texto


# ---------------------------------------------------------------------------
# 6. El autocompletado de /flujoteca no lista la biblioteca por pulsacion
# ---------------------------------------------------------------------------

def test_el_completer_de_flujoteca_esta_cacheado(monkeypatch):
    """El completer corre en CADA TECLA: `flujoteca.listar()` abre un JSON por
    flujo, asi que llamarlo por pulsacion es la version cara de un prompt que
    se traba. Mismo patron que la cache ya probada de /bots."""
    _guardar("uno", _escribe())
    cli._flujoteca_invalidar_completar()
    llamadas = []
    real = ft.listar
    monkeypatch.setattr(ft, "listar",
                        lambda: llamadas.append(1) or real())

    primero = cli._flujoteca_para_completar()
    for _ in range(20):
        cli._flujoteca_para_completar()

    assert primero == ["uno"]
    assert len(llamadas) == 1, f"{len(llamadas)} lecturas de la biblioteca"


def test_invalidar_el_completer_relee(monkeypatch):
    _guardar("uno", _escribe())
    cli._flujoteca_invalidar_completar()
    assert cli._flujoteca_para_completar() == ["uno"]
    _guardar("dos", _escribe())
    cli._flujoteca_invalidar_completar()
    assert sorted(cli._flujoteca_para_completar()) == ["dos", "uno"]


def test_la_biblioteca_rota_no_tumba_el_prompt(monkeypatch):
    """Nunca lanza: un fallo de la biblioteca no puede romper el prompt (se
    dice como degradado y se completa con lo ultimo que se supo)."""
    cli._flujoteca_invalidar_completar()

    def _revienta():
        raise RuntimeError("biblioteca rota")

    monkeypatch.setattr(ft, "listar", _revienta)
    assert cli._flujoteca_para_completar() == []


def test_los_subcomandos_con_nombre_incluyen_ejecutar_y_correr():
    """La rama del completer solo sigue completando nombres detras de los
    subcomandos que LLEVAN un nombre; `nuevo` pide uno que aun no existe."""
    assert "ejecutar" in cli._FLUJOTECA_SUB_CON_NOMBRE
    assert "correr" in cli._FLUJOTECA_SUB_CON_NOMBRE
    assert "nuevo" not in cli._FLUJOTECA_SUB_CON_NOMBRE
    assert set(cli._FLUJOTECA_SUB_CON_NOMBRE) <= cli._FLUJOTECA_SUBCOMANDOS


# ---------------------------------------------------------------------------
# 7. La ayuda y el despachador anuncian el comando
# ---------------------------------------------------------------------------

def test_la_ayuda_de_flujoteca_nombra_ejecutar(salida):
    cli._slash_flujoteca("ayuda", None)
    assert "/flujoteca ejecutar" in "\n".join(salida)


def test_el_despachador_le_pasa_ai_a_slash_flujoteca():
    """La firma recibe `ai` porque el ctx del flujo lo necesita: sin el, un
    nodo que llama al modelo (resumir, generar_codigo) corre sin cliente."""
    import inspect
    assert "ai" in inspect.signature(cli._slash_flujoteca).parameters
    fuente = inspect.getsource(cli)
    assert '_slash_flujoteca(raw[len("/flujoteca"):].strip(), ai)' in fuente


# ---------------------------------------------------------------------------
# 8. Los cableados HERMANOS de esta obra que viven en cli.py y no tienen otro
#    fichero de test propio: /enrutador, el aviso de `sin_efecto` de /workflow
#    y el contrato de /hacer congelado al arrancar.
# ---------------------------------------------------------------------------

def test_enrutador_estado_ensena_contadores_y_latencia(salida, monkeypatch):
    """Sin telemetria, "una accion que se fue a chat" es invisible POR
    DEFINICION -- y ensanchar los guards del intent es justo el cambio que
    puede provocarla."""
    from cognia import enrutador as enr
    enr.reset_contadores()
    monkeypatch.setenv("COGNIA_ENRUTADOR", "1")

    cli._slash_enrutador("estado")

    texto = "\n".join(salida)
    assert "ACTIVO" in texto
    assert "rutas" in texto and "chat" in texto and "agente" in texto
    assert "cache" in texto and "determinista" in texto and "modelo" in texto
    assert "todavia no enruto nada" in texto


def test_enrutador_off_apaga_de_verdad_y_persiste(tmp_path, salida,
                                                  monkeypatch):
    """El interruptor tiene que APAGAR (`enrutador.activo()` lee el env) y
    sobrevivir al cierre (la config)."""
    from cognia import enrutador as enr
    monkeypatch.delenv("COGNIA_ENRUTADOR", raising=False)
    assert enr.activo() is True

    cli._slash_enrutador("off")
    assert enr.activo() is False
    assert os.environ["COGNIA_ENRUTADOR"] == "0"
    assert cli._load_config().get("enrutador") == "off"

    cli._slash_enrutador("on")
    assert enr.activo() is True
    assert cli._load_config().get("enrutador") == "on"


def test_enrutador_apagar_tira_la_cache_de_decisiones(monkeypatch):
    """Apagar y encender sin vaciar la cache devolveria las rutas de antes y
    el interruptor pareceria que no hace nada."""
    from cognia import enrutador as enr
    vaciadas = []
    monkeypatch.setattr(enr, "invalidar_cache",
                        lambda: vaciadas.append(1))
    cli._slash_enrutador("off")
    cli._slash_enrutador("on")
    assert len(vaciadas) == 2


def test_enrutador_argumento_raro_no_apaga_nada(salida, monkeypatch):
    monkeypatch.setenv("COGNIA_ENRUTADOR", "1")
    cli._slash_enrutador("apagalo porfa")
    assert os.environ["COGNIA_ENRUTADOR"] == "1"
    assert "Uso:" in "\n".join(salida)


def test_el_contexto_del_enrutador_respeta_el_tope(monkeypatch):
    """El tope es PARTE del cambio, no un extra: el prefill medido son 219 ms
    y tres turnos largos lo duplican."""
    monkeypatch.setattr(cli, "_history", [
        {"role": "user", "content": "u" * 4000},
        {"role": "assistant", "content": "a" * 4000},
    ])
    ctx = cli._contexto_para_enrutador()
    assert ctx
    assert len(ctx) <= 600


def test_el_contexto_del_enrutador_no_tumba_el_turno(monkeypatch):
    """Un fallo armando el contexto no puede matar el turno: se degrada."""
    from cognia import enrutador as enr

    def _revienta(*a, **k):
        raise RuntimeError("history raro")

    monkeypatch.setattr(enr, "contexto_de_history", _revienta)
    assert cli._contexto_para_enrutador() == ""


def test_workflow_sin_efecto_redirige_a_hacer_o_flujoteca(salida, monkeypatch):
    """`ok` dice que la corrida TERMINO; `sin_efecto` dice que NO TOCO EL PC
    habiendosele pedido. Medido: 732 tokens explicando que no puede hacer
    nada, y `ok=True` encima. El envelope se construye con el constructor
    REAL del adaptador (las nueve claves), no a mano."""
    from cognia.harness import workflows_adapter as wf
    sobre = wf._envelope(ok=True, texto="no tengo acceso a tu PC",
                         run_id="r1", pasos=1, tokens=732, sin_efecto=True)
    assert set(sobre) == wf.CLAVES_ENVELOPE
    monkeypatch.setattr(wf, "ejecutar", lambda *a, **k: sobre)

    cli._slash_workflow("escribi un fichero notas.txt")

    texto = "\n".join(salida)
    assert "no toco tu PC" in texto
    assert "/hacer" in texto and "/flujoteca ejecutar" in texto


def test_workflow_con_efecto_no_avisa_de_nada(salida, monkeypatch):
    """La contra-prueba: el aviso no puede salir en toda corrida (si sale
    siempre, deja de significar algo y se aprende a ignorarlo)."""
    from cognia.harness import workflows_adapter as wf
    sobre = wf._envelope(ok=True, texto="hecho", run_id="r2", pasos=1,
                         tokens=10, sin_efecto=False)
    monkeypatch.setattr(wf, "ejecutar", lambda *a, **k: sobre)

    cli._slash_workflow("resumi esto")

    assert "no toco tu PC" not in "\n".join(salida)


def test_el_contrato_de_hacer_solo_existe_si_se_deriva_al_ARRANCAR(tmp_path,
                                                                   monkeypatch):
    """LA CAUSA, medida: `derive_criteria_from_task` DESCARTA todo
    `file_exists` cuya ruta ya existe. Derivado al TERMINAR -- que es lo que
    se hacia -- el criterio desaparece justo porque el agente cumplio, el
    contrato sale VACIO y /hacer no imprime ni check ni cruz. Derivado al
    ARRANCAR y congelado, el mismo trabajo sale verificado."""
    from cognia.agents.goal_contract import (GoalContract,
                                             derive_criteria_from_task)
    monkeypatch.chdir(tmp_path)
    tarea = "escribe un fichero informe.md con el resumen del repo"

    congelados = derive_criteria_from_task(tarea)       # AL ARRANCAR
    assert congelados, "sin criterios al arrancar no hay nada que congelar"

    (tmp_path / "informe.md").write_text("hecho", encoding="utf-8")

    tardios = derive_criteria_from_task(tarea)          # AL TERMINAR
    assert tardios == [], "el defecto medido: el criterio se cae al cumplirse"

    estado = GoalContract.from_spec(tarea[:120], congelados).check()
    assert estado.complete and estado.total == 1


def test_los_criterios_se_congelan_antes_del_orquestador():
    """Red SECUNDARIA del test de arriba: que la derivacion temprana este
    ANTES de que el agente pueda escribir nada. Si el orden se invierte, el
    contrato vuelve a salir vacio y ningun test de comportamiento lo veria
    (el defecto es la AUSENCIA de una linea)."""
    import inspect
    fuente = inspect.getsource(cli._run_agent_task)
    i = fuente.index("_criterios_congelados = _dc_ini(task)")
    j = fuente.index("from shattering.orchestrator import")
    assert i < j
    assert "list(_criterios_congelados)" in inspect.getsource(cli)


# ---------------------------------------------------------------------------
# 9. Los cinco cableados de la revision adversarial (2026-08-30). Los cinco
#    defectos estaban REPRODUCIDOS; cada test de aqui ejerce el camino del
#    producto y afirma sobre un EFECTO, nunca sobre el fuente.
# ---------------------------------------------------------------------------

def _sin_cablear(prompt_args="", fichero="nota.txt", texto="TEXTO VIEJO"):
    """El flujo que `flujoteca.asegurar_prompt` produce DE VERDAD: nodo de
    entrada al inicio y NINGUN nodo que referencie el marcador del prompt.

    Los tests de flujos que habia escribian ese marcador A MANO, asi que
    ninguno ejercia jamas esta forma -- la unica que el guardado genera solo."""
    return [
        {"id": "prompt", "tool": "prompt", "args": prompt_args,
         "wires": ["esc"]},
        {"id": "esc", "tool": "escribir_archivo",
         "args": f"{fichero} | {texto}", "wires": []},
    ]


@pytest.fixture
def consola_real(monkeypatch):
    """La consola RICH de verdad, con el tema del CLI, escribiendo en un
    buffer. Sin esto un test de markup no prueba nada: `_print_line` esta
    monkeypatcheado en el resto del fichero y guarda la cadena CRUDA, o sea
    justo lo que NO ve el dueno."""
    import io as _io

    from rich.console import Console
    buf = _io.StringIO()
    monkeypatch.setattr(cli, "_HAS_RICH", True)
    monkeypatch.setattr(cli, "_console",
                        Console(theme=cli._THEMES[cli._THEME_ORDER[0]],
                                highlight=False, file=buf, width=200,
                                no_color=True))
    return buf


# -- 1. EL AVISO QUE FALTABA: nodo de entrada que no usa nadie --------------

def test_un_nodo_prompt_que_nadie_usa_avisa_y_el_aviso_no_miente(entorno,
                                                                 salida):
    """El defecto mas grave de la revision: el prompt se aceptaba, se ecoaba
    en la cabecera, salia `ok` en la tabla y NO LLEGABA A NINGUNA TOOL. Antes
    de existir el nodo de entrada, el CLI al menos decia "este flujo no tiene
    nodo de entrada"; con el nodo, el silencio era CONFIADO."""
    _guardar("sin cablear", _sin_cablear(prompt_args="por defecto"))

    cli._slash_flujoteca("ejecutar sin cablear ESTO ES LO QUE QUIERO", None)

    texto = "\n".join(salida)
    assert "[warn_cl]" in texto, texto
    assert "{{prompt}}" in texto, texto
    assert "/flujoteca editar sin cablear" in texto, texto
    # y el aviso dice la VERDAD: el fichero quedo con el texto del flujo,
    # no con el del dueno. Esta linea es la que convierte el aviso en dato.
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "TEXTO VIEJO"


def test_un_flujo_bien_cableado_no_avisa_de_nada(entorno, salida):
    """La contra-prueba obligatoria: un aviso que sale siempre deja de
    significar algo y se aprende a ignorar (memoria de la casa)."""
    _guardar("cableado", _escribe(prompt_args="por defecto"))

    cli._slash_flujoteca("ejecutar cableado ESTO SI LLEGA", None)

    texto = "\n".join(salida)
    assert "ningun nodo usa" not in texto.lower(), texto
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "ESTO SI LLEGA"


def test_entrada_vacia_y_sin_usar_avisa_aunque_no_haya_prompt(entorno, salida,
                                                              monkeypatch):
    """Sin prompt del CLI, sin default y sin nadie que lo lea: ese flujo no
    puede hacer nada util con lo que le escribas, y callarlo es la version
    silenciosa de "no hacen nada"."""
    monkeypatch.setattr(cli, "_flujoteca_pedir_prompt", lambda nombre: "")
    _guardar("inutil", _sin_cablear(prompt_args=""))

    cli._slash_flujoteca("ejecutar inutil", None)

    texto = "\n".join(salida)
    assert "[warn_cl]" in texto and "{{prompt}}" in texto, texto
    assert "no cambia nada" in texto, texto


def test_con_default_y_sin_prompt_del_cli_no_se_avisa(entorno, salida):
    """El limite del aviso de arriba: un flujo con default y sin argumento
    corre como siempre y no se le da la murga al dueno."""
    _guardar("con default", _sin_cablear(prompt_args="el default"))
    cli._slash_flujoteca("ejecutar con default", None)
    assert "no cambia nada" not in "\n".join(salida)


# -- 2. EL SLUG resuelve con prompt y sin prompt ----------------------------

def test_el_slug_resuelve_igual_con_prompt_que_sin_el(entorno):
    """Medido antes del arreglo, con los flujos REALES del dueno:
        'informe_semanal'              -> corre
        'informe_semanal hazlo corto'  -> "no encuentro ningun flujo"
    El mismo identificador dejaba de existir por anadirle el prompt, que es
    justo el argumento que el pedido hace OPCIONAL."""
    _guardar("Informe semanal", _escribe(prompt_args="x"))
    slug = ft.slugificar("Informe semanal")
    assert slug == "informe_semanal"

    assert cli._flujoteca_partir_nombre(slug) == (slug, "")
    assert cli._flujoteca_partir_nombre(slug + " hazlo corto") == (
        slug, "hazlo corto")
    assert cli._flujoteca_partir_nombre("Informe semanal") == (
        "Informe semanal", "")
    assert cli._flujoteca_partir_nombre("Informe semanal hazlo corto") == (
        "Informe semanal", "hazlo corto")


def test_ejecutar_por_slug_con_prompt_escribe_el_fichero(entorno, salida):
    """Y no se queda en el reparto: por la PUERTA DEL PRODUCTO y mirando el
    disco, que es donde se ve si el flujo corrio."""
    _guardar("Informe semanal", _escribe(prompt_args="por defecto"))

    cli._slash_flujoteca("ejecutar informe_semanal hazlo corto", None)

    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == "hazlo corto", "\n".join(salida)


def test_un_slug_que_no_existe_sigue_diciendose(entorno, salida):
    """El limite: aceptar slugs no puede volver a inventar flujos fantasma."""
    _guardar("Informe semanal", _escribe())
    cli._slash_flujoteca("ejecutar informe_mensual hazlo corto", None)
    texto = "\n".join(salida)
    assert "no encuentro" in texto, texto
    assert "Traceback" not in texto


# -- 3. Los corchetes literales que rich se comia ---------------------------

def test_la_sintaxis_del_comando_se_ve_ENTERA_por_la_consola_real(consola_real):
    """'prompt' es un token del tema, asi que rich parseaba el corchete como
    etiqueta de estilo y lo descartaba. Salida real medida:
        'Uso: /flujoteca ejecutar <nombre> '
    Es el UNICO momento en que el dueno ve la sintaxis (cuando ya se equivoco
    de nombre) y justo ahi se le ocultaba el argumento nuevo."""
    # los DOS caminos por los que el dueno ve la sintaxis: el nombre que no
    # existe (el que midio la revision) y el comando a secas.
    _guardar("existe", _escribe())
    cli._slash_flujoteca("ejecutar no existe este flujo", None)
    cli._slash_flujoteca("ejecutar", None)
    pintado = consola_real.getvalue()
    assert pintado.count("<nombre> [prompt]") == 2, pintado
    assert "Uso: /flujoteca ejecutar <nombre> [prompt]" in pintado, pintado


def test_el_genero_entero_de_corchetes_comidos(consola_real):
    """No era una linea: era un GENERO. Tres comandos mas de la misma forma,
    los tres medidos perdiendo su argumento por pantalla."""
    cli._slash_enrutador("apagalo porfa")
    cli._slash_memoria_agente("cosa rara")
    cli._slash_grabar("cosa rara")
    pintado = consola_real.getvalue()
    assert "Uso: /enrutador [estado|on|off]" in pintado, pintado
    assert "Uso: /memoria agente [on | off | estado]" in pintado, pintado
    assert "Uso: /grabar inicio [titulo] | fin" in pintado, pintado


def test_sin_rich_el_corchete_escapado_no_deja_la_barra_suelta():
    """El otro extremo del mismo arreglo: el camino SIN rich borraba el
    corchete escapado como si fuera estilo y dejaba la barra colgando
    ("Uso: /lazo \\ (sin argumento alterna)", medido)."""
    crudo = "[warn_cl]Uso: /lazo " + cli._ESC_COR + "on|off][/warn_cl]"
    assert cli._strip_markup(crudo) == "Uso: /lazo [on|off]"


# -- 4. La denegacion se LEE del gate, no se adivina del texto --------------

def test_el_texto_del_dueno_no_puede_denegar_un_nodo(entorno, salida):
    """FALSA ALARMA medida: el regex "confirma|cancelad|denegad|bloquead" se
    aplicaba a TODAS las salidas, y desde el nodo de entrada obligatorio una
    de ellas es el texto EN BRUTO que teclea el dueno. El nodo `prompt` tiene
    danger=False y no pasa por ningun confirm: es IMPOSIBLE que lo deniegue
    nadie, y aun asi el CLI lo acusaba en un flujo que escribia perfectamente.
    Con la primera falsa alarma el dueno aprende a ignorar la linea que si
    importa."""
    _guardar("sano", _escribe(prompt_args=""))
    pedido = "confirma los datos del informe antes de escribir"

    cli._slash_flujoteca("ejecutar sano " + pedido, None)

    texto = "\n".join(salida)
    assert (entorno / "ws" / "nota.txt").read_text(
        encoding="utf-8") == pedido, texto
    assert "sin permiso" not in texto, texto
    assert "DENEGADO" not in texto, texto


def test_una_denegacion_real_se_dice_con_su_nodo_y_su_motivo(entorno, salida,
                                                             monkeypatch):
    """La contra-prueba: la senal que importa sigue saliendo, ahora con el
    nodo marcado DENEGADO (que no es ERROR: no fallo, no se le dejo correr) y
    sin acusar jamas al nodo de entrada."""
    afuera = entorno / "afuera"
    afuera.mkdir()
    ajeno = afuera / "ajeno.txt"
    ajeno.write_text("no me borres", encoding="utf-8")
    monkeypatch.setattr(cli, "_confirmar_accion", lambda kind, detalle: False)

    _guardar("con gate", [
        {"id": "prompt", "tool": "prompt", "args": "", "wires": ["del"]},
        {"id": "del", "tool": "borrar_archivo", "args": str(ajeno),
         "wires": ["esc"]},
        {"id": "esc", "tool": "escribir_archivo", "args": "sigue.txt | ok",
         "wires": []},
    ])
    cli._slash_flujoteca("ejecutar con gate confirma el borrado por favor",
                         None)

    texto = "\n".join(salida)
    assert "sin permiso (del)" in texto, texto      # SOLO el nodo del gate
    assert "DENEGADO" in texto, texto
    assert ajeno.exists(), "el gate dijo NO y el fichero se borro igual"
    assert (entorno / "ws" / "sigue.txt").exists(), texto   # el flujo siguio


# -- 5. El escalon 3 del enrutado, cableado en el REPL ----------------------

def _repl_con_turnos(monkeypatch, entradas, tareas_vistas):
    """Corre el REPL DE VERDAD con stdin scripteado y los bordes stubbeados.

    Es la unica forma de probar el cableado del escalon 3: la variable
    `_ultimo_turno_agente` vive en el bucle de `_repl_sesion`, asi que un test
    que no corra el bucle no puede distinguir "cableado" de "codigo muerto" --
    que es exactamente como llego a produccion."""
    import builtins
    import sys
    import types

    def _mod(nombre, **attrs):
        m = types.ModuleType(nombre)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    class _OrchMuerto:
        def __init__(self, *a, **k):
            raise RuntimeError("sin backend (harness)")

    class _FakeHistory:
        def add_message(self, *a, **k):
            pass

        def get_recent(self, *a, **k):
            return []

    class _FakeCognia:
        def __init__(self):
            self.chat_history = _FakeHistory()

        def observe(self, *a, **k):
            pass

    monkeypatch.setitem(sys.modules, "shattering.orchestrator",
                        _mod("shattering.orchestrator",
                             ShatteringOrchestrator=_OrchMuerto))
    monkeypatch.setitem(
        sys.modules, "cognia_v3.interfaces.respuestas_articuladas",
        _mod("cognia_v3.interfaces.respuestas_articuladas",
             responder_articulado=lambda ai, raw: {"response": "charla"}))
    monkeypatch.setitem(sys.modules, "cognia.bbrain",
                        _mod("cognia.bbrain", write_bbrain=lambda *a, **k: None))
    monkeypatch.setitem(
        sys.modules, "node.speech_cascade",
        _mod("node.speech_cascade",
             prewarm_fast_speech=lambda *a, **k: None,
             classify_turn=lambda *a, **k: "slow",
             fast_speech_backend=lambda *a, **k: None,
             portero_activo=lambda *a, **k: False,
             portero_system=lambda *a, **k: ""))
    monkeypatch.setattr(cli, "Cognia", _FakeCognia)
    monkeypatch.setattr(cli, "_print_startup_panel", lambda: None)
    monkeypatch.setattr(cli, "_animate_startup", lambda lines: None)
    monkeypatch.setattr(
        cli, "_run_agent_task",
        lambda ai, tarea, pl, **k: tareas_vistas.append(tarea) or "hecho")

    cola = list(entradas) + ["/salir"]

    def _input_fake(prompt=""):
        if not cola:
            raise EOFError
        return cola.pop(0)

    monkeypatch.setattr(builtins, "input", _input_fake)
    cli.repl()


def test_y_ahora_borralo_llega_al_agente_tras_un_turno_de_agente(monkeypatch):
    """El escalon 3 era CODIGO MUERTO: ningun camino del producto ponia
    `turno_previo_agente=True`, asi que "crea un fichero" + "y ahora borralo"
    NO BORRABA NADA con la flota apagada (el modelo devuelve vacio y `decidir`
    cae a chat). Aqui la flota esta apagada a proposito (el orquestador del
    harness LANZA), que es justo cuando duele."""
    tareas = []
    _repl_con_turnos(monkeypatch,
                     ["crea un fichero prueba.txt en el escritorio",
                      "y ahora borralo"], tareas)
    assert tareas == ["crea un fichero prueba.txt en el escritorio",
                      "y ahora borralo"], tareas


def test_un_turno_de_charla_en_medio_apaga_el_escalon(monkeypatch):
    """La contra-prueba, que es la mitad cara del cableado: un "y ahora
    borralo" DETRAS DE CHARLA no puede activar el agente solo."""
    tareas = []
    _repl_con_turnos(monkeypatch,
                     ["crea un fichero prueba.txt en el escritorio",
                      "hola",
                      "y ahora borralo"], tareas)
    assert tareas == ["crea un fichero prueba.txt en el escritorio"], tareas
