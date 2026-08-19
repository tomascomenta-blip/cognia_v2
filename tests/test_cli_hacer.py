# -*- coding: utf-8 -*-
"""
`cognia hacer "<tarea>"` — el agente sin el REPL (2026-08-18).

POR QUE ESTOS TESTS. La pieza no es "un comando mas": es la puerta por la que
se puede automatizar y MEDIR el agente. Lo que la hace util en una tuberia es
el contrato de la salida, y eso es exactamente lo que se rompe sin querer:

  stdout = SOLO el resultado    (si se cuela el progreso, `cognia hacer ... |
  stderr = progreso y avisos     jq` o `> fichero` dejan de servir)
  codigo = 0 ok / 1 fallo / 2 uso / 130 Ctrl-C

Cada test falla sin la implementacion. El agente va mockeado a proposito: aqui
se prueba el CONTRATO del comando, no el modelo (eso lo mide el gate e2e).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia import cli_hacer


@pytest.fixture
def agente_falso(monkeypatch):
    """Sustituye el agente real: devuelve una respuesta y escupe progreso."""
    llamadas = {}

    class _Cognia:
        def __init__(self):
            print("arranque ruidoso de Cognia")   # va por stdout a proposito

    def _run(ai, tarea, print_fn, max_steps=None, **kw):
        llamadas.update(tarea=tarea, max_steps=max_steps)
        print_fn("paso 1: pensando")
        print("un print suelto del camino del agente")   # el ruido real
        return "RESULTADO FINAL"

    import cognia.cognia as _mod_cognia
    import cognia.cli as _mod_cli
    import cognia.first_run as _mod_fr
    monkeypatch.setattr(_mod_cognia, "Cognia", _Cognia, raising=False)
    monkeypatch.setattr(_mod_cli, "_run_agent_task", _run, raising=False)
    monkeypatch.setattr(_mod_fr, "apply_config", lambda *a, **k: None,
                        raising=False)
    return llamadas


class TestContratoDeSalida:

    def test_stdout_lleva_SOLO_el_resultado(self, agente_falso, capsys, tmp_path):
        assert cli_hacer.main(["escribe hola", "--cwd", str(tmp_path)]) == 0
        cap = capsys.readouterr()
        assert cap.out.strip() == "RESULTADO FINAL"
        # Lo demas existe, pero por stderr.
        assert "paso 1: pensando" in cap.err
        assert "arranque ruidoso" in cap.err
        assert "un print suelto" in cap.err

    def test_el_ruido_del_agente_no_contamina_la_tuberia(self, agente_falso,
                                                         capsys, tmp_path):
        # El doble cinturon: hasta un print() suelto dentro del agente tiene
        # que acabar en stderr. Sin el, `cognia hacer ... > out.txt` mezcla
        # razonamiento y respuesta.
        cli_hacer.main(["algo", "--cwd", str(tmp_path)])
        assert "print suelto" not in capsys.readouterr().out

    def test_silencioso_deja_stderr_limpio(self, agente_falso, capsys, tmp_path):
        cli_hacer.main(["algo", "-s", "--cwd", str(tmp_path)])
        cap = capsys.readouterr()
        assert cap.out.strip() == "RESULTADO FINAL"
        assert "paso 1" not in cap.err

    def test_json_es_json_valido_y_solo_json(self, agente_falso, capsys,
                                             tmp_path):
        assert cli_hacer.main(["algo", "--json", "--cwd", str(tmp_path)]) == 0
        d = json.loads(capsys.readouterr().out)      # falla si hay ruido
        assert d["respuesta"] == "RESULTADO FINAL"
        assert d["ok"] is True and d["tarea"] == "algo"
        assert isinstance(d["segundos"], (int, float))


class TestEntradaDeLaTarea:

    def test_toma_la_tarea_de_los_argumentos(self, agente_falso, tmp_path):
        cli_hacer.main(["arregla", "el", "bug", "--cwd", str(tmp_path)])
        assert agente_falso["tarea"] == "arregla el bug"

    def test_toma_la_tarea_de_stdin(self, agente_falso, monkeypatch, tmp_path):
        # `echo "tarea" | cognia hacer` es la forma natural de encadenar.
        import io
        entrada = io.StringIO("tarea por tuberia\n")
        entrada.isatty = lambda: False
        monkeypatch.setattr(sys, "stdin", entrada)
        cli_hacer.main(["--cwd", str(tmp_path)])
        assert agente_falso["tarea"] == "tarea por tuberia"

    def test_sin_tarea_y_con_terminal_no_se_cuelga(self, agente_falso,
                                                   monkeypatch, capsys):
        # Si stdin ES una terminal, leerlo pareceria un cuelgue: hay que salir
        # con uso incorrecto y decirlo.
        import io
        entrada = io.StringIO("")
        entrada.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", entrada)
        assert cli_hacer.main([]) == 2
        assert "Uso:" in capsys.readouterr().err

    def test_pasos_llega_al_agente(self, agente_falso, tmp_path):
        cli_hacer.main(["algo", "--pasos", "3", "--cwd", str(tmp_path)])
        assert agente_falso["max_steps"] == 3


class TestCodigosDeSalida:

    def test_cwd_inexistente_es_uso_incorrecto(self, agente_falso, capsys):
        assert cli_hacer.main(["algo", "--cwd", "Z:/no/existe/ni/de/broma"]) == 2
        assert "no puedo entrar" in capsys.readouterr().err

    def test_una_excepcion_del_agente_devuelve_1(self, monkeypatch, capsys,
                                                 tmp_path):
        import cognia.cli as _mod_cli
        import cognia.cognia as _mod_cognia
        import cognia.first_run as _mod_fr
        monkeypatch.setattr(_mod_fr, "apply_config", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(_mod_cognia, "Cognia", lambda: object(),
                            raising=False)

        def _explota(*a, **k):
            raise RuntimeError("el backend se cayo")

        monkeypatch.setattr(_mod_cli, "_run_agent_task", _explota,
                            raising=False)
        assert cli_hacer.main(["algo", "--cwd", str(tmp_path)]) == 1
        assert "el backend se cayo" in capsys.readouterr().err

    def test_ctrl_c_devuelve_130(self, monkeypatch, tmp_path):
        import cognia.cli as _mod_cli
        import cognia.cognia as _mod_cognia
        import cognia.first_run as _mod_fr
        monkeypatch.setattr(_mod_fr, "apply_config", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(_mod_cognia, "Cognia", lambda: object(),
                            raising=False)

        def _corta(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr(_mod_cli, "_run_agent_task", _corta, raising=False)
        assert cli_hacer.main(["algo", "--cwd", str(tmp_path)]) == 130


class TestCableadoEnElCli:

    def test_el_despacho_conoce_hacer(self):
        fuente = (Path(__file__).resolve().parent.parent
                  / "cognia" / "__main__.py").read_text(encoding="utf-8")
        assert 'cmd in ("hacer", "do")' in fuente
        assert "cli_hacer" in fuente

    def test_la_ayuda_lo_documenta(self):
        # Un comando que no sale en la ayuda es un comando que no existe para
        # el usuario (el repo ya tiene huerfanos asi).
        fuente = (Path(__file__).resolve().parent.parent
                  / "cognia" / "__main__.py").read_text(encoding="utf-8")
        assert 'hacer "<tarea>"' in fuente

class TestNoContaminaElProcesoQueLoLlama:
    """El bug que este comando introdujo y que cazo la suite del repo: --cwd
    hacia os.chdir() y NO lo restauraba. Con el proceso muriendo justo despues
    es invisible; llamado en proceso (tests, un script, el propio REPL) deja el
    directorio cambiado y todo lo que use rutas RELATIVAS despues revienta.
    Fueron ONCE tests posteriores con FileNotFoundError."""

    def test_el_cwd_vuelve_a_su_sitio(self, agente_falso, tmp_path):
        import os
        antes = os.getcwd()
        cli_hacer.main(["algo", "--cwd", str(tmp_path)])
        assert os.getcwd() == antes

    def test_vuelve_incluso_si_el_agente_explota(self, monkeypatch, tmp_path):
        import os
        import cognia.cli as _mod_cli
        import cognia.cognia as _mod_cognia
        import cognia.first_run as _mod_fr
        monkeypatch.setattr(_mod_fr, "apply_config", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(_mod_cognia, "Cognia", lambda: object(),
                            raising=False)

        def _explota(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(_mod_cli, "_run_agent_task", _explota, raising=False)
        antes = os.getcwd()
        cli_hacer.main(["algo", "--cwd", str(tmp_path)])
        assert os.getcwd() == antes

