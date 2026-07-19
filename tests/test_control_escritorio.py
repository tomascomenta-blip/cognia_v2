"""
tests/test_control_escritorio.py
================================
Tests de cognia/control/escritorio.py (planes/JARVIS_COGNIA.md 4.2).

Con un backend falso: los tests no tocan ventanas reales, para que corran en
cualquier maquina y no dependan de que haya un Explorador abierto. La prueba
contra el escritorio de verdad se hace por CLI.

Lo que mas importa fijar aca es que NINGUNA accion pueda saltarse el gate de
permisos, y que el contexto que se le pasa al gate sea la ventana activa REAL
en el momento de actuar.
"""

import pytest

from cognia.control.escritorio import Escritorio, _normalizar
from cognia.control.permisos import GestorPermisos


class _Ctrl:
    """Doble de un control de UI Automation."""

    def __init__(self, nombre, tipo="WindowControl", clase="", hijos=None):
        self.Name = nombre
        self.ControlTypeName = tipo
        self.ClassName = clase
        self._hijos = hijos or []
        self.activado = False
        self.enfocado = False
        self.clickeado = False

    def GetChildren(self):
        return list(self._hijos)

    def SetActive(self):
        self.activado = True

    def SetFocus(self):
        self.enfocado = True

    def Click(self, simulateMove=False):
        self.clickeado = True


class _BackendFalso:
    """Doble del modulo uiautomation."""

    def __init__(self, ventanas=None, activa="Documento1 - Word"):
        self.raiz = _Ctrl("root", hijos=ventanas or [])
        self._activa = _Ctrl(activa)
        self.tecleado = []

    def GetRootControl(self):
        return self.raiz

    def GetForegroundControl(self):
        return self._activa

    def WindowControl(self, searchDepth=1, Name=None):
        for w in self.raiz.GetChildren():
            if w.Name == Name:
                return w
        return None

    def WalkControl(self, raiz, maxDepth=6):
        def recorrer(c, prof):
            for h in c.GetChildren():
                yield h, prof
                if prof < maxDepth:
                    yield from recorrer(h, prof + 1)
        return recorrer(raiz, 1)

    def SendKeys(self, texto, waitTime=0):
        self.tecleado.append(texto)


def _escritorio(activa="Documento1 - Word", confirmar=None):
    ventanas = [
        _Ctrl("Explorador de archivos", hijos=[
            _Ctrl("Guardar", tipo="ButtonControl"),
            _Ctrl("Cancelar", tipo="ButtonControl"),
        ]),
        _Ctrl("Este equipo - Explorador de archivos"),
        _Ctrl("Configuración"),
        _Ctrl("cognia_v2 - Visual Studio Code"),
    ]
    backend = _BackendFalso(ventanas, activa=activa)
    esc = Escritorio(GestorPermisos(confirmar=confirmar), backend=backend)
    return esc, backend


class TestNormalizar:
    def test_ignora_acentos_y_mayusculas(self):
        assert _normalizar("Configuración") == _normalizar("CONFIGURACION")
        assert _normalizar("  Explorador  ") == "explorador"

    def test_cadena_vacia(self):
        assert _normalizar("") == ""
        assert _normalizar(None) == ""


class TestLeer:
    def test_ventana_activa(self):
        esc, _ = _escritorio(activa="Chrome")
        assert esc.ventana_activa() == "Chrome"

    def test_listar_ventanas(self):
        esc, _ = _escritorio()
        nombres = [v["nombre"] for v in esc.listar_ventanas()]
        assert "Configuración" in nombres
        assert len(nombres) == 4

    def test_buscar_ventana_sin_acentos(self):
        esc, _ = _escritorio()
        assert esc.buscar_ventana("configuracion")["nombre"] == "Configuración"

    def test_buscar_prefiere_la_coincidencia_mas_ajustada(self):
        """Con dos ventanas que dicen 'Explorador', gana la de titulo mas
        corto: es la que el dueño quiso nombrar."""
        esc, _ = _escritorio()
        assert esc.buscar_ventana("explorador")["nombre"] == "Explorador de archivos"

    def test_buscar_sin_resultado(self):
        esc, _ = _escritorio()
        assert esc.buscar_ventana("photoshop") is None
        assert esc.buscar_ventana("") is None


class TestElGateNoSePuedeSaltar:
    def test_leer_pantalla_bloqueado_en_ventana_sensible(self):
        esc, _ = _escritorio(activa="KeePassXC")
        assert esc.listar_elementos("Explorador de archivos") == []

    def test_enfocar_bloqueado_en_ventana_sensible(self):
        esc, backend = _escritorio(activa="Bitwarden Desktop")
        assert esc.enfocar("Configuración") is False
        assert backend.raiz.GetChildren()[2].activado is False

    def test_clic_sin_canal_de_confirmacion_se_deniega(self):
        """Sin forma de preguntar, una accion que modifica no se hace."""
        esc, backend = _escritorio(confirmar=None)
        assert esc.clic("Guardar", "Explorador de archivos") is False
        boton = backend.raiz.GetChildren()[0].GetChildren()[0]
        assert boton.clickeado is False

    def test_clic_se_hace_si_el_dueño_confirma(self):
        esc, backend = _escritorio(confirmar=lambda p: True)
        assert esc.clic("guardar", "Explorador de archivos") is True
        boton = backend.raiz.GetChildren()[0].GetChildren()[0]
        assert boton.clickeado is True

    def test_escribir_respeta_el_no_del_dueño(self):
        esc, backend = _escritorio(confirmar=lambda p: False)
        assert esc.escribir("hola") is False
        assert backend.tecleado == []

    def test_el_contexto_del_gate_es_la_ventana_activa_real(self):
        """El permiso se evalua contra la ventana que ESTA al frente, no
        contra la que el llamador menciona: si el foco esta en el gestor de
        contraseñas, da igual sobre que ventana se pidio actuar."""
        vistas = []
        esc, _ = _escritorio(activa="1Password 8",
                             confirmar=lambda p: vistas.append(p) or True)
        assert esc.clic("Guardar", "Explorador de archivos") is False
        assert vistas == []          # ni se pregunto: quedo prohibido


class TestAcciones:
    def test_enfocar_activa_la_ventana(self):
        esc, backend = _escritorio()
        assert esc.enfocar("configuracion") is True
        ventana = backend.raiz.GetChildren()[2]
        assert ventana.activado is True and ventana.enfocado is True

    def test_enfocar_ventana_inexistente(self):
        esc, _ = _escritorio()
        assert esc.enfocar("photoshop") is False

    def test_listar_elementos_filtra_por_tipo(self):
        esc, _ = _escritorio()
        elementos = esc.listar_elementos("Explorador de archivos")
        nombres = [e["nombre"] for e in elementos]
        assert "Guardar" in nombres and "Cancelar" in nombres
        assert all(e["tipo"] == "ButtonControl" for e in elementos)

    def test_escribir_manda_las_teclas(self):
        esc, backend = _escritorio(confirmar=lambda p: True)
        assert esc.escribir("hola mundo") is True
        assert backend.tecleado == ["hola mundo"]


class TestRobustez:
    def test_un_backend_roto_no_propaga_excepciones(self):
        """Si COM falla, las manos devuelven False y no tumban a Cognia."""
        class Roto:
            def __getattr__(self, nombre):
                def explota(*a, **k):
                    raise OSError("COM se cayo")
                return explota

        esc = Escritorio(GestorPermisos(confirmar=lambda p: True),
                         backend=Roto())
        assert esc.ventana_activa() == ""
        assert esc.listar_ventanas() == []
        assert esc.buscar_ventana("x") is None
        assert esc.enfocar("x") is False
        assert esc.clic("x") is False
