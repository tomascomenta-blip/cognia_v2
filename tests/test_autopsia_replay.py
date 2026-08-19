"""
tests/test_autopsia_replay.py
=============================
Tests de cognia/autopsia/replay.py. SIN modelo y SIN red: la unica dependencia
ejecutable (`run_tool_fn`) se inyecta como callable, que es la regla del repo.

Lo que se prueba, y por que cada cosa:
  - normalizacion de los DOS formatos del repo (legacy de loop.py y grabador);
  - determinismo: dos reproducciones en cache dan la MISMA huella (si no, el
    replay no sirve como sustrato causal);
  - la cache NO colapsa la misma accion repetida con resultados distintos (el
    bug que fabricaria evidencia);
  - los tres modos de ablacion;
  - divergencia por tool/args/ok y por longitud;
  - el informe NO MIENTE sobre cache vs real: fuentes declaradas, mezcla
    marcada, ausentes contados, y el modo real sin ws no corre nada.
"""
import json

import pytest

from cognia.autopsia import replay as R


# --------------------------------------------------------------------------
# Material de prueba: los dos formatos, con el mismo contenido.
# --------------------------------------------------------------------------

TRAZA_LEGACY = [
    {"action": "escribir_archivo", "args": "a.txt | hola", "ok": True,
     "result_head": "RESULTADO escribir_archivo: escrito a.txt (4 bytes)"},
    {"action": "leer_archivo", "args": "a.txt", "ok": True,
     "result_head": "hola"},
    {"action": "ejecutar", "args": "python -c \"print(1)\"", "ok": True,
     "result_head": "1\nexit code: 0"},
]

TRAZA_GRABADOR = {
    "id": "20260819-000000-abcdef",
    "titulo": "prueba",
    "tarea": "escribir y leer",
    "workspace": "/tmp/ws",
    "pasos": [
        {"tipo": "paso", "n": 1, "tool": "escribir_archivo", "args": "a.txt | hola",
         "ok": True, "resumen_resultado": "RESULTADO escribir_archivo: escrito a.txt (4 bytes)",
         "duracion_s": 0.01, "ficheros_tocados": ["a.txt"], "comando": "",
         "exit_code": None, "paso_agente": 1, "via_bus": False},
        {"tipo": "paso", "n": 2, "tool": "leer_archivo", "args": "a.txt",
         "ok": True, "resumen_resultado": "hola", "duracion_s": 0.002,
         "ficheros_tocados": ["a.txt"], "comando": "", "exit_code": None,
         "paso_agente": 1, "via_bus": True},
        {"tipo": "paso", "n": 3, "tool": "ejecutar", "args": "python -c \"print(1)\"",
         "ok": True, "resumen_resultado": "1\nexit code: 0", "duracion_s": 0.4,
         "ficheros_tocados": [], "comando": "python -c \"print(1)\"",
         "exit_code": 0, "paso_agente": 2, "via_bus": False},
    ],
}


# --------------------------------------------------------------------------
# 1. Normalizacion de los dos formatos.
# --------------------------------------------------------------------------

def test_normaliza_formato_legacy():
    t = R.normalizar(TRAZA_LEGACY)
    assert t.origen == "legacy"
    assert len(t) == 3
    assert [p["tool"] for p in t.pasos] == ["escribir_archivo", "leer_archivo", "ejecutar"]
    assert [p["n"] for p in t.pasos] == [1, 2, 3]
    assert t.pasos[1]["resumen"] == "hola"
    assert t.es_real is True


def test_normaliza_formato_grabador():
    t = R.normalizar(TRAZA_GRABADOR)
    assert t.origen == "grabador"
    assert t.id == "20260819-000000-abcdef"
    assert t.tarea == "escribir y leer"
    assert len(t) == 3
    assert t.pasos[2]["exit_code"] == 0
    assert t.pasos[2]["comando"] == "python -c \"print(1)\""
    assert t.pasos[1]["via_bus"] is True


def test_los_dos_formatos_dan_la_MISMA_huella():
    # Es el punto de la normalizacion: la misma trayectoria escrita en dos
    # formatos tiene que ser la MISMA trayectoria. Si no, todo lo de arriba
    # (cache, ablacion, divergencia) compara peras con manzanas.
    assert R.huella(R.normalizar(TRAZA_LEGACY)) == R.huella(R.normalizar(TRAZA_GRABADOR))


def test_normalizar_es_idempotente():
    t1 = R.normalizar(TRAZA_LEGACY)
    t2 = R.normalizar(t1)
    assert R.huella(t1) == R.huella(t2)
    assert len(t2) == len(t1)


def test_normalizar_tolera_basura_y_lo_ANOTA():
    t = R.normalizar([{"action": "listar", "args": ".", "ok": True, "result_head": "x"},
                      "esto no es un dict",
                      {"args": "sin tool", "ok": True},
                      None])
    assert len(t) == 1
    assert len(t.avisos) == 3  # los 3 saltados quedan declarados, no escondidos


def test_normalizar_entradas_degeneradas():
    for basura in (None, 42, "una cadena"):
        t = R.normalizar(basura)
        assert len(t) == 0
        assert t.avisos, f"{basura!r} deberia dejar aviso"


def test_normaliza_objeto_con_a_dict():
    class _Grabacion:
        def a_dict(self):
            return TRAZA_GRABADOR
    t = R.normalizar(_Grabacion())
    assert len(t) == 3 and t.origen == "grabador"


def test_cargar_jsonl_del_grabador(tmp_path):
    ruta = tmp_path / "g.jsonl"
    lineas = [{"tipo": "cabecera", "id": "g1", "titulo": "t", "tarea": "hacer algo",
               "workspace": "w", "ts_inicio": 1.0}]
    lineas += TRAZA_GRABADOR["pasos"]
    lineas += [{"tipo": "anotacion", "campo": "titulo", "valor": "titulo final"},
               {"tipo": "cierre", "ts_fin": 2.0, "ok": True, "pasos": 3}]
    with open(ruta, "w", encoding="utf-8") as f:
        for obj in lineas:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.write('{"tipo": "paso", "n": 4, ')  # linea cortada a mitad: caso NORMAL
    t = R.cargar_jsonl(ruta)
    assert len(t) == 3
    assert t.titulo == "titulo final"   # la anotacion gana
    assert t.tarea == "hacer algo"
    assert any("ilegible" in a for a in t.avisos)


# --------------------------------------------------------------------------
# 2. Firma y huella.
# --------------------------------------------------------------------------

def test_firma_es_estable_y_distingue_args():
    assert R.firma("leer_archivo", "a.txt") == R.firma("leer_archivo", "a.txt")
    assert R.firma("leer_archivo", "a.txt") != R.firma("leer_archivo", "b.txt")
    assert R.firma("leer_archivo", "a.txt") != R.firma("borrar_archivo", "a.txt")
    # No normaliza espacios a proposito: en este repo los args son protocolo.
    assert R.firma("x", " a ") != R.firma("x", "a")


def test_huella_cambia_si_cambia_el_orden():
    t1 = R.normalizar(TRAZA_LEGACY)
    t2 = R.normalizar(list(reversed(TRAZA_LEGACY)))
    assert R.huella(t1) != R.huella(t2)


def test_huella_no_depende_de_los_resultados():
    otra = [dict(p, result_head="OTRA COSA") for p in TRAZA_LEGACY]
    assert R.huella(R.normalizar(otra)) == R.huella(R.normalizar(TRAZA_LEGACY))


# --------------------------------------------------------------------------
# 3. Cache y reproduccion determinista.
# --------------------------------------------------------------------------

def test_grabar_resultados_indexa_todo():
    c = R.grabar_resultados(TRAZA_LEGACY)
    assert len(c) == 3
    assert c.firmas() == 3


def test_reproducir_en_cache_es_determinista():
    t = R.normalizar(TRAZA_LEGACY)
    c = R.grabar_resultados(t)
    a = R.reproducir(t, cache=c)
    b = R.reproducir(t, cache=c)
    assert a["ok"] and b["ok"]
    assert a["huella"] == b["huella"]
    assert a["n_pasos"] == b["n_pasos"] == 3
    assert a["n_cache"] == 3 and a["n_real"] == 0


def test_verificar_determinismo():
    t = R.normalizar(TRAZA_GRABADOR)
    c = R.grabar_resultados(t)
    v = R.verificar_determinismo(t, c, veces=3)
    assert v["determinista"] is True
    assert len(set(v["huellas"])) == 1


def test_cache_NO_colapsa_la_misma_accion_con_resultados_distintos():
    # El bug que fabricaria evidencia: leer el mismo fichero antes y despues de
    # editarlo tiene la MISMA firma y resultados DISTINTOS.
    traza = [
        {"action": "leer_archivo", "args": "a.txt", "ok": True, "result_head": "viejo"},
        {"action": "editar_archivo", "args": "a.txt | viejo | nuevo", "ok": True,
         "result_head": "RESULTADO editar_archivo: ok"},
        {"action": "leer_archivo", "args": "a.txt", "ok": True, "result_head": "nuevo"},
    ]
    inf = R.reproducir(traza, cache=R.grabar_resultados(traza))
    assert [p["resultado"] for p in inf["pasos"]][0] == "viejo"
    assert [p["resultado"] for p in inf["pasos"]][2] == "nuevo"
    assert inf["n_cache"] == 3


def test_reproducir_hasta_es_inclusivo():
    t = R.normalizar(TRAZA_LEGACY)
    c = R.grabar_resultados(t)
    inf = R.reproducir(t, hasta=1, cache=c)
    assert inf["n_pasos"] == 2
    assert inf["pasos"][-1]["tool"] == "leer_archivo"


def test_reproducir_hasta_fuera_de_rango_avisa_y_no_revienta():
    t = R.normalizar(TRAZA_LEGACY)
    inf = R.reproducir(t, hasta=99, cache=R.grabar_resultados(t))
    assert inf["n_pasos"] == 3
    assert any("supera el ultimo paso" in a for a in inf["avisos"])


def test_reproducir_sin_cache_declara_los_AUSENTES():
    inf = R.reproducir(TRAZA_LEGACY)  # modo cache, sin cache
    assert inf["modo"] == "cache"
    assert inf["n_ausente"] == 3 and inf["n_cache"] == 0
    assert inf["ok"] is False           # una reproduccion vacia NO es un exito
    assert "INCOMPLETA" in inf["error"]


def test_cache_ajena_no_se_hace_pasar_por_reproduccion():
    t = R.normalizar(TRAZA_LEGACY)
    cache_ajena = R.grabar_resultados([
        {"action": "listar", "args": ".", "ok": True, "result_head": "x"}])
    inf = R.reproducir(t, cache=cache_ajena)
    assert inf["n_cache"] == 0 and inf["n_ausente"] == 3
    assert all(p["fuente"] == "ausente" for p in inf["pasos"])


def test_reproducir_de_trayectoria_vacia():
    inf = R.reproducir([], cache=None)
    assert inf["ok"] is True and inf["n_pasos"] == 0


# --------------------------------------------------------------------------
# 4. El informe NO MIENTE sobre cache vs real.
# --------------------------------------------------------------------------

def _run_tool_falso(registro):
    def _fn(tool, args, ctx):
        registro.append((tool, args))
        return f"RESULTADO {tool}: ejecutado de verdad"
    return _fn


def test_modo_real_exige_ws_y_NO_EJECUTA_NADA_sin_el():
    llamadas = []
    inf = R.reproducir(TRAZA_LEGACY, run_tool_fn=_run_tool_falso(llamadas))
    assert inf["ok"] is False
    assert llamadas == []                      # lo importante: no toco el mundo
    assert "ws" in inf["error"]
    assert inf["n_pasos"] == 0


def test_modo_real_marca_cada_paso_como_real(tmp_path):
    llamadas = []
    traza = [{"action": "listar", "args": ".", "ok": True, "result_head": "x"},
             {"action": "fecha", "args": "", "ok": True, "result_head": "2026"}]
    inf = R.reproducir(traza, run_tool_fn=_run_tool_falso(llamadas),
                       ws=str(tmp_path))
    assert inf["modo"] == "real"
    assert inf["n_real"] == 2 and inf["n_cache"] == 0
    assert inf["mezclado"] is False
    assert all(p["fuente"] == "real" for p in inf["pasos"])
    assert len(llamadas) == 2


def test_modo_mixto_marca_MEZCLADO_y_dice_que_paso_vino_de_donde(tmp_path):
    llamadas = []
    traza = [{"action": "listar", "args": ".", "ok": True, "result_head": "grabado"},
             {"action": "fecha", "args": "", "ok": True, "result_head": "2026"}]
    # cache que solo tiene el PRIMER paso
    cache = R.grabar_resultados([traza[0]])
    inf = R.reproducir(traza, run_tool_fn=_run_tool_falso(llamadas), ws=str(tmp_path),
                       cache=cache, preferir_cache=True)
    assert inf["modo"] == "mixto"
    assert inf["mezclado"] is True
    assert inf["n_cache"] == 1 and inf["n_real"] == 1
    assert inf["pasos"][0]["fuente"] == "cache"
    assert inf["pasos"][0]["resultado"] == "grabado"
    assert inf["pasos"][1]["fuente"] == "real"
    assert llamadas == [("fecha", "")]          # solo se ejecuto el que faltaba
    assert "MEZCLADO" in R.resumen_linea(inf)


def test_modo_real_RECHAZA_args_sospechosos_de_truncados(tmp_path):
    llamadas = []
    largo = "a.txt | " + "x" * 300
    traza = [{"action": "escribir_archivo", "args": largo[:R.LIMITE_ARGS_LEGACY],
              "ok": True, "result_head": "escrito"}]
    inf = R.reproducir(traza, run_tool_fn=_run_tool_falso(llamadas), ws=str(tmp_path))
    assert inf["n_rechazado"] == 1
    assert llamadas == []                       # NO escribio el fichero mutilado
    assert inf["pasos"][0]["fuente"] == "rechazado"
    assert "MUTILADOS" in inf["pasos"][0]["motivo"]
    assert inf["ok"] is False
    # y con el flag explicito si corre
    inf2 = R.reproducir(traza, run_tool_fn=_run_tool_falso(llamadas), ws=str(tmp_path),
                        permitir_args_truncados=True)
    assert inf2["n_real"] == 1 and len(llamadas) == 1


def test_limite_de_truncado_depende_de_via_bus(tmp_path):
    args_120 = "x" * 120     # entero para el legacy (limite 200), sospechoso por bus
    base = {"tool": "leer_archivo", "args": args_120, "ok": True,
            "resumen_resultado": "y", "n": 1}
    t_bus = R.normalizar({"pasos": [dict(base, via_bus=True)]})
    t_dir = R.normalizar({"pasos": [dict(base, via_bus=False)]})
    assert t_bus.pasos[0]["args_sospechoso"] is True
    assert t_dir.pasos[0]["args_sospechoso"] is False


def test_modo_real_captura_la_excepcion_de_la_tool(tmp_path):
    def _explota(tool, args, ctx):
        raise RuntimeError("boom")
    inf = R.reproducir([{"action": "listar", "args": ".", "ok": True, "result_head": ""}],
                       run_tool_fn=_explota, ws=str(tmp_path))
    assert inf["n_real"] == 1
    assert inf["pasos"][0]["ok"] is False
    assert "boom" in inf["pasos"][0]["resultado"]


def test_modo_real_restaura_el_cwd(tmp_path):
    import os
    antes = os.getcwd()
    R.reproducir([{"action": "listar", "args": ".", "ok": True, "result_head": ""}],
                 run_tool_fn=lambda t, a, c: "ok", ws=str(tmp_path))
    assert os.getcwd() == antes


def test_ok_de_un_paso_real_lo_decide_la_PRIMERA_linea():
    # Regla heredada de loop.py: un leer_archivo exitoso que devuelve un log con
    # la palabra ERROR dentro NO es un fallo.
    assert R._parece_error("RESULTADO x ERROR: no existe") is True
    assert R._parece_error("contenido ok\nlinea con ERROR adentro") is False


def test_resumen_linea_no_esconde_ausentes():
    inf = R.reproducir(TRAZA_LEGACY)
    assert "AUSENTES=3" in R.resumen_linea(inf)


# --------------------------------------------------------------------------
# 5. Ablacion.
# --------------------------------------------------------------------------

def test_ablacion_saltar():
    t = R.normalizar(TRAZA_LEGACY)
    ab = R.ablacionar(t, 1, "saltar")
    assert len(ab) == 2
    assert [p["tool"] for p in ab.pasos] == ["escribir_archivo", "ejecutar"]
    assert [p["n"] for p in ab.pasos] == [1, 2]      # renumerados
    assert len(t) == 3                                # la original intacta
    assert ab.es_real is False
    assert ab.ablaciones[-1]["modo"] == "saltar"


def test_ablacion_invertir_ok():
    t = R.normalizar(TRAZA_LEGACY)
    ab = R.ablacionar(t, 0, "invertir_ok")
    assert ab.pasos[0]["ok"] is False
    assert t.pasos[0]["ok"] is True
    assert "ABLACION" in ab.pasos[0]["resumen"]
    # y forzado explicito
    ab2 = R.ablacionar(ab, 0, "invertir_ok", ok=True)
    assert ab2.pasos[0]["ok"] is True


def test_ablacion_sustituir():
    t = R.normalizar(TRAZA_LEGACY)
    ab = R.ablacionar(t, 2, "sustituir",
                      paso={"action": "py_validar", "args": "a.py", "ok": True,
                            "result_head": "sintaxis ok"})
    assert ab.pasos[2]["tool"] == "py_validar"
    assert ab.pasos[2]["n"] == 3
    assert ab.pasos[2]["origen_paso"] == "sustituido"
    assert t.pasos[2]["tool"] == "ejecutar"


def test_ablacion_invalida_no_lanza_y_lo_declara():
    t = R.normalizar(TRAZA_LEGACY)
    for i, modo, kw in ((99, "saltar", {}), (-1, "saltar", {}),
                        (0, "inventado", {}), (0, "sustituir", {})):
        ab = R.ablacionar(t, i, modo, **kw)
        assert len(ab) == 3                        # sin cambios
        assert ab.ablaciones[-1]["aplicada"] is False
        assert ab.avisos


def test_ablacion_cambia_la_huella():
    t = R.normalizar(TRAZA_LEGACY)
    assert R.huella(R.ablacionar(t, 1, "saltar")) != R.huella(t)
    assert R.huella(R.ablacionar(t, 1, "invertir_ok")) != R.huella(t)


def test_reproducir_una_ablacion_saltar_sigue_usando_la_cache():
    # Tras un 'saltar' los n se renumeran, asi que el indice ya no cuadra y la
    # cache tiene que caer al respaldo por FIRMA. Se comprueba que cae bien.
    t = R.normalizar(TRAZA_LEGACY)
    c = R.grabar_resultados(t)
    ab = R.ablacionar(t, 0, "saltar")
    inf = R.reproducir(ab, cache=c)
    assert inf["n_cache"] == 2 and inf["n_ausente"] == 0
    assert [p["resultado"] for p in inf["pasos"]] == ["hola", "1\nexit code: 0"]
    assert any(p["motivo"] == "cache por firma" for p in inf["pasos"])


# --------------------------------------------------------------------------
# 6. Divergencia.
# --------------------------------------------------------------------------

def test_divergencia_identicas():
    t = R.normalizar(TRAZA_LEGACY)
    d = R.divergencia(t, R.normalizar(TRAZA_GRABADOR))
    assert d["divergen"] is False and d["paso"] is None


def test_divergencia_por_tool():
    t = R.normalizar(TRAZA_LEGACY)
    ab = R.ablacionar(t, 1, "sustituir",
                      paso={"action": "borrar_archivo", "args": "a.txt", "ok": True,
                            "result_head": "x"})
    d = R.divergencia(t, ab)
    assert d["divergen"] and d["paso"] == 1 and d["campo"] == "tool"
    assert d["a"] == "leer_archivo" and d["b"] == "borrar_archivo"


def test_divergencia_por_ok():
    t = R.normalizar(TRAZA_LEGACY)
    d = R.divergencia(t, R.ablacionar(t, 2, "invertir_ok"))
    assert d["paso"] == 2 and d["campo"] == "ok"


def test_divergencia_por_args():
    otra = [dict(TRAZA_LEGACY[0]), dict(TRAZA_LEGACY[1], args="b.txt"),
            dict(TRAZA_LEGACY[2])]
    d = R.divergencia(TRAZA_LEGACY, otra)
    assert d["paso"] == 1 and d["campo"] == "args" and d["b"] == "b.txt"


def test_divergencia_por_longitud():
    t = R.normalizar(TRAZA_LEGACY)
    d = R.divergencia(t, R.ablacionar(t, 2, "saltar"))
    assert d["divergen"] and d["campo"] == "longitud"
    assert d["paso"] == 2 and d["n_a"] == 3 and d["n_b"] == 2


def test_divergencia_de_informes_ve_el_RESULTADO():
    # Misma trayectoria pedida, resultado distinto: eso es lo que importa para
    # atribuir, y `divergencia` sobre trayectorias no lo puede ver.
    t = R.normalizar(TRAZA_LEGACY)
    otra = [dict(p) for p in TRAZA_LEGACY]
    otra[1] = dict(otra[1], result_head="CONTENIDO DISTINTO")
    a = R.reproducir(t, cache=R.grabar_resultados(t))
    b = R.reproducir(t, cache=R.grabar_resultados(otra))
    assert R.divergencia(t, R.normalizar(otra))["divergen"] is False
    d = R.divergencia_informes(a, b)
    assert d["divergen"] and d["paso"] == 1 and d["campo"] == "resultado"
    assert a["huella"] != b["huella"]


def test_el_tiempo_se_mide_con_perf_counter_no_con_time_time():
    # Regresion REAL cazada al medir: en Windows time.time() tiene resolucion de
    # ~15,6 ms, asi que un replay en cache salia "0.0 ms" y el informe de ahorro
    # daba 5e10x, que es un numero fabricado. Con perf_counter el replay de una
    # traza no vacia mide algo ESTRICTAMENTE positivo.
    t = R.normalizar(TRAZA_LEGACY)
    inf = R.reproducir(t, cache=R.grabar_resultados(t))
    assert inf["ms"] > 0.0
    assert all(p["ms"] >= 0.0 for p in inf["pasos"])
    import inspect
    codigo = "\n".join(l for l in inspect.getsource(R.reproducir).splitlines()
                       if not l.strip().startswith("#"))
    assert "perf_counter" in codigo
    assert "time.time()" not in codigo


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
