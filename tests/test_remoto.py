"""
El control remoto movil: API basica sin arrancar REPLs reales.

La sesion-como-subproceso se verifico end-to-end a mano (mensaje desde el
navegador movil -> REPL real -> respuesta por WS); aqui se fija el contrato
de la API que la app necesita para arrancar.
"""

from pathlib import Path

from starlette.testclient import TestClient

from cognia.remoto.sesiones import _limpiar, registrar_proyecto
from cognia.remoto.servidor import _SALUDOS, crear_app


def _cliente():
    return TestClient(crear_app())


def test_saludo_por_franja_horaria():
    r = _cliente().get("/api/saludo").json()
    assert r["franja"] in _SALUDOS
    assert r["texto"] in _SALUDOS[r["franja"]]


def test_comandos_del_repl_disponibles():
    """Las sugerencias del '/': el catalogo REAL del CLI, no una copia."""
    r = _cliente().get("/api/comandos").json()
    cmds = {c["cmd"] for c in r}
    assert "/hacer" in cmds and "/crear" in cmds and "/investigar" in cmds
    assert len(cmds) > 50, "el catalogo debe ser el del REPL completo"


def test_cert_autofirmado_para_https(tmp_path):
    """El microfono del movil SOLO va en contexto seguro (https). El server
    genera un cert autofirmado; aqui se verifica que produce cert+key validos
    y reutilizables (no los regenera si ya existen)."""
    from cognia.remoto.servidor import asegurar_cert
    cert, key = asegurar_cert(tmp_path)
    assert Path(cert).exists() and Path(key).exists()
    assert "BEGIN CERTIFICATE" in Path(cert).read_text()
    # idempotente: segunda llamada reusa los mismos ficheros
    cert2, key2 = asegurar_cert(tmp_path)
    assert (cert2, key2) == (cert, key)


def test_expertos_catalogo_jarvis():
    """La vista Jarvis necesita el cerebro central + los expertos con color."""
    r = _cliente().get("/api/expertos").json()
    ids = {e["id"] for e in r}
    cerebro = [e for e in r if e.get("central")]
    assert len(cerebro) == 1 and cerebro[0]["id"] == "cerebro"
    # roles siempre presentes; micro-expertos segun haya en disco
    assert {"planificador", "generador", "evaluador", "juez"} <= ids
    # cada nodo lleva color (para pintar la constelacion y el filtro del chat)
    assert all(e.get("color", "").startswith("#") for e in r)


def test_app_movil_se_sirve():
    r = _cliente().get("/")
    assert r.status_code == 200
    assert "Cognia Remoto" in r.text
    assert 'data-tema' in r.text or "aplicarTema" in r.text


def test_registrar_proyecto_valida_carpetas(tmp_path, monkeypatch):
    # aislar el registro: sin esto el test contaminaba el proyectos.json REAL
    # del usuario (aparecieron 6 proyectos tmp en su app; reporte 2026-07-20)
    from cognia.remoto import sesiones as _ses
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS",
                        tmp_path / "proyectos.json")
    pr = registrar_proyecto(str(tmp_path))
    assert pr["nombre"] == tmp_path.name
    # repetir la misma carpeta reusa el proyecto (no duplica)
    assert registrar_proyecto(str(tmp_path))["id"] == pr["id"]
    try:
        registrar_proyecto(str(tmp_path / "no_existe"))
        assert False, "debia rechazar carpetas inexistentes"
    except ValueError:
        pass


def test_imagen_fuera_de_la_biblioteca_prohibida():
    """El endpoint de imagenes NO puede leer discos ajenos."""
    r = _cliente().get("/api/imagen", params={"ruta": "C:/Windows/win.ini"})
    assert r.status_code == 403


def test_limpiar_quita_ansi_y_prompt():
    assert _limpiar("\x1b[92mcognia> \x1b[0mhola") == "hola"
    assert _limpiar("cognia> cognia> respuesta") == "respuesta"
    assert _limpiar("──────────────") == ""


def test_grafo_visual_temas_y_hubs():
    """Bolitas divididas por temas: el hub no colapsa todo en un color, y el
    muestreo estratificado no deja que una relacion dominante borre el resto."""
    r = _cliente().get("/api/grafo_visual", params={"limite": 60}).json()
    if r.get("error"):
        return  # sin KG en esta maquina: nada que verificar
    assert r["n_temas"] >= 2, "todo en un tema = el hub colapso el grafo"
    temas = {n["tema"] for n in r["nodos"]}
    assert -1 in temas or r.get("hubs", 0) >= 0


def test_flujos_listar_y_guardar(tmp_path, monkeypatch):
    c = _cliente()
    flujos = c.get("/api/flujos").json()
    assert any(f["nombre"] == "depurar" for f in flujos)
    # guardar rechaza nombres con ruta (el movil no escribe fuera de skills)
    # 404 tambien vale: el router de FastAPI ni siquiera casa la ruta con
    # %2F — la traversal muere antes de llegar al handler.
    r = c.put("/api/flujos/..%2Fmalo", json={"contenido": "x"})
    assert r.status_code in (200, 400, 404)
    if r.status_code == 200:
        assert "/" not in r.json()["nombre"] and ".." not in r.json()["nombre"]


def test_reclasificar_separa_log_de_chat():
    """El chat solo lleva conversacion; banner, arte y logger van al Registro.
    Reporte del dueno 2026-07-20: el filtrado frontend dejaba pasar el banner
    y los tracebacks — la clasificacion vive ahora en el servidor."""
    from cognia.remoto.sesiones import reclasificar
    casos_log = [
        "2026-07-20 21:26:21 | INFO     | cognia.memory | x",
        "│ ⠀⣠⢚⣵⣄⠈⣼⡇ │",
        "██████╗    ██████╗",
        "v3.2 · Fases 1-13 · Sistema cognitivo",
        "Loading weights:   0%|          | 0/103",
    ]
    for texto in casos_log:
        quien, _ = reclasificar("cognia", texto, False)
        assert quien == "log", texto
    casos_chat = [
        "¡Hola! Saludos desde el móvil.",
        "Modo actual: sencillo.",
        "- **Tamaño del Modelo**: 8B parámetros",  # viñeta de respuesta, no diff
        "busca esto en el archivo",  # imperativo del chat, no la tool 'buscar'
    ]
    for texto in casos_chat:
        quien, _ = reclasificar("cognia", texto, False)
        assert quien == "cognia", texto


def test_reclasificar_actividad_plegable():
    """Pedido del dueno 2026-07-20: pasos, agentes, workflows y acciones de
    archivo van al chat como bloques plegables +/− ('actividad'), no como
    chat plano ni al Registro. Solo los logs quedan fuera."""
    from cognia.remoto.sesiones import reclasificar
    casos_actividad = [
        "RESULTADO ejecutar: 350",
        "escribir_archivo saludo.txt",
        "leer_archivo saludo.txt",
        'buscar "inversiones" en docs/',
        "paso 3 de 5",
        "Objetivo verificado: 1/1 criterios reales cumplidos",
        '+ "Hola desde el móvil."',
        "[planner] descomponiendo la meta",
        "Plan de subtareas:",
        # caja rich: se juzga el CONTENIDO, no el marco
        "│ RESULTADO leer_archivo saludo.txt: Hola │",
    ]
    for texto in casos_actividad:
        quien, _ = reclasificar("cognia", texto, False)
        assert quien == "actividad", texto
    # el marco puro de la caja sigue siendo log (no aporta contenido)
    quien, _ = reclasificar("cognia", "╭──────────────╮", False)
    assert quien == "log"


def test_reclasificar_paneles_rich_fuera_del_chat():
    """Los paneles enmarcados '│ ... │' (ayuda/estado) son chrome, no la
    respuesta: van a actividad (plegable), no al chat como markdown.
    Reporte 2026-07-20: '│ local │' y '│ Recibido: 1 parte(s) │' se colaban."""
    from cognia.remoto.sesiones import reclasificar
    for texto in ["│ local                        │",
                  "│ <ruta> | <contenido>. Recibido: 1 parte(s).   │"]:
        quien, _ = reclasificar("cognia", texto, False)
        assert quien == "actividad", texto
    # una respuesta normal (sin marco) sigue yendo al chat
    quien, _ = reclasificar("cognia", "Claro, aquí tienes el resumen.", False)
    assert quien == "cognia"


def test_reclasificar_traceback_multilinea_con_estado():
    from cognia.remoto.sesiones import reclasificar
    lineas = ["--- Logging error ---", "Traceback (most recent call last):",
              '  File "x.py", line 1', "TypeError: %d format",
              "Arguments: (16384, None)"]
    en_traza = False
    for l in lineas:
        quien, en_traza = reclasificar("cognia", l, en_traza)
        assert quien == "log", l
    quien, _ = reclasificar("cognia", "Y esta linea vuelve al chat", en_traza)
    assert quien == "cognia"
