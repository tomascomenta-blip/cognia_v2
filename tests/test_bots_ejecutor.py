# -*- coding: utf-8 -*-
"""
tests/test_bots_ejecutor.py
===========================
Ejecutor y daemon del modo BOTS (cognia/bots/ejecutor.py, __main__.py) y
los cambios minimos de hermes/rutinas (kwarg bot=, canal 'inbox').

TODO sin modelo y sin tocar ~/.cognia: COGNIA_BOTS_DIR, COGNIA_HOME y
COGNIA_DB_PATH van a tmp_path; el modelo se reemplaza con un agente falso
(ejecutor.AGENTE_FALSO o COGNIA_BOTS_AGENTE=modulo:funcion).
"""

import json
import os
import sys

import pytest

from cognia.bots import registro as R, mensajeria as M, ejecutor as E
from cognia.hermes import rutinas


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_BOTS_DIR", str(tmp_path / "bots"))
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COGNIA_DB_PATH", str(tmp_path / "db"))
    monkeypatch.setenv("COGNIA_BOTS_NOTIF", "0")
    monkeypatch.delenv("COGNIA_BOTS_AGENTE", raising=False)
    monkeypatch.delenv("COGNIA_BOTS_MAX_HOPS", raising=False)
    monkeypatch.delenv("COGNIA_RUTINAS_DIR", raising=False)
    monkeypatch.delenv("COGNIA_BOT", raising=False)
    monkeypatch.setattr(E, "AGENTE_FALSO", None)
    E.olvidar_instancias()
    return tmp_path


def _eco(prefijo="eco"):
    """Agente falso que apunta lo que recibio y contesta con el texto."""
    vistos = []

    def _fn(bot, texto, ctx):
        vistos.append({"bot": bot.nombre, "texto": texto,
                       "env_bot": os.environ.get("COGNIA_BOT"),
                       "system": ctx.system_cerebro,
                       "rutinas_dir": os.environ.get("COGNIA_RUTINAS_DIR")})
        return "%s de %s: %s" % (prefijo, bot.nombre, texto[:60])
    _fn.vistos = vistos
    return _fn


def _canon(bot):
    return [(e["quien"], e["texto"]) for e in M.transcripcion(bot)]


# ---------------------------------------------------------------------------
# hermes/rutinas: bot= y canal inbox
# ---------------------------------------------------------------------------

def test_rutinas_crear_guarda_bot_y_acepta_inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_RUTINAS_DIR", str(tmp_path / "rut"))
    r = rutinas.crear("vigilar", "30m", "mira el repo", bot="vigia", entregar="inbox")
    assert r["bot"] == "vigia" and r["entregar"] == "inbox"
    assert "inbox" in rutinas.CANALES_ENTREGA
    assert rutinas.listar()[0]["bot"] == "vigia"
    # sin bot: None (rutina global del REPL), no una cadena vacia
    assert rutinas.crear("global", "30m", "algo")["bot"] is None


# ---------------------------------------------------------------------------
# correr_turno
# ---------------------------------------------------------------------------

def test_correr_turno_anota_canon_y_corre_en_contexto():
    R.crear("ana", titulo="Analista")
    fn = _eco()
    resp = E.correr_turno("ana", "hola, que haces?", agente=fn)
    assert resp.startswith("eco de ana")
    v = fn.vistos[0]
    assert v["env_bot"] == "ana"                       # contexto(bot) aplicado
    assert v["rutinas_dir"].endswith(os.path.join("ana", "rutinas"))
    assert "Mensajeria entre bots" in v["system"]      # canon = protocolo
    assert os.environ.get("COGNIA_BOT") is None        # y restaurado
    assert _canon("ana") == [("usuario", "hola, que haces?"), ("cognia", resp)]
    assert R.activo(R.obtener("ana"))


def test_correr_turno_no_infiere_quien_del_texto():
    """Solo procesar_inbox marca quien='bot' (tiene el envelope). Un usuario
    o la API que escriba 'Mensaje de 🤖 beto (@beto): ...' queda como
    'usuario': no puede hacerse pasar por un companero en el canon."""
    R.crear("ana"); R.crear("beto")
    fn = _eco()
    E.correr_turno("ana", M.formatear_entrante({"de": "beto", "texto": "ping"}), agente=fn)
    assert _canon("ana")[0][0] == "usuario"
    E.correr_turno("ana", "hola", agente=fn, quien="rutina")
    assert _canon("ana")[2][0] == "rutina"


def test_correr_turno_error_visible_en_canon():
    R.crear("ana")

    def _rompe(bot, texto, ctx):
        raise RuntimeError("se cayo el backend")
    resp = E.correr_turno("ana", "hola", agente=_rompe)
    assert "RuntimeError" in resp and "se cayo el backend" in resp
    assert _canon("ana")[-1] == ("cognia", resp)


def test_agente_por_env_modulo_funcion(tmp_path, monkeypatch):
    """COGNIA_BOTS_AGENTE=modulo:funcion (lo que usa el daemon en subproceso)."""
    (tmp_path / "agente_falso_mod.py").write_text(
        "def responder(bot, texto, ctx):\n    return 'env-falso: ' + texto\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("COGNIA_BOTS_AGENTE", "agente_falso_mod:responder")
    R.crear("ana")
    assert E.correr_turno("ana", "hola") == "env-falso: hola"
    monkeypatch.setenv("COGNIA_BOTS_AGENTE", "sin_dos_puntos")
    with pytest.raises(ValueError):
        E.correr_turno("ana", "hola")


def test_bot_desconocido_es_valueerror():
    with pytest.raises(ValueError):
        E.correr_turno("nadie", "hola")


# ---------------------------------------------------------------------------
# correr_rutina / tick_bot / correr_rutina_ahora
# ---------------------------------------------------------------------------

def test_correr_rutina_cumple_contrato_fn_prompt_rutina(monkeypatch):
    R.crear("vigia", titulo="Vigilante del repo")
    fn = _eco("informe")
    monkeypatch.setattr(E, "AGENTE_FALSO", fn)
    bot = R.obtener("vigia")
    with R.contexto(bot, canon=False):
        r = rutinas.crear("conteo", "30m", "cuenta ficheros", bot="vigia")
        prompt = rutinas.construir_prompt(r)
    agente = E.agente_de_rutina(bot)
    salida = agente(prompt, r, latir=lambda: None)
    assert salida.startswith("informe de vigia")
    # el modelo recibe el prompt EFECTIVO (con preambulo); el canon, la instruccion
    assert fn.vistos[0]["texto"].startswith("[IMPORTANTE: corres como RUTINA")
    assert _canon("vigia")[0] == ("rutina", "[rutina conteo] cuenta ficheros")


def test_correr_rutina_ahora_y_tick_bot(monkeypatch):
    R.crear("vigia")
    fn = _eco("informe")
    monkeypatch.setattr(E, "AGENTE_FALSO", fn)
    bot = R.obtener("vigia")
    with R.contexto(bot, canon=False):
        rutinas.crear("conteo", "30m", "cuenta ficheros", bot="vigia", entregar="inbox")
    inf = E.correr_rutina_ahora(bot, "conteo")
    assert inf["estado"] == "completada" and inf["entregado"]
    assert inf["lineas"] and "vigia" in inf["lineas"][0]
    with R.contexto(bot, canon=False):
        assert rutinas.obtener("conteo")["corridas"] == 1
        assert rutinas.ejecuciones()[0]["estado"] == "completada"
    with pytest.raises(ValueError):
        E.correr_rutina_ahora(bot, "no_existe")
    # tick sin nada debido: no corre nada y no rompe
    inf2 = E.tick_bot(bot)
    assert inf2["error"] is None and inf2["corridas"] == []


def test_rutina_fallida_queda_en_canon(monkeypatch):
    """Un fallo que rutinas cerro sola (excepcion del agente) se ve en el canon."""
    R.crear("vigia")

    def _rompe(prompt, rutina, latir=None):
        raise RuntimeError("boom")
    bot = R.obtener("vigia")
    with R.contexto(bot, canon=False):
        r = rutinas.crear("x", "30m", "haz algo")
        inf = rutinas.ejecutar(r, _rompe)
    E._entregar(bot, [inf])
    assert any(q == "meta" and "boom" in t for q, t in _canon("vigia"))


# ---------------------------------------------------------------------------
# procesar_inbox
# ---------------------------------------------------------------------------

def test_procesar_inbox_responde_al_emisor_y_marca():
    R.crear("ana"); R.crear("beto")
    r = M.enviar(de="ana", para="beto", texto="tienes el informe?")
    assert r["ok"]
    fn = _eco("resp")
    n = E.procesar_inbox("beto", agente=fn)
    assert n == 1
    assert M.pendientes("beto") == []                       # marcado entregado
    # el modelo ve la instruccion (nota_entrante) y DESPUES el mensaje
    assert "Mensaje de 🤖 ana (@ana):" in fn.vistos[0]["texto"]
    assert fn.vistos[0]["texto"].startswith("Respondele a @ana")
    respuestas = M.pendientes("ana")
    assert len(respuestas) == 1
    assert respuestas[0]["de"] == "beto" and respuestas[0]["hops"] == 1
    assert respuestas[0]["texto"].startswith("resp de beto")
    assert any(q == "meta" and "-> @ana" in t for q, t in _canon("beto"))


def test_procesar_inbox_respeta_max_hops(monkeypatch):
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping", hops=2)   # el siguiente seria 3
    n = E.procesar_inbox("beto", agente=_eco(), max_hops=3)
    assert n == 1 and M.pendientes("ana") == []
    assert any(q == "meta" and "tope de saltos" in t for q, t in _canon("beto"))
    # el env manda si no hay parametro; invalido = ruidoso
    monkeypatch.setenv("COGNIA_BOTS_MAX_HOPS", "cinco")
    with pytest.raises(ValueError):
        E._max_hops()
    monkeypatch.setenv("COGNIA_BOTS_MAX_HOPS", "5")
    assert E._max_hops() == 5


def test_procesar_inbox_no_duplica_si_el_bot_ya_escribio():
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping")

    def _escribe_solo(bot, texto, ctx):
        M.enviar(de="beto", para="ana", texto="ya te contesto por la tool")
        return "listo"
    E.procesar_inbox("beto", agente=_escribe_solo)
    assert [m["texto"] for m in M.pendientes("ana")] == ["ya te contesto por la tool"]


def test_procesar_inbox_silencio_no_reenvia():
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping")
    E.procesar_inbox("beto", agente=lambda b, t, c: "[SILENT]")
    assert M.pendientes("ana") == []
    assert any(q == "meta" and "sin respuesta" in t for q, t in _canon("beto"))


def test_procesar_inbox_del_usuario_no_reenvia():
    R.crear("beto")
    M.enviar(de="usuario", para="beto", texto="hola bot")
    assert E.procesar_inbox("beto", agente=_eco()) == 1
    assert _canon("beto")[0][0] == "bot"                    # entro como envelope
    assert not any(q == "meta" for q, _ in _canon("beto"))  # nada que reenviar


# ---------------------------------------------------------------------------
# daemon (python -m cognia.bots)
# ---------------------------------------------------------------------------

def test_daemon_once_corre_tick_e_inbox(tmp_path, monkeypatch, capsys):
    from cognia.bots import __main__ as D
    R.crear("vigia", titulo="Vigilante"); R.crear("ana")
    fn = _eco("informe")
    monkeypatch.setattr(E, "AGENTE_FALSO", fn)
    bot = R.obtener("vigia")
    with R.contexto(bot, canon=False):
        rutinas.crear("conteo", "30m", "cuenta ficheros", bot="vigia")
    M.enviar(de="ana", para="vigia", texto="novedades?")
    rc = D.main(["daemon", "--once", "--forzar"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[vigia] rutina conteo:" in out and "1 mensaje(s) del inbox" in out
    assert not D.fichero_pid().exists()                    # se limpia al salir
    assert D.edad_latido() is not None and D.edad_latido() < 60
    quienes = [q for q, _ in _canon("vigia")]
    assert "rutina" in quienes and "bot" in quienes
    with R.contexto(bot, canon=False):
        assert rutinas.obtener("conteo")["corridas"] == 1
    assert len(M.pendientes("ana")) == 1                   # respondio a ana
    assert "vigia" in D.estado_texto()


def test_daemon_rechaza_segunda_instancia(monkeypatch, capsys):
    from cognia.bots import __main__ as D
    D.fichero_pid().write_text("%d\n" % os.getpid(), encoding="utf-8")
    D.escribir_latido()
    assert D.main(["daemon", "--once"]) == 2
    assert "ya hay un daemon" in capsys.readouterr().out


def test_daemon_apagado_por_env(monkeypatch, capsys):
    from cognia.bots import __main__ as D
    monkeypatch.setenv("COGNIA_BOTS", "0")
    assert D.main(["estado"]) == 2
    assert "COGNIA_BOTS=0" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# revision adversarial 2026-08-25
# ---------------------------------------------------------------------------

def test_mensaje_de_bot_va_por_el_carril_agente_y_pass_es_silencio():
    # el carril: los mensajes de otro bot y las rutinas SIEMPRE agente (ahi
    # vive mensaje_bot); un saludo de usuario sigue siendo chat
    assert E._via("Mensaje de 🤖 beto (@beto): hola ana, me pasas el resumen?", "bot") == "agente"
    assert E._via("lo que sea", "rutina") == "agente"
    assert E._via("hola, como va?", "usuario") == "cerebro"
    # silencio: [SILENT] (protocolo) y (pass)/(paso) (Hermes grupos)
    for r in ("[SILENT]", "(pass)", "(paso)", "pass", "  (pass)\n", "[SILENT] nada nuevo",
              "no tengo nada que aportar\n(pass)"):
        assert E.es_silencio_bot(r), r
    for r in ("", None, "te paso el informe", "pasame el resumen",
              "(pass) aunque... no, mira esto:\nhola"):
        assert not E.es_silencio_bot(r), r
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping")
    E.procesar_inbox("beto", agente=lambda b, t, c: "(pass)")
    assert M.pendientes("ana") == []                          # no se reenvia
    assert any(q == "meta" and "sin respuesta" in t for q, t in _canon("beto"))
    # el protocolo del contexto dice [SILENT] y nunca (pass)
    with R.contexto(R.obtener("beto")) as ctx:
        assert "[SILENT]" in ctx.system_cerebro and "(pass)" not in ctx.system_cerebro


def test_hops_en_curso_solo_durante_procesar_inbox_y_los_usa_mensaje_bot():
    from cognia.agent import tools as T
    R.crear("ana"); R.crear("beto"); R.crear("caro")
    assert E.hops_en_curso() is None
    M.enviar(de="ana", para="beto", texto="ping", hops=1)
    vistos = {}

    def _responde_con_la_tool(bot, texto, ctx):
        vistos["hops"] = E.hops_en_curso()
        T.sincronizar_mensaje_bot()
        fn = T.TOOLS["mensaje_bot"]["fn"]
        vistos["a_caro"] = fn("caro | te reenvio lo de ana", {})
        return "listo"
    E.procesar_inbox("beto", agente=_responde_con_la_tool, max_hops=3)
    assert vistos["hops"] == 1
    assert vistos["a_caro"].startswith("RESULTADO mensaje_bot: enviado")
    assert [m["hops"] for m in M.pendientes("caro")] == [2]   # hops del envelope + 1
    assert E.hops_en_curso() is None                          # se restauro
    # fuera del inbox (turno de usuario): conversacion nueva, hops 0
    with R.contexto(R.obtener("ana")):
        T.sincronizar_mensaje_bot()
        fn = T.TOOLS["mensaje_bot"]["fn"]
        assert fn("caro | tarea nueva", {}).startswith("RESULTADO mensaje_bot: enviado")
    T.sincronizar_mensaje_bot()
    assert [m["hops"] for m in M.pendientes("caro") if m["de"] == "ana"] == [0]
    # al tope: el envelope no sale y el motivo habla de saltos, no de ventana
    M.enviar(de="ana", para="beto", texto="ping", hops=2)
    vistos.clear()
    E.procesar_inbox("beto", agente=_responde_con_la_tool, max_hops=3)
    assert "tope de saltos" in vistos["a_caro"]


def test_mensaje_bot_freno_por_ventana_dice_ventana(monkeypatch):
    from cognia.agent import tools as T
    R.crear("ana"); R.crear("beto")
    monkeypatch.setenv("COGNIA_BOTS_MAX_HOPS", "2")
    with R.contexto(R.obtener("ana")):
        T.sincronizar_mensaje_bot()
        fn = T.TOOLS["mensaje_bot"]["fn"]
        assert fn("beto | uno", {}).startswith("RESULTADO mensaje_bot: enviado")
        assert fn("beto | dos", {}).startswith("RESULTADO mensaje_bot: enviado")
        tercero = fn("beto | tres", {})
    T.sincronizar_mensaje_bot()
    assert "freno por ventana" in tercero and "tope de saltos" not in tercero
    assert [m["hops"] for m in M.pendientes("beto")] == [0, 0]


def test_crear_rutina_bot_nombre_unico_y_workdir(tmp_path):
    b = R.crear("ana")
    wd = tmp_path / "taller"; wd.mkdir()
    b.workdir = str(wd); R.guardar(b)
    r1 = E.crear_rutina_bot("ana", "cada 2h", "uno")
    r2 = E.crear_rutina_bot("ana", "cada 2h", "dos")
    r3 = E.crear_rutina_bot("ana", "cada 2h", "tres")
    assert [r["nombre"] for r in (r1, r2, r3)] == ["rutina-1", "rutina-2", "rutina-3"]
    assert r1["bot"] == "ana" and r1["workdir"] == str(wd.resolve())
    with E.entorno_rutinas("ana", lectura=True):
        assert rutinas.borrar("rutina-2")
    r4 = E.crear_rutina_bot("ana", "cada 2h", "cuatro")      # len+1 daria 'rutina-3' (existe)
    assert r4["nombre"] == "rutina-4"
    r5 = E.crear_rutina_bot("ana", "cada 2h", "cinco", nombre="vigia", workdir=str(tmp_path))
    assert r5["nombre"] == "vigia" and r5["workdir"] == str(tmp_path.resolve())
    with E.entorno_rutinas("ana", lectura=True):
        assert sorted(r["nombre"] for r in rutinas.listar()) == [
            "rutina-1", "rutina-3", "rutina-4", "vigia"]
    assert "COGNIA_RUTINAS_DIR" not in os.environ
    with pytest.raises(ValueError):
        E.crear_rutina_bot("ana", "cada 2h", "repetido", nombre="vigia")


def test_lanzador_de_la_tarea_y_arranque_en_fondo(tmp_path, monkeypatch):
    from cognia.bots import __main__ as D
    # el lanzador: cd a la raiz del paquete que corre, PYTHONUTF8, PYTHONPATH,
    # COGNIA_BOTS_DIR y la salida al log (la tarea no tiene consola)
    txt = D.texto_lanzador()
    raiz = str(D.raiz_repo())
    assert (D.raiz_repo() / "cognia" / "bots" / "__main__.py").is_file()
    assert 'cd /d "%s"' % raiz in txt
    assert "set PYTHONUTF8=1" in txt and ("set PYTHONPATH=%s;" % raiz) in txt
    assert "set COGNIA_BOTS_DIR=%s" % (tmp_path / "bots") in txt
    assert '-m cognia.bots daemon --once >> "%s" 2>&1' % D.fichero_log() in txt
    assert "\r\n" in txt and D._comando_tarea() == '"%s"' % D.fichero_lanzador()
    env = D.entorno_hijo()
    assert env["PYTHONUTF8"] == "1" and env["PYTHONPATH"].startswith(raiz)
    assert env["COGNIA_BOTS_DIR"] == str(tmp_path / "bots")
    # arranque en fondo: un hijo que muere al instante NO se reporta como lanzado
    lanzados = []

    class _Muerto:
        pid = 4242
        returncode = 1

        def poll(self):
            return 1

    class _Vivo:
        pid = 4343
        returncode = None

        def poll(self):
            return None

    def _popen(args, **kw):
        lanzados.append((args, kw))
        return _popen.proximo
    monkeypatch.setattr(D.subprocess, "Popen", _popen)
    D.fichero_log().write_text("python.exe: No module named cognia.bots\n", encoding="utf-8")
    _popen.proximo = _Muerto()
    r = D.arrancar_en_fondo(espera_s=0)
    assert r["ok"] is False and r["pid"] == 4242
    assert "murio al arrancar" in r["motivo"] and "No module named cognia.bots" in r["motivo"]
    args, kw = lanzados[-1]
    assert args[:3] == [sys.executable, "-m", "cognia.bots"] and "daemon" in args
    assert kw["cwd"] == raiz and kw["env"]["PYTHONUTF8"] == "1"
    assert kw["env"]["COGNIA_BOTS_DIR"] == str(tmp_path / "bots")
    _popen.proximo = _Vivo()
    r = D.arrancar_en_fondo(espera_s=0)
    assert r["ok"] is True and r["pid"] == 4343 and "lanzado" in r["motivo"]
    # con un daemon vivo registrado no lanza otro
    D.fichero_pid().write_text("%d\n" % os.getpid(), encoding="utf-8")
    D.escribir_latido()
    r = D.arrancar_en_fondo(espera_s=0)
    assert r["ok"] is False and "ya hay un daemon" in r["motivo"]


def test_hops_en_curso_llega_a_un_hilo_sin_contextvar_como_el_de_timeout_tool():
    """agent/tools.run_tool corre la tool en un Thread SIN copy_context
    (harness/timeout_tool.correr_con_deadline): ahi la ContextVar vale None.
    E2E real 2026-08-25: beta respondia con hops 0 en vez de 1 mientras el
    test con agente falso (mismo hilo) pasaba. El respaldo de proceso, puesto
    bajo el candado del turno, tiene que verlo igual."""
    import threading
    from cognia.agent import tools as T
    R.crear("ana"); R.crear("beto"); R.crear("caro")
    M.enviar(de="ana", para="beto", texto="ping", hops=1)
    vistos = {}

    def _tool_en_hilo_ajeno(bot, texto, ctx):
        def _w():
            vistos["hops_hilo"] = E.hops_en_curso()
            vistos["activo_hilo"] = R.bot_activo().nombre
            T.sincronizar_mensaje_bot()
            vistos["res"] = T.TOOLS["mensaje_bot"]["fn"]("caro | reenvio", {})
        t = threading.Thread(target=_w)          # sin copy_context, a proposito
        t.start(); t.join(10)
        return "listo"
    E.procesar_inbox("beto", agente=_tool_en_hilo_ajeno, max_hops=4)
    assert vistos["hops_hilo"] == 1 and vistos["activo_hilo"] == "beto"
    assert vistos["res"].startswith("RESULTADO mensaje_bot: enviado")
    assert [m["hops"] for m in M.pendientes("caro")] == [2]
    assert E.hops_en_curso() is None and E._HOPS_TURNO[0] is None


def test_procesar_inbox_no_reenvia_un_turno_fallido():
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping")
    E.procesar_inbox("beto", agente=lambda b, t, c: "(cerrada sin progreso verificado: sin_arranque)\n\nNo se pudo")
    assert M.pendientes("ana") == []
    assert any(q == "meta" and "turno fallido" in t for q, t in _canon("beto"))

    def _rompe(b, t, c):
        raise RuntimeError("boom")
    M.enviar(de="ana", para="beto", texto="ping 2")
    E.procesar_inbox("beto", agente=_rompe)
    assert M.pendientes("ana") == []                      # '[error del turno...' tampoco viaja
    assert E.es_fallo_de_turno("[error del turno de beto: RuntimeError: boom]")
    assert not E.es_fallo_de_turno("todo bien, cerrada la tarea")


# ---------------------------------------------------------------------------
# remate e2e 2026-08-25: el turno entrante lleva instruccion; mensaje_bot es
# resultado util; sin proactividad headless
# ---------------------------------------------------------------------------

def _capturar_agente(monkeypatch, respuesta="ok"):
    """Reemplaza cli._run_agent_task y evita construir Cognia(): devuelve el
    dict donde queda lo que recibio el agente (task, kwargs)."""
    import cognia.cli as cli
    visto = {}

    def _falso(ai, task, print_fn, **kw):
        visto["task"] = task
        visto["kw"] = kw
        return respuesta
    monkeypatch.setattr(cli, "_run_agent_task", _falso)
    monkeypatch.setattr(E, "asegurar_config", lambda: None)
    monkeypatch.setattr(E, "instancia", lambda bot, ai=None: object())
    return visto


def test_turno_entrante_de_bot_lleva_la_nota_con_mensaje_bot_y_silent(monkeypatch):
    """Antes el agente recibia SOLO 'Mensaje de 🤖 beta (@beta): ...' con
    guidance 'Eres alfa, Bot A.': las reglas del protocolo con tool vivian en
    ctx.system_cerebro, que el carril agente no usa. Medido con el 27B: 3/3
    turnos entrantes vagaron (leer/listar/buscar) y cerraron sin_arranque."""
    R.crear("alfa", titulo="Bot A"); R.crear("beta", titulo="Bot B")
    M.enviar(de="beta", para="alfa", texto="Un espejo con sed de olas")
    visto = _capturar_agente(monkeypatch)
    assert E.procesar_inbox("alfa") == 1
    task, kw = visto["task"], visto["kw"]
    nota = E.nota_entrante(R.obtener("beta"))
    # la instruccion PRIMERO (el modelo leia 'TAREA: Mensaje de...' como un
    # encargo sobre el repo), el mensaje despues, y la PISTA del bucle
    assert task.startswith(nota)
    assert task.endswith("\nMensaje de 🤖 beta (@beta): Un espejo con sed de olas")
    assert "mensaje_bot" in nota and "`beta | " in nota and "[SILENT]" in nota
    assert "cierra el turno con responder" in nota and "No explores" in nota
    assert kw["hint"] == "mensaje_bot"
    assert kw["skills"] == {}          # sin auto-skill (commit-git matcheaba un poema)
    # el A/B sigue: guidance es el sufijo corto, sin el protocolo entero
    assert kw["guidance"] == R.sufijo_agente(R.obtener("alfa")) and len(kw["guidance"]) <= 300
    assert "mensaje_bot" in kw["allowed_tools"] and "responder" in kw["allowed_tools"]
    # headless: sin proactividad (nadie lee sugerencias en daemon.log)
    assert kw["proactividad"] is False
    # el canon guarda el texto LIMPIO (la nota es para el modelo)
    entrante = [t for q, t in _canon("alfa") if q == "bot"]
    assert entrante == ["Mensaje de 🤖 beta (@beta): Un espejo con sed de olas"]
    # un envelope que no viene de un bot (usuario por la API): nota sin mensaje_bot
    M.enviar(de="usuario", para="alfa", texto="hola alfa")
    E.procesar_inbox("alfa")
    assert "no es un bot" in visto["task"] and "mensaje_bot" not in visto["task"]
    assert visto["kw"]["hint"] == ""
    assert "no es un bot" in E.nota_entrante("usuario") and "mensaje_bot" not in E.nota_entrante(None)


def test_turno_no_headless_conserva_la_proactividad(monkeypatch):
    R.crear("alfa")
    visto = _capturar_agente(monkeypatch)
    E.correr_turno("alfa", "lista los ficheros del directorio actual", headless=False)
    assert visto["kw"]["proactividad"] is True
    assert visto["kw"]["skills"] is None and visto["kw"]["hint"] == ""   # turno normal: como antes


def test_mensaje_bot_enviado_es_el_resultado_util_aunque_el_bucle_cierre_sin_arranque():
    """mensaje_bot no es 'avance verificado' para el presupuesto por progreso:
    el 27B mandaba el mensaje en el paso 1, seguia 6 pasos y cerraba con
    '(cerrada sin progreso verificado: sin_arranque)'; el canon y el roster
    decian que el turno fallo cuando SI escribio (e2e 2026-08-25)."""
    R.crear("ana"); R.crear("beto")
    M.enviar(de="ana", para="beto", texto="ping")

    def _escribe_y_vaga(bot, texto, ctx):
        M.enviar(de="beto", para="ana", texto="pong por la tool", hops=1)
        return "(cerrada sin progreso verificado: sin_arranque)"
    E.procesar_inbox("beto", agente=_escribe_y_vaga)
    canon = _canon("beto")
    assert ("cognia", "(le escribio a @ana con mensaje_bot)") in canon
    assert any(q == "meta" and t.startswith("(el bucle cerro con: (cerrada sin progreso")
               for q, t in canon)
    assert any(q == "meta" and "ya le escribio a @ana" in t for q, t in canon)
    assert not any("turno fallido" in t for _, t in canon)
    assert [m["texto"] for m in M.pendientes("ana")] == ["pong por la tool"]   # no duplica
    # sin mensaje enviado, el fallo sigue siendo fallo (no se maquilla)
    M.enviar(de="ana", para="beto", texto="ping 2")
    E.procesar_inbox("beto", agente=lambda b, t, c: "(cerrada sin progreso verificado: sin_arranque)")
    assert any(q == "meta" and "turno fallido" in t for q, t in _canon("beto"))
    assert [m["texto"] for m in M.pendientes("ana")] == ["pong por la tool"]
    # resultado_util directo: respuesta buena + mensaje enviado -> se respeta la respuesta
    antes = {e["id"] for e in M.pendientes("ana")}
    M.enviar(de="beto", para="ana", texto="otro")
    assert E.resultado_util("beto", R.obtener("ana"), antes, "todo listo") == ("todo listo", None)
    assert E.resultado_util("beto", R.obtener("ana"), antes, "") == (
        "(le escribio a @ana con mensaje_bot)", None)


def test_daemon_siembra_proactividad_apagada(monkeypatch, capsys):
    """El daemon imprimia '[backend] DEGRADADO: proactividad sin backend LLM'
    tras cada turno con el backend vivo: nadie lee sugerencias en daemon.log."""
    from cognia.bots import __main__ as D
    monkeypatch.delenv("COGNIA_PROACTIVIDAD", raising=False)
    R.crear("ana")
    monkeypatch.setattr(E, "AGENTE_FALSO", _eco())
    assert D.main(["daemon", "--once"]) == 0
    assert os.environ.get("COGNIA_PROACTIVIDAD") == "0"
    import cognia.cli as cli
    assert cli._proactividad_encendida() is False
    monkeypatch.setenv("COGNIA_PROACTIVIDAD", "1")
    assert cli._proactividad_encendida() is True
    # el dueno manda: si ya la fijo, el daemon no la pisa
    monkeypatch.setenv("COGNIA_PROACTIVIDAD", "on")
    D.main(["daemon", "--once"])
    assert os.environ["COGNIA_PROACTIVIDAD"] == "on"
