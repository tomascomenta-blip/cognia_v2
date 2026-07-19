"""
tests/test_control_permisos.py
==============================
Tests del gate de seguridad de las manos de Cognia
(planes/JARVIS_COGNIA.md 2.5).

Lo que se fija aca es politica, no implementacion: que lo no declarado no sea
libre, que el contexto gane sobre el catalogo, y que sin canal para preguntar el
defecto sea NO.
"""

import pytest

from cognia.control.permisos import (NIVEL_CONFIRMAR, NIVEL_LIBRE,
                                     NIVEL_PROHIBIDO, Accion, GestorPermisos,
                                     ventana_es_sensible)


class TestVentanaSensible:
    @pytest.mark.parametrize("titulo", [
        "Bitwarden - Gestor de contraseñas",
        "1Password",
        # Variantes con sufijo: cazaron un bug real. Un patron con \b al final
        # ("\bkeepass\b") NO matchea "KeePassXC" porque "XC" impide el limite
        # de palabra, y ese es el cliente de escritorio mas usado.
        "KeePassXC",
        "Bitwarden Desktop",
        "1Password 8",
        "Nueva pestaña de incógnito - Google Chrome",
        "Private Browsing — Mozilla Firefox",
        "Homebanking | Banco Nación",
        "PayPal - Resumen",
        "Control de cuentas de usuario",
    ])
    def test_detecta_contextos_peligrosos(self, titulo):
        assert ventana_es_sensible(titulo) is True

    @pytest.mark.parametrize("titulo", [
        "Documento1 - Word",
        "cognia_v2 - Visual Studio Code",
        "YouTube - Google Chrome",
        "",
        None,
    ])
    def test_no_marca_ventanas_normales(self, titulo):
        assert ventana_es_sensible(titulo) is False


class TestNiveles:
    def test_lo_no_declarado_no_es_libre(self):
        """Una accion que nadie clasifico no puede colarse como libre."""
        g = GestorPermisos()
        assert g.nivel_de("hacer_algo_que_nadie_penso") == NIVEL_CONFIRMAR

    def test_lectura_y_navegacion_son_libres(self):
        g = GestorPermisos()
        for tipo in ("abrir_pestaña", "leer_pantalla", "buscar", "navegar"):
            assert g.nivel_de(tipo) == NIVEL_LIBRE

    def test_lo_destructivo_pide_confirmacion(self):
        g = GestorPermisos()
        for tipo in ("borrar", "enviar_correo", "pagar", "cerrar_sin_guardar"):
            assert g.nivel_de(tipo) == NIVEL_CONFIRMAR


class TestEvaluar:
    def test_accion_libre_pasa_sin_preguntar(self):
        preguntas = []
        g = GestorPermisos(confirmar=lambda p: preguntas.append(p) or True)
        v = g.evaluar(Accion("abrir_pestaña", "github.com"))
        assert v.permitida is True
        assert bool(v) is True
        assert preguntas == []          # no molesto al dueño por esto

    def test_accion_sensible_pregunta_y_respeta_el_si(self):
        g = GestorPermisos(confirmar=lambda p: True)
        v = g.evaluar(Accion("borrar", "informe.docx"))
        assert v.permitida is True
        assert "confirmado" in v.motivo

    def test_accion_sensible_respeta_el_no(self):
        g = GestorPermisos(confirmar=lambda p: False)
        v = g.evaluar(Accion("pagar", "1200 pesos"))
        assert v.permitida is False
        assert bool(v) is False

    def test_sin_canal_para_preguntar_el_defecto_es_no(self):
        """Si no hay forma de pedir permiso, no se asume que si."""
        g = GestorPermisos(confirmar=None)
        v = g.evaluar(Accion("borrar", "todo"))
        assert v.permitida is False
        assert "no hay canal" in v.motivo

    def test_si_falla_el_canal_de_confirmacion_se_deniega(self):
        def explota(pregunta):
            raise RuntimeError("el microfono se desconecto")
        g = GestorPermisos(confirmar=explota)
        v = g.evaluar(Accion("enviar_correo", "al jefe"))
        assert v.permitida is False
        assert "fallo al pedir confirmacion" in v.motivo

    def test_la_pregunta_describe_la_accion_concreta(self):
        vistas = []
        g = GestorPermisos(confirmar=lambda p: vistas.append(p) or False)
        g.evaluar(Accion("borrar", "fotos/2019"))
        assert len(vistas) == 1
        assert "borrar" in vistas[0] and "fotos/2019" in vistas[0]


class TestElContextoManda:
    def test_ventana_sensible_prohibe_hasta_lo_inofensivo(self):
        """Leer la pantalla del gestor de contraseñas es justo lo que no se
        quiere, por inofensiva que sea la accion en abstracto."""
        g = GestorPermisos(confirmar=lambda p: True, modo_estricto=True)
        v = g.evaluar(Accion("leer_pantalla"), ventana_activa="Bitwarden")
        assert v.nivel == NIVEL_PROHIBIDO
        assert v.permitida is False

    def test_ventana_sensible_prohibe_aunque_el_dueño_diria_que_si(self):
        """PROHIBIDO no se negocia: ni siquiera se pregunta."""
        preguntas = []
        g = GestorPermisos(confirmar=lambda p: preguntas.append(p) or True)
        v = g.evaluar(Accion("escribir_texto", "hola"),
                      ventana_activa="1Password")
        assert v.permitida is False
        assert preguntas == []

    def test_modo_no_estricto_deja_pasar_lo_libre(self):
        g = GestorPermisos(confirmar=lambda p: True, modo_estricto=False)
        libre = g.evaluar(Accion("leer_pantalla"), ventana_activa="Bitwarden")
        sensible = g.evaluar(Accion("escribir_texto", "x"),
                             ventana_activa="Bitwarden")
        assert libre.permitida is True
        assert sensible.permitida is False

    def test_ventana_normal_no_estorba(self):
        g = GestorPermisos(confirmar=lambda p: True)
        v = g.evaluar(Accion("abrir_pestaña", "x"),
                      ventana_activa="Documento1 - Word")
        assert v.permitida is True


class TestAuditoria:
    def test_registra_todo_lo_evaluado(self):
        g = GestorPermisos(confirmar=lambda p: False)
        g.evaluar(Accion("abrir_pestaña", "a"))
        g.evaluar(Accion("borrar", "b"))
        g.evaluar(Accion("leer_pantalla"), ventana_activa="KeePass")
        e = g.estadisticas()
        assert e["evaluadas"] == 3
        assert e["permitidas"] == 1
        assert e["denegadas"] == 2
        assert e["prohibidas_por_contexto"] == 1
