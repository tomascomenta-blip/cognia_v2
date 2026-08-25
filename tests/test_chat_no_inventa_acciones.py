# -*- coding: utf-8 -*-
"""El chat NO inventa acciones (transcript del dueno 2026-08-25, 11:52-11:57).

Lo que paso: "Quiero que limpies todas las capturas de pantalla en mi
computador" fue al CHAT (intent.detect solo casaba imperativos al inicio);
el chat respondio con comandos de LINUX en Windows; "hazlo tu" siguio en
chat y el modelo INVENTO "Ejecute los dos comandos... veintinueve archivos
eliminados" sin correr tool alguna; "no los ejecutaste" repitio el invento.

Tres piezas bajo test, SIN modelo:
  (1) cognia/agent/intent.py: peticion cortes de accion en cualquier
      posicion, reclamo de no-ejecucion y continuacion corta ("hazlo tu");
  (2) cognia/agent/intent.py afirma_accion_ejecutada: detector de
      afirmaciones de accion en una respuesta de chat (que no tiene tools);
  (3) cli._chat_afirmaciones_cierre: la costura que el fast-path llama tras
      _full_response (el stream se simula pasando la respuesta inventada tal
      cual: el cierre es EXACTAMENTE lo que ve el REPL despues del stream;
      el bucle del REPL entero no se puede aislar en unit test, mismo
      precedente que tests/test_cli_confianza.py) -> aviso visible + ambar,
      la respuesta inventada NO se devuelve (el llamador persiste lo
      devuelto) y _run_agent_task recibe la peticion ORIGINAL.
"""
import re
from pathlib import Path

import pytest

import cognia.cli as cli
from cognia.agent.intent import afirma_accion_ejecutada, detect

# ── transcript real ────────────────────────────────────────────────────────
PETICION = ("Quiero que limpies todas las capturas de pantalla en mi "
            "computador porfavor")
RESPUESTA_LINUX = ("Puedes listar con ls ~/Pictures/Screenshots/*.jpg y "
                   "luego find ~/Pictures -name '*.png' -delete; tambien "
                   "existe gnome-screenshot.")
RESPUESTA_INVENTADA = ("Ejecute los dos comandos que me pediste. Diecisiete "
                       "imagenes salieron de la primera carpeta y doce de la "
                       "segunda, veintinueve archivos eliminados.")


# ── (1) intent: positivos (>= 25, incluidos los 4 del transcript) ─────────

POSITIVOS = [
    # los 4 del transcript
    PETICION,
    "bueno quiero que limpies todas las capturas de pantalla en mi computador porfavor",
    "hazlo tu",
    "no los ejecutaste",
    # peticion cortes de accion
    "necesito que borres los archivos temporales",
    "puedes eliminar las descargas viejas de mi pc",
    "podrias mover las fotos a otra carpeta",
    "podes renombrar el archivo notas.txt",
    "me borras las capturas de pantalla?",
    "hazme una carpeta para las fotos",
    "haceme espacio, elimina las descargas",
    "haz una limpieza del escritorio",
    # mandato directo corto
    "hazlo",
    "ejecutalo",
    "correlo",
    "si, hazlo",
    # reclamos de no-ejecucion
    "de verdad hazlo",
    "no lo hiciste",
    "no hiciste nada",
    "no se ejecuto",
    "eso no paso",
    # verbo de sistema en cualquier posicion + objeto de sistema
    "organiza los archivos del escritorio",
    "ordena mis descargas",
    "instala el programa 7zip",
    "desinstala esa aplicacion",
    "actualiza el sistema",
    "descarga las imagenes a la carpeta fotos",
    "comprime la carpeta proyectos",
    "descomprime el archivo zip",
    "convierte las imagenes a png",
    "limpia la papelera",
    "borra las capturas de pantalla",
    "cierra todos los programas",
    "abre la carpeta de descargas",
    # ingles
    "delete the old screenshots on my desktop",
    "can you remove the temp files",
]


@pytest.mark.parametrize("texto", POSITIVOS)
def test_positivos_van_al_agente(texto):
    r = detect(texto)
    assert r.needs_agent, texto


# ── (1) intent: negativos (>= 15; las guardas conversacionales siguen) ────

NEGATIVOS = [
    "hola",
    "gracias",
    "que es un decorador",
    "explica como borrar archivos en linux",
    "que comandos usaria para limpiar capturas de pantalla?",
    "como se elimina un archivo en windows",
    "como puedo borrar una carpeta",
    "que programas abren archivos zip",
    "soy Tomas Montes el creador de este harness",
    "quiero que sepas que me gusta el proyecto",
    "quiero aprender python",
    "me gusta el color azul",
    "el explorador de windows ordena los archivos por fecha",
    "por que el cielo es azul",
    "cual es la capital de francia",
    "que significa refactorizar",
    "cuando borras un archivo va a la papelera",
]


@pytest.mark.parametrize("texto", NEGATIVOS)
def test_negativos_siguen_en_chat(texto):
    assert not detect(texto).needs_agent, texto


def test_reclamo_lleva_reason_y_tool_vacia():
    for texto in ("no los ejecutaste", "no lo hiciste", "no hiciste nada",
                  "no se ejecuto", "eso no paso", "de verdad hazlo"):
        r = detect(texto)
        assert r.needs_agent, texto
        assert r.reason == "reclamo:no_ejecutado", texto
        assert r.suggested_tool == "", texto


def test_continuacion_corta_tras_respuesta_con_comandos():
    # "hazlo tu"/"dale"/"procede" tras una respuesta con comandos o plan
    for texto in ("hazlo tu", "dale", "procede", "adelante", "si, hazlo"):
        r = detect(texto, respuesta_previa=RESPUESTA_LINUX)
        assert r.needs_agent, texto
        assert r.reason == "continuacion:accion", texto
        assert r.suggested_tool == "", texto


def test_dale_sin_contexto_de_plan_es_charla():
    # sin respuesta previa con comandos, "dale"/"adelante" son muletillas
    assert not detect("dale").needs_agent
    assert not detect("adelante").needs_agent
    # ...pero "hazlo"/"ejecutalo" llevan el mandato adentro: disparan igual
    assert detect("hazlo tu").needs_agent
    assert detect("ejecutalo").needs_agent


def test_dale_tras_respuesta_sin_plan_sigue_en_chat():
    assert not detect("dale", respuesta_previa="Me alegro de que te guste "
                      "el proyecto, cuentame mas.").needs_agent


# ── (2) detector de afirmaciones de accion ────────────────────────────────

def test_afirmacion_inventada_del_transcript_se_detecta():
    assert afirma_accion_ejecutada(RESPUESTA_INVENTADA)


def test_repetir_el_invento_tambien_se_detecta():
    # el turno "no los ejecutaste" repitio EXACTAMENTE el mismo texto
    assert afirma_accion_ejecutada(RESPUESTA_INVENTADA + " "
                                   + RESPUESTA_INVENTADA)


@pytest.mark.parametrize("respuesta", [
    "He eliminado todos los archivos de la papelera.",
    "Ya ejecute los comandos y borre las capturas antiguas.",
    "Listo. Movi las fotos a otra carpeta y elimine los duplicados.",
    "I ran the two commands and deleted the screenshots.",
    "I've removed 12 files from Downloads.",
    "29 files were deleted from the folder.",
    "La limpieza quedo completada: se eliminaron 29 archivos.",
    "Todo esta hecho, tu escritorio quedo limpio.",
])
def test_afirmaciones_positivas(respuesta):
    assert afirma_accion_ejecutada(respuesta), respuesta


@pytest.mark.parametrize("respuesta", [
    # explicar NO es afirmar
    "Para borrar capturas puedes usar Remove-Item ~\\Pictures\\*.png.",
    RESPUESTA_LINUX,
    # imperativo dirigido al usuario
    "Ejecuta este comando: Remove-Item *.png",
    "Ejecute los siguientes comandos: dir y del.",
    # condicional
    "Si ejecutas find -delete se eliminaran los archivos.",
    "Cuando borres los archivos, quedaran solo las carpetas.",
    # reformulacion de la peticion, no afirmacion
    "Me pediste que ejecute los comandos, pero no puedo ejecutar nada.",
    # comandos dentro de un bloque de codigo son PROPUESTA
    "Puedes hacerlo asi:\n```\nrm -rf ~/Pictures/Screenshots\n```",
    # confesion honesta
    "No puedo ejecutar comandos: solo soy el chat.",
])
def test_no_afirmaciones_no_disparan(respuesta):
    assert afirma_accion_ejecutada(respuesta) == "", respuesta


# ── (3) cierre del fast-path: _chat_afirmaciones_cierre ───────────────────

RESPUESTA_AGENTE = "Hecho: revise las carpetas y pedi permiso antes de borrar."


@pytest.fixture
def arnes(monkeypatch, tmp_path):
    """El cierre con TODO falso: config en tmp, salida capturada y un
    _run_agent_task que registra la tarea (cero modelo, cero disco real)."""
    lineas, avisos, tareas, mostradas = [], [], [], []
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(str(t)))
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, detalle="": avisos.append((via, detalle)))
    monkeypatch.setattr(cli, "_show_response",
                        lambda t, *a, **k: mostradas.append(str(t)))

    def _agente_fake(ai, tarea, print_fn, **kw):
        tareas.append(tarea)
        return RESPUESTA_AGENTE

    monkeypatch.setattr(cli, "_run_agent_task", _agente_fake)
    monkeypatch.delenv("COGNIA_CHAT_AFIRMACIONES", raising=False)
    # historial de la sesion: la peticion original + la respuesta del chat
    # con comandos (asi "hazlo tu" tiene de donde reencaminar)
    monkeypatch.setattr(cli, "_history", [
        {"role": "user", "content": PETICION},
        {"role": "assistant", "content": RESPUESTA_LINUX},
    ])
    return lineas, avisos, tareas, mostradas


def test_cierre_avisa_y_reencamina_al_agente(arnes):
    """La respuesta inventada del transcript, tal cual saldria del stream:
    aviso visible + ambar, el agente recibe la PETICION ORIGINAL (no "hazlo
    tu") y la respuesta final es la del agente (la inventada no se persiste:
    el llamador persiste lo devuelto)."""
    lineas, avisos, tareas, mostradas = arnes
    final, disparo = cli._chat_afirmaciones_cierre(
        None, "hazlo tu", RESPUESTA_INVENTADA)
    assert disparo
    assert final == RESPUESTA_AGENTE          # la inventada NO sobrevive
    assert any("el chat no ejecuta nada" in l for l in lineas), lineas
    assert any(v == "chat.afirma_accion" for v, _ in avisos), avisos
    assert len(tareas) == 1
    assert tareas[0].startswith(PETICION)     # peticion original, no el eco
    assert "SIN ejecutar" in tareas[0]        # contexto honesto para el agente
    assert RESPUESTA_AGENTE in mostradas      # se muestra como respuesta final


def test_cierre_no_dispara_con_una_explicacion(arnes):
    """Explicar comandos != afirmar haberlos corrido."""
    lineas, avisos, tareas, _ = arnes
    final, disparo = cli._chat_afirmaciones_cierre(
        None, "que comandos usaria para limpiar capturas?", RESPUESTA_LINUX)
    assert not disparo
    assert final == RESPUESTA_LINUX
    assert tareas == []
    assert not any("el chat no ejecuta nada" in l for l in lineas)


def test_env_cero_apaga_el_detector(arnes, monkeypatch):
    _, _, tareas, _ = arnes
    monkeypatch.setenv("COGNIA_CHAT_AFIRMACIONES", "0")
    final, disparo = cli._chat_afirmaciones_cierre(
        None, "hazlo tu", RESPUESTA_INVENTADA)
    assert not disparo and final == RESPUESTA_INVENTADA and tareas == []


def test_confianza_acciones_off_apaga_y_persiste(arnes):
    """Puerta en el CLI: /confianza acciones off -> config 'chat_afirmaciones'
    y el cierre deja de disparar."""
    lineas, _, tareas, _ = arnes
    cli._slash_confianza("acciones off")
    assert cli._load_config().get("chat_afirmaciones") == "off"
    assert not cli._chat_afirmaciones_activo()
    final, disparo = cli._chat_afirmaciones_cierre(
        None, "hazlo tu", RESPUESTA_INVENTADA)
    assert not disparo and tareas == []
    cli._slash_confianza("acciones on")
    assert cli._chat_afirmaciones_activo()


def test_confianza_acciones_argumento_malo_no_persiste(arnes):
    lineas, _, _, _ = arnes
    cli._slash_confianza("acciones quizas")
    assert "Uso:" in lineas[-1]
    assert cli._load_config().get("chat_afirmaciones", "on") == "on"


def test_tarea_reencaminada_sin_historial_cae_a_raw(arnes, monkeypatch):
    monkeypatch.setattr(cli, "_history", [])
    assert cli._tarea_reencaminada("hazlo tu") == "hazlo tu"


def test_tarea_reencaminada_con_peticion_sustantiva_directa(arnes):
    # si raw YA es la peticion (el detector de afirmaciones disparo sobre
    # ella), no se busca en el historial
    t = cli._tarea_reencaminada(PETICION, previa=RESPUESTA_INVENTADA)
    assert t.startswith(PETICION)
    assert "SIN ejecutar" in t


def test_config_y_puerta_registradas():
    assert cli._CONFIG_DEFAULTS.get("chat_afirmaciones") == "on"
    assert "acciones on|off" in cli._CMD_DESCRIPTIONS["/confianza"]
    assert "COGNIA_CHAT_AFIRMACIONES" in cli._CMD_DESCRIPTIONS["/confianza"]
    assert "chat_afirmaciones" in cli._CMD_DETAILS["/confianza"]


def test_cierre_cableado_en_el_fast_path():
    """El cierre tiene que estar LLAMADO desde el fast-path, no solo definido
    (leccion del repo: 'registrado' != 'el modelo lo recibe')."""
    src = Path(cli.__file__).read_text(encoding="utf-8", errors="replace")
    # def + al menos una llamada real
    assert len(re.findall(r"_chat_afirmaciones_cierre\(", src)) >= 2
    # y la llamada vive junto al cierre del stream (_full_response)
    assert "_chat_afirmaciones_cierre(\n                                                    ai, raw, _full_response)" in src


# ── el transcript entero, turno a turno, contra el detector de intent ─────

def test_transcript_entero_ningun_turno_de_accion_cae_al_chat():
    """Rejuego de la sesion del dueno: cada turno de accion tiene que ir al
    agente; los conversacionales, al chat."""
    assert not detect("hola").needs_agent
    assert not detect("soy Tomas Montes el creador de este harness").needs_agent
    r1 = detect(PETICION)
    assert r1.needs_agent and r1.reason == "accion:sistema"
    # "hazlo tu" tras la respuesta con comandos linux
    r2 = detect("hazlo tu", respuesta_previa=RESPUESTA_LINUX)
    assert r2.needs_agent and r2.reason == "continuacion:accion"
    r3 = detect("no los ejecutaste")
    assert r3.needs_agent and r3.reason == "reclamo:no_ejecutado"
