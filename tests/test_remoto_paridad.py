"""
Paridad del control remoto con el REPL local (contrato 2026-08-24), lado
SERVIDOR: cognia/remoto/{servidor,sesiones,__main__}.py.

Cada bloque fija una letra del contrato y falla sin su cambio:

  A  interrumpir: el hijo nace en su propio grupo de proceso y recibe
     CTRL_BREAK_EVENT (SIGINT en POSIX). Probado con un hijo python REAL que
     instala el handler de SIGBREAK y escribe "INTERRUMPIDO" — no con mocks.
  B  multilinea: N lineas del textarea -> UNA entrada del REPL, construida
     como la continuacion oficial de cli.py (replica vigilada contra la
     fuente real del REPL).
  C  streaming: TokenTexto se agrupa en "delta" (120 ms / 80 chars, reloj
     inyectable) y va SOLO a los suscriptores, nunca al jsonl.
  D  Confianza y FooterTurno tipados -> "confianza"/"footer" con sus campos.
  F  /ficheros (prefijo, sin escape, sin venv/.git) y /subir (415, 413,
     nombre saneado, imagenes/ vs adjuntos/).
  G  --host/--port por CLI y env, CORS sin "*", 413 en /mensaje, 429 tras 10
     fallos de token, sid unico, .pid persistido + reconciliacion que MATA un
     huerfano real, --limpiar con --dry-run, /api/version.

TODOS los tests parchean RAIZ_DATOS a tmp_path: hoy hay 1154 carpetas
huerfanas en ~/.cognia/remoto de tests que no lo hicieron.
"""

import inspect
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cognia.remoto import servidor as _srv
from cognia.remoto import sesiones as _ses
from cognia.remoto.sesiones import (AgrupadorDelta, ColaSuscriptor,
                                    GestorSesiones, Sesion, a_entrada_repl,
                                    entradas_para_repl, extra_de_evento,
                                    interpretar_evento, lineas_continuacion,
                                    parsear_evento, registrar_proyecto,
                                    unir_continuacion_oficial)


# ── utilidades ─────────────────────────────────────────────────────────────

def _ev(tipo: str, **campos) -> str:
    return "@EV " + json.dumps({"tipo": tipo, "ts": 0.0, **campos},
                               ensure_ascii=False)


def _aislar(tmp_path, monkeypatch):
    """RAIZ_DATOS/proyectos a tmp: nada toca ~/.cognia/remoto."""
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", tmp_path / "proyectos.json")
    proyecto = tmp_path / "proy"
    proyecto.mkdir(exist_ok=True)
    return registrar_proyecto(str(proyecto))


def _cliente(tmp_path, **kw) -> TestClient:
    c = TestClient(_srv.crear_app(**kw))
    c.headers.update({"X-Cognia-Token": _srv.asegurar_token(tmp_path)})
    return c


def _sesion(tmp_path, monkeypatch) -> Sesion:
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    s = Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
               titulo="t")
    s._arrancando = False
    return s


def _lineas(s: Sesion) -> list[dict]:
    if not s.fichero.exists():
        return []
    return [json.loads(l)
            for l in s.fichero.read_text(encoding="utf-8").splitlines()]


# REPL falso que SOBREVIVE a la senal de interrupcion: instala el handler
# (como hara cli.py bajo COGNIA_REMOTO), escribe INTERRUMPIDO al recibirla y
# hace eco de cada linea. Sin el handler, CTRL_BREAK lo mataria (default de
# Windows) — eso es justo lo que el test de abajo distingue.
_GUION_REPL_INTERRUMPIBLE = (
    "import signal, sys\n"
    "def h(sig, frm):\n"
    "    print('INTERRUMPIDO', flush=True)\n"
    "signal.signal(getattr(signal, 'SIGBREAK', signal.SIGINT), h)\n"
    "print('/ayuda para comandos', flush=True)\n"     # cierra el gate
    "for l in sys.stdin:\n"
    "    if l.strip() == '/salir':\n"
    "        break\n"
    "    print('eco: ' + l.strip(), flush=True)\n")


def _repl_interrumpible():
    return [sys.executable, "-c", _GUION_REPL_INTERRUMPIBLE]


def _repl_eco():
    return [sys.executable, "-c",
            "import sys\n"
            "print('/ayuda para comandos', flush=True)\n"
            "for l in sys.stdin:\n"
            "    if l.strip() == '/salir':\n"
            "        break\n"
            "    print('eco: ' + l.strip(), flush=True)\n"]


def _esperar(cond, timeout=8.0, paso=0.05):
    fin = time.time() + timeout
    while time.time() < fin:
        if cond():
            return True
        time.sleep(paso)
    return cond()


# ═══ A. INTERRUMPIR ═══════════════════════════════════════════════════════

def test_A_ctrl_break_llega_a_un_hijo_real_en_grupo_propio():
    """Prueba REAL del mecanismo, sin Sesion: un python hijo con
    CREATE_NEW_PROCESS_GROUP (start_new_session en POSIX) instala el handler
    de SIGBREAK y escribe INTERRUMPIDO al recibir send_signal(_SENAL)."""
    guion = ("import signal, sys, time\n"
             "def h(sig, frm):\n"
             "    print('INTERRUMPIDO', flush=True); raise KeyboardInterrupt\n"
             "signal.signal(getattr(signal, 'SIGBREAK', signal.SIGINT), h)\n"
             "print('LISTO', flush=True)\n"
             "try:\n"
             "    for _ in range(100000):\n"       # bucle de bytecode: como
             "        time.sleep(0.001)\n"          # un stream de tokens
             "except KeyboardInterrupt:\n"
             "    print('KI', flush=True)\n")
    p = subprocess.Popen([sys.executable, "-c", guion],
                         stdout=subprocess.PIPE, text=True,
                         **_ses._flags_grupo_propio())
    try:
        assert p.stdout.readline().strip() == "LISTO"
        t0 = time.time()
        p.send_signal(_ses._SENAL_INTERRUPCION)
        assert p.stdout.readline().strip() == "INTERRUMPIDO"
        assert p.stdout.readline().strip() == "KI"
        assert time.time() - t0 < 5.0
        assert p.wait(timeout=5) == 0     # SOBREVIVIO a la senal y termino bien
    finally:
        if p.poll() is None:
            p.kill()


def test_A_la_senal_no_toca_al_padre_ni_a_otros_hijos(tmp_path, monkeypatch):
    """Dos sesiones vivas: interrumpir una deja intacta a la otra y al
    servidor (el grupo propio es lo que lo garantiza)."""
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_interrumpible)
    g = GestorSesiones()
    a = g.crear(pr, "a")
    b = g.crear(pr, "b")
    assert a.id != b.id
    assert _esperar(lambda: not a._arrancando and not b._arrancando)
    r = a.interrumpir()
    assert r == {"ok": True, "motivo": _ses.MOTIVO_INTERRUPCION_ENVIADA}
    # el motivo dice el LIMITE (hallazgo 9, 2026-08-25): la senal se aplica
    # al volver la llamada bloqueada, y el front lo pinta tal cual
    assert "al terminar la llamada en curso" in r["motivo"]
    # el handler del hijo corre en su hilo principal, que esta bloqueado en
    # stdin: se despierta con la siguiente linea (misma limitacion que un
    # REPL idle; una generacion en curso lo ejecuta al siguiente token)
    a.enviar("ping"); b.enviar("ping")
    assert _esperar(lambda: any(l["texto"] == "INTERRUMPIDO"
                                for l in _lineas(a)))
    assert _esperar(lambda: any(l["texto"] == "eco: ping"
                                for l in _lineas(b)))
    assert not any(l["texto"] == "INTERRUMPIDO" for l in _lineas(b))
    assert a.viva() and b.viva()
    assert any("interrupcion enviada al REPL" in l["texto"]
               for l in _lineas(a) if l["quien"] == "sistema")
    a.parar(); b.parar()


def test_A_endpoint_interrumpir_contrato(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_interrumpible)
    c = _cliente(tmp_path)
    # sesion desconocida: ok=False con motivo, no 500
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/nadie/interrumpir")
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["motivo"]
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones",
                 json={"titulo": "t", "acceso": "restringido"}).json()["id"]
    s = c.app.state.gestor._sesiones[sid]
    # mientras ARRANCA (sin handler instalado todavia) se rechaza: la senal
    # lo mataria — medido: el REPL moria y enviar() lo re-arrancaba mudo
    if s._arrancando:
        r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/interrumpir").json()
        assert r["ok"] is False and "arrancando" in r["motivo"]
    assert _esperar(lambda: not s._arrancando)
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/interrumpir").json()
    assert r == {"ok": True, "motivo": _ses.MOTIVO_INTERRUPCION_ENVIADA}
    c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/mensaje",
           json={"texto": "sigo vivo"})
    tr = lambda: c.get(
        f"/api/proyectos/{pr['id']}/sesiones/{sid}/transcripcion").json()
    assert _esperar(lambda: any(l["texto"] == "eco: sigo vivo" for l in tr()))
    assert any(l["texto"] == "INTERRUMPIDO" for l in tr())
    c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/parar")
    # parada: ok=False, motivo legible
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/interrumpir").json()
    assert r["ok"] is False and "viva" in r["motivo"]


# ═══ B. MULTILINEA ════════════════════════════════════════════════════════

def test_B_el_protocolo_lo_lee_la_funcion_REAL_del_repl(monkeypatch):
    """Contra cognia.cli._leer_con_continuacion, la funcion que la rama
    input() pelado usa desde la paridad: las lineas que manda el servidor
    (lineas_continuacion) se leen como UNA entrada, con sus saltos bajo
    COGNIA_REMOTO (separador "\n") y unidas con " " fuera de el."""
    import cognia.cli as cli
    assert _ses.repl_soporta_continuacion() is True
    # sin linea vacia: esa la mide test_B_lineas_vacias_y_barra_final...
    texto = "def f():\n    return 1\nprint(f())"
    lineas = lineas_continuacion(texto)
    assert lineas == ["def f(): \\", "    return 1 \\", "print(f())"]

    def leer_desde(cola):
        def leer():
            if not cola:
                raise EOFError
            return cola.pop(0)
        return leer

    # bajo remoto: la primera linea llega .strip() (input() del REPL), el
    # resto por leer(); los saltos se conservan y la sangria tambien
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    entrada = cli._leer_con_continuacion(
        lineas[0].strip(), leer_desde(lineas[1:]),
        cli._separador_continuacion_simple())
    assert entrada == "def f():\n    return 1\nprint(f())"
    # fuera del remoto (terminal con stdin en pipe): une con " ", como el
    # prompt rico, y coincide con la replica de sesiones.py
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    entrada = cli._leer_con_continuacion(
        lineas[0].strip(), leer_desde(lineas[1:]),
        cli._separador_continuacion_simple())
    assert entrada == a_entrada_repl(texto) == "def f(): return 1 print(f())"
    # y la replica clasica sigue siendo la expresion del prompt rico
    fuente = inspect.getsource(cli)
    assert 'line = line[:-1].rstrip() + " " + continuation' in fuente


def test_B_modo_por_defecto_es_continuacion_si_el_repl_la_soporta(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO_MULTILINEA", raising=False)
    assert _ses.modo_multilinea() == "continuacion"
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "unir")
    assert _ses.modo_multilinea() == "unir"
    assert entradas_para_repl("a\nb") == ["a b"]
    # un REPL sin soporte (cache forzada) cae a "unir" solo
    monkeypatch.delenv("COGNIA_REMOTO_MULTILINEA", raising=False)
    monkeypatch.setattr(_ses, "_SOPORTE_CONTINUACION", [False])
    assert _ses.modo_multilinea() == "unir"


def test_B_lineas_continuacion_y_union():
    assert lineas_continuacion("a\nb\nc") == ["a \\", "b \\", "c"]
    assert lineas_continuacion("solo") == ["solo"]
    assert lineas_continuacion("\n\n") == []
    # las vacias INTERIORES viajan (una continuacion vacia); las de los
    # extremos no dicen nada (hallazgo rev1 2026-08-25: un bloque de codigo
    # pegado perdia sus lineas en blanco)
    assert lineas_continuacion("a\n\n  \nb") == ["a \\", " \\", " \\", "b"]
    assert lineas_continuacion("\n\na\nb\n\n") == ["a \\", "b"]
    # lo que el bucle oficial construye con esas lineas:
    assert unir_continuacion_oficial(["a \\", "b \\", "c"]) == "a b c"
    assert unir_continuacion_oficial(["x \\"]) == "x "
    assert a_entrada_repl("def f():\n    return 1\nprint(f())") == \
        "def f(): return 1 print(f())"


def test_B_entradas_para_repl_segun_modo(monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "unir")
    assert entradas_para_repl("hola") == ["hola"]
    assert entradas_para_repl("a\nb\nc") == ["a b c"]
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "continuacion")
    assert entradas_para_repl("hola") == ["hola"]
    assert entradas_para_repl("a\nb\nc") == ["a \\", "b \\", "c"]
    # BARRA FINAL (ruta Windows): se cierra con " \\" + linea vacia en los
    # dos modos y en el mensaje de una sola linea; antes el REPL se quedaba
    # esperando continuacion y el siguiente mensaje se pegaba a este
    assert entradas_para_repl("C:\\Users\\") == ["C:\\Users\\ \\", ""]
    assert entradas_para_repl("mira\nC:\\Users\\") == ["mira \\", "C:\\Users\\ \\", ""]
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "unir")
    assert entradas_para_repl("mira\nC:\\Users\\") == ["mira C:\\Users\\ \\", ""]
    assert _ses.cerrar_barra_final(["a", "b"]) == ["a", "b"]
    assert _ses.cerrar_barra_final(_ses.cerrar_barra_final(["x\\"])) == ["x\\ \\", ""]


def test_B_lineas_vacias_y_barra_final_contra_la_funcion_REAL_del_repl(
        monkeypatch):
    """Lo que el REPL construye de verdad (cli._leer_con_continuacion, con
    la primera linea .strip() como hace input()) a partir de lo que el
    servidor manda. La barra final es asunto del servidor y se mide en
    verde; las lineas vacias dependen de cli._unir_continuacion (su
    `acumulado[:-1].rstrip()` recorta el "\n" que precede a la vacia): si
    cli.py aun no la conserva, se marca xfail con el motivo — y en cuanto
    la conserve el test lo exige."""
    import cognia.cli as cli
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "continuacion")
    sep = cli._separador_continuacion_simple()
    assert sep == "\n"

    def leer_desde(cola):
        def leer():
            if not cola:
                raise EOFError
            return cola.pop(0)
        return leer

    def repl_lee(texto):
        ent = entradas_para_repl(texto)
        # el REPL: input().strip() para la primera y el resto por leer();
        # el resultado pasa por el strip del bucle antes de despachar
        return cli._leer_con_continuacion(ent[0].strip(), leer_desde(ent[1:]),
                                          sep).strip()

    # barra final, con y sin lineas antes: la ruta llega ENTERA y el REPL
    # no queda esperando (la lista se agoto: leer() no vuelve a llamarse)
    assert repl_lee("C:\\Users\\") == "C:\\Users\\"
    assert repl_lee("mira esta ruta:\nC:\\Users\\") == "mira esta ruta:\nC:\\Users\\"
    # sangria de las lineas de continuacion: se conserva
    assert repl_lee("def f():\n    return 1") == "def f():\n    return 1"
    # LINEA VACIA interior (bloque de codigo pegado)
    texto = "def f():\n    x = 1\n\n    return x\nfin"
    leido = repl_lee(texto)
    if leido != texto:
        assert leido == "def f():\n    x = 1\n    return x\nfin"
        pytest.xfail("cli._unir_continuacion aplasta la linea vacia "
                     "(acumulado[:-1].rstrip() recorta el '\\n'): pendiente "
                     "del agente cli — el servidor ya la manda como ' \\'")
    assert leido == texto


def test_B_un_mensaje_de_tres_lineas_es_UNA_entrada_del_repl(tmp_path,
                                                            monkeypatch):
    """Contra un REPL (falso) que hace eco por LINEA leida y NO soporta la
    continuacion (modo "unir"): tres lineas del textarea producen UN eco.
    Antes: tres."""
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "unir")
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_eco)
    c = _cliente(tmp_path)
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones",
                 json={"titulo": "t"}).json()["id"]
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/mensaje",
               json={"texto": "linea uno\n/ayuda\nlinea tres"}).json()
    assert r == {"ok": True, "entradas": 1}
    tr = lambda: c.get(
        f"/api/proyectos/{pr['id']}/sesiones/{sid}/transcripcion").json()
    assert _esperar(lambda: any(l["texto"].startswith("eco:") for l in tr()))
    ecos = [l["texto"] for l in tr() if l["texto"].startswith("eco:")]
    assert ecos == ["eco: linea uno /ayuda linea tres"]
    # la transcripcion guarda lo que el usuario ESCRIBIO, con sus saltos
    assert [l["texto"] for l in tr() if l["quien"] == "usuario"] == \
        ["linea uno\n/ayuda\nlinea tres"]
    c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/parar")


def _repl_con_continuacion():
    """REPL falso que implementa el bucle REAL de cli._leer_con_continuacion
    (mismo codigo, copiado) con separador "\n": eco de cada ENTRADA."""
    return [sys.executable, "-c",
            "import sys\n"
            "print('/ayuda para comandos', flush=True)\n"
            "def leer():\n"
            "    l = sys.stdin.readline()\n"
            "    if not l: raise EOFError\n"
            "    return l.rstrip('\\n')\n"
            "while True:\n"
            "    try: linea = leer().strip()\n"
            "    except EOFError: break\n"
            "    if linea == '/salir': break\n"
            "    while linea.endswith('\\\\'):\n"
            "        try: sig = leer().rstrip()\n"
            "        except EOFError: linea = linea[:-1].rstrip(); break\n"
            "        linea = linea[:-1].rstrip() + '\\n' + sig\n"
            "    print('ENTRADA ' + repr(linea), flush=True)\n"]


def test_B_tres_lineas_con_el_protocolo_llegan_con_sus_saltos(tmp_path,
                                                             monkeypatch):
    """Modo "continuacion" (el default con el REPL de hoy): la entrada es UNA
    y conserva los saltos y la sangria del textarea."""
    monkeypatch.setenv("COGNIA_REMOTO_MULTILINEA", "continuacion")
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_con_continuacion)
    c = _cliente(tmp_path)
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones",
                 json={"titulo": "t"}).json()["id"]
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/mensaje",
               json={"texto": "def f():\n    return 1\nprint(f())"}).json()
    assert r == {"ok": True, "entradas": 3}
    tr = lambda: c.get(
        f"/api/proyectos/{pr['id']}/sesiones/{sid}/transcripcion").json()
    assert _esperar(lambda: any(l["texto"].startswith("ENTRADA") for l in tr()))
    entradas = [l["texto"] for l in tr() if l["texto"].startswith("ENTRADA")]
    assert entradas == ["ENTRADA 'def f():\\n    return 1\\nprint(f())'"]
    # el caso limite del protocolo se CIERRA (antes solo se avisaba y el
    # siguiente mensaje se pegaba): la ruta llega entera con su barra y el
    # REPL despacha la entrada sin esperar a la siguiente
    r = c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/mensaje",
               json={"texto": "C:\\dir\\"}).json()
    assert r == {"ok": True, "entradas": 2}
    assert _esperar(lambda: "ENTRADA 'C:\\\\dir\\\\\\n'" in
                    [l["texto"] for l in tr()])
    assert not any("termina en" in l["texto"] for l in tr())
    # y con lineas antes, incluida una VACIA (el servidor la manda; que el
    # REPL real la conserve es de cli._unir_continuacion — este falso la
    # aplasta igual que el real de hoy: se mide lo que manda el servidor)
    c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/mensaje",
           json={"texto": "ruta:\n\nC:\\dir\\"})
    assert _esperar(lambda: any(l["texto"].startswith("ENTRADA 'ruta:")
                                for l in tr()))
    ent = [l["texto"] for l in tr() if l["texto"].startswith("ENTRADA 'ruta:")]
    assert ent[0].endswith("C:\\\\dir\\\\\\n'"), ent
    c.post(f"/api/proyectos/{pr['id']}/sesiones/{sid}/parar")


# ═══ C. STREAMING: delta ══════════════════════════════════════════════════

def test_C_agrupador_cierra_por_chars_o_por_tiempo():
    reloj = [0.0]
    trozos = []
    ag = AgrupadorDelta(trozos.append, reloj=lambda: reloj[0],
                        max_chars=80, max_ms=120)
    for _ in range(7):
        ag.token("0123456789")        # 70 chars: no cierra
    assert trozos == [] and ag.pendiente() == 70
    ag.token("0123456789")            # 80: cierra por chars
    assert trozos == ["0123456789" * 8]
    ag.token("hola")
    reloj[0] = 0.119
    ag.token(" ")
    assert len(trozos) == 1           # 119 ms: todavia no
    reloj[0] = 0.120
    ag.token("mundo")                 # 120 ms desde el primer token: cierra
    assert trozos[1] == "hola mundo"
    ag.token("resto"); ag.vaciar()
    assert trozos[2] == "resto"
    ag.vaciar()                       # vacio: no emite nada
    assert len(trozos) == 3


def test_C_los_delta_van_a_los_suscriptores_y_NO_al_jsonl(tmp_path,
                                                          monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    q = ColaSuscriptor()
    s.suscriptores.append(q)
    reloj = [0.0]
    s._delta = AgrupadorDelta(s._emitir_delta, reloj=lambda: reloj[0])
    for tok in ("¡Hola", "!", " ¿En", " qué"):
        s._procesar_linea(_ev("TokenTexto", texto=tok))
    assert len(q) == 0                 # 12 chars, 0 ms: aun en el buffer
    reloj[0] = 1.0
    s._procesar_linea(_ev("TokenTexto", texto=" puedo"))
    d = q.get(timeout=0.1)
    assert d["quien"] == "delta" and d["texto"] == "¡Hola! ¿En qué puedo"
    # otro evento cierra el residuo ANTES de anotarse (orden de stdout)
    s._procesar_linea(_ev("TokenTexto", texto=" ayudarte?"))
    s._procesar_linea(_ev("TareaFin", ok=True, pasos=1))
    assert q.get(timeout=0.1)["texto"] == " ayudarte?"
    assert q.get(timeout=0.1)["quien"] == "actividad"
    # la prosa final tambien vacia primero y llega como "cognia"
    s._procesar_linea(_ev("TokenTexto", texto="x"))
    s._procesar_linea("¡Hola! ¿En qué puedo ayudarte?")
    assert q.get(timeout=0.1)["texto"] == "x"
    assert q.get(timeout=0.1)["quien"] == "cognia"
    # y el jsonl NO tiene ni un delta: la transcripcion es la respuesta final
    quienes = [l["quien"] for l in _lineas(s)]
    assert "delta" not in quienes
    assert quienes == ["actividad", "cognia"]


def test_C_interpretar_sigue_sin_anotar_tokentexto():
    """El contrato viejo se conserva: interpretar_evento no anota TokenTexto
    (el delta es un canal aparte, de _procesar_linea)."""
    assert interpretar_evento({"tipo": "TokenTexto", "texto": "x"})[0] is None


# ═══ D. CONFIANZA y FOOTER ════════════════════════════════════════════════

def test_D_tipos_nuevos_en_la_allowlist():
    for tipo in ("Confianza", "FooterTurno"):
        assert tipo in _ses._TIPOS_EVENTO
        assert parsear_evento(json.dumps({"tipo": tipo}))["tipo"] == tipo


def test_D_confianza_es_chip_con_nivel_y_fuentes(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_ev("Confianza", nivel="alta", glifo="●", valor=0.9,
                          fuentes=["docs.python.org", "peps.python.org"],
                          texto="● confianza ALTA (0,90) · 2 fuentes"))
    (l,) = _lineas(s)
    assert l["quien"] == "confianza"
    assert l["texto"] == "● confianza ALTA (0,90) · 2 fuentes"
    assert l["nivel"] == "alta" and l["valor"] == 0.9
    assert l["fuentes"] == ["docs.python.org", "peps.python.org"]
    # el renderer local (si pintara la misma linea) no la duplica en el chat
    s._procesar_linea("● confianza ALTA (0,90) · 2 fuentes")
    assert len(_lineas(s)) == 1
    # sin texto: se arma con glifo y nivel
    quien, texto, _ = interpretar_evento(
        {"tipo": "Confianza", "nivel": "baja", "glifo": "○"})
    assert (quien, texto) == ("confianza", "○ confianza baja")


def test_D_footer_del_turno_linea_gris(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea(_ev("FooterTurno", ok=True, segundos=14.6, tokens=312,
                          ctx_libre_pct=95.0))
    (l,) = _lineas(s)
    assert l["quien"] == "footer"
    assert l["texto"] == "✓ 14.6s · 312 tokens · ctx 95% libre"
    assert l["ok"] is True and l["tokens"] == 312 and l["segundos"] == 14.6
    # el footer PLANO del renderer sigue descartandose como eco
    s._procesar_linea("14.6s · 312 tokens")
    assert len(_lineas(s)) == 1
    # sin ctx (None = no se sabe): no se inventa un 0; con fallo, el motivo
    quien, texto, _ = interpretar_evento(
        {"tipo": "FooterTurno", "ok": False, "segundos": 2.0, "tokens": 0,
         "motivo": "interrumpido"})
    assert (quien, texto) == ("footer", "✗ 2.0s — interrumpido")
    assert extra_de_evento({"tipo": "FooterTurno"})["ctx_libre_pct"] is None
    assert extra_de_evento({"tipo": "ToolFin"}) == {}


# ═══ F. FICHEROS y SUBIDA ═════════════════════════════════════════════════

def _proyecto_con_ficheros(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    raiz = Path(pr["ruta"])
    (raiz / "src").mkdir()
    (raiz / "src" / "main.py").write_text("x", encoding="utf-8")
    (raiz / "src" / "util.py").write_text("x", encoding="utf-8")
    (raiz / "README.md").write_text("x", encoding="utf-8")
    (raiz / ".git").mkdir(); (raiz / ".git" / "HEAD").write_text("ref")
    (raiz / "venv").mkdir(); (raiz / "venv" / "pyvenv.cfg").write_text("v")
    (raiz / "node_modules").mkdir()
    (raiz / "node_modules" / "x.js").write_text("j")
    # un fichero FUERA del proyecto: nunca debe listarse
    (tmp_path / "secreto.txt").write_text("s", encoding="utf-8")
    return pr


def test_F_ficheros_por_prefijo_sin_ruido_y_sin_escape(tmp_path, monkeypatch):
    pr = _proyecto_con_ficheros(tmp_path, monkeypatch)
    c = _cliente(tmp_path)
    url = f"/api/proyectos/{pr['id']}/ficheros"
    todos = c.get(url).json()["items"]
    assert set(todos) == {"README.md", "src/main.py", "src/util.py"}
    assert c.get(url, params={"q": "src/m"}).json()["items"] == ["src/main.py"]
    # el prefijo tambien vale por NOMBRE (el movil escribe "@main")
    assert c.get(url, params={"q": "MAIN"}).json()["items"] == ["src/main.py"]
    # intentos de escapar: nada de fuera de la raiz
    for q in ("../", "../secreto", "..\\secreto.txt", "/", "C:/"):
        assert c.get(url, params={"q": q}).json()["items"] == [], q
    # proyecto desconocido -> 404 legible, no 500 mudo
    r = c.get("/api/proyectos/nope/ficheros")
    assert r.status_code == 404 and "nope" in r.json()["detail"]


def test_F_ficheros_excluye_solo_git_exacto_no_github(tmp_path, monkeypatch):
    """`.github/workflows/ci.yml` se mencionaba desde el movil y no salia:
    el filtro era startswith('.git') (hallazgo rev2 2026-08-25)."""
    pr = _proyecto_con_ficheros(tmp_path, monkeypatch)
    raiz = Path(pr["ruta"])
    (raiz / ".github" / "workflows").mkdir(parents=True)
    (raiz / ".github" / "workflows" / "ci.yml").write_text("on: push")
    (raiz / ".gitignore").write_text("venv/")
    items = _srv._listar_ficheros(raiz, "")
    assert ".github/workflows/ci.yml" in items and ".gitignore" in items
    assert not any(i.startswith(".git/") for i in items)
    assert _srv._listar_ficheros(raiz, ".github/w") == [".github/workflows/ci.yml"]


def test_F_subir_413_por_content_length_ANTES_de_parsear_el_multipart(
        tmp_path, monkeypatch):
    """Un POST cuyo Content-Length supera MAX_CUERPO_SUBIDA se rechaza en el
    middleware, sin que starlette llegue a spoolear el multipart (se vigila
    el parser real: si se llama, el test falla). Es la unica defensa que
    corta antes de recibir; el tope del endpoint actua sobre el temporal ya
    escrito (hallazgo rev1 2026-08-25)."""
    import starlette.formparsers as fp
    pr = _aislar(tmp_path, monkeypatch)
    c = _cliente(tmp_path)

    def parse_prohibido(self):
        raise AssertionError("el multipart se parseo pese al Content-Length")
    monkeypatch.setattr(fp.MultiPartParser, "parse", parse_prohibido)
    r = c.post(f"/api/proyectos/{pr['id']}/subir",
               headers={"Content-Length": str(_srv.MAX_CUERPO_SUBIDA + 1)},
               files={"archivo": ("x.txt", b"x", "text/plain")})
    assert r.status_code == 413 and "envoltorio" in r.json()["error"]
    assert not (Path(pr["ruta"]) / "adjuntos").exists()
    # sin la cabecera desmedida, el parser SI corre (y el tope del endpoint
    # sigue actuando sobre lo spooleado: test_F_subir_extension_prohibida...)
    monkeypatch.undo()
    pr = _aislar(tmp_path, monkeypatch)
    c = _cliente(tmp_path)
    assert _subir(c, pr["id"], "ok.txt", b"hola").status_code == 200


def test_F_ficheros_tope_30(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    raiz = Path(pr["ruta"])
    for i in range(45):
        (raiz / f"f{i:03d}.txt").write_text("x")
    items = _srv._listar_ficheros(raiz, "f")
    assert len(items) == 30 and items[0] == "f000.txt"


def _subir(c, pid, nombre, datos: bytes, tipo="application/octet-stream"):
    return c.post(f"/api/proyectos/{pid}/subir",
                  files={"archivo": (nombre, datos, tipo)})


def test_F_subir_imagen_y_adjunto(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    c = _cliente(tmp_path)
    r = _subir(c, pr["id"], "foto.png", b"\x89PNG....", "image/png")
    assert r.status_code == 200, r.text
    assert r.json() == {"ruta": "imagenes/foto.png",
                        "mencion": "@imagenes/foto.png", "bytes": 8}
    assert (Path(pr["ruta"]) / "imagenes" / "foto.png").read_bytes() == \
        b"\x89PNG...."
    # misma foto otra vez: no pisa, sufija
    assert _subir(c, pr["id"], "foto.png", b"2").json()["ruta"] == \
        "imagenes/foto-2.png"
    r = _subir(c, pr["id"], "notas.md", b"# hola").json()
    assert r["ruta"] == "adjuntos/notas.md" and r["mencion"] == "@adjuntos/notas.md"
    # nombre con ruta: solo el basename, dentro del proyecto
    r = _subir(c, pr["id"], "../../evil.txt", b"x").json()
    assert r["ruta"] == "adjuntos/evil.txt"
    assert not (tmp_path / "evil.txt").exists()


def test_F_subir_extension_prohibida_415_y_tope_413(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    c = _cliente(tmp_path)
    r = _subir(c, pr["id"], "virus.exe", b"MZ")
    assert r.status_code == 415 and ".exe" in r.json()["error"]
    assert _subir(c, pr["id"], "sinext", b"x").status_code == 415
    assert not (Path(pr["ruta"]) / "adjuntos").exists()
    monkeypatch.setattr(_srv, "MAX_SUBIDA", 1000)
    r = _subir(c, pr["id"], "grande.txt", b"x" * 1001)
    assert r.status_code == 413 and "tope 1000" in r.json()["error"]
    assert not (Path(pr["ruta"]) / "adjuntos" / "grande.txt").exists()
    assert _subir(c, pr["id"], "justo.txt", b"x" * 1000).status_code == 200


# ═══ G. SEGURIDAD y ROBUSTEZ ══════════════════════════════════════════════

def test_G_host_y_port_por_cli_y_por_env(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO_HOST", raising=False)
    monkeypatch.delenv("COGNIA_REMOTO_PORT", raising=False)
    a = _srv.parsear_args([])
    assert (a.host, a.port, a.limpiar, a.dry_run) == ("0.0.0.0", 8777,
                                                      False, False)
    a = _srv.parsear_args(["--host", "10.0.0.7", "--port", "9001"])
    assert (a.host, a.port) == ("10.0.0.7", 9001)
    monkeypatch.setenv("COGNIA_REMOTO_HOST", "127.0.0.1")
    monkeypatch.setenv("COGNIA_REMOTO_PORT", "8790")
    a = _srv.parsear_args([])
    assert (a.host, a.port) == ("127.0.0.1", 8790)
    # la CLI gana al env
    assert _srv.parsear_args(["--port", "1"]).port == 1
    a = _srv.parsear_args(["--limpiar", "--dry-run"])
    assert a.limpiar and a.dry_run
    # el __main__ pasa argv de verdad al parser
    fuente = (Path(_srv.__file__).parent / "__main__.py").read_text("utf-8")
    assert "main(sys.argv[1:])" in fuente


def test_G_cors_solo_el_propio_origen_y_nunca_estrella(tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_srv, "_ip_lan", lambda: "192.168.1.50")
    origenes = _srv._origenes_permitidos("0.0.0.0", 8790)
    assert origenes == ["https://192.168.1.50:8790", "https://127.0.0.1:8790",
                        "https://localhost:8790"]
    assert "*" not in origenes
    c = _cliente(tmp_path, host="0.0.0.0", port=8790)
    propio = c.get("/api/version",
                   headers={"Origin": "https://192.168.1.50:8790"})
    assert propio.headers.get("access-control-allow-origin") == \
        "https://192.168.1.50:8790"
    ajeno = c.get("/api/version", headers={"Origin": "https://evil.lan"})
    assert "access-control-allow-origin" not in ajeno.headers
    pre = c.options("/api/version",
                    headers={"Origin": "https://evil.lan",
                             "Access-Control-Request-Method": "GET"})
    assert pre.headers.get("access-control-allow-origin") != "*"
    assert "evil.lan" not in pre.headers.get("access-control-allow-origin", "")


def test_G_mensaje_grande_413(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_srv, "MAX_BODY_MENSAJE", 2000)
    arrancados = []
    monkeypatch.setattr(Sesion, "enviar",
                        lambda self, texto: arrancados.append(texto))
    c = _cliente(tmp_path)
    url = f"/api/proyectos/{pr['id']}/sesiones/s1/mensaje"
    r = c.post(url, json={"texto": "x" * 2500})
    assert r.status_code == 413 and "tope 2000" in r.json()["error"]
    # sin Content-Length fiable tambien: el endpoint mide lo leido
    r = c.post(url, content=json.dumps({"texto": "x" * 2500}).encode(),
               headers={"Content-Type": "application/json",
                        "Content-Length": "10"})
    assert r.status_code in (400, 413)
    assert arrancados == []          # nada llego al REPL
    assert c.post(url, json={"texto": "corto"}).json()["ok"] is True
    assert arrancados == ["corto"]
    # JSON roto: 400 legible, no 500
    r = c.post(url, content=b"{no json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_G_limitador_de_auth_con_reloj_inyectado():
    reloj = [100.0]
    lim = _srv.LimitadorAuth(max_fallos=10, ventana_s=60, bloqueo_s=60,
                             reloj=lambda: reloj[0])
    for i in range(9):
        assert lim.fallo("1.2.3.4") is False
    assert lim.bloqueada("1.2.3.4") == 0
    assert lim.fallo("1.2.3.4") is True          # el decimo bloquea
    assert 59 < lim.bloqueada("1.2.3.4") <= 60
    assert lim.bloqueada("5.6.7.8") == 0         # por IP
    reloj[0] += 59.9
    assert lim.bloqueada("1.2.3.4") > 0
    reloj[0] += 0.2
    assert lim.bloqueada("1.2.3.4") == 0         # expiro y se limpio
    # fallos viejos fuera de la ventana no cuentan
    for i in range(9):
        lim.fallo("9.9.9.9")
    reloj[0] += 61
    assert lim.fallo("9.9.9.9") is False


def test_G_429_tras_10_fallos_de_token(tmp_path, monkeypatch):
    """El bloqueo aplica a las peticiones SIN token valido; el token bueno
    pasa aunque su IP este bloqueada (hallazgo rev1 2026-08-25: la PWA con
    un token viejo dejaba fuera un minuto al dueno con el token nuevo)."""
    from starlette.websockets import WebSocketDisconnect
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_eco)
    app = _srv.crear_app()
    c = TestClient(app)
    tok = _srv.asegurar_token(tmp_path)
    for i in range(10):
        assert c.get("/api/version", headers={"X-Cognia-Token": "no"}).status_code == 401
    r = c.get("/api/version", headers={"X-Cognia-Token": "no"})
    assert r.status_code == 429 and r.headers.get("retry-after")
    assert "espera" in r.json()["error"]
    # con el token BUENO: 200 (10 fallos previos no bloquean al legitimo)
    assert c.get("/api/version", headers={"X-Cognia-Token": tok}).status_code == 200
    # el bloqueo sigue para los malos: un intento mas ni se evalua
    assert c.get("/api/version", headers={"X-Cognia-Token": "no"}).status_code == 429
    # WS: con token bueno CONECTA; con malo, 4429 con el reason
    sid = c.post(f"/api/proyectos/{pr['id']}/sesiones", json={"titulo": "t"},
                 headers={"X-Cognia-Token": tok}).json()["id"]
    with c.websocket_connect(f"/ws/{pr['id']}/{sid}?token={tok}") as ws:
        ws.close()
    with pytest.raises(WebSocketDisconnect) as ex:
        with c.websocket_connect(f"/ws/{pr['id']}/{sid}?token=no"):
            pass
    assert ex.value.code == 4429 and "espera" in (ex.value.reason or "")
    app.state.gestor.parar_sesion(sid)
    # pasado el bloqueo (reloj del limitador adelantado), el malo vuelve a
    # 401 (cuenta de nuevo) en vez de 429
    lim = app.state.limitador
    lim._reloj = lambda: time.monotonic() + 61
    assert c.get("/api/version", headers={"X-Cognia-Token": "no"}).status_code == 401


def test_G_sid_unico_en_el_mismo_segundo(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_eco)
    monkeypatch.setattr(_ses.time, "strftime",
                        lambda fmt, *a: "20260824-120000" if "%Y%m%d" in fmt
                        else "12:00:00")
    g = GestorSesiones()
    a, b, c3 = g.crear(pr, "a"), g.crear(pr, "b"), g.crear(pr, "c")
    assert [a.id, b.id, c3.id] == ["20260824-120000", "20260824-120000-2",
                                   "20260824-120000-3"]
    # cada una tiene SU jsonl con SU titulo (antes la segunda escribia en el
    # de la primera)
    for s, t in ((a, "a"), (b, "b"), (c3, "c")):
        assert json.loads(s.fichero.read_text("utf-8").splitlines()[0])["titulo"] == t
    for s in (a, b, c3):
        s.parar()
    # y un jsonl que ya existia en disco (servidor anterior) tambien cuenta
    (tmp_path / pr["id"] / "20260824-120000-4.jsonl").write_text("{}\n")
    g2 = GestorSesiones()
    d = g2.crear(pr, "d")
    assert d.id == "20260824-120000-5"
    d.parar()


def test_G_pid_persistido_y_borrado_al_terminar(tmp_path, monkeypatch):
    pr = _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_ses, "_python_cognia", _repl_eco)
    g = GestorSesiones()
    s = g.crear(pr, "t")
    f = tmp_path / pr["id"] / f"{s.id}.pid"
    assert f.exists() and int(f.read_text()) == s.proc.pid
    s.parar()
    assert _esperar(lambda: not f.exists())


def _hijo_cognia_falso(tmp_path):
    """Un hijo REAL cuya cmdline es exactamente la del REPL (`python -m
    cognia`): un paquete `cognia` de mentira en tmp_path que duerme, puesto
    por delante en PYTHONPATH. sys.argv no cambia la cmdline que ve psutil;
    esto si."""
    pk = tmp_path / "pkgfalso" / "cognia"
    pk.mkdir(parents=True, exist_ok=True)
    (pk / "__init__.py").write_text("")
    (pk / "__main__.py").write_text("import time; time.sleep(60)")
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "pkgfalso"),
               COGNIA_EFIMERO="1")  # sin rastro en la memoria del dueno
    return subprocess.Popen([sys.executable, "-m", "cognia"], cwd=str(tmp_path),
                            env=env, **_ses._flags_grupo_propio())


def test_G_reconciliacion_mata_a_un_huerfano_REAL_y_lo_anota(tmp_path,
                                                             monkeypatch):
    """Simula el servidor anterior: un `python -m cognia` vivo (de mentira,
    ver _hijo_cognia_falso) cuyo .pid quedo en disco se MATA y se anota en su
    jsonl. Un `python -c sleep` cualquiera con un .pid a su nombre (PID
    reciclado: hallazgos rev1/rev2 2026-08-25) NO se toca y su .pid rancio se
    retira diciendolo."""
    _aislar(tmp_path, monkeypatch)
    d = tmp_path / "p1"; d.mkdir()
    huerfano = _hijo_cognia_falso(tmp_path)
    victima = subprocess.Popen([sys.executable, "-c",
                                "import time; time.sleep(60)"],
                               **_ses._flags_grupo_propio())
    try:
        assert _esperar(lambda: _ses._proceso_vivo(huerfano.pid) is not None)
        (d / "s1.pid").write_text(str(huerfano.pid))
        (d / "s1.jsonl").write_text(
            json.dumps({"quien": "meta", "titulo": "vieja"}) + "\n")
        # y un .pid de un proceso que YA no existe (PID imposible)
        (d / "s2.pid").write_text("999999999")
        (d / "s2.jsonl").write_text("")
        # y uno ilegible
        (d / "s3.pid").write_text("basura")
        # y el python AJENO
        (d / "s4.pid").write_text(str(victima.pid))
        (d / "s4.jsonl").write_text("")
        acciones = _ses.reconciliar_huerfanos(tmp_path)
        assert huerfano.wait(timeout=5) != 0       # MUERTO
        por_sid = {a["sesion"]: a for a in acciones}
        assert por_sid["s1"]["accion"] == "terminado"
        assert por_sid["s1"]["pid"] == huerfano.pid
        assert por_sid["s2"]["accion"] == "ya no corria"
        assert "ilegible" in por_sid["s3"]["accion"]
        assert "no es nuestro REPL" in por_sid["s4"]["accion"]
        assert "no es un `python -m cognia`" in por_sid["s4"]["accion"]
        assert victima.poll() is None              # VIVO
        assert not list(d.glob("*.pid"))           # todos consumidos
        ultima = json.loads((d / "s1.jsonl").read_text("utf-8").splitlines()[-1])
        assert ultima["quien"] == "sistema"
        assert "sesion anterior terminada al reiniciar el servidor" in ultima["texto"]
        assert str(huerfano.pid) in ultima["texto"]
        ultima4 = json.loads((d / "s4.jsonl").read_text("utf-8").splitlines()[-1])
        assert "no es nuestro REPL" in ultima4["texto"]
        # segunda pasada: nada que hacer
        assert _ses.reconciliar_huerfanos(tmp_path) == []
    finally:
        for p in (huerfano, victima):
            if p.poll() is None:
                p.kill()


def test_G_predicado_es_repl_cognia_por_cmdline_y_por_fecha(tmp_path,
                                                            monkeypatch):
    """El predicado solo: cmdline por TOKEN (-m cognia / -m cognia.x; no
    -m cognia_prueba ni un script con 'cognia' en la ruta) y create_time
    anterior al mtime del .pid (un .pid mas viejo que el proceso = PID
    reciclado: no se mata)."""
    import psutil
    ok = _ses.cmdline_es_cognia
    assert ok(["python", "-m", "cognia"]) and ok(["py", "-m", "cognia.remoto", "--port", "1"])
    assert not ok(["python", "-m", "cognia_prueba"])
    assert not ok(["python", "C:/cognia_v2/x.py"]) and not ok([]) and not ok(None)
    assert not ok(["python", "-m"])
    hijo = _hijo_cognia_falso(tmp_path)
    try:
        assert _esperar(lambda: _ses._proceso_vivo(hijo.pid) is not None)
        pr = psutil.Process(hijo.pid)
        assert _ses.es_repl_cognia(pr, time.time()) == (True, "ok")
        # sin fecha: solo cmdline
        assert _ses.es_repl_cognia(pr, None)[0] is True
        # .pid escrito 100 s ANTES de nacer el proceso: reciclado
        nuestro, motivo = _ses.es_repl_cognia(pr, pr.create_time() - 100)
        assert nuestro is False and "DESPUES" in motivo
        # y el bucle lo respeta: .pid envejecido con utime -> no lo toca
        _aislar(tmp_path, monkeypatch)
        d = tmp_path / "p1"; d.mkdir()
        (d / "s1.pid").write_text(str(hijo.pid)); (d / "s1.jsonl").write_text("")
        viejo = time.time() - 100
        os.utime(d / "s1.pid", (viejo, viejo))
        acc = _ses.reconciliar_huerfanos(tmp_path)
        assert len(acc) == 1 and "PID reciclado" in acc[0]["accion"]
        assert hijo.poll() is None
        # el propio pytest (cmdline sin -m cognia) tampoco es un REPL
        assert _ses.es_repl_cognia(psutil.Process(os.getpid()), None)[0] is False
    finally:
        if hijo.poll() is None:
            hijo.kill()


def _escuchando():
    """Un socket LISTEN de ESTE proceso en un puerto libre (para simular un
    servidor vivo arrancado en proceso, cmdline sin -m cognia)."""
    import socket
    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    sk.listen(1)
    return sk, sk.getsockname()[1]


def test_G_servidor_pid_formato_unico_y_lectura_con_vida(tmp_path, monkeypatch,
                                                         caplog):
    """servidor.pid: JSON {"pid","host","port"} escrito por el servidor y una
    UNICA lectura (leer_pid_servidor) que solo devuelve un servidor VIVO:
    formato viejo (int), pid muerto o pid vivo que no es un servidor de
    Cognia = rancio, se dice y se retira (hallazgos rev1/rev2 2026-08-25:
    el CLI leia int() y nunca encontraba el servidor que el mismo arranco;
    y tras un kill el fichero quedaba)."""
    import logging
    _aislar(tmp_path, monkeypatch)
    f = tmp_path / "servidor.pid"
    assert _srv.leer_pid_servidor(tmp_path) is None
    assert _ses.estado_pid_servidor(tmp_path) == (None, "no hay servidor.pid")
    # formato viejo (lo que escribia cli._remoto_arrancar): rancio, borrado
    f.write_text("12345")
    with caplog.at_level(logging.WARNING, logger="cognia.remoto"):
        assert _srv.leer_pid_servidor(tmp_path) is None
    assert "formato viejo" in caplog.text and not f.exists()
    # pid muerto
    f.write_text(json.dumps({"pid": 999999999, "host": "0.0.0.0", "port": 1}))
    assert _srv.leer_pid_servidor(tmp_path, borrar_rancio=False) is None
    assert f.exists()          # sin borrar_rancio se deja (el CLI decide)
    info, motivo = _ses.estado_pid_servidor(tmp_path)
    assert info is None and "muerto" in motivo
    # pid VIVO pero ni -m cognia ni escucha en el puerto: rancio (reciclado)
    f.write_text(json.dumps({"pid": os.getpid(), "host": "127.0.0.1", "port": 1}))
    info, motivo = _ses.estado_pid_servidor(tmp_path)
    assert info is None and "no es" in motivo, motivo
    # pid vivo que ESCUCHA en el puerto declarado (servidor en proceso)
    sk, puerto = _escuchando()
    try:
        _srv.escribir_pid_servidor(tmp_path, "127.0.0.1", puerto)
        assert json.loads(f.read_text()) == {"pid": os.getpid(),
                                             "host": "127.0.0.1", "port": puerto}
        info = _srv.leer_pid_servidor(tmp_path)
        assert info == {"pid": os.getpid(), "host": "127.0.0.1",
                        "port": puerto, "vivo": True}
        # el borrado propio no se lleva el fichero de OTRO servidor
        f.write_text(json.dumps({"pid": os.getpid() + 1, "host": "h", "port": 9}))
        assert _srv.borrar_pid_servidor_propio(tmp_path) is False and f.exists()
        _srv.escribir_pid_servidor(tmp_path, "127.0.0.1", puerto)
        assert _srv.borrar_pid_servidor_propio(tmp_path) is True
        assert not f.exists()
        assert _srv.borrar_pid_servidor_propio(tmp_path) is False   # idempotente
    finally:
        sk.close()


def test_G_un_segundo_servidor_no_reconcilia_las_sesiones_del_vivo(
        tmp_path, monkeypatch, capsys):
    """main() con un servidor VIVO en servidor.pid (este proceso, escuchando
    en el puerto declarado): no llama a reconciliar_huerfanos, no pisa
    servidor.pid y el REPL (falso) del primero sigue vivo. Sin servidor vivo:
    reconcilia, escribe su pid y lo borra al salir. servir() (el uvicorn.run
    de la casa) se sustituye por un no-op (el servidor real se prueba en el
    e2e)."""
    _aislar(tmp_path, monkeypatch)
    monkeypatch.setattr(_srv, "servir", lambda *a, **k: None)
    monkeypatch.setattr(_srv, "asegurar_cert", lambda d: ("c", "k"))
    llamadas = []
    original = _ses.reconciliar_huerfanos
    monkeypatch.setattr(_ses, "reconciliar_huerfanos",
                        lambda raiz=None, **k: llamadas.append(raiz) or original(raiz, **k))
    sk, puerto = _escuchando()
    hijo = _hijo_cognia_falso(tmp_path)
    try:
        assert _esperar(lambda: _ses._proceso_vivo(hijo.pid) is not None)
        d = tmp_path / "p1"; d.mkdir()
        (d / "s1.pid").write_text(str(hijo.pid)); (d / "s1.jsonl").write_text("")
        # el "primero" es OTRO pid (si fuera este, main() lo tomaria por si
        # mismo y al salir borraria el fichero como propio): la lectura se
        # parchea para que lo de por vivo (la lectura real se prueba aparte)
        primero = {"pid": os.getpid() + 7, "host": "127.0.0.1", "port": puerto}
        (tmp_path / "servidor.pid").write_text(json.dumps(primero))
        monkeypatch.setattr(_srv, "estado_pid_servidor",
                            lambda raiz=None: ({**primero, "vivo": True}, "escucha"))
        assert _srv.main(["--host", "127.0.0.1", "--port", str(puerto + 1)]) == 0
        salida = capsys.readouterr().out
        assert "ya hay un servidor vivo" in salida
        assert llamadas == []                          # NO reconcilio
        assert hijo.poll() is None                     # REPL del primero VIVO
        assert (d / "s1.pid").exists()
        assert json.loads((tmp_path / "servidor.pid").read_text()) == primero
        # sin servidor vivo: reconcilia (mata al huerfano), escribe y borra
        monkeypatch.setattr(_srv, "estado_pid_servidor",
                            lambda raiz=None: (None, "servidor.pid rancio: pid 1 muerto"))
        vistos = {}

        def run_falso(app, **k):
            vistos["pid"] = json.loads((tmp_path / "servidor.pid").read_text())
        monkeypatch.setattr(_srv, "servir", run_falso)
        assert _srv.main(["--host", "127.0.0.1", "--port", str(puerto + 1)]) == 0
        salida = capsys.readouterr().out
        assert "rancio" in salida and "sesion huerfana p1/s1" in salida
        assert llamadas == [tmp_path]
        assert hijo.wait(timeout=5) != 0
        assert vistos["pid"] == {"pid": os.getpid(), "host": "127.0.0.1",
                                 "port": puerto + 1}
        assert not (tmp_path / "servidor.pid").exists()   # borrado al salir
    finally:
        sk.close()
        if hijo.poll() is None:
            hijo.kill()


def test_G_crear_app_NO_reconcilia(tmp_path, monkeypatch):
    """La reconciliacion es de main(): los tests crean apps con la RAIZ real
    y no deben matar los REPLs de un servidor vivo."""
    _aislar(tmp_path, monkeypatch)
    d = tmp_path / "p1"; d.mkdir()
    (d / "s1.pid").write_text("999999999")
    _srv.crear_app()
    assert (d / "s1.pid").exists()
    fuente = inspect.getsource(_srv.main)
    assert "reconciliar_huerfanos" in fuente


def test_G_limpiar_huerfanas_con_dry_run(tmp_path, monkeypatch, capsys):
    datos = tmp_path / "datos"; datos.mkdir()
    monkeypatch.setattr(_ses, "RAIZ_DATOS", datos)
    monkeypatch.setattr(_srv, "RAIZ_DATOS", datos)
    monkeypatch.setattr(_ses, "FICHERO_PROYECTOS", datos / "proyectos.json")
    (tmp_path / "proy").mkdir()
    pr = registrar_proyecto(str(tmp_path / "proy"))
    for h in ("aaaa1111", "bbbb2222"):
        (datos / h).mkdir(); (datos / h / "x.jsonl").write_text("")
    (datos / "papelera").mkdir()
    (datos / "token.txt").write_text("t")
    huerfanas = _ses.carpetas_huerfanas(datos)
    assert [d.name for d in huerfanas] == ["aaaa1111", "bbbb2222"]
    # dry-run: lista, no borra
    assert _srv.limpiar_desde_cli(True, datos) == 0
    out = capsys.readouterr().out
    assert "se borraria" in out and "aaaa1111" in out and "2 carpeta(s)" in out
    assert (datos / "aaaa1111").exists()
    # y por el main real, con argv
    assert _srv.main(["--limpiar", "--dry-run"]) == 0
    assert (datos / "bbbb2222").exists()
    assert _srv.main(["--limpiar"]) == 0
    out = capsys.readouterr().out
    assert "borrada:" in out
    assert not (datos / "aaaa1111").exists()
    assert not (datos / "bbbb2222").exists()
    assert (datos / pr["id"]).exists()      # la registrada sigue
    assert (datos / "papelera").exists()    # la papelera se respeta
    assert (datos / "token.txt").exists()   # solo carpetas


def test_G_version_y_capacidades(tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    import cognia
    r = _cliente(tmp_path).get("/api/version").json()
    assert r["version"] == cognia.__version__
    assert r["capacidades"] == ["interrumpir", "delta", "subir", "ficheros"]
    # el back conserva "total" por compatibilidad de la API (y lo declara):
    # es el FRONT el que ofrece restringido por defecto
    assert r["acceso_default"] == "total"


def test_G_sesion_restringida_no_hereda_acceso_total(tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    s = Sesion(id="s", proyecto_id="p", ruta_proyecto=str(tmp_path),
               titulo="t", acceso="restringido")
    env = s._entorno()
    assert "COGNIA_ACCESO_TOTAL" not in env and "COGNIA_SCREEN" not in env
    assert env["COGNIA_REMOTO"] == "1" and env["COGNIA_EVENTS_JSONL"] == "1"


# ═══ cazados en el e2e REAL de la paridad (2026-08-25) ════════════════════

def test_e2e_la_ultima_linea_de_un_KeyboardInterrupt_no_entra_al_chat():
    """El traceback de una interrupcion remota no atrapada terminaba en
    'KeyboardInterrupt: interrumpido desde el remoto' y esa linea entraba al
    chat como respuesta de Cognia (no casaba Error|Exception|Warning)."""
    from cognia.remoto.sesiones import reclasificar
    quien, en_traza = reclasificar("cognia", "Traceback (most recent call last):", False)
    assert (quien, en_traza) == ("log", True)
    quien, en_traza = reclasificar("cognia", '  File "x.py", line 1, in f', en_traza)
    assert quien == "log"
    quien, en_traza = reclasificar(
        "cognia", "KeyboardInterrupt: interrumpido desde el remoto", en_traza)
    assert quien == "log"
    assert reclasificar("cognia", "SystemExit: 3", True)[0] == "log"
    # y una respuesta normal despues del traceback vuelve al chat
    assert reclasificar("cognia", "Listo, ya esta.", en_traza)[0] == "cognia"


def test_e2e_pensando_del_fast_path_es_actividad_no_chat():
    """'  · pensando…' lo pinta el renderer ANTES del primer evento tipado del
    turno; sin _con_eventos el de-dup no actua y llegaba al chat como si
    Cognia hubiera dicho '· pensando…'. Las lineas con marca del renderer
    son actividad (plegable) tambien en el fallback por regex."""
    from cognia.remoto.sesiones import _limpiar, es_eco_renderer, reclasificar
    for linea in ("  · pensando…", "  · pensando… (3s)", "  ⏺ leer_archivo x.py",
                  "  ✗ ejecutar — fallo", "  ⚠ backend lento",
                  "  → python scripts/servir_flota.py"):
        assert reclasificar("cognia", linea, False)[0] == "actividad", linea
        assert es_eco_renderer(linea), linea
    # el razonamiento "∴" (2 espacios en el e2e real; 4 en la prosa del
    # pensar) es actividad pero NO eco: no duplica ningun evento anotado
    for linea in ("  ∴ Empty workspace. I'll write", "    ∴ pienso en voz alta"):
        assert reclasificar("cognia", linea, False)[0] == "actividad", linea
        assert not es_eco_renderer(linea), linea
    # una vineta de markdown de la respuesta NO es marca del renderer
    assert reclasificar("cognia", "- primer punto", False)[0] == "cognia"
    assert reclasificar("cognia", "Hola. ¿En qué te ayudo?", False)[0] == "cognia"
    # SOLO con la sangria EXACTA del renderer (hallazgo rev2 2026-08-25): la
    # respuesta final se imprime plana y una enumeracion del modelo con "→ "
    # o "· " es CHAT, ni actividad ni eco descartado
    for linea in ("→ primero calcula la media", "· un punto", "⚠ ojo con esto",
                  "∴ por tanto x", " · casi", "   · tres espacios",
                  "·sin espacio", "  ·  dos espacios tras la marca"):
        assert reclasificar("cognia", linea, False)[0] == "cognia", linea
        assert not es_eco_renderer(linea), linea
    # y el prompt que precede a la marca en la misma linea ("cognia>   · …")
    # ya no se come la sangria: la marca sigue siendo reconocible
    assert _limpiar("cognia>   · pensando…") == "  · pensando…"
    assert _limpiar("cognia> Hola") == "Hola"
    assert reclasificar("cognia", "cognia>   · pensando…", False)[0] == "actividad"


def test_e2e_el_diff_de_escribir_archivo_y_el_razonamiento_no_entran_al_chat(
        tmp_path, monkeypatch):
    """Lineas REALES del e2e 2026-08-25 (ensayo de 3000 palabras escrito con
    escribir_archivo): el renderer imprime el diff con "+ " solo en la primera
    linea de cada parrafo y envuelve el resto a 80 columnas sin marca; el
    razonamiento "∴" sigue sangrado. Todo eso llegaba al chat como ~150
    respuestas de Cognia. El bloque diff cierra con el ToolFin (evento)."""
    s = _sesion(tmp_path, monkeypatch)
    s._con_eventos = True
    for l in [
        _ev("PasoIntencion", intencion="Empty workspace. I'll write the essay"),
        "  ∴ Empty workspace. I'll write the essay to a file. Let me write a long",
        "    essay (about 3500–4000 words) in Spanish, in prose form, organized by",
        "    century.",
        "+ EL IMPERIO ROMANO, SIGLO A SIGLO: UN ENSAYO",
        "+",
        "+ El Imperio Romano no nació como un imperio. Nació como una reparación.",
        "Después de décadas de guerras civiles que desgastaron la República, la figura",
        "fue rompiendo por dentro.",
        "+",
        "+ El primer siglo antes de Cristo fue el siglo de la construcción. Augusto",
        "posteriores.",
        _ev("ToolFin", tool="escribir_archivo", args="ensayo.txt", ok=True,
            resumen="RESULTADO escribir_archivo: ok"),
        "Listo: el ensayo quedó en ensayo.txt.",
        _ev("FooterTurno", ok=True, segundos=1.0, tokens=10),
    ]:
        s._procesar_linea(l)
    lineas = _lineas(s)
    chat = [l["texto"] for l in lineas if l["quien"] == "cognia"]
    assert chat == ["Listo: el ensayo quedó en ensayo.txt."], chat
    assert sum(1 for l in lineas if l["quien"] == "actividad") >= 10
    # una respuesta con sangria o "+" que NO viene tras un bloque sigue en chat
    s2 = _sesion(tmp_path, monkeypatch)
    s2.id = "s2"
    s2._procesar_linea("Hola. Te explico:")
    s2._procesar_linea("    codigo = 1")
    assert [l["quien"] for l in _lineas(s2)] == ["cognia", "cognia"]
