"""
tests/test_arranque_lazy_imports.py
Tests de regresion del ARRANQUE: los paquetes pesados no se importan al hacer
`import cognia`.

Medido con -X importtime el 2026-07-23 en la maquina del dueno:
  `import cognia` = 436ms, de los cuales networkx 110ms, asyncio 96ms y
  numpy 49ms (este ultimo importado desde cognia/config.py sin ningun uso).
Tras hacerlos lazy: 212ms (-38%). En el i3-10110U el factor es ~3x, asi que
son ~700ms menos de espera antes del primer prompt del CLI.

Sin estos tests el import pesado vuelve solo: alcanza con que alguien agregue
`import networkx as nx` arriba de cognia/knowledge/graph.py "por comodidad".

Los checks corren en un SUBPROCESO limpio: dentro de pytest, conftest.py y los
otros tests ya dejaron medio mundo en sys.modules.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _modulos_tras_importar(codigo: str, nombres: tuple) -> dict:
    """Corre `codigo` en un python limpio y devuelve {nombre: bool cargado}."""
    import os
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    prog = (
        "import sys, json\n"
        f"{codigo}\n"
        f"print('RESULTADO=' + json.dumps({{n: (n in sys.modules) for n in {nombres!r}}}))\n"
    )
    res = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                         text=True, env=env, cwd=str(ROOT),
                         encoding="utf-8", errors="replace", timeout=180)
    assert res.returncode == 0, f"el subproceso fallo:\n{res.stdout}\n{res.stderr}"
    marca = [l for l in res.stdout.splitlines() if l.startswith("RESULTADO=")]
    assert marca, f"sin RESULTADO en la salida:\n{res.stdout}\n{res.stderr}"
    import json
    return json.loads(marca[-1][len("RESULTADO="):])


class TestImportsPerezososEnArranque:

    def test_networkx_no_se_importa_al_importar_cognia(self):
        """110ms de los 436ms. Solo lo usa el KG, y solo cuando se lo consulta."""
        cargado = _modulos_tras_importar("import cognia", ("networkx",))
        assert cargado["networkx"] is False, (
            "networkx volvio a importarse en el arranque: revisar "
            "cognia/config.py (debe usar find_spec) y cognia/knowledge/graph.py "
            "(debe importar nx DENTRO de _get_graph/graph_path)"
        )

    def test_config_no_liga_el_simbolo_numpy(self):
        """`np` no se usaba en config.py: era un import muerto.

        HONESTIDAD: sacarlo NO acelero `import cognia` (211.8 vs 212.4ms, dentro
        del ruido) porque cognia/memory/episodic_fast.py y semantic_search.py
        importan numpy igual mas adelante en la misma cadena. Se quedo por ser
        codigo muerto, no por velocidad. El invariante testeable es ese: que el
        simbolo no vuelva a ligarse en config.
        """
        import cognia.config as cfg
        assert not hasattr(cfg, "np")


class TestComportamientoIntacto:
    """Las banderas siguen significando lo mismo y el KG sigue andando."""

    def test_has_networkx_sigue_siendo_verdadero_si_esta_instalado(self):
        import importlib.util
        from cognia.config import HAS_NETWORKX
        assert HAS_NETWORKX == (importlib.util.find_spec("networkx") is not None)

    def test_has_numpy_sigue_siendo_verdadero_si_esta_instalado(self):
        import importlib.util
        from cognia.config import HAS_NUMPY
        assert HAS_NUMPY == (importlib.util.find_spec("numpy") is not None)

    def test_graph_path_sigue_resolviendo_caminos(self, tmp_path):
        """El KG con nx lazy da el MISMO camino que con el import arriba."""
        from cognia.database import init_db
        from cognia.knowledge.graph import KnowledgeGraph
        db = str(tmp_path / "kg.db")
        init_db(db)
        kg = KnowledgeGraph(db_path=db)
        kg.add_triple("gato", "is_a", "animal")
        kg.add_triple("animal", "is_a", "ser vivo")
        assert kg.graph_path("gato", "ser vivo") == ["gato", "animal", "ser vivo"]

    def test_sleep_sigue_siendo_async_con_asyncio_lazy(self):
        """asyncio se importa dentro de Cognia.sleep(); debe seguir siendo corutina."""
        import inspect
        from cognia.cognia import Cognia
        assert inspect.iscoroutinefunction(Cognia.sleep)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
