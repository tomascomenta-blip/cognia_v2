# -*- coding: utf-8 -*-
"""
Tests del CORPUS VIVO del modo RLM (2026-08-18): el contexto que PERSISTE
entre turnos del REPL en vez de ser one-shot sobre una ruta.

POR QUE cada invariante:
- El indice incremental tiene que dar EXACTAMENTE lo mismo que reconstruir.
  Un indice de lineas/offsets que se desvia un char no falla: devuelve el
  rango equivocado en silencio, y ctx_ver/rlm_llamar leerian texto corrido.
  Por eso el test compara ``anexar`` contra ``ContextoRLM(texto_entero)``
  campo a campo, no solo el tamano.
- El coste de anexar tiene que ser del DELTA, no del total. Si crecer costara
  O(total) por turno, el corpus vivo seria O(total*turnos) sobre la sesion —
  el "reloj" que justifica todo el modo se perderia por la puerta de atras.
  El test MIDE (no declara) el ratio contra la reconstruccion.
- La poda tiene que VERSE. Un corpus que encoge callado es el fallo silencioso
  que persigue el repo: se exige que aparezca en ``aviso()``, en ctx_info (la
  primera tool que el modelo llama) y en el informe (lo unico que se imprime
  siempre), y que diga CUANTO y QUE se tiro.
- Nunca dejar el corpus vacio por respetar el techo: el bloque mas nuevo es
  justo el que se esta preguntando.
- El camino de RUTA no se rompe: correr_rlm sin ``contexto`` sigue cargando
  del disco (eso lo cubre test_rlm.py; aca se verifica que el parametro nuevo
  es opcional y que un corpus vivo VACIO se declara en vez de correr).

Sin GPU y sin modelo: completar_fn inyectado con RespuestaChat guionadas,
igual que test_rlm.py.
"""
import time

from cognia.agent import rlm
from cognia.agent.chat_client import RespuestaChat, ToolCall


# ── helpers ────────────────────────────────────────────────────────────

def _turnos(n, largo=200, desde=1):
    return [{"role": "user" if i % 2 else "assistant",
             "content": f"turno numero {i} " + "z" * largo}
            for i in range(desde, desde + n)]


def _ctx(estado):
    return {"_rlm": estado, "working_memory": {}, "agent_state": {},
            "print_fn": lambda *a, **k: None}


def _estado_de(contexto):
    med = rlm.MedidorContexto(
        ctx_chars=contexto.chars, ctx_lineas=len(contexto.lineas),
        origen=contexto.origen, n_ctx=32768,
        aviso_corpus=contexto.aviso())
    return rlm.EstadoRLM(
        contexto=contexto, medidor=med,
        completar_fn=lambda *a, **k: None,
        perfil={"url": "http://127.0.0.1:9", "temperature": 0.7,
                "top_p": 0.8})


def _sin_backend(monkeypatch):
    import cognia.backend_activo as ba
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})


# ── 1. el indice incremental es IDENTICO al reconstruido ───────────────

def test_anexar_da_el_mismo_indice_que_reconstruir():
    """Si el indice incremental se desviara, ctx_ver leeria otro texto sin
    que nada falle: se compara campo a campo, no solo el tamano."""
    piezas = ["alfa\nbeta\n", "gamma\ndelta\n", "sin salto final",
              "\nepsilon\n", ""]
    inc = rlm.ContextoRLM("", "test")
    for p in piezas:
        inc.anexar(p)
    entero = rlm.ContextoRLM("".join(piezas), "test")
    assert inc.texto == entero.texto
    assert inc.chars == entero.chars
    assert inc.lineas == entero.lineas
    assert inc._offsets == entero._offsets
    # Y el rango de chars (lo que usan ctx_ver / rlm_llamar) coincide.
    for i in range(1, len(entero.lineas) + 1):
        assert inc.rango_chars(i, i) == entero.rango_chars(i, i)


def test_anexar_vacio_no_toca_nada():
    c = rlm.ContextoRLM("hola\nmundo", "test")
    antes = (c.chars, list(c.lineas), list(c._offsets))
    assert c.anexar("") == 0
    assert (c.chars, c.lineas, c._offsets) == antes


# ── 2. el corpus vivo crece entre turnos ───────────────────────────────

def test_corpus_vivo_crece_y_dedupea_por_ordinal():
    vivo = rlm.ContextoVivo(origen="sesion test")
    assert vivo.chars == 0
    r1 = rlm.sembrar_vivo(vivo, turnos=_turnos(3))
    assert r1["turnos"] == 3
    chars_1 = vivo.chars
    # Re-sembrar la MISMA lista no duplica (dedup por ordinal).
    r2 = rlm.sembrar_vivo(vivo, turnos=_turnos(3))
    assert r2["turnos"] == 0 and vivo.chars == chars_1
    # La lista crece: entra solo el delta.
    r3 = rlm.sembrar_vivo(vivo, turnos=_turnos(5))
    assert r3["turnos"] == 2 and vivo.chars > chars_1
    assert vivo.turnos == 5 and len(vivo.bloques) == 5


def test_corpus_vivo_es_grepeable_por_las_tools():
    """El punto entero: lo que se dijo en la sesion se ENCUENTRA con las
    tools del RLM sin que el texto pase por la ventana."""
    vivo = rlm.ContextoVivo(origen="sesion test")
    rlm.sembrar_vivo(vivo, turnos=_turnos(20))
    vivo.anexar_turno("user", "acordamos el presupuesto AGUJA_VIVA_7")
    estado = _estado_de(vivo)
    salida = rlm._ctx_grep("AGUJA_VIVA_7", _ctx(estado))
    assert "AGUJA_VIVA_7" in salida and "ERROR" not in salida.splitlines()[0]
    # Y ctx_info declara que el corpus es la SESION, no un fichero.
    info = rlm._ctx_info("", _ctx(estado))
    assert "corpus VIVO de la sesion" in info
    assert "21 turnos" in info


def test_archivo_tocado_entra_y_se_dedupea_por_mtime(tmp_path):
    f = tmp_path / "modulo.py"
    f.write_text("def hola():\n    return 'MARCA_ARCHIVO'\n", encoding="utf-8")
    vivo = rlm.ContextoVivo(origen="sesion test")
    r = vivo.anexar_archivo(str(f))
    assert r["anexado"] and vivo.archivos == 1
    assert "MARCA_ARCHIVO" in vivo.texto
    # Mismo fichero sin cambios: no entra otra vez.
    assert vivo.anexar_archivo(str(f))["anexado"] is False
    # Editado (mtime + tamano distintos): entra como bloque NUEVO, las dos
    # versiones quedan en el log de la sesion.
    time.sleep(1.1)     # el mtime de la clave se trunca a segundos
    f.write_text("def hola():\n    return 'MARCA_ARCHIVO_V2'\n",
                 encoding="utf-8")
    assert vivo.anexar_archivo(str(f))["anexado"] is True
    assert "MARCA_ARCHIVO_V2" in vivo.texto and "MARCA_ARCHIVO'" in vivo.texto


def test_archivo_inexistente_no_lanza_y_SE_DECLARA():
    """Un fichero que no entro no puede desaparecer: 'no entro' y 'no habia
    nada' piden decisiones distintas."""
    vivo = rlm.ContextoVivo(origen="sesion test")
    r = vivo.anexar_archivo("no_existe_jamas_12345.txt")
    assert r["anexado"] is False and r["motivo"]
    assert vivo.chars == 0
    assert len(vivo.saltados) == 1
    assert "NO entraron 1 ficheros" in vivo.aviso()
    assert "no_existe_jamas_12345.txt" in vivo.aviso()


def test_binario_y_gigante_se_saltan_declarados(tmp_path):
    bina = tmp_path / "bin.dat"
    bina.write_bytes(b"cabecera\x00\x01\x02" + b"x" * 100)
    vivo = rlm.ContextoVivo(origen="sesion test")
    assert vivo.anexar_archivo(str(bina))["motivo"] == "binario"
    assert [s["motivo"] for s in vivo.saltados] == ["binario"]
    # 'ya ingerido' NO es un salto: no falto nada.
    ok = tmp_path / "ok.txt"
    ok.write_text("contenido", encoding="utf-8")
    vivo.anexar_archivo(str(ok))
    vivo.anexar_archivo(str(ok))
    assert len(vivo.saltados) == 1 and vivo.saltados_total == 1
    # La LISTA se capa por memoria, el CONTADOR no: un aviso que dijera 12
    # con 40 saltados mentiria por recorte.
    for i in range(40):
        vivo.anexar_archivo(f"no_existe_{i}.txt")
    assert vivo.saltados_total == 41 and len(vivo.saltados) <= 12
    assert "NO entraron 41 ficheros" in vivo.aviso()


def test_el_aviso_cuadra_con_los_bloques():
    """Los bloques del corpus tienen que sumar: turnos + comandos +
    archivos. Un contador que no cuadra es un hueco invisible."""
    vivo = rlm.ContextoVivo(origen="sesion test")
    rlm.sembrar_vivo(vivo, turnos=_turnos(3))
    vivo.anexar_comando(0, "/hacer algo", "hecho")
    vivo.anexar_comando(1, "/rlm que paso", "paso esto")
    assert vivo.turnos == 3 and vivo.comandos == 2 and vivo.archivos == 0
    assert len(vivo.bloques) == vivo.turnos + vivo.comandos + vivo.archivos
    assert "3 turnos, 2 comandos, 0 archivos" in vivo.aviso()
    # Dedup por indice: re-ingerir el mismo comando no duplica.
    assert vivo.anexar_comando(0, "/hacer algo", "hecho")["anexado"] is False
    assert vivo.comandos == 2


# ── 3. el coste de anexar es del DELTA ─────────────────────────────────

def test_costo_de_anexar_es_del_delta():
    """MEDIDO, no declarado: anexar un turno a un corpus grande tiene que
    costar mucho menos que reconstruirlo. Umbral flojo (5x) porque es una
    medicion de pared en una maquina compartida; el punto es que la
    diferencia sea de orden, no un porcentaje."""
    bloque = ("linea de relleno " + "y" * 80 + "\n") * 20000   # ~2 MB
    vivo = rlm.ContextoVivo(origen="sesion test", max_chars=10 ** 9)
    vivo.anexar_bloque("base", "BASE", bloque)
    assert vivo.chars > 1_000_000
    turno = "turno nuevo " + "w" * 500

    # Reconstruir (lo que costaria sin indice incremental).
    t0 = time.perf_counter()
    rlm.ContextoRLM(vivo.texto + turno, "test")
    t_rebuild = time.perf_counter() - t0

    # Anexar (lo que cuesta con el).
    t0 = time.perf_counter()
    vivo.anexar_turno("user", turno)
    t_anexar = time.perf_counter() - t0

    assert t_anexar * 5 < t_rebuild, (
        f"anexar {t_anexar * 1000:.2f} ms vs reconstruir "
        f"{t_rebuild * 1000:.2f} ms: el indice incremental no esta ganando")


# ── 4. el techo: que se tira y QUIEN lo dice ───────────────────────────

def test_poda_tira_los_mas_viejos_y_lo_declara():
    vivo = rlm.ContextoVivo(origen="sesion test", max_chars=3000)
    # Cada turno son ~520 chars de cuerpo + cabecera: entran ~5.
    rlm.sembrar_vivo(vivo, turnos=_turnos(20, largo=500))
    assert vivo.chars <= 3000
    assert vivo.podados > 0
    # Se fueron los VIEJOS: el turno 1 ya no esta, el ultimo si.
    assert "turno numero 1 " not in vivo.texto
    assert "turno numero 20 " in vivo.texto
    av = vivo.aviso()
    assert "PODADO" in av
    assert f"{vivo.podados} bloques" in av
    assert "TURNO" in av      # dice QUE se tiro, no solo cuantos
    # Y el indice sigue sano tras podar (offsets rebasados).
    espejo = rlm.ContextoRLM(vivo.texto, "test")
    assert vivo.lineas == espejo.lineas and vivo._offsets == espejo._offsets


def test_poda_nunca_deja_el_corpus_vacio():
    """Un solo bloque mas grande que el techo se CONSERVA y el aviso lo
    dice: tirar lo ultimo que se dijo para respetar un numero seria peor."""
    vivo = rlm.ContextoVivo(origen="sesion test", max_chars=100)
    vivo.anexar_turno("user", "x" * 5000)
    assert vivo.chars > 100 and len(vivo.bloques) == 1
    assert "supera el techo" in vivo.aviso()
    # Con un segundo bloque, el viejo se va y el nuevo se queda igual.
    vivo.anexar_turno("user", "AGUJA_ULTIMA")
    assert "AGUJA_ULTIMA" in vivo.texto and len(vivo.bloques) == 1


def test_la_poda_se_ve_en_ctx_info_y_en_el_informe():
    """El aviso tiene que llegar por los DOS canales: ctx_info (lo primero
    que el modelo mira) y el informe (lo unico que se imprime siempre)."""
    vivo = rlm.ContextoVivo(origen="sesion test", max_chars=3000)
    rlm.sembrar_vivo(vivo, turnos=_turnos(20, largo=500))
    estado = _estado_de(vivo)
    info = rlm._ctx_info("", _ctx(estado))
    assert "PODADO" in info
    informe = estado.medidor.informe()
    assert informe.startswith("[contexto efectivo RLM]")
    assert "PODADO" in informe
    assert estado.medidor.como_dict()["aviso_corpus"]


def test_techo_por_env(monkeypatch):
    monkeypatch.setenv("COGNIA_RLM_VIVO_MAX_CHARS", "1500")
    vivo = rlm.ContextoVivo(origen="sesion test")
    assert vivo.max_chars == 1500
    rlm.sembrar_vivo(vivo, turnos=_turnos(10, largo=400))
    assert vivo.chars <= 1500 and vivo.podados > 0


# ── 5. correr_rlm con contexto inyectado (y sin romper el de ruta) ─────

def _tc(nombre, argumentos):
    return ToolCall(id=f"t_{nombre}", nombre=nombre, argumentos=argumentos,
                    argumentos_crudos="{}")


def test_correr_rlm_usa_el_corpus_vivo_sin_tocar_disco(monkeypatch):
    _sin_backend(monkeypatch)
    vivo = rlm.ContextoVivo(origen="sesion abc12345")
    rlm.sembrar_vivo(vivo, turnos=_turnos(40, largo=300))
    vivo.anexar_turno("user", "el presupuesto quedo en CLAVE_SESION_9")

    guion = iter([
        RespuestaChat(texto="", finish_reason="tool_calls",
                      usage={"prompt_tokens": 500, "completion_tokens": 20},
                      tool_calls=[_tc("ctx_grep",
                                      {"patron": "CLAVE_SESION_9"})]),
        RespuestaChat(texto="Quedo en CLAVE_SESION_9.", finish_reason="stop",
                      usage={"prompt_tokens": 800, "completion_tokens": 20}),
    ])
    mensajes_vistos = []

    def _completar(mensajes, **kw):
        mensajes_vistos.append(mensajes)
        return next(guion)

    res = rlm.correr_rlm("en cuanto quedo el presupuesto?",
                         completar_fn=_completar, contexto=vivo,
                         url="http://127.0.0.1:9")
    assert res["ok"] and "CLAVE_SESION_9" in res["texto"]
    assert res["medidor"]["origen"] == "sesion abc12345"
    assert res["informe"].startswith("[contexto efectivo RLM]")
    # El system DICE que el corpus es la sesion.
    sys_msg = mensajes_vistos[0][0]
    assert sys_msg["role"] == "system"
    assert "corpus VIVO de la sesion" in sys_msg["content"]
    # INVARIANTE de siempre: el corpus entero jamas viajo en un message.
    for llamada in mensajes_vistos:
        for m in llamada:
            assert vivo.texto not in str(m.get("content", ""))


def test_corpus_vivo_vacio_se_declara_en_vez_de_correr():
    """0 chars no es 'no encontro nada': se dice y no se gasta la GPU."""
    vivo = rlm.ContextoVivo(origen="sesion vacia")

    def _no_llamar(*a, **k):
        raise AssertionError("no debia llamarse al modelo con corpus vacio")

    res = rlm.correr_rlm("que dijimos?", completar_fn=_no_llamar,
                         contexto=vivo)
    assert res["ok"] is False and "VAC" in res["texto"].upper()
    assert res["pasos"] == 0


def test_camino_de_ruta_sigue_funcionando(tmp_path):
    """El parametro nuevo es OPCIONAL: sin el, correr_rlm carga del disco
    como siempre (y degrada igual si la ruta no existe)."""
    res = rlm.correr_rlm("pregunta", str(tmp_path / "no_existe.txt"),
                         completar_fn=lambda *a, **k: None)
    assert res["ok"] is False and "ERROR cargando el contexto" in res["texto"]


# ── 6. el cableado del CLI (parseo + helper del corpus) ────────────────

def test_parseo_de_rlm_ruta_vs_pregunta(tmp_path):
    """El disparador es que el token EXISTA, no que 'parezca' ruta: sin esto
    '/rlm que dijimos de rlm.py?' se iria al camino de fichero y devolveria
    un error de carga en vez de una respuesta."""
    from cognia import cli
    f = tmp_path / "log.txt"
    f.write_text("hola", encoding="utf-8")
    # Ruta real + pregunta.
    assert cli._rlm_parsear(f"{f} que dice?") == (str(f), "que dice?")
    # Pregunta pura -> corpus vivo (ruta vacia).
    assert cli._rlm_parsear("que decidimos sobre rlm.py?") == \
        ("", "que decidimos sobre rlm.py?")
    assert cli._rlm_parsear("de que hablamos?") == ("", "de que hablamos?")
    # Comillas = ruta SIEMPRE, aunque no exista (lo explicito gana).
    assert cli._rlm_parsear('"C:\\no\\existe.txt" que dice?') == \
        ("C:\\no\\existe.txt", "que dice?")
    # Ruta sin pregunta -> pregunta vacia (el REPL muestra el uso).
    assert cli._rlm_parsear(str(f)) == (str(f), "")
    assert cli._rlm_parsear("") == ("", "")


def test_helper_del_cli_crece_incremental(tmp_path, monkeypatch):
    """El corpus del REPL se siembra de _history + _session_log y crece por
    DELTA: la segunda llamada no reingiere lo de la primera."""
    from cognia import cli
    monkeypatch.setattr(cli, "_RLM_VIVO", None)
    monkeypatch.setattr(cli, "_RLM_VIVO_HIST", 0)
    monkeypatch.setattr(cli, "_RLM_VIVO_SLASH", 0)
    monkeypatch.setattr(cli, "_RLM_VIVO_ARCH", set())
    monkeypatch.setattr(cli, "_SESSION_ID", "abcdef123456")
    monkeypatch.setattr(cli, "_SESSION_CWD", str(tmp_path))
    # Sin ficheros tocados: se apunta HOME a un tmp vacio.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_history",
                        [{"role": "user", "content": "hola MARCA_UNO"}])
    monkeypatch.setattr(cli, "_session_log",
                        [{"input": "/hacer x", "output": "MARCA_DOS"}])

    vivo, d1 = cli._rlm_corpus_vivo()
    assert d1["turnos"] == 1 and d1["comandos"] == 1
    assert "MARCA_UNO" in vivo.texto and "MARCA_DOS" in vivo.texto
    assert d1["ms"] >= 0

    # Nada nuevo: delta cero y el MISMO objeto (no se reconstruye).
    vivo2, d2 = cli._rlm_corpus_vivo()
    assert vivo2 is vivo
    assert (d2["turnos"], d2["comandos"], d2["chars"]) == (0, 0, 0)

    # Llega un turno: entra solo el.
    cli._history.append({"role": "assistant", "content": "chau MARCA_TRES"})
    _v3, d3 = cli._rlm_corpus_vivo()
    assert d3["turnos"] == 1 and "MARCA_TRES" in vivo.texto
    assert vivo.turnos == 2 and vivo.comandos == 1


def test_semilla_profunda_de_chat_history_sin_duplicar():
    """El corpus baja de chat_history MUCHO mas hondo que los 20 mensajes que
    el REPL restaura para el prompt — y no duplica el solape."""
    from cognia import cli

    class _CH:
        def get_recent_turns(self, n=20):
            return [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"viejo {i}"} for i in range(10)]

    class _AI:
        chat_history = _CH()

    # _history trae restaurados los 4 ultimos (el prefijo que se solapa).
    hist = [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"viejo {i}"} for i in range(6, 10)]
    assert cli._solape_turnos(_CH().get_recent_turns(), hist) == 4

    cli._RLM_VIVO = None
    cli._RLM_VIVO_HIST = 0
    cli._RLM_VIVO_SLASH = 0
    cli._RLM_VIVO_ARCH = set()
    _h, _s = list(cli._history), list(cli._session_log)
    try:
        cli._history[:] = hist
        cli._session_log[:] = []
        vivo, d = cli._rlm_corpus_vivo(_AI())
        # 6 previos (0..5) + 4 de _history = 10 turnos, ni uno repetido.
        assert d["previos"] == 6 and d["turnos"] == 4
        assert vivo.turnos == 10
        assert vivo.texto.count("viejo 7") == 1
        assert "viejo 0" in vivo.texto and "viejo 9" in vivo.texto
        # Y se ve de donde viene cada uno.
        assert "(user, previo)" in vivo.texto
    finally:
        cli._history[:] = _h
        cli._session_log[:] = _s
        cli._RLM_VIVO = None
        cli._RLM_VIVO_HIST = 0
        cli._RLM_VIVO_SLASH = 0
        cli._RLM_VIVO_ARCH = set()


def test_solape_sin_solape_ni_listas_vacias():
    from cognia import cli
    a = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    b = [{"role": "user", "content": "z"}]
    assert cli._solape_turnos(a, b) == 0
    assert cli._solape_turnos([], b) == 0 and cli._solape_turnos(a, []) == 0
    # Solape total: la lista viva es exactamente la cola de la previa.
    assert cli._solape_turnos(a, a) == 2


def test_contexto_estatico_no_tiene_aviso():
    """El aviso es del corpus vivo: un ContextoRLM de fichero no ensucia el
    informe con una linea fija."""
    c = rlm.ContextoRLM("hola\nmundo", "fichero")
    assert c.aviso() == ""
    med = rlm.MedidorContexto(ctx_chars=c.chars, ctx_lineas=2,
                              origen="fichero", n_ctx=32768,
                              aviso_corpus=c.aviso())
    assert "corpus VIVO" not in med.informe()
