"""
WP6 (2026-08-09): la logica de servir_flota vive en cognia/flota.py (el
paquete) y scripts/servir_flota.py DELEGA. Dos copias de los combos fue como
el :8088 sirvio un modelo retirado sin que nadie lo viera: estos tests
vigilan que la fuente de verdad siga siendo UNA.
"""

from pathlib import Path

import cognia.flota as F

RAIZ = Path(__file__).resolve().parent.parent


class TestFuenteUnica:

    def test_el_script_delega_y_no_duplica_combos(self):
        script = RAIZ / "scripts" / "servir_flota.py"
        fuente = script.read_text(encoding="utf-8")
        assert "from cognia.flota import main" in fuente
        # Si alguien vuelve a definir COMBOS en el script, hay dos verdades.
        assert "COMBOS = {" not in fuente

    def test_scripts_dir_encuentra_el_repo(self):
        # En el checkout del repo (y en un editable install) scripts/ existe
        # como hermano de cognia/: arrancar puede reusar servir_modelo.py.
        d = F._scripts_dir()
        assert d is not None
        assert (d / "servir_modelo.py").is_file()
        assert (d / "servir_vlm.py").is_file()


class TestCombos:

    def test_combos_esperados(self):
        assert set(F.COMBOS) == {"construir", "construir-ui", "pensar",
                                 "pensar-en-lazo", "juzgar", "solo"}

    def test_pensar_sirve_gpt_oss_con_ctx_16384(self):
        # La leccion medida 2026-07-25: con 8192 el 20B truncaba (pass@1 25%
        # contra 100% con 16384). Si alguien baja el ctx, esto grita.
        (script, args), = F.COMBOS["pensar"]
        assert script == "servir_modelo.py"
        assert "gpt-oss" in args
        assert "16384" in args

    def test_combo_de_modelo_mapea_el_cerebro(self):
        assert F.combo_de_modelo("gpt-oss-20b-mxfp4.gguf") == "pensar"
        assert F.combo_de_modelo("UIGEN-X-8B-Q4_K_M.gguf") == "construir-ui"
        assert F.combo_de_modelo("qwen2.5-coder-14b-instruct-q4_k_m.gguf") == "construir"
        # Un GGUF ajeno a la flota NO se disfraza de combo.
        assert F.combo_de_modelo("qwen2.5-7b-instruct-q4_k_m.gguf") is None
        assert F.combo_de_modelo("") is None


class TestCli:

    def test_accion_desconocida_devuelve_1(self, capsys):
        assert F.main(["bailar"]) == 1
        assert "Accion desconocida" in capsys.readouterr().err

    def test_combo_desconocido_devuelve_1(self, capsys):
        assert F.main(["arrancar", "volar"]) == 1
        assert "Combo desconocido" in capsys.readouterr().err

    def test_sin_argumentos_muestra_ayuda(self, capsys):
        assert F.main([]) == 1
        assert "cognia flota" in capsys.readouterr().out

    def test_arrancar_sin_scripts_falla_honesto(self, monkeypatch, capsys):
        # Instalacion pip normal (wheel sin scripts/): arrancar no degrada en
        # silencio ni revienta con FileNotFoundError — explica que hacer.
        monkeypatch.setattr(F, "_scripts_dir", lambda: None)
        assert F.arrancar("pensar") == 1
        err = capsys.readouterr().err
        assert "editable install" in err

    def test_forma_historica_combo_directo(self, monkeypatch):
        # `servir_flota.py pensar` sigue funcionando: main() acepta el combo
        # como primera palabra y delega en arrancar.
        llamado = {}
        monkeypatch.setattr(F, "arrancar",
                            lambda modo, patron="": llamado.update(
                                modo=modo, patron=patron) or 0)
        assert F.main(["pensar"]) == 0
        assert llamado == {"modo": "pensar", "patron": ""}

    def test_arrancar_default_es_pensar(self, monkeypatch, capsys):
        llamado = {}
        monkeypatch.setattr(F, "arrancar",
                            lambda modo, patron="": llamado.update(modo=modo) or 0)
        assert F.main(["arrancar"]) == 0
        assert llamado["modo"] == "pensar"


class TestEstadoConProps:

    def test_estado_reporta_el_gguf_real(self, monkeypatch, capsys):
        # El punto entero del rework: estado ya no dice solo RESPONDE, dice
        # QUE modelo sirve el puerto (la averia del :8088 era invisible).
        def props_falsos(puerto):
            if puerto == 8080:
                return {"modelo": "gpt-oss-20b-mxfp4.gguf",
                        "n_ctx": 16384, "puerto": 8080}
            return {}
        monkeypatch.setattr(F, "props_puerto", props_falsos)
        assert F.estado() == 0
        out = capsys.readouterr().out
        assert "gpt-oss-20b-mxfp4.gguf" in out
        assert "combo 'pensar'" in out
        assert ":8081" in out and "no responde" in out
