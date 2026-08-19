# -*- coding: utf-8 -*-
"""
tests/test_estado_canal.py
==========================
Tests del canal de ESTADO (cognia/estado/canal.py). Sin modelo y sin red: todo
lo que aca se prueba es contabilidad determinista.

Lo que cada bloque defiende (y por que, no que):
  - el render prioriza restricciones -> el "governance decay" es el fallo
    SILENCIOSO: un limite de seguridad perdido no da error nunca.
  - el recorte se declara -> un recorte callado es la misma enfermedad que la
    compactacion que este modulo reemplaza.
  - la conservacion detecta perdidas -> es la metrica que nadie reporta.
  - los trazadores no son inferibles -> si lo fueran, medirian al resumidor
    adivinando, no conservando.
  - serializar/deserializar preserva -> el estado tiene que sobrevivir al
    proceso, si no vuelve a vivir dentro de la conversacion.
"""

import json

import pytest

from cognia.estado import canal


# ------------------------------------------------------------------ registro

def test_anotar_fichero_mide_el_disco(tmp_path):
    """El sha y los bytes salen del disco, no de lo que declara quien llama."""
    f = tmp_path / "hola.txt"
    f.write_bytes(b"abcde")
    e = canal.EstadoVerificado("obj", "t")
    d = canal.anotar_fichero(e, str(f), "crear")
    assert d["bytes"] == 5
    assert d["ok"] is True
    assert d["sha"] == __import__("hashlib").sha256(b"abcde").hexdigest()


def test_fichero_inexistente_sale_no_ok(tmp_path):
    """El fallo tipico no es que el modelo mienta: es que cree que escribio."""
    e = canal.EstadoVerificado()
    d = canal.anotar_fichero(e, str(tmp_path / "no_esta.py"), "crear")
    assert d["ok"] is False and d["sha"] is None


def test_restriccion_es_idempotente():
    e = canal.EstadoVerificado()
    assert canal.anotar_restriccion(e, "no tocar .env") is True
    assert canal.anotar_restriccion(e, "  NO TOCAR .env ") is False
    assert len(e["restricciones"]) == 1


def test_pendientes_y_resolver():
    e = canal.EstadoVerificado()
    canal.anotar_pendiente(e, "escribir los tests del canal")
    assert canal.anotar_pendiente(e, "escribir los tests del canal") is False
    # Resuelve por substring: el agente rara vez repite la frase exacta.
    assert canal.resolver_pendiente(e, "escribir los tests") is True
    assert e["pendientes"] == []
    assert canal.resolver_pendiente(e, "algo que no estaba") is False


def test_comando_guarda_la_cola_de_la_salida():
    """La cola y no la cabeza: el error util esta al final."""
    e = canal.EstadoVerificado()
    d = canal.anotar_comando(e, "pytest", 1, "linea1\n" * 200 + "FAILED tests/x.py", tope_salida=40)
    assert d["exit"] == 1
    assert "FAILED tests/x.py" in d["salida_corta"]
    assert len(d["salida_corta"]) <= 40


# -------------------------------------------------------------------- render

def _estado_gordo(n_ficheros=8, n_comandos=8):
    e = canal.EstadoVerificado("objetivo largo de prueba", "tX")
    canal.anotar_restriccion(e, "RESTRICCION UNO no publicar sin autorizacion")
    canal.anotar_restriccion(e, "RESTRICCION DOS nunca commitear el .env")
    for i in range(n_ficheros):
        canal.anotar_fichero(e, "modulo/fichero_%02d.py" % i, "editar", ok=True)
    for i in range(n_comandos):
        canal.anotar_comando(e, "comando_de_prueba_numero_%02d --con-flags-largos" % i, 0, "ok")
    canal.anotar_decision(e, "se descarto la via B por coste", "agente")
    canal.anotar_pendiente(e, "cablear el canal en el bucle")
    return e


def test_render_prioriza_restricciones():
    """Con un tope que NO da para todo, las restricciones siguen enteras y los
    comandos (lo menos critico) desaparecen."""
    e = _estado_gordo()
    txt = canal.render(e, tope_chars=350)
    assert "RESTRICCION UNO" in txt and "RESTRICCION DOS" in txt
    assert "comando_de_prueba_numero_00" not in txt
    # Y el orden es el declarado: restricciones antes que ficheros.
    assert txt.index("RESTRICCIONES") < txt.index("[RECORTE")


def test_restricciones_nunca_se_pierden_aunque_no_quepan():
    """Decision explicita: si las restricciones solas pasan el tope, se
    conservan igual y se AVISA. Tirarlas es el bug, no la solucion."""
    e = canal.EstadoVerificado("o", "t")
    for i in range(12):
        canal.anotar_restriccion(e, "restriccion numero %02d que es larga de verdad" % i)
    txt = canal.render(e, tope_chars=200)
    for i in range(12):
        assert ("restriccion numero %02d" % i) in txt
    assert "AVISO" in txt and "exceden tope_chars" in txt


def test_el_recorte_se_declara_con_cuentas():
    """Un recorte silencioso es la enfermedad que se esta atacando."""
    e = _estado_gordo()
    txt = canal.render(e, tope_chars=400)
    assert "[RECORTE:" in txt
    assert "lineas omitidas" in txt and "chars)" in txt
    assert "comandos" in txt.split("[RECORTE:")[1]


def test_render_respeta_el_tope_cuando_puede():
    e = _estado_gordo()
    txt = canal.render(e, tope_chars=600)
    assert len(txt) <= 600
    # Y sin tope apretado no aparece ninguna linea de recorte.
    completo = canal.render(e, tope_chars=100000)
    assert "[RECORTE" not in completo and "[AVISO" not in completo


def test_render_es_determinista():
    """Sin ts absolutos dentro: dos renders del mismo estado son iguales byte a
    byte, que es lo que permite diffear turnos."""
    e = _estado_gordo()
    assert canal.render(e, 800) == canal.render(e, 800)


def test_render_incluye_estado_de_verificacion_de_ficheros():
    e = canal.EstadoVerificado("o", "t")
    canal.anotar_fichero(e, "existe.py", "crear", ok=True)
    canal.anotar_fichero(e, "roto.py", "crear", ok=False)
    txt = canal.render(e, 1200)
    assert "OK    existe.py" in txt   # marca alineada a 5 chars + separador
    assert "FALLO roto.py" in txt


def test_render_reporta_progreso_verificado():
    """La linea que responde 'cuanto progreso verificado llevas' aparece aunque
    no haya fallos que listar."""
    e = canal.EstadoVerificado("o", "t")
    canal.anotar_verificacion(e, "pytest -q", True)
    canal.anotar_verificacion(e, "pytest -q", True)
    canal.anotar_verificacion(e, "ruff", False)
    txt = canal.render(e, 1200)
    assert "VERIFICACIONES (3): 2 OK / 1 FALLO" in txt
    assert "FALLO ruff" in txt


# ------------------------------------------------------------- conservacion

def test_conservacion_detecta_perdidas():
    e = canal.EstadoVerificado("o", "t")
    canal.anotar_fichero(e, "src/vivo.py", "editar", ok=True)
    canal.anotar_fichero(e, "src/perdido.py", "editar", ok=True)
    canal.anotar_restriccion(e, "nunca commitear el fichero .env ni tokens")
    canal.anotar_restriccion(e, "no publicar a PyPI sin autorizacion del dueno")

    post = "seguimos con src/vivo.py; recordar: nunca commitear el fichero .env ni tokens"
    d = canal.conservacion(e, post)
    assert d["recall_ficheros"] == 0.5
    assert d["recall_restricciones"] == 0.5
    assert d["n"] == 4
    perdidos = {(p["tipo"], p["valor"]) for p in d["perdidos"]}
    assert ("fichero", "src/perdido.py") in perdidos
    assert ("restriccion", "no publicar a PyPI sin autorizacion del dueno") in perdidos
    # La escala de 5 es la que publica la industria (2,19-2,45 sobre 5,0).
    assert d["escala_5"] == 2.5


def test_conservacion_todo_perdido_y_todo_conservado():
    e = canal.EstadoVerificado("o", "t")
    canal.anotar_fichero(e, "a/largo_nombre.py", "editar", ok=True)
    canal.anotar_restriccion(e, "usar siempre venv312 y nunca python pelado")
    assert canal.conservacion(e, "charla sin nada")["recall_global"] == 0.0
    entero = canal.render(e, 4000)
    assert canal.conservacion(e, entero)["recall_global"] == 1.0


def test_conservacion_acepta_parafraseo_pero_no_invencion():
    """El resumidor reescribe: exigir substring exacto mediria 'copiado
    literal'. Se pide cobertura de tokens distintivos (UMBRAL_COBERTURA)."""
    e = canal.EstadoVerificado("o", "t")
    canal.anotar_restriccion(e, "nunca commitear el fichero .env ni los tokens")
    parafraseado = "regla: jamas commitear .env, tokens fuera del repo, fichero prohibido"
    assert canal.conservacion(e, parafraseado)["recall_restricciones"] == 1.0
    otro_tema = "el color del boton quedo azul y el margen en 12 pixeles"
    assert canal.conservacion(e, otro_tema)["recall_restricciones"] == 0.0


def test_conservacion_sin_artefactos_devuelve_none():
    """Ni 0.0 ni 1.0: 'no habia nada que conservar' es una tercera cosa. Un 0.0
    aca seria un numero inventado."""
    d = canal.conservacion(canal.EstadoVerificado(), "texto cualquiera")
    assert d["recall_ficheros"] is None
    assert d["recall_global"] is None and d["n"] == 0


# --------------------------------------------------------------- trazadores

def test_trazadores_no_son_inferibles_del_resto():
    """Se siembran 4 trazadores y se le da al medidor TODO el resto del turno
    menos los trazadores. Si fueran inferibles, apareceria alguno."""
    e = canal.EstadoVerificado("refactor del modulo de contexto", "t")
    canal.anotar_restriccion(e, "usar siempre venv312")
    canal.anotar_fichero(e, "cognia/estado/canal.py", "editar", ok=True)
    canal.anotar_decision(e, "se elige la via A", "agente")
    trz = canal.sembrar_trazadores(e, k=4, semilla=1234)

    ids = [t["id"] for t in trz]
    assert len(set(ids)) == 4
    contexto_sin_trazadores = " ".join([
        "refactor del modulo de contexto", "usar siempre venv312",
        "cognia/estado/canal.py", "se elige la via A",
        "el umbral acordado", "NUNCA tocar el fichero legado",
        "decision ya tomada", "restriccion vigente no publicar sin la firma",
    ])
    d = canal.comprobar_trazadores(e, contexto_sin_trazadores)
    assert d["recall"] == 0.0
    assert sorted(d["perdidos"]) == sorted(ids)


def test_trazadores_se_detectan_cuando_sobreviven():
    e = canal.EstadoVerificado("o", "t")
    trz = canal.sembrar_trazadores(e, k=3, semilla=99)
    texto = "resumen: " + " y ".join(t["texto"] for t in trz)
    d = canal.comprobar_trazadores(e, texto)
    assert d["recall"] == 1.0 and d["n"] == 3


def test_trazadores_entran_al_canal_por_su_tipo():
    """No tienen seccion propia: si la tuvieran, el recall CON canal saldria
    1,0 siempre y estariamos midiendo el instrumento."""
    e = canal.EstadoVerificado("o", "t")
    canal.sembrar_trazadores(e, k=4, semilla=7)
    tipos = [t["tipo"] for t in e["trazadores"]]
    assert set(tipos) == {"valor", "fichero_prohibido", "decision", "restriccion"}
    assert len(e["restricciones"]) == 2   # fichero_prohibido + restriccion
    assert len(e["decisiones"]) == 2      # valor + decision
    entero = canal.render(e, 4000)
    assert canal.comprobar_trazadores(e, entero)["recall"] == 1.0


def test_trazadores_con_semilla_son_reproducibles():
    a = canal.EstadoVerificado("o", "t")
    b = canal.EstadoVerificado("o", "t")
    assert [t["id"] for t in canal.sembrar_trazadores(a, 4, semilla=5)] == \
           [t["id"] for t in canal.sembrar_trazadores(b, 4, semilla=5)]


# -------------------------------------------------------------- persistencia

def test_estado_sobrevive_a_serializar_y_deserializar():
    e = _estado_gordo()
    canal.sembrar_trazadores(e, k=2, semilla=3)
    vuelto = canal.deserializar(canal.serializar(e))
    assert vuelto == e
    # Y lo que se reinyecta es identico: el estado no pierde nada al viajar.
    assert canal.render(vuelto, 1500) == canal.render(e, 1500)


def test_deserializar_rellena_secciones_de_una_version_vieja():
    """Un estado guardado por una version anterior no debe reventar el render."""
    viejo = json.dumps({"turno": "t9", "objetivo": "algo", "pasos": 2,
                        "restricciones": ["no tocar .env"]})
    d = canal.deserializar(viejo)
    assert d["ficheros"] == {} and d["trazadores"] == []
    assert "no tocar .env" in canal.render(d, 500)


def test_guardar_y_cargar_en_directorio(tmp_path):
    e = _estado_gordo()
    ruta = canal.guardar(e, directorio=str(tmp_path))
    assert ruta.endswith("tX.json")
    assert canal.cargar("tX", directorio=str(tmp_path)) == e


def test_dir_estado_respeta_la_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_ESTADO_DIR", str(tmp_path / "otro"))
    assert str(canal.dir_estado()).endswith("otro")
    monkeypatch.delenv("COGNIA_ESTADO_DIR")
    assert ".cognia" in str(canal.dir_estado())


# ------------------------------------------------- la medicion, como test

def test_el_canal_mejora_el_recall_sobre_la_compactacion_real():
    """La medicion de `cognia.estado.medicion_conservacion`, como regresion.
    Si algun dia el canal deja de mejorar el recall, este test lo dice."""
    from cognia.estado import medicion_conservacion as med

    estado, mensajes = med.construir_turno()
    post = med.compactar_cola(mensajes, n=12)
    bloque = canal.render(estado, tope_chars=1200)

    sin = canal.conservacion(estado, post)
    con = canal.conservacion(estado, post + "\n" + bloque)

    assert sin["n"] == con["n"] == 15   # 6 ficheros + 5 restricciones + 4 trazadores
    assert con["recall_global"] > sin["recall_global"]
    assert sin["recall_restricciones"] == 0.0   # el fallo silencioso, reproducido
    assert con["recall_restricciones"] == 1.0
    assert con["recall_ficheros"] == 1.0


def test_el_bloque_del_canal_cabe_en_un_presupuesto_razonable():
    """1200 chars son ~300 tokens: el canal tiene que ser barato de reinyectar
    en CADA paso, si no el remedio compite con el problema."""
    from cognia.estado import medicion_conservacion as med

    estado, _ = med.construir_turno()
    assert len(canal.render(estado, tope_chars=1200)) <= 1200


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
