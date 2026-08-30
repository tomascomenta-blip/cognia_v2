# -*- coding: utf-8 -*-
"""
tests/test_flows_prompt.py — el nodo de ENTRADA de un flujo (PLAN2, PEDIDO 3)
============================================================================

El dueno pidio "un nodo PROMPT obligatorio al inicio de cada workflow
(variable o constante)". La decision de diseno que hay que fijar aqui es que
EL MODO VA EN EL NOMBRE DE LA TOOL (`prompt` = variable, `prompt_fijo` =
constante) y no en un campo nuevo del nodo: `tool` esta en la whitelist de
`flujo_ia.sanear_flujo` y en la tupla de 7 campos de `flujoteca.comparar`,
asi que sobrevive a una edicion conversacional y SALE en el diff del
historial; un campo `prompt_modo` desapareceria en silencio en la primera
edicion (medido).

Los ocho casos que enumera el plan, y por que cada uno:

  1. la tool `prompt` devuelve TEXTO CRUDO (falla si aparece "RESULTADO")
  2. `ctx["prompt_flujo"]` PISA el default del nodo
  3. `prompt_fijo` IGNORA `ctx["prompt_flujo"]`
  4. un prompt que contiene la palabra "ERROR" NO marca el nodo como fallido
  5. `{{prompt}}` se propaga en secuencial Y en paralelo
  6. `asegurar_prompt` es IDEMPOTENTE (por tool, no por id)
  7. `asegurar_prompt` con el id 'prompt' OCUPADO usa prompt_0
  8. `ctx["_cancelado"]` corta a mitad y devuelve `cancelado=True`

Las tools se ejercen por el REGISTRO REAL (`TOOLS["prompt"]["fn"]` y
`run_tool`), no por un doble: el defecto que este fichero previene es
justamente el de un prefijo que se cuela en los args de todos los nodos, y
un `run_tool` falso no lo veria nunca.
"""
import pytest

from cognia.agent import flows
from cognia.agent.tools import TOOLS, run_tool


def _existe(n):
    return n in TOOLS


# ---------------------------------------------------------------------------
# 1-3. El contrato de las dos tools, contra el registro REAL
# ---------------------------------------------------------------------------

def test_las_dos_tools_de_entrada_estan_registradas():
    for n in ("prompt", "prompt_fijo"):
        assert n in TOOLS, n
        assert TOOLS[n]["danger"] is False


def test_prompt_devuelve_texto_CRUDO_sin_prefijo_resultado():
    """EL contrato del PEDIDO 3. Si la tool devolviera "RESULTADO prompt: X",
    ese prefijo se colaria via {{prompt}} DENTRO de cada fichero escrito y de
    cada busqueda del flujo. Se afirma la ausencia literal de 'RESULTADO'."""
    salida = TOOLS["prompt"]["fn"]("un nivel con zombis nuevos", {})
    assert salida == "un nivel con zombis nuevos"
    assert "RESULTADO" not in salida

    fija = TOOLS["prompt_fijo"]["fn"]("la constante", {})
    assert fija == "la constante"
    assert "RESULTADO" not in fija


def test_ctx_prompt_flujo_pisa_el_default_del_nodo():
    assert TOOLS["prompt"]["fn"]("por defecto",
                                 {"prompt_flujo": "lo que pidio el dueno"}) \
        == "lo que pidio el dueno"
    # sin prompt del llamador, manda el default del nodo (nunca aborta)
    assert TOOLS["prompt"]["fn"]("por defecto", {}) == "por defecto"
    # sin ninguno de los dos, cadena vacia (el CLI es quien pregunta)
    assert TOOLS["prompt"]["fn"]("", {}) == ""
    assert TOOLS["prompt"]["fn"](None, None) == ""


def test_prompt_fijo_ignora_el_prompt_del_llamador():
    """CONSTANTE quiere decir constante: el argumento del CLI no la pisa (el
    CLI lo avisa en amarillo, pero el motor no cambia de valor)."""
    assert TOOLS["prompt_fijo"]["fn"](
        "SIEMPRE ESTO", {"prompt_flujo": "otra cosa"}) == "SIEMPRE ESTO"


# ---------------------------------------------------------------------------
# 4. El borde de 5.6: la heuristica \bERROR\b no puede morder al prompt
# ---------------------------------------------------------------------------

def test_un_prompt_que_dice_ERROR_no_marca_el_nodo_como_fallido():
    """`_correr_nodo` marca fallo con re.search(r"\\bERROR\\b", res[:120]).
    Un objetivo del dueno que empiece "arregla el ERROR de la web" hacia que
    el nodo de ENTRADA saliera en `errores` y el flujo entero con ok=False,
    sin que nada hubiera fallado."""
    flujo = {"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt",
         "args": "arregla el ERROR de la pagina", "wires": ["eco"]},
        {"id": "eco", "tool": "calcular", "args": "1+1", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run_tool, tool_existe=_existe)

    assert r["errores"] == {}, r["errores"]
    assert r["ok"] is True
    assert r["salidas"]["prompt"] == "arregla el ERROR de la pagina"


def test_un_nodo_normal_que_dice_ERROR_sigue_marcandose():
    """La contra-prueba: la excepcion es SOLO para las dos tools de entrada.
    Si valiera para todas, se apagaria la deteccion de fallos entera."""
    def run(name, args, ctx):
        return "RESULTADO x ERROR: boom"

    flujo = {"nombre": "f", "nodos": [
        {"id": "a", "tool": "x", "args": "", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run)
    assert "a" in r["errores"]


def test_una_excepcion_en_la_tool_de_entrada_SI_es_error():
    """Fallo DURO (excepcion/timeout) del nodo de entrada: eso si cuenta.
    Exceptuar el texto no es exceptuar el fallo."""
    def run(name, args, ctx):
        raise RuntimeError("el registro se cayo")

    flujo = {"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "hola", "wires": []}]}
    r = flows.ejecutar(flujo, {}, run)
    assert "prompt" in r["errores"]
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 5. {{prompt}} se propaga, en secuencial y en paralelo
# ---------------------------------------------------------------------------

def _flujo_con_prompt():
    return {"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "el tema",
         "wires": ["a", "b"]},
        {"id": "a", "tool": "eco", "args": "A:{{prompt}}", "wires": []},
        {"id": "b", "tool": "eco", "args": "B:{{prompt}}", "wires": []}]}


def _run_eco(name, args, ctx):
    if name in ("prompt", "prompt_fijo"):
        return TOOLS[name]["fn"](args, ctx)
    return f"RESULTADO eco: {args}"


@pytest.mark.parametrize("paralelo", [False, True])
def test_prompt_se_propaga_a_los_hijos(paralelo):
    r = flows.ejecutar(_flujo_con_prompt(), {}, _run_eco, paralelo=paralelo,
                       cap=2)
    assert r["salidas"]["a"] == "RESULTADO eco: A:el tema"
    assert r["salidas"]["b"] == "RESULTADO eco: B:el tema"
    assert r["errores"] == {}


@pytest.mark.parametrize("paralelo", [False, True])
def test_el_prompt_del_llamador_llega_a_los_hijos(paralelo):
    r = flows.ejecutar(_flujo_con_prompt(), {"prompt_flujo": "OTRO"},
                       _run_eco, paralelo=paralelo, cap=2)
    assert r["salidas"]["a"] == "RESULTADO eco: A:OTRO"
    assert r["salidas"]["b"] == "RESULTADO eco: B:OTRO"


def test_la_salida_del_prompt_no_se_recorta_a_2000():
    """El tope de `_interpolar` sube a 8000 para los nodos de entrada: el
    objetivo del dueno no puede truncarse en silencio a la mitad de una
    frase. Un nodo normal sigue con 2000."""
    largo = "x" * 5000
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": largo, "wires": ["a"]},
        {"id": "a", "tool": "eco", "args": "{{prompt}}", "wires": []}]},
        {}, _run_eco)
    assert len(r["salidas"]["a"]) == len("RESULTADO eco: ") + 5000

    r2 = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "n", "tool": "eco", "args": largo, "wires": ["a"]},
        {"id": "a", "tool": "eco", "args": "{{n}}", "wires": []}]},
        {}, _run_eco)
    assert len(r2["salidas"]["a"]) == len("RESULTADO eco: ") + 2000


# ---------------------------------------------------------------------------
# 5b. variables= : se siembran ANTES del primer nodo y NUNCA pisan un nodo
# ---------------------------------------------------------------------------

def test_variables_se_siembran_antes_del_primer_nodo():
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "{{prompt}}", "wires": []}]},
        {}, _run_eco, variables={"prompt": "sembrado"})
    assert r["salidas"]["a"] == "RESULTADO eco: sembrado"
    assert r["marcadores_vacios"] == []


def test_una_variable_nunca_pisa_un_nodo():
    """Si una variable pudiera pisar un id de nodo, ese nodo dejaria de verse
    y NADIE sabria por que: la salida del flujo seria la de la variable."""
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "del nodo",
         "wires": ["a"]},
        {"id": "a", "tool": "eco", "args": "{{prompt}}", "wires": []}]},
        {}, _run_eco, variables={"prompt": "de la variable"})
    assert r["salidas"]["prompt"] == "del nodo"
    assert r["salidas"]["a"] == "RESULTADO eco: del nodo"


# ---------------------------------------------------------------------------
# 6-7. asegurar_prompt: idempotente, id ocupado, raices
# ---------------------------------------------------------------------------

def test_asegurar_prompt_anade_el_nodo_al_inicio_y_lo_cablea_a_las_raices():
    flujo = {"nombre": "f", "nodos": [
        {"id": "a", "tool": "listar", "args": ".", "wires": ["c"]},
        {"id": "b", "tool": "listar", "args": "..", "wires": ["c"]},
        {"id": "c", "tool": "resumir", "args": "{{a}}", "wires": []}]}
    out = flows.asegurar_prompt(flujo)

    assert out["nodos"][0]["id"] == "prompt"
    assert out["nodos"][0]["tool"] == "prompt"
    # LAS DOS raices previas, no solo la primera: un flujo con dos ramas de
    # arranque perderia una si se colgara solo del primer nodo
    assert out["nodos"][0]["wires"] == ["a", "b"]
    assert flows.validar(out)[0] == "prompt"
    # funcion PURA: el flujo que recibio no se toco
    assert len(flujo["nodos"]) == 3


def test_asegurar_prompt_es_IDEMPOTENTE():
    """`restaurar()` reguarda un flujo que YA tiene su nodo de entrada: si no
    fuera idempotente, cada restauracion anadiria uno mas, para siempre."""
    flujo = {"nombre": "f", "nodos": [
        {"id": "a", "tool": "listar", "args": ".", "wires": []}]}
    una = flows.asegurar_prompt(flujo)
    dos = flows.asegurar_prompt(una)
    tres = flows.asegurar_prompt(dos)
    assert len(una["nodos"]) == len(dos["nodos"]) == len(tres["nodos"]) == 2


def test_asegurar_prompt_comprueba_la_TOOL_y_no_el_ID():
    """El dueno puede renombrar el nodo a 'objetivo'. Comprobar por id le
    anadiria un segundo nodo de entrada en CADA guardado."""
    flujo = {"nombre": "f", "nodos": [
        {"id": "objetivo", "tool": "prompt", "args": "x", "wires": ["a"]},
        {"id": "a", "tool": "listar", "args": ".", "wires": []}]}
    assert flows.asegurar_prompt(flujo) is flujo     # no toco nada


def test_asegurar_prompt_reconoce_tambien_prompt_fijo():
    flujo = {"nombre": "f", "nodos": [
        {"id": "p", "tool": "prompt_fijo", "args": "cte", "wires": ["a"]},
        {"id": "a", "tool": "listar", "args": ".", "wires": []}]}
    assert flows.asegurar_prompt(flujo) is flujo


def test_asegurar_prompt_con_el_id_ocupado_usa_prompt_0():
    """Un nodo llamado 'prompt' que NO es de entrada (ej. una tool distinta
    con ese id) no se puede pisar: se busca prompt_0, prompt_1, ..."""
    flujo = {"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "listar", "args": ".", "wires": []},
        {"id": "prompt_0", "tool": "listar", "args": "..", "wires": []}]}
    out = flows.asegurar_prompt(flujo)
    assert out["nodos"][0]["id"] == "prompt_1"
    assert sorted(out["nodos"][0]["wires"]) == ["prompt", "prompt_0"]
    assert flows.validar(out)                # ids unicos, DAG valido


def test_asegurar_prompt_no_toca_un_flujo_sin_nodos():
    """Un flujo vacio no se arregla anadiendole un nodo: lo rechaza `validar`
    con su mensaje, que es el que hay que leer."""
    assert flows.asegurar_prompt({"nombre": "f", "nodos": []}) == \
        {"nombre": "f", "nodos": []}


def test_flujoteca_guardar_asegura_el_nodo_de_entrada(tmp_path, monkeypatch):
    """DONDE se hace obligatorio: en el borde de GUARDADO, no en `validar`
    (medido: en validar rompe 126 de 293 tests y vuelve inabribles los flujos
    ya guardados). Cubre /flujoteca nuevo, editar, el editor visual,
    duplicar y restaurar de un golpe."""
    from cognia.agent import flujoteca as F
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "fl"))
    F.guardar({"nombre": "Sin Prompt", "nodos": [
        {"id": "a", "tool": "listar", "args": ".", "wires": []}]},
        nombre="Sin Prompt")
    guardado = F.cargar("Sin Prompt")
    assert guardado["nodos"][0]["tool"] == "prompt"

    # y restaurar NO acumula un segundo nodo de entrada
    F.restaurar("Sin Prompt", 1)
    assert len(F.cargar("Sin Prompt")["nodos"]) == 2


# ---------------------------------------------------------------------------
# 8. Ctrl-C corta el flujo
# ---------------------------------------------------------------------------

def test_cancelado_corta_a_mitad_y_lo_dice():
    """`ejecutar` no consultaba `ctx["_cancelado"]`: Ctrl-C imprimia "corte
    pedido" y el flujo seguia gastando nodos. Se comprueba AL PRINCIPIO de
    cada nodo (la tool en curso termina, como en el loop del agente)."""
    corridos = []
    estado = {"corta": False}

    def run(name, args, ctx):
        corridos.append(args)
        if len(corridos) == 2:
            estado["corta"] = True      # el usuario aprieta Ctrl-C aqui
        return f"RESULTADO eco: {args}"

    flujo = {"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "1", "wires": ["b"]},
        {"id": "b", "tool": "eco", "args": "2", "wires": ["c"]},
        {"id": "c", "tool": "eco", "args": "3", "wires": ["d"]},
        {"id": "d", "tool": "eco", "args": "4", "wires": []}]}
    r = flows.ejecutar(flujo, {"_cancelado": lambda: estado["corta"]}, run)

    assert corridos == ["1", "2"]               # c y d JAMAS corrieron
    assert r["cancelado"] is True
    assert "c" not in r["salidas"] and "d" not in r["salidas"]
    # un flujo cortado NO es un flujo que salio bien, aunque `errores` este
    # vacio justo porque los nodos que faltaban no llegaron a correr
    assert r["ok"] is False
    assert r["errores"] == {}


def test_un_hook_de_cancelacion_roto_no_tumba_el_flujo():
    def boom():
        raise RuntimeError("hook roto")

    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "1", "wires": []}]},
        {"_cancelado": boom},
        lambda n, a, c: f"RESULTADO eco: {a}")
    assert r["cancelado"] is False and r["ok"] is True


def test_sin_hook_de_cancelacion_todo_sigue_igual():
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "1", "wires": []}]}, {},
        lambda n, a, c: f"RESULTADO eco: {a}")
    assert r["cancelado"] is False
    assert set(r) >= {"salidas", "orden", "errores", "saltados", "cacheados",
                      "ok", "entregable", "ficheros", "cancelado",
                      "marcadores_vacios", "args_normalizados"}


def test_el_entregable_salta_los_nodos_de_entrada():
    """Un flujo cuyo ULTIMO nodo topologico es de entrada no puede entregar
    el prompt como si fuera el resultado."""
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "trabajo", "wires": ["prompt"]},
        {"id": "prompt", "tool": "prompt", "args": "el tema", "wires": []}]},
        {}, _run_eco)
    assert r["orden"][-1] == "prompt"
    assert r["entregable"] == "RESULTADO eco: trabajo"


# ---------------------------------------------------------------------------
# 9-10. Los dos bordes del informe de PERMISOS (2026-08-30)
# ---------------------------------------------------------------------------
# 9. Un nodo DENEGADO por el gate contaba como `ok`.
# 10. `saltar_si` miraba la salida CRUDA del nodo de entrada.
#
# Aqui se ejercen con un `run_tool` inyectado porque lo que se fija es la
# MECANICA del motor (que senal se cree, a que nodo se atribuye, que devuelve
# el dict). El mismo par de defectos se mide contra el registro REAL y contra
# el disco en tests/test_flujo_e2e_real.py: sin esa mitad, esto seria otro
# test que pasa con un doble complaciente.


TOOLS_ENTRADA_LOCAL = ("prompt", "prompt_fijo")


def _gate(nombre, args, ctx):
    """Doble del GATE, calcado del real: `sentinel.evaluar_shell` deniega
    consultando `ctx['confirm']` y devolviendo un texto SIN la palabra ERROR
    (por eso la heuristica del motor lo daba por bueno)."""
    if nombre in TOOLS_ENTRADA_LOCAL:
        return TOOLS[nombre]["fn"](args, ctx)
    if nombre != "peligrosa":
        return f"RESULTADO {nombre}: {args}"
    confirm = ctx.get("confirm") if isinstance(ctx, dict) else None
    if callable(confirm) and not confirm("ejecutar comando", args):
        return ("RESULTADO ejecutar: no confirmado por el usuario "
                "(lleva codigo en linea).")
    return "RESULTADO ejecutar: hecho"


_FLUJO_GATE = {"nombre": "g", "nodos": [
    {"id": "prompt", "tool": "prompt", "args": "haz la cosa", "wires": ["p"]},
    {"id": "p", "tool": "peligrosa", "args": "rm -rf /", "wires": []}]}


def test_un_nodo_denegado_no_cuenta_como_ok():
    """El texto de la denegacion no lleva la palabra ERROR, asi que la
    heuristica de texto lo aprobaba: `ok=True`, `errores={}` y la fila verde.
    La deteccion buena es el CANAL: el confirm dijo que no."""
    r = flows.ejecutar(_FLUJO_GATE, {"confirm": lambda *a, **k: False},
                       _gate)

    assert r["denegados"] == ["p"]
    assert r["ok"] is False
    assert "p" in r["errores"]
    assert "ejecutar comando" in r["motivos_denegacion"]["p"]


def test_un_confirm_que_dice_que_si_no_denuncia_nada():
    """La contra-prueba: el envoltorio no puede inventarse denegaciones.
    Mismo flujo, mismo canal, respuesta SI -> flujo limpio."""
    r = flows.ejecutar(_FLUJO_GATE, {"confirm": lambda *a, **k: True}, _gate)

    assert r["denegados"] == []
    assert r["ok"] is True
    assert r["entregable"] == "RESULTADO ejecutar: hecho"


def test_un_nodo_denegado_no_puede_ser_el_entregable():
    """Como el nodo denegado suele ser el ULTIMO del orden topologico, su
    texto se convertia en el entregable y `/flujoteca ejecutar` lo imprimia
    como si fuera el producto del flujo."""
    r = flows.ejecutar(_FLUJO_GATE, {"confirm": lambda *a, **k: False},
                       _gate)

    assert "no confirmado" not in r["entregable"]


def test_un_nodo_que_FALLA_si_entrega_su_error():
    """El limite del arreglo anterior: denegado != fallido. Un nodo que
    revienta sigue ensenando su error como entregable (hay test que lo fija
    en test_flujo_e2e_real); solo el DENEGADO se aparta, porque no produjo
    nada, ni bueno ni malo."""
    def _revienta(nombre, args, ctx):
        return f"RESULTADO {nombre} ERROR: se rompio"

    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "x", "wires": []}]}, {}, _revienta)

    assert r["denegados"] == []
    assert r["ok"] is False
    assert r["entregable"] == "RESULTADO eco ERROR: se rompio"


def test_el_confirm_del_llamador_no_se_queda_envuelto():
    """El motor envuelve `ctx['confirm']` para enterarse, pero el ctx es del
    llamador: un envoltorio pegado ahi para siempre sobreviviria al flujo y
    se acumularia uno por ejecucion."""
    original = lambda *a, **k: False        # noqa: E731
    ctx = {"confirm": original}
    flows.ejecutar(_FLUJO_GATE, ctx, _gate)

    assert ctx["confirm"] is original


def test_la_denegacion_se_atribuye_al_nodo_QUE_LA_PIDIO():
    """Con dos nodos peligrosos y un confirm que solo dice que no al
    segundo, el primero no puede salir manchado."""
    def _confirm(motivo="", detalle=""):
        return "bueno" in str(detalle)

    r = flows.ejecutar({"nombre": "dos", "nodos": [
        {"id": "a", "tool": "peligrosa", "args": "bueno", "wires": ["b"]},
        {"id": "b", "tool": "peligrosa", "args": "malo", "wires": []}]},
        {"confirm": _confirm}, _gate)

    assert r["denegados"] == ["b"], r
    assert "a" not in r["errores"]


def test_denegados_y_motivos_estan_en_el_contrato_del_retorno():
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "a", "tool": "eco", "args": "1", "wires": []}]}, {},
        lambda n, a, c: f"RESULTADO eco: {a}")

    assert set(r) >= {"salidas", "orden", "errores", "saltados", "cacheados",
                      "ok", "entregable", "ficheros", "cancelado",
                      "marcadores_vacios", "args_normalizados",
                      "denegados", "motivos_denegacion"}
    assert r["denegados"] == [] and r["motivos_denegacion"] == {}


def test_saltar_si_no_mira_la_salida_del_nodo_de_entrada():
    """El objetivo que teclea el dueno no puede apagar los nodos del flujo.
    El valor de ejemplo documentado de `saltar_si` es literalmente "ERROR"
    (editor_html.py:158) y la tecla D del editor escribe "RESULTADO"
    (editor_html.py:2726): las dos palabras salen en cualquier log pegado."""
    for condicion in ("ERROR", "RESULTADO"):
        r = flows.ejecutar({"nombre": "f", "nodos": [
            {"id": "prompt", "tool": "prompt", "args": "", "wires": ["w"]},
            {"id": "w", "tool": "eco", "args": "el trabajo",
             "saltar_si": condicion, "wires": []}]},
            {"prompt_flujo": "arregla el ERROR: mira este RESULTADO del log"},
            _run_eco)

        assert r["saltados"] == [], condicion
        assert r["salidas"]["w"] == "RESULTADO eco: el trabajo"
        assert r["ok"] is True


def test_saltar_si_no_mira_la_salida_del_nodo_de_entrada_en_PARALELO():
    """El modo paralelo tiene su propio camino (`vista` por niveles): el
    arreglo tiene que valer en los dos o vale en ninguno."""
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "", "wires": ["w"]},
        {"id": "w", "tool": "eco", "args": "el trabajo",
         "saltar_si": "ERROR", "wires": []}]},
        {"prompt_flujo": "arregla el ERROR de la web"}, _run_eco,
        paralelo=True)

    assert r["saltados"] == []
    assert r["salidas"]["w"] == "RESULTADO eco: el trabajo"


def test_saltar_si_no_mira_un_prompt_FIJO_tampoco():
    """`prompt_fijo` es la constante que escribe el dueno en el editor: mismo
    texto, misma exencion."""
    r = flows.ejecutar({"nombre": "f", "nodos": [
        {"id": "prompt", "tool": "prompt_fijo",
         "args": "revisa el ERROR del build", "wires": ["w"]},
        {"id": "w", "tool": "eco", "args": "el trabajo",
         "saltar_si": "ERROR", "wires": []}]}, {}, _run_eco)

    assert r["saltados"] == []


def test_la_denegacion_se_ve_aunque_la_tool_corra_en_OTRO_HILO():
    """MEDIDO en el camino real del agente y por poco se cuela: `run_tool`
    corre la tool bajo el deadline por tool (harness/timeout_tool), que la
    lanza EN OTRO HILO. Con la constancia solo en un thread-local, el
    `confirm` se llamaba en un hilo donde el marco no existia y la denegacion
    se perdia: el motivo que llegaba al modelo era el de respaldo, y ademas
    decia "esta sesion no tiene canal de confirmacion" teniendolo."""
    from concurrent.futures import ThreadPoolExecutor

    def _en_otro_hilo(nombre, args, ctx):
        if nombre in TOOLS_ENTRADA_LOCAL:
            return TOOLS[nombre]["fn"](args, ctx)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_gate, nombre, args, ctx).result()

    r = flows.ejecutar(_FLUJO_GATE, {"confirm": lambda *a, **k: False},
                       _en_otro_hilo)

    assert r["denegados"] == ["p"], r
    assert r["ok"] is False
    # y el motivo es el REAL (el canal dijo que no), no el de respaldo
    assert "ejecutar comando" in r["motivos_denegacion"]["p"]
    assert "no tiene canal" not in r["motivos_denegacion"]["p"]
