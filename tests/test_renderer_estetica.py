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


def test_pensando_update_conserva_pensar_y_segundos():
    con = _ConsolaFalsa()
    r = Renderer(console=con)
    r(events.RazonamientoTick(chars=10, fragmento="a"))
    r(events.RazonamientoTick(chars=20, fragmento="b"))
    st = con.statuses[0]
    assert st.updates, "el segundo tick debe actualizar el status"
    assert "[pensar]" in st.updates[-1]
    assert "s)" in st.updates[-1]           # el (Ns) de hoy sigue

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
