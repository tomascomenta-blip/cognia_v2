# -*- coding: utf-8 -*-
"""
tests/test_flujo_e2e_real.py — EL TEST QUE FALTABA HACE UN ANO
==============================================================

Por que existe (PLAN2, seccion "Tests — solo cuentan los que EJECUTAN"):

La razon por la que los cinco fallos de la cadena de flujos estaban en
produccion es que TODOS los tests de flujos usan un `run_tool` FALSO que
acepta cualquier cadena y devuelve texto, y NINGUNO mira el disco. 288 tests
verdes convivieron con la cadena entera rota: el dueno decia "los workflows
no entregan nada al final ni hacen nada en mi PC" y la suite decia que todo
bien.

Este fichero es el contrario exacto de eso:

  - `run_tool` es el REAL (`cognia.agent.tools.run_tool`), con el registro
    REAL de tools.
  - Las afirmaciones son sobre EFECTOS OBSERVABLES: un fichero que existe en
    `tmp_path`, su contenido EXACTO en bytes, un error que aparece en
    `errores` en vez de perderse.

Si un test de este fichero se puede hacer pasar con un doble de `run_tool`,
esta mal escrito.

AISLAMIENTO: el workspace del agente se redirige a `tmp_path` por las DOS
vias que hacen falta -- `dev_tools.AGENT_WORKSPACE_ROOT` (la que usa
`resolve_write_path`, o sea las tools de ESCRITURA) y el `cwd` (el que usan
las de LECTURA, que resuelven rutas relativas contra el directorio actual).
Con una sola de las dos, `escribir_archivo` escribe en tmp_path y
`leer_archivo` lee del repo: el test pasaria por el motivo equivocado.
"""
import json

import pytest

from cognia.agent import flows
from cognia.agent.tools import TOOLS, run_tool


@pytest.fixture()
def taller(tmp_path, monkeypatch):
    """El workspace del agente = tmp_path, por las dos vias. Devuelve
    (tmp_path, run_tool_real, tool_existe_real)."""
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("COGNIA_EFIMERO", "1")
    monkeypatch.delenv("COGNIA_FLOWS_PARALELO", raising=False)
    monkeypatch.delenv("COGNIA_FLOWS_CACHE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _existe(n):
    return n in TOOLS


# ---------------------------------------------------------------------------
# 1. El camino que el dueno pide: un flujo que TOCA SU PC
# ---------------------------------------------------------------------------

def test_escribir_luego_leer_deja_el_fichero_en_disco(taller):
    """escribir_archivo -> leer_archivo con el registro REAL. Se afirma sobre
    el DISCO (existe + contenido exacto), no sobre el texto que devuelve la
    tool: una tool puede decir 'OK' y no haber escrito nada."""
    flujo = {"nombre": "e2e", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "notas.txt | hola mundo", "wires": ["leer"]},
        {"id": "leer", "tool": "leer_archivo", "args": "notas.txt",
         "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    destino = taller / "notas.txt"
    assert destino.exists(), r["salidas"]
    assert destino.read_text(encoding="utf-8") == "hola mundo"
    assert r["errores"] == {}
    # y el nodo de lectura VIO lo escrito (la cadena se cerro de verdad)
    assert "hola mundo" in r["salidas"]["leer"]


def test_ok_entregable_y_ficheros_traen_valores_reales(taller):
    """Las tres claves de 5.5, medidas contra el disco. `entregable` es la
    salida del ultimo nodo NO-prompt; `ficheros`, las rutas que el flujo
    produjo de verdad."""
    flujo = {"nombre": "e2e2", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "el objetivo",
         "wires": ["esc"]},
        {"id": "esc", "tool": "escribir_archivo",
         "args": "informe.md | tema: {{prompt}}", "wires": ["mas"]},
        {"id": "mas", "tool": "apendar_archivo",
         "args": "informe.md | linea final", "wires": ["leer"]},
        {"id": "leer", "tool": "leer_archivo", "args": "informe.md",
         "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert r["ok"] is True, r["errores"]
    assert r["cancelado"] is False
    assert (taller / "informe.md").exists()
    texto = (taller / "informe.md").read_text(encoding="utf-8")
    assert texto.startswith("tema: el objetivo")   # {{prompt}} interpolado
    assert "linea final" in texto
    # ficheros: deducido de los nodos de escritura que salieron OK, sin
    # duplicados (esc y mas escriben el MISMO fichero)
    assert r["ficheros"] == ["informe.md"]
    # entregable: el ultimo nodo del orden topologico que no es de entrada
    assert r["entregable"] == r["salidas"]["leer"]
    assert "linea final" in r["entregable"]


def test_ficheros_no_lista_el_nodo_que_fallo(taller):
    """Un nodo de escritura que FALLA no puede aparecer en `ficheros`: decir
    'produje x' sin haberlo producido es la mentira que este trabajo viene a
    quitar."""
    flujo = {"nombre": "e2e3", "nodos": [
        {"id": "bien", "tool": "escribir_archivo", "args": "a.txt | ok",
         "wires": ["mal"]},
        # sin el separador y con un solo trozo: la tool devuelve ERROR de
        # formato y no escribe nada
        {"id": "mal", "tool": "escribir_archivo", "args": "b.txt",
         "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert (taller / "a.txt").exists()
    assert not (taller / "b.txt").exists()
    assert r["ficheros"] == ["a.txt"]
    assert "mal" in r["errores"]
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 2. LA CAUSA RAIZ: el separador de args de los flujos legacy
# ---------------------------------------------------------------------------

def test_legacy_con_salto_de_linea_hoy_escribe_el_fichero(taller):
    """CONTRAFACTUAL EN UN TEST (PLAN2 5.1). `flujo_ia` ensenaba
    `args: "informe.md\\n{{hallar}}"` y la tool exige `ruta | contenido`:
    ANTES esto daba 'ERROR: formato' y el disco quedaba intacto -- que es
    literalmente "los workflows no hacen nada en mi PC". Se mide con el
    fichero, no con el texto."""
    legacy = {"nombre": "legacy", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "notas.txt\nPRUEBA", "wires": []}]}
    r = flows.ejecutar(legacy, {}, run_tool, tool_existe=_existe)
    assert r["args_normalizados"] == ["esc"]
    destino = taller / "notas.txt"
    assert destino.exists(), r["salidas"]["esc"]
    assert destino.read_text(encoding="utf-8") == "PRUEBA"
    assert r["errores"] == {}
    assert r["ficheros"] == ["notas.txt"]
    # y la version que le llego (el "disco" del dueno) NO se reescribio
    assert legacy["nodos"][0]["args"] == "notas.txt\nPRUEBA"


def test_el_brazo_nulo_del_separador_no_escribe_nada(taller, monkeypatch):
    """EL BRAZO NULO del contrafactual: el MISMO flujo con la normalizacion
    apagada no deja fichero. Sin este brazo, el test de arriba solo dice 'hoy
    funciona', no 'esto es lo que lo arreglo'."""
    monkeypatch.setattr(flows, "normalizar_args", lambda f, **k: (f, []))
    legacy = {"nombre": "legacy", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "notas.txt\nPRUEBA", "wires": []}]}
    r = flows.ejecutar(legacy, {}, run_tool, tool_existe=_existe)

    assert not (taller / "notas.txt").exists()
    assert "esc" in r["errores"]
    assert "formato" in r["errores"]["esc"]
    assert r["ficheros"] == []


def test_contenido_multilinea_con_el_separador_viejo_tambien_llega_entero(
        taller):
    """El caso que mas duele: escribir un fichero DE VARIAS LINEAS con el
    separador viejo. Hoy `escribir_archivo` devuelve 'ERROR: formato' y no
    toca el disco, asi que partir por el PRIMER salto (y dejar el resto como
    contenido) no puede empeorar nada y arregla el caso entero."""
    flujo = {"nombre": "multi", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "nivel.md\n# Nivel\nzombis nuevos\nfin", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert r["args_normalizados"] == ["esc"]
    assert (taller / "nivel.md").read_text(encoding="utf-8") == \
        "# Nivel\nzombis nuevos\nfin"
    assert r["ficheros"] == ["nivel.md"]


def test_la_lista_de_tools_que_exigen_el_separador_sigue_siendo_CIERTA(taller):
    """EL GUARDIAN DE LA MEDIDA. `TOOLS_SEPARADOR_OBLIGATORIO` es una lista a
    mano, y una lista a mano se desincroniza en la primera tool que cambie de
    parser. Esto REEJECUTA la medida que la justifica: cada tool de la lista
    tiene que seguir devolviendo un ERROR de formato cuando le llega un args
    con saltos y sin pipe. El dia que una deje de exigirlo, este test se pone
    rojo ANTES de que la heuristica le parta un argumento legitimo."""
    for nombre in flows.TOOLS_SEPARADOR_OBLIGATORIO:
        assert nombre in TOOLS, nombre
        salida = TOOLS[nombre]["fn"]("a.txt\nlinea1\nlinea2", {})
        assert "ERROR" in salida and "formato" in salida, \
            f"{nombre} ya NO exige el separador: {salida[:120]}"

    # y la contra-prueba: las que SI toleran los saltos estan FUERA de la
    # lista (si entraran, se les partiria un patron de busqueda legitimo)
    for tolerante in ("buscar", "buscar_ficheros"):
        assert tolerante not in flows.TOOLS_SEPARADOR_OBLIGATORIO
        salida = TOOLS[tolerante]["fn"]("a.txt\nlinea1\nlinea2", {})
        assert "formato" not in salida, salida[:120]


def test_normalizar_args_no_parte_un_contenido_multilinea(taller):
    """La contra-prueba de la normalizacion: un contenido de VARIAS lineas
    (mas trozos que posicionales) NO se toca. Si se tocara, un fichero de 40
    lineas se guardaria con una."""
    flujo = {"nombre": "multi", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "doc.txt | linea1\nlinea2\nlinea3", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)
    assert r["args_normalizados"] == []
    assert (taller / "doc.txt").read_text(encoding="utf-8") == \
        "linea1\nlinea2\nlinea3"


def test_flujoteca_normaliza_al_cargar_sin_reescribir_el_disco(
        taller, monkeypatch, tmp_path):
    """`flujoteca.cargar` arregla el separador EN MEMORIA y el fichero de la
    version sigue teniendo el "\\n": las versiones del dueno son historial,
    no cache."""
    from cognia.agent import flujoteca as F
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    F.guardar({"nombre": "Legacy", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "salida.txt\nCUERPO", "wires": []}]}, nombre="Legacy")

    flujo, aviso = F.cargar_con_aviso("Legacy")
    nodo = [n for n in flujo["nodos"] if n["id"] == "esc"][0]
    assert nodo["args"] == "salida.txt | CUERPO"
    assert "separador" in aviso and "esc" in aviso

    # el JSON en disco sigue con el salto de linea original
    crudo = json.loads((tmp_path / "flujoteca" / "legacy" / "v1.json")
                       .read_text(encoding="utf-8"))
    crudo_esc = [n for n in crudo["nodos"] if n["id"] == "esc"][0]
    assert crudo_esc["args"] == "salida.txt\nCUERPO"

    # y el flujo cargado CORRE y deja el fichero
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)
    assert (taller / "salida.txt").read_text(encoding="utf-8") == "CUERPO"
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# 3. Los fallos que hoy se pierden en silencio
# ---------------------------------------------------------------------------

def test_delegar_subtarea_sin_run_agent_aparece_en_errores(taller):
    """Un nodo `delegar_subtarea` (que ESTA en la paleta del editor) con un
    ctx pelado no puede delegar. Lo que NO puede pasar es que eso se pierda:
    tiene que salir en `errores` y bajar `ok`."""
    flujo = {"nombre": "deleg", "nodos": [
        {"id": "d", "tool": "delegar_subtarea",
         "args": "investigador | mira que hay en el escritorio", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert "d" in r["errores"], r["salidas"]
    assert "delegacion no disponible" in r["errores"]["d"]
    assert r["ok"] is False
    assert r["entregable"] == r["salidas"]["d"]     # se ENSENA, no se traga


def test_marcador_desconocido_se_reporta_en_vez_de_quedar_en_hueco(taller):
    """`{{hallar}}` sin nodo `hallar` se sustituye por "" y el flujo sigue.
    Eso es lo que hace que un flujo escriba un fichero VACIO y nadie sepa por
    que. No se endurece a error (rompe flujos vivos): se REPORTA."""
    flujo = {"nombre": "hueco", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "x.txt | dato: {{no_existe}}", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert r["marcadores_vacios"] == ["no_existe"]
    # el fichero se escribio con el hueco DENTRO (escribir_archivo recorta el
    # blanco final): el flujo "funciono" y el dato no esta. Por eso hay que
    # reportarlo.
    assert (taller / "x.txt").read_text(encoding="utf-8") == "dato:"


def test_tool_inexistente_se_caza_al_CREAR_y_no_al_ejecutar(taller):
    """5.4: `organizar_flujo` valida contra el registro REAL. El planner
    habla de research_llm/synthesize, que no son tools de Cognia; sin la
    traduccion, `crear_flujo` guardaba basura y el dueno se enteraba nodo por
    nodo al ejecutar."""
    flujo = flows.organizar_flujo("investiga la historia del ajedrez")
    tools = [n["tool"] for n in flujo["nodos"]]
    assert tools, flujo
    for t in tools:
        assert t in TOOLS, f"'{t}' no existe en el registro real"


def test_crear_flujo_y_ejecutar_flujo_de_punta_a_punta(taller):
    """La cadena entera por la puerta de las TOOLS (no de las funciones):
    crear_flujo persiste, ejecutar_flujo lo encuentra por el workspace y lo
    corre con el registro real, sin un solo nodo 'no existe'."""
    creado = TOOLS["crear_flujo"]["fn"]("analizar el proyecto y resumirlo", {})
    assert "ERROR" not in creado, creado
    assert (taller / ".flujo.json").exists()

    corrido = TOOLS["ejecutar_flujo"]["fn"]("", {})
    assert "RESULTADO ejecutar_flujo" in corrido
    assert "no existe" not in corrido, corrido


def test_ejecutar_flujo_alcanza_la_flujoteca(taller, tmp_path, monkeypatch):
    """PEDIDO 4.6: `ejecutar_flujo <nombre>` corre lo que el dueno dibujo en
    el editor visual, no solo el .flujo.json del workspace. Se mide con el
    FICHERO que deja."""
    from cognia.agent import flujoteca as F
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    F.guardar({"nombre": "Mi Informe", "nodos": [
        {"id": "esc", "tool": "escribir_archivo",
         "args": "desde_flujoteca.txt | contenido de la biblioteca",
         "wires": []}]}, nombre="Mi Informe")

    salida = TOOLS["ejecutar_flujo"]["fn"]("Mi Informe", {})
    assert "flujoteca:Mi Informe" in salida, salida
    assert (taller / "desde_flujoteca.txt").read_text(encoding="utf-8") == \
        "contenido de la biblioteca"
    # y el texto que lee el dueno DICE que se produjo (la queja de 5.5)
    assert "Ficheros: desde_flujoteca.txt" in salida
    assert "Entregable:" in salida


def test_precedencia_ruta_literal_gana_a_la_flujoteca(taller, tmp_path,
                                                     monkeypatch):
    """Precedencia ANUNCIADA: ruta literal > workspace > flujoteca. Dos
    flujos con el mismo nombre en sitios distintos es un accidente esperable;
    correr uno sin decir cual es peor que no correrlo."""
    from cognia.agent import flujoteca as F
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    F.guardar({"nombre": "choque", "nodos": [
        {"id": "b", "tool": "escribir_archivo",
         "args": "quien.txt | biblioteca", "wires": []}]}, nombre="choque")
    literal = taller / "choque"
    literal.write_text(json.dumps({"nombre": "choque", "nodos": [
        {"id": "l", "tool": "escribir_archivo",
         "args": "quien.txt | ruta literal", "wires": []}]}),
        encoding="utf-8")

    salida = TOOLS["ejecutar_flujo"]["fn"](str(literal), {})
    assert "ruta " in salida
    assert (taller / "quien.txt").read_text(encoding="utf-8") == "ruta literal"


# ---------------------------------------------------------------------------
# 5. El GATE DE PERMISOS - un nodo denegado NO es un nodo que salio bien
# ---------------------------------------------------------------------------
# Revision adversarial 2026-08-30 (lente permisos), CONFIRMADO y reproducido:
# un nodo `ejecutar` denegado devuelve "RESULTADO ejecutar: no confirmado por
# el usuario (...)" -- texto SIN la palabra ERROR -- asi que la heuristica del
# motor lo daba por bueno: fila VERDE, `ok=True`, "0 con error", y su texto de
# ENTREGABLE. Y por el camino del AGENTE no habia ni el aviso.
#
# Estos tests NO leen el fuente ni buscan palabras en el texto de la
# denegacion: afirman sobre el DISCO (el efecto no ocurrio) y sobre el
# CONTRATO del retorno.


def _sin_atajos(monkeypatch):
    """Deja el gate en la configuracion de casa, sin los flags que lo
    puentean: si no, el resultado depende del entorno de quien corre el test
    y un dia pasa por el motivo equivocado."""
    monkeypatch.setenv("COGNIA_SENTINEL", "1")
    for flag in ("COGNIA_ACCESO_TOTAL", "COGNIA_AUTONOMOUS"):
        monkeypatch.delenv(flag, raising=False)


def _flujo_peligroso(destino):
    """prompt -> ejecutar. El comando lleva CODIGO EN LINEA, que es lo que el
    centinela no puede verificar y por eso manda al canal de confirmacion."""
    cmd = 'python -c "open(r\'%s\',\'w\').write(\'pwned\')"' % destino
    return {"nombre": "peligroso", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "haz la cosa",
         "wires": ["e"]},
        {"id": "e", "tool": "ejecutar", "args": cmd, "wires": []}]}


def test_un_nodo_denegado_por_el_gate_no_cuenta_como_ok(taller, monkeypatch):
    """SENAL (A): el canal de confirmacion dijo que NO.

    Antes: ok=True, errores={}, y el texto del gate como entregable.
    Ahora: el nodo esta en `denegados`, tumba `ok`, y no entrega nada."""
    _sin_atajos(monkeypatch)
    destino = taller / "PWNED.txt"
    preguntas = []

    def confirm(motivo="", detalle=""):
        preguntas.append(motivo)
        return False

    r = flows.ejecutar(_flujo_peligroso(destino), {"confirm": confirm},
                       run_tool, tool_existe=_existe)

    # 1. el efecto NO ocurrio: es lo unico que prueba que el gate actuo
    assert not destino.exists()
    # 2. y actuo por el CANAL, no por el texto: senal estructural
    assert preguntas, "el gate ni pregunto: el test no mide lo que cree"
    # 3. el motor se entero
    assert r["denegados"] == ["e"], r
    assert r["ok"] is False
    assert "e" in r["errores"]
    assert r["motivos_denegacion"].get("e")
    # 4. la denegacion NO es el entregable del flujo
    assert "no confirmado" not in r["entregable"]


def test_sin_canal_de_confirmacion_el_nodo_tampoco_sale_verde(taller,
                                                              monkeypatch):
    """SENAL (B): sin `confirm` en el ctx no se llama a nadie -- el gate
    deniega por default-deny y lo unico que queda es el veredicto que
    `run_tool` publica en el ctx (`_ultimo_ok`, el P0-1 de tools.py). Es el
    caso del agente en una sesion sin terminal: el dueno en remoto."""
    _sin_atajos(monkeypatch)
    destino = taller / "PWNED2.txt"

    r = flows.ejecutar(_flujo_peligroso(destino), {}, run_tool,
                       tool_existe=_existe)

    assert not destino.exists()
    assert r["denegados"] == ["e"], r
    assert r["ok"] is False


def test_ejecutar_flujo_le_dice_al_modelo_que_el_gate_lo_freno(taller,
                                                               monkeypatch):
    """Lo que LEE EL MODELO. `_RE_FLUJO_DENEGADO` solo existe en cli.py, asi
    que por la tool la observacion decia "2 nodos, 0 con error" y traia la
    denegacion como entregable: cero senal de que el gate freno la unica
    accion del flujo. Es el "se bloquea mudo" en el CONTRATO."""
    _sin_atajos(monkeypatch)
    destino = taller / "PWNED3.txt"
    literal = taller / "peligroso.flujo.json"
    literal.write_text(json.dumps(_flujo_peligroso(destino)),
                       encoding="utf-8")

    salida = TOOLS["ejecutar_flujo"]["fn"](
        str(literal), {"confirm": lambda *a, **k: False})

    assert not destino.exists()
    assert "DENEGADO" in salida, salida
    assert "0 con error" not in salida, salida
    assert "e:" in salida                    # que nodo fue
    assert "/permisos" in salida             # y que hacer


def test_un_prompt_que_habla_de_confirmar_no_es_una_denegacion(taller,
                                                               monkeypatch):
    """FALSO POSITIVO del detector por regex (cli.py:9325): el nodo `prompt`
    devuelve el texto CRUDO del dueno y tiene danger=False, o sea que es
    imposible que nadie lo deniegue. Con "confirma"/"cancelado" dentro del
    objetivo, el detector textual acusaba a un flujo perfectamente sano
    (MEDIDO). El del motor no puede: mira el canal de permisos, no letras."""
    _sin_atajos(monkeypatch)
    flujo = {"nombre": "sano", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "", "wires": ["w"]},
        {"id": "w", "tool": "escribir_archivo",
         "args": "sano.md | {{prompt}}", "wires": []}]}

    r = flows.ejecutar(flujo, {"prompt_flujo": "confirma los datos del "
                                               "informe; no fue cancelado ni "
                                               "denegado ni bloqueado"},
                       run_tool, tool_existe=_existe)

    assert (taller / "sano.md").exists()
    assert r["denegados"] == [], r
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# 6. `saltar_si` no mira las salidas de los nodos de ENTRADA
# ---------------------------------------------------------------------------
# Mismo informe, hallazgo 2. El hermano de este bug se arreglo hoy en
# `_correr_nodo` (exceptuar TOOLS_ENTRADA de la heuristica de ERROR);
# `saltar_si` quedo sin tocar y miraba TODAS las salidas previas, incluida la
# del nodo `prompt` que ahora se inserta al inicio de TODO flujo.


def test_el_texto_que_pega_el_dueno_no_salta_nodos(taller):
    """EL CASO EXACTO DEL REVISOR, medido: flujo prompt -> escribir_archivo
    con saltar_si "ERROR" (el valor de ejemplo que documenta el propio
    editor, editor_html.py:158) y el dueno pegando un log: "arregla el ERROR
    de la web".

    Antes: ok=True, saltados=['w'], entregable "(saltado: 'ERROR')" y c.txt
    NO existia -- la queja del dueno ("no hacen nada") producida por su
    propio texto. Y el tope de interpolacion de los nodos de entrada subio
    hoy a 8000 chars precisamente para que pueda pegar objetivos largos: un
    log, donde ERROR en mayusculas abunda, es el uso PREVISTO."""
    flujo = {"nombre": "c", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "", "wires": ["w"]},
        {"id": "w", "tool": "escribir_archivo",
         "args": "c.txt | el trabajo de verdad", "saltar_si": "ERROR",
         "wires": []}]}

    r = flows.ejecutar(flujo, {"prompt_flujo": "arregla el ERROR de la web"},
                       run_tool, tool_existe=_existe)

    destino = taller / "c.txt"
    assert destino.exists(), r          # EL DISCO, no el texto de la tool
    assert destino.read_text(encoding="utf-8") == "el trabajo de verdad"
    assert r["saltados"] == []
    assert r["ok"] is True
    assert "saltado" not in r["entregable"]


def test_una_variable_sembrada_tampoco_salta_nodos(taller):
    """La otra puerta del MISMO texto: un flujo VIEJO (sin nodo de entrada)
    recibe el objetivo del dueno por `variables={"prompt": ...}`, que es como
    `_t_ejecutar_flujo` hace que `{{prompt}}` funcione sin reescribir los
    flujos ya guardados. Si esa siembra pudiera disparar `saltar_si`, el
    arreglo valdria solo para los flujos nuevos."""
    flujo = {"nombre": "viejo", "nodos": [
        {"id": "w", "tool": "escribir_archivo",
         "args": "d.txt | trabajo: {{prompt}}", "saltar_si": "ERROR",
         "wires": []}]}

    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe,
                       variables={"prompt": "arregla el ERROR de la web"})

    assert (taller / "d.txt").exists(), r
    assert r["saltados"] == []


def test_saltar_si_sigue_disparando_con_la_salida_de_un_nodo_normal(taller):
    """La contra-prueba: el arreglo no puede desactivar `saltar_si`. Con la
    condicion en la salida de un nodo de TRABAJO (no de entrada), el nodo se
    salta y el fichero NO aparece."""
    flujo = {"nombre": "cond", "nodos": [
        {"id": "a", "tool": "escribir_archivo",
         "args": "bandera.txt | x", "wires": ["b"]},
        {"id": "b", "tool": "escribir_archivo",
         "args": "no_deberia.txt | y", "saltar_si": "bandera.txt",
         "wires": []}]}

    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert "bandera.txt" in r["salidas"]["a"]
    assert r["saltados"] == ["b"], r
    assert not (taller / "no_deberia.txt").exists()
