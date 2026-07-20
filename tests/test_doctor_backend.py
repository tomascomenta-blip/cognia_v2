"""
Regresion: el doctor decia "Todo en orden" sin comprobar si Cognia puede pensar.

Medido el 2026-07-20 corriendo `python -m cognia.doctor` en la maquina del
dueno. El diagnostico revisaba Ollama (opcional), los shards en disco y la
velocidad de inferencia, y terminaba en verde — pero:

  - Ollama no existe en esta maquina.
  - Los shards estaban en disco ([OK] 4 en ~/.cognia/shards/...) y a la vez el
    orquestador los daba por no disponibles ([WARN] "shards no detectados"):
    dos chequeos del propio doctor contradiciendose.
  - La prueba de velocidad se omitia por eso mismo.
  - El backend que SI funcionaba — un llama-server en el 8080 — no se miraba
    en ningun sitio.

Resultado: "Todo en orden. Cognia esta lista." sin haber generado una sola
palabra. Un diagnostico que no puede fallar no sirve para diagnosticar.
"""

import pytest

import cognia.doctor as D


@pytest.fixture
def llm(monkeypatch):
    """Deja llm_local manipulable sin tocar el backend real."""
    import cognia.llm_local as L
    return L


class TestDetectaQueSiFunciona:

    def test_backend_vivo_pasa(self, llm, monkeypatch):
        monkeypatch.setattr(llm, "detectar_backend",
                            lambda forzar=False: {"tipo": "llama",
                                                  "url": "http://127.0.0.1:8080"})
        monkeypatch.setattr(llm, "generar", lambda *a, **k: "OK")

        assert D.check_llm_backend() is True

    def test_prueba_generando_no_solo_sondeando(self, llm, monkeypatch):
        """
        Un servidor que acepta conexiones pero no tiene modelo cargado
        responderia al ping igual: hay que pedirle texto.
        """
        llamado = []
        monkeypatch.setattr(llm, "detectar_backend",
                            lambda forzar=False: {"tipo": "llama", "url": "u"})
        monkeypatch.setattr(llm, "generar",
                            lambda *a, **k: llamado.append(1) or "OK")

        D.check_llm_backend()
        assert llamado, "no basta con detectar: hay que generar"


class TestFallaCuandoDebe:

    def test_sin_backend_es_FALLO_no_aviso(self, llm, monkeypatch):
        """
        Con _warn (que devuelve True) el doctor seguiria diciendo "Todo en
        orden" sin backend, que es justo el mensaje enganoso a corregir.
        """
        monkeypatch.setattr(llm, "detectar_backend", lambda forzar=False: None)

        assert D.check_llm_backend() is False

    def test_backend_que_no_genera_avisa(self, llm, monkeypatch):
        monkeypatch.setattr(llm, "detectar_backend",
                            lambda forzar=False: {"tipo": "llama", "url": "u"})
        monkeypatch.setattr(llm, "generar", lambda *a, **k: None)

        # Avisa pero no tumba: el servidor esta, quiza solo falta cargar modelo.
        assert D.check_llm_backend() is True

    def test_un_llm_local_roto_no_revienta_el_doctor(self, monkeypatch):
        """El diagnostico tiene que sobrevivir a que falle lo que diagnostica."""
        import builtins
        real_import = builtins.__import__

        def falso_import(nombre, *a, **k):
            if nombre == "cognia.llm_local":
                raise ImportError("modulo roto")
            return real_import(nombre, *a, **k)

        monkeypatch.setattr(builtins, "__import__", falso_import)
        assert D.check_llm_backend() is True   # avisa, no explota


class TestEstaEnLaListaDeChequeos:

    def test_el_doctor_lo_ejecuta(self):
        import inspect
        fuente = inspect.getsource(D.run_all)
        assert "check_llm_backend" in fuente

    def test_va_antes_que_los_shards(self):
        """Es la comprobacion que decide si Cognia puede trabajar."""
        import inspect
        fuente = inspect.getsource(D.run_all)
        assert fuente.index("check_llm_backend") < fuente.index("check_shards")


class TestBbrainTambienDiceElBackendReal:
    """
    Mismo punto ciego que el doctor, en el documento con el que Cognia entiende
    su propio entorno. Medido el 2026-07-20: bbrain.md decia

        - GGUF activo: no encontrado
        - Shards NPZ: SHARD_WEIGHTS_DIR no configurado
        - Ollama: no disponible

    teniendo un llama-server sano en el 8080. Cualquier agente que leyera ese
    fichero concluiria que Cognia no puede inferir.
    """

    def test_reporta_el_backend_que_detecta_llm_local(self, monkeypatch):
        import cognia.bbrain as B
        import cognia.llm_local as L

        monkeypatch.setattr(L, "detectar_backend",
                            lambda forzar=False: {"tipo": "llama",
                                                  "url": "http://127.0.0.1:8080"})
        lineas = "\n".join(B._backend_lines())

        assert "llm_local" in lineas
        assert "llama" in lineas
        assert "8080" in lineas

    def test_dice_claramente_cuando_no_hay_ninguno(self, monkeypatch):
        import cognia.bbrain as B
        import cognia.llm_local as L

        monkeypatch.setattr(L, "detectar_backend", lambda forzar=False: None)
        lineas = "\n".join(B._backend_lines())

        assert "NINGUNO" in lineas
        assert "silencio" in lineas   # avisa de la degradacion silenciosa

    def test_un_fallo_detectando_no_rompe_bbrain(self, monkeypatch):
        import cognia.bbrain as B
        import cognia.llm_local as L

        monkeypatch.setattr(L, "detectar_backend",
                            lambda forzar=False: (_ for _ in ()).throw(OSError("x")))
        lineas = "\n".join(B._backend_lines())

        assert "no se pudo comprobar" in lineas
