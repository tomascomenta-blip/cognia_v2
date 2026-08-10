"""
Ola 2 (I2): flota.estado() muestra los roles del summoner con import
PROTEGIDO (sin summoner, el estado clasico sigue intacto) y flota.main()
gana las acciones 'dormir', 'liberar <rol>' y 'ctx <N> [cache]' que
despachan al summoner. Todo con un summoner FALSO: nada de GPU ni procesos.
"""

import sys
import types

import pytest

import cognia
import cognia.flota as F


@pytest.fixture
def summoner_falso(monkeypatch):
    """Inyecta un modulo summoner falso donde flota lo importa
    (`from cognia import summoner` resuelve por atributo del paquete y por
    sys.modules: se parchean los dos)."""
    fake = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "cognia.summoner", fake)
    monkeypatch.setattr(cognia, "summoner", fake, raising=False)
    return fake


@pytest.fixture
def sin_summoner(monkeypatch):
    """Simula un arbol sin cognia/summoner.py (wheel viejo)."""
    monkeypatch.setitem(sys.modules, "cognia.summoner", None)
    monkeypatch.delattr(cognia, "summoner", raising=False)


class TestEstadoConRoles:

    def test_estado_muestra_los_roles_del_summoner(self, monkeypatch, capsys,
                                                   summoner_falso):
        monkeypatch.setattr(F, "props_puerto", lambda puerto: {})
        summoner_falso.estado_roles = lambda: {
            "cerebro": "VIVO pid=7 :8080 qwythos (sin idle)",
            "vlm": "dormido",
        }
        assert F.estado() == 0
        out = capsys.readouterr().out
        assert "roles (summoner):" in out
        assert "VIVO pid=7 :8080 qwythos" in out
        assert "dormido" in out
        # el estado clasico de puertos sigue primero, intacto
        assert "no responde" in out

    def test_estado_sobrevive_sin_summoner(self, monkeypatch, capsys,
                                           sin_summoner):
        monkeypatch.setattr(F, "props_puerto", lambda puerto: {})
        assert F.estado() == 0
        out = capsys.readouterr().out
        assert "no disponibles" in out
        assert ":8080" in out          # lo clasico no se perdio

    def test_estado_sobrevive_estado_roles_roto(self, monkeypatch, capsys,
                                                summoner_falso):
        monkeypatch.setattr(F, "props_puerto", lambda puerto: {})

        def revienta():
            raise RuntimeError("estado corrupto")
        summoner_falso.estado_roles = revienta
        assert F.estado() == 0
        assert "no disponibles" in capsys.readouterr().out


class TestAccionesNuevas:

    def test_dormir_despacha_barrido(self, capsys, summoner_falso):
        summoner_falso.barrido = lambda: ["vlm", "imagen"]
        assert F.main(["dormir"]) == 0
        assert "vlm, imagen" in capsys.readouterr().out

    def test_dormir_sin_nada_que_dormir(self, capsys, summoner_falso):
        summoner_falso.barrido = lambda: []
        assert F.main(["dormir"]) == 0
        assert "ninguno" in capsys.readouterr().out

    def test_dormir_sin_summoner_falla_honesto(self, capsys, sin_summoner):
        assert F.main(["dormir"]) == 1
        assert "summoner no disponible" in capsys.readouterr().err

    def test_liberar_exige_rol(self, capsys, summoner_falso):
        assert F.main(["liberar"]) == 1
        assert "Uso:" in capsys.readouterr().err

    def test_liberar_llama_al_summoner(self, capsys, summoner_falso):
        llamado = {}
        summoner_falso.liberar = lambda rol: llamado.update(rol=rol) or True
        assert F.main(["liberar", "vlm"]) == 0
        assert llamado == {"rol": "vlm"}
        assert "liberado" in capsys.readouterr().out

    def test_liberar_rol_dormido_devuelve_1(self, capsys, summoner_falso):
        summoner_falso.liberar = lambda rol: False
        assert F.main(["liberar", "vlm"]) == 1
        assert "no estaba vivo" in capsys.readouterr().out

    def test_ctx_exige_numero(self, capsys, summoner_falso):
        assert F.main(["ctx"]) == 1
        assert F.main(["ctx", "abc"]) == 1
        assert "Uso:" in capsys.readouterr().err

    def test_ctx_llama_escalar_ctx(self, capsys, summoner_falso):
        llamado = {}

        def escalar(n, cache=""):
            llamado.update(n=n, cache=cache)
            return {"ok": True, "n_ctx": n, "cache": cache or "f16",
                    "relanzado": True}
        summoner_falso.escalar_ctx = escalar
        assert F.main(["ctx", "200192", "f16"]) == 0
        assert llamado == {"n": 200192, "cache": "f16"}
        assert "relanzado" in capsys.readouterr().out

    def test_ctx_sin_cache_pasa_vacio(self, summoner_falso):
        llamado = {}

        def escalar(n, cache=""):
            llamado.update(n=n, cache=cache)
            return {"ok": True, "n_ctx": n, "cache": "f16",
                    "relanzado": False}
        summoner_falso.escalar_ctx = escalar
        assert F.main(["ctx", "32768"]) == 0
        assert llamado == {"n": 32768, "cache": ""}

    def test_ctx_fallo_visible(self, capsys, summoner_falso):
        def escalar(n, cache=""):
            raise RuntimeError("n_ctx 999999 no esta medido")
        summoner_falso.escalar_ctx = escalar
        assert F.main(["ctx", "999999"]) == 1
        assert "no esta medido" in capsys.readouterr().err


class TestNoRompeLoExistente:

    def test_accion_desconocida_menciona_las_nuevas(self, capsys):
        assert F.main(["bailar"]) == 1
        err = capsys.readouterr().err
        assert "dormir" in err and "liberar" in err and "ctx" in err
