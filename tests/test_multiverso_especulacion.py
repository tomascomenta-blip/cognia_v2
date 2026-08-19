# -*- coding: utf-8 -*-
"""Tests de cognia/multiverso/especulacion.py.

Sin modelo y sin red: el ejecutor de tools se INYECTA como callable y el
clasificador de reversibilidad tambien. Los pocos casos que necesitan ficheros
de verdad usan tmp_path (no tocan el repo)."""

import os
import pytest

from cognia.multiverso import especulacion as E


@pytest.fixture(autouse=True)
def _limpio():
    E.reiniciar()
    yield
    E.reiniciar()


def _tool_falsa(salidas):
    """run_tool_fn de mentira: {(tool, args): texto}. Cuenta las llamadas."""
    llamadas = []

    def run(tool, args, ctx):
        llamadas.append((tool, args))
        return salidas.get((tool, args), "RESULTADO %s: (sin canned)" % tool)

    run.llamadas = llamadas
    return run


# ══════════════════════════════════════════════════════════════════════════
# PREDICTOR
# ══════════════════════════════════════════════════════════════════════════

def test_predictor_deterministico_aprende_del_historial():
    # tras 'listar' el agente pidio 'leer_archivo a.py' 3 veces y 'buscar' 1
    hist = []
    for _ in range(3):
        hist += [{"tool": "listar", "args": "src"},
                 {"tool": "leer_archivo", "args": "src/a.py"}]
    hist += [{"tool": "listar", "args": "src"}, {"tool": "buscar", "args": "x | src"}]
    hist += [{"tool": "listar", "args": "src"}]          # el paso actual
    pred = E.predecir({"historial": hist}, k=2)
    assert [p.tool for p in pred] == ["leer_archivo", "buscar"]
    assert pred[0].args == "src/a.py"
    assert pred[0].meta["conteo"] == 3 and pred[0].meta["de"] == 4
    assert pred[0].meta["prob"] == 0.75


def test_predictor_sin_historial_no_inventa():
    assert E.predecir({"historial": []}) == []
    assert E.predecir({"historial": [{"tool": "listar", "args": "."}]}) == []


def test_predictor_respeta_k():
    hist = [{"tool": "listar", "args": "."}, {"tool": "leer_archivo", "args": "a"},
            {"tool": "listar", "args": "."}, {"tool": "buscar", "args": "z | ."},
            {"tool": "listar", "args": "."}, {"tool": "arbol", "args": "."},
            {"tool": "listar", "args": "."}]
    assert len(E.predecir({"historial": hist}, k=2)) == 2
    assert len(E.predecir({"historial": hist}, k=99)) == 3


# ══════════════════════════════════════════════════════════════════════════
# PUREZA: nunca se especula algo con efecto
# ══════════════════════════════════════════════════════════════════════════

def test_predecir_filtra_lo_no_puro_aunque_lo_pida_el_predictor():
    sucias = [{"tool": "ejecutar", "args": "git push origin main"},
              {"tool": "escribir_archivo", "args": "a.txt | hola"},
              {"tool": "ejecutar", "args": "rm -rf build"},
              {"tool": "listar", "args": "src"}]
    pred = E.predecir({}, k=9, predictor_fn=lambda ctx, k: sucias)
    assert [p.tool for p in pred] == ["listar"]


def test_predictor_del_bigrama_tampoco_cuela_lo_no_puro():
    hist = [{"tool": "listar", "args": "."}, {"tool": "git_commit", "args": "wip"},
            {"tool": "listar", "args": "."}]
    assert E.predecir({"historial": hist}) == []


@pytest.mark.parametrize("cmd, puro", [
    ("ls src", True),
    ("dir src", True),
    ("cat a.py", True),
    ("grep -r foo src", True),
    ("rg foo src", True),
    ("find src -maxdepth 1", True),
    ("find src -delete", False),            # find que BORRA
    ("ls src && rm -rf src", False),        # encadenado
    ("cat a.py > b.py", False),             # redireccion
    ("cat a.py | tee b", False),            # tuberia
    ("git push", False),
    ("python -c \"import os; print(os.listdir('src'))\"", True),
    ("python -c \"import shutil; shutil.rmtree('src')\"", False),
])
def test_pureza_de_comandos(cmd, puro):
    a = {"tool": "ejecutar", "args": cmd}
    # se fuerza el fallback local (clasificar_fn que no sabe contestar)
    assert E.es_pura(a, clasificar_fn=lambda *_a, **_k: "") is puro


def test_ejecutar_especulativo_veta_lo_no_puro_en_el_2o_chequeo():
    """Defensa en profundidad: aunque la accion llegue ya 'aprobada', se
    vuelve a clasificar justo antes de correrla, y una no-pura no se corre."""
    run = _tool_falsa({})
    cache = E.ejecutar_especulativo(
        [{"tool": "ejecutar", "args": "git push"},
         {"tool": "escribir_archivo", "args": "x | y"},
         {"tool": "listar", "args": "src"}],
        run, {}, clasificar_fn=lambda *_a, **_k: "", esperar=True)
    assert run.llamadas == [("listar", "src")]
    assert len(cache["vetadas"]) == 2
    assert E.estadisticas()["especuladas"] == 1


def test_clasificar_fn_inyectado_manda_sobre_el_fallback():
    """Si el modulo de reversibilidad dice que algo NO es puro, no se corre,
    aunque la lista blanca local lo aceptaria."""
    run = _tool_falsa({})
    E.ejecutar_especulativo([{"tool": "listar", "args": "src"}], run, {},
                            clasificar_fn=lambda *_a, **_k: {"cubo": "externo"},
                            esperar=True)
    assert run.llamadas == []


# ══════════════════════════════════════════════════════════════════════════
# LAS TRES FAMILIAS DE EQUIVALENCIA
# ══════════════════════════════════════════════════════════════════════════

LISTADO = "RESULTADO listar src: ['D sub', 'F a.py', 'F b.py']"
LECTURA = "RESULTADO leer_archivo src/a.py: uno\ndos\n"
BUSQUEDA = "RESULTADO buscar 'foo': src/a.py:2:foo aqui | src/b.py:9:foo alla"


def _cache(accion, salida):
    run = _tool_falsa({(accion["tool"], accion["args"]): salida})
    return E.ejecutar_especulativo([accion], run, {}, esperar=True)


@pytest.mark.parametrize("real", [
    ("ejecutar", "ls src"),
    ("ejecutar", "dir src"),
    ("ejecutar", "find src -maxdepth 1"),
    ("ejecutar", "python -c \"import os; print(os.listdir('src'))\""),
])
def test_familia_listar_acepta_por_equivalencia(real):
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(real, cache)
    assert r["aceptada"] and r["via"] == "equivalencia"
    assert r["resultado"] == LISTADO
    assert r["evidencia"]["familia"] == "LISTAR"


@pytest.mark.parametrize("real", [("ejecutar", "cat src/a.py"),
                                  ("ejecutar", "type src/a.py")])
def test_familia_leer_acepta_por_equivalencia(real):
    cache = _cache({"tool": "leer_archivo", "args": "src/a.py"}, LECTURA)
    r = E.aceptar(real, cache)
    assert r["aceptada"] and r["via"] == "equivalencia"
    assert r["resultado"] == LECTURA


def test_familia_buscar_acepta_por_equivalencia():
    cache = _cache({"tool": "buscar", "args": "foo | src"}, BUSQUEDA)
    r = E.aceptar(("ejecutar", "rg foo src"), cache)
    assert r["aceptada"] and r["via"] == "equivalencia"
    assert r["evidencia"]["familia"] == "BUSCAR"


def test_la_equivalencia_es_simetrica():
    """Especular el comando y que el modelo pida la tool tambien vale."""
    cache = _cache({"tool": "ejecutar", "args": "cat src/a.py"},
                   "RESULTADO ejecutar: uno\ndos")
    r = E.aceptar(("leer_archivo", "src/a.py"), cache)
    assert r["aceptada"] and r["via"] == "equivalencia"


def test_igualdad_exacta_gana_y_se_marca_como_tal():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(("listar", "  src "), cache)      # espacios: misma firma
    assert r["aceptada"] and r["via"] == "igualdad"
    assert r["evidencia"]["regla"] == "igualdad-de-firma"


def test_politica_estricta_rechaza_la_equivalencia():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(("ejecutar", "ls src"), cache, politica="estricta")
    assert not r["aceptada"] and r["via"] is None
    assert "estricta" in r["evidencia"]["motivo"]


def test_politica_desconocida_es_un_error_ruidoso():
    with pytest.raises(ValueError):
        E.aceptar(("listar", "src"), {}, politica="mano_ancha")


# ══════════════════════════════════════════════════════════════════════════
# RECHAZOS: la equivalencia FALSA
# ══════════════════════════════════════════════════════════════════════════

def test_ls_de_OTRO_directorio_se_rechaza():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(("ejecutar", "ls otro_dir"), cache)
    assert not r["aceptada"] and r["via"] is None
    assert "ninguna especulacion tiene el efecto" in r["evidencia"]["motivo"]
    assert r["resultado"] is None


def test_cat_de_otro_fichero_se_rechaza():
    cache = _cache({"tool": "leer_archivo", "args": "src/a.py"}, LECTURA)
    assert not E.aceptar(("ejecutar", "cat src/b.py"), cache)["aceptada"]


def test_buscar_otro_patron_se_rechaza():
    cache = _cache({"tool": "buscar", "args": "foo | src"}, BUSQUEDA)
    assert not E.aceptar(("ejecutar", "rg bar src"), cache)["aceptada"]


@pytest.mark.parametrize("cmd", ["ls -a src", "ls -la src", "ls -R src",
                                 "dir /s src", "grep -ri foo src",
                                 "rg -i foo src"])
def test_flags_que_cambian_el_conjunto_no_son_equivalentes(cmd):
    """`ls -a` ve los ocultos, `-R` recorre, `-i` ignora mayusculas: otro
    efecto observable, aunque el comando 'parezca' el mismo."""
    assert E.efecto_observable(("ejecutar", cmd))["efecto"] is None


def test_lectura_parcial_no_es_una_lectura():
    assert E.efecto_observable(("leer_archivo", "a.py offset=20"))["efecto"] is None


def test_dotfile_veta_la_equivalencia_con_ls():
    """`ls` sin -a NO muestra dotfiles y `listar` si: la condicion se evalua
    sobre el listado ya cacheado, sin ejecutar nada."""
    con_oculto = "RESULTADO listar src: ['F .env', 'F a.py']"
    cache = _cache({"tool": "listar", "args": "src"}, con_oculto)
    r = E.aceptar(("ejecutar", "ls src"), cache)
    assert not r["aceptada"]
    assert ".env" in r["evidencia"]["motivo"]
    # y con el mismo listado SIN ocultos, si se acepta
    assert E.aceptar(("ejecutar", "ls src"),
                     _cache({"tool": "listar", "args": "src"}, LISTADO))["aceptada"]


def test_grep_es_riesgo_declarado_y_solo_pasa_en_permisiva():
    """grep -r no respeta .gitignore y rg si: no hay chequeo barato."""
    cache = _cache({"tool": "buscar", "args": "foo | src"}, BUSQUEDA)
    assert not E.aceptar(("ejecutar", "grep -r foo src"), cache)["aceptada"]
    r = E.aceptar(("ejecutar", "grep -r foo src"), cache, politica="permisiva")
    assert r["aceptada"] and r["evidencia"]["riesgo"] == "declarado"


def test_lectura_truncada_veta_la_equivalencia_con_cat():
    truncada = ("RESULTADO leer_archivo a.py: uno\ndos\n"
                "(el archivo sigue; continua con offset=2001)")
    cache = _cache({"tool": "leer_archivo", "args": "a.py"}, truncada)
    r = E.aceptar(("ejecutar", "cat a.py"), cache)
    assert not r["aceptada"] and "truncada" in r["evidencia"]["motivo"]


def test_busqueda_en_el_tope_veta_la_equivalencia():
    hits = " | ".join("f%d.py:1:foo" % i for i in range(15))
    cache = _cache({"tool": "buscar", "args": "foo | src"},
                   "RESULTADO buscar 'foo': " + hits)
    r = E.aceptar(("ejecutar", "rg foo src"), cache)
    assert not r["aceptada"] and "tope" in r["evidencia"]["motivo"]


# ══════════════════════════════════════════════════════════════════════════
# CHEQUEO EN CALIENTE (modo auditoria)
# ══════════════════════════════════════════════════════════════════════════

def test_verificar_fn_veta_cuando_el_contenido_difiere():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(("ejecutar", "ls src"), cache,
                  verificar_fn=lambda t, a: "a.py\nb.py\nsub\nSORPRESA.py")
    assert not r["aceptada"]
    assert r["evidencia"]["contenido_igual"] is False
    assert r["evidencia"]["diferencia"]["solo_real"] == ["SORPRESA.py"]


def test_verificar_fn_confirma_cuando_el_contenido_coincide():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    r = E.aceptar(("ejecutar", "ls src"), cache,
                  verificar_fn=lambda t, a: "a.py\nb.py\nsub")
    assert r["aceptada"] and r["evidencia"]["contenido_igual"] is True


# ══════════════════════════════════════════════════════════════════════════
# NORMALIZADORES DE CONTENIDO
# ══════════════════════════════════════════════════════════════════════════

def test_normaliza_la_tabla_de_cmd_exe_dir():
    salida = ("RESULTADO ejecutar: El volumen de la unidad C no tiene etiqueta.\r\n"
              " Directorio de C:\\tmp\\src\r\n\r\n"
              "19/08/2026  12:36a. m.    <DIR>          .\r\n"
              "19/08/2026  12:36a. m.    <DIR>          ..\r\n"
              "19/08/2026  12:36a. m.                40 a.py\r\n"
              "19/08/2026  12:36a. m.                40 b.py\r\n"
              "19/08/2026  12:36a. m.    <DIR>          sub\r\n"
              "               2 archivos            80 bytes\r\n"
              "               3 dirs  492.164.124.672 bytes libres")
    assert E.normalizar_contenido("LISTAR", salida) == frozenset({"a.py", "b.py", "sub"})


def test_normaliza_ls_sin_comerse_la_primera_entrada():
    """La cabecera 'RESULTADO ejecutar: ' va PEGADA al primer nombre."""
    assert E.normalizar_contenido(
        "LISTAR", "RESULTADO ejecutar: a.py\nb.py\nsub") == frozenset({"a.py", "b.py", "sub"})


def test_normaliza_find_descontando_el_directorio_base():
    salida = "RESULTADO ejecutar: src\nsrc/a.py\nsrc/b.py\nsrc/sub"
    assert E.normalizar_contenido("LISTAR", salida, ("LISTAR", "/x/src")) == \
        frozenset({"a.py", "b.py", "sub"})


def test_normaliza_la_lectura_pese_a_los_dos_puntos_de_la_ruta():
    """La ruta absoluta lleva ':' (C:\\...): cortar por el primer ':' metia
    media ruta dentro del contenido."""
    a = E.normalizar_contenido("LEER", "RESULTADO leer_archivo C:\\tmp\\a.py: uno\ndos\n")
    b = E.normalizar_contenido("LEER", "RESULTADO ejecutar: uno\r\ndos\r\n")
    assert a == b == "uno\ndos"


def test_hits_sin_numero_de_linea_no_se_leen_como_cero_hits():
    """`rg pat dir` (sin -n) no trae numero de linea. El parser ingenuo
    devolvia el conjunto VACIO, indistinguible de 'no hay coincidencias'."""
    sin_n = "RESULTADO ejecutar: C:\\tmp\\src\\a.py:foo aqui\nC:\\tmp\\src\\b.py:foo alla"
    hits = E.normalizar_contenido("BUSCAR", sin_n)
    assert hits is not None and len(hits) == 2
    assert all(h[1] is None for h in hits)


def test_contenido_no_interpretable_nunca_es_igual():
    assert E.contenidos_iguales("BUSCAR", None, frozenset()) is False
    assert E.contenidos_iguales("BUSCAR", frozenset(), None) is False


def test_buscar_compara_sin_numero_de_linea_cuando_un_lado_no_lo_trae():
    con_n = E.normalizar_contenido("BUSCAR", "RESULTADO buscar 'foo': a.py:2:foo")
    sin_n = E.normalizar_contenido("BUSCAR", "RESULTADO ejecutar: a.py:foo")
    assert con_n != sin_n
    assert E.contenidos_iguales("BUSCAR", con_n, sin_n) is True


# ══════════════════════════════════════════════════════════════════════════
# ESTADISTICAS
# ══════════════════════════════════════════════════════════════════════════

def test_las_estadisticas_cuadran():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    E.aceptar(("listar", "src"), cache)                 # igualdad
    E.aceptar(("ejecutar", "ls src"), cache)            # equivalencia
    E.aceptar(("ejecutar", "ls otro"), cache)           # rechazo
    E.aceptar(("git_log", ""), cache)                   # rechazo (fuera de tabla)
    st = E.estadisticas()
    assert st["especuladas"] == 1
    assert st["aceptadas_igualdad"] == 1
    assert st["aceptadas_equivalencia"] == 1
    assert st["rechazadas"] == 2
    assert st["aceptadas"] == 2
    assert st["intentos"] == st["aceptadas"] + st["rechazadas"] == 4
    assert st["tasa_aceptacion"] == 0.5
    assert st["tasa_solo_igualdad"] == 0.25
    assert st["ganancia_equivalencia"] == 0.25
    assert st["por_familia"]["LISTAR"] == 2
    assert st["ms_ahorrados"] >= 0.0
    assert st["ms_especulados"] >= st["ms_ahorrados"] - 1e-6 or st["ms_desperdiciados"] == 0.0


def test_reiniciar_deja_el_contador_a_cero():
    cache = _cache({"tool": "listar", "args": "src"}, LISTADO)
    E.aceptar(("listar", "src"), cache)
    assert E.estadisticas()["aceptadas"] == 1
    E.reiniciar()
    st = E.estadisticas()
    assert st["aceptadas"] == 0 and st["intentos"] == 0
    assert st["tasa_aceptacion"] == 0.0


def test_ms_ahorrados_solo_cuenta_lo_que_se_reutiliza():
    run = _tool_falsa({})
    cache = E.ejecutar_especulativo(
        [{"tool": "listar", "args": "a"}, {"tool": "listar", "args": "b"}],
        run, {}, esperar=True)
    E.aceptar(("listar", "a"), cache)
    st = E.estadisticas()
    assert st["especuladas"] == 2
    assert 0.0 < st["ms_ahorrados"] <= st["ms_especulados"]
    assert st["ms_desperdiciados"] > 0.0


# ══════════════════════════════════════════════════════════════════════════
# EJECUCION EN HILO + TABLA AUDITABLE
# ══════════════════════════════════════════════════════════════════════════

def test_la_especulacion_corre_en_otro_hilo_y_se_puede_esperar():
    import threading
    hilos = []

    def run(tool, args, ctx):
        hilos.append(threading.current_thread().name)
        return LISTADO

    cache = E.ejecutar_especulativo([{"tool": "listar", "args": "src"}], run, {})
    cache["esperar"](5)
    assert hilos and hilos[0] != threading.current_thread().name
    assert len(cache["entradas"]) == 1


def test_esperar_ms_en_aceptar_no_revienta_con_un_cache_plano():
    """aceptar() tolera un cache 'plano' {firma: entrada} (util en tests)."""
    plano = {"listar|src": {"accion": E.Accion("listar", "src"),
                            "resultado": LISTADO, "ms": 1.0,
                            "efecto": ("LISTAR", E._abs("src")),
                            "familia": "LISTAR", "regla": "listar.tool"}}
    r = E.aceptar(("listar", "src"), plano)
    assert r["aceptada"] and r["via"] == "igualdad"


def test_la_tabla_de_equivalencias_esta_bien_formada():
    """Es documentacion ejecutable: cada regla declara familia, riesgo y POR
    QUE, y toda regla 'condicionada' trae su chequeo."""
    ids = set()
    for r in E.TABLA_EQUIVALENCIAS:
        assert r["id"] not in ids
        ids.add(r["id"])
        assert r["familia"] in {"LISTAR", "LEER", "BUSCAR"}
        assert r["riesgo"] in {"seguro", "condicionado", "declarado"}
        assert len(r["porque"]) > 20
        if r["riesgo"] == "condicionado":
            assert callable(r["condicion"])
        else:
            assert "condicion" not in r


def test_integra_con_el_clasificador_real_de_reversibilidad():
    """Sin inyectar nada: el modulo hermano manda. Si aun no existe, se salta
    (el paquete lo escriben varias manos y el fallback local ya esta probado)."""
    R = pytest.importorskip("cognia.multiverso.reversibilidad")
    assert hasattr(R, "clasificar")
    assert E.cubo_de(("listar", "src")) == "puro"
    assert E.cubo_de(("ejecutar", "git push origin main")) != "puro"
    run = _tool_falsa({})
    E.ejecutar_especulativo([{"tool": "ejecutar", "args": "git push origin main"}],
                            run, {}, esperar=True)
    assert run.llamadas == []


def test_accion_acepta_las_formas_en_que_llega_del_bucle():
    for x in (E.Accion("listar", "src"), {"tool": "listar", "args": "src"},
              ("listar", "src"), ["listar", "src"], "listar src"):
        assert E.firma(x) == "listar|src"


# ══════════════════════════════════════════════════════════════════════════
# UN CASO DE PUNTA A PUNTA CON FICHEROS DE VERDAD (sin subprocess)
# ══════════════════════════════════════════════════════════════════════════

def test_extremo_a_extremo_sobre_ficheros_reales(tmp_path):
    d = tmp_path / "proy"
    d.mkdir()
    (d / "a.py").write_text("uno\ndos\n", encoding="utf-8")
    (d / "b.py").write_text("tres\n", encoding="utf-8")

    def run(tool, args, ctx):
        if tool == "listar":
            e = sorted(os.listdir(args))
            return "RESULTADO listar %s: %s" % (args, [("F " + n) for n in e])
        if tool == "leer_archivo":
            with open(args, encoding="utf-8") as f:
                return "RESULTADO leer_archivo %s: %s" % (args, f.read())
        raise AssertionError("no deberia correr %s" % tool)

    hist = [{"tool": "listar", "args": str(d)},
            {"tool": "leer_archivo", "args": str(d / "a.py")},
            {"tool": "listar", "args": str(d)}]
    pred = E.predecir({"historial": hist}, k=3)
    assert [p.tool for p in pred] == ["leer_archivo"]

    cache = E.ejecutar_especulativo(pred, run, {"cwd": str(d)}, esperar=True)
    # el modelo, al final, pide el equivalente por comando: se sirve del cache
    r = E.aceptar(("ejecutar", 'cat "%s"' % (d / "a.py")), cache)
    assert r["aceptada"] and r["via"] == "equivalencia"
    assert "uno\ndos" in r["resultado"]
    # y el contenido resiste el chequeo en caliente contra el fichero real
    r2 = E.aceptar(("ejecutar", 'cat "%s"' % (d / "a.py")), cache,
                   verificar_fn=lambda t, a: (d / "a.py").read_text(encoding="utf-8"))
    assert r2["aceptada"] and r2["evidencia"]["contenido_igual"] is True
