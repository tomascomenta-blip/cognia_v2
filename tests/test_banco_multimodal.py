"""
Ola 2 (I2): scripts/banco_multimodal.py solo tiene que IMPORTAR limpio (sin
cognia, sin GPU) y listar su bateria con --listar. La ejecucion real es de la
ola 3; aca se testean la forma de las tareas, los flags opt-in REALES del
repo y las postcondiciones (que miran bytes, no la palabra del modelo).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import banco_multimodal as BM

# Los flags opt-in que existen de verdad en cognia/agent/tools.py
# (_OPTIN_PREFIJOS + bloques condicionales). 'COGNIA_VOZ' pelado NO existe:
# el conflicto C7 del plan se resolvio a favor de COGNIA_VOZ_TOOLS.
_FLAGS_REALES = {"COGNIA_VOZ_TOOLS", "COGNIA_IMG_TOOLS", "COGNIA_VLM_TOOLS",
                 "COGNIA_MUSICA_TOOLS", "COGNIA_3D_TOOLS", "COGNIA_BROWSER",
                 "COGNIA_SCREEN"}


class TestImportaLimpio:

    def test_no_importa_cognia_a_nivel_modulo(self):
        # El banco corre en ola 3; en ola 2 el import no debe arrastrar ni
        # cognia ni shattering (los flags opt-in son a import-time y este
        # modulo NO debe fijarlos por accidente).
        fuente = Path(BM.__file__).read_text(encoding="utf-8")
        for linea in fuente.splitlines():
            limpia = linea.strip()
            if limpia.startswith(("import cognia", "from cognia",
                                  "import shattering", "from shattering")):
                # solo se permite dentro de funciones (indentado)
                assert linea != limpia, f"import a nivel modulo: {limpia}"


class TestBateria:

    def test_forma_de_las_tareas(self):
        ts = BM.tareas()
        assert len(ts) >= 4
        for t in ts:
            assert set(t) == {"nombre", "tarea", "verificar", "setup",
                              "env_extra"}
            assert callable(t["verificar"])
            assert t["setup"] is None or callable(t["setup"])
            assert isinstance(t["env_extra"], dict) and t["env_extra"]

    def test_nombres_unicos(self):
        nombres = [t["nombre"] for t in BM.tareas()]
        assert len(nombres) == len(set(nombres))

    def test_flags_son_los_reales_del_repo(self):
        for t in BM.tareas():
            for flag, valor in t["env_extra"].items():
                assert flag in _FLAGS_REALES, f"{t['nombre']}: flag {flag}"
                assert valor == "1"

    def test_cubre_las_tres_tools_de_ola_1(self):
        # El encargo minimo: voz_decir, imagen_generar, vlm_mirar.
        flags = set()
        for t in BM.tareas():
            flags |= set(t["env_extra"])
        assert {"COGNIA_VOZ_TOOLS", "COGNIA_IMG_TOOLS",
                "COGNIA_VLM_TOOLS"} <= flags


class TestListar:

    def test_listar_sale_0_y_muestra_todo(self, capsys):
        assert BM.main(["--listar"]) == 0
        out = capsys.readouterr().out
        for t in BM.tareas():
            assert t["nombre"] in out

    def test_solo_desconocida_sale_2(self, capsys):
        assert BM.main(["--solo", "noexiste"]) == 2
        assert "noexiste" in capsys.readouterr().err


class TestPostcondiciones:

    def test_png_solido_es_png_valido(self, tmp_path):
        ruta = tmp_path / "muestra.png"
        BM._png_solido(ruta)
        datos = ruta.read_bytes()
        assert datos[:8] == b"\x89PNG\r\n\x1a\n"
        assert b"IHDR" in datos and b"IEND" in datos
        assert BM._hay_png(tmp_path)

    def test_hay_wav_exige_riff_real(self, tmp_path):
        assert not BM._hay_wav(tmp_path)
        (tmp_path / "falso.wav").write_text("no soy audio", encoding="utf-8")
        assert not BM._hay_wav(tmp_path)
        (tmp_path / "corto.wav").write_bytes(b"RIFF" + b"\x00" * 10)
        assert not BM._hay_wav(tmp_path)          # solo cabecera no cuenta
        (tmp_path / "real.wav").write_bytes(b"RIFF" + b"\x00" * 100)
        assert BM._hay_wav(tmp_path)

    def test_hay_png_ignora_basura_con_extension(self, tmp_path):
        (tmp_path / "falso.png").write_text("html de error", encoding="utf-8")
        assert not BM._hay_png(tmp_path)

    def test_setup_de_vlm_fabrica_la_muestra(self, tmp_path):
        t = next(x for x in BM.tareas() if x["nombre"] == "vlm_describe")
        t["setup"](tmp_path)
        assert (tmp_path / "muestra.png").is_file()
        # y su verificador exige texto no trivial
        assert not t["verificar"](tmp_path)
        (tmp_path / "descripcion.txt").write_text(
            "un cuadrado rojo sobre fondo liso", encoding="utf-8")
        assert t["verificar"](tmp_path)

    def test_verificador_web_exige_cervantes(self, tmp_path):
        t = next(x for x in BM.tareas() if x["nombre"] == "web_autor")
        (tmp_path / "autor.txt").write_text("Miguel de Cervantes",
                                            encoding="utf-8")
        assert t["verificar"](tmp_path)
        (tmp_path / "autor.txt").write_text("no se", encoding="utf-8")
        assert not t["verificar"](tmp_path)
