# -*- coding: utf-8 -*-
"""Las PUERTAS de los dos subsistemas nuevos (regla del repo: lo que no se
puede teclear en el REPL, para el dueno no existe).

  /entrega [estado|on|off]
  /bucle razonamiento [on|off|umbral <n>|racha <n>]

No se toca el config real del dueno: `_load_config`/`_save_config` se
monkeypatchean sobre un dict en memoria.
"""

import pytest

import cognia.cli as C
from cognia.harness import entrega as E
from cognia.harness import razonamiento as R


@pytest.fixture
def cfg(monkeypatch):
    """Config en memoria + entorno limpio de las envs de los dos subsistemas."""
    d = {}
    monkeypatch.setattr(C, "_load_config", lambda: dict(d))
    monkeypatch.setattr(C, "_save_config", lambda c: d.update(c))
    for var in (E.ENV_ACTIVO, R.ENV_ACTIVO, R.ENV_UMBRAL, R.ENV_RACHA):
        monkeypatch.delenv(var, raising=False)
    return d


def _salida(capsys):
    return capsys.readouterr().out


# ── /entrega ───────────────────────────────────────────────────────────

def test_entrega_esta_en_la_ayuda():
    assert "/entrega" in C._CMD_DESCRIPTIONS
    assert "disco" in C._CMD_DESCRIPTIONS["/entrega"].lower()


def test_entrega_estado_imprime_la_foto(cfg, capsys):
    C._slash_entrega("")
    out = _salida(capsys)
    assert "entrega" in out and "en este proceso" in out


def test_entrega_on_off_persiste_y_propaga(cfg, capsys, monkeypatch):
    import os
    C._slash_entrega("off")
    assert cfg["entrega"] == "off"
    assert os.environ[E.ENV_ACTIVO] == "0"
    assert E.activo() is False
    C._slash_entrega("on")
    assert cfg["entrega"] == "on" and E.activo() is True


def test_entrega_subcomando_invalido_no_calla(cfg, capsys):
    C._slash_entrega("aplastame")
    assert "Uso: /entrega" in _salida(capsys)


def test_aplicar_config_entrega_grita_con_basura(cfg, capsys, monkeypatch):
    cfg["entrega"] = "quizas"
    avisos = []
    monkeypatch.setattr(C, "_aviso_degradado",
                        lambda origen, motivo: avisos.append((origen, motivo)))
    C._aplicar_config_entrega()
    assert avisos and avisos[0][0] == "entrega"
    assert E.activo() is True            # cae al default, no se rompe


# ── /bucle razonamiento ────────────────────────────────────────────────

def test_bucle_menciona_el_razonamiento_en_la_ayuda():
    assert "razonamiento" in C._CMD_DESCRIPTIONS["/bucle"].lower()


def test_bucle_razonamiento_estado(cfg, capsys):
    C._slash_bucle("razonamiento")
    out = _salida(capsys)
    assert "razonamiento en bucle" in out
    assert "paso pesado" in out and "racha dura" in out


def test_bucle_razonamiento_on_off_umbral_y_racha(cfg, capsys):
    import os
    C._slash_bucle("razonamiento off")
    assert cfg["razonamiento"] == "off" and R.activo() is False
    C._slash_bucle("razonamiento on")
    assert R.activo() is True
    C._slash_bucle("razonamiento umbral 1500")
    assert cfg["razonamiento_umbral"] == "1500"
    assert os.environ[R.ENV_UMBRAL] == "1500" and R.umbral_chars() == 1500
    C._slash_bucle("razonamiento racha 4")
    assert cfg["razonamiento_racha"] == "4" and R.racha_dura() == 4


@pytest.mark.parametrize("cmd, pista", [
    ("razonamiento umbral 3", "entero >= 200"),
    ("razonamiento umbral cero", "no es un entero"),
    ("razonamiento racha 1", "entero >= 2"),
    ("razonamiento loquesea", "Uso: /bucle razonamiento"),
])
def test_bucle_razonamiento_valida_y_lo_dice(cfg, capsys, cmd, pista):
    C._slash_bucle(cmd)
    assert pista in _salida(capsys)
    assert "razonamiento_umbral" not in cfg and "razonamiento_racha" not in cfg


def test_el_estado_general_de_bucle_incluye_los_cuatro(cfg, capsys):
    C._slash_bucle("")
    out = _salida(capsys)
    for titulo in ("recordatorio de repeticion", "timeout por tool",
                   "razonamiento en bucle"):
        assert titulo in out
