# -*- coding: utf-8 -*-
"""Puerta /confianza del REPL y los dos ganchos del turno (previa/posterior).

SIN RED: `cognia.agent.confianza_chat.investigar` se monkeypatchea (el CLI
lo llama por atributo del modulo, asi que el parche llega), la config va a
tmp_path y la salida de _print_line/_aviso_degradado se captura en listas.
El unico test que toca el backend real (REPL por stdin) se salta si
http://127.0.0.1:8080/health no responde.
"""
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

import cognia.cli as cli
from cognia.agent import confianza_chat as cc
from cognia.agent import sentinel as s

RAIZ = Path(__file__).resolve().parents[1]
PY = RAIZ / "venv312" / "Scripts" / "python.exe"
PREGUNTA = "cuantos suscriptores tiene The Acua Boy en YouTube?"
CONFESION = ("No tengo acceso a datos en tiempo real ni a YouTube, por lo "
             "que no puedo decirte cuantos suscriptores tiene.")


@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    # El centinela audita en ~/.cognia/sentinel_audit.jsonl: fuera del real.
    monkeypatch.setattr(s, "_AUDIT", tmp_path / "audit.jsonl")
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.delenv("COGNIA_CONFIANZA", raising=False)
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    # Foto limpia del ultimo turno (dict de modulo, compartido entre tests).
    for k, v in {"pregunta": "", "modo": "", "via": "", "aviso": "",
                 "fuentes": [], "segundos": 0.0, "veredicto": None,
                 "linea": ""}.items():
        cli._CONFIANZA_ULTIMO[k] = v


@pytest.fixture
def salida(monkeypatch):
    lineas, avisos = [], []
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(str(t)))
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, detalle="": avisos.append((via, detalle)))
    return lineas, avisos


def _inv_con_evidencia(pregunta=PREGUNTA, aviso=""):
    inv = cc.Investigacion(pregunta=pregunta, consulta="The Acua Boy youtube",
                           via="youtube", segundos=0.8, entidad="The Acua Boy")
    inv.evidencias.append(cc.Evidencia(
        url="https://www.youtube.com/@theacuaboy170",
        titulo="the acua boy",
        texto="Canal de YouTube the acua boy (@theacuaboy170).",
        dato="DATOS EXTRAIDOS (youtube): handle: @theacuaboy170; "
             "suscriptores: 4.63 K suscriptores",
        via="youtube"))
    inv.fuentes.append("youtube.com")
    inv.aviso = aviso
    return inv


# ── (c) registro: claves de config y puerta en /ayuda ───────────────────

def test_claves_de_config_y_puerta_registradas():
    for clave, valor in cc.CLAVES_CONFIG.items():
        assert cli._CONFIG_DEFAULTS.get(clave) == valor, clave
    assert cli._CONFIG_DEFAULTS["confianza"] == "on"
    assert "/confianza" in cli._CMD_DESCRIPTIONS
    assert "COGNIA_CONFIANZA" in cli._CMD_DESCRIPTIONS["/confianza"]
    assert "/confianza" in cli._CMD_DETAILS
    detalle = cli._CMD_DETAILS["/confianza"]
    for glifo in ("●", "◐", "○", "✕"):
        assert glifo in detalle
    assert "COGNIA_CONFIANZA" in detalle
    # el mando 'umbral' era MUERTO (no decidia nada): fuera de la ayuda, de
    # los defaults y del uso del comando
    assert "confianza_umbral" not in detalle
    assert "umbral <" not in cli._CMD_DESCRIPTIONS["/confianza"]
    assert "confianza_umbral" not in cli._CONFIG_DEFAULTS


# ── (a) /confianza cambia y persiste la config ──────────────────────────

def test_slash_confianza_persiste_config(salida, tmp_path):
    lineas, avisos = salida
    cli._slash_confianza("off")
    assert cli._load_config()["confianza"] == "off"
    assert (tmp_path / "cfg.json").exists()
    assert cli._confianza_config().on is False
    cli._slash_confianza("on")
    cli._slash_confianza("previa off")
    cli._slash_confianza("posterior off")
    cli._slash_confianza("segundos 40")
    cli._slash_confianza("paginas 5")
    cfg = cli._load_config()
    assert cfg["confianza"] == "on"
    assert cfg["confianza_previa"] == "off"
    assert cfg["confianza_posterior"] == "off"
    assert cfg["confianza_segundos"] == "40"
    assert cfg["confianza_paginas"] == "5"
    assert "confianza_umbral" not in cfg
    resuelta = cli._confianza_config()
    assert (resuelta.on, resuelta.previa, resuelta.posterior) == (True, False, False)
    assert resuelta.segundos == 40 and resuelta.max_paginas == 5
    assert all("(guardado)" in l for l in lineas) and not avisos
    # 'umbral' ya no es un subcomando: Uso, y nada persistido
    cli._slash_confianza("umbral 0,7")
    assert "Uso:" in lineas[-1] and "confianza_umbral" not in cli._load_config()
    lineas.clear()
    cli._slash_confianza("estado")
    assert not any(l.strip().startswith("[info_dim]  umbral") for l in lineas)


@pytest.mark.parametrize("arg", ["umbral 3", "umbral abc", "previa quizas",
                                 "posterior", "segundos 0", "paginas x",
                                 "zzz", "probar"])
def test_slash_confianza_argumento_malo_no_revienta(salida, arg):
    lineas, avisos = salida
    cli._slash_confianza(arg)
    assert lineas and "Uso:" in lineas[-1]
    assert cli._load_config() == dict(cli._CONFIG_DEFAULTS)   # nada persistido


def test_env_cero_apaga_todo_y_estado_lo_dice(salida, monkeypatch):
    lineas, _ = salida
    monkeypatch.setenv("COGNIA_CONFIANZA", "0")
    assert cli._confianza_config().on is False
    assert cli._confianza_previa(PREGUNTA) is None and not lineas
    cli._slash_confianza("estado")
    texto = "\n".join(lineas)
    assert "COGNIA_CONFIANZA=0" in texto and "ninguno todavia" in texto
    assert "via web" in texto


# ── (b) probar: evidencias visibles sin llamar al modelo ────────────────

def test_probar_muestra_clasificacion_evidencias_y_fuentes(salida, monkeypatch):
    lineas, avisos = salida
    llamadas = []

    def _inv_fake(pregunta, clasif=None, **kw):
        llamadas.append((pregunta, clasif, kw))
        kw["on_evento"]("buscando el canal «The Acua Boy» en YouTube…")
        return _inv_con_evidencia(pregunta)

    monkeypatch.setattr(cc, "investigar", _inv_fake)
    cli._slash_confianza("segundos 7")
    cli._slash_confianza("probar " + PREGUNTA)
    texto = "\n".join(lineas)
    assert "VOLATIL" in texto and "youtube" in texto.lower()
    assert "buscando el canal" in texto
    assert "the acua boy — https://www.youtube.com/@theacuaboy170" in texto
    assert "4.63 K suscriptores" in texto
    assert "fuentes: youtube.com" in texto
    assert not avisos
    (pregunta, clasif, kw), = llamadas
    assert pregunta == PREGUNTA and clasif.volatil
    assert kw["presupuesto_s"] == 7 and kw["max_paginas"] == 3
    assert cli._CONFIANZA_ULTIMO["modo"] == "probar"
    # el estado refleja el ultimo turno investigado
    lineas.clear()
    cli._slash_confianza("")
    assert "[probar]" in "\n".join(lineas)


def test_probar_declara_el_fallo(salida, monkeypatch):
    lineas, _ = salida
    monkeypatch.setattr(cc, "investigar", lambda p, c=None, **kw: cc.Investigacion(
        pregunta=p, consulta=p, aviso="YouTube no respondió (RuntimeError: sin red)"))
    cli._slash_confianza("probar " + PREGUNTA)
    assert any("aviso: YouTube no respondió" in l for l in lineas)
    assert cli._CONFIANZA_ULTIMO["aviso"].startswith("YouTube no respondió")


# ── (d) el bloque de evidencia entra en los mensajes del modelo ─────────

def test_previa_antepone_las_evidencias_al_mensaje(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar",
                        lambda p, c=None, **kw: _inv_con_evidencia(p))
    inv = cli._confianza_previa(PREGUNTA)
    assert inv is not None and inv.evidencias
    assert any("confianza a priori BAJA" in l and "investigando" in l
               for l in lineas)
    assert not avisos
    # la costura real del fast-path: _raw_llm = prefijo + raw -> _build_stream_messages
    raw_llm = cli._confianza_prefijo(inv) + PREGUNTA
    msgs = cli._build_stream_messages(None, raw_llm, "sistema", [])
    ultimo = msgs[-1]
    assert ultimo["role"] == "user"
    assert "DATOS OBTENIDOS DE LA WEB" in ultimo["content"]
    assert "4.63 K suscriptores" in ultimo["content"]
    assert ultimo["content"].rstrip().endswith(PREGUNTA)
    assert msgs[0] == {"role": "system", "content": "sistema"}
    # veredicto: la cifra de la respuesta coincide con la evidencia -> media
    ver = cli._confianza_veredicto("Tiene unos 4.630 suscriptores.", inv)
    assert ver.confianza >= cc.UMBRAL_INVESTIGAR
    assert lineas[-1].startswith("[ok_cl]◐ confianza MEDIA")
    assert "1 fuente: youtube.com" in lineas[-1]
    assert cli._CONFIANZA_ULTIMO["linea"] == cc.linea_confianza(ver, inv)


def test_previa_sin_evidencias_declara_y_no_prefija(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar", lambda p, c=None, **kw: cc.Investigacion(
        pregunta=p, consulta=p, aviso="la web no respondió (ConnectionError: x)"))
    inv = cli._confianza_previa(PREGUNTA)
    assert inv is not None and cli._confianza_prefijo(inv) == ""
    assert avisos == [("confianza.web", "la web no respondió (ConnectionError: x)")]
    cli._confianza_veredicto("No lo se.", inv)
    assert lineas[-1].startswith("[info_dim]○ confianza BAJA")
    assert "sin verificar: la web no respondió" in lineas[-1]


def test_previa_no_volatil_ni_off_no_imprime_nada(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar",
                        lambda *a, **k: pytest.fail("no debia investigar"))
    assert cli._confianza_previa("explica que es un decorador en python") is None
    cli._slash_confianza("previa off")
    lineas.clear()
    assert cli._confianza_previa(PREGUNTA) is None
    assert not lineas and not avisos


def test_posterior_reinyecta_las_fuentes_en_la_segunda_llamada(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar",
                        lambda p, c=None, **kw: _inv_con_evidencia(p))
    pedidos, mostrados = [], []

    def _pedir(texto):
        pedidos.append(texto)
        return "Segun YouTube, the acua boy tiene 4,63 mil suscriptores [1]."

    res = cli._confianza_posterior(PREGUNTA, CONFESION, _pedir,
                                   mostrar=mostrados.append)
    final, inv, ver = res
    assert final.startswith("Segun YouTube") and mostrados == [final]
    # la segunda llamada lleva el bloque de evidencia + la pregunta original
    (texto,) = pedidos
    assert "DATOS OBTENIDOS DE LA WEB" in texto and texto.endswith(PREGUNTA)
    assert "4.63 K suscriptores" in texto
    assert any("declara incertidumbre" in l and "No tengo acceso" in l
               for l in lineas)
    assert any("respondiendo con las fuentes" in l for l in lineas)
    assert lineas[-1].startswith("[ok_cl]◐ confianza MEDIA")
    assert ver.confianza >= cc.UMBRAL_INVESTIGAR and not avisos
    assert cli._CONFIANZA_ULTIMO["modo"] == "posterior"


def test_posterior_sin_evidencias_deja_la_respuesta_y_avisa(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar", lambda p, c=None, **kw: cc.Investigacion(
        pregunta=p, consulta=p, aviso="YouTube no respondió (RuntimeError: sin red)"))
    final, inv, ver = cli._confianza_posterior(
        PREGUNTA, CONFESION, lambda t: pytest.fail("sin evidencias no se re-pregunta"))
    assert final == CONFESION
    assert avisos == [("confianza.web", "YouTube no respondió (RuntimeError: sin red)")]
    assert lineas[-1].startswith("[info_dim]○ confianza BAJA") and "sin verificar" in lineas[-1]


def test_posterior_segunda_llamada_vacia_conserva_la_original(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar",
                        lambda p, c=None, **kw: _inv_con_evidencia(p))
    final, _, _ = cli._confianza_posterior(PREGUNTA, CONFESION, lambda t: "")
    assert final == CONFESION
    assert avisos and avisos[0][0] == "confianza" and "vacia" in avisos[0][1]


def test_posterior_no_dispara_sin_confesion_ni_apagado(salida, monkeypatch):
    lineas, avisos = salida
    monkeypatch.setattr(cc, "investigar",
                        lambda *a, **k: pytest.fail("no debia investigar"))
    assert cli._confianza_posterior(
        "explica que es un decorador", "Un decorador envuelve una funcion.",
        lambda t: "") is None
    cli._slash_confianza("posterior off")
    lineas.clear()
    assert cli._confianza_posterior(PREGUNTA, CONFESION, lambda t: "") is None
    assert not lineas and not avisos


# ── REPL real por stdin (solo con el backend vivo) ──────────────────────
#
# SIN RED y SIN TOCAR LOS DATOS DEL DUEÑO: la primera versión lanzaba
# `python -m cognia` a pelo, salía a DuckDuckGo/YouTube en cada pytest y
# _persist_turn escribía el turno en el chat_history REAL (la sesión
# siguiente arrancaba con "Continuidad: N mensajes restaurados" incluyendo
# el turno del test) y el centinela en su jsonl real. Aquí:
#   - HOME/USERPROFILE/COGNIA_HOME apuntan a tmp_path (config, sqlite,
#     auditoría del centinela y _CONFIG_PATH van ahí; el subproceso no ve
#     el monkeypatch de sentinel._AUDIT, por eso se redirige el home entero);
#   - se copia SOLO config.env del dueño (rutas del backend :8080), y
#     HF_HOME apunta a la caché real en modo offline (sin ella el REPL
#     intenta descargar sentence-transformers a un home virgen: medido);
#   - un bootstrap reemplaza `confianza_chat.investigar` por una función
#     con la evidencia del canal ANTES de arrancar el REPL: ni ddgs, ni
#     lite, ni YouTube. La única red es el backend local.
# Lo que sigue probándose es lo que un unit test no puede: el fast-path
# entero (gancho previa -> prefijo en _raw_llm -> modelo -> veredicto).

_BOOT = '''
import runpy, sys
from cognia.agent import confianza_chat as cc

def _inv(pregunta, clasif=None, **kw):
    inv = cc.Investigacion(pregunta=pregunta,
                           consulta="The Acua Boy youtube suscriptores",
                           via="youtube", segundos=0.1, entidad="The Acua Boy")
    inv.evidencias.append(cc.Evidencia(
        url="https://www.youtube.com/@theacuaboy170", titulo="the acua boy",
        texto="Canal de YouTube: the acua boy (@theacuaboy170). 4.63 K "
              "suscriptores.", dato="4.63 K suscriptores", via="youtube"))
    inv.fuentes.append("youtube.com")
    return inv

cc.investigar = _inv
sys.argv = ["cognia"]
runpy.run_module("cognia", run_name="__main__")
'''
_CONFIG_ENV_REAL = Path.home() / ".cognia" / "config.env"
_HF_REAL = Path.home() / ".cache" / "huggingface"


def _backend_vivo() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.mark.skipif(not _backend_vivo(), reason="llama-server no responde en :8080")
@pytest.mark.skipif(not PY.exists(), reason="sin venv312")
@pytest.mark.skipif(not _CONFIG_ENV_REAL.exists(),
                    reason="sin ~/.cognia/config.env (rutas del backend)")
def test_repl_por_stdin_muestra_la_previa_y_la_linea_de_confianza(tmp_path):
    """Cablea el fast-path de verdad (no se puede aislar en unit test: el
    turno vive dentro del bucle del REPL). Home aislado + investigar
    inyectado: cero web, cero rastro en los datos del dueño."""
    home = tmp_path / "home"
    (home / ".cognia").mkdir(parents=True)
    (home / ".cognia" / ".setup_done").touch()
    (home / ".cognia" / "config.env").write_bytes(_CONFIG_ENV_REAL.read_bytes())
    boot = tmp_path / "boot.py"
    boot.write_text(_BOOT, encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", COGNIA_SPINNER="0",
               COGNIA_ANIMACION="0", NO_COLOR="1",
               HOME=str(home), USERPROFILE=str(home),
               COGNIA_HOME=str(home / ".cognia"),
               HF_HOME=str(_HF_REAL), HF_HUB_OFFLINE="1")
    env.pop("COGNIA_CONFIANZA", None)
    env.pop("COGNIA_REMOTO", None)
    p = subprocess.run([str(PY), str(boot)], cwd=str(RAIZ), env=env,
                       input=PREGUNTA + "\n/salir\n", capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    out = p.stdout + p.stderr
    assert "confianza a priori BAJA" in out, out[-3000:]
    assert any(g in out for g in ("● confianza", "◐ confianza",
                                  "○ confianza", "✕ confianza")), out[-3000:]
    assert "1 fuente: youtube.com" in out, out[-3000:]
    # todo lo persistido (chat_history sqlite) quedó en el home temporal,
    # no en el del dueño
    assert (home / ".cognia" / "cognia_memory.db").exists()
