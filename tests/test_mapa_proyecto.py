"""
Mapa de proyecto: saber donde esta cada cosa sin leer los ficheros enteros.

Con n_ctx=8192, mandar el codigo completo de un directorio para preguntar
"donde esta la funcion que puntua programas" gasta la ventana en texto que casi
todo sobra. La idea sale de la investigacion que hizo Cognia sola el 2026-07-20
(code-review-graph, 21k estrellas) y el recorrido con ast lo escribio ella
misma en generated_programs/python_project_map_with_ast.

Estos tests fijan lo que se le anadio al integrarlo, que es lo que fallaba en
su version: recursividad, saltar venv, sobrevivir a ficheros que no parsean,
metodos con su clase y async def.
"""

import pytest

from cognia.mapa_proyecto import (
    buscar,
    mapear,
    mapear_fichero,
    resumen,
)

MODULO = '''\
import os


class Motor:
    """Un motor."""

    def arrancar(self):
        return True

    async def parar(self):
        return False


def suelta(x):
    return x * 2


async def suelta_async():
    return 1
'''


@pytest.fixture
def proyecto(tmp_path):
    (tmp_path / "motor.py").write_text(MODULO, encoding="utf-8")

    sub = tmp_path / "paquete"
    sub.mkdir()
    (sub / "hijo.py").write_text("def dentro():\n    return 1\n", encoding="utf-8")

    venv = tmp_path / "venv312" / "Lib"
    venv.mkdir(parents=True)
    (venv / "dependencia.py").write_text("def no_deberia_salir():\n    pass\n",
                                         encoding="utf-8")

    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "basura.py").write_text("def tampoco():\n    pass\n", encoding="utf-8")

    return tmp_path


class TestRecorrido:

    def test_encuentra_clases_y_funciones_con_su_linea(self, proyecto):
        fm = mapear(proyecto)["motor.py"]

        assert [c.nombre for c in fm.clases] == ["Motor"]
        nombres = {f.nombre for f in fm.funciones}
        assert {"arrancar", "suelta"} <= nombres
        assert all(s.linea > 0 for s in fm.clases + fm.funciones)

    def test_async_def_cuenta(self):
        """El visitor original solo miraba visit_FunctionDef."""
        fm = mapear_fichero_texto = None
        m = mapear
        # se usa el fixture indirectamente via mapear_fichero sobre un temporal
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.py"
            p.write_text("async def tarea():\n    return 1\n", encoding="utf-8")
            fm = mapear_fichero(p)
        assert [f.nombre for f in fm.funciones] == ["tarea"]

    def test_los_metodos_saben_de_que_clase_son(self, proyecto):
        fm = mapear(proyecto)["motor.py"]
        metodos = {f.nombre: f.clase for f in fm.funciones}

        assert metodos["arrancar"] == "Motor"
        assert metodos["parar"] == "Motor"
        assert metodos["suelta"] == "", "una funcion suelta no tiene clase"

    def test_etiqueta_de_metodo_lleva_la_clase(self, proyecto):
        fm = mapear(proyecto)["motor.py"]
        arrancar = next(f for f in fm.funciones if f.nombre == "arrancar")
        assert arrancar.etiqueta() == "Motor.arrancar"


class TestQueNoSeCuelaLoQueSobra:

    def test_es_recursivo(self, proyecto):
        """La version original solo miraba el primer nivel."""
        assert "paquete/hijo.py" in mapear(proyecto)

    def test_no_recursivo_si_se_pide(self, proyecto):
        assert "paquete/hijo.py" not in mapear(proyecto, recursivo=False)

    @pytest.mark.parametrize("ruta", ["venv312/Lib/dependencia.py",
                                      "__pycache__/basura.py"])
    def test_ignora_dependencias_y_basura(self, proyecto, ruta):
        """Sin esto el mapa se llena de site-packages y no sirve de nada."""
        assert ruta not in mapear(proyecto)


class TestRobustez:

    def test_un_fichero_que_no_parsea_no_tumba_el_mapa(self, tmp_path):
        (tmp_path / "roto.py").write_text("def a(\n", encoding="utf-8")
        (tmp_path / "sano.py").write_text("def b():\n    pass\n", encoding="utf-8")

        m = mapear(tmp_path)
        assert m["roto.py"].error, "deberia anotar el error"
        assert [f.nombre for f in m["sano.py"].funciones] == ["b"]

    def test_directorio_inexistente_devuelve_vacio(self, tmp_path):
        assert mapear(tmp_path / "no_existe") == {}


class TestSalida:

    def test_el_resumen_es_mucho_mas_corto_que_el_codigo(self, proyecto):
        fuente = (proyecto / "motor.py").read_text(encoding="utf-8")
        r = resumen(mapear(proyecto))

        assert "motor.py" in r
        assert "Motor:" in r
        assert len(r) < len(fuente) * 2   # y sobre un repo real, ordenes menos

    def test_buscar_localiza_el_simbolo(self, proyecto):
        hits = buscar(mapear(proyecto), "arrancar")

        assert len(hits) == 1
        assert "motor.py:" in hits[0]
        assert "Motor.arrancar" in hits[0]

    def test_buscar_no_distingue_mayusculas(self, proyecto):
        assert buscar(mapear(proyecto), "MOTOR")

    def test_mapa_vacio_no_rompe_el_resumen(self):
        assert "Sin ficheros" in resumen({})


class TestDependencias:
    """
    Los imports contestan lo que el mapa de clases no puede: "si cambio esto,
    que se rompe". La idea la propuso la propia Cognia el 2026-07-20 al
    sintetizar su investigacion (un comando para analizar dependencias); la
    atribucion que dio del repo era inventada, pero la idea era buena.
    """

    @pytest.fixture
    def paquete(self, tmp_path):
        (tmp_path / "base.py").write_text("def util():\n    pass\n", encoding="utf-8")
        (tmp_path / "medio.py").write_text(
            "import json\nfrom base import util\n\ndef m():\n    return util()\n",
            encoding="utf-8")
        (tmp_path / "alto.py").write_text(
            "import os\nimport medio\nimport base\n\ndef a():\n    pass\n",
            encoding="utf-8")
        return tmp_path

    def test_recoge_los_imports(self, paquete):
        fm = mapear(paquete)["medio.py"]
        assert "json" in fm.importa
        assert "base" in fm.importa

    def test_import_from_con_punto(self, tmp_path):
        (tmp_path / "rel.py").write_text("from . import hermano\n", encoding="utf-8")
        assert "." in mapear(tmp_path)["rel.py"].importa

    def test_solo_internos_descarta_la_stdlib(self, paquete):
        """json y os son ruido para la pregunta '¿a quien afecta mi cambio?'."""
        from cognia.mapa_proyecto import dependencias
        deps = dependencias(mapear(paquete))

        assert "base" in deps["medio.py"]
        assert "json" not in deps["medio.py"]
        assert "os" not in deps["alto.py"]

    def test_puede_incluir_los_externos_si_se_pide(self, paquete):
        from cognia.mapa_proyecto import dependencias
        deps = dependencias(mapear(paquete), solo_internos=False)
        assert "json" in deps["medio.py"]

    def test_quien_usa_da_el_grafo_al_reves(self, paquete):
        """Asi es como se pregunta de verdad: voy a tocar base, ¿a quien rompo?"""
        from cognia.mapa_proyecto import quien_usa
        usan = quien_usa(mapear(paquete), "base")

        assert usan == ["alto.py", "medio.py"]

    def test_quien_usa_acepta_el_nombre_con_extension(self, paquete):
        from cognia.mapa_proyecto import quien_usa
        assert quien_usa(mapear(paquete), "base.py") == ["alto.py", "medio.py"]

    def test_modulo_que_nadie_importa(self, paquete):
        from cognia.mapa_proyecto import quien_usa
        assert quien_usa(mapear(paquete), "inexistente") == []

    def test_encuentra_los_imports_absolutos_del_paquete(self, tmp_path):
        """
        Regresion medida el 2026-07-20 con el comando ya montado: guardando
        solo la raiz del modulo, `from cognia.compresion_salidas import x`
        quedaba como "cognia" y preguntar quien usa compresion_salidas
        respondia "nadie" — teniendo tres ficheros que lo importaban.
        """
        from cognia.mapa_proyecto import quien_usa

        (tmp_path / "compresion_salidas.py").write_text("def c(): pass\n",
                                                        encoding="utf-8")
        (tmp_path / "usuario.py").write_text(
            "from cognia.compresion_salidas import comprimir\n", encoding="utf-8")

        mapa = mapear(tmp_path)
        assert "cognia.compresion_salidas" in mapa["usuario.py"].importa
        assert quien_usa(mapa, "compresion_salidas") == ["usuario.py"]
        assert quien_usa(mapa, "cognia.compresion_salidas") == ["usuario.py"]
