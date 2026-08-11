# -*- coding: utf-8 -*-
"""
Tests del modo RLM (contexto largo por tools, contrato congelado 2026-08-11).

POR QUE cada invariante:
- Fusion de solapes en MedidorContexto: releer el mismo rango N veces no
  puede inflar la cobertura — el informe es la evidencia de cuanto contexto
  se vio DE VERDAD, y una cobertura inflada es el modo de fallo clasico de
  medir con el instrumento torcido (leccion 'el contrafactual es la unica
  defensa').
- Caps de vista (MAX_CHARS_VISTA) y registro de SOLO lo devuelto: si la tool
  registrara como visto texto que recorto, el medidor mentiria; y si no
  capara, el raiz se cargaria el contexto a la ventana por la puerta de
  atras, que es exactamente lo que el modo evita.
- Guardas de rlm_llamar (fan-out / presupuesto / trozo) con mensaje propio:
  el raiz tiene que saber QUE ajustar; un ERROR generico lo deja adivinando.
- Profundidad 1 ESTRUCTURAL: el hijo no recibe kwarg tools — no es un prompt
  pidiendo portarse bien, es que el server jamas se las ofrece. Se testea
  capturando los kwargs reales del completar inyectado.
- INVARIANTE central: el texto completo del contexto JAMAS viaja en un
  message del raiz. Si viajara, el modo entero seria teatro (el contexto
  "externo" estaria en la ventana igual). El contexto de test supera
  4*MAX_CHARS_VISTA para que el assert sea probatorio y no vacuo.
- El informe sale SIEMPRE, aun con ok=False: medir es parte del contrato,
  no un premio del camino feliz.
- Exencion ACI: sin ella aci_trim recorta a 1800 chars una vista que la tool
  ya capo a 8000 con criterio propio, y el modelo veria texto que no existe.

Sin modelo real: completar_fn SIEMPRE inyectado con RespuestaChat guionadas
(patron _correr de test_agente_nativo.py) y URLs muertas http://127.0.0.1:9.
Sin importlib.reload de tools: recargar el modulo vacia el registry que otros
modulos poblaron al importarse (bug conocido, ver test_a3_catalogo_tools).
"""
import re

import pytest

from cognia.agent import rlm
from cognia.agent import tools as T
from cognia.agent.chat_client import RespuestaChat, ToolCall


# ── helpers ────────────────────────────────────────────────────────────

def _no_llamar(*a, **k):
    raise AssertionError("completar_fn no debia llamarse en este caso")


def _estado(texto, completar_fn=_no_llamar, max_hijos=16,
            presupuesto_tokens=120000, hijo_max_tokens=2048):
    """EstadoRLM armado a mano sobre un texto sintetico (sin correr_rlm:
    estos tests apuntan a las tools, no al runner)."""
    contexto = rlm.ContextoRLM(texto, "test")
    medidor = rlm.MedidorContexto(
        ctx_chars=contexto.chars, ctx_lineas=len(contexto.lineas),
        origen="test", n_ctx=32768, max_hijos=max_hijos,
        presupuesto_tokens=presupuesto_tokens)
    return rlm.EstadoRLM(
        contexto=contexto, medidor=medidor, completar_fn=completar_fn,
        perfil={"url": "http://127.0.0.1:9", "temperature": 0.7,
                "top_p": 0.8},
        max_hijos=max_hijos, presupuesto_tokens=presupuesto_tokens,
        hijo_max_tokens=hijo_max_tokens)


def _ctx(estado=None):
    """ctx minimo del bucle (patron _ctx de test_a3_catalogo_tools)."""
    c = {"working_memory": {}, "agent_state": {},
         "print_fn": lambda *a, **k: None}
    if estado is not None:
        c["_rlm"] = estado
    return c


def _lineas(n, largo=100, marca=None):
    """Texto sintetico de n lineas de `largo` chars; marca opcional
    {num_linea: sufijo} para plantar agujas en lineas conocidas."""
    filas = []
    for i in range(1, n + 1):
        base = f"linea {i:05d} " + "x" * largo
        if marca and i in marca:
            base = base[:largo - len(marca[i]) - 1] + " " + marca[i]
        filas.append(base[:largo])
    return "\n".join(filas)


# ── 1. MedidorContexto fusiona solapes ─────────────────────────────────

def test_medidor_fusiona_solapes():
    """0-100 + 50-150 son 150 chars vistos, no 200: el solape se colapsa."""
    med = rlm.MedidorContexto(ctx_chars=1000)
    med.ver_raiz(0, 100)
    med.ver_raiz(50, 150)
    d = med.como_dict()
    assert d["visto_raiz_chars"] == 150
    assert med.cobertura_raiz() == pytest.approx(0.15)
    # La union raiz+hijos tambien fusiona a traves de las dos listas.
    med.ver_hijo(100, 200)
    assert med.como_dict()["visto_union_chars"] == 200
    assert med.cobertura_union() == pytest.approx(0.20)


def test_medidor_cobertura_cero_sin_contexto():
    # Contexto vacio: 0.0 y no ZeroDivisionError (correr_rlm puede cargar
    # un directorio sin archivos de texto).
    med = rlm.MedidorContexto(ctx_chars=0)
    assert med.cobertura_raiz() == 0.0


# ── 2. ctx_ver capa a MAX_CHARS_VISTA y registra SOLO lo devuelto ──────

def test_ctx_ver_capa_y_registra_solo_lo_devuelto():
    estado = _estado(_lineas(300))          # ~30.300 chars > MAX_CHARS_VISTA
    out = T.run_tool("ctx_ver", "1 | 300", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert "[recortado: devueltas lineas" in out
    m = re.search(r"RESULTADO ctx_ver \[lineas (\d+)-(\d+)\]", out)
    assert m, out[:200]
    desde, fin = int(m.group(1)), int(m.group(2))
    assert desde == 1 and fin < 300         # no devolvio el rango pedido
    # Visto == exactamente los chars de las lineas devueltas, ni una mas:
    # registrar el rango PEDIDO inflaria la cobertura con texto no visto.
    ini_ch, fin_ch = estado.contexto.rango_chars(desde, fin)
    assert estado.medidor.como_dict()["visto_raiz_chars"] == fin_ch - ini_ch
    assert fin_ch - ini_ch <= rlm.MAX_CHARS_VISTA


def test_ctx_ver_rango_invalido_es_error_con_rango_valido():
    estado = _estado(_lineas(10))
    out = T.run_tool("ctx_ver", "5 | 99", _ctx(estado))
    assert "ERROR" in out[:120]
    assert "1-10" in out                    # le dice el rango valido
    assert estado.medidor.como_dict()["visto_raiz_chars"] == 0


# ── 3. ctx_grep: patron invalido y cap de matches ──────────────────────

def test_ctx_grep_patron_invalido_error_legible():
    estado = _estado(_lineas(5))
    out = T.run_tool("ctx_grep", "(", _ctx(estado))
    assert "ERROR" in out[:120]
    assert "regex" in out                   # legible, no un traceback


def test_ctx_grep_capa_matches_y_reporta_los_que_quedan():
    # 200 lineas matchean; se muestran MAX_MATCHES_GREP y se DICE cuantas
    # quedaron (callarselo haria creer al raiz que ya vio todo). Lineas
    # CORTAS a proposito: con lineas largas el cap de chars corta antes que
    # el de matches y este test dejaria de apuntar a lo que dice apuntar.
    estado = _estado(_lineas(200, largo=25,
                             marca={i: "AGUJA" for i in range(1, 201)}))
    out = T.run_tool("ctx_grep", "AGUJA", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert f"{rlm.MAX_MATCHES_GREP} de 200 matches" in out
    assert f"[... {200 - rlm.MAX_MATCHES_GREP} matches mas" in out


# ── 4. rlm_llamar: las tres guardas + errores del hijo ─────────────────

def _hijo_ok(texto="respuesta del hijo", finish="stop"):
    return RespuestaChat(texto=texto, finish_reason=finish,
                         usage={"prompt_tokens": 100,
                                "completion_tokens": 20})


def test_rlm_llamar_fanout_agotado():
    llamadas = []

    def _completar(mensajes, **kw):
        llamadas.append(kw)
        return _hijo_ok()

    estado = _estado(_lineas(50), completar_fn=_completar, max_hijos=1)
    ok = T.run_tool("rlm_llamar", "1 | 10 | que dice?", _ctx(estado))
    assert "ERROR" not in ok[:120] and len(llamadas) == 1
    # La llamada max_hijos+1 se corta ANTES de tocar el modelo.
    err = T.run_tool("rlm_llamar", "11 | 20 | y aca?", _ctx(estado))
    assert "ERROR" in err[:120]
    assert "limite de 1 subllamadas agotado" in err
    assert len(llamadas) == 1


def test_rlm_llamar_presupuesto_agotado():
    estado = _estado(_lineas(50), presupuesto_tokens=10)
    # El gasto ya hecho (aunque sea del raiz) cuenta contra el presupuesto.
    estado.medidor.registrar_raiz({"prompt_tokens": 40,
                                   "completion_tokens": 10})
    out = T.run_tool("rlm_llamar", "1 | 10 | que dice?", _ctx(estado))
    assert "ERROR" in out[:120]
    assert "presupuesto RLM de 10 tokens agotado (llevas 50)" in out


def test_rlm_llamar_trozo_gigante():
    estado = _estado(_lineas(700))          # ~70.700 chars > MAX_CHARS_TROZO
    out = T.run_tool("rlm_llamar", "1 | 700 | resumi todo", _ctx(estado))
    assert "ERROR" in out[:120]
    assert f"supera el limite de {rlm.MAX_CHARS_TROZO}" in out
    assert "ctx_partir" in out              # le dice QUE ajustar


def test_rlm_llamar_error_del_hijo_se_propaga():
    estado = _estado(
        _lineas(50),
        completar_fn=lambda m, **kw: RespuestaChat(error="HTTP 503 de :9"))
    out = T.run_tool("rlm_llamar", "1 | 10 | que dice?", _ctx(estado))
    assert "ERROR" in out[:120] and "HTTP 503" in out
    # Un hijo fallido no consume el cupo: no hubo respuesta que medir.
    assert estado.medidor.llamadas_hijo == 0


def test_rlm_llamar_finish_length_avisa_truncado():
    # Los dos modos de fallo (respuesta corta legitima vs degollada por
    # max_tokens) se ven iguales sin el aviso (leccion stop_type/usage).
    estado = _estado(_lineas(50),
                     completar_fn=lambda m, **kw: _hijo_ok(
                         "parcial...", finish="length"))
    out = T.run_tool("rlm_llamar", "1 | 10 | que dice?", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert "[respuesta del hijo truncada por max_tokens]" in out


def test_rlm_llamar_pregunta_con_pipe_llega_entera():
    """maxsplit=2: la pregunta es contenido libre y '|' no la parte."""
    visto = {}

    def _completar(mensajes, **kw):
        visto["user"] = mensajes[-1]["content"]
        return _hijo_ok()

    estado = _estado(_lineas(50), completar_fn=_completar)
    out = T.run_tool("rlm_llamar", "1 | 10 | busca 'a | b' en el texto",
                     _ctx(estado))
    assert "ERROR" not in out[:120]
    assert "busca 'a | b' en el texto" in visto["user"]


# ── 5. Profundidad 1: el hijo se llama SIN kwarg tools ─────────────────

def test_hijo_sin_tools_estructural():
    capturado = {}

    def _completar(mensajes, **kw):
        capturado["kwargs"] = kw
        capturado["mensajes"] = mensajes
        return _hijo_ok()

    estado = _estado(_lineas(50), completar_fn=_completar,
                     hijo_max_tokens=2048)
    out = T.run_tool("rlm_llamar", "5 | 15 | que dice?", _ctx(estado))
    assert "ERROR" not in out[:120]
    kw = capturado["kwargs"]
    # La guarda del contrato: sin tools el server jamas se las ofrece — la
    # profundidad 1 no depende de que el hijo "se porte bien".
    assert "tools" not in kw
    assert kw["via"] == "rlm_hijo"
    assert kw["razonador"] is True
    assert kw["max_tokens"] == 2048
    # Mensajes FRESCOS (system + user), no la conversacion del raiz.
    assert [m["role"] for m in capturado["mensajes"]] == ["system", "user"]
    assert estado.medidor.llamadas_hijo == 1
    assert estado.medidor.cobertura_hijos() > 0


# ── 6 + 7. correr_rlm e2e guionado + INVARIANTE de la ventana ──────────

def _sin_backend(monkeypatch):
    """props() sin red: perfil degradado -> correr_rlm usa su fallback."""
    import cognia.backend_activo as ba
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})


def _tc(nombre, argumentos):
    return ToolCall(id=f"t_{nombre}", nombre=nombre, argumentos=argumentos,
                    argumentos_crudos="{}")


def _paso_tool(nombre, argumentos):
    return RespuestaChat(texto="", finish_reason="tool_calls",
                         usage={"prompt_tokens": 500,
                                "completion_tokens": 50},
                         tool_calls=[_tc(nombre, argumentos)])


def test_correr_rlm_e2e_guionado_y_ventana_sellada(tmp_path, monkeypatch):
    """El raiz hace ctx_grep -> rlm_llamar -> cierra en prosa; y NINGUN
    message del raiz contiene el texto completo del contexto."""
    _sin_backend(monkeypatch)
    for var in ("COGNIA_RLM_MAX_HIJOS", "COGNIA_RLM_PRESUPUESTO",
                "COGNIA_RLM_HIJO_TOKENS"):
        monkeypatch.delenv(var, raising=False)
    # > 4*MAX_CHARS_VISTA para que el invariante sea probatorio: con un
    # contexto chico el texto no cabria en ningun message y el assert
    # pasaria vacio.
    texto = _lineas(400, marca={200: "CLAVE_QQQ"})
    assert len(texto) > 4 * rlm.MAX_CHARS_VISTA
    ruta = tmp_path / "contexto.txt"
    ruta.write_text(texto, encoding="utf-8")

    guion_raiz = iter([
        _paso_tool("ctx_grep", {"patron": "CLAVE_QQQ"}),
        _paso_tool("rlm_llamar", {"desde": 150, "hasta": 250,
                                  "pregunta": "cual es la clave?"}),
        RespuestaChat(texto="La clave es CLAVE_QQQ (linea 200).",
                      finish_reason="stop",
                      usage={"prompt_tokens": 900,
                             "completion_tokens": 30}),
    ])
    todos_los_mensajes = []

    def _completar(mensajes, **kw):
        todos_los_mensajes.append(mensajes)
        if kw.get("via") == "rlm_hijo":
            return _hijo_ok("la clave es CLAVE_QQQ")
        return next(guion_raiz)

    res = rlm.correr_rlm("cual es la clave?", str(ruta),
                         completar_fn=_completar,
                         url="http://127.0.0.1:9")
    assert res["ok"] and "CLAVE_QQQ" in res["texto"]
    med = res["medidor"]
    assert med["llamadas_hijo"] == 1
    assert med["cobertura_raiz"] > 0
    assert med["cobertura_hijos"] > 0
    assert med["cobertura_union"] >= med["cobertura_hijos"]
    # La ventana pico sale del usage REAL guionado, no de len//4.
    assert med["ventana_pico_raiz"] == 900
    assert res["informe"].startswith("[contexto efectivo RLM]")
    assert med["origen"] == str(ruta)       # el informe dice DE DONDE salio
    # INVARIANTE: el contexto entero jamas viajo en un message (ni del
    # raiz ni del hijo: el hijo ve UN fragmento, nunca el todo).
    assert todos_los_mensajes
    for llamada in todos_los_mensajes:
        for m in llamada:
            assert texto not in str(m.get("content", ""))


# ── 8. informe presente aun con ok=False ───────────────────────────────

def test_correr_rlm_informe_sale_aun_en_error(tmp_path, monkeypatch):
    _sin_backend(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_text(_lineas(30), encoding="utf-8")
    res = rlm.correr_rlm(
        "pregunta", str(ruta),
        completar_fn=lambda m, **kw: RespuestaChat(error="HTTP 503 de :9"),
        url="http://127.0.0.1:9")
    assert res["ok"] is False
    # Medir no es un premio del camino feliz: el informe sale IGUAL.
    assert res["informe"].startswith("[contexto efectivo RLM]")
    assert res["medidor"]["ctx_chars"] > 0


def test_correr_rlm_ruta_inexistente_degrada_sin_lanzar(tmp_path):
    res = rlm.correr_rlm("pregunta", str(tmp_path / "no_existe.txt"),
                         completar_fn=_no_llamar)
    assert res["ok"] is False and "ERROR" in res["texto"]
    assert res["informe"] == "" and res["medidor"] == {}


# ── 9. Registro en TOOLS + gate de modo no activo ──────────────────────

def test_las_cinco_tools_registradas_y_gateadas():
    # Import normal, sin reload (recargar tools vacia el registry que otros
    # modulos poblaron al importarse: contaminacion conocida, ver test_a3).
    assert rlm.RLM_TOOLS <= set(T.TOOLS)
    # Sin ctx['_rlm'] cada tool degrada con la MISMA causa visible: estan
    # siempre registradas (patron horizonte) y gateadas en runtime.
    for nombre in sorted(rlm.RLM_TOOLS):
        out = T.run_tool(nombre, "1 | 2 | x", _ctx())
        assert out == (f"RESULTADO {nombre} ERROR: el modo RLM no esta "
                       "activo (usa /rlm).")


# ── 10. Exencion ACI: la vista larga vuelve ENTERA ─────────────────────

def test_ctx_ver_exento_de_aci_trim():
    # Output > 1800 chars (el cap de aci_trim) pero < MAX_CHARS_VISTA: tiene
    # que volver entero — el doble truncado haria que el modelo vea texto
    # del contexto que no existe.
    estado = _estado(_lineas(40, largo=90))
    out = T.run_tool("ctx_ver", "1 | 40", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert len(out) > 1800
    assert "chars omitidos" not in out      # el marcador de aci_trim
    assert "linea 00040" in out             # la cola llego intacta


# ── 11. Regresiones de la revision adversarial (fixes 2026-08-11) ──────
# Cada test de esta seccion falla sin su fix y pasa con el. POR QUE en cada
# docstring; el patron de armado (EstadoRLM sintetico + run_tool) es el mismo
# del resto del archivo.

import time as _time

from cognia.agent import loop as L


def test_ctx_info_linea_gigante_registra_solo_lo_mostrado():
    """Fix 1: un contexto de UNA linea minificada de 400k chars mostrado por
    ctx_info son ~200 chars vistos, no la linea entera. Antes se registraba
    la linea completa y el informe decia cobertura ~100% habiendo mostrado
    200 chars: el medidor mentia justo en el numero que es su razon de ser."""
    estado = _estado("z" * 400_000)         # 1 linea, sin \n
    out = T.run_tool("ctx_info", "", _ctx(estado))
    assert "ERROR" not in out[:120]
    # Lo mostrado esta capado: ninguna linea de la vista cuela la gigante.
    assert max(len(ln) for ln in out.split("\n")) <= rlm._CAP_LINEA + 20
    d = estado.medidor.como_dict()
    assert d["visto_raiz_chars"] <= rlm._CAP_LINEA
    assert estado.medidor.cobertura_raiz() < 0.01   # antes: ~1.0


def test_ctx_info_cabeceras_gigantes_capadas():
    """Fix 2: el contexto es texto ARBITRARIO — lineas de contenido que
    empiezan con '=== ARCHIVO: ' y miden 20k chars entraban ENTERAS a la
    linea 'archivos (...)' (40 mostradas = ~800k chars a la ventana, la
    puerta de atras que el modo existe para cerrar). Ahora cada cabecera va
    capada a _CAP_LINEA y la linea armada al cap de vista."""
    texto = "\n".join("=== ARCHIVO: " + "h" * 20_000 + " ==="
                      for _ in range(45))
    estado = _estado(texto)
    out = T.run_tool("ctx_info", "", _ctx(estado))
    assert "ERROR" not in out[:120]
    linea_archivos = next(ln for ln in out.split("\n")
                          if ln.startswith("archivos ("))
    assert len(linea_archivos) <= rlm.MAX_CHARS_VISTA
    # La salida ENTERA queda acotada (bordes capados a 200 + archivos a
    # 8000): sin los caps esto media ~800k chars.
    assert len(out) < 2 * rlm.MAX_CHARS_VISTA


def test_ctx_ver_una_linea_gigante_avisa_recorte():
    """Fix 3: ctx_ver de UNA linea > MAX_CHARS_VISTA devolvia el prefijo SIN
    ningun aviso; el modelo creia haber visto la linea entera y concluia que
    lo posterior al char 8000 no existe (el agujero invisible es peor que el
    recorte)."""
    estado = _estado("y" * 20_000)          # 1 linea de 20k chars
    out = T.run_tool("ctx_ver", "1 | 1", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert (f"[recortado: la linea 1 mide 20000 chars y solo se muestran "
            f"los primeros {rlm.MAX_CHARS_VISTA}") in out
    # Y el medidor registra SOLO el prefijo devuelto, no la linea entera.
    assert (estado.medidor.como_dict()["visto_raiz_chars"]
            == rlm.MAX_CHARS_VISTA)


def test_ctx_grep_match_despues_de_columna_200_visible():
    """Fix 4: recortar siempre desde el inicio de la linea escondia matches
    despues de la columna 200 — el modelo recibia una linea "matcheada" SIN
    el match adentro y concluia que el grep miente. La ventana va centrada
    en el match, con prefijo que dice desde que char arranca, y el medidor
    registra el rango realmente mostrado."""
    linea = "x" * 500 + "AGUJA_TARDE" + "y" * 100
    estado = _estado(linea)
    out = T.run_tool("ctx_grep", "AGUJA_TARDE", _ctx(estado))
    assert "ERROR" not in out[:120]
    fila = out.split("\n")[1]
    assert "AGUJA_TARDE" in fila            # el match VIAJA en la linea
    m = re.match(r"1 \(char (\d+)\): \.\.\.", fila)
    assert m, fila[:80]                     # prefijo con el offset real
    desde_col = int(m.group(1))
    assert 0 < desde_col <= 500             # ventana corrida hacia el match
    # Visto == exactamente la ventana mostrada (200 chars), no la linea.
    assert estado.medidor.como_dict()["visto_raiz_chars"] == rlm._CAP_LINEA


def test_ctx_grep_espacio_final_significativo():
    """Fix 5: el strip() del patron convertia 'ERROR ' en 'ERROR' y el grep
    devolvia matches de mas EN SILENCIO (un regex con espacio final es
    exactamente como se distingue 'ERROR uno' de 'ERRORES dos'). El patron
    va intacto al compile; strip() solo detecta vacio."""
    estado = _estado("ERROR uno\nERRORES dos")
    out = T.run_tool("ctx_grep", "ERROR ", _ctx(estado))
    assert "1 de 1 matches" in out          # antes: 2 de 2
    assert "ERROR uno" in out
    assert "ERRORES dos" not in out


def test_ctx_grep_backtracking_catastrofico_no_cuelga():
    """Fix 6: '(a+)+b' sobre una linea de 3000 'a' es backtracking
    catastrofico — con re puro colgaba el REPL entero adentro de ctx_grep.
    Con el paquete regex el timeout por busqueda corta en ~2s y devuelve un
    ERROR legible que dice QUE ajustar."""
    if rlm._regex is None:                  # pragma: no cover - entorno
        pytest.skip("sin el paquete regex el timeout por busqueda no existe")
    estado = _estado("a" * 3000)
    t0 = _time.monotonic()
    out = T.run_tool("ctx_grep", "(a+)+b", _ctx(estado))
    # Timeout generoso: lo que se prueba es que TERMINA, no que sea rapido.
    assert _time.monotonic() - t0 < 30
    assert "ERROR" in out[:120]
    assert "simplifica el patron" in out or "tardo mas" in out


def test_convencion_error_solo_en_primera_linea():
    """Fix 7: la convencion \\bERROR\\b del bucle se evalua sobre la PRIMERA
    linea del output. Un ctx_grep exitoso sobre un log con 'ERROR' (el caso
    de uso central del modo) y un hijo que cite errores del contexto NO
    deben contarse como tool fallida: 3 exitos asi seguidos disparaban el
    corte por no-progreso."""
    # (a) ctx_grep cuyo CONTENIDO matcheado es 'ERROR ...': la primera linea
    # es la cabecera con el conteo y el clasificador del bucle da ok.
    estado = _estado("ERROR uno\nnada\nERROR dos")
    out = T.run_tool("ctx_grep", "ERROR", _ctx(estado))
    assert "2 de 2 matches" in out
    assert re.search(r"\bERROR\b", out.split("\n", 1)[0][:120]) is None
    # (b) rlm_llamar exitoso cuyo hijo responde texto que ARRANCA con
    # 'ERROR timeout...': el texto va despues del \n, la primera linea es
    # solo la cabecera con el rango.
    estado2 = _estado(
        _lineas(50),
        completar_fn=lambda m, **kw: _hijo_ok(
            "ERROR timeout al conectar aparece 3 veces en el fragmento"))
    out2 = T.run_tool("rlm_llamar", "1 | 10 | que errores hay?",
                      _ctx(estado2))
    cabeza, resto = out2.split("\n", 1)
    assert cabeza == "RESULTADO rlm_llamar [lineas 1-10]:"
    assert re.search(r"\bERROR\b", cabeza[:120]) is None
    assert resto.startswith("ERROR timeout")


def test_ctx_partir_exento_de_aci_trim():
    """Fix 8: ctx_partir devuelve un INDICE (n<=64 trozos, sin contenido);
    si aci_trim le comiera el medio a 1800 chars el raiz planificaria
    subllamadas sobre trozos que jamas vio. La exencion ACI cubre a las 5
    tools RLM, no solo a las de lectura."""
    assert "ctx_partir" in T.ACI_EXENTAS
    estado = _estado(_lineas(1000))
    out = T.run_tool("ctx_partir", "64", _ctx(estado))
    assert "ERROR" not in out[:120]
    assert len(out) > 1800                  # supera el cap de aci_trim
    assert "chars omitidos" not in out      # el marcador de aci_trim
    assert "trozo 64:" in out               # la cola del indice llego entera


def test_recortar_mensajes_devuelve_chars_liberados():
    """Fix 9a: _recortar_mensajes devuelve CHARS liberados, no un conteo de
    turnos. Con el conteo (3) el caller restaba 3//4 = 0 tokens del estimado
    y el while no convergia nunca (o creia haber liberado nada). Bajo el
    umbral del 80% devuelve 0 y no toca nada."""
    marca = "[... recortado por presupuesto de contexto ...]"
    tools = [{"role": "tool", "content": "t" * 5000} for _ in range(4)]
    mensajes = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "objetivo"}] + tools
    # Bajo el umbral (80% de n_ctx): 0 liberado y mensajes intactos.
    assert L._recortar_mensajes(list(mensajes), 32768, 100) == 0
    assert all(marca not in m["content"] for m in mensajes)
    antes = sum(len(m["content"]) for m in mensajes)
    liberados = L._recortar_mensajes(mensajes, 1000, 900)
    despues = sum(len(m["content"]) for m in mensajes)
    # El retorno son los chars REALMENTE removidos (no 3, el conteo viejo).
    assert liberados == antes - despues
    assert liberados > 3 * 4000             # 3 turnos de 5000 -> ~250 c/u
    # El objetivo y el system son intocables por diseno.
    assert mensajes[0]["content"] == "sys"
    assert mensajes[1]["content"] == "objetivo"


def test_recorte_itera_mas_de_una_pasada():
    """Fix 9b: una sola pasada recorta a lo sumo 3 turnos; con tool-calls
    paralelas de resultados grandes el prompt seguia sobre n_ctx y el bucle
    no volvia a recortar hasta el turno siguiente (si llegaba). El caller
    ahora itera restando lo liberado del estimado: aca se simula ESE while
    y se exige que caigan mas de 3 turnos en total."""
    marca = "[... recortado por presupuesto de contexto ...]"
    mensajes = ([{"role": "system", "content": "sys"},
                 {"role": "user", "content": "objetivo"}]
                + [{"role": "tool", "content": "t" * 5000}
                   for _ in range(8)])
    est, pasadas = 10_000, 0                # muy por encima de 0.8 * 1000
    while True:                             # el mismo while del caller
        liberados = L._recortar_mensajes(mensajes, 1000, est)
        if not liberados:
            break
        est -= liberados // 4
        pasadas += 1
        assert pasadas < 20                 # el while tiene que converger
    recortados = sum(1 for m in mensajes if marca in m["content"])
    assert recortados > 3                   # antes: exactamente 3 y listo
    assert pasadas >= 2
