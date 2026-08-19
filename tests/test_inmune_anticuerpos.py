# -*- coding: utf-8 -*-
"""
tests/test_inmune_anticuerpos.py
================================
Regresion del SISTEMA INMUNE del arnes (cognia/inmune/anticuerpos.py, 2026-08-19).

Falla sin el modulo (ImportError en la coleccion) y pasa con el. Todo contra el
modulo REAL: sin mocks, sin LLM y sin red. El almacen se redirige a un tmp_path
por COGNIA_INMUNE_DIR, que es el override que el modulo lee a call-time.

Lo que se protege, en orden de importancia:
 1. LA COMPUERTA: nada se activa por haber sido sintetizado (cuarentena), y un
    SOLO falso positivo sobre los casos sanos impide la activacion.
 2. `sintetizar` devuelve None cuando el fallo no cabe en un chequeo
    determinista: NO se fabrica un anticuerpo de prosa.
 3. El veto devuelve al MODELO un texto con el remedio.
 4. El retiro automatico tras N falsos positivos en produccion.
 5. La persistencia sobrevive a "otra instancia" (recargar desde disco).
 6. `evaluar` no lanza NUNCA y es barato.
"""
from __future__ import annotations

import json
import time

import pytest

from cognia.inmune import anticuerpos as ac


# ── Andamiaje ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def almacen_aislado(tmp_path, monkeypatch):
    """Cada test tiene su propio almacen y ve el disco sin esperar al TTL."""
    monkeypatch.setenv("COGNIA_INMUNE_DIR", str(tmp_path / "inmune"))
    monkeypatch.setenv("COGNIA_INMUNE_TTL", "0")
    monkeypatch.delenv("COGNIA_INMUNE_MAX_FP", raising=False)
    ac.recargar()
    yield
    ac.recargar()


def _informe_push():
    """Informe causal de un `git push --force` que borro trabajo (paso 2)."""
    trayectoria = {
        "id": "tray-0042",
        "pasos": [
            {"tool": "git_estado", "args": "", "ok": True},
            {"tool": "leer_archivo", "args": "README.md", "ok": True},
            {"tool": "ejecutar", "args": "git push --force origin main",
             "ok": False, "error": "remote rejected / se perdieron 3 commits"},
        ],
    }
    informe = {
        "trayectoria": "tray-0042",
        "paso_culpable": 2,
        "confianza": 0.9,
        "modo_fallo": "el push forzado borro commits del remoto",
    }
    return informe, trayectoria


def _activar(ab, positivos, negativos):
    ac.registrar(ab)
    return ac.examinar(ab, positivos, negativos)


# ── 1. Sintesis desde un informe causal ───────────────────────────────────────

def test_sintetiza_comando_prohibido_desde_informe_causal():
    informe, tray = _informe_push()
    ab = ac.sintetizar(informe, tray)
    assert ab is not None
    assert ab["chequeo"]["tipo"] == "comando_prohibido"
    assert ab["chequeo"]["comando"] == "git push --force"
    assert ab["disparador"]["tool"] == "ejecutar"
    assert ab["origen"]["trayectoria"] == "tray-0042"
    assert ab["origen"]["paso"] == 2
    assert ab["estado"] == "cuarentena"          # NADA nace activo
    assert ab["aciertos"] == 0 and ab["falsos_positivos"] == 0
    assert ab["remedio"].strip()                  # hay algo que decirle al modelo


def test_sintetiza_leido_antes_para_una_edicion_a_ciegas():
    tray = [
        {"tool": "listar", "args": ".", "ok": True},
        {"tool": "editar_archivo", "args": "src/app.py | <<<<<<< SEARCH\nfoo\n=======",
         "ok": False, "error": "no se encontro el bloque SEARCH en el fichero"},
    ]
    ab = ac.sintetizar({"trayectoria": "t7", "paso_culpable": 1}, tray)
    assert ab is not None
    assert ab["chequeo"] == {"tipo": "precondicion_fichero", "exige": "leido_antes"}
    assert "leer_archivo" in ab["remedio"]


def test_sintetiza_precondicion_existe_cuando_el_error_dice_que_no_estaba():
    tray = [{"tool": "leer_archivo", "args": "docs/ausente.md",
             "ok": False, "error": "FileNotFoundError: no such file or directory"}]
    ab = ac.sintetizar({"trayectoria": "t8", "paso_culpable": 0}, tray)
    assert ab["chequeo"] == {"tipo": "precondicion_fichero", "exige": "existe"}


def test_sintetiza_orden_de_pasos_cuando_el_informe_lo_declara():
    tray = [{"tool": "git_commit", "args": "arreglo", "ok": False,
             "error": "nothing staged"}]
    ab = ac.sintetizar(
        {"trayectoria": "t9", "paso_culpable": 0,
         "orden": {"tras": "editar_archivo", "requiere": "git_add"}}, tray)
    assert ab["chequeo"] == {"tipo": "orden_de_pasos",
                             "tras": "editar_archivo", "requiere": "git_add"}


def test_sintetiza_patron_args_solo_si_el_error_CITA_el_token():
    # El error cita literalmente '--formato=xml': hay evidencia para el patron.
    tray = [{"tool": "ejecutar", "args": "reporte --formato=xml salida.txt",
             "ok": False, "error": "opcion desconocida: --formato=xml"}]
    ab = ac.sintetizar({"trayectoria": "t10", "paso_culpable": 0}, tray)
    assert ab["chequeo"]["tipo"] == "patron_args"
    assert ac.aplica(ab, "ejecutar", "reporte --formato=xml otra.txt")
    assert not ac.aplica(ab, "ejecutar", "reporte --formato=json otra.txt")


# ── 2. Lo que NO se puede volver chequeo devuelve None ────────────────────────

def test_fallo_de_razonamiento_no_produce_anticuerpo():
    tray = [{"tool": "resumir", "args": "el informe trimestral", "ok": True}]
    informe = {"trayectoria": "t11", "paso_culpable": 0,
               "modo_fallo": "el modelo saco una conclusion que la evidencia no sostiene"}
    assert ac.sintetizar(informe, tray) is None


def test_informe_sin_tool_devuelve_none():
    assert ac.sintetizar({"trayectoria": "t12", "modo_fallo": "algo salio mal"}, []) is None


def test_confianza_baja_devuelve_none():
    informe, tray = _informe_push()
    informe["confianza"] = 0.3
    assert ac.sintetizar(informe, tray) is None


def test_chequeo_explicito_invalido_no_se_acepta_tal_cual():
    """Un 'tipo' inventado por el informe causal no se cuela: o cae en una regla
    de inferencia o no hay anticuerpo."""
    tray = [{"tool": "resumir", "args": "x", "ok": False}]
    informe = {"trayectoria": "t13", "paso_culpable": 0,
               "chequeo": {"tipo": "adivinacion_magica", "que": "todo"}}
    assert ac.sintetizar(informe, tray) is None


def test_entradas_basura_no_lanzan():
    for malo in (None, "texto", 42, [], {"paso_culpable": {"tool": ""}}):
        assert ac.sintetizar(malo, None) is None


# ── 3. LA COMPUERTA ───────────────────────────────────────────────────────────

def test_cuarentena_impide_vetar_hasta_pasar_el_examen():
    informe, tray = _informe_push()
    ab = ac.registrar(ac.sintetizar(informe, tray))
    assert ab["estado"] == "cuarentena"
    assert ac.activos() == []
    # En cuarentena NO veta, aunque la llamada reproduzca el fallo exacto.
    assert ac.evaluar("ejecutar", "git push --force origin main", {}) is None

    res = ac.examinar(
        ab,
        casos_positivos=[("ejecutar", "git push --force origin main", {}),
                         ("ejecutar", "git push origin main --force", {})],
        casos_negativos=[("ejecutar", "git push origin main", {}),
                         ("ejecutar", "git status", {}),
                         ("ejecutar", "pytest -q", {})],
    )
    assert res["activado"] is True
    assert res["positivos_vetados"] == 2 and res["falsos_positivos"] == []
    assert ac.evaluar("ejecutar", "git push --force origin main", {})["veto"] is True


def test_un_solo_falso_positivo_en_los_sanos_impide_la_activacion():
    """El anticuerpo demasiado ancho veta los 2 positivos... y tambien un sano."""
    ab = ac.registrar({
        "id": "ab-ancho",
        "nombre": "demasiado ancho",
        "origen": {"trayectoria": "t14", "paso": 3},
        "disparador": {"tool": "ejecutar", "patron_args": None, "contexto": {}},
        "chequeo": {"tipo": "patron_args", "patron": "git"},
        "remedio": "no uses git asi",
    })
    res = ac.examinar(
        ab,
        casos_positivos=[("ejecutar", "git push --force", {}),
                         ("ejecutar", "git reset --hard", {})],
        casos_negativos=[("ejecutar", "git status", {}),      # <- sano, vetado
                         ("ejecutar", "pytest -q", {})],
    )
    assert res["activado"] is False
    assert res["positivos_vetados"] == 2          # capturaba el fallo, si
    assert len(res["falsos_positivos"]) == 1      # pero se lleva un sano por delante
    assert "falso" in res["motivo"]
    assert ac.obtener("ab-ancho")["estado"] == "cuarentena"
    assert ac.evaluar("ejecutar", "git push --force", {}) is None


def test_un_positivo_que_escapa_impide_la_activacion():
    ab = ac.registrar({
        "id": "ab-flojo",
        "disparador": {"tool": "ejecutar"},
        "chequeo": {"tipo": "comando_prohibido", "comando": "git push --force"},
        "remedio": "usa --force-with-lease",
    })
    res = ac.examinar(ab,
                      casos_positivos=[("ejecutar", "git push --force", {}),
                                       ("ejecutar", "git reset --hard HEAD~1", {})],
                      casos_negativos=[("ejecutar", "git status", {})])
    assert res["activado"] is False
    assert res["positivos_vetados"] == 1
    assert "NO vetados" in res["motivo"]


def test_sin_casos_positivos_no_se_activa():
    ab = ac.registrar({
        "id": "ab-supersticion",
        "disparador": {"tool": "ejecutar"},
        "chequeo": {"tipo": "comando_prohibido", "comando": "rm -rf"},
    })
    res = ac.examinar(ab, casos_positivos=[], casos_negativos=[("ejecutar", "ls", {})])
    assert res["activado"] is False
    assert "sin casos positivos" in res["motivo"]


# ── 4. El veto que lee el modelo ──────────────────────────────────────────────

def test_el_veto_devuelve_al_modelo_el_remedio_y_el_origen():
    informe, tray = _informe_push()
    informe["remedio"] = "Usa 'git push --force-with-lease' o pide confirmacion."
    ab = ac.registrar(ac.sintetizar(informe, tray))
    ac.examinar(ab, [("ejecutar", "git push --force origin main", {})],
                [("ejecutar", "git push origin main", {})])

    veto = ac.evaluar("ejecutar", "git push --force origin main", {})
    assert veto is not None and veto["veto"] is True
    msg = veto["mensaje"]
    assert "VETADO" in msg
    assert "force-with-lease" in msg               # el remedio llega literal
    assert "tray-0042" in msg and "paso 2" in msg  # de donde viene el fallo
    assert "NO reintentes" in msg                  # orden explicita, no un log
    assert veto["id"] == ab["id"]


def test_dejar_pasar_devuelve_none_exactamente():
    informe, tray = _informe_push()
    ab = ac.registrar(ac.sintetizar(informe, tray))
    ac.examinar(ab, [("ejecutar", "git push --force", {})], [("ejecutar", "ls", {})])
    assert ac.evaluar("ejecutar", "git status", {}) is None
    assert ac.evaluar("leer_archivo", "README.md", {}) is None   # otra tool: ni mira


# ── 5. Los cuatro chequeos, cada uno contra el disco/ctx de verdad ────────────

def test_precondicion_existe_contra_ficheros_reales(tmp_path):
    hay = tmp_path / "esta.txt"
    hay.write_text("x", encoding="utf-8")
    no_hay = tmp_path / "no_esta.txt"
    ab = {"disparador": {"tool": "leer_archivo"},
          "chequeo": {"tipo": "precondicion_fichero", "exige": "existe"}}
    assert ac.aplica(ab, "leer_archivo", str(no_hay)) is True
    assert ac.aplica(ab, "leer_archivo", str(hay)) is False


def test_precondicion_no_existe_protege_de_sobrescribir(tmp_path):
    hay = tmp_path / "importante.py"
    hay.write_text("codigo", encoding="utf-8")
    ab = {"disparador": {"tool": "escribir_archivo"},
          "chequeo": {"tipo": "precondicion_fichero", "exige": "no_existe"}}
    assert ac.aplica(ab, "escribir_archivo", f"{hay} | contenido nuevo") is True
    assert ac.aplica(ab, "escribir_archivo", f"{tmp_path / 'otro.py'} | x") is False


def test_leido_antes_usa_el_ctx_y_falla_abierto_si_no_lo_traen():
    ab = {"disparador": {"tool": "editar_archivo"},
          "chequeo": {"tipo": "precondicion_fichero", "exige": "leido_antes"}}
    args = "src/app.py | <<<<<<< SEARCH"
    assert ac.aplica(ab, "editar_archivo", args, {"leidos": []}) is True
    assert ac.aplica(ab, "editar_archivo", args, {"leidos": ["src/app.py"]}) is False
    # Rutas equivalentes en NTFS (caja y separador) cuentan como la misma.
    assert ac.aplica(ab, "editar_archivo", args, {"leidos": ["SRC\\APP.PY"]}) is False
    # El ctx no trae la clave: no se puede decidir -> no veta (limite declarado).
    assert ac.aplica(ab, "editar_archivo", args, {}) is False


def test_orden_de_pasos_mira_la_ultima_aparicion():
    ab = {"disparador": {"tool": "git_commit"},
          "chequeo": {"tipo": "orden_de_pasos", "tras": "editar_archivo",
                      "requiere": "git_add"}}
    assert ac.aplica(ab, "git_commit", "msg",
                     {"historial": ["git_add", "editar_archivo"]}) is True
    assert ac.aplica(ab, "git_commit", "msg",
                     {"historial": ["editar_archivo", "git_add"]}) is False
    assert ac.aplica(ab, "git_commit", "msg", {"historial": ["listar"]}) is False


def test_comando_prohibido_caza_los_flags_reordenados():
    ab = {"disparador": {"tool": "ejecutar"},
          "chequeo": {"tipo": "comando_prohibido", "comando": "git push --force"}}
    assert ac.aplica(ab, "ejecutar", "git push --force origin main") is True
    assert ac.aplica(ab, "ejecutar", "GIT PUSH origin main --force") is True
    assert ac.aplica(ab, "ejecutar", "git push origin main") is False


# ── 6. Retiro automatico en produccion ────────────────────────────────────────

def test_retiro_automatico_tras_n_falsos_positivos():
    informe, tray = _informe_push()
    ab = ac.registrar(ac.sintetizar(informe, tray))
    ac.examinar(ab, [("ejecutar", "git push --force", {})], [("ejecutar", "ls", {})])
    ident = ab["id"]
    assert ac.evaluar("ejecutar", "git push --force", {}) is not None

    for i in range(1, ac.MAX_FALSOS_POSITIVOS):
        est = ac.registrar_resultado(ident, fue_util=False)
        assert est["estado"] == "activo", f"retirado demasiado pronto en el FP {i}"
    est = ac.registrar_resultado(ident, fue_util=False)
    assert est["estado"] == "retirado"
    assert "automatico" in est["motivo_retiro"]
    assert ac.evaluar("ejecutar", "git push --force", {}) is None
    assert ac.activos() == []


def test_registrar_resultado_util_no_retira_y_suma_aciertos():
    ab = ac.registrar({"id": "ab-util", "disparador": {"tool": "ejecutar"},
                       "chequeo": {"tipo": "comando_prohibido", "comando": "rm -rf"}})
    ac.examinar(ab, [("ejecutar", "rm -rf /", {})], [("ejecutar", "ls", {})])
    for _ in range(10):
        ac.registrar_resultado("ab-util", fue_util=True)
    est = ac.obtener("ab-util")
    assert est["estado"] == "activo" and est["aciertos"] >= 10


def test_retirar_a_mano_deja_el_motivo_y_no_borra():
    ab = ac.registrar({"id": "ab-mano", "disparador": {"tool": "ejecutar"},
                       "chequeo": {"tipo": "comando_prohibido", "comando": "rm -rf"}})
    ac.examinar(ab, [("ejecutar", "rm -rf x", {})], [("ejecutar", "ls", {})])
    ac.retirar("ab-mano", motivo="ya no aplica: cambio la herramienta")
    est = ac.obtener("ab-mano")
    assert est["estado"] == "retirado"
    assert "cambio la herramienta" in est["motivo_retiro"]
    assert len(ac.listar()) == 1          # se marca, no se borra
    assert ac.evaluar("ejecutar", "rm -rf x", {}) is None


def test_registrar_deduplica_y_no_resucita_un_retirado():
    informe, tray = _informe_push()
    a1 = ac.registrar(ac.sintetizar(informe, tray))
    ac.retirar(a1["id"], motivo="falsos positivos")
    a2 = ac.registrar(ac.sintetizar(informe, tray))   # el MISMO fallo, otra vez
    assert a2["id"] == a1["id"]
    assert a2["estado"] == "retirado"                 # no vuelve a cuarentena
    assert len(ac.listar()) == 1


# ── 7. Persistencia entre instancias ──────────────────────────────────────────

def test_persistencia_entre_instancias():
    informe, tray = _informe_push()
    ab = ac.registrar(ac.sintetizar(informe, tray))
    ac.examinar(ab, [("ejecutar", "git push --force", {})],
                [("ejecutar", "git status", {})])
    ident = ab["id"]

    # El JSON esta en disco, en el sitio que dice el contrato.
    ruta = ac.ruta_almacen()
    assert ruta.is_file()
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    assert [a["id"] for a in crudo] == [ident]
    assert crudo[0]["estado"] == "activo"

    # "Otra instancia": se tira toda la cache y se relee desde cero.
    ac.recargar()
    assert [a["id"] for a in ac.activos()] == [ident]
    assert ac.evaluar("ejecutar", "git push --force origin main", {})["id"] == ident


def test_almacen_corrupto_degrada_a_vacio_sin_lanzar():
    ruta = ac.ruta_almacen()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("{esto no es json", encoding="utf-8")
    ac.recargar()
    assert ac.listar() == []
    assert ac.evaluar("ejecutar", "git push --force", {}) is None


# ── 8. El camino caliente: no lanza y es barato ───────────────────────────────

@pytest.mark.parametrize("tool,args,ctx", [
    ("ejecutar", None, None),
    (None, None, None),
    ("ejecutar", "", "no soy un dict"),
    ("ejecutar", "x" * 5000, {"historial": None, "leidos": 7}),
])
def test_evaluar_nunca_lanza(tool, args, ctx):
    informe, tray = _informe_push()
    ab = ac.registrar(ac.sintetizar(informe, tray))
    ac.examinar(ab, [("ejecutar", "git push --force", {})], [("ejecutar", "ls", {})])
    assert ac.evaluar(tool, args, ctx) is None


def test_coste_de_evaluar_con_50_activos():
    """El presupuesto declarado en la cabecera del modulo: ~1 ms por llamada.

    No es un micro-benchmark de precision (esto corre en una suite compartida):
    es el guardarrail que avisa si alguien mete algo caro en el camino caliente.
    El numero fino esta en scripts/medir_inmune.py.
    """
    datos = []
    for i in range(50):
        datos.append({
            "id": f"ab-perf-{i}",
            "nombre": f"perf {i}",
            "origen": {"trayectoria": "perf", "paso": i},
            "disparador": {"tool": "ejecutar", "patron_args": None, "contexto": {}},
            "chequeo": {"tipo": "patron_args", "patron": f"prohibido_{i}"},
            "remedio": "no",
            "estado": "activo",
            "creado": "2026-08-19T00:00:00", "aciertos": 0,
            "falsos_positivos": 0, "ultima_vez": None,
        })
    ac._guardar(datos)
    assert len(ac.activos()) == 50

    args = "pytest -q tests/ --maxfail=1"
    ac.evaluar("ejecutar", args, {})                       # calienta las regex
    n = 1000
    t0 = time.perf_counter()
    for _ in range(n):
        ac.evaluar("ejecutar", args, {})
    us = (time.perf_counter() - t0) / n * 1e6
    print(f"\n[medicion] evaluar 50 activos x {n} llamadas: {us:.2f} us/llamada")
    assert us < 1000.0, f"{us:.1f} us/llamada: no cabe en el camino caliente"


# ── regresion 2026-08-19: el formato de traza del BUCLE usa "action" ────────

def test_sintetiza_con_el_formato_action_del_bucle(tmp_path, monkeypatch):
    """El `trace` de cognia/agent/loop.py usa "action", no "tool".

    Sin esto, sintetizar() devolvia None con TODA traza real del bucle y el
    sistema inmune no podia producir un solo anticuerpo: funcionaba en sus
    tests (que usaban "tool") y estaba muerto en produccion. Lo cazo el e2e
    scripts/e2e_revolucionarios.py.
    """
    monkeypatch.setenv("COGNIA_INMUNE_DIR", str(tmp_path))
    import importlib
    from cognia.inmune import anticuerpos as inm
    importlib.reload(inm)
    tray = [
        {"action": "escribir_archivo", "args": "datos.txt | 42", "ok": True},
        {"action": "ejecutar", "args": "rm -rf datos.txt", "ok": True},
        {"action": "leer_archivo", "args": "datos.txt", "ok": False,
         "result_head": "RESULTADO leer_archivo ERROR: no existe datos.txt"},
    ]
    informe = {"paso_culpable": 1, "confianza": 0.95, "motivo": "contrafactual"}
    ab = inm.sintetizar(informe, tray)
    assert ab is not None, "con formato 'action' tiene que salir anticuerpo"
    assert ab["estado"] == "cuarentena"
    assert (ab.get("disparador") or {}).get("tool") == "ejecutar"
