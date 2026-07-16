"""Regresion de los fixes de instalacion facil (auditoria e2e 2026-07-15):
merge de config.env (wizard vs install-model), flags desconocidos de
install-model, y fallback ~/.cognia/models del registry de GGUFs."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_write_config_mergea_no_pisa(tmp_path, monkeypatch):
    import cognia.first_run as fr
    monkeypatch.setattr(fr, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(fr, "CONFIG_FILE", tmp_path / "config.env")
    # install-model persistio sus claves
    (tmp_path / "config.env").write_text(
        "LLAMA_GGUF_PATH=C:/modelos/x.gguf\nLLAMA_SERVER_PATH=C:/bin/s.exe\n",
        encoding="utf-8")
    # el wizard escribe SOLO las suyas -> antes borraba las del install
    fr._write_config({"COGNIA_RUN_MODE": "local", "COGNIA_USER_NAME": "Tomas"})
    final = fr._load_config()
    assert final["LLAMA_GGUF_PATH"] == "C:/modelos/x.gguf"
    assert final["LLAMA_SERVER_PATH"] == "C:/bin/s.exe"
    assert final["COGNIA_RUN_MODE"] == "local"


def test_install_model_flag_desconocido_aborta(capsys):
    from cognia.model_install import main
    with pytest.raises(SystemExit) as e:
        main(["--with-heavy-code", "--skip-guf"])   # typo
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert "--skip-guf" in out and "validos" in out


def test_resolve_gguf_fallback_home(tmp_path, monkeypatch):
    from pathlib import Path as _P
    import shattering.model_constants as mc
    home = tmp_path / "home"
    d = home / ".cognia" / "models" / "modelo-x"
    d.mkdir(parents=True)
    gguf = d / "Modelo-X-Q4.gguf"
    gguf.write_bytes(b"x")
    monkeypatch.setattr(_P, "home", classmethod(lambda cls: home))
    # clave cuya ruta repo-relativa NO existe (hermetico: la maquina dev
    # puede tener los 3b/7b reales en model_shards y la ruta repo ganaria,
    # que es el comportamiento correcto en modo dev)
    monkeypatch.setitem(mc.MODEL_GGUF_REGISTRY, "test_x",
                        "model_shards/modelo-x/Modelo-X-Q4.gguf")
    p = mc.resolve_gguf_path("test_x")
    assert p == gguf


def test_resolve_gguf_sin_nada_devuelve_ruta_repo(tmp_path, monkeypatch):
    from pathlib import Path as _P
    import shattering.model_constants as mc
    monkeypatch.setattr(_P, "home",
                        classmethod(lambda cls: tmp_path / "vacio"))
    p = mc.resolve_gguf_path("7b")
    # contrato previo intacto: devuelve la ruta del repo (exista o no)
    assert p is not None and "model_shards" in str(p)
