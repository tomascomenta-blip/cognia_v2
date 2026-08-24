"""
Estetica del renderer (2026-08-10): pensar en verde, razonamiento opcional en
vivo, preview de lo escrito, gerundios contra el registry real y footer con
glifo solo local.

Cada test falla sin su fix:
- el status de 'pensando…' usaba [spinner] (magenta) en vez de [pensar] (verde),
- el razonamiento jamas se mostraba como texto (ni con flag),
- ToolFin no mostraba QUE se escribio en el archivo,
- GERUNDIOS tenia claves fantasma ('listar_archivos'/'buscar_archivos') que no
  existen en agent/tools.py TOOLS — esas tools salian como 'Trabajando',
- el footer no distinguia ok/fallo de la tarea.

CONTRATOS QUE ESTOS TESTS PROTEGEN (lectura 'remoto' de inv_cli.json):
- el TEXTO de la linea '⏺ Verbo obj — cabeza' no cambia (es_eco_renderer),
- el footer bajo COGNIA_REMOTO sigue plano ('Ns · M tokens · K pasos'),
- nada del razonamiento se streamea bajo COGNIA_REMOTO=1.
"""
import importlib.util
import io

import pytest

from cognia.ux import events
from cognia.ux.estilo import GERUNDIOS, verbo_de
from cognia.ux.renderer import Renderer


# ---------------------------------------------------------------------------
# Dobles minimos: consola que graba markup/estilos sin pintar nada.
# ---------------------------------------------------------------------------

class _StatusFalso:
    def __init__(self, texto, spinner=None):
        self.texto = texto
        self.spinner = spinner
        self.updates = []

    def start(self):
        pass

    def stop(self):
        pass

    def update(self, texto):
        self.updates.append(texto)


class _ConsolaFalsa:
    """Graba lo que el renderer pediria pintar: statuses (markup + spinner) y
    prints (texto + kwargs). Sin rich de por medio: probamos la DECISION del
    renderer, no el pintado de rich."""

    def __init__(self):
        self.statuses = []
        self.impresos = []

    def status(self, texto, spinner=None):
        st = _StatusFalso(texto, spinner)
        self.statuses.append(st)
        return st

    def print(self, *args, **kwargs):
        self.impresos.append((args, kwargs))


def _tema_de_prueba():
    """Espejo de las claves nuevas que el wiring agrega a _THEMES (oscuro)."""
    rich = pytest.importorskip("rich")     # noqa: F841 (venv312 lo tiene)
    from rich.theme import Theme
    return Theme({
        "ok_cl": "green", "pensar": "green", "tool_verbo": "cyan",
        "tool_obj": "bold bright_white", "escrito": "green", "borrado": "red",
        "intencion": "italic dim white", "spinner": "green",
        "info_dim": "dim grey62", "footer": "dim grey50",
        "warn_cl": "yellow", "err_cl": "red",
        # decision 17 (2026-08-17): la respuesta va en texto NORMAL
        "respuesta": "default",
    })


def _consola_rich():
    from rich.console import Console
    buf = io.StringIO()
    return Console(file=buf, theme=_tema_de_prueba(), highlight=False,
                   width=200, force_terminal=False), buf


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    # el renderer lee COGNIA_PENSAR a call-time y COGNIA_REMOTO en init y en
    # call-time: cada test parte de un entorno conocido.
    monkeypatch.delenv("COGNIA_PENSAR", raising=False)
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    # el preview del agente pinta las bandas de la variante ACTIVA
    # (diff_render.variante_activa lee COGNIA_THEME): la maquina que corre la
    # suite no puede decidir con que tema se mide.
    monkeypatch.delenv("COGNIA_THEME", raising=False)
    # Bajo pytest stdout NO es un tty, y desde 2026-08-15 eso basta para que el
    # spinner no arranque. Estos tests miden el ESTILO del status, no cuando
    # aparece: se fuerza el modo interactivo. Quien mide lo otro es
    # test_spinner_no_anima_sin_tty, que borra la variable a proposito.
    monkeypatch.setenv("COGNIA_SPINNER", "1")


# ---------------------------------------------------------------------------
# 1) pensando… SIEMPRE en verde: markup [pensar], spinner dots
# ---------------------------------------------------------------------------

def test_pensando_usa_estilo_pensar_y_dots():
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.RazonamientoTick(chars=10, fragmento="a"))
    assert len(con.statuses) == 1
    st = con.statuses[0]
    assert "[pensar]" in st.texto and "[/pensar]" in st.texto
    assert "pensando…" in st.texto
    assert "[spinner]" not in st.texto
    assert st.spinner == "dots"


def test_pensando_update_conserva_pensar_y_segundos(monkeypatch):
    # F2 (2026-08-23): con la linea VIVA activa el update es del ticker de
    # spinner_vivo; este test mide el camino CLASICO, que sigue intacto con
    # la linea viva apagada (COGNIA_SPINNER_INFO=0, el apagado de emergencia).
    monkeypatch.setenv("COGNIA_SPINNER_INFO", "0")
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.RazonamientoTick(chars=10, fragmento="a"))
    r(events.RazonamientoTick(chars=20, fragmento="b"))
    st = con.statuses[0]
    assert st.updates, "el segundo tick debe actualizar el status"
    assert "[pensar]" in st.updates[-1]
    assert "s)" in st.updates[-1]           # el (Ns) de hoy sigue


def test_pensando_con_linea_viva_el_ticker_es_el_dueno(monkeypatch):
    # F2: linea viva activa -> el segundo tick NO pisa el texto (el ticker de
    # 1s es el unico que actualiza; dos escritores harian parpadear la linea)
    monkeypatch.setenv("COGNIA_SPINNER_INFO", "1")
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.RazonamientoTick(chars=10, fragmento="a"))
    try:
        assert r._ticker is not None
        r(events.RazonamientoTick(chars=20, fragmento="b"))
        st = con.statuses[0]
        assert not st.updates                # el tick manual quedo callado
    finally:
        r._parar_status()

def test_spinner_no_anima_sin_tty(monkeypatch, capsys):
    """Sin terminal de verdad: linea quieta, NO status animado.

    Regresion medida 2026-08-15 capturando el REPL a PNG: el modulo declara en
    su cabecera 'sin terminal, a lineas quietas' pero nadie miraba el fd, asi
    que con FORCE_COLOR (script de captura, CI, cualquier pipe) rich animaba
    sin poder mover el cursor y escribia UNA LINEA POR FRAME — 6 s de
    'pensando…' = ~250 lineas de basura en la traza donde se diagnostica.
    """
    monkeypatch.delenv("COGNIA_SPINNER", raising=False)   # autodeteccion real
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1))
    assert con.statuses == [], "sin tty no se arranca ningun status animado"
    # y la informacion NO se pierde: cae a la linea quieta por la MISMA consola
    texto = " ".join(str(a) for args, _ in con.impresos for a in args)
    assert "Leyendo" in texto and "motor.py" in texto


def test_tool_spinner_sigue_usando_spinner():
    # las tools NO cambian de clave: el verde les llega por el wiring del
    # tema ('spinner' pasa a verde en los 3 temas), no por markup nuevo.
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1))
    assert "[spinner]" in con.statuses[-1].texto


# ---------------------------------------------------------------------------
# 2) razonamiento OPCIONAL en vivo (COGNIA_PENSAR=ver)
# ---------------------------------------------------------------------------

def test_razonamiento_oculto_por_defecto(capsys):
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=30, fragmento="pienso en voz alta secreta\n"))
    out = capsys.readouterr().out
    assert "pienso en voz alta secreta" not in out
    assert "∴" not in out                    # solo el spinner/linea quieta


def test_razonamiento_oculto_con_valor_oculto(capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_PENSAR", "oculto")
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=30, fragmento="nada de esto se ve\n"))
    assert "nada de esto se ve" not in capsys.readouterr().out


def test_razonamiento_visible_con_ver(capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    r = Renderer(console=None)
    r(events.RazonamientoTick(
        chars=40, fragmento="Voy a mirar el archivo de config\n"))
    r(events.TokenTexto(texto="Hola, esta es la respuesta final del turno."))
    r(events.TareaFin(ok=True, resumen="", pasos=1, duracion_s=2.0))
    out = capsys.readouterr().out
    # prosa del pensamiento: sangria 4 + marca '∴ ' al inicio de la linea
    assert "    ∴ Voy a mirar el archivo de config" in out
    # y la respuesta real tambien salio (el flujo pensar se cerro antes)
    assert "Hola, esta es la respuesta" in out
    pos_pensar = out.find("∴")
    pos_resp = out.find("Hola, esta es")
    assert 0 <= pos_pensar < pos_resp        # el pensamiento va ANTES


def test_flag_ver_se_lee_a_call_time(capsys, monkeypatch):
    # /pensar setea os.environ en el MISMO proceso: el renderer no se recrea.
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=10, fragmento="antes del flag\n"))
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    r(events.RazonamientoTick(chars=20, fragmento="despues del flag\n"))
    r(events.TareaFin(ok=True, resumen="", pasos=1, duracion_s=2.0))
    out = capsys.readouterr().out
    assert "antes del flag" not in out
    assert "∴ despues del flag" in out


def test_razonamiento_jamas_en_remoto(capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=40, fragmento="secreto que el movil no ve\n"))
    out = capsys.readouterr().out
    assert "secreto que el movil no ve" not in out
    assert "∴" not in out


def test_tool_inicio_cierra_el_flujo_pensar(capsys, monkeypatch):
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    r = Renderer(console=None)
    r(events.RazonamientoTick(chars=20, fragmento="leo primero el codigo\n"))
    r(events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1))
    out = capsys.readouterr().out
    assert "∴ leo primero el codigo" in out
    assert r._flujo_pensar is None           # cerrado por ToolInicio


# ---------------------------------------------------------------------------
# 3) ToolFin: texto EXACTO (semi-contrato) + preview de lo escrito
# ---------------------------------------------------------------------------

def test_tool_fin_rico_conserva_el_texto_exacto():
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                     resumen="42 lineas", paso=1))
    # el texto plano de la linea NO cambia: es_eco_renderer del remoto y el
    # test wp3 dependen de esta forma exacta
    assert "⏺ Leyendo motor.py — 42 lineas" in buf.getvalue()


def test_tool_fin_fallo_conserva_el_texto_exacto():
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.ToolFin(tool="ejecutar", args="pytest -q", ok=False,
                     resumen="exit 1", paso=1))
    assert "✗ Ejecutando pytest — fallo: exit 1" in buf.getvalue()


def test_preview_escribir_archivo_hasta_3_lineas(capsys):
    args = "nota.txt | uno\ndos\ntres\ncuatro"
    r = Renderer(console=None)
    r(events.ToolFin(tool="escribir_archivo", args=args, ok=True,
                     resumen="RESULTADO escribir_archivo nota.txt: OK", paso=1))
    out = capsys.readouterr().out
    assert "      + uno" in out
    assert "      + dos" in out
    assert "      + tres…" in out            # hay una 4a linea: '…' honesto
    assert "cuatro" not in out


def test_preview_marca_truncado_del_productor(capsys):
    # loop.py trunca args a [:120]: un args de exactamente 120 chars quedo
    # cortado y el preview lo dice con '…' al final
    args = ("x.txt | " + "a" * 200)[:120]
    r = Renderer(console=None)
    r(events.ToolFin(tool="escribir_archivo", args=args, ok=True,
                     resumen="OK", paso=1))
    lineas = [l for l in capsys.readouterr().out.split("\n")
              if l.startswith("      + ")]
    assert len(lineas) == 1
    assert lineas[0].endswith("…")


def test_preview_editar_archivo_borrado_y_escrito(capsys):
    args = ("app.py | <<<<<<< SEARCH\nviejo()\n=======\nnuevo()\n"
            ">>>>>>> REPLACE")
    r = Renderer(console=None)
    r(events.ToolFin(tool="editar_archivo", args=args, ok=True,
                     resumen="RESULTADO editar_archivo app.py: OK", paso=1))
    out = capsys.readouterr().out
    assert "      - viejo()" in out
    assert "      + nuevo()" in out


def test_preview_no_sale_si_fallo(capsys):
    r = Renderer(console=None)
    r(events.ToolFin(tool="escribir_archivo", args="x.txt | contenido",
                     ok=False, resumen="ERROR: sin permiso", paso=1))
    assert "      + " not in capsys.readouterr().out


def test_preview_no_sale_en_remoto(capsys, monkeypatch):
    # lineas nuevas que es_eco_renderer no conoce llegarian al chat del movil
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    r(events.ToolFin(tool="escribir_archivo", args="x.txt | contenido",
                     ok=True, resumen="OK", paso=1))
    assert "      + " not in capsys.readouterr().out


def test_leer_archivo_no_tiene_preview(capsys):
    r = Renderer(console=None)
    r(events.ToolFin(tool="leer_archivo", args="motor.py | desde=1",
                     ok=True, resumen="42 lineas", paso=1))
    assert "      + " not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 3 bis) PUNTOS 2 y 3 del juicio visual: el preview del AGENTE es un diff
# ---------------------------------------------------------------------------
# El preview que sale en CADA /hacer escribia '+ linea' con style='escrito' y
# '- linea' con style='borrado': texto pelado, sin banda, y con la asimetria
# que la decision 12 ya habia matado en el diff de /editar ('+' 9,34:1 contra
# '-' 4,92:1). Ahora pasa por console/diff_render.render_bloque: mismo lenguaje
# visual, y las bandas salen del tema por variante.

def _consola_grabadora(variante="oscuro"):
    """Console de verdad (truecolor, ancho fijo) para mirar los BYTES."""
    from rich.console import Console
    from rich.theme import Theme
    from cognia.ux import paleta
    return Console(record=True, width=80, force_terminal=True,
                   color_system="truecolor", legacy_windows=False,
                   theme=Theme(paleta.tema_cli(variante)),
                   file=io.StringIO(), highlight=False)


def _fondo_ansi(hexa: str) -> str:
    h = hexa.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"48;2;{r};{g};{b}"


def test_preview_escritura_pinta_la_banda_del_diff():
    from cognia.ux import paleta
    con = _consola_grabadora()
    r = Renderer(console=con)
    r(events.ToolFin(tool="escribir_archivo", args="nota.txt | uno\ndos",
                     ok=True, resumen="OK", paso=1))
    crudo = con.export_text(styles=True, clear=False)
    assert _fondo_ansi(paleta.DIFF_FONDO["oscuro"]["mas"]) in crudo, crudo
    # y sigue siendo el MISMO texto que antes (sangria de 6 + '+ ')
    plano = [l.rstrip() for l in con.export_text(clear=False).split("\n")]
    assert "      + uno" in plano and "      + dos" in plano


def test_preview_edicion_pinta_LAS_DOS_bandas():
    from cognia.ux import paleta
    con = _consola_grabadora()
    r = Renderer(console=con)
    r(events.ToolFin(tool="editar_archivo",
                     args="app.py | <<<<<<< SEARCH\nviejo()\n=======\n"
                          "nuevo()\n>>>>>>> REPLACE",
                     ok=True, resumen="OK", paso=1))
    crudo = con.export_text(styles=True, clear=False)
    assert _fondo_ansi(paleta.DIFF_FONDO["oscuro"]["mas"]) in crudo
    assert _fondo_ansi(paleta.DIFF_FONDO["oscuro"]["menos"]) in crudo
    plano = [l.rstrip() for l in con.export_text(clear=False).split("\n")]
    assert "      - viejo()" in plano and "      + nuevo()" in plano


def test_preview_obedece_a_tema_claro(monkeypatch):
    """Punto 3: con '/tema claro' el preview deja de ser una isla negra."""
    from cognia.ux import paleta
    monkeypatch.setenv("COGNIA_THEME", "claro")
    con = _consola_grabadora("claro")
    r = Renderer(console=con)
    r(events.ToolFin(tool="escribir_archivo", args="nota.txt | uno",
                     ok=True, resumen="OK", paso=1))
    crudo = con.export_text(styles=True, clear=False)
    assert _fondo_ansi(paleta.DIFF_FONDO["claro"]["mas"]) in crudo, crudo
    assert _fondo_ansi(paleta.DIFF_FONDO["oscuro"]["mas"]) not in crudo


def test_preview_del_agente_no_rompe_al_movil():
    """CONTRATO. remoto/sesiones.py clasifica el chat del movil por el arranque
    de la linea: '+ ' es ACTIVIDAD. Las lineas REALES que emite el preview
    (pintadas, con ANSI y relleno de banda) tienen que clasificar EXACTAMENTE
    igual que las lineas planas de siempre, o el diff del agente se le cuela al
    dueno como prosa de Cognia en el chat."""
    from cognia.remoto.sesiones import _es_actividad, _limpiar
    con = _consola_grabadora()
    r = Renderer(console=con)
    r(events.ToolFin(tool="editar_archivo",
                     args="app.py | <<<<<<< SEARCH\nviejo()\n=======\n"
                          "nuevo()\n>>>>>>> REPLACE",
                     ok=True, resumen="OK", paso=1))
    limpias = [_limpiar(l) for l in con.export_text(styles=True, clear=False).split("\n")]
    limpias = [l for l in limpias if l]
    assert not any("\x1b" in l for l in limpias)
    assert "      + nuevo()" in limpias, limpias
    assert "      - viejo()" in limpias, limpias
    # la clasificacion, contra la funcion REAL: '+ ' actividad, '- ' no (es lo
    # que ya hacia el preview plano; el pintado no puede cambiarlo)
    assert _es_actividad("      + nuevo()") is True
    assert _es_actividad("      - viejo()") is False
    pintadas = {l: _es_actividad(l) for l in limpias if l.strip()[:1] in "+-"}
    assert pintadas == {"      - viejo()": False, "      + nuevo()": True}


def test_sin_console_el_preview_cae_al_texto_plano_de_siempre(capsys):
    """Degradacion: sin Console (o sin rich) no hay banda, pero el signo del
    margen sigue distinguiendo agregado de borrado."""
    r = Renderer(console=None)
    r(events.ToolFin(tool="editar_archivo",
                     args="app.py | <<<<<<< SEARCH\nviejo()\n=======\n"
                          "nuevo()\n>>>>>>> REPLACE",
                     ok=True, resumen="OK", paso=1))
    out = capsys.readouterr().out
    assert "      - viejo()" in out and "      + nuevo()" in out


# ---------------------------------------------------------------------------
# 4) PasoIntencion en italic ('intencion')
# ---------------------------------------------------------------------------

def test_intencion_usa_estilo_intencion():
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.PasoIntencion(paso=1, intencion="Voy a leer el archivo"))
    estilos = [k.get("style") for a, k in con.impresos if a]
    textos = [a[0] for a, k in con.impresos if a]
    assert any("Voy a leer el archivo" in t for t in textos)
    assert "intencion" in estilos


# ---------------------------------------------------------------------------
# 5) Footer: plano sin rich / en remoto; glifo ✓/✗ solo local con rich
# ---------------------------------------------------------------------------

def test_footer_plano_intacto_sin_rich(capsys):
    r = Renderer(console=None)
    r(events.TareaFin(ok=True, resumen="", pasos=3, tokens_predichos=87,
                      duracion_s=3.2))
    out = capsys.readouterr().out
    assert "  3.2s · 87 tokens · 3 pasos" in out
    assert "✓" not in out and "✗" not in out


def test_footer_con_glifo_ok_en_rich_local():
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.TareaFin(ok=True, resumen="", pasos=3, tokens_predichos=87,
                      duracion_s=3.2))
    assert "✓ 3.2s · 87 tokens · 3 pasos" in buf.getvalue()


def test_footer_con_glifo_error_en_rich_local():
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.TareaFin(ok=False, resumen="", pasos=2, duracion_s=5.0))
    assert "✗ 5.0s · 2 pasos" in buf.getvalue()


def test_footer_remoto_sigue_plano(monkeypatch):
    # bajo remoto el footer debe matchear _RE_FOOTER_RENDERER del de-dup de
    # sesiones.py: sin glifo, exactamente 'Ns · M tokens · K pasos'
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.TareaFin(ok=True, resumen="", pasos=3, tokens_predichos=87,
                      duracion_s=3.2))
    out = buf.getvalue()
    assert "3.2s · 87 tokens · 3 pasos" in out
    assert "✓" not in out and "✗" not in out


# ---------------------------------------------------------------------------
# 6) GERUNDIOS: cada clave apunta a una tool REAL del registry
# ---------------------------------------------------------------------------

# nombre de tool -> modulo opt-in que la registra. Los opt-in exponen
# register(tool) y agent/tools.py lo llama SOLO con su flag activo, asi que
# el registro no esta en TOOLS durante los tests: se verifica contra el
# FUENTE del modulo (el literal '@tool("nombre"') sin mutar el registry
# global (llamar register() aqui contaminaria el resto de la suite).
_OPTIN_DE = {
    "web_buscar": "cognia.agent.browser_tool",
    "web_abrir": "cognia.agent.browser_tool",
    "voz_decir": "cognia.agent.voz_tools",
    "voz_escuchar": "cognia.agent.voz_tools",
    "voz_clonar": "cognia.agent.voz_tools",
    "musica_orquestar": "cognia.agent.musica_tools",
    "tresd_generar": "cognia.agent.tresd_tools",
    "vlm_mirar": "cognia.agent.vlm_tools",
    "imagen_generar": "cognia.agent.image_tools",
    "imagen_editar": "cognia.agent.image_tools",
    "imagen_quitar_fondo": "cognia.agent.image_tools",
    "repo_a_prompt": "cognia.agent.repo_reverse_tool",
}

def _declarada_en_fuente(nombre: str, mod: str) -> bool:
    """El modulo opt-in declara '@tool("nombre"' en su fuente?"""
    try:
        spec = importlib.util.find_spec(mod)
        if spec is None or not spec.origin:
            return False
        from pathlib import Path
        fuente = Path(spec.origin).read_text(encoding="utf-8",
                                             errors="replace")
        return f'@tool("{nombre}"' in fuente
    except Exception:
        return False


@pytest.mark.parametrize("nombre", sorted(GERUNDIOS))
def test_gerundio_apunta_a_tool_del_registry(nombre):
    from cognia.agent.tools import TOOLS
    if nombre in TOOLS:
        return
    mod = _OPTIN_DE.get(nombre)
    if mod and _declarada_en_fuente(nombre, mod):
        return
    pytest.fail(
        f"GERUNDIOS['{nombre}'] no existe en agent/tools.py TOOLS ni esta "
        f"declarada en un modulo opt-in documentado — la tool saldria como "
        f"'Trabajando' generico")


def test_gerundios_familias_nuevas():
    assert verbo_de("voz_decir") == "Hablando"
    assert verbo_de("voz_escuchar") == "Escuchando"
    assert verbo_de("voz_clonar") == "Clonando voz"
    assert verbo_de("musica_orquestar") == "Orquestando"
    assert verbo_de("tresd_generar") == "Modelando 3D"
    assert verbo_de("vlm_mirar") == "Mirando"
    assert verbo_de("imagen_generar") == "Dibujando"
    assert verbo_de("imagen_editar") == "Retocando"
    assert verbo_de("imagen_quitar_fondo") == "Recortando"
    assert verbo_de("tarea_estado") == "Revisando la tarea"
    assert verbo_de("bitacora_buscar") == "Consultando bitacora"
    assert verbo_de("delegar_subtarea") == "Delegando"


def test_claves_fantasma_eliminadas():
    # 'listar_archivos'/'buscar_archivos' nunca existieron en el registry:
    # el nombre real es 'listar'/'buscar'
    assert "listar_archivos" not in GERUNDIOS
    assert "buscar_archivos" not in GERUNDIOS
    assert "buscar_en_archivos" not in GERUNDIOS
    assert verbo_de("listar") == "Explorando"
    assert verbo_de("buscar") == "Buscando"
    assert verbo_de("copiar_archivo") == "Copiando"
    assert verbo_de("contar_lineas") == "Contando lineas"


# ---------------------------------------------------------------------------
# Decision 17 (2026-08-17): la RESPUESTA del modelo va en texto normal
# ---------------------------------------------------------------------------
# El streaming de la respuesta era el ultimo 'cyan' hardcodeado del renderer
# (FlujoSuave(style="cyan")). Se veia asi: el bloque de texto MAS GRANDE de la
# pantalla pintado de un acento que ni siquiera obedecia a /tema — con
# alto_contraste salia hex por hex igual que con oscuro.

def test_la_respuesta_streameada_usa_el_token_del_tema():
    from cognia.ux.estilo import ESTILO_RESPUESTA
    con, buf = _consola_rich()
    r = Renderer(console=con)
    r(events.TokenTexto(texto="Hola, esto es lo que contesta el modelo.\n"))
    assert r._flujo is not None, "no se abrio el flujo de la respuesta"
    assert r._flujo._style == ESTILO_RESPUESTA, (
        "el stream de la respuesta no pasa por el token del tema")
    r._cerrar_flujo()
    assert "Hola, esto es lo que contesta" in buf.getvalue()


def test_el_flujo_no_revienta_con_una_consola_sin_el_tema():
    """estilo_seguro(): una Console pelada no conoce los tokens del CLI. Antes
    de resolverlos con guarda, un embebedor o un test se comia un MissingStyle
    por un ADORNO — y el turno entero se perdia."""
    from rich.console import Console
    from cognia.ux.estilo import FlujoSuave, respuesta
    buf = io.StringIO()
    pelada = Console(file=buf, width=80, force_terminal=False)
    f = FlujoSuave(console=pelada)
    f.escribir("texto sin tema ")
    f.cerrar()
    respuesta("y una respuesta entera", console=pelada)
    salida = buf.getvalue()
    assert "texto sin tema" in salida and "y una respuesta entera" in salida
