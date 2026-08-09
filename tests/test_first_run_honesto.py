"""
Regresion WP6 (2026-08-09): el wizard marcaba FIRST_RUN_OK aunque
install_model hubiera FALLADO — el fallo quedaba escondido para siempre (el
wizard no volvia a ofrecer el modelo y Cognia arrancaba degradada a
fallbacks en cada sesion). Y el wizard ofrecia el 3B a ciegas, sin mirar que
puede correr la maquina (VRAM via nvidia-smi / RAM).
"""

import subprocess

import pytest

import cognia.first_run as F


@pytest.fixture
def hogar(tmp_path, monkeypatch):
    """~/.cognia hermetico: las rutas de modulo apuntan a un tmp."""
    home = tmp_path / ".cognia"
    monkeypatch.setattr(F, "COGNIA_HOME", home)
    monkeypatch.setattr(F, "CONFIG_FILE", home / "config.env")
    monkeypatch.setattr(F, "SHARDS_DIR", home / "shards")
    monkeypatch.setattr(F, "DATA_DIR", home / "data")
    monkeypatch.setattr(F, "FIRST_RUN_OK", home / ".setup_done")
    return home


def _respuestas(monkeypatch, texto="", si_no=False):
    """Wizard sin teclado: todas las preguntas responden lo mismo."""
    monkeypatch.setattr(F, "_ask", lambda *a, **k: texto)
    monkeypatch.setattr(F, "_ask_yn", lambda *a, **k: si_no)


class TestFirstRunOkHonesto:

    def test_install_fallido_NO_marca_setup_done(self, hogar, monkeypatch, capsys):
        _respuestas(monkeypatch, texto="1", si_no=True)  # modo local, si a todo
        import cognia.model_install as MI
        monkeypatch.setattr(
            MI, "install_model",
            lambda **k: (_ for _ in ()).throw(RuntimeError("sin espacio")))

        F.run_wizard(force=True)

        assert not (hogar / ".setup_done").exists(), \
            "FIRST_RUN_OK con la instalacion fallada esconde el fallo para siempre"
        out = capsys.readouterr().out
        assert "FALLO" in out
        assert "cognia install-model" in out          # la orden para reintentar
        assert (hogar / "config.env").exists()        # la config SI se guarda

    def test_install_exitoso_SI_marca_setup_done(self, hogar, monkeypatch):
        _respuestas(monkeypatch, texto="1", si_no=True)
        import cognia.model_install as MI
        monkeypatch.setattr(MI, "install_model", lambda **k: {"gguf": "x"})

        F.run_wizard(force=True)

        assert (hogar / ".setup_done").exists()

    def test_declinar_descarga_es_eleccion_y_marca_ok(self, hogar, monkeypatch):
        # Decir "no" a bajar el modelo no es un fallo: el setup queda hecho.
        _respuestas(monkeypatch, texto="1", si_no=False)

        F.run_wizard(force=True)

        assert (hogar / ".setup_done").exists()


class TestHardwareDetectado:

    def test_vram_via_nvidia_smi(self, monkeypatch):
        class R:
            returncode = 0
            stdout = "16311\n"
        monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: R())
        hw = F.detectar_hardware()
        assert hw["vram_gb"] == pytest.approx(15.9, abs=0.1)

    def test_sin_nvidia_smi_cae_a_ram(self, monkeypatch):
        def sin_smi(*a, **k):
            raise FileNotFoundError("nvidia-smi no existe")
        monkeypatch.setattr(F.subprocess, "run", sin_smi)
        hw = F.detectar_hardware()
        assert hw["vram_gb"] is None
        # psutil es dependencia dura del paquete: la RAM siempre se conoce.
        assert hw["ram_gb"] is not None and hw["ram_gb"] > 0

    def test_detectar_nunca_lanza(self, monkeypatch):
        monkeypatch.setattr(F.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        F.detectar_hardware()   # no debe explotar: el wizard corre igual


class TestRecomendacionPorHardware:

    def test_16gb_vram_recomienda_el_pensador_validado(self):
        r = F.recomendar_modelo({"vram_gb": 15.9, "ram_gb": 32.0})
        assert "gpt-oss-20b" in r
        assert "flota" in r            # y dice COMO servirlo

    def test_12gb_vram_recomienda_14b(self):
        assert "14B" in F.recomendar_modelo({"vram_gb": 12.0, "ram_gb": 32.0})

    def test_8gb_vram_recomienda_heavy_code(self):
        assert "--with-heavy-code" in F.recomendar_modelo(
            {"vram_gb": 8.0, "ram_gb": 32.0})

    def test_sin_gpu_es_honesto_con_el_3b(self):
        assert "3B" in F.recomendar_modelo({"vram_gb": None, "ram_gb": 16.0})

    def test_maquina_justa_avisa_que_ira_lento(self):
        assert "lento" in F.recomendar_modelo({"vram_gb": None, "ram_gb": 4.0})


class TestElWizardUsaElHardware:

    def test_standalone_muestra_hardware_y_recomendacion(self, hogar, monkeypatch, capsys):
        _respuestas(monkeypatch, si_no=False)
        monkeypatch.setattr(F, "detectar_hardware",
                            lambda: {"vram_gb": 15.9, "ram_gb": 32.0})
        config: dict = {}
        assert F._wizard_standalone(config) is True
        out = capsys.readouterr().out
        assert "VRAM 15.9 GB" in out
        assert "gpt-oss-20b" in out
