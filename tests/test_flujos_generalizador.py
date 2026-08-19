"""
tests/test_flujos_generalizador.py
==================================
Tests del generalizador de flujos (cognia/flujos/generalizador.py).

Sin modelo y sin red: el unico punto donde entra un LLM (describir) recibe el
callable INYECTADO, asi que el modulo entero se prueba en seco.

Las trayectorias son sinteticas pero realistas — mismas tools y mismo
protocolo de args ('ruta | contenido') que produce cognia/agent/tools.py, y
mismos campos que graba cognia/flujos/grabador.py.
"""

import json

import pytest

from cognia.flujos import generalizador as G


# ---------------------------------------------------------------------------
# Trayectoria 1: crear un proyecto desde cero (con una lectura exploratoria al
# principio y una lectura de verificacion al final que no influyen en nada).
# ---------------------------------------------------------------------------

@pytest.fixture
def traj_proyecto():
    return {
        "id": "g1", "titulo": "crear proyecto",
        "tarea": "Crea un proyecto python llamado tienda_ropa con tests y un README",
        "workspace": "C:/tmp/ws",
        "pasos": [
            {"n": 1, "tool": "leer_archivo", "args": "notas_viejas.txt",
             "ok": True, "resumen_resultado": "12 lineas", "duracion_s": 0.1,
             "ficheros_tocados": ["notas_viejas.txt"], "comando": "",
             "exit_code": None},
            {"n": 2, "tool": "crear_directorio", "args": "tienda_ropa/src",
             "ok": True, "resumen_resultado": "creado", "duracion_s": 0.05,
             "ficheros_tocados": ["tienda_ropa/src"], "comando": "",
             "exit_code": None},
            {"n": 3, "tool": "escribir_archivo",
             "args": "tienda_ropa/src/main.py | def main():\n    print('tienda_ropa')\n",
             "ok": True, "resumen_resultado": "2 lineas escritas",
             "duracion_s": 0.2, "ficheros_tocados": ["tienda_ropa/src/main.py"],
             "comando": "", "exit_code": None},
            {"n": 4, "tool": "escribir_archivo",
             "args": "tienda_ropa/README.md | # tienda_ropa\n\nProyecto de ejemplo.\n",
             "ok": True, "resumen_resultado": "3 lineas escritas",
             "duracion_s": 0.1, "ficheros_tocados": ["tienda_ropa/README.md"],
             "comando": "", "exit_code": None},
            {"n": 5, "tool": "escribir_archivo",
             "args": ("tienda_ropa/tests/test_main.py | from src.main import main"
                      "\n\ndef test_main():\n    main()\n"),
             "ok": True, "resumen_resultado": "4 lineas escritas",
             "duracion_s": 0.1,
             "ficheros_tocados": ["tienda_ropa/tests/test_main.py"],
             "comando": "", "exit_code": None},
            {"n": 6, "tool": "ejecutar",
             "args": "python -m pytest tienda_ropa/tests -q", "ok": True,
             "resumen_resultado": "1 passed, exit 0", "duracion_s": 3.4,
             "ficheros_tocados": [],
             "comando": "python -m pytest tienda_ropa/tests -q", "exit_code": 0},
            {"n": 7, "tool": "leer_archivo", "args": "tienda_ropa/README.md",
             "ok": True, "resumen_resultado": "3 lineas", "duracion_s": 0.05,
             "ficheros_tocados": ["tienda_ropa/README.md"], "comando": "",
             "exit_code": None},
        ],
        "resultado": "Proyecto creado y 1 test pasa", "ok": True,
    }


# ---------------------------------------------------------------------------
# Trayectoria 2: refactor con tests. Trae un paso FALLIDO (los tests en rojo),
# una lectura irrelevante, y una relectura identica al final.
# ---------------------------------------------------------------------------

@pytest.fixture
def traj_refactor():
    return {
        "id": "g2", "titulo": "refactor informe",
        "tarea": ("Refactoriza cognia/analytics/informe.py para extraer la "
                  "funcion resumen y corre los tests"),
        "workspace": "C:/tmp/ws",
        "pasos": [
            {"n": 1, "tool": "leer_archivo", "args": "cognia/analytics/informe.py",
             "ok": True, "resumen_resultado": "180 lineas", "duracion_s": 0.1,
             "ficheros_tocados": ["cognia/analytics/informe.py"], "comando": "",
             "exit_code": None},
            {"n": 2, "tool": "leer_archivo", "args": "docs/arquitectura.md",
             "ok": True, "resumen_resultado": "60 lineas", "duracion_s": 0.1,
             "ficheros_tocados": ["docs/arquitectura.md"], "comando": "",
             "exit_code": None},
            {"n": 3, "tool": "editar_archivo",
             "args": ("cognia/analytics/informe.py | <<<<<<< SEARCH\n"
                      "def informe(d):\n=======\ndef resumen(d):\n>>>>>>> REPLACE"),
             "ok": True, "resumen_resultado": "1 bloque aplicado",
             "duracion_s": 0.3,
             "ficheros_tocados": ["cognia/analytics/informe.py"], "comando": "",
             "exit_code": None},
            {"n": 4, "tool": "ejecutar",
             "args": "python -m pytest tests/test_informe.py -q", "ok": False,
             "resumen_resultado": "1 failed, exit 1", "duracion_s": 2.0,
             "ficheros_tocados": [],
             "comando": "python -m pytest tests/test_informe.py -q",
             "exit_code": 1},
            {"n": 5, "tool": "editar_archivo",
             "args": ("cognia/analytics/informe.py | <<<<<<< SEARCH\n"
                      "    return d\n=======\n    return resumen(d)\n>>>>>>> REPLACE"),
             "ok": True, "resumen_resultado": "1 bloque aplicado",
             "duracion_s": 0.3,
             "ficheros_tocados": ["cognia/analytics/informe.py"], "comando": "",
             "exit_code": None},
            {"n": 6, "tool": "ejecutar",
             "args": "python -m pytest tests/test_informe.py -q", "ok": True,
             "resumen_resultado": "3 passed, exit 0", "duracion_s": 2.1,
             "ficheros_tocados": [],
             "comando": "python -m pytest tests/test_informe.py -q",
             "exit_code": 0},
            {"n": 7, "tool": "leer_archivo", "args": "cognia/analytics/informe.py",
             "ok": True, "resumen_resultado": "182 lineas", "duracion_s": 0.1,
             "ficheros_tocados": ["cognia/analytics/informe.py"], "comando": "",
             "exit_code": None},
        ],
        "resultado": "resumen extraida, 3 tests pasan", "ok": True,
    }


# ---------------------------------------------------------------------------
# Trayectoria 3: pura exploracion. No toca NADA: no hay nada verificable.
# ---------------------------------------------------------------------------

@pytest.fixture
def traj_exploracion():
    return {
        "id": "g3", "titulo": "explorar",
        "tarea": "Explicame como esta organizado el modulo de flujos",
        "workspace": "C:/tmp/ws",
        "pasos": [
            {"n": 1, "tool": "listar", "args": "cognia/flujos", "ok": True,
             "resumen_resultado": "4 entradas", "duracion_s": 0.05,
             "ficheros_tocados": [], "comando": "", "exit_code": None},
            {"n": 2, "tool": "leer_archivo", "args": "cognia/flujos/grabador.py",
             "ok": True, "resumen_resultado": "300 lineas", "duracion_s": 0.1,
             "ficheros_tocados": ["cognia/flujos/grabador.py"], "comando": "",
             "exit_code": None},
            {"n": 3, "tool": "buscar", "args": "def cargar | cognia/flujos",
             "ok": True, "resumen_resultado": "2 coincidencias",
             "duracion_s": 0.2, "ficheros_tocados": [], "comando": "",
             "exit_code": None},
        ],
        "resultado": "El modulo tiene grabador y reproductor.", "ok": True,
    }


def _ns(traj):
    return [p["n"] for p in traj["pasos"]]


def _reglas(traj):
    return {e["n"]: e["regla"] for e in G.podas_de(traj)}


# ---------------------------------------------------------------------------
# limpiar()
# ---------------------------------------------------------------------------

def test_poda_quita_las_lecturas_que_no_influyeron(traj_proyecto):
    limpia = G.limpiar(traj_proyecto)
    # 1 (notas_viejas.txt, nunca se vuelve a mencionar) y 7 (relectura final)
    assert _ns(limpia) == [2, 3, 4, 5, 6]
    assert _reglas(limpia) == {1: "lectura_no_influyente",
                               7: "lectura_no_influyente"}


def test_poda_conserva_la_lectura_del_fichero_que_luego_se_edita(traj_refactor):
    limpia = G.limpiar(traj_refactor)
    # El paso 1 lee informe.py y los pasos 3 y 5 lo editan: influyo.
    assert 1 in _ns(limpia)
    assert 2 not in _ns(limpia)         # docs/arquitectura.md no influyo


def test_poda_quita_el_paso_fallido_y_la_repeticion(traj_refactor):
    limpia = G.limpiar(traj_refactor)
    assert _ns(limpia) == [1, 3, 5, 6]
    reglas = _reglas(limpia)
    assert reglas[4] == "fallido"        # los tests en rojo
    assert reglas[7] == "repeticion"     # relectura identica al paso 1
    assert reglas[2] == "lectura_no_influyente"


def test_poda_distingue_el_reintento_del_primer_fallo():
    traj = {
        "id": "g4", "tarea": "Instala las dependencias del proyecto demo",
        "pasos": [
            {"n": 1, "tool": "ejecutar", "args": "pip install -r req.txt",
             "ok": False, "resumen_resultado": "error de red, exit 1",
             "comando": "pip install -r req.txt", "exit_code": 1,
             "ficheros_tocados": []},
            {"n": 2, "tool": "ejecutar", "args": "pip install -r req.txt",
             "ok": False, "resumen_resultado": "error de red, exit 1",
             "comando": "pip install -r req.txt", "exit_code": 1,
             "ficheros_tocados": []},
            {"n": 3, "tool": "ejecutar", "args": "pip install -r req.txt",
             "ok": True, "resumen_resultado": "ok, exit 0",
             "comando": "pip install -r req.txt", "exit_code": 0,
             "ficheros_tocados": []},
        ],
        "resultado": "instalado", "ok": True,
    }
    limpia = G.limpiar(traj)
    # El reintento que SI funciono es el que hizo el trabajo: sobrevive solo el.
    assert _ns(limpia) == [3]
    assert _reglas(limpia) == {1: "fallido", 2: "reintento_fallido"}


def test_cada_paso_podado_deja_su_motivo_auditable(traj_refactor):
    limpia = G.limpiar(traj_refactor)
    entradas = G.podas_de(limpia)
    assert len(entradas) == 3
    for e in entradas:
        assert e["regla"]
        assert len(e["motivo"]) > 10      # explicacion, no una etiqueta
        assert e["tool"]


def test_la_poda_nunca_deja_la_trayectoria_vacia(traj_exploracion):
    # Todas las lecturas son "no influyentes" (no hay nada despues), pero
    # borrarlas todas daria un flujo de cero pasos: se revierte y se declara.
    limpia = G.limpiar(traj_exploracion)
    assert _ns(limpia) == [1, 2, 3]
    assert any(e["regla"] == "poda_revertida" for e in G.podas_de(limpia))


def test_limpiar_no_muta_la_trayectoria_original(traj_refactor):
    antes = len(traj_refactor["pasos"])
    G.limpiar(traj_refactor)
    assert len(traj_refactor["pasos"]) == antes
    assert "_poda" not in traj_refactor


# ---------------------------------------------------------------------------
# detectar_huecos()
# ---------------------------------------------------------------------------

def test_detecta_el_nombre_del_proyecto_como_hueco(traj_proyecto):
    huecos = G.detectar_huecos(G.limpiar(traj_proyecto))
    por_ejemplo = {h["ejemplo"]: h for h in huecos}
    assert "tienda_ropa" in por_ejemplo
    h = por_ejemplo["tienda_ropa"]
    # Nombre tomado del sustantivo que lo precede en la tarea ("un proyecto
    # python llamado tienda_ropa"), no de la tecnologia ni del verbo.
    assert h["nombre_sugerido"] == "proyecto"
    assert h["en_tarea"] is True
    # Aparece en la ruta de 4 pasos y ademas dentro del contenido escrito.
    assert len(set(o[0] for o in h["ocurrencias"])) >= 4


def test_el_valor_de_la_tarea_gana_a_la_ruta_larga_que_lo_contiene(traj_proyecto):
    huecos = G.detectar_huecos(G.limpiar(traj_proyecto))
    ejemplos = [h["ejemplo"] for h in huecos]
    # 'tienda_ropa/src/main.py' NO se vuelve un hueco opaco: gana 'tienda_ropa'
    # y la plantilla queda '{proyecto}/src/main.py'.
    assert "tienda_ropa/src/main.py" not in ejemplos


def test_detecta_la_ruta_del_modulo_refactorizado(traj_refactor):
    huecos = G.detectar_huecos(G.limpiar(traj_refactor))
    por_ejemplo = {h["ejemplo"]: h for h in huecos}
    h = por_ejemplo["cognia/analytics/informe.py"]
    assert h["tipo"] == "ruta"
    assert h["nombre_sugerido"] == "ruta_informe"   # del stem, no del path
    assert h["en_tarea"] is True


def test_las_ocurrencias_traen_paso_campo_y_span(traj_proyecto):
    huecos = G.detectar_huecos(G.limpiar(traj_proyecto))
    h = [x for x in huecos if x["ejemplo"] == "tienda_ropa"][0]
    for (paso, campo, span) in h["ocurrencias"]:
        assert isinstance(paso, int)
        assert campo in ("args", "comando")
        assert span[1] - span[0] == len("tienda_ropa")


def test_no_parametriza_vocabulario_estructural(traj_proyecto):
    huecos = G.detectar_huecos(G.limpiar(traj_proyecto))
    ejemplos = set(h["ejemplo"] for h in huecos)
    # 'tests', 'src' y 'python' cumplen las senales pero nadie quiere
    # rellenarlos: convertirlos en huecos hace el flujo inusable.
    assert not ejemplos & {"tests", "src", "python", "README"}


# ---------------------------------------------------------------------------
# parametrizar() + instanciar()  — la plantilla tiene que RE-SUSTITUIR bien
# ---------------------------------------------------------------------------

def test_la_plantilla_reproduce_los_args_originales(traj_proyecto):
    limpia = G.limpiar(traj_proyecto)
    huecos = G.detectar_huecos(limpia)
    flujo = G.parametrizar(limpia, huecos)
    vuelta = G.instanciar(flujo, {"proyecto": "tienda_ropa"})
    assert vuelta["ok"] is True
    assert [p["args"] for p in vuelta["pasos"]] == \
           [p["args"] for p in limpia["pasos"]]


def test_la_plantilla_sustituye_tambien_dentro_del_contenido(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)
    escritos = [p["args_plantilla"] for p in flujo["pasos"]
                if p["tool"] == "escribir_archivo"]
    main_py = [a for a in escritos if "main.py" in a][0]
    assert main_py.startswith("{proyecto}/src/main.py |")
    assert "print('{proyecto}')" in main_py      # dentro del codigo escrito
    assert "tienda_ropa" not in main_py


def test_instanciar_con_otro_valor_produce_otro_proyecto(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)
    inst = G.instanciar(flujo, {"proyecto": "tienda_libros"})
    args = [p["args"] for p in inst["pasos"]]
    assert "tienda_libros/src" in args[0]
    assert not any("tienda_ropa" in a for a in args)
    assert any("pytest tienda_libros/tests" in a for a in args)


def test_instanciar_reporta_el_obligatorio_que_falta_sin_lanzar(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)
    inst = G.instanciar(flujo, {})
    assert inst["ok"] is False
    assert "proyecto" in inst["faltantes"]
    # No lanza: devuelve los pasos con el marcador intacto para que el llamador
    # decida (pedirle el valor al usuario, abortar, lo que sea).
    assert "{proyecto}" in inst["pasos"][0]["args"]


def test_el_param_de_la_tarea_es_obligatorio_y_el_incidental_no(traj_refactor):
    flujo = G.generalizar(traj_refactor)
    por_nombre = {p["nombre"]: p for p in flujo["params"]}
    assert por_nombre["ruta_informe"]["obligatorio"] is True    # sale en la tarea
    # La ruta del test nunca se nombro: tiene el ejemplo como valor por defecto.
    assert por_nombre["ruta_test_informe"]["obligatorio"] is False
    # Dando SOLO los obligatorios el flujo ya es ejecutable: el incidental cae
    # a su ejemplo en vez de bloquear.
    inst = G.instanciar(flujo, {p["nombre"]: p["ejemplo"]
                                for p in flujo["params"] if p["obligatorio"]})
    assert inst["ok"] is True
    assert "ruta_test_informe" not in inst["faltantes"]
    assert any("tests/test_informe.py" in p["args"] for p in inst["pasos"])


def test_la_plantilla_no_rompe_el_contenido_con_llaves():
    # Un JSON escrito por el agente lleva llaves: str.format explotaria o se
    # comeria caracteres. Por eso el relleno es por marcador conocido.
    traj = {
        "id": "g5", "tarea": "Crea la config del servicio pagos",
        "pasos": [
            {"n": 1, "tool": "escribir_archivo",
             "args": 'pagos/config.json | {"nombre": "pagos", "port": 8080}',
             "ok": True, "resumen_resultado": "1 linea escrita",
             "ficheros_tocados": ["pagos/config.json"], "comando": "",
             "exit_code": None},
        ],
        "resultado": "config creada", "ok": True,
    }
    flujo = G.generalizar(traj)
    inst = G.instanciar(flujo, {p["nombre"]: p["ejemplo"]
                                for p in flujo["params"]})
    assert inst["pasos"][0]["args"] == traj["pasos"][0]["args"]
    assert json.loads(inst["pasos"][0]["args"].split("|", 1)[1])["port"] == 8080


# ---------------------------------------------------------------------------
# postcondiciones_de()
# ---------------------------------------------------------------------------

def test_postcondiciones_del_efecto_observado(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)
    posts = flujo["postcondiciones"]
    existe = [p["ruta"] for p in posts if p["tipo"] == "fichero_existe"]
    assert "{proyecto}/src/main.py" in existe
    assert "{proyecto}/README.md" in existe
    comandos = [p["comando"] for p in posts if p["tipo"] == "comando_exit0"]
    assert comandos == ["python -m pytest {proyecto}/tests -q"]
    assert flujo["estado"] == "borrador"


def test_postcondicion_de_edicion_mira_el_lado_NUEVO(traj_refactor):
    # Chequear el lado SEARCH verificaria lo que se acaba de borrar: el examen
    # reprobaria justo cuando el flujo funciono.
    flujo = G.generalizar(traj_refactor)
    contiene = [p["texto"] for p in flujo["postcondiciones"]
                if p["tipo"] == "fichero_contiene"]
    assert any("(d):" in t and t.startswith("def ") for t in contiene)
    assert not any("SEARCH" in t or "=====" in t for t in contiene)


def test_un_comando_sin_exit0_no_genera_postcondicion():
    traj = {
        "id": "g6", "tarea": "Arranca el servidor de la demo",
        "pasos": [
            {"n": 1, "tool": "ejecutar_fondo", "args": "python demo/server.py",
             "ok": True, "resumen_resultado": "arrancado en background",
             "comando": "python demo/server.py", "exit_code": None,
             "ficheros_tocados": []},
        ],
        "resultado": "servidor arriba", "ok": True,
    }
    # Sin exit code OBSERVADO no se afirma nada: un chequeo inventado que
    # siempre pasa es peor que declarar el flujo no examinable.
    assert G.postcondiciones_de(traj) == []
    assert G.generalizar(traj)["estado"] == "no_examinable"


def test_los_pasos_fallidos_no_aportan_postcondiciones(traj_refactor):
    posts = G.postcondiciones_de(traj_refactor)   # SIN limpiar, a proposito
    assert all(p.get("de_paso") != 4 for p in posts)


def test_flujo_sin_efectos_verificables_es_no_examinable(traj_exploracion):
    flujo = G.generalizar(traj_exploracion)
    assert flujo["postcondiciones"] == []
    assert flujo["estado"] == "no_examinable"
    # Y no se "arregla" borrando los pasos: siguen ahi para que el usuario vea
    # que grabo.
    assert len(flujo["pasos"]) == 3


# ---------------------------------------------------------------------------
# describir()  — con y sin LLM
# ---------------------------------------------------------------------------

def test_describir_sin_llm_produce_algo_usable(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)          # completar_fn=None
    assert flujo["nombre"] and flujo["nombre"] == flujo["nombre"].lower()
    assert " " not in flujo["nombre"]
    assert "proyecto" in flujo["nombre"]
    assert "5 pasos" in flujo["descripcion"]
    assert "proyecto" in flujo["descripcion"]


def test_el_nombre_determinista_no_lleva_el_VALOR_de_ejemplo(traj_proyecto):
    flujo = G.generalizar(traj_proyecto)
    # El flujo sirve para cualquier tienda: su nombre no puede ser el ejemplo.
    assert "tienda_ropa" not in flujo["nombre"]


def test_el_llm_solo_pule_nombre_y_descripcion(traj_proyecto):
    llamadas = []

    def completar_fn(prompt):
        llamadas.append(prompt)
        return "NOMBRE: crear_proyecto_python\nDESCRIPCION: Crea un proyecto con tests."

    base = G.generalizar(traj_proyecto)
    pulido = G.generalizar(traj_proyecto, completar_fn=completar_fn)
    assert llamadas, "el completar_fn inyectado tiene que usarse"
    assert pulido["nombre"] == "crear_proyecto_python"
    assert pulido["descripcion"] == "Crea un proyecto con tests."
    # La SUSTANCIA no la toca el LLM.
    assert pulido["pasos"] == base["pasos"]
    assert pulido["postcondiciones"] == base["postcondiciones"]
    assert pulido["params"] == base["params"]
    assert pulido["estado"] == base["estado"]


def test_un_llm_roto_no_rompe_el_flujo(traj_proyecto):
    def completar_fn(prompt):
        raise RuntimeError("backend caido")

    base = G.generalizar(traj_proyecto)
    igual = G.generalizar(traj_proyecto, completar_fn=completar_fn)
    assert igual["nombre"] == base["nombre"]
    assert igual["descripcion"] == base["descripcion"]


def test_una_respuesta_basura_del_llm_cae_a_la_determinista(traj_proyecto):
    base = G.generalizar(traj_proyecto)
    igual = G.generalizar(traj_proyecto, completar_fn=lambda p: "no se, perdon")
    assert igual["nombre"] == base["nombre"]


def test_el_llm_puede_responder_json(traj_proyecto):
    flujo = G.generalizar(
        traj_proyecto,
        completar_fn=lambda p: '{"nombre": "scaffold_py", "descripcion": "Scaffold."}')
    assert flujo["nombre"] == "scaffold_py"
    assert flujo["descripcion"] == "Scaffold."


# ---------------------------------------------------------------------------
# Guardado / carga
# ---------------------------------------------------------------------------

def test_guardar_y_cargar_conserva_el_flujo(tmp_path, monkeypatch, traj_proyecto):
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path))
    flujo = G.generalizar(traj_proyecto)
    ruta = G.guardar_flujo(flujo)
    assert ruta and (tmp_path / (flujo["nombre"] + ".json")).exists()

    leido = G.cargar_flujo(flujo["nombre"])
    assert leido["version_formato"] == G.FORMATO_VERSION
    assert leido["pasos"] == flujo["pasos"]
    assert leido["postcondiciones"] == flujo["postcondiciones"]
    assert leido["estado"] == "borrador"
    # Un flujo cargado del disco se puede instanciar igual que uno recien hecho.
    assert G.instanciar(leido, {"proyecto": "x"})["ok"] is True


def test_listar_flujos_resume_lo_guardado(tmp_path, monkeypatch,
                                          traj_proyecto, traj_exploracion):
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path))
    G.guardar_flujo(G.generalizar(traj_proyecto))
    G.guardar_flujo(G.generalizar(traj_exploracion))
    filas = G.listar_flujos()
    assert len(filas) == 2
    estados = sorted(f["estado"] for f in filas)
    assert estados == ["borrador", "no_examinable"]


def test_cargar_lo_inexistente_o_corrupto_devuelve_none(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path))
    assert G.cargar_flujo("no_existe") is None
    (tmp_path / "roto.json").write_text("{esto no es json", encoding="utf-8")
    assert G.cargar_flujo("roto") is None
    assert G.listar_flujos() == []      # el corrupto se salta, no revienta


def test_una_version_de_formato_distinta_avisa_pero_no_lanza(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path))
    (tmp_path / "futuro.json").write_text(
        json.dumps({"nombre": "futuro", "version_formato": 99, "pasos": []}),
        encoding="utf-8")
    flujo = G.cargar_flujo("futuro")
    assert flujo is not None
    assert "_aviso" in flujo


# ---------------------------------------------------------------------------
# Bordes: nada de esto puede lanzar (el generalizador corre tras una tarea).
# ---------------------------------------------------------------------------

def test_entradas_degeneradas_no_lanzan():
    for entrada in (None, {}, {"pasos": []}, {"pasos": None, "tarea": None}):
        flujo = G.generalizar(entrada)
        assert flujo["estado"] == "no_examinable"
        assert flujo["nombre"]
        assert G.instanciar(flujo, {})["pasos"] == []


def test_el_flujo_generado_liga_en_el_reproductor(traj_proyecto, traj_refactor):
    # Contrato entre modulos, no cortesia: reproductor.ligar() lee 'default'
    # (no 'ejemplo') y rechaza el flujo si queda un marcador sin ligar. Sin
    # este test el desajuste seria SILENCIOSO hasta la primera reproduccion.
    from cognia.flujos import reproductor

    for traj in (traj_proyecto, traj_refactor):
        flujo = G.generalizar(traj)
        obligatorios = {p["nombre"]: p["ejemplo"]
                        for p in flujo["params"] if p["obligatorio"]}
        ligado = reproductor.ligar(flujo, obligatorios)
        assert ligado["ok"] is True, ligado["error"]
        assert ligado["sin_ligar"] == []
        assert all("{" not in p["args"] or "}" not in p["args"]
                   for p in ligado["pasos"])


def test_el_reproductor_entiende_todas_las_postcondiciones(traj_proyecto,
                                                           traj_refactor):
    # verificar_postcondiciones REPRUEBA todo tipo que no conoce: emitir un
    # tipo que no soporta condenaria al flujo a suspender su propio examen.
    from cognia.flujos import reproductor

    tipos = set()
    for traj in (traj_proyecto, traj_refactor):
        tipos |= set(p["tipo"] for p in G.generalizar(traj)["postcondiciones"])
    assert tipos <= {"fichero_existe", "fichero_contiene", "comando_exit0"}

    resultados = reproductor.verificar_postcondiciones(
        [{"tipo": t, "ruta": "no/existe.txt", "texto": "x", "comando": "x"}
         for t in sorted(tipos)],
        ejecutar_fn=lambda c, cwd=None: (0, ""))
    assert not any("desconocido" in r["detalle"] for r in resultados)


def test_un_flujo_que_solo_borra_sale_no_examinable():
    traj = {
        "id": "g7", "tarea": "Borra el fichero temporal cache.tmp",
        "pasos": [
            {"n": 1, "tool": "borrar_archivo", "args": "cache.tmp", "ok": True,
             "resumen_resultado": "borrado", "ficheros_tocados": ["cache.tmp"],
             "comando": "", "exit_code": None},
        ],
        "resultado": "borrado", "ok": True,
    }
    flujo = G.generalizar(traj)
    assert flujo["postcondiciones"] == []
    assert flujo["estado"] == "no_examinable"


def test_generalizar_es_determinista(traj_proyecto, traj_refactor):
    # La razon de ser del modulo: dos corridas sobre la misma grabacion dan el
    # MISMO flujo. Si dependiera de un LLM esto no se podria ni afirmar.
    for traj in (traj_proyecto, traj_refactor):
        a, b = G.generalizar(traj), G.generalizar(traj)
        a["origen"].pop("ts")
        b["origen"].pop("ts")
        assert a == b


def test_acepta_el_objeto_grabacion_por_pato(traj_proyecto):
    class FakeGrabacion:
        def a_dict(self):
            return traj_proyecto

    flujo = G.generalizar(FakeGrabacion())
    assert flujo["origen"]["grabacion_id"] == "g1"
    assert flujo["estado"] == "borrador"


def test_avisa_cuando_los_args_vienen_recortados_por_el_bus(traj_proyecto):
    # El bus emite args[:120] (loop.py:711): la plantilla puede estar
    # incompleta y el flujo tiene que DECIRLO, no aparentar estar entero.
    traj_proyecto["pasos"][2]["via_bus"] = True
    flujo = G.generalizar(traj_proyecto)
    assert flujo["avisos"] and "recortados" in flujo["avisos"][0]


def test_sin_pasos_del_bus_no_hay_avisos(traj_proyecto):
    assert G.generalizar(traj_proyecto)["avisos"] == []
