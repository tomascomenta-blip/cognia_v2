"""
WP5 (obra 2026-08-09): el remoto consume EVENTOS TIPADOS, no regex.

La sesion remota lanza el REPL con COGNIA_EVENTS_JSONL=1: el bus de
ux/events.py escribe "@EV {json}" por stdout y sesiones.py clasifica por
TIPO. El regex historico queda de fallback para la prosa. Aqui se verifica
hermeticamente (lineas sinteticas, sin modelo ni subproceso real):

  1. el parser de lineas-evento (prefijada y JSON pelado, sin falsos positivos)
  2. el mapa evento -> (quien, texto) de la transcripcion
  3. el pipeline de _procesar_linea (gate de arranque, ecos del renderer)
  4. la regresion del gate: el arranque COMPACTO ya no imprime "Sistema
     listo" y el gate viejo se comia las primeras 200 lineas de cada sesion
  5. el volcado del traceback si el REPL muere al arrancar (antes: silencio)
  6. los niveles de permiso por sesion (total/restringido) y su persistencia
  7. el prefijo del sink stdout en ux/events.py
"""

import json

import pytest

from cognia.remoto import sesiones as _ses
from cognia.remoto.sesiones import (Sesion, es_eco_renderer,
                                    interpretar_evento, parsear_evento)


def _ev(tipo: str, **campos) -> str:
    return "@EV " + json.dumps({"tipo": tipo, "ts": 0.0, **campos},
                               ensure_ascii=False)


# ── 1. parser de lineas-evento ─────────────────────────────────────────────

def test_parsear_evento_prefijado():
    d = parsear_evento(_ev("ToolInicio", tool="leer_archivo", args="x.py"))
    assert d and d["tipo"] == "ToolInicio" and d["tool"] == "leer_archivo"


def test_parsear_evento_json_pelado_solo_tipos_del_contrato():
    # red por si el prefijo se pierde: un JSON pelado con tipo del contrato SI
    crudo = json.dumps({"tipo": "Degradado", "donde": "x", "motivo": "y"})
    assert parsear_evento(crudo)["tipo"] == "Degradado"
    # ...pero un JSON ajeno con clave "tipo" (comunisima en datos en espanol)
    # NO es un evento: el agente muestra ficheros JSON todo el tiempo
    assert parsear_evento('{"tipo": "gasto", "monto": 100}') is None
    assert parsear_evento("prosa normal del CLI") is None
    assert parsear_evento("@EV esto no es json") is None


# ── 2. mapa evento -> transcripcion ────────────────────────────────────────

def test_interpretar_toolfin_ok_va_a_actividad_plegable():
    quien, texto, ecos = interpretar_evento(
        {"tipo": "ToolFin", "tool": "leer_archivo", "args": "motor.py",
         "ok": True, "resumen": "42 lineas\nsegunda linea del resumen"})
    assert quien == "actividad"
    assert texto.startswith("⏺ leer_archivo motor.py — 42 lineas")
    # las lineas 2-3 del resumen las imprime el renderer sin marca: van a
    # ecos para que el fallback no las cuele como chat
    assert ecos == ["segunda linea del resumen"]


def test_interpretar_toolfin_fallo_se_ve_como_fallo():
    quien, texto, _ = interpretar_evento(
        {"tipo": "ToolFin", "tool": "ejecutar", "args": "pytest",
         "ok": False, "resumen": "ERROR: exit 1"})
    assert quien == "actividad" and "fallo" in texto and "✗" in texto


def test_interpretar_degradado_visible_en_chat():
    quien, texto, _ = interpretar_evento(
        {"tipo": "Degradado", "donde": "agente.bucle_nativo",
         "motivo": "server caido",
         "accion_sugerida": "python scripts/servir_flota.py pensar"})
    assert quien == "sistema", "un degradado JAMAS se pliega ni se esconde"
    assert "server caido" in texto and "servir_flota" in texto


def test_interpretar_streaming_y_eco_no_se_anotan():
    for tipo in ("TareaInicio", "TokenTexto", "RazonamientoTick"):
        quien, _, _ = interpretar_evento({"tipo": tipo, "texto": "x"})
        assert quien is None, tipo


def test_interpretar_tareafin_cierre_compacto():
    quien, texto, _ = interpretar_evento(
        {"tipo": "TareaFin", "ok": True, "pasos": 3, "duracion_s": 12.5,
         "tokens_predichos": 900, "resumen": "hecho"})
    assert quien == "actividad"
    assert "✓" in texto and "3 pasos" in texto and "900 tokens" in texto


def test_interpretar_tipo_desconocido_no_se_pierde_en_silencio():
    quien, texto, _ = interpretar_evento({"tipo": "EventoNuevo", "x": 1})
    assert quien == "actividad" and "EventoNuevo" in texto


# ── 3./4. pipeline de _procesar_linea ──────────────────────────────────────

_PANEL_COMPACTO = [
    "cognia v4.6 · sistema cognitivo local",
    "  modelo gpt-oss-20b (:8080)",
    "  cwd    C:/proy",
    "  /ayuda para comandos · /hacer <tarea> para el agente",
]


def _sesion(tmp_path, monkeypatch) -> Sesion:
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    return Sesion(id="s1", proyecto_id="p1", ruta_proyecto=str(tmp_path),
                  titulo="t")


def _transcrito(s: Sesion) -> list[tuple[str, str]]:
    lineas = s.fichero.read_text(encoding="utf-8").splitlines()
    return [(e["quien"], e["texto"])
            for e in map(json.loads, lineas)]


def test_pipeline_eventos_clasifican_y_los_ecos_no_duplican(tmp_path,
                                                            monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    for linea in _PANEL_COMPACTO:
        s._procesar_linea(linea)
    for linea in [
        _ev("TareaInicio", tarea="haz algo", modo="agente"),
        _ev("PasoIntencion", paso=1, intencion="Voy a leer motor.py"),
        "  Voy a leer motor.py",                     # eco del renderer
        _ev("ToolInicio", tool="leer_archivo", args="motor.py", paso=1),
        _ev("ToolFin", tool="leer_archivo", args="motor.py", ok=True,
            resumen="42 lineas\ndetalle extra", paso=1),
        "  ⏺ Leyendo motor.py — 42 lineas",          # eco del renderer
        "    detalle extra",                          # eco (resumen linea 2)
        _ev("Degradado", donde="backend", motivo="sin slots"),
        "La respuesta final para el usuario.",        # prosa -> chat
        "  3.2s · 500 tokens · 2 pasos",              # footer del renderer
        _ev("TareaFin", ok=True, pasos=2, duracion_s=3.2,
            tokens_predichos=500),
    ]:
        s._procesar_linea(linea)
    got = _transcrito(s)
    assert ("actividad", "Voy a leer motor.py") in got
    assert any(q == "actividad" and t.startswith("· leer_archivo")
               for q, t in got)
    assert any(q == "actividad" and t.startswith("⏺ leer_archivo motor.py")
               for q, t in got)
    assert any(q == "sistema" and "sin slots" in t for q, t in got)
    assert ("cognia", "La respuesta final para el usuario.") in got
    assert any(q == "actividad" and t.startswith("✓ tarea terminada")
               for q, t in got)
    # ningun duplicado: los ecos del renderer no llegaron a la transcripcion
    textos = [t for _, t in got]
    assert len(textos) == len(set(textos)), textos
    assert "  ⏺ Leyendo motor.py — 42 lineas" not in textos
    # el panel de arranque no llego ni al chat ni al registro
    assert not any("sistema cognitivo local" in t for t in textos)


def test_gate_arranque_compacto_no_se_come_la_respuesta(tmp_path,
                                                        monkeypatch):
    """REGRESION tanda 1: el arranque compacto ya no imprime "Sistema listo";
    con el gate viejo, las primeras 200 lineas de CADA sesion (respuesta del
    modelo incluida) se descartaban. El gate debe cerrar con la ultima linea
    del panel compacto."""
    s = _sesion(tmp_path, monkeypatch)
    for linea in _PANEL_COMPACTO:
        s._procesar_linea(linea)
    assert s._arrancando is False
    s._procesar_linea("Hola, soy la respuesta.")
    assert ("cognia", "Hola, soy la respuesta.") in _transcrito(s)


def test_gate_arranque_banner_full_sigue_funcionando(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    s._procesar_linea("linea de banner gigante")
    s._procesar_linea("[OK] Sistema listo")
    assert s._arrancando is False


def test_es_eco_renderer():
    assert es_eco_renderer("  ⏺ Leyendo x — 42 lineas")
    assert es_eco_renderer("  · pensando…")
    assert es_eco_renderer("  ✗ ejecutar — fallo")
    assert es_eco_renderer("  ⚠ degradado — backend")
    assert es_eco_renderer("  → python scripts/servir_flota.py pensar")
    assert es_eco_renderer("3.2s · 500 tokens · 2 pasos")
    assert es_eco_renderer("12s · 3 pasos")
    assert not es_eco_renderer("La respuesta normal.")
    assert not es_eco_renderer("2026 fue un buen anio")


# ── 5. el REPL muere al arrancar: el traceback se VE ───────────────────────

class _ProcMuerto:
    """stdout con un traceback de arranque y exit code 1 (import roto)."""

    def __init__(self, lineas):
        self.stdout = iter(lineas)

    def wait(self, timeout=None):
        return 1

    def poll(self):
        return 1


def test_repl_muerto_al_arrancar_vuelca_el_traceback(tmp_path, monkeypatch):
    """Antes: el gate de arranque descartaba el traceback y el movil veia
    puro silencio (sesiones.py 307-313 historico)."""
    s = _sesion(tmp_path, monkeypatch)
    s.proc = _ProcMuerto([
        "Traceback (most recent call last):",
        '  File "cognia/cli.py", line 1, in <module>',
        "ImportError: No module named rich",
    ])
    s._bombear()
    got = _transcrito(s)
    # el aviso visible lleva el exit code y la ultima linea (la del error)
    aviso = [t for q, t in got if q == "sistema" and "murio al arrancar" in t]
    assert aviso and "exit 1" in aviso[0] and "ImportError" in aviso[0]
    # el traceback completo queda en el Registro
    assert ("log", "Traceback (most recent call last):") in got
    assert ("log", "ImportError: No module named rich") in got
    assert any(q == "sistema" and "sesion terminada (exit 1)" in t
               for q, t in got)


def test_salida_limpia_no_vuelca_nada(tmp_path, monkeypatch):
    class _ProcOk(_ProcMuerto):
        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    s = _sesion(tmp_path, monkeypatch)
    s.proc = _ProcOk(["banner cualquiera"])
    s._bombear()
    got = _transcrito(s)
    assert not any("murio al arrancar" in t for _, t in got)
    assert ("sistema", "sesion terminada") in got


# ── 6. niveles de permiso por sesion ───────────────────────────────────────

def test_entorno_acceso_total_es_el_historico(tmp_path, monkeypatch):
    s = _sesion(tmp_path, monkeypatch)
    env = s._entorno()
    assert env["COGNIA_ACCESO_TOTAL"] == "1"
    assert env["COGNIA_SCREEN"] == "1" and env["COGNIA_SCREEN_AUTO"] == "1"
    # el canal de eventos SIEMPRE va (es el contrato del remoto nuevo)
    assert env["COGNIA_EVENTS_JSONL"] == "1"
    assert env["COGNIA_REMOTO"] == "1"


def test_entorno_restringido_sin_acceso_total(tmp_path, monkeypatch):
    # aunque el SERVIDOR corra con la var puesta, la sesion restringida la
    # limpia: heredarla seria un bypass silencioso del nivel de permiso
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    monkeypatch.setenv("COGNIA_SCREEN", "1")
    s = _sesion(tmp_path, monkeypatch)
    s.acceso = "restringido"
    env = s._entorno()
    assert "COGNIA_ACCESO_TOTAL" not in env
    assert "COGNIA_SCREEN" not in env and "COGNIA_SCREEN_AUTO" not in env
    assert env["COGNIA_EVENTS_JSONL"] == "1"


def test_acceso_persiste_y_no_se_escala_al_reabrir(tmp_path, monkeypatch):
    """Una sesion creada restringida NO puede reabrirse con acceso total:
    el nivel viaja en la meta del jsonl y obtener() lo restaura."""
    from cognia.remoto.sesiones import GestorSesiones
    monkeypatch.setattr(_ses, "RAIZ_DATOS", tmp_path)
    monkeypatch.setattr(Sesion, "arrancar", lambda self: None)
    proyecto = {"id": "p1", "ruta": str(tmp_path)}
    g = GestorSesiones()
    s = g.crear(proyecto, "t", acceso="restringido")
    assert s.acceso == "restringido"
    # un gestor NUEVO (reinicio del servidor) reabre la sesion desde disco
    g2 = GestorSesiones()
    assert g2.obtener(proyecto, s.id).acceso == "restringido"
    # un valor invalido cae al default historico, no revienta
    assert g.crear(proyecto, "t2", acceso="raro").acceso == "total"


# ── 7. el sink stdout de ux/events.py lleva el prefijo ─────────────────────

def test_sink_stdout_prefija_las_lineas(capsys, monkeypatch):
    from cognia.ux import events
    # bus limpio y sink virgen para este test (es un singleton de modulo)
    monkeypatch.setattr(events, "_sink_jsonl", None)
    monkeypatch.setattr(events, "_suscriptores", [])
    events.activar_sink_jsonl("1")
    events.emitir(events.Aviso(texto="hola", origen="test"))
    salida = capsys.readouterr().out.strip()
    assert salida.startswith(events.PREFIJO_STDOUT)
    d = json.loads(salida[len(events.PREFIJO_STDOUT):])
    assert d["tipo"] == "Aviso" and d["texto"] == "hola"
    # y sesiones.py lo parsea de vuelta: el contrato cierra el circulo
    assert parsear_evento(salida)["tipo"] == "Aviso"


def test_evento_pegado_a_prosa_a_medias_se_separa(tmp_path, monkeypatch):
    """E2E 2026-08-09: el sink y el renderer comparten stdout y una linea-
    evento puede caer pegada a una frase a medias del streaming. El evento se
    procesa y la prosa no se pierde; si la prosa era el ECO del renderer del
    mismo evento (aviso pintado sin marca), se suprime."""
    s = _sesion(tmp_path, monkeypatch)
    s._arrancando = False
    s._procesar_linea(
        "  ¡Hola! ¿En qué puedo " + _ev("Aviso", texto="backend: :8080"))
    got = _transcrito(s)
    assert ("actividad", "⚠ backend: :8080") in got
    assert any(q == "cognia" and t.strip() == "¡Hola! ¿En qué puedo"
               for q, t in got), "la prosa no se pierde"
    # eco del renderer pegado al MISMO evento en una linea: se suprime entero
    s._procesar_linea("  backend: :8080 " + _ev("Aviso", texto="backend: :8080"))
    textos = [t for _, t in _transcrito(s)]
    assert "backend: :8080" not in textos, "el eco del aviso no va al chat"


def test_aviso_eco_del_renderer_no_duplica(tmp_path, monkeypatch):
    """El renderer imprime el Aviso como '  {texto}' SIN marca: el eco tiene
    que suprimirse (e2e 2026-08-09: 'backend: ...' salia duplicado, una vez
    como chat y otra como actividad)."""
    s = _sesion(tmp_path, monkeypatch)
    s._arrancando = False
    s._procesar_linea(_ev("Aviso", texto="backend: gpt-oss-20b :8080"))
    s._procesar_linea("  backend: gpt-oss-20b :8080")   # eco del renderer
    got = _transcrito(s)
    assert got == [("actividad", "⚠ backend: gpt-oss-20b :8080")], got


def test_sink_stdout_salta_streaming(capsys, monkeypatch):
    """TokenTexto/RazonamientoTick NO van por stdout: de alta frecuencia, se
    entrelazaban con la prosa a medias del renderer en el mismo stdout (e2e
    2026-08-09). El remoto no los usa; el modo archivo si los guarda."""
    from cognia.ux import events
    monkeypatch.setattr(events, "_sink_jsonl", None)
    monkeypatch.setattr(events, "_suscriptores", [])
    events.activar_sink_jsonl("1")
    events.emitir(events.TokenTexto(texto="hola"))
    events.emitir(events.RazonamientoTick(chars=10))
    assert capsys.readouterr().out == ""
    events.emitir(events.Aviso(texto="si sale", origen="test"))
    assert "@EV" in capsys.readouterr().out


def test_sink_stdout_va_primero_que_el_renderer(monkeypatch):
    """El sink se inserta al FRENTE de los suscriptores: el remoto tiene que
    ver la linea-evento ANTES de que el renderer pinte su version humana en
    el mismo stdout (si no, el eco entra al chat antes que el evento)."""
    from cognia.ux import events
    monkeypatch.setattr(events, "_sink_jsonl", None)
    orden = []
    renderer_falso = lambda ev: orden.append("renderer")
    monkeypatch.setattr(events, "_suscriptores", [renderer_falso])
    real_print = print
    monkeypatch.setattr("builtins.print",
                        lambda *a, **k: orden.append("sink"))
    events.activar_sink_jsonl("1")
    events.emitir(events.Aviso(texto="x", origen="t"))
    monkeypatch.undo()
    assert orden == ["sink", "renderer"], orden


def test_sink_a_fichero_sigue_sin_prefijo(tmp_path, monkeypatch):
    """El modo archivo es JSONL puro (telemetria): el prefijo es SOLO del
    modo stdout, donde hay prosa mezclada."""
    from cognia.ux import events
    monkeypatch.setattr(events, "_sink_jsonl", None)
    monkeypatch.setattr(events, "_suscriptores", [])
    ruta = tmp_path / "eventos.jsonl"
    events.activar_sink_jsonl(str(ruta))
    events.emitir(events.Aviso(texto="x", origen="test"))
    linea = ruta.read_text(encoding="utf-8").strip()
    assert linea.startswith("{")
    assert json.loads(linea)["tipo"] == "Aviso"
