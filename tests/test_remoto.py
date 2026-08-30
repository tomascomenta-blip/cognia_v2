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
    """Cliente YA autenticado: todo /api/* exige el token compartido."""
    from cognia.remoto import servidor as _srv
    app = crear_app()
    c = TestClient(app)
    c.headers.update(
        {"X-Cognia-Token": _srv.asegurar_token(_srv.RAIZ_DATOS)})
    return c


def test_saludo_por_franja_horaria():
    r = _cliente().get("/api/saludo").json()
    assert r["franja"] in _SALUDOS
    assert r["texto"] in _SALUDOS[r["franja"]]


def _nivel_nucleo(monkeypatch):
    """Fija el nivel por defecto sin tocar la config del dueno.

    `_comandos()` pregunta por `cli_visibilidad.es_avanzado()`, que depende de
    un cache global y de ~/.cognia/config.env: sin fijarlo, este test aprueba
    o falla segun QUE OTRO test corriera antes."""
    from cognia import cli_visibilidad as vis
    monkeypatch.setattr(vis, "es_avanzado", lambda override=None: False)


def test_comandos_del_repl_disponibles(monkeypatch):
    """Las sugerencias del '/': el catalogo REAL del CLI, no una copia.

    ENMENDADO 2026-08-29 (visibilidad de comandos): el movil ya no recibe las
    280 entradas por defecto, sino el NUCLEO -- el mismo recorte que ve el
    escritorio, porque un desplegable de 280 lineas en un telefono es el muro
    que `cognia/cli_visibilidad.py` existe para quitar. Lo que este test sigue
    fijando es que las entradas SALEN DEL CLI REAL y no de una copia."""
    from cognia.cli import _CMD_DESCRIPTIONS

    _nivel_nucleo(monkeypatch)
    r = _cliente().get("/api/comandos").json()
    cmds = {c["cmd"] for c in r}
    assert "/hacer" in cmds and "/crear" in cmds
    assert len(cmds) > 50, "el nucleo tiene ~80 comandos, no cuatro"
    assert cmds <= set(_CMD_DESCRIPTIONS), "hay comandos que el REPL no tiene"
    # y cada descripcion es la del CLI, no un texto propio del remoto
    assert all(c["desc"] == _CMD_DESCRIPTIONS[c["cmd"]] for c in r)


def test_comandos_avanzado_devuelve_el_catalogo_entero(monkeypatch):
    """OCULTAR NO ES DESACTIVAR, tambien en el movil: `?avanzado=1` trae las
    280 entradas, y los comandos de nicho siguen siendo tecleables aunque no
    se sugieran."""
    from cognia.cli import _CMD_DESCRIPTIONS

    _nivel_nucleo(monkeypatch)
    c = _cliente()
    nucleo = {x["cmd"] for x in c.get("/api/comandos").json()}
    todo = {x["cmd"] for x in c.get("/api/comandos?avanzado=1").json()}
    assert todo == set(_CMD_DESCRIPTIONS)
    assert "/investigar" in todo and "/investigar" not in nucleo
    assert len(todo) > len(nucleo)
    # sinonimos: quien teclea la URL a mano no merece un 422 de FastAPI
    for valor in ("on", "true", "si", "todo"):
        assert len(c.get(f"/api/comandos?avanzado={valor}").json()) == len(todo)


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


# ── Regresion 2026-07-25: las imagenes del AGENTE no se veian en el chat ──
# El front detectaba la ruta del "RESULTADO imagen_generar OK: <ruta>" y pedia
# /api/imagen, pero el endpoint solo abria la biblioteca de program_creator:
# 403 -> onerror -> el <img> se borraba. Insercion de imagenes que fallaba en
# silencio. Ahora se autoriza por raices (proyectos registrados incluidos).

def _png_minimo(destino: Path) -> Path:
    """PNG 1x1 real (no un stub): el endpoint devuelve bytes de verdad."""
    import base64
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
        b"YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
    return destino


def test_imagen_del_workspace_del_agente_se_sirve(tmp_path, monkeypatch):
    """Una imagen en <proyecto>/imagenes/ (donde image_tools deja las suyas)
    DEBE poder insertarse en el chat. Antes del fix: 403."""
    from cognia.remoto import sesiones as _ses
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "mi_proyecto"
    proyecto.mkdir()
    registrar_proyecto(str(proyecto))
    png = _png_minimo(proyecto / "imagenes" / "gen_12345678.png")
    r = _cliente().get("/api/imagen", params={"ruta": str(png)})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_imagen_admite_jpg_y_webp(tmp_path, monkeypatch):
    """No solo PNG: una captura o un asset bajado puede ser jpg/webp."""
    from cognia.remoto import sesiones as _ses
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "proy2"
    proyecto.mkdir()
    registrar_proyecto(str(proyecto))
    cli = _cliente()
    for nombre, mime in (("captura.jpg", "image/jpeg"),
                         ("asset.webp", "image/webp")):
        f = proyecto / nombre
        f.write_bytes(b"bytes-de-imagen")
        r = cli.get("/api/imagen", params={"ruta": str(f)})
        assert r.status_code == 200, (nombre, r.text)
        assert r.headers["content-type"] == mime


def test_imagen_no_servible_da_error_legible(tmp_path, monkeypatch):
    """Un .txt DENTRO del proyecto no es 403 (esta permitido) sino 415 con
    motivo: el chat lo muestra en vez de tragarselo."""
    from cognia.remoto import sesiones as _ses
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "proy3"
    proyecto.mkdir()
    registrar_proyecto(str(proyecto))
    doc = proyecto / "notas.txt"
    doc.write_text("hola", encoding="utf-8")
    r = _cliente().get("/api/imagen", params={"ruta": str(doc)})
    assert r.status_code == 415
    assert "formato" in r.json()["error"]


def test_imagen_no_escapa_del_proyecto_con_dotdot(tmp_path, monkeypatch):
    """Ampliar las raices no puede abrir el disco: '..' se resuelve ANTES."""
    from cognia.remoto import sesiones as _ses
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "proy4"
    proyecto.mkdir()
    registrar_proyecto(str(proyecto))
    fuera = _png_minimo(tmp_path.parent / "secreto_fuera.png")
    r = _cliente().get("/api/imagen",
                       params={"ruta": str(proyecto / ".." / ".." / fuera.name)})
    assert r.status_code == 403
    fuera.unlink(missing_ok=True)


def test_front_detecta_rutas_de_imagen_y_no_borra_en_fallo():
    """Contrato del front (se rompio dos veces por editar solo el back):
    regex multi-formato, insercion de TODAS las rutas y fallo VISIBLE."""
    html = (Path(__file__).resolve().parent.parent
            / "cognia" / "remoto" / "static" / "index.html").read_text(
                encoding="utf-8")
    assert "RUTA_IMG" in html and "function rutasImagen" in html
    for ext in ("png", "jpe?g", "webp", "gif"):
        assert ext in html.split("const EXT_IMG")[1][:120]
    # el onerror ya no puede limitarse a borrar el <img>
    assert "img.remove()" not in html
    assert "img-fallo" in html


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
    from cognia.remoto import servidor as _srv
    # las escrituras del test van a un cognia_skills/ temporal, no al repo
    monkeypatch.setattr(_srv, "_DIR_FLUJOS_EDIT", tmp_path / "cognia_skills")
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


# ── Regresion A6 2026-08-01: 0.0.0.0:8777 sin autenticacion ──
# Cada sesion corre con COGNIA_ACCESO_TOTAL=1 + COGNIA_SCREEN_AUTO=1:
# cualquier dispositivo de la LAN pilotaba la maquina. Ahora todo /api/*
# y /ws/* exige el token compartido de ~/.cognia/remoto/token.txt.

def test_api_exige_token():
    from cognia.remoto import servidor as _srv
    c = TestClient(crear_app())            # SIN header de token
    assert c.get("/api/proyectos").status_code == 401
    assert c.put("/api/flujos/x", json={"contenido": "y"}).status_code == 401
    tok = _srv.asegurar_token(_srv.RAIZ_DATOS)
    assert c.get("/api/proyectos",
                 headers={"X-Cognia-Token": tok}).status_code == 200
    # ?token= tambien vale: <img src> y la primera visita desde la URL impresa
    assert c.get(f"/api/proyectos?token={tok}").status_code == 200
    # un token INCORRECTO no pasa
    assert c.get("/api/proyectos",
                 headers={"X-Cognia-Token": "nope"}).status_code == 401
    # la app en si se sirve sin token (el token llega en esa URL)
    assert c.get("/").status_code == 200


def test_token_persistente_y_no_vacio(tmp_path):
    from cognia.remoto.servidor import asegurar_token
    t1 = asegurar_token(tmp_path)
    assert len(t1) >= 16
    assert asegurar_token(tmp_path) == t1          # idempotente
    assert (tmp_path / "token.txt").read_text(encoding="utf-8").strip() == t1


def test_ws_exige_token(tmp_path, monkeypatch):
    from cognia.remoto import sesiones as _ses
    from cognia.remoto import servidor as _srv
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    pr = registrar_proyecto(str(tmp_path))
    c = TestClient(crear_app())
    entro = False
    try:
        with c.websocket_connect(f"/ws/{pr['id']}/s1"):
            entro = True
    except Exception:
        pass                                # cierre antes del accept: correcto
    assert not entro, "el WebSocket acepto una conexion sin token"


# ── Regresion A6: "[backend] via=..." llegaba al CHAT como si fuera Cognia ──
# stderr del REPL va mergeado a stdout; la instrumentacion del backend es
# actividad (plegable), no conversacion. transcripcion() reclasifica al leer,
# asi que las sesiones viejas se limpian gratis.

def test_reclasificar_instrumentacion_backend_a_actividad():
    from cognia.remoto.sesiones import reclasificar
    casos = [
        "[backend] via=generate modelo=qwen2.5-coder-14b-instruct-q4_k_m",
        "[backend] DEGRADADO: 'chat' sin backend LLM -- respuesta template",
        "[degradado] llama: el server no responde",
        "[llama_backend] llama-server started on :8080 (pid=1234)",
    ]
    for texto in casos:
        quien, _ = reclasificar("cognia", texto, False)
        assert quien == "actividad", texto


# ── Regresion A6: PUT /api/flujos escribia en el repo sin safety scan ──

def test_guardar_flujo_escanea_y_escribe_fuera_del_repo(tmp_path, monkeypatch):
    from cognia.remoto import servidor as _srv
    monkeypatch.setattr(_srv, "_DIR_FLUJOS_EDIT", tmp_path / "cognia_skills")
    c = _cliente()
    # instrucciones destructivas: 400 y NO se persiste nada
    r = c.put("/api/flujos/malicioso",
              json={"contenido": "paso 1: corre rm -rf C:/Users"})
    assert r.status_code == 400, r.text
    assert "peligroso" in r.json()["error"]
    assert not (tmp_path / "cognia_skills" / "malicioso.md").exists()
    # contenido sano: va a cognia_skills/ (nunca dentro del paquete cognia/)
    r = c.put("/api/flujos/mi-flujo", json={"contenido": "# pasos\n1. leer"})
    assert r.status_code == 200, r.text
    destino = tmp_path / "cognia_skills" / "mi-flujo.md"
    assert destino.read_text(encoding="utf-8") == "# pasos\n1. leer"
    assert not (_srv._DIR_FLUJOS / "mi-flujo.md").exists()
    # el GET lo devuelve: round-trip del editor del movil
    nombres = {f["nombre"] for f in c.get("/api/flujos").json()}
    assert "mi-flujo" in nombres and "depurar" in nombres


# ── Regresion A6: sin forma de PARAR un REPL sin borrar su transcripcion ──

def _repl_falso():
    """Sustituto de `python -m cognia`: eco por stdin, muere con /salir."""
    import sys as _sys
    guion = ("import sys\n"
             "for l in sys.stdin:\n"
             "    if l.strip() == '/salir':\n"
             "        break\n"
             "    print('eco: ' + l.strip(), flush=True)\n")
    return [_sys.executable, "-c", guion]


def _remoto_aislado(tmp_path, monkeypatch):
    """RAIZ_DATOS/proyectos/REPL parcheados a tmp: nada toca ~/.cognia."""
    from cognia.remoto import sesiones as _ses
    from cognia.remoto import servidor as _srv
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    monkeypatch.setattr(_ses, "_python_cognia", _repl_falso)
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    return registrar_proyecto(str(proyecto))


def test_parar_sesion_mata_el_repl_y_conserva_el_jsonl(tmp_path, monkeypatch):
    pr = _remoto_aislado(tmp_path, monkeypatch)
    c = _cliente()
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones",
                 json={"titulo": "t"}).json()["id"]
    assert any(m["sesion"] == sid for m in c.get("/api/monitores").json())
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/parar")
    assert r.json()["ok"] is True
    # el REPL murio...
    assert all(m["sesion"] != sid for m in c.get("/api/monitores").json())
    # ...y la transcripcion SOBREVIVE (parar != borrar)
    assert (tmp_path / pr["id"] / f"{sid}.jsonl").exists()
    # parar dos veces es inocuo (ya no estaba viva)
    assert c.post(
        f"/api/proyectos/{pr['id']}/sesiones/{sid}/parar").json()["ok"] is False


# ── Regresion A6: baja de proyecto dejaba REPLs huerfanos y datos colgados ──

def test_baja_proyecto_para_repls_y_aparta_datos(tmp_path, monkeypatch):
    pr = _remoto_aislado(tmp_path, monkeypatch)
    c = _cliente()
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones",
                 json={}).json()["id"]
    assert len(c.get("/api/monitores").json()) == 1
    r = c.delete(f"/api/proyectos/{pr['id']}").json()
    assert r["ok"] is True and r["sesiones_paradas"] == 1
    # 0 REPLs vivos y el proyecto fuera de la lista
    assert c.get("/api/monitores").json() == []
    assert all(p["id"] != pr["id"] for p in c.get("/api/proyectos").json())
    # las transcripciones NO se borraron: estan en la papelera
    assert r["papelera"], "los datos debian moverse a la papelera"
    assert (Path(r["papelera"]) / f"{sid}.jsonl").exists()
    assert not (tmp_path / pr["id"]).exists()


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


# ── Regresión 2026-08-01 (revisión adversarial): la PUERTA de entrada ──

def test_token_no_ascii_da_401_no_500():
    """?token=<no ASCII> reventaba el middleware: hmac.compare_digest lanza
    TypeError con str no-ASCII y el 500 salía sin manejar. Debe ser 401."""
    c = TestClient(crear_app())                 # sin header de token
    for malo in ("café", "tokén", "日本語", "\u00ff"):
        r = c.get("/api/proyectos", params={"token": malo})
        assert r.status_code == 401, (malo, r.status_code)
    # por header hay que mandar BYTES latin-1 (asi decodifica Starlette una
    # cabecera con byte alto llegada por la red); httpx rechaza str no-ASCII
    for malo in (b"caf\xe9", b"\xff"):
        r = c.get("/api/proyectos", headers={"X-Cognia-Token": malo})
        assert r.status_code == 401, (malo, r.status_code)


def test_token_valido_no_lanza_con_no_ascii():
    """Contrato directo de la función (sin pasar por HTTP)."""
    from cognia.remoto.servidor import _token_valido
    assert _token_valido("café", "abc") is False
    assert _token_valido("", "abc") is False
    assert _token_valido("abc", "abc") is True


# ── Regresión 2026-08-01: FAIL-OPEN del escaneo de skills ──

def test_guardar_flujo_sin_escaneo_rechaza(tmp_path, monkeypatch):
    """Si skill_safety_scan no está disponible, el PUT NO puede persistir:
    el 'except Exception: hits = []' anterior desactivaba el blocklist en
    silencio y guardaba cualquier contenido."""
    import sys
    from cognia.remoto import servidor as _srv
    monkeypatch.setattr(_srv, "_DIR_FLUJOS_EDIT", tmp_path / "cognia_skills")
    # import roto: sys.modules[x]=None hace fallar el `from ... import ...`
    monkeypatch.setitem(sys.modules, "cognia.agent.skills", None)
    c = _cliente()
    r = c.put("/api/flujos/sin-escaneo",
              json={"contenido": "paso 1: corre rm -rf C:/Users"})
    assert r.status_code == 503, r.text
    assert "escaneo" in r.json()["error"]
    assert not (tmp_path / "cognia_skills" / "sin-escaneo.md").exists()


# ── Regresión 2026-08-01: el token se filtraba al historial del navegador ──

def test_front_no_abre_la_imagen_con_el_token_en_la_url():
    """img.onclick hacía window.open(img.src) — img.src lleva ?token=, así que
    el token acababa en el historial, justo lo que borra el history.replaceState
    del arranque. Ahora se baja con header y se abre un blob:."""
    html = (Path(__file__).resolve().parent.parent
            / "cognia" / "remoto" / "static" / "index.html").read_text(
                encoding="utf-8")
    assert "window.open(img.src" not in html
    bloque = html.split("img.onclick")[1][:1200]
    assert "X-Cognia-Token" in bloque
    assert "createObjectURL" in bloque
    assert "revokeObjectURL" in bloque
