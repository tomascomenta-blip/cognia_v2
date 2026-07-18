"""
tests/test_console.py
Tests de cognia/console/: proc_registry, monitors, permissions y surveys.

Sin REPL, sin input() real (I/O inyectada) y sin sleeps largos: los monitores
usan interval 0.05s y los waits son polls cortos con timeout.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _wait_until(cond, timeout=8.0, step=0.05):
    """Pollea cond() hasta que sea truthy o venza el timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = cond()
        if result:
            return result
        time.sleep(step)
    return cond()


# ── proc_registry ─────────────────────────────────────────────────────────────

class TestProcRegistry:
    def test_spawn_output_tail_y_status_done(self):
        from cognia.console.proc_registry import get_output, get_status, spawn_shell
        cmd = f'"{sys.executable}" -c "print(0);print(1);print(2)"'
        sid = spawn_shell(cmd)
        assert isinstance(sid, int)
        assert _wait_until(lambda: get_status(sid) == "done")
        lines = get_output(sid)
        assert lines == ["0", "1", "2"]
        assert get_output(sid, last_n=1) == ["2"]

    def test_list_shells_expone_campos(self):
        from cognia.console.proc_registry import list_shells, spawn_shell
        cmd = f'"{sys.executable}" -c "print(\'ok\')"'
        sid = spawn_shell(cmd)
        por_id = {s["id"]: s for s in list_shells()}
        assert sid in por_id
        entry = por_id[sid]
        assert entry["cmd"] == cmd
        assert entry["status"] in ("running", "done", "failed")
        assert "proc" not in entry  # no expone el Popen

    def test_kill_shell(self):
        from cognia.console.proc_registry import get_status, kill_shell, spawn_shell
        cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'
        sid = spawn_shell(cmd)
        assert get_status(sid) == "running"
        assert kill_shell(sid) is True
        assert _wait_until(lambda: get_status(sid) == "failed")

    def test_ids_inexistentes(self):
        from cognia.console.proc_registry import get_output, get_status, kill_shell
        assert kill_shell(99999) is False
        assert get_output(99999) == []
        assert get_status(99999) is None


# ── permissions ───────────────────────────────────────────────────────────────

@pytest.fixture
def perm_env(tmp_path, monkeypatch):
    """Aisla config.env en tmp_path y limpia el modo de la sesion."""
    from cognia import first_run
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", tmp_path / "config.env")
    monkeypatch.delenv("COGNIA_PERMISSION_MODE", raising=False)
    yield tmp_path


class TestPermissions:
    def test_default_automatico(self, perm_env):
        from cognia.console.permissions import get_mode
        assert get_mode() == "automatico"

    def test_set_mode_persiste_en_config(self, perm_env):
        from cognia.console.permissions import get_mode, set_mode
        set_mode("manual")
        assert get_mode() == "manual"
        contenido = (perm_env / "config.env").read_text(encoding="utf-8")
        assert "COGNIA_PERMISSION_MODE=manual" in contenido

    def test_set_mode_invalido(self, perm_env):
        from cognia.console.permissions import set_mode
        with pytest.raises(ValueError):
            set_mode("turbo")

    def test_bypass_todo_false(self, perm_env):
        from cognia.console.permissions import needs_confirmation, set_mode
        set_mode("bypass")
        assert needs_confirmation("shell_exec", "rm -rf /") is False
        assert needs_confirmation("file_delete", "C:\\Windows\\x") is False

    def test_manual_todo_true(self, perm_env):
        from cognia.console.permissions import needs_confirmation, set_mode
        set_mode("manual")
        assert needs_confirmation("shell_exec", "echo hola") is True
        assert needs_confirmation("network", "http://localhost/") is True

    def test_automatico_shell_peligroso(self, perm_env):
        from cognia.console.permissions import needs_confirmation
        assert needs_confirmation("shell_exec", "rm -rf /") is True
        assert needs_confirmation("shell_exec", "format c:") is True
        assert needs_confirmation("shell_exec", "shutdown /s /t 0") is True
        assert needs_confirmation("shell_exec", "reg delete HKLM\\Software\\X /f") is True

    def test_automatico_shell_inofensivo(self, perm_env):
        from cognia.console.permissions import needs_confirmation
        assert needs_confirmation("shell_exec", "echo hola") is False
        assert needs_confirmation("shell_exec", "git status") is False
        # "del" como palabra castellana (no en posicion de comando) no dispara
        assert needs_confirmation("shell_exec", "python informe_del_dia.py") is False

    def test_automatico_file_delete_siempre(self, perm_env):
        from cognia.console.permissions import needs_confirmation
        assert needs_confirmation("file_delete", "notas.txt") is True

    def test_automatico_file_write_por_ruta(self, perm_env, tmp_path):
        from cognia.console.permissions import needs_confirmation
        # relativa (dentro del proyecto) y temp: OK sin confirmar
        assert needs_confirmation("file_write", "notas.txt") is False
        assert needs_confirmation("file_write", str(tmp_path / "x.txt")) is False
        # fuera del proyecto / ~/.cognia / temp: confirmar
        assert needs_confirmation("file_write", "C:\\Windows\\notas.txt") is True

    def test_automatico_network_y_desconocido(self, perm_env):
        from cognia.console.permissions import needs_confirmation
        assert needs_confirmation("network", "GET http://localhost:8088/health") is False
        assert needs_confirmation("accion_rara", "lo que sea") is True


# ── monitors ──────────────────────────────────────────────────────────────────

class TestMonitors:
    def _drain(self):
        from cognia.console.monitors import pop_fired_events
        pop_fired_events()

    def _esperar_evento(self, marca, timeout=8.0):
        """Pollea pop_fired_events() hasta ver un evento que contenga la marca."""
        from cognia.console.monitors import pop_fired_events
        encontrados = []

        def check():
            encontrados.extend(pop_fired_events())
            return any(marca in e for e in encontrados)

        assert _wait_until(check, timeout=timeout), f"sin evento con {marca!r}: {encontrados}"
        return encontrados

    def test_file_exists_dispara_y_pop_lo_devuelve(self, tmp_path):
        from cognia.console.monitors import list_monitors, monitor_file_exists
        self._drain()
        objetivo = tmp_path / "x.txt"
        mid = monitor_file_exists(str(objetivo), "espera-x", interval_s=0.05, timeout_s=10)
        objetivo.write_text("listo", encoding="utf-8")
        eventos = self._esperar_evento("espera-x")
        assert any(f"[monitor {mid}]" in e for e in eventos)
        por_id = {m["id"]: m for m in list_monitors()}
        assert por_id[mid]["status"] == "fired"

    def test_stop_monitor(self, tmp_path):
        from cognia.console.monitors import list_monitors, monitor_file_exists, stop_monitor
        self._drain()
        mid = monitor_file_exists(str(tmp_path / "nunca.txt"), "nunca-aparece",
                                  interval_s=0.05, timeout_s=60)
        assert stop_monitor(mid) is True
        assert stop_monitor(99999) is False
        assert _wait_until(
            lambda: {m["id"]: m for m in list_monitors()}[mid]["status"] == "stopped"
        )

    def test_output_regex_sobre_shell(self):
        from cognia.console.monitors import monitor_output_regex
        from cognia.console.proc_registry import spawn_shell
        self._drain()
        cmd = f'"{sys.executable}" -c "print(\'arrancando\');print(\'SERVIDOR LISTO\')"'
        sid = spawn_shell(cmd)
        mid = monitor_output_regex(sid, r"SERVIDOR LISTO", "espera-listo",
                                   interval_s=0.05, timeout_s=10)
        eventos = self._esperar_evento("espera-listo")
        assert any("SERVIDOR LISTO" in e and f"[monitor {mid}]" in e for e in eventos)

    def test_timeout_encola_evento(self, tmp_path):
        from cognia.console.monitors import monitor_file_exists
        self._drain()
        monitor_file_exists(str(tmp_path / "jamas.txt"), "timeout-corto",
                            interval_s=0.05, timeout_s=0.15)
        eventos = self._esperar_evento("timeout-corto")
        assert any("TIMEOUT" in e for e in eventos)

    def test_url_caida_dispara(self):
        from cognia.console.monitors import monitor_url_healthy
        self._drain()
        # puerto 9 local cerrado: con esperar_caida=True dispara enseguida
        monitor_url_healthy("http://127.0.0.1:9/health", "url-caida",
                            esperar_caida=True, interval_s=0.05, timeout_s=15)
        eventos = self._esperar_evento("url-caida", timeout=12.0)
        assert any("dejo de responder" in e for e in eventos)


# ── surveys ───────────────────────────────────────────────────────────────────

def _fake_input(respuestas):
    it = iter(respuestas)
    return lambda prompt="": next(it)


class TestSurveys:
    def test_seleccion_unica(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Color?", ["rojo", "verde"],
                         input_fn=_fake_input(["2"]), print_fn=lambda *a: None)
        assert out == {"selected": ["verde"], "libre": None}

    def test_seleccion_multiple(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Cuales?", ["a", "b", "c"], multi=True,
                         input_fn=_fake_input(["1,3"]), print_fn=lambda *a: None)
        assert out == {"selected": ["a", "c"], "libre": None}

    def test_respuesta_libre(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Opinion?", ["a", "b"],
                         input_fn=_fake_input(["o", "mi propia respuesta"]),
                         print_fn=lambda *a: None)
        assert out == {"selected": [], "libre": "mi propia respuesta"}

    def test_multi_con_libre_combinada(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Cuales?", ["a", "b"], multi=True,
                         input_fn=_fake_input(["1,o", "ademas esto"]),
                         print_fn=lambda *a: None)
        assert out == {"selected": ["a"], "libre": "ademas esto"}

    def test_invalido_reintenta_y_acepta(self):
        from cognia.console.surveys import ask_survey
        impresos = []
        out = ask_survey("Color?", ["rojo", "verde"],
                         input_fn=_fake_input(["zz", "1"]),
                         print_fn=lambda *a: impresos.append(" ".join(str(x) for x in a)))
        assert out["selected"] == ["rojo"]
        assert any("invalida" in linea.lower() for linea in impresos)

    def test_tres_invalidos_devuelve_vacio(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Color?", ["rojo", "verde"],
                         input_fn=_fake_input(["99", "abc", "0"]),
                         print_fn=lambda *a: None)
        assert out == {"selected": [], "libre": None}

    def test_unica_rechaza_dos_numeros(self):
        from cognia.console.surveys import ask_survey
        # "1,2" es invalido en modo unico; reintenta y acepta "2"
        out = ask_survey("Color?", ["rojo", "verde"],
                         input_fn=_fake_input(["1,2", "2"]), print_fn=lambda *a: None)
        assert out["selected"] == ["verde"]

    def test_sin_opciones(self):
        from cognia.console.surveys import ask_survey
        out = ask_survey("Nada?", [], input_fn=_fake_input([]), print_fn=lambda *a: None)
        assert out == {"selected": [], "libre": None}
