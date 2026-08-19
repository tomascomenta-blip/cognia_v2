# -*- coding: utf-8 -*-
"""Tests del detector de bucles (cognia/hermes/guardia_bucle.py).

Sin modelo ni red: el guardia es aritmetica sobre una ventana. Los casos son
los TRES patrones reales (A-A-A, A-B-A-B, A-B-C-A-B-C), las tools exentas
(polling legitimo), el caso sano (args distintos) y el bucle de contenido.
"""

import pytest

from cognia.hermes.guardia_bucle import (
    EXENTAS_COGNIA,
    GuardiaBucle,
    GuardiaContenido,
    firma_llamada,
)


def _registrar_todas(g, llamadas):
    return [g.registrar(n, a) for n, a in llamadas]


# --------------------------------------------------------------------------
# Forma 1: repeticion consecutiva A-A-A -> aviso, y despues bloqueo
# --------------------------------------------------------------------------

def test_repeticion_consecutiva_avisa_y_luego_bloquea():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = [g.registrar("leer_archivo", "cognia/cli.py") for _ in range(5)]

    assert vs[0]["estado"] == "ok"
    assert vs[1]["estado"] == "ok"
    # 3ra identica -> primer aviso, dirigido AL MODELO
    assert vs[2]["estado"] == "aviso"
    assert vs[2]["patron"] == "repeticion"
    assert vs[2]["repeticiones"] == 3
    assert "leer_archivo" in vs[2]["mensaje"]
    assert "cognia/cli.py" in vs[2]["mensaje"]
    # 4ta -> segundo (y ultimo) aviso
    assert vs[3]["estado"] == "aviso"
    # 5ta -> se acabaron los avisos: bloqueo con razon para el bucle
    assert vs[4]["estado"] == "bloqueo"
    assert vs[4]["razon"] == "bucle_detectado"
    assert g.bloqueado is True


def test_el_bloqueo_es_pegajoso():
    # Si el que llama IGNORA el corte y sigue registrando, el veredicto no se
    # ablanda solo.
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=1)
    for _ in range(4):
        g.registrar("ejecutar", "python roto.py")
    assert g.registrar("ejecutar", "python roto.py")["estado"] == "bloqueo"
    assert g.registrar("listar", ".")["estado"] == "bloqueo"


def test_max_avisos_cero_bloquea_a_la_primera_deteccion():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=0)
    vs = [g.registrar("buscar", "TODO") for _ in range(3)]
    assert [v["estado"] for v in vs] == ["ok", "ok", "bloqueo"]


# --------------------------------------------------------------------------
# Forma 2: ping-pong A-B-A-B
# --------------------------------------------------------------------------

def test_ping_pong_detectado():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = _registrar_todas(g, [
        ("leer_archivo", "a.py"),
        ("editar_archivo", "a.py|x|y"),
        ("leer_archivo", "a.py"),
        ("editar_archivo", "a.py|x|y"),
    ])
    assert [v["estado"] for v in vs[:3]] == ["ok", "ok", "ok"]
    assert vs[3]["estado"] == "aviso"
    assert vs[3]["patron"] == "ping_pong"
    assert vs[3]["repeticiones"] == 2
    # El mensaje nombra LAS DOS acciones de la alternancia (concreto > abstracto)
    assert "leer_archivo" in vs[3]["mensaje"]
    assert "editar_archivo" in vs[3]["mensaje"]


# --------------------------------------------------------------------------
# Forma 3: ciclo A-B-C-A-B-C
# --------------------------------------------------------------------------

def test_ciclo_de_tres_detectado():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    secuencia = [("leer_archivo", "a.py"), ("buscar", "def foo"), ("listar", "src")]
    vs = _registrar_todas(g, secuencia + secuencia)
    assert [v["estado"] for v in vs[:5]] == ["ok"] * 5
    assert vs[5]["estado"] == "aviso"
    assert vs[5]["patron"] == "ciclo_3"
    assert vs[5]["repeticiones"] == 2


def test_una_sola_vuelta_no_es_ciclo():
    # A-B-C-A-B (media vuelta) todavia no es evidencia de nada.
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = _registrar_todas(g, [
        ("leer_archivo", "a.py"), ("buscar", "x"), ("listar", "src"),
        ("leer_archivo", "a.py"), ("buscar", "x"),
    ])
    assert all(v["estado"] == "ok" for v in vs)


# --------------------------------------------------------------------------
# Tools exentas: el polling legitimo NO es un bucle
# --------------------------------------------------------------------------

def test_exentas_no_disparan():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2, exentas=EXENTAS_COGNIA)
    vs = [g.registrar("ver_salida", "pid=123") for _ in range(8)]
    assert all(v["estado"] == "ok" for v in vs)
    assert all(v["patron"] == "" for v in vs)
    assert g.bloqueado is False


def test_exentas_intercaladas_no_limpian_un_bucle_real():
    # Intercalar `ver_salida` entre repeticiones no puede blanquear el bucle:
    # si contara como "algo distinto", el modelo compraria impunidad gratis.
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2, exentas=EXENTAS_COGNIA)
    for _ in range(2):
        assert g.registrar("ejecutar", "python x.py")["estado"] == "ok"
        assert g.registrar("ver_salida", "pid=1")["estado"] == "ok"
    assert g.registrar("ejecutar", "python x.py")["estado"] == "aviso"


def test_sin_exentas_declaradas_el_default_no_inventa_politica():
    # El default es frozenset(): el guardia no decide solo que tool es polling.
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = [g.registrar("ver_salida", "pid=123") for _ in range(3)]
    assert vs[2]["estado"] == "aviso"


# --------------------------------------------------------------------------
# Caso sano: args distintos NO disparan
# --------------------------------------------------------------------------

def test_args_distintos_no_disparan():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = [g.registrar("leer_archivo", f"modulo_{i}.py") for i in range(8)]
    assert all(v["estado"] == "ok" for v in vs)
    assert g.bloqueado is False


def test_misma_tool_con_args_distintos_no_es_bucle_aunque_llene_la_ventana():
    g = GuardiaBucle(ventana=4, umbral=3, max_avisos=2)
    vs = [g.registrar("buscar", f"patron_{i}") for i in range(12)]
    assert all(v["estado"] == "ok" for v in vs)


# --------------------------------------------------------------------------
# Firma estable
# --------------------------------------------------------------------------

def test_firma_estable_e_independiente_del_orden_del_dict():
    assert firma_llamada("t", {"a": 1, "b": 2}) == firma_llamada("t", {"b": 2, "a": 1})
    assert firma_llamada("t", "  x   y  ") == firma_llamada("t", "x y")
    assert firma_llamada("t", "x") != firma_llamada("t", "y")
    assert firma_llamada("t1", "x") != firma_llamada("t2", "x")
    assert len(firma_llamada("t", "x")) == 16


def test_args_dict_equivalente_al_string_no_colisiona_por_accidente():
    # Dos llamadas realmente distintas tienen firmas distintas.
    assert firma_llamada("escribir_archivo", {"ruta": "a.py", "texto": "x"}) != \
        firma_llamada("escribir_archivo", {"ruta": "a.py", "texto": "y"})


def test_los_args_de_dict_repetidos_disparan_igual():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    vs = [g.registrar("escribir_archivo", {"ruta": "a.py", "texto": "hola"})
          for _ in range(3)]
    assert vs[2]["estado"] == "aviso"


# --------------------------------------------------------------------------
# Contador de reinicio: hacer algo distinto vuelve a dar credito
# --------------------------------------------------------------------------

def test_progreso_real_reinicia_la_escalada():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=1)
    for _ in range(3):
        g.registrar("ejecutar", "python x.py")   # 3ra -> aviso 1
    assert g._avisos == 1
    # Tres acciones GENUINAMENTE nuevas: el agente avanzo, la escalada vuelve a 0
    for nueva in ("uno.py", "dos.py", "tres.py"):
        g.registrar("leer_archivo", nueva)
    assert g._avisos == 0
    assert g.bloqueado is False


def test_reiniciar_borra_todo():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=0)
    for _ in range(3):
        g.registrar("ejecutar", "x")
    assert g.bloqueado is True
    g.reiniciar()
    assert g.bloqueado is False
    assert g.registrar("ejecutar", "x")["estado"] == "ok"


# --------------------------------------------------------------------------
# Camino caliente: nunca lanza
# --------------------------------------------------------------------------

@pytest.mark.parametrize("basura", [None, object(), b"\xff", {"k": object()},
                                    ["a", object()], 12345])
def test_registrar_nunca_lanza(basura):
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2, exentas=EXENTAS_COGNIA)
    v = g.registrar("tool_rara", basura)
    assert v["estado"] in ("ok", "aviso", "bloqueo")


def test_nombre_vacio_o_none_no_rompe():
    g = GuardiaBucle()
    assert g.registrar(None, None)["estado"] == "ok"
    assert g.registrar("", "")["estado"] == "ok"


def test_configuracion_absurda_degrada_sin_romper():
    g = GuardiaBucle(ventana="x", umbral=-5, max_avisos=None, exentas=None)
    assert g.ventana >= 2 and g.umbral >= 2 and g.max_avisos >= 0
    assert g.registrar("t", "a")["estado"] == "ok"


def test_veredicto_tiene_siempre_las_mismas_claves():
    g = GuardiaBucle(ventana=10, umbral=3, max_avisos=2)
    esperadas = {"estado", "patron", "mensaje", "razon", "tool", "firma",
                 "repeticiones", "avisos"}
    for _ in range(5):
        assert set(g.registrar("t", "a")) == esperadas


# --------------------------------------------------------------------------
# GuardiaContenido: el modelo repitiendo el mismo texto
# --------------------------------------------------------------------------

_BLOQUE = "no puedo seguir; voy a intentarlo otra vez ahora.\n"  # 50 chars


def test_bloque_de_prueba_mide_el_chunk_por_defecto():
    assert len(_BLOQUE) == 50


def test_contenido_repetido_dispara():
    g = GuardiaContenido()          # chunk=50, umbral=10 (constantes de la fuente)
    v = g.registrar(_BLOQUE * 12)
    assert v["estado"] == "bloqueo"
    assert v["patron"] == "contenido_repetido"
    assert v["razon"] == "bucle_detectado"
    assert g.bloqueado is True


def test_contenido_repetido_dispara_llegando_a_trozos():
    # El stream llega troceado: el detector acumula entre llamadas.
    g = GuardiaContenido()
    veredictos = [g.registrar(_BLOQUE) for _ in range(12)]
    assert veredictos[0]["estado"] == "ok"
    assert veredictos[-1]["estado"] == "bloqueo"


def test_contenido_variado_no_dispara():
    g = GuardiaContenido()
    texto = "\n".join(f"linea {i}: resultado parcial {i * 7} de la busqueda"
                      for i in range(400))
    assert g.registrar(texto)["estado"] == "ok"
    assert g.bloqueado is False


def test_contenido_lejano_no_dispara():
    # El mismo fragmento 12 veces, pero separado por texto distinto: es una
    # frase comun de un documento largo, no un bucle. El control de DISTANCIA
    # es lo que lo distingue.
    g = GuardiaContenido()
    relleno = ["".join(f"parrafo unico {i}-{j} con detalle propio. " for j in range(20))
               for i in range(12)]
    texto = "".join(_BLOQUE + r for r in relleno)
    assert g.registrar(texto)["estado"] == "ok"


def test_contenido_reiniciar_y_no_lanza():
    g = GuardiaContenido()
    g.registrar(_BLOQUE * 12)
    assert g.bloqueado is True
    g.reiniciar()
    assert g.bloqueado is False
    assert g.registrar("")["estado"] == "ok"
    assert g.registrar(None)["estado"] == "ok"
    assert g.registrar(12345)["estado"] in ("ok", "bloqueo")


def test_contenido_no_crece_sin_techo():
    # Una generacion larga y sana no puede hacer crecer el buffer sin limite.
    g = GuardiaContenido(chunk=10, umbral=5)
    for i in range(500):
        g.registrar(f"token-unico-{i} ")
    assert len(g._buffer) <= g._tope_buffer + 64
