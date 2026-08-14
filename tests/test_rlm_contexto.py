# -*- coding: utf-8 -*-
"""
Tests del modo RLM: como se LEE el corpus y con que regimen se corre.

Los dos bugs que motivan el fichero (medidos el 2026-08-13, ver los repros
adentro de cada test):

1. CORPUS NO-UTF8 DESTROZADO. ``ContextoRLM.cargar`` decodificaba con
   ``errors='replace'``, asi que un fichero cp1252 — lo NORMAL en Windows —
   entraba al contexto con un U+FFFD por cada acento. ctx_grep('funcion' con
   tilde) devolvia 0 matches sobre un corpus que dice justo eso, la segunda
   pasada sin tildes tampoco lo rescataba (quitarle el acento al PATRON no
   repara un TEXTO que ya perdio la letra) y chars/tokens_aprox mentian
   porque el reemplazo colapsa runs de bytes. El fallo es SILENCIOSO: un 0
   legitimo, sin ERROR, sobre un contexto que si tenia el dato.

2. REGIMEN FABRICADO. Cuando el perfil salia texto, correr_rlm inventaba un
   perfil ``{'tools': 'nativo', ...}`` sobre CUALQUIER modelo. Contra un
   server que no parsea tools, el bucle nativo lee la primera respuesta en
   prosa como "sin tool_calls" = fin natural y cierra en el paso 1 con una
   respuesta inventada SIN haber tocado el contexto. Ahora el regimen se MIDE
   (capacidad.soporta_tools) y sin tool-calling se falla con causa visible.

Todo se comprueba en BYTES (``write_bytes``/``read_bytes``): un assert sobre
un str de pantalla no distingue 'funcion' con tilde de su mojibake.
Sin modelo real: URLs muertas (127.0.0.1:9), props() y la sonda stubbeadas.
"""
import pytest

from cognia.agent import rlm


# ── helpers ────────────────────────────────────────────────────────────

def _ctx_de(contexto):
    """El ctx del bucle con un EstadoRLM minimo sobre ese contexto."""
    estado = rlm.EstadoRLM(
        contexto=contexto,
        medidor=rlm.MedidorContexto(ctx_chars=contexto.chars,
                                    ctx_lineas=len(contexto.lineas),
                                    origen=contexto.origen, n_ctx=32768),
        completar_fn=None, perfil={})
    return {"_rlm": estado}


def _sin_backend(monkeypatch):
    """props() sin red y sin override de regimen en el entorno: nada de este
    fichero toca el llama-server vivo, y un COGNIA_AGENT_TOOLS exportado en la
    consola del dueno no puede decidir el resultado de estos tests."""
    import cognia.backend_activo as ba
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})
    for var in ("COGNIA_AGENT_TOOLS", "COGNIA_AGENT_LEGACY",
                "COGNIA_RLM_WORKER"):
        monkeypatch.delenv(var, raising=False)


# ── 1. Corpus cp1252: la busqueda CON tildes tiene que encontrar ───────

def test_ctx_grep_encuentra_tildes_en_corpus_cp1252(tmp_path):
    """El caso que se medio roto: .txt en cp1252 con 'funcion critica' CON
    tildes -> ctx_grep de esa palabra devolvia 0 matches (bytes \\xf3/\\xed
    convertidos en U+FFFD). Debe devolver 1."""
    ruta = tmp_path / "corpus.txt"
    crudo = "linea uno\nfunción crítica del módulo\nfin\n".encode("cp1252")
    ruta.write_bytes(crudo)
    # El corpus es cp1252 DE VERDAD (no utf-8 disfrazado): un acento = 1 byte
    # y el fichero no decodifica en utf-8 estricto.
    assert b"\xf3" in ruta.read_bytes()
    with pytest.raises(UnicodeDecodeError):
        crudo.decode("utf-8")

    c = rlm.ContextoRLM.cargar(str(ruta))
    assert "\ufffd" not in c.texto            # ni un reemplazo
    assert "función crítica" in c.texto
    assert c.codificacion == "cp1252"

    ctx = _ctx_de(c)
    salida = rlm._ctx_grep("función", ctx)
    assert salida.startswith("RESULTADO ctx_grep: 1 de 1 matches"), salida
    assert "función crítica del módulo" in salida
    # Y la enye tambien (NFD la descompone; el corpus la trae como \xf1).
    ruta2 = tmp_path / "enye.txt"
    ruta2.write_bytes("el año pasado\n".encode("cp1252"))
    c2 = rlm.ContextoRLM.cargar(str(ruta2))
    assert "1 de 1 matches" in rlm._ctx_grep("año", _ctx_de(c2))


def test_ctx_info_declara_la_codificacion(tmp_path):
    """Sin declararla, un corpus leido como cp1252 y uno utf-8 se ven
    identicos desde el modelo y una busqueda fallida no tiene explicacion."""
    ruta = tmp_path / "corpus.txt"
    ruta.write_bytes("función crítica\n".encode("cp1252"))
    c = rlm.ContextoRLM.cargar(str(ruta))
    salida = rlm._ctx_info("", _ctx_de(c))
    primera = salida.split("\n")[0]
    assert "codificacion: cp1252" in primera, primera
    assert "origen:" in primera


def test_utf8_gana_a_cp1252_en_la_cascada(tmp_path):
    """La cascada arranca en utf-8 ESTRICTO: un corpus utf-8 no puede salir
    leido como cp1252 (seria 'funciÃ³n', mojibake al reves)."""
    ruta = tmp_path / "corpus.txt"
    ruta.write_bytes("función crítica\n".encode("utf-8"))
    c = rlm.ContextoRLM.cargar(str(ruta))
    assert c.codificacion == "utf-8"
    assert "función crítica" in c.texto and "Ã" not in c.texto


def test_bom_de_powershell_no_se_pega_a_la_primera_palabra(tmp_path):
    """PowerShell escribe utf-8 CON BOM por defecto (trampa ya pagada en este
    repo): sin descontarlo, la primera palabra del corpus queda '\\ufeffhola'
    y es inbuscable."""
    ruta = tmp_path / "ps.txt"
    ruta.write_bytes(b"\xef\xbb\xbf" + "hola función\n".encode("utf-8"))
    c = rlm.ContextoRLM.cargar(str(ruta))
    assert not c.texto.startswith("\ufeff")
    assert c.lineas[0] == "hola función"
    assert "1 de 1 matches" in rlm._ctx_grep("^hola", _ctx_de(c))


def test_chars_y_tokens_no_los_distorsiona_el_reemplazo(tmp_path):
    """chars/tokens_aprox son el tamano que el modelo usa para planificar
    trozos: si salen del texto CON reemplazos, no describen el corpus.

    El reemplazo colapsa un run invalido entero en UN U+FFFD, asi que el
    conteo se corre respecto del corpus real (aqui: 14 chars contra 16)."""
    ruta = tmp_path / "mixto.txt"
    # \xe9\xa9\xbf es una secuencia utf-8 VALIDA (colapsa a 1 char) y el
    # \xf3 suelto del final invalida el fichero entero en utf-8 estricto.
    crudo = b"caf\xe9\xa9\xbf y funci\xf3n"
    ruta.write_bytes(crudo)
    viejo = crudo.decode("utf-8", errors="replace")     # el camino de antes
    c = rlm.ContextoRLM.cargar(str(ruta))
    assert c.chars == len(crudo.decode("cp1252")) == 16
    assert len(viejo) == 14 and c.chars != len(viejo)
    assert c.tokens_aprox == c.chars // 4


def test_directorio_decodifica_POR_FICHERO(tmp_path):
    """Un repo real mezcla utf-8 con una ANSI vieja: decidir la codificacion
    en bloque romperia justo los otros ficheros."""
    (tmp_path / "a_utf8.txt").write_bytes("año utf8\n".encode("utf-8"))
    (tmp_path / "b_ansi.txt").write_bytes("función ansi\n".encode("cp1252"))
    c = rlm.ContextoRLM.cargar(str(tmp_path))
    assert "\ufffd" not in c.texto
    assert "año utf8" in c.texto and "función ansi" in c.texto
    # El resumen nombra AMBOS codecs con cuantos ficheros leyo cada uno.
    assert "utf-8 (1)" in c.codificacion and "cp1252 (1)" in c.codificacion
    assert "1 de 1 matches" in rlm._ctx_grep("función", _ctx_de(c))


def test_binario_con_bytes_indecodificables_no_tumba_la_carga(tmp_path):
    """Ultimo recurso latin-1: un fichero raro se lee degradado, pero el
    corpus entero se carga igual (0x81/0x8d no existen en cp1252)."""
    (tmp_path / "raro.txt").write_bytes(b"basura \x81\x8d\x8f\x90 mas\n")
    (tmp_path / "bueno.txt").write_bytes("función\n".encode("cp1252"))
    c = rlm.ContextoRLM.cargar(str(tmp_path))
    assert "función" in c.texto
    assert "latin-1" in c.codificacion


# ── 2. El regimen se MIDE: sin tool-calling, error con causa ───────────

def _stub_capacidad(monkeypatch, soporta, motivo=""):
    """La sonda stubbeada: ni un POST sale de estos tests."""
    from cognia.agent import capacidad as cap
    monkeypatch.setattr(cap, "soporta_tools",
                        lambda url="", forzar=False: soporta)
    monkeypatch.setattr(cap, "medicion",
                        lambda url="", forzar=False: {"motivo": motivo,
                                                      "soporta_tools": soporta})


def _espia_bucle(monkeypatch, salida=None):
    """Marca si se entro al bucle nativo (y con que), sin correrlo."""
    from cognia.agent import loop as _loop
    llamadas = []

    def _falso(**kw):
        llamadas.append(kw)
        return salida or {"texto": "listo", "pasos": 2, "ok": True,
                          "tokens": 0, "finish": "stop"}

    monkeypatch.setattr(_loop, "bucle_nativo", _falso)
    return llamadas


def test_sin_tool_calling_falla_con_causa_y_NO_entra_al_bucle(tmp_path,
                                                              monkeypatch):
    """El bug: con el perfil fabricado, un server sin tools entraba al bucle
    nativo y cerraba en el paso 1 sin tocar el contexto. Ahora: error con la
    causa que dio la sonda, y el bucle no se ejecuta."""
    _sin_backend(monkeypatch)
    _stub_capacidad(monkeypatch, False,
                    "respondio sin tool_calls (finish_reason=stop): el server "
                    "no parsea tools — ¿le falta --jinja?")
    llamadas = _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(("linea de contexto\n" * 40).encode("utf-8"))

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9")

    assert res["ok"] is False
    assert llamadas == []                       # NO se entro al bucle nativo
    assert res["texto"].startswith("ERROR")
    # La causa REAL, no un "fallo el modo": el usuario tiene que poder actuar.
    assert "no parsea tools" in res["texto"] and "--jinja" in res["texto"]
    assert "cognia.agent.capacidad" in res["texto"]
    # El comando sugerido tiene que RE-MEDIR: la medicion se cachea 24 h por
    # (url, modelo) y poner --jinja no cambia el nombre del .gguf, asi que sin
    # --forzar el usuario arregla el server y el comando le sigue diciendo que
    # esta roto (el modo RLM muerto hasta 24 h por un veredicto rancio).
    assert "--forzar" in res["texto"]
    # Medir es parte del contrato aun en el corte: 0% visto es un dato.
    assert res["informe"].startswith("[contexto efectivo RLM]")
    assert res["medidor"]["ctx_chars"] > 0
    assert res["medidor"]["cobertura_union"] == 0.0


def test_el_comando_del_remedio_re_mide_no_lee_la_cache(tmp_path, monkeypatch):
    """El fleco de 9dab2037: el remedio mandaba a correr
    'python -m cognia.agent.capacidad <url>' SIN --forzar, y ese comando LEE la
    cache de 24 h (clave (url, modelo)). Como reiniciar llama-server con --jinja
    no cambia el nombre del .gguf, la clave es la misma y el false rancio
    sobrevive: el usuario arregla el server, corre lo que el error le pide, le
    dicen otra vez que esta roto y el RLM queda muerto hasta 24 h. El flag va
    PEGADO al comando, no suelto en el texto."""
    _sin_backend(monkeypatch)
    _stub_capacidad(monkeypatch, False, "respondio sin tool_calls")
    _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(b"hola\n")

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9")

    assert res["ok"] is False
    # La url medida + el flag que re-mide, en la misma linea del comando.
    assert ("python -m cognia.agent.capacidad http://127.0.0.1:9 --forzar"
            in res["texto"])
    # Y la razon por la que hace falta, para que no la borren de nuevo.
    assert "24 h" in res["texto"]


def test_regimen_forzado_a_texto_manda_al_entorno_no_al_jinja(tmp_path,
                                                              monkeypatch):
    """Con COGNIA_AGENT_LEGACY=1 el server puede estar perfecto: el remedio es
    quitar el override, no ir a ponerle --jinja a un server que esta bien."""
    _sin_backend(monkeypatch)
    _stub_capacidad(monkeypatch, True, "tool call valido en 2.0s")
    monkeypatch.setenv("COGNIA_AGENT_LEGACY", "1")
    llamadas = _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(b"hola\n")

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9")
    assert res["ok"] is False and llamadas == []
    assert "forzado" in res["texto"]
    assert "COGNIA_AGENT_LEGACY" in res["texto"]
    assert "--jinja" not in res["texto"]
    # Ni --forzar: aca no hay nada que re-medir, la sonda ya dice que el server
    # esta bien y lo que corta es el override del entorno.
    assert "--forzar" not in res["texto"]


def test_sonda_rota_tampoco_cuela_el_regimen(tmp_path, monkeypatch):
    """Si la sonda revienta, no hay medicion: y sin medicion no hay nativo
    (que es exactamente lo que se dejo de suponer)."""
    _sin_backend(monkeypatch)
    from cognia.agent import capacidad as cap

    def _explota(url="", forzar=False):
        raise RuntimeError("cache corrupto")

    monkeypatch.setattr(cap, "soporta_tools", _explota)
    llamadas = _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(b"hola\n")

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9")
    assert res["ok"] is False and llamadas == []
    assert "cache corrupto" in res["texto"]


def test_con_tool_calling_medido_si_entra_al_bucle(tmp_path, monkeypatch):
    """El contrafactual del test de arriba: la puerta no esta cerrada para
    todos — con la sonda en True el modo corre como siempre."""
    _sin_backend(monkeypatch)
    _stub_capacidad(monkeypatch, True, "tool call valido en 2.0s")
    llamadas = _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(b"hola\n")

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9")
    assert res["ok"] is True and res["texto"] == "listo"
    assert len(llamadas) == 1
    # El perfil que viaja al bucle ya no puede decir 'texto' (el modo solo
    # existe en nativo) y trae sampling utilizable.
    perfil = llamadas[0]["perfil"]
    assert perfil["tools"] == "nativo" and "temperature" in perfil


def test_completar_fn_inyectada_NO_la_bloquea_la_sonda(tmp_path, monkeypatch):
    """Con completar_fn inyectada quien responde es ELLA, no el server de la
    url: el veredicto de la sonda habla de un tercero que no interviene, y no
    puede cortar la corrida (si lo hiciera, todo test guionado contra una url
    muerta — el patron de test_rlm.py — dejaria de correr)."""
    _sin_backend(monkeypatch)
    _stub_capacidad(monkeypatch, False, "no parsea tools")
    llamadas = _espia_bucle(monkeypatch)
    ruta = tmp_path / "ctx.txt"
    ruta.write_bytes(b"hola\n")

    res = rlm.correr_rlm("que dice?", str(ruta), url="http://127.0.0.1:9",
                         completar_fn=lambda m, **kw: None)
    assert res["ok"] is True and len(llamadas) == 1
