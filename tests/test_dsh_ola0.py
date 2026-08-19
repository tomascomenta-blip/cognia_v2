# -*- coding: utf-8 -*-
"""
DSH · Ola 0 — los ocho fallos SILENCIOSOS del harness (2026-08-18).

Todos comparten la misma forma: el sistema seguía adelante como si nada
mientras la información que necesitaba para decidir se perdía por el camino.
No fallaban ruidosamente; mentían en voz baja.

  1. La verificación de tests se cegaba cuando pytest coloreaba, y el agente
     recibía "pytest terminó con exit 0" en vez de "1 failed, 2 passed".
  2. Una excepción DENTRO del verificador se le presentaba al agente igual que
     un visto bueno (ambos devolvían "").
  3. kill_shell devolvía True aunque terminate() y kill() hubieran reventado.
  4. Los logs escribían por un stderr que ni el spinner ni el prompt capturan.
  5. Windows: nadie fijaba la code page, así que los bytes UTF-8 correctos
     llegaban a la consola como mojibake.
  6. Los avisos de dependencias opcionales gritaban en cada arranque, encima
     del banner, para siempre.

Cada test falla sin su arreglo.
"""

import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestLaVerificacionNoSeCiegaConColores:
    """El agente sólo lee el resumen para saber si acaba de romper algo."""

    def test_el_resumen_sobrevive_a_los_codigos_ansi(self):
        from cognia.harness import verificacion
        coloreado = "\x1b[32m1 failed, 2 passed\x1b[0m in 0.12s"
        resumen = verificacion._resumen_pytest(coloreado, 1)
        assert "1 failed" in resumen and "2 passed" in resumen
        # Sin el fix: "pytest termino con exit 1" — el detalle se perdía.
        assert "exit" not in resumen.lower()

    def test_el_comando_pide_salida_sin_color(self):
        # Cinturón y tirantes: además de limpiar ANSI, no se pide color.
        fuente = (Path(__file__).resolve().parent.parent / "cognia" /
                  "harness" / "verificacion.py").read_text(encoding="utf-8")
        assert '"--color=no"' in fuente

    def test_sigue_leyendo_un_resumen_limpio(self):
        # CONTRAFACTUAL: lo que ya funcionaba no cambia.
        from cognia.harness import verificacion
        assert "3 passed" in verificacion._resumen_pytest("3 passed in 0.1s", 0)


class TestElFalloDelVerificadorNoEsUnaAprobacion:

    def test_una_excepcion_se_le_dice_al_agente(self, monkeypatch, tmp_path):
        from cognia.harness import interceptor
        f = tmp_path / "x.py"
        f.write_text("print(1)\n", encoding="utf-8")

        import cognia.harness.verificacion as _ver

        def _explota(*a, **k):
            raise ImportError("pytest no está instalado")

        monkeypatch.setattr(_ver, "verificar_edicion", _explota)
        salida = interceptor._verificar(str(f), {})
        # Sin el fix esto era "" — indistinguible de "verificado, todo bien".
        assert salida != ""
        assert "no pude verificar" in salida
        assert "ImportError" in salida

    def test_un_fichero_no_verificable_sigue_callado(self, tmp_path):
        # CONTRAFACTUAL: el silencio legítimo (nada que verificar) se conserva.
        from cognia.harness import interceptor
        f = tmp_path / "notas.txt"
        f.write_text("hola", encoding="utf-8")
        assert interceptor._verificar(str(f), {}) == ""


class TestKillShellDiceLaVerdad:

    def test_devuelve_false_si_el_proceso_sobrevive(self, monkeypatch):
        from cognia.console import proc_registry as pr

        class _Zombi:
            """Ignora terminate() y kill(): el proceso que no se deja matar."""
            def poll(self):
                return None          # sigue vivo, siempre
            def terminate(self):
                pass
            def kill(self):
                pass
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cmd", timeout)

        monkeypatch.setattr(pr, "_REGISTRY",
                            {99: {"proc": _Zombi(), "status": "running"}},
                            raising=False)
        # Sin el fix: True ("shell terminado") con el proceso todavía vivo.
        assert pr.kill_shell(99) is False

    def test_devuelve_true_cuando_de_verdad_murio(self, monkeypatch):
        from cognia.console import proc_registry as pr

        class _Muerto:
            def poll(self):
                return 0
            def terminate(self):
                pass
            def kill(self):
                pass
            def wait(self, timeout=None):
                return 0

        monkeypatch.setattr(pr, "_REGISTRY",
                            {98: {"proc": _Muerto(), "status": "running"}},
                            raising=False)
        assert pr.kill_shell(98) is True

    def test_id_inexistente_sigue_siendo_false(self):
        from cognia.console import proc_registry as pr
        assert pr.kill_shell(123456) is False


class TestLosLogsPasanPorLaInterfaz:

    def test_enrutado_captura_y_restaurar_devuelve(self):
        from cognia import logger_config as lc
        vistos = []
        lc.enrutar_consola_a(lambda nivel, texto: vistos.append((nivel, texto)))
        try:
            logging.getLogger("cognia.prueba_dsh").warning("aviso de prueba")
            assert vistos, "el log no llego a la interfaz"
            assert vistos[0][0] == "WARNING"
            assert "aviso de prueba" in vistos[0][1]
        finally:
            lc.restaurar_enrutado()
        # Tras restaurar, el enrutado ya no recibe nada.
        antes = len(vistos)
        logging.getLogger("cognia.prueba_dsh").warning("otro aviso")
        assert len(vistos) == antes

    def test_el_destino_que_falla_no_tumba_el_log(self):
        from cognia import logger_config as lc

        def _destino_roto(nivel, texto):
            raise RuntimeError("la consola exploto")

        lc.enrutar_consola_a(_destino_roto)
        try:
            logging.getLogger("cognia.prueba_dsh").error("algo")  # no lanza
        finally:
            lc.restaurar_enrutado()


class TestConsolaDeWindows:

    def test_preparar_consola_no_lanza_y_reporta(self):
        from cognia.consola import preparar_consola_windows
        r = preparar_consola_windows()
        assert isinstance(r, dict) and "code_page" in r and "vt" in r

    def test_en_windows_pone_utf8(self):
        import os
        if os.name != "nt":
            import pytest
            pytest.skip("solo aplica a Windows")
        from cognia.consola import preparar_consola_windows
        # Sin esto, el banner Braille sale como una pared de '?' con cp1252.
        assert preparar_consola_windows()["code_page"] is True


class TestElArranqueNoGrita:

    def test_las_dependencias_ausentes_se_registran_sin_imprimir(self):
        from cognia import config
        assert hasattr(config, "degradados")
        assert isinstance(config.degradados(), list)

    def test_registrar_degradado_no_escribe_en_pantalla(self, capsys):
        from cognia import config
        config.registrar_degradado("cosa", "efecto", "arreglo")
        cap = capsys.readouterr()
        assert cap.out == "" and cap.err == ""
        assert any(d["que"] == "cosa" for d in config.degradados())

    def test_importar_el_cli_no_escupe_warnings(self):
        # El test que cierra el ciclo: importar el paquete no puede escribir
        # NADA en stderr. Es lo que el usuario ve encima del banner.
        r = subprocess.run(
            [sys.executable, "-c", "import cognia.config"],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent))
        assert "WARNING" not in (r.stderr or ""), r.stderr[:400]


class TestLosAvisosSilenciadosSE_MUESTRAN:
    """Silenciar un aviso solo vale si alguien lo ENSEÑA en otro sitio. Si no,
    no se ha silenciado: se ha perdido. Lo cazó la revisión adversarial."""

    def test_el_doctor_lee_los_degradados(self):
        from cognia import doctor
        assert hasattr(doctor, "check_degradados")
        fuente = (Path(__file__).resolve().parent.parent / "cognia" /
                  "doctor.py").read_text(encoding="utf-8")
        assert "check_degradados" in fuente
        assert "Capacidades degradadas" in fuente,             "el check tiene que estar en la lista de secciones, no solo definido"

    def test_el_check_reporta_lo_registrado(self, capsys):
        from cognia import config, doctor
        config.registrar_degradado("cosa-de-prueba", "algo va peor", "instala x")
        doctor.check_degradados()
        salida = capsys.readouterr().out
        assert "cosa-de-prueba" in salida and "algo va peor" in salida


class TestShellKillNoMienteEnElCli:
    """kill_shell ya devuelve la verdad; el CLI la contaba al reves."""

    def test_el_cli_distingue_los_TRES_casos(self):
        fuente = (Path(__file__).resolve().parent.parent / "cognia" /
                  "cli.py").read_text(encoding="utf-8")
        i = fuente.index("def _slash_shell_kill")
        bloque = fuente[i:i + 1400]
        assert "get_status" in bloque, "hay que preguntar si EXISTE"
        assert "SIGUE VIVO" in bloque, "un kill fallido no es 'no existe'"

