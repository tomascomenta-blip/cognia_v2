"""
Tests del MODO SOMBRA del disyuntor (el pendiente del plan
INVESTIGACION_Y_ANTIRUIDO): registrar los disparos sin actuar, para calibrar
los umbrales (Aider/OpenHands) con datos propios, y el informe de aceptacion
que responde "¿que fraccion de disparos precedio a un bucle realmente
esteril?" (umbral 60%).

Offline: no network, no LLM.
"""

import json
import sys
import types

import pytest

from cognia.agent import tool_synthesis as TS
from cognia.disciplina import __main__ as CLI


# Un comando que falla SIEMPRE con el mismo sintoma: misma huella en cada
# intento, que es la condicion del D6.
FALLA_FIJA = (f'"{sys.executable}" -c '
              f'"import sys; print(\'AssertionError: rota fija\'); sys.exit(1)"')
PASA = f'"{sys.executable}" -c "print(\'ok\')"'


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(CLI, "DIR_ESTADO", tmp_path / "disciplina")
    monkeypatch.setattr(TS, "GENERATED_DIR", tmp_path / "gen")
    monkeypatch.setattr(TS, "MANIFEST_PATH", tmp_path / "gen" / "_manifest.json")
    monkeypatch.setattr(TS, "DISCIPLINA_DIR", tmp_path / "disciplina")
    monkeypatch.delenv("COGNIA_DISCIPLINA_SOMBRA", raising=False)
    return tmp_path


def _eventos(tmp_path):
    out = []
    for ruta in sorted((tmp_path / "disciplina").glob("*.jsonl")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            reg = json.loads(linea)
            if reg.get("evento"):
                out.append(reg)
    return out


# ── CLI: --sombra registra sin cortar ───────────────────────────────────

def test_sombra_registra_el_disparo_pero_no_corta(_aislar):
    assert CLI.main(["verificar", "--sombra", FALLA_FIJA]) == 1
    rc = CLI.main(["verificar", "--sombra", FALLA_FIJA])
    assert rc == 1, "en sombra el corte NO actua: exit de fallo normal, no 3"
    evs = _eventos(_aislar)
    assert [e["evento"] for e in evs] == ["disparo_sombra"]
    assert evs[0]["motivo"] == "D6"


def test_sin_sombra_corta_y_ademas_persiste_el_disparo(_aislar):
    assert CLI.main(["verificar", FALLA_FIJA]) == 1
    assert CLI.main(["verificar", FALLA_FIJA]) == 3
    evs = _eventos(_aislar)
    assert [e["evento"] for e in evs] == ["disparo"], \
        "el corte real tambien queda en el JSONL: sin eso no hay calibracion"


def test_los_eventos_no_contaminan_la_ventana_de_intentos(_aislar):
    """
    Regresion: _cargar reconstruye el disyuntor desde el JSONL. Una linea de
    evento leida como Intento (clave vacia, ok=False) seria un intento
    fantasma que puede disparar el corte por si solo.
    """
    CLI.main(["verificar", "--sombra", FALLA_FIJA])
    CLI.main(["verificar", "--sombra", FALLA_FIJA])   # deja un disparo_sombra
    d = CLI._cargar(FALLA_FIJA)
    assert len(d.intentos) == 2, "los 2 intentos reales, sin fantasmas"
    assert all(i.clave for i in d.intentos)


def test_verde_tras_sombra_no_arrastra_nada(_aislar):
    CLI.main(["verificar", "--sombra", FALLA_FIJA])
    CLI.main(["verificar", "--sombra", FALLA_FIJA])
    assert CLI.main(["verificar", PASA]) == 0


# ── la definicion operativa de acierto/falso positivo ───────────────────

def _linea(**kw):
    return json.dumps(kw, ensure_ascii=False)


def test_evaluar_disparos_falso_positivo():
    """El primer parche posterior al disparo es verde: cortar era bloquear."""
    lineas = [
        _linea(n=1, clave="aaa", ok=False, hubo_cambio=True),
        _linea(evento="disparo_sombra", motivo="D6", intento=1),
        _linea(n=2, clave="aaa", ok=True, hubo_cambio=True),
    ]
    (ev,) = CLI._evaluar_disparos(lineas)
    assert not ev["acierto"]


def test_evaluar_disparos_acierto_por_bucle_esteril():
    lineas = [
        _linea(evento="disparo", motivo="D6", intento=2),
        _linea(n=3, clave="aaa", ok=False, hubo_cambio=True),
        _linea(n=4, clave="aaa", ok=True, hubo_cambio=True),
    ]
    (ev,) = CLI._evaluar_disparos(lineas)
    assert ev["acierto"], "el verde tardo 2 parches: el corte habria ahorrado"


def test_evaluar_disparos_acierto_por_reset_y_por_silencio():
    con_reset = [
        _linea(evento="disparo", motivo="D2", intento=3),
        _linea(evento="reset"),
        _linea(n=1, clave="bbb", ok=True, hubo_cambio=True),
    ]
    (ev,) = CLI._evaluar_disparos(con_reset)
    assert ev["acierto"] and "reset" in ev["razon"]

    sin_nada = [_linea(evento="disparo_sombra", motivo="D1", intento=3)]
    (ev2,) = CLI._evaluar_disparos(sin_nada)
    assert ev2["acierto"] and "sin verde" in ev2["razon"]


def test_evaluar_disparos_la_exploracion_no_es_un_parche():
    """Un intento --sin-cambio despues del disparo no decide el veredicto."""
    lineas = [
        _linea(evento="disparo", motivo="D6", intento=2),
        _linea(n=3, clave="aaa", ok=False, hubo_cambio=False),  # explorar
        _linea(n=4, clave="aaa", ok=True, hubo_cambio=True),    # 1er parche
    ]
    (ev,) = CLI._evaluar_disparos(lineas)
    assert not ev["acierto"], "el primer PARCHE fue verde: falso positivo"


def test_sombra_informe_agrega(capsys, _aislar):
    d = _aislar / "disciplina"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.jsonl").write_text("\n".join([
        _linea(evento="disparo_sombra", motivo="D6", intento=2),
        _linea(n=3, clave="x", ok=True, hubo_cambio=True),      # FP
    ]) + "\n", encoding="utf-8")
    (d / "b.jsonl").write_text("\n".join([
        _linea(evento="disparo", motivo="D6", intento=2),       # acierto
    ]) + "\n", encoding="utf-8")
    assert CLI.main(["sombra-informe"]) == 0
    salida = capsys.readouterr().out
    assert "disparos: 2" in salida
    assert "aceptacion: 50%" in salida
    assert "orientativo" in salida, "con <10 disparos el numero no decide"


# ── el bucle de tool_synthesis en sombra ────────────────────────────────

ROTO = "def run(args: str) -> str:\n    return undefined_name(args)\n"


class _OrchRoto:
    def __init__(self):
        self.prompts = []

    def infer(self, prompt):
        self.prompts.append(prompt)
        return types.SimpleNamespace(text=ROTO)

    def reparaciones(self):
        return [p for p in self.prompts if ROTO in p]

    def generaciones(self):
        return [p for p in self.prompts if ROTO not in p]


def _spec():
    return TS.ToolSpec(name="rota", doc="d", purpose="p",
                       test_input="x", expect_contains="x")


def test_bucle_en_sombra_no_reinicia_y_registra(_aislar, monkeypatch):
    monkeypatch.setenv("COGNIA_DISCIPLINA_SOMBRA", "1")
    orch = _OrchRoto()
    res = TS.synthesize_and_register(_spec(), orch=orch, max_attempts=3)
    assert not res["ok"]
    assert "breaker" not in res, "en sombra el disyuntor no para el bucle"
    assert len(orch.generaciones()) == 1, "sin reinicio limpio: 1 generacion"
    assert len(orch.reparaciones()) == 2, "el bucle viejo entero: 2 reparaciones"
    evs = _eventos(_aislar)
    assert evs and all(e["evento"] == "disparo_sombra" for e in evs)


def test_bucle_sin_sombra_persiste_sus_disparos(_aislar):
    orch = _OrchRoto()
    res = TS.synthesize_and_register(_spec(), orch=orch, max_attempts=3)
    assert not res["ok"]
    evs = _eventos(_aislar)
    assert [e["evento"] for e in evs] == ["disparo"]
    assert evs[0]["accion"] == "reinicio_limpio"
