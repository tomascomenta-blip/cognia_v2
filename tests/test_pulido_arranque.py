# -*- coding: utf-8 -*-
"""
tests/test_pulido_arranque.py
=============================
Regresion del pulido del ARRANQUE (2026-08-25): imports perezosos, banner sin
repeticiones y docs que dicen la verdad del codigo.

Medido con -X importtime en la maquina del dueno ANTES de tocar nada:
  import cognia.cli = 331-338 ms, de los que 220 eran `import cognia`
  (cognia/__init__.py hacia `from .cognia import Cognia`: 215 ms de clase que
  solo instancia cli.repl()); dentro, prometheus_client 39 ms (28,5 de
  platform_collector, dos Counters) y network.mesh_node 33,8 ms (cuatro
  metodos). DESPUES: import cognia.cli = 215-228 ms (-110 ms), import cognia =
  6 ms (-214), `cognia --help` 0,29 s -> 0,09 s de pared, REPL hasta /salir
  0,54 s -> 0,49 s. Lo que queda (prompt_toolkit 94 ms, cognia.config 70 ms)
  no es de esta tanda.

Salida del arranque (printf '/salir' | python -m cognia, 80 columnas):
  59 lineas / 8.844 B -> 57 lineas / 8.673 B: fuera el lema repetido en el
  cuerpo (ya sale en el borde inferior) y una de las dos lineas vacias
  consecutivas entre '/ayuda ...' y 'Para empezar'.

Los checks de "no se importa" corren en un SUBPROCESO limpio: dentro de
pytest conftest.py y el resto de la suite ya dejaron medio mundo en
sys.modules (mismo motivo que tests/test_arranque_lazy_imports.py).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _subproceso(codigo: str) -> dict:
    """Corre `codigo` en un python limpio; devuelve el dict que imprima como
    RESULTADO=<json>."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    prog = "import sys, json\n" + codigo + "\n"
    res = subprocess.run([PY, "-c", prog], capture_output=True, text=True,
                         env=env, cwd=str(ROOT), encoding="utf-8",
                         errors="replace", timeout=180)
    assert res.returncode == 0, f"el subproceso fallo:\n{res.stdout}\n{res.stderr}"
    marca = [l for l in res.stdout.splitlines() if l.startswith("RESULTADO=")]
    assert marca, f"sin RESULTADO en la salida:\n{res.stdout}\n{res.stderr}"
    return json.loads(marca[-1][len("RESULTADO="):])


def _cargados(codigo: str, nombres: tuple) -> dict:
    return _subproceso(
        codigo + "\n"
        f"print('RESULTADO=' + json.dumps({{n: (n in sys.modules) for n in {nombres!r}}}))"
    )


PESADOS = ("cognia.cognia", "prometheus_client", "network.mesh_node")
HAY_PROMETHEUS = importlib.util.find_spec("prometheus_client") is not None


# ---------------------------------------------------------------------------
# 1) La clase Cognia se importa al pedirla, no al importar el paquete
# ---------------------------------------------------------------------------
class TestClaseCogniaPerezosa:

    def test_import_cognia_no_carga_la_clase_ni_sus_pesados(self):
        """220 ms de 331: `import cognia` ya no arrastra cognia.cognia."""
        cargado = _cargados("import cognia", PESADOS)
        assert cargado == {n: False for n in PESADOS}, cargado

    def test_import_cognia_cli_no_carga_la_clase_ni_prometheus_ni_mesh(self):
        """Es el `-X importtime ... | grep prometheus/mesh_node -> 0 lineas`
        del informe, como test: importar el CLI no paga la clase."""
        cargado = _cargados("import cognia.cli", PESADOS)
        assert cargado == {n: False for n in PESADOS}, cargado

    def test_el_contrato_de_acceso_se_conserva(self):
        """Todos los caminos de antes siguen dando LA MISMA clase."""
        r = _subproceso(
            "import cognia\n"
            "a = 'Cognia' in dir(cognia)\n"
            "from cognia import Cognia\n"
            "import cognia.cognia as cc\n"
            "import cognia.cli as cli\n"
            "from cognia.cli import Cognia as C2\n"
            "print('RESULTADO=' + json.dumps({"
            "  'en_dir': a,"
            "  'paquete': cognia.Cognia is cc.Cognia,"
            "  'from_import': Cognia is cc.Cognia,"
            "  'cli_attr': cli.Cognia is cc.Cognia,"
            "  'cli_from': C2 is cc.Cognia,"
            "  'hasattr': hasattr(cognia, 'Cognia'),"
            "  'no_existe': hasattr(cognia, 'NoExiste'),"
            "  'cli_no_existe': hasattr(cli, 'NoExiste'),"
            "}))"
        )
        assert r == {"en_dir": True, "paquete": True, "from_import": True,
                     "cli_attr": True, "cli_from": True, "hasattr": True,
                     "no_existe": False, "cli_no_existe": False}, r

    def test_cognia_punto_cognia_sin_importar_el_submodulo(self):
        """`import cognia; cognia.cognia.Cognia` funcionaba porque el import
        de arriba colgaba el submodulo del paquete; se conserva."""
        r = _subproceso(
            "import cognia\n"
            "k = cognia.cognia.Cognia\n"
            "print('RESULTADO=' + json.dumps({'ok': k.__name__ == 'Cognia'}))"
        )
        assert r == {"ok": True}

    def test_mock_patch_de_cognia_Cognia_sigue_funcionando(self):
        from unittest import mock
        import cognia
        import cognia.cognia as cc
        centinela = object()
        with mock.patch("cognia.Cognia", centinela):
            assert cognia.Cognia is centinela
        assert cognia.Cognia is cc.Cognia

    def test_version_disponible_y_sin_importlib_metadata_al_importar(self):
        """__version__ tambien es perezoso (35,6 ms de importlib.metadata):
        sigue siendo una cadena no vacia y `import cognia` no anade
        importlib.metadata a sys.modules (si ya estaba, por site, no cuenta)."""
        r = _subproceso(
            "antes = 'importlib.metadata' in sys.modules\n"
            "import cognia\n"
            "despues = 'importlib.metadata' in sys.modules\n"
            "v = cognia.__version__\n"
            "from cognia import __version__ as v2\n"
            "print('RESULTADO=' + json.dumps({'sin_metadata': despues == antes,"
            " 'version': v, 'igual': v == v2, 'en_dir': '__version__' in dir(cognia),"
            " 'cacheada': '__version__' in vars(cognia)}))"
        )
        assert r["sin_metadata"], "import cognia volvio a pagar importlib.metadata"
        assert isinstance(r["version"], str) and r["version"], r
        assert r["igual"] and r["en_dir"] and r["cacheada"], r


# ---------------------------------------------------------------------------
# 2) prometheus_client al primer Counter
# ---------------------------------------------------------------------------
class TestPrometheusPerezoso:

    def test_importar_cognia_y_hypothesis_no_carga_prometheus(self):
        cargado = _cargados(
            "import cognia.cognia, cognia.reasoning.hypothesis",
            ("prometheus_client",))
        assert cargado["prometheus_client"] is False

    def test_los_contadores_aparecen_al_primer_uso_y_son_los_mismos(self):
        import cognia.cognia as cc
        a = cc._contadores_prometheus()
        b = cc._contadores_prometheus()
        assert isinstance(a, tuple) and len(a) == 2 and a == b
        if HAY_PROMETHEUS:
            assert all(x is not None for x in a), a
            assert cc._SLEEP_CYCLES is a[0] and cc._EPISODES_STORED is a[1]
        else:
            assert a == (None, None)

    def test_el_contador_de_ollama_cuenta_un_fallo_real(self, monkeypatch):
        """Comportamiento intacto: un fallo del circuit breaker incrementa el
        Counter (si prometheus_client esta) y el fail_count (siempre)."""
        from cognia.reasoning import hypothesis as h
        monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")   # puerto discard: rechaza
        cb = h._OllamaCircuitBreaker(timeout=0.5)
        contador = h._contador_errores_ollama()
        if HAY_PROMETHEUS:
            assert contador is not None
            antes = contador._value.get()
        assert cb.call(b"{}") is None
        assert cb.fail_count == 1
        if HAY_PROMETHEUS:
            assert contador._value.get() == antes + 1
            assert h._contador_errores_ollama() is contador
        else:
            assert contador is None

    @pytest.mark.skipif(not HAY_PROMETHEUS, reason="sin prometheus_client no hay registro que duplicar")
    def test_un_segundo_registro_reutiliza_el_counter_y_avisa(self, caplog):
        """Regresion (revision 2026-08-25): con el import perezoso, el ValueError
        'Duplicated timeseries' de un segundo registro (reload del modulo o dos
        copias de cognia.cognia en sys.path) saltaba dentro de observe() y de
        _sleep_sync() -- y la llamada siguiente devolvia (None, None) en
        silencio. Ahora se reutiliza el Counter ya registrado (mismo objeto,
        sigue contando) y se avisa por logging."""
        import importlib
        import logging
        import cognia.cognia as cc
        from cognia.reasoning import hypothesis as h
        a = cc._contadores_prometheus()
        a[0].inc()
        antes = a[0]._value.get()
        # Simula el reload: el modulo vuelve a su estado 'sin intentar'
        # (es lo que hace importlib.reload con las globales del modulo).
        cc._PROM_INTENTADO = False
        cc._SLEEP_CYCLES = cc._EPISODES_STORED = None
        with caplog.at_level(logging.WARNING, logger="cognia.reasoning.hypothesis"):
            b = cc._contadores_prometheus()
        assert b[0] is a[0] and b[1] is a[1], "el segundo registro tiene que devolver EL MISMO Counter"
        b[0].inc()
        assert a[0]._value.get() == antes + 1, "y seguir contando sobre el mismo"
        assert any("ya estaba registrado" in r.message for r in caplog.records),             "la degradacion tiene que ser visible en el log"
        # Lo mismo con un reload REAL del modulo de hipotesis (el otro Counter).
        c = h._contador_errores_ollama()
        importlib.reload(h)
        assert h._contador_errores_ollama() is c

    def test_un_nombre_imposible_de_registrar_degrada_a_none_avisando(self, caplog, monkeypatch):
        """Si el registro falla y el REGISTRY tampoco lo tiene, None + warning:
        nunca una excepcion desde observe()."""
        import logging
        import prometheus_client
        from cognia.reasoning import hypothesis as h
        from prometheus_client import REGISTRY

        class _Revienta:
            def __init__(self, *a, **k):
                raise ValueError("Duplicated timeseries in CollectorRegistry (simulado)")
        monkeypatch.setattr(prometheus_client, "Counter", _Revienta)
        assert "cognia_no_existe_total" not in getattr(REGISTRY, "_names_to_collectors", {})
        with caplog.at_level(logging.WARNING, logger="cognia.reasoning.hypothesis"):
            assert h.contador_prometheus_o_existente("cognia_no_existe_total", "x") is None
        assert any("no se pudo registrar cognia_no_existe_total" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 3) network.mesh_node al primer uso
# ---------------------------------------------------------------------------
class TestMeshPerezoso:

    def test_importar_cognia_cognia_no_carga_mesh_pero_pedirlo_si(self):
        r = _subproceso(
            "import cognia.cognia as cc\n"
            "antes = 'network.mesh_node' in sys.modules\n"
            "has = cc.HAS_MESH\n"
            "despues = 'network.mesh_node' in sys.modules\n"
            "print('RESULTADO=' + json.dumps({'antes': antes, 'has': has,"
            " 'despues': despues}))"
        )
        assert r["antes"] is False, "import cognia.cognia volvio a cargar network.mesh_node"
        # si el paquete existe, pedir HAS_MESH lo importa (y vale True); si no,
        # queda False y nada se carga
        assert r["despues"] is r["has"], r

    def test_los_metodos_mesh_responden_como_antes_sin_nodo(self):
        """Sin instanciar Cognia (caro): los metodos sobre un objeto sin nodo
        devuelven los mismos [WARN] de siempre."""
        import cognia.cognia as cc
        falso = types.SimpleNamespace(_mesh_node=None)
        assert cc.Cognia.mesh_status(falso) == "[WARN] MeshNode no disponible."
        assert cc.Cognia.connect_mesh_peer(falso, "ws://x") == "[WARN] MeshNode no disponible."
        assert cc.Cognia.publish_knowledge(falso, [{"a": 1}]) == "[WARN] MeshNode no disponible."
        esperado = ("[WARN] MeshNode no inicializado." if cc.HAS_MESH
                    else "[WARN] network/mesh_node.py no disponible.")
        assert cc.Cognia.start_mesh(falso) == esperado
        if cc.HAS_MESH:
            assert callable(cc.get_mesh_node) and cc.CogniaMeshNode.__name__ == "CogniaMeshNode"

    def test_instanciar_cognia_no_carga_mesh_pero_el_primer_metodo_mesh_si(self, tmp_path):
        """Cognia.__init__ pedia get_mesh_node() en cada arranque del REPL, asi
        que los 33,8 ms de network.mesh_node se pagaban igual (medido
        2026-08-25). Ahora el nodo es una propiedad perezosa: Cognia() no lo
        importa y el primer metodo mesh (mesh_status) lo crea y responde como
        siempre. Proceso limpio con COGNIA_DB_PATH temporal (Cognia() ~80 ms)."""
        r = _subproceso(
            "import os\n"
            f"os.environ['COGNIA_DB_PATH'] = {str(tmp_path)!r}\n"
            "import cognia.cognia as cc\n"
            "c = cc.Cognia()\n"
            "tras_init = 'network.mesh_node' in sys.modules\n"
            "intentado = c._mesh_intentado\n"
            "estado = c.mesh_status()\n"
            "tras_status = 'network.mesh_node' in sys.modules\n"
            "nodo = type(c._mesh_node).__name__\n"
            "print('RESULTADO=' + json.dumps({'tras_init': tras_init, 'intentado': intentado,"
            " 'tras_status': tras_status, 'nodo': nodo, 'estado': estado[:40], 'has': cc.HAS_MESH}))"
        )
        assert r["tras_init"] is False and r["intentado"] is False, r
        if r["has"]:
            assert r["tras_status"] is True and r["nodo"] == "CogniaMeshNode", r
            assert r["estado"].startswith("[NET] COGNIA MESH"), r
        else:
            assert r["nodo"] == "NoneType" and r["estado"] == "[WARN] MeshNode no disponible.", r


# ---------------------------------------------------------------------------
# 4) Banner: el lema una sola vez y sin dos lineas vacias seguidas
# ---------------------------------------------------------------------------
rich_console = pytest.importorskip("rich.console")
import cognia.cli as cli  # noqa: E402

VACIA_EN_MARCO = re.compile(r"^[│┃║]\s*[│┃║]\s*$")
FIN_BANNER_REMOTO = re.compile(r"[└╰][─═]{3,}.*sistema cognitivo local")


def _pintar(ancho: int, monkeypatch, alto: int = 60) -> str:
    monkeypatch.setenv("COGNIA_BANNER", "completo")
    buf = io.StringIO()
    con = rich_console.Console(
        file=buf, width=ancho, height=alto,
        theme=cli._THEMES[cli._THEME_ORDER[cli._theme_idx]],
        highlight=False, force_terminal=False, legacy_windows=False)
    monkeypatch.setattr(cli, "_console", con)
    cli._print_banner_completo()
    return buf.getvalue()


def test_el_arte_ya_no_lleva_el_lema():
    assert "Sistema cognitivo local" not in cli._BANNER_RAW
    assert "/ayuda para todos los comandos" in cli._BANNER_RAW


@pytest.mark.parametrize("ancho", [80, 100, 120])
def test_el_lema_sale_una_vez_y_no_hay_dos_vacias_seguidas(ancho, monkeypatch):
    salida = _pintar(ancho, monkeypatch)
    lineas = salida.splitlines()
    # una sola vez, en el borde inferior (el que lee el gate del remoto)
    assert sum("sistema cognitivo local" in l.lower() for l in lineas) == 1, salida
    assert any(FIN_BANNER_REMOTO.search(l) for l in lineas), \
        "el borde inferior con el lema es lo que cierra el gate de remoto/sesiones.py"
    # dentro del marco, nunca dos lineas vacias consecutivas
    for a, b in zip(lineas, lineas[1:]):
        assert not (VACIA_EN_MARCO.match(a) and VACIA_EN_MARCO.match(b)), (
            f"a {ancho} columnas hay dos lineas vacias seguidas dentro del marco:\n{salida}")
    # y sigue habiendo UNA linea de aire entre '/ayuda ...' y lo que sigue
    idx = next(i for i, l in enumerate(lineas) if "/ayuda para todos los comandos" in l)
    assert VACIA_EN_MARCO.match(lineas[idx + 1]), lineas[idx:idx + 3]
    assert not VACIA_EN_MARCO.match(lineas[idx + 2]), lineas[idx:idx + 3]


# ---------------------------------------------------------------------------
# 5) docs/ESTILO.md dice la verdad del codigo
# ---------------------------------------------------------------------------
def test_estilo_md_no_marca_pendiente_lo_que_ya_esta_cableado():
    doc = (ROOT / "docs" / "ESTILO.md").read_text(encoding="utf-8")
    pendientes = [l for l in doc.splitlines() if "PENDIENTE" in l.upper()]
    assert not [l for l in pendientes if "/estilo banner" in l], pendientes
    assert "no esta cableado" not in doc
    assert not [l for l in pendientes if "E11" in l], pendientes
    # y es verdad: /estilo banner repinta y la migracion E11 no dejo literales
    fuente = (ROOT / "cognia" / "cli.py").read_text(encoding="utf-8")
    assert re.search(r'elif sub == "banner":\s*\n(.*\n){0,6}?\s*_reimprimir_banner\(\)', fuente)
    assert "[success_dim]" not in fuente
    assert "| E11 |" in doc
