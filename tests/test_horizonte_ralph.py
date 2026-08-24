"""
Tests del contrato RALPH del modo horizonte (cognia/agent/horizonte.py) SIN
GPU: validador del report de 5 campos (los 3 estados con sus reglas, claves
exactas, trim, cota del traspaso), fusion anti-rendicion de blocked, relanzo
UNA vez por report invalido, texto de cierre 'reporta' y el cableado en el
outer loop (pedir_report inyectable) + la puerta /horizonte del CLI.
"""

import json

import pytest

from cognia.agent import estado_tarea as et
from cognia.agent import horizonte as hz
from cognia.agent.horizonte import (
    HandoffDemasiadoGrande, ReportInvalido, ciclos_con_contrato,
    consumir_report, fusionar_blocked, parsear_report, prompt_de_ronda,
    serializar_handoff, texto_cierre, validar_report)


@pytest.fixture
def tareas_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path / "estado"))
    monkeypatch.delenv("COGNIA_HORIZONTE_HANDOFF_MAX", raising=False)
    return tmp_path


def _rep(**kw):
    base = {"status": "continue", "summary": "hice algo",
            "evidence": [], "nextSteps": ["seguir"], "blocker": ""}
    base.update(kw)
    return base


# ── validador: los 3 estados con sus reglas ─────────────────────────────────
def test_continue_valido_y_sus_reglas():
    assert validar_report(_rep()) is not None
    with pytest.raises(ReportInvalido, match="nextSteps no vacio"):
        validar_report(_rep(nextSteps=[]))
    with pytest.raises(ReportInvalido, match="blocker vacio"):
        validar_report(_rep(blocker="algo"))


def test_complete_exige_evidencia_sin_pasos_ni_blocker():
    ok = _rep(status="complete", evidence=["existe a.py"], nextSteps=[])
    assert validar_report(ok) is ok
    with pytest.raises(ReportInvalido, match="evidence no vacio"):
        validar_report(_rep(status="complete", evidence=[], nextSteps=[]))
    with pytest.raises(ReportInvalido, match="nextSteps vacio"):
        validar_report(_rep(status="complete", evidence=["x"],
                            nextSteps=["mas"]))
    with pytest.raises(ReportInvalido, match="blocker vacio"):
        validar_report(_rep(status="complete", evidence=["x"], nextSteps=[],
                            blocker="b"))


def test_blocked_exige_blocker():
    assert validar_report(_rep(status="blocked", blocker="sin permisos"))
    with pytest.raises(ReportInvalido, match="blocker no vacio"):
        validar_report(_rep(status="blocked", blocker=""))


def test_claves_exactas_por_sort_join():
    with pytest.raises(ReportInvalido, match="claves"):
        validar_report({**_rep(), "extra": 1})
    faltante = _rep()
    del faltante["blocker"]
    with pytest.raises(ReportInvalido, match="claves"):
        validar_report(faltante)
    with pytest.raises(ReportInvalido, match="objeto JSON"):
        validar_report(["lista"])
    with pytest.raises(ReportInvalido, match="status"):
        validar_report(_rep(status="done"))


def test_strings_normalizados_y_no_vacios():
    with pytest.raises(ReportInvalido, match="normalizado"):
        validar_report(_rep(summary=" hice algo"))
    with pytest.raises(ReportInvalido, match="vacio"):
        validar_report(_rep(summary=""))
    with pytest.raises(ReportInvalido, match=r"nextSteps\[0\]"):
        validar_report(_rep(nextSteps=["paso "]))
    with pytest.raises(ReportInvalido, match="evidence"):
        validar_report(_rep(evidence="no es lista"))
    with pytest.raises(ReportInvalido, match="string"):
        validar_report(_rep(summary=5))


def test_parsear_tolera_fence_y_rechaza_basura():
    r = parsear_report("```json\n" + json.dumps(_rep()) + "\n```")
    assert r["status"] == "continue"
    with pytest.raises(ReportInvalido, match="JSON"):
        parsear_report("no soy json")
    with pytest.raises(ReportInvalido, match="vacia"):
        parsear_report("   ")


def test_cota_del_handoff_error_claro(monkeypatch):
    r = _rep(summary="x" * 3000)
    with pytest.raises(HandoffDemasiadoGrande) as exc:
        serializar_handoff(r, max_chars=1000)
    assert "tope es 1000" in str(exc.value)
    assert "horizonte_handoff_max" in str(exc.value)
    assert len(serializar_handoff(r, max_chars=16384)) > 3000
    monkeypatch.setenv("COGNIA_HORIZONTE_HANDOFF_MAX", "600")
    with pytest.raises(HandoffDemasiadoGrande, match="tope es 600"):
        consumir_report(r)
    monkeypatch.setenv("COGNIA_HORIZONTE_HANDOFF_MAX", "basura")
    assert hz.handoff_max_env() == hz.HANDOFF_MAX


def test_consumir_es_segunda_validacion():
    with pytest.raises(ReportInvalido):
        consumir_report(_rep(status="complete", evidence=[], nextSteps=[]))


# ── fusion anti-rendicion ───────────────────────────────────────────────────
def test_blocked_antes_de_3_rondas_se_vuelve_continue_anotado():
    r = _rep(status="blocked", blocker="no hay red", nextSteps=[])
    f1, racha, anot = fusionar_blocked(r, 0, "")
    assert f1["status"] == "continue" and f1["blocker"] == ""
    assert racha == 1 and anot == "no hay red"
    assert "BLOQUEO REPORTADO" in f1["summary"] and "no hay red" in f1["summary"]
    assert f1["nextSteps"]                       # continue exige pasos
    validar_report(f1)                           # el fusionado es valido
    f2, racha, _ = fusionar_blocked(r, racha, "no hay red")
    assert f2["status"] == "continue" and racha == 2
    f3, racha, anot = fusionar_blocked(r, racha, "no hay red")
    assert f3["status"] == "blocked" and racha == 3 and anot == ""


def test_blocker_distinto_reinicia_la_racha():
    r = _rep(status="blocked", blocker="otro", nextSteps=[])
    _, racha, _ = fusionar_blocked(r, 2, "no hay red")
    assert racha == 1


def test_continue_no_se_fusiona():
    r = _rep()
    assert fusionar_blocked(r, 2, "x") == (r, 0, "")


# ── texto de cierre ─────────────────────────────────────────────────────────
def test_cierre_dice_reporta_nunca_completado_a_secas():
    t = texto_cierre(_rep(status="complete", evidence=["a.py existe",
                                                       "pytest 3 passed"],
                          nextSteps=[]), 2)
    assert t.startswith("el worker reporta completado (2 rondas)")
    assert "a.py existe" in t and "pytest 3 passed" in t
    assert "NO verificada" in t
    assert texto_cierre(_rep(), 1).startswith(
        "el worker reporta que sigue pendiente (1 ronda)")
    assert "bloqueo" in texto_cierre(_rep(status="blocked", blocker="b"), 3)
    assert "no entrego un report valido" in texto_cierre(None, 2, "motivo x")
    assert "motivo x" in texto_cierre(None, 2, "motivo x")


def test_prompt_de_ronda_trae_las_frases_clave():
    p = prompt_de_ronda(2, 3, "SOLO FALTA:\n- b.py", '{"status": "continue"}',
                        blocker_anotado="sin red", contrato_faltan=1,
                        report_previo_status="complete")
    for frase in ("WORKER FRESCO", "Ronda 2 de 3", "INMUTABLE",
                  "FUENTE DE VERDAD", "traspaso ACOTADO", "SOLO FALTA",
                  "TRASPASO del worker anterior", "BLOQUEO REPORTADO",
                  "reporto 'complete'"):
        assert frase in p, frase


# ── el outer loop con pedir_report inyectado ────────────────────────────────
class BucleFake:
    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []

    def __call__(self, task, system, completar, schemas, args_legacy,
                 mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                 history, trace, print_fn, max_turns):
        paso = self.guion[len(self.llamadas)]
        self.llamadas.append(list(history))
        for p in paso.get("crea", []):
            p.write_text("x\n", encoding="utf-8")
            history.append(f"RESULTADO escribir_archivo: OK escrito {p}")
            trace.append({"action": "escribir_archivo", "args": f"{p} | x",
                          "ok": True, "result_head": "ok"})
        nat = {"texto": "cerrado", "pasos": 1, "ok": True, "tokens": 10,
               "finish": "stop"}
        nat.update(paso.get("nat", {}))
        return nat


class PedidorFake:
    """Guion de salidas crudas por llamada; registra los errores citados."""

    def __init__(self, salidas):
        self.salidas = list(salidas)
        self.errores = []

    def __call__(self, hist_ciclo, texto_final, error_previo):
        self.errores.append(error_previo)
        return self.salidas.pop(0)


def _correr(fake, pedidor, criterios, max_ciclos=3, tarea="tarea"):
    estado = et.nuevo("20260824-120000-ralph", tarea, criterios)
    history = [f"TAREA: {tarea}"]
    lineas = []
    out = ciclos_con_contrato(
        tarea, "system", None, [], None, None, None, None, {}, {},
        history, [], lambda s: lineas.append(s), 8,
        criterios=criterios, task_id="20260824-120000-ralph", estado=estado,
        max_ciclos=max_ciclos, bucle=fake, pedir_report=pedidor)
    return out, estado, history, lineas


def _crit(*paths):
    return [{"kind": "file_exists", "path": str(p),
             "description": f"debe existir {p}"} for p in paths]


def test_sin_criterios_gobierna_el_report(tareas_tmp):
    fake = BucleFake([{}, {}, {}])
    ped = PedidorFake([
        json.dumps(_rep(summary="ronda 1", nextSteps=["crear b"])),
        json.dumps(_rep(status="complete", evidence=["b creado"],
                        nextSteps=[])),
    ])
    out, estado, _, lineas = _correr(fake, ped, [])
    assert out["ciclos"] == 2 and out["contrato_ok"] is None
    assert out["report"]["status"] == "complete"
    assert out["cierre_worker"].startswith("el worker reporta completado (2 rondas)")
    assert "b creado" in out["cierre_worker"]
    # El worker 2 recibio el prompt de ronda con el traspaso del 1.
    h2 = fake.llamadas[1]
    assert "WORKER FRESCO" in h2[1] and "Ronda 2 de 3" in h2[1]
    assert '"summary": "ronda 1"' in h2[1]
    # Persistido en el estado durable, ronda a ronda.
    assert estado["ciclos"][0]["report"]["summary"] == "ronda 1"
    assert estado["ciclos"][1]["report"]["status"] == "complete"
    assert estado["cierre_worker"] == out["cierre_worker"]
    assert any("reporta completado" in l for l in lineas)


def test_complete_sin_evidencia_se_relanza_una_vez_citando_el_error(tareas_tmp):
    fake = BucleFake([{}])
    ped = PedidorFake([
        json.dumps(_rep(status="complete", evidence=[], nextSteps=[])),
        json.dumps(_rep(status="complete", evidence=["ahora si"],
                        nextSteps=[])),
    ])
    out, estado, _, lineas = _correr(fake, ped, [], max_ciclos=1)
    assert ped.errores[0] == ""
    assert "evidence no vacio" in ped.errores[1]        # error CITADO
    assert out["report"]["evidence"] == ["ahora si"]
    assert any("lo vuelvo a pedir" in l for l in lineas)


def test_report_invalido_dos_veces_ronda_sin_report(tareas_tmp):
    fake = BucleFake([{}, {}])
    ped = PedidorFake(["basura", "{\"status\": \"complete\"}"])
    out, estado, _, lineas = _correr(fake, ped, [], max_ciclos=2)
    assert out["report"] is None and out["ciclos"] == 1   # sin continue: para
    assert estado["ciclos"][0]["report"] is None
    assert "claves" in estado["ciclos"][0]["report_error"]
    assert out["cierre_worker"].startswith("el worker no entrego un report valido")
    assert any("SIN report valido tras 2 intentos" in l for l in lineas)


def test_handoff_por_encima_de_la_cota_se_cita_y_reintenta(tareas_tmp):
    fake = BucleFake([{}, {}])
    ped = PedidorFake([
        json.dumps(_rep(summary="x" * 900)),
        json.dumps(_rep(summary="corto")),
        json.dumps(_rep(status="complete", evidence=["e"], nextSteps=[])),
    ])
    estado = et.nuevo("20260824-120001-cota", "t", [])
    out = ciclos_con_contrato(
        "t", "s", None, [], None, None, None, None, {}, {},
        ["TAREA: t"], [], lambda s: None, 8, criterios=[],
        task_id="20260824-120001-cota", estado=estado, max_ciclos=2,
        bucle=fake, pedir_report=ped, handoff_max=600)
    assert "tope es 600" in ped.errores[1]
    assert out["ciclos"] == 2 and out["report"]["status"] == "complete"


def test_blocked_temprano_no_corta_y_se_anota_en_la_ronda_siguiente(tareas_tmp):
    a = tareas_tmp / "a.py"
    fake = BucleFake([{}, {"crea": [a]}])
    ped = PedidorFake([
        json.dumps(_rep(status="blocked", blocker="sin red", nextSteps=[])),
        json.dumps(_rep(status="complete", evidence=["a.py"], nextSteps=[])),
    ])
    out, estado, _, _ = _correr(fake, ped, _crit(a), max_ciclos=2)
    assert out["ciclos"] == 2 and out["contrato_ok"] is True
    h2 = fake.llamadas[1]
    assert "BLOQUEO REPORTADO" in h2[1] and "sin red" in h2[1]
    assert estado["ciclos"][0]["report"]["status"] == "continue"


def test_blocked_aceptado_tras_3_rondas_corta(tareas_tmp):
    a = tareas_tmp / "nunca.py"
    fake = BucleFake([{}, {}, {}, {}])
    bl = json.dumps(_rep(status="blocked", blocker="sin red", nextSteps=[]))
    ped = PedidorFake([bl, bl, bl, bl])
    # El contrato nunca sube: el corte por progreso monotono llegaria en la
    # ronda 2; para ver la racha de 3 se necesita que el report gobierne.
    out, estado, _, lineas = _correr(fake, ped, [], max_ciclos=4)
    # sin criterios: blocked fusionado = continue (rondas 1 y 2), aceptado en
    # la 3 -> corta ahi, la 4 no corre
    assert out["ciclos"] == 3 and out["report"]["status"] == "blocked"
    assert out["cierre_worker"].startswith("el worker reporta bloqueo (3 rondas)")
    assert "sin red" in out["cierre_worker"]


def test_complete_del_worker_no_manda_sobre_el_contrato(tareas_tmp):
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    fake = BucleFake([{"crea": [a]}, {"crea": [b]}])
    ped = PedidorFake([
        json.dumps(_rep(status="complete", evidence=["a.py"], nextSteps=[])),
        json.dumps(_rep(status="complete", evidence=["b.py"], nextSteps=[])),
    ])
    out, _, _, _ = _correr(fake, ped, _crit(a, b), max_ciclos=2)
    assert out["ciclos"] == 2 and out["contrato_ok"] is True
    h2 = fake.llamadas[1]
    assert "reporto 'complete'" in h2[1] and "SOLO FALTA" in h2[1]
    assert "SI verifico" in out["cierre_worker"]


def test_sin_pedidor_ni_completar_comportamiento_de_antes(tareas_tmp):
    fake = BucleFake([{}, {}])
    out, estado, _, _ = _correr(fake, None, [], max_ciclos=2)
    assert out["ciclos"] == 1 and out["report"] is None
    assert "sin pedidor" in estado["ciclos"][0]["report_error"]


def test_pedir_report_por_chat_arma_response_format_estricto():
    llamadas = []

    class Resp:
        error = ""
        texto = json.dumps(_rep())

    def completar(mensajes, tools=None, **kw):
        llamadas.append((mensajes, tools, kw))
        return Resp()

    txt = hz.pedir_report_por_chat(completar, "sys", ["TAREA: t", "RESULTADO x"],
                                   "fin", {"url": "http://u", "max_tokens": 8192},
                                   error_previo="faltaba evidence")
    assert json.loads(txt)["status"] == "continue"
    mensajes, tools, kw = llamadas[0]
    assert tools is None and kw["url"] == "http://u" and kw["max_tokens"] == 8192
    # sin pensamiento: el report resume, no decide (y el thinking lo vaciaba)
    assert kw["kwargs_plantilla"] == {"enable_thinking": False}
    assert kw["razonador"] is False
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert kw["response_format"]["json_schema"]["schema"] is hz.SCHEMA_REPORT
    assert "RESULTADO x" in mensajes[1]["content"]
    assert "faltaba evidence" in mensajes[2]["content"]
    assert "5 claves" in mensajes[2]["content"]

    class RespMal:
        error = "HTTP 500"
        texto = ""
    with pytest.raises(ReportInvalido, match="HTTP 500"):
        hz.pedir_report_por_chat(lambda *a, **k: RespMal(), "", ["t"], "", {})

    class RespVacia:
        error = ""
        texto = "  "
        finish_reason = "length"
    with pytest.raises(ReportInvalido, match="finish=length"):
        hz.pedir_report_por_chat(lambda *a, **k: RespVacia(), "", ["t"], "", {})


# ── puerta del CLI ──────────────────────────────────────────────────────────
def test_puerta_horizonte_en_el_cli(tmp_path, monkeypatch, capsys):
    from cognia import cli
    assert "/horizonte" in cli._CMD_DESCRIPTIONS
    assert "/horizonte" in cli._CMD_DETAILS
    assert "reporta completado" in cli._CMD_DETAILS["/horizonte"]
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path / "vacio"))
    for var in (hz.FLAG, hz.ENV_CICLOS, hz.ENV_HANDOFF_MAX):
        # setenv ANTES de delenv: asi monkeypatch restaura la AUSENCIA y la
        # env que siembra el CLI no se filtra a los tests siguientes.
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)
    hz._ULTIMA.clear()
    cli._slash_horizonte("on")
    assert cli._load_config()["horizonte"] == "on"
    assert hz.habilitado() and cli._env_es_sembrada(hz.FLAG)
    cli._slash_horizonte("rondas 3")
    assert cli._load_config()["horizonte_max_rondas"] == "3"
    assert hz.max_ciclos_env() == 3
    cli._slash_horizonte("handoff 100")           # invalido: < 512
    assert cli._load_config()["horizonte_handoff_max"] == "16384"
    cli._slash_horizonte("handoff 2048")
    assert hz.handoff_max_env() == 2048
    capsys.readouterr()
    cli._slash_horizonte("estado")
    salida = capsys.readouterr().out
    assert "modo horizonte: ACTIVO" in salida and "config 'horizonte'" in salida
    assert "rondas max: 3" in salida and "traspaso max: 2048" in salida
    assert "ultima corrida: ninguna" in salida
    cli._slash_horizonte("off")
    assert not hz.habilitado()
    # Desde DISCO, saltando directorios sin estado.json: la raiz la comparte
    # TX ('tx-...' ordena despues de '2026...') y tomar el primero a secas
    # decia 'ninguna' con una corrida real en disco (cazado tecleando).
    est = et.nuevo("20260824-100000-vieja", "tarea vieja", [])
    et.registrar_ciclo(est, 1, {"texto": "t"}, None, [], "",
                       report=_rep(summary="resumen viejo"))
    est["cierre_worker"] = "el worker reporta que sigue pendiente (1 ronda)"
    et.guardar(est)
    (et.dir_tareas() / "tx-20260901-000000").mkdir()
    capsys.readouterr()
    cli._slash_horizonte("estado")
    salida = capsys.readouterr().out
    assert "20260824-100000-vieja" in salida
    assert "resumen viejo" in salida and "reporta que sigue pendiente" in salida


def test_aplicar_config_horizonte_siembra_y_valida(tmp_path, monkeypatch):
    from cognia import cli
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    for var in (hz.FLAG, hz.ENV_CICLOS, hz.ENV_HANDOFF_MAX):
        # setenv ANTES de delenv: asi monkeypatch restaura la AUSENCIA y la
        # env que siembra el CLI no se filtra a los tests siguientes.
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)
    cli._save_config({**cli._CONFIG_DEFAULTS, "horizonte": "on",
                      "horizonte_max_rondas": "2",
                      "horizonte_handoff_max": "12"})     # 12 < 512: invalido
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, det="": avisos.append((via, det)))
    cli._aplicar_config_horizonte()
    assert hz.habilitado() and hz.max_ciclos_env() == 2
    assert hz.handoff_max_env() == 16384                  # default sembrado
    assert any("horizonte_handoff_max" in d for _, d in avisos)
    assert cli._env_es_sembrada(hz.FLAG)
    # la env del usuario NO se pisa
    monkeypatch.setenv(hz.FLAG, "0")
    cli._aplicar_config_horizonte()
    assert not hz.habilitado()
