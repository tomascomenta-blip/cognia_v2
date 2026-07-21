# -*- coding: utf-8 -*-
"""Regresión de la suite congelada G6 (cierres-con-salida) y su diagnóstico.

Todo con FAKES: acá NUNCA se toca el modelo real ni el server :8088 (regla
dura del repo: el orquestador corre las mediciones con modelo, serializadas).
Cubre: la suite parsea y está congelada (sha256), ningún ítem es trivial
(un cierre vacío jamás pasa) ni adivinable por eco del enunciado, la
aritmética de los oráculos se re-computa desde check_expr, el clasificador
distingue las 4 clases, y el mecanismo que DESACTIVA el parche E8 funciona.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cognia_v3" /
                       "eval" / "suites"))

from suite_oracle import carga_suite, cierre_pass, numeros_todos, oracle_pass

from cognia_v3.eval.diag_cierres import (
    SUITE, SUITE_SHA256, clasificar_cierre, desactivar_parche_cierre,
    espiar_run_tool, menciona_salida_o_fallo, reporta_valor_ajeno,
)

ITEMS = carga_suite(str(SUITE))


# ── la suite: estructura, freeze, no-trivialidad, no-adivinanza ─────────────

def test_suite_estructura():
    assert len(ITEMS) == 50
    ids = [it["id"] for it in ITEMS]
    assert len(set(ids)) == 50
    assert all(it["gate"] == "G6" for it in ITEMS)
    doms = {}
    for it in ITEMS:
        doms[it["dominio"]] = doms.get(it["dominio"], 0) + 1
    # las 3 sub-clases del plan, todas presentes
    assert doms == {"cierre_output": 22, "multi_tool": 14,
                    "error_accionable": 14}
    es = sum(1 for it in ITEMS if it["idioma"] == "es")
    assert 20 <= es <= 30  # mezcla es/en real, no monolingüe


def test_suite_congelada_sha256():
    """El freeze es vinculante: editar la suite rompe este test (y el ABORT
    de diag_cierres.main). Cambio de suite = suite NUEVA con otro nombre."""
    h = hashlib.sha256(SUITE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert h == SUITE_SHA256


def test_ningun_item_trivial():
    """Un cierre vacío ('listo, tarea completada') NUNCA satisface un oráculo:
    si lo hiciera, el ítem mediría nada."""
    vacios = ["", "Listo, tarea completada.",
              "Done! Task completed successfully.",
              "Listo. La tarea se completó con éxito.", "OK, ya está hecho."]
    for it in ITEMS:
        for v in vacios:
            assert not cierre_pass(v, it["oracle"]), \
                f"{it['id']}: cierre vacío {v!r} PASA -> ítem trivial"


def test_ningun_item_adivinable_por_eco():
    """Si el ECO del enunciado satisface el oráculo, el ítem mide adivinanza
    (el modelo puede 'acertar' sin ejecutar la tool) -> INVÁLIDO."""
    for it in ITEMS:
        assert not cierre_pass(it["prompt"], it["oracle"]), \
            f"{it['id']}: el eco del prompt PASA -> adivinable sin ejecutar"


def test_aritmetica_recomputada():
    """Los oráculos numéricos se RE-COMPUTAN desde check_expr (expresión sobre
    S = contenidos del setup). Caza cualquier número mal calculado a mano."""
    con_expr = [it for it in ITEMS if "check_expr" in it]
    assert len(con_expr) >= 20  # el grueso de los ítems numéricos lo trae
    for it in con_expr:
        S = {s["path"]: s["content"] for s in it.get("setup", [])}
        val = eval(it["check_expr"], {"__builtins__": {}},
                   {"S": S, "len": len, "sum": sum, "range": range,
                    "int": int, "float": float})
        assert abs(float(val) - float(it["oracle"]["number"])) <= 1e-6, \
            f"{it['id']}: check_expr={val} != number={it['oracle']['number']}"


def test_setup_paths_seguros():
    for it in ITEMS:
        for s in it.get("setup", []):
            p = s["path"]
            assert ".." not in p and ":" not in p
            assert not p.startswith(("/", "\\"))
            assert s["content"], f"{it['id']}: setup {p} vacío"


# ── cierre_pass: el número puede ir en cualquier posición ───────────────────

def test_cierre_pass_number_en_cualquier_posicion():
    # razón de existir de cierre_pass: oracle_pass exige el ÚLTIMO número
    r = "El resultado es 350, lo verifiqué 2 veces."
    assert cierre_pass(r, {"number": 350})
    assert not oracle_pass(r, {"number": 350})  # regla del último: 2
    assert not cierre_pass("El resultado es 351.", {"number": 350})


def test_cierre_pass_separadores_de_miles():
    assert cierre_pass("The result is 13,952,011.", {"number": 13952011})
    assert cierre_pass("Da 13 952 011 en total", {"number": 13952011})
    # sin fallback para no-enteros: el match exacto sigue mandando
    assert cierre_pass("mide 12,5 cm", {"number": 12.5})
    assert not cierre_pass("son 13952 en total", {"number": 13952011})


def test_cierre_pass_must_y_veto():
    o = {"must_all": ["config_rota"], "must_any": ["invalido", "no es valido"],
         "not_any": ["sin errores"]}
    assert cierre_pass("config_rota.json no es válido: falta una coma", o)
    assert not cierre_pass("config_rota.json revisado", o)      # sin must_any
    assert not cierre_pass("no es válido el archivo", o)         # sin must_all
    assert not cierre_pass("config_rota es inválido pero quedó sin errores", o)


def test_oracle_pass_intacto():
    """cierre_pass NO reemplaza a oracle_pass: la semántica del ÚLTIMO número
    de las suites G1/G2R/G5 sigue igual (regresión del 'no rompas')."""
    assert oracle_pass("El cálculo da 15% de 200 = 30", {"number": 30})
    assert not oracle_pass("Son 30. Ver página 12.", {"number": 30})


# ── clasificador por clases (fakes de cada clase) ───────────────────────────

_O_NUM = {"number": 13951811}
_P_NUM = 'Ejecutá: python -c "print(4783 * 2917)" y decime qué imprime.'


def test_clasifica_pasa():
    assert clasificar_cierre("La salida fue 13951811.", _O_NUM, _P_NUM) == "pasa"
    assert clasificar_cierre("El script imprimió 13,951,811 al final.",
                             _O_NUM, _P_NUM) == "pasa"


def test_clasifica_vacio():
    # cierra sin reportar nada: ni valor, ni mención de salida -> FORMATO
    assert clasificar_cierre("Listo, ya ejecuté el script. Tarea completada.",
                             _O_NUM, _P_NUM) == "vacio"
    assert clasificar_cierre("", _O_NUM, _P_NUM) == "vacio"
    assert clasificar_cierre("Done. Task completed.", _O_NUM, _P_NUM) == "vacio"


def test_clasifica_parcial():
    # menciona que HUBO salida pero no da el valor -> FORMATO
    assert clasificar_cierre("El script corrió y produjo la salida esperada.",
                             _O_NUM, _P_NUM) == "parcial"
    assert clasificar_cierre("The command printed the result correctly.",
                             _O_NUM, _P_NUM) == "parcial"


def test_clasifica_incorrecto():
    # afirma un valor concreto y está MAL -> CAPACIDAD
    assert clasificar_cierre("La salida fue 99887.", _O_NUM, _P_NUM) == "incorrecto"
    # número del enunciado (eco) NO cuenta como valor afirmado: cae en FORMATO
    # (parcial por el 'print' ecoado — nunca 'incorrecto' ni 'pasa')
    assert clasificar_cierre("Ejecuté print(4783 * 2917) como pediste, listo.",
                             _O_NUM, _P_NUM) in ("vacio", "parcial")
    # token con guiones alucinado (oráculo de texto)
    o = {"must_any": ["nube-8842"]}
    p = "Leé codigo_acceso.txt y decime el código."
    assert clasificar_cierre("El código es roca-1122.", o, p) == "incorrecto"


def test_clasifica_error_accionable():
    o = {"must_all": ["informe_trimestral_zz"],
         "must_any": ["no existe", "not found", "no se encontr", "errno"]}
    p = "Leé el archivo informe_trimestral_zz.txt y decime qué contiene."
    # relaya el fallo con el archivo -> pasa
    assert clasificar_cierre(
        "No pude leerlo: informe_trimestral_zz.txt no existe.", o, p) == "pasa"
    # dice que falló pero sin lo accionable -> parcial (FORMATO)
    assert clasificar_cierre("Hubo un error al leer el archivo.", o, p) == "parcial"
    # miente que terminó -> vacio (FORMATO)
    assert clasificar_cierre("Listo, tarea completada.", o, p) == "vacio"
    # contracciones inglesas NO son 'valor citado' (sesgo anti-CAPACIDAD)
    assert clasificar_cierre("It failed, the file doesn't seem readable and I "
                             "couldn't open it.", o, p) == "parcial"


def test_clasifica_prioridad_incorrecto_sobre_parcial():
    # trae palabra de salida Y un valor equivocado: manda el valor -> incorrecto
    assert clasificar_cierre("El resultado fue 55555.", _O_NUM, _P_NUM) == "incorrecto"


def test_reporta_valor_ajeno_y_mencion():
    assert reporta_valor_ajeno("da 4242", "calculá algo")
    assert not reporta_valor_ajeno("usé 4783 del enunciado", _P_NUM)
    assert not reporta_valor_ajeno("en 3 pasos quedó", "hacé x")  # <10 = ruido
    assert menciona_salida_o_fallo("la salida está arriba")
    assert not menciona_salida_o_fallo("listo, hecho")


# ── el mecanismo que desactiva el parche E8 (regresión del instrumento) ─────

def test_desactivar_parche_cierre():
    import cognia.agent.loop as loop_mod
    # estado real de producción: la tarea pide ejecutar y hay salida en history
    assert loop_mod.task_pide_ejecucion("ejecutá el script x.py")
    assert loop_mod.salida_de_ejecucion(["RESULTADO ejecutar: 42"]) == "42"
    restore = desactivar_parche_cierre()
    try:
        # con el patch, el gate de los 3 sitios de cli.py queda apagado
        assert not loop_mod.task_pide_ejecucion("ejecutá el script x.py")
        assert loop_mod.salida_de_ejecucion(["RESULTADO ejecutar: 42"]) == ""
    finally:
        restore()
    # y restore() devuelve producción intacta
    assert loop_mod.task_pide_ejecucion("ejecutá el script x.py")
    assert loop_mod.salida_de_ejecucion(["RESULTADO ejecutar: 42"]) == "42"


def test_espia_run_tool_registra_y_restaura():
    import cognia.agent.tools as tools_mod
    orig = tools_mod.run_tool
    tools_mod.run_tool = lambda n, a, c: f"RESULTADO {n}: fake-ok"  # fake, sin I/O
    try:
        traza = []
        restore = espiar_run_tool(traza)
        out = tools_mod.run_tool("calcular", "2+3", {})
        assert out == "RESULTADO calcular: fake-ok"
        assert traza == [{"tool": "calcular", "ok": True,
                          "head": "RESULTADO calcular: fake-ok"}]
        restore()
        assert tools_mod.run_tool("x", "", {}) == "RESULTADO x: fake-ok"
        assert len(traza) == 1  # ya no espía
    finally:
        tools_mod.run_tool = orig


def test_numeros_todos():
    assert numeros_todos("da 12 y 30,5 y −2") == [12.0, 30.5, -2.0]
    assert numeros_todos("sin cifras") == []


# ── integración: el loop REAL de cli.py con orquestador FAKE (cero modelo) ──
# Demuestra el porqué del diag: con el parche E8 puesto un cierre "listo,
# tarea completada" igual sale con la salida real anexada (señal CERO para
# medir hábito); con desactivar_parche_cierre() el hábito nativo queda
# expuesto y clasifica 'vacio'.

class _InferRes:
    def __init__(self, text):
        self.text = text


class _FakeOrch:
    """Orquestador fake: pasos ACCION guionados; nunca toca modelo/server."""
    def __init__(self, guiones):
        self._guiones = list(guiones)
        self._llama = None

    def _try_load_llama(self):
        return None

    def infer(self, prompt, **kw):
        if "Siguiente ACCION:" in prompt and self._guiones:
            return _InferRes(self._guiones.pop(0))
        return _InferRes("0")  # decompose / wants_more / otros

    def as_ai(self):
        class _AI:  # mínimo que _run_agent_task necesita
            pass
        ai = _AI()
        ai._orchestrator = self
        return ai


_GUION = ["ACCION: ejecutar echo 6204787",
          "ACCION: responder Listo, tarea completada."]
_TAREA = "Ejecutá el comando echo 6204787 y reportá la salida."


def _corre_loop(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    orch = _FakeOrch(_GUION)
    return str(_cli._run_agent_task(orch.as_ai(), _TAREA, lambda s: None,
                                    max_steps=4) or "")


def test_loop_con_parche_tapa_el_habito(tmp_path, monkeypatch):
    # SIN desactivar: el post-loop de cli.py anexa la salida real al cierre
    # vacío -> mediría el parche, no el modelo (por eso el diag lo apaga).
    resp = _corre_loop(tmp_path, monkeypatch)
    assert "6204787" in resp and "Salida de la ejecución" in resp
    assert clasificar_cierre(resp, {"number": 6204787}, _TAREA) == "pasa"


def test_loop_sin_parche_expone_el_habito(tmp_path, monkeypatch):
    # CON desactivar_parche_cierre(): el mismo guion cierra pelado y el
    # clasificador ve el hábito nativo (vacio = FORMATO entrenable).
    restore = desactivar_parche_cierre()
    try:
        resp = _corre_loop(tmp_path, monkeypatch)
    finally:
        restore()
    assert resp.strip() == "Listo, tarea completada."
    assert clasificar_cierre(resp, {"number": 6204787}, _TAREA) == "vacio"
