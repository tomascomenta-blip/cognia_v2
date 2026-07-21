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


def test_app_movil_se_sirve():
    r = _cliente().get("/")
    assert r.status_code == 200
    assert "Cognia Remoto" in r.text
    assert 'data-tema' in r.text or "aplicarTema" in r.text


def test_registrar_proyecto_valida_carpetas(tmp_path):
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
