"""
tests/test_first_run_wizard.py
==============================
Regresion del wizard de primer arranque (2026-08-13).

EL BUG (reproducido antes de tocar codigo): cualquier respuesta no reconocida
al menu 1/2/3 caia en `else: mode = "1"`, o sea LOCAL, o sea una descarga de
2,6 GB que el usuario nunca pidio. Se comprobo con stdin = "x\\ny\\n\\n":
la corrida imprimia "-- Local (este equipo) --" y llegaba a install_model.

Aca ademas: el BOM que llega por pipe, la constante de tamano compartida con
model_install (el prompt prometia "~2GB" mientras la reserva pedia 2,6 GB) y
la lectura del .env que escribe install.ps1.

Los stubs son de TEST (nadie descarga nada en pytest): install_model se
sustituye por un centinela que anota si lo llamaron.
"""

from __future__ import annotations

import io
import sys

import pytest

from cognia import first_run, model_install


class _DescargaLlamada(BaseException):
    """La levanta el centinela si el wizard intenta instalar el modelo.

    BaseException y no Exception A PROPOSITO: _wizard_standalone envuelve
    install_model en `except Exception`, asi que un centinela normal quedaria
    tragado por el propio codigo bajo prueba y el test no veria nada."""


@pytest.fixture()
def wizard(tmp_path, monkeypatch):
    """Wizard apuntando a un ~/.cognia de mentira, sin red ni descargas."""
    home = tmp_path / "cognia_home"
    home.mkdir()
    monkeypatch.setattr(first_run, "COGNIA_HOME", home)
    monkeypatch.setattr(first_run, "CONFIG_FILE", home / "config.env")
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", home / ".env")
    monkeypatch.setattr(first_run, "SHARDS_DIR", home / "shards")
    monkeypatch.setattr(first_run, "DATA_DIR", home / "data")
    monkeypatch.setattr(first_run, "FIRST_RUN_OK", home / ".setup_done")

    def _no_descargar(*a, **k):
        raise _DescargaLlamada("install_model fue llamado")

    monkeypatch.setattr(model_install, "install_model", _no_descargar)
    # Disco: por defecto alcanza, para que los tests no dependan del disco de
    # la maquina que los corre (el test de "no alcanza" lo re-parchea).
    monkeypatch.setattr(model_install, "espacio_faltante", lambda *a, **k: 0.0)
    # Hardware: la maquina de CI no tiene por que tener nvidia-smi.
    monkeypatch.setattr(first_run, "detectar_hardware",
                        lambda: {"vram_gb": None, "ram_gb": 16.0})
    return home


def _correr(monkeypatch, entradas: str):
    """Corre el wizard con `entradas` por stdin y devuelve (salida, excepcion)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(entradas))
    try:
        first_run.run_wizard(force=True)
        return None
    except BaseException as exc:      # SystemExit por EOF incluido
        return exc


# ── _limpiar / _ask: el BOM llega de verdad por pipe ───────────────────────────

def test_limpiar_saca_el_bom_y_los_espacios():
    assert first_run._limpiar("\ufeff1") == "1"
    assert first_run._limpiar("  \ufeff 2 \n") == "2"
    assert first_run._limpiar("3") == "3"


def test_ask_devuelve_la_opcion_aunque_venga_con_bom(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "\ufeff2")
    assert first_run._ask("Elegi", default="1") == "2"


def test_ask_yn_no_confunde_un_no_con_bom_con_el_default(monkeypatch):
    """Con BOM, 'n' no era 'n' -> devolvia el default, que aca es SI-descargar."""
    monkeypatch.setattr("builtins.input", lambda _p: "\ufeffn")
    assert first_run._ask_yn("Descargar?", default=True) is False


# ── El menu: una respuesta desconocida NO puede descargar 2,6 GB ──────────────

def test_respuesta_desconocida_repregunta_y_no_descarga(wizard, monkeypatch, capsys):
    """EL BUG: 'x' entraba a LOCAL y llegaba a install_model.

    La entrada es SOLO 'x' (el comando de verificacion es `echo 'x' | cognia
    init`): despues no queda nada que leer, asi que la re-pregunta se topa con
    EOF y el wizard sale limpio. Con el bug, esa misma entrada entraba a Local
    y ofrecia la descarga."""
    exc = _correr(monkeypatch, "x\n")
    salida = capsys.readouterr().out
    assert "no es una opcion" in salida
    assert "-- Local (este equipo) --" not in salida
    assert not isinstance(exc, _DescargaLlamada), "el wizard arranco la descarga"
    # Se quedo sin entrada re-preguntando: EOF -> salida limpia, no traceback.
    assert isinstance(exc, SystemExit) and exc.code == 0


def test_repregunta_hasta_una_opcion_valida(wizard, monkeypatch, capsys):
    """'x' -> re-pregunta -> '3' (solo memoria) se respeta."""
    _correr(monkeypatch, "x\n3\n\n\n\n")
    salida = capsys.readouterr().out
    assert "no es una opcion" in salida
    assert "-- Solo memoria --" in salida
    assert first_run._leer_env(wizard / "config.env")["COGNIA_RUN_MODE"] == "memoria"


def test_enter_sigue_valiendo_el_default_local(wizard, monkeypatch, capsys):
    """El default silencioso queda SOLO para la cadena vacia (Enter)."""
    exc = _correr(monkeypatch, "\ny\n\n")
    salida = capsys.readouterr().out
    assert "no es una opcion" not in salida
    assert "-- Local (este equipo) --" in salida
    assert isinstance(exc, _DescargaLlamada)   # Enter + Y = si quiso descargar


def test_bom_en_la_opcion_no_cae_en_local(wizard, monkeypatch, capsys):
    """'\\ufeff3' es la opcion 3, no 'respuesta rara' -> no descarga nada."""
    _correr(monkeypatch, "\ufeff3\n\n\n\n")
    salida = capsys.readouterr().out
    assert "-- Solo memoria --" in salida
    assert "no es una opcion" not in salida


# ── El tamano anunciado y el reservado son el MISMO numero ─────────────────────

def test_constante_de_tamano_es_compartida():
    assert model_install.BYTES_STACK_BASE == 2_600_000_000
    assert model_install.gb_stack(False) == pytest.approx(2.6)
    assert model_install.gb_stack(True) == pytest.approx(7.6)


def test_el_prompt_anuncia_los_gb_reales_no_2gb(wizard, monkeypatch, capsys):
    """El wizard prometia '~2GB' y model_install reservaba 2,6 GB."""
    monkeypatch.setattr(model_install, "espacio_faltante", lambda *a, **k: 0.0)
    _correr(monkeypatch, "1\nn\nn\nn\n\n\n\n")
    salida = capsys.readouterr().out
    assert "~2.6 GB" in salida
    assert "~2GB" not in salida


def test_sin_espacio_avisa_los_gb_que_faltan_y_no_pregunta(wizard, monkeypatch, capsys):
    """Antes: preguntaba, el usuario decia que si, y RuntimeError despues."""
    monkeypatch.setattr(model_install, "espacio_faltante", lambda *a, **k: 0.7)
    exc = _correr(monkeypatch, "1\nn\nn\n\n\n\n")
    salida = capsys.readouterr().out
    assert "te faltan 0.7 GB" in salida
    assert "Descargar el modelo" not in salida
    assert not isinstance(exc, _DescargaLlamada)


def test_espacio_faltante_devuelve_cero_cuando_alcanza(monkeypatch):
    import collections
    Uso = collections.namedtuple("Uso", "total used free")
    monkeypatch.setattr(model_install.shutil, "disk_usage",
                        lambda _p: Uso(0, 0, 10_000_000_000))
    assert model_install.espacio_faltante(False) == 0.0
    monkeypatch.setattr(model_install.shutil, "disk_usage",
                        lambda _p: Uso(0, 0, 2_000_000_000))
    assert model_install.espacio_faltante(False) == pytest.approx(0.6)


def test_check_espacio_dice_cuanto_falta(monkeypatch):
    monkeypatch.setattr(model_install, "espacio_faltante", lambda *a, **k: 1.4)
    with pytest.raises(RuntimeError, match=r"faltan 1\.4 GB"):
        model_install._check_espacio(False)


# ── ~/.cognia/.env: lo que escribe install.ps1 tambien se lee ─────────────────

def test_load_config_lee_el_env_del_instalador(tmp_path, monkeypatch):
    monkeypatch.setattr(first_run, "CONFIG_FILE", tmp_path / "config.env")
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", tmp_path / ".env")
    (tmp_path / ".env").write_text(
        "LLAMA_GGUF_PATH=D:/modelos/x.gguf\nCOGNIA_COORDINATOR_URL=http://c\n",
        encoding="utf-8")
    conf = first_run._load_config()
    assert conf["LLAMA_GGUF_PATH"] == "D:/modelos/x.gguf"
    assert conf["COGNIA_COORDINATOR_URL"] == "http://c"


def test_config_env_gana_sobre_el_env(tmp_path, monkeypatch):
    monkeypatch.setattr(first_run, "CONFIG_FILE", tmp_path / "config.env")
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", tmp_path / ".env")
    (tmp_path / ".env").write_text("LLAMA_GGUF_PATH=viejo.gguf\n", encoding="utf-8")
    (tmp_path / "config.env").write_text("LLAMA_GGUF_PATH=nuevo.gguf\n",
                                         encoding="utf-8")
    assert first_run._load_config()["LLAMA_GGUF_PATH"] == "nuevo.gguf"


def test_write_config_no_absorbe_las_claves_del_env(tmp_path, monkeypatch):
    """config.env se reescribe con lo SUYO: mergear el .env duplicaria las
    claves del instalador y congelaria valores que el .env todavia manda."""
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", tmp_path / "config.env")
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", tmp_path / ".env")
    (tmp_path / ".env").write_text("SOLO_DEL_INSTALADOR=1\n", encoding="utf-8")
    first_run._write_config({"COGNIA_LANG": "espanol"})
    escrito = (tmp_path / "config.env").read_text(encoding="utf-8")
    assert "COGNIA_LANG=espanol" in escrito
    assert "SOLO_DEL_INSTALADOR" not in escrito
    # ...pero la vista combinada sigue viendolo.
    assert first_run._load_config()["SOLO_DEL_INSTALADOR"] == "1"


def test_leer_env_no_lanza_con_fichero_ausente(tmp_path):
    assert first_run._leer_env(tmp_path / "no_existe.env") == {}
