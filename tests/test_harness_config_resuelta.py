# -*- coding: utf-8 -*-
"""
Regresion (2026-08-23): "que config esta corriendo DE VERDAD?" se pago dos
veces (los dos backends con :8088 sirviendo un modelo retirado; el token de
PyPI viviendo donde nadie miraba) y ninguna vista decia de que capa salia
cada valor efectivo.

Estos tests fijan el contrato de `cognia/harness/config_resuelta.py` (F6,
patron dump-config de deepseek-harness): el ORIGEN correcto por clave
(default | fichero | env:NOMBRE), la precedencia env > fichero > default, el
enmascarado de secretos, la degradacion explicita cuando una capa no se puede
leer (avisador, nunca lanzar) y que el subcomando `cognia config-resuelta`
sale 0 sin abrir el REPL.

Sin el modulo, el fichero entero falla en el import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cognia.harness import config_resuelta as cr


@pytest.fixture(autouse=True)
def subsistema_aislado(monkeypatch):
    """Sin avisador registrado del CLI real; cada test inyecta el suyo. Y sin
    marcas de envs sembradas heredadas de otro test (o del propio CLI si un
    test lo importo)."""
    monkeypatch.setattr(cr, "_AVISADOR", None)
    monkeypatch.setattr(cr, "_SEMBRADAS", set())


def _resolver(defaults, fichero_datos, entorno, tmp_path):
    """Atajo: resuelve con un fichero temporal (None = fichero inexistente)."""
    ruta = tmp_path / "cognia_config.json"
    if fichero_datos is not None:
        ruta.write_text(json.dumps(fichero_datos), encoding="utf-8")
    return cr.config_resuelta(defaults=defaults, ruta_fichero=ruta,
                              entorno=entorno)


# ── Origen por clave ─────────────────────────────────────────────────────────

def test_origen_default_sin_capas(tmp_path):
    res = _resolver({"offload": "on"}, None, {}, tmp_path)
    assert res["offload"] == {"valor": "on", "origen": "default",
                              "default": "on"}


def test_origen_fichero_cuando_difiere(tmp_path):
    res = _resolver({"offload": "on"}, {"offload": "off"}, {}, tmp_path)
    assert res["offload"]["valor"] == "off"
    assert res["offload"]["origen"] == "fichero"
    assert res["offload"]["default"] == "on"


def test_fichero_igual_al_default_es_default(tmp_path):
    # _load_config tambien mergea, pero un valor identico no es un override:
    # reportarlo como 'fichero' llenaria la vista de falsos cambios
    res = _resolver({"offload": "on"}, {"offload": "on"}, {}, tmp_path)
    assert res["offload"]["origen"] == "default"


def test_env_pisa_fichero_y_default(tmp_path):
    res = _resolver({"offload": "on"}, {"offload": "off"},
                    {"COGNIA_OFFLOAD": "1"}, tmp_path)
    assert res["offload"]["valor"] == "1"
    assert res["offload"]["origen"] == "env:COGNIA_OFFLOAD"


def test_segunda_env_del_registro_tambien_pisa(tmp_path):
    # spinner_info tiene dos envs: COGNIA_SPINNER (la global) tambien la pisa
    res = _resolver({"spinner_info": "on"}, None,
                    {"COGNIA_SPINNER": "0"}, tmp_path)
    assert res["spinner_info"]["origen"] == "env:COGNIA_SPINNER"
    assert res["spinner_info"]["valor"] == "0"


def test_clave_desconocida_del_fichero_sale(tmp_path):
    # esta en la config efectiva de _load_config igual: tiene que verse
    res = _resolver({"offload": "on"}, {"clave_vieja": "x"}, {}, tmp_path)
    assert res["clave_vieja"]["origen"] == "fichero"
    assert res["clave_vieja"]["valor"] == "x"


# ── Degradacion explicita ────────────────────────────────────────────────────

def test_fichero_corrupto_avisa_y_sigue(tmp_path):
    avisos = []
    cr.registrar_avisador(lambda via, motivo: avisos.append((via, motivo)))
    ruta = tmp_path / "cognia_config.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    res = cr.config_resuelta(defaults={"offload": "on"}, ruta_fichero=ruta,
                             entorno={"COGNIA_OFFLOAD": "0"})
    # la capa rota se ignora pero defaults + env siguen resolviendo
    assert res["offload"]["origen"] == "env:COGNIA_OFFLOAD"
    assert avisos and avisos[0][0] == "config"
    assert "cognia_config.json" in avisos[0][1]


def test_avisador_roto_no_tumba(tmp_path):
    def _revienta(via, motivo):
        raise RuntimeError("avisador roto")
    cr.registrar_avisador(_revienta)
    ruta = tmp_path / "cognia_config.json"
    ruta.write_text("[1,2]", encoding="utf-8")  # JSON valido pero no objeto
    res = cr.config_resuelta(defaults={"a": "1"}, ruta_fichero=ruta,
                             entorno={})
    assert res["a"]["origen"] == "default"


# ── Secretos ─────────────────────────────────────────────────────────────────

def test_es_secreto_y_enmascarar():
    assert cr.es_secreto("COGNIA_CONTRIBUTOR_TOKEN")
    assert cr.es_secreto("api_key")
    assert not cr.es_secreto("offload_umbral")
    assert cr.enmascarar("abcd1234secreto") == "abcd..."
    assert cr.enmascarar("ab") == "..."


def test_render_enmascara_secretos_en_sueltas(tmp_path):
    res = _resolver({"a": "1"}, None, {}, tmp_path)
    sueltas = cr.env_sueltas({"COGNIA_CONTRIBUTOR_TOKEN": "abcd1234secreto"})
    texto = "\n".join(cr.formatear_plano(res, sueltas))
    assert "COGNIA_CONTRIBUTOR_TOKEN = abcd..." in texto
    assert "abcd1234secreto" not in texto


# ── Env sueltas ──────────────────────────────────────────────────────────────

def test_env_sueltas_excluye_las_del_registro_y_vacias():
    sueltas = cr.env_sueltas({"COGNIA_OFFLOAD": "1",     # tiene clave: fuera
                              "COGNIA_FOO": "x",          # suelta: dentro
                              "COGNIA_VACIA": "  ",       # vacia: fuera
                              "OTRA_VAR": "y"})           # no COGNIA_: fuera
    assert sueltas == [("COGNIA_FOO", "x")]


# ── Subcomando CLI ───────────────────────────────────────────────────────────

def test_subcomando_cli_sale_cero():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "cognia", "config-resuelta"],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(Path(__file__).resolve().parent.parent), timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Configuracion RESUELTA" in proc.stdout


# ── Regresion 2026-08-23 (revision adversarial): la env SEMBRADA por el CLI ──

def test_env_sembrada_por_el_cli_no_es_origen_env(tmp_path):
    """_aplicar_config_offload/_aplicar_config_compactacion copian la config
    al env en CADA arranque del REPL: sin el registro de sembradas, las 8
    claves salian 'Pisadas por ENV (ganan a todo)' con el valor crudo ('1' en
    vez de 'on') aunque el usuario jamas puso una env — justo la mentira de
    origen que este modulo existe para matar."""
    cr.marcar_sembrada("COGNIA_OFFLOAD")
    res = _resolver({"offload": "on"}, None, {"COGNIA_OFFLOAD": "1"}, tmp_path)
    assert res["offload"] == {"valor": "on", "origen": "default",
                              "default": "on"}
    # con override en el fichero, el origen honesto es 'fichero'
    res = _resolver({"offload": "on"}, {"offload": "off"},
                    {"COGNIA_OFFLOAD": "0"}, tmp_path)
    assert res["offload"]["valor"] == "off"
    assert res["offload"]["origen"] == "fichero"


def test_env_del_usuario_sigue_ganando_aunque_haya_sembradas(tmp_path):
    """Una env que el usuario puso ANTES de arrancar nunca se marca (la
    siembra solo escribe cuando la env esta vacia): sigue reportandose env."""
    cr.marcar_sembrada("COGNIA_COMPACT")          # otra clave, no esta
    res = _resolver({"offload": "on"}, None, {"COGNIA_OFFLOAD": "0"}, tmp_path)
    assert res["offload"]["origen"] == "env:COGNIA_OFFLOAD"
    assert res["offload"]["valor"] == "0"


def test_el_arranque_del_repl_no_inventa_envs(tmp_path, monkeypatch):
    """El cableado entero: sembrar como lo hace el REPL (config->env) y
    resolver DESPUES — ninguna de las 8 claves puede salir con origen env."""
    import cognia.cli as cli
    for var in ("COGNIA_OFFLOAD", "COGNIA_TOOL_RESULT_MAX",
                "COGNIA_OFFLOAD_CABEZA", "COGNIA_OFFLOAD_COLA",
                "COGNIA_COMPACT", "COGNIA_COMPACT_UMBRAL",
                "COGNIA_COMPACT_RETENCION", "COGNIA_COMPACT_CAP"):
        # setenv ANTES de delenv: delenv(raising=False) sobre una var AUSENTE
        # no registra nada que deshacer, y la env que siembra
        # _aplicar_config_offload dentro del test se filtraba a los tests
        # siguientes (cazado: test_run_tool_aplica_trim fallaba solo en la
        # corrida conjunta porque COGNIA_OFFLOAD=1 quedaba puesta).
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)
    monkeypatch.setattr(cli, "_load_config", lambda: {})
    cli._aplicar_config_offload()
    cli._aplicar_config_compactacion()
    res = cr.config_resuelta(defaults=cli._CONFIG_DEFAULTS,
                             ruta_fichero=tmp_path / "no_existe.json")
    con_env = [k for k, v in res.items() if v["origen"].startswith("env")]
    assert con_env == []
    # y la fuente que pinta /offload estado tampoco miente
    assert cli._env_es_sembrada("COGNIA_OFFLOAD") is True


# ── Footer de contexto honesto (2026-08-23): las 3 claves nuevas ────────────

def test_claves_del_footer_registradas_en_env_que_pisan(tmp_path):
    """REGRESION: contexto_umbral_aviso/critico y barra_bloques nacieron con
    env (COGNIA_CTX_AVISO/CRITICO, COGNIA_BARRA_BLOQUES) pero sin entrada en
    ENV_QUE_PISAN: una env del dueno salia como SUELTA y la clave decia
    'default' mientras la barra obedecia a la env."""
    defaults = {"contexto_umbral_aviso": "", "contexto_umbral_critico": "90",
                "barra_bloques": "on"}
    entorno = {"COGNIA_CTX_AVISO": "70", "COGNIA_CTX_CRITICO": "95",
               "COGNIA_BARRA_BLOQUES": "0"}
    res = _resolver(defaults, None, entorno, tmp_path)
    assert res["contexto_umbral_aviso"]["origen"] == "env:COGNIA_CTX_AVISO"
    assert res["contexto_umbral_aviso"]["valor"] == "70"
    assert res["contexto_umbral_critico"]["origen"] == "env:COGNIA_CTX_CRITICO"
    assert res["barra_bloques"]["origen"] == "env:COGNIA_BARRA_BLOQUES"
    assert cr.env_sueltas(entorno) == []


def test_la_siembra_del_footer_no_inventa_envs(tmp_path, monkeypatch):
    """_aplicar_config_barra copia critico y bloques al env en cada arranque
    (aviso solo si el dueno lo fijo): con el registro de sembradas ninguna de
    las 3 claves puede salir con origen env, y el valor del fichero se
    atribuye al fichero."""
    import cognia.cli as cli
    for var in ("COGNIA_CTX_AVISO", "COGNIA_CTX_CRITICO",
                "COGNIA_BARRA_BLOQUES"):
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)
    monkeypatch.setattr(cli, "_load_config",
                        lambda: {"contexto_umbral_aviso": "75"})
    cli._aplicar_config_barra()
    assert os.environ["COGNIA_CTX_CRITICO"] == "90"
    assert os.environ["COGNIA_BARRA_BLOQUES"] == "on"
    assert os.environ["COGNIA_CTX_AVISO"] == "75"
    ruta = tmp_path / "cognia_config.json"
    ruta.write_text(json.dumps({"contexto_umbral_aviso": "75"}),
                    encoding="utf-8")
    res = cr.config_resuelta(defaults=cli._CONFIG_DEFAULTS, ruta_fichero=ruta)
    assert res["contexto_umbral_aviso"] == {"valor": "75", "origen": "fichero",
                                            "default": ""}
    assert res["contexto_umbral_critico"]["origen"] == "default"
    assert res["barra_bloques"]["origen"] == "default"
    # el vacio (acoplado a compactacion) NO siembra: sin env, el amarillo se
    # mueve con /compactar umbral
    monkeypatch.delenv("COGNIA_CTX_AVISO")
    monkeypatch.setattr(cli, "_load_config", lambda: {})
    cli._aplicar_config_barra()
    assert "COGNIA_CTX_AVISO" not in os.environ
