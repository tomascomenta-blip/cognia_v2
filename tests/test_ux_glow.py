# -*- coding: utf-8 -*-
"""Tests del MOTOR de glow/barrido (cognia/ux/glow, paso P3 del sistema de
estilos por elemento).

Todo determinista: el reloj se inyecta (Reloj(ahora=...) / RELOJ.fijar) o se
pasa `t=` explicito; las capacidades se fuerzan con forzar_capacidades para
no depender de la terminal de pytest. Los niveles de color 256/16/none se
prueban en SUBPROCESOS: rich cachea el ANSI dentro de cada Style por proceso
(medido en la investigacion), asi que un mismo proceso no puede pintar dos
niveles.

Regresion: sin glow.py no existe el modulo; sin la memo por cuadro
CALCULOS sube en cada llamada; sin el Text-subclass de LineaViva el status
cambia de layout (Table.grid) y deja de ser byte-identico."""
import io
import os
import re
import subprocess
import sys
import threading
import time
import types

import pytest
from rich.console import Console
from rich.text import Text

from cognia.ux import glow
from cognia.ux.glow import Caps, EstiloGlow, Reloj

TRUECOLOR = Caps("truecolor", True)
PY = sys.executable
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    """Cada test arranca con memo vacia, capacidades forzadas a truecolor
    animable y sin pulso vivo; al salir se deja todo como estaba."""
    glow.vaciar_memo()
    glow.forzar_capacidades(TRUECOLOR)
    monkeypatch.setattr(glow, "RESOLVER", None)
    monkeypatch.setattr(glow, "VERSION", None)
    monkeypatch.setattr(glow, "VARIANTE", lambda: "oscuro")
    monkeypatch.setattr(glow, "LEER_CONFIG", lambda: {})
    monkeypatch.setattr(glow, "RELOJ", Reloj(ahora=lambda: 0.0))
    yield
    glow.parar_pulso()
    glow.forzar_capacidades(None)
    glow.vaciar_memo()


def _estilo(**kw):
    base = dict(color="#7ee62a", anim_activa=True, anim_velocidad=2, anim_ancho=5)
    base.update(kw)
    return EstiloGlow(**base)


def _colores(texto: Text) -> list:
    """[(hex, bold)] por CARACTER de un Text (los spans vecinos iguales estan
    fundidos; aqui se expanden para comparar posicion a posicion)."""
    out = [None] * len(texto.plain)
    for sp in texto.spans:
        st = sp.style
        hexs = st.color.triplet.hex if (st.color is not None and st.color.triplet) else None
        for i in range(sp.start, sp.end):
            out[i] = (hexs, bool(st.bold))
    return out


def _k(hexs: str, base="#7ee62a") -> float:
    """Cuanto se aleja un hex del base (0 = base): el 'brillo' del barrido."""
    b = int(base[1:], 16)
    c = int(hexs[1:], 16)
    return sum(abs(((c >> s) & 255) - ((b >> s) & 255)) for s in (16, 8, 0))


def _pico(texto: Text) -> int:
    ks = [_k(h) for h, _ in _colores(texto)]
    return max(range(len(ks)), key=lambda i: ks[i])


# ---------------------------------------------------------------------------
# frames deterministas
# ---------------------------------------------------------------------------

def test_barrido_t0_ningun_caracter_brilla_y_a_medio_periodo_el_pico_esta_en_el_medio():
    e = _estilo()
    txt = "Maullando ideas"
    f0 = glow.estilizar(e, txt, t=0.0)
    assert all(h == "#7ee62a" for h, _ in _colores(f0)), "a t=0 la ventana aun no entro"
    assert all(b for _, b in _colores(f0)), "el barrido pone negrita mientras anima"
    medio = glow.estilizar(e, txt, t=e.periodo_s / 2)
    assert _pico(medio) == len(txt) // 2
    assert _k(_colores(medio)[len(txt) // 2][0]) > 0


def test_frames_son_byte_identicos_entre_llamadas_y_procesos():
    # el frame a t fijo es una funcion pura del estilo: dos procesos lo
    # pintan igual (el test corre el mismo calculo en un subproceso)
    e = _estilo()
    aqui = _colores(glow.estilizar(e, "cognia", t=0.7))
    codigo = (
        "from cognia.ux import glow\n"
        "glow.forzar_capacidades(glow.Caps('truecolor', True))\n"
        "e = glow.EstiloGlow(color='#7ee62a', anim_activa=True, anim_velocidad=2, anim_ancho=5)\n"
        "t = glow.estilizar(e, 'cognia', t=0.7)\n"
        "print([(s.style.color.triplet.hex, bool(s.style.bold), s.start, s.end) for s in t.spans])\n")
    out = subprocess.run([PY, "-c", codigo], capture_output=True, text=True, cwd=RAIZ,
                         env=dict(os.environ, PYTHONUTF8="1", PYTHONPATH=RAIZ), timeout=60)
    assert out.returncode == 0, out.stderr
    alla = eval(out.stdout.strip())
    exp = [None] * 6
    for h, b, a, z in alla:
        for i in range(a, z):
            exp[i] = (h, b)
    assert aqui == exp


def test_barrido_recorre_todo_el_texto_de_izquierda_a_derecha():
    e = _estilo()
    txt = "x" * 30
    picos = []
    for paso in range(1, 20):
        t = e.periodo_s * paso / 20
        fr = glow.estilizar(e, txt, t=t)
        if any(_k(h) > 0 for h, _ in _colores(fr)):
            picos.append(_pico(fr))
    assert picos == sorted(picos), picos
    assert picos[0] <= 2 and picos[-1] >= len(txt) - 3, "la ventana entra por la izquierda y sale por la derecha"


def test_direccion_izquierda_es_el_espejo():
    d = _estilo(anim_direccion="derecha")
    i = _estilo(anim_direccion="izquierda")
    txt = "abcdefghijklmnopqrstuvwxyz"
    for t in (0.5, 0.9, 1.3):
        cd = _colores(glow.estilizar(d, txt, t=t))
        ci = _colores(glow.estilizar(i, txt, t=t))
        assert cd == ci[::-1]


def test_ida_vuelta_va_y_vuelve():
    e = _estilo(anim_direccion="ida_vuelta")
    txt = "x" * 40
    picos = []
    for paso in range(0, 40):
        t = e.ciclo_s * paso / 40
        fr = glow.estilizar(e, txt, t=t)
        if any(_k(h) > 0 for h, _ in _colores(fr)):
            picos.append(_pico(fr))
    cima = picos.index(max(picos))
    assert picos[:cima + 1] == sorted(picos[:cima + 1])
    assert picos[cima:] == sorted(picos[cima:], reverse=True)
    assert picos[0] <= 2 and picos[-1] <= 2 and max(picos) >= len(txt) - 3


def test_repetir_1_devuelve_frame_estatico_tras_un_periodo():
    e = _estilo(anim_repetir=1, glow_intensidad=1)
    txt = "cognia"
    vivo = glow.estilizar(e, txt, t=e.periodo_s / 2)
    fijo = glow.estilizar(e, txt, t=e.periodo_s + 0.01)
    estatico = glow.frame_estatico(e, txt)
    assert _colores(fijo) == _colores(estatico)
    assert _colores(vivo) != _colores(estatico)
    # solo_al_llegar = repetir 1 implicito
    s = _estilo(anim_solo_al_llegar=True)
    assert _colores(glow.estilizar(s, txt, t=9.0)) == _colores(glow.frame_estatico(s, txt))


def test_cada_s_pausa_con_frame_estatico_entre_barridos():
    e = _estilo(anim_cada_s=1.0)
    txt = "cognia"
    est = _colores(glow.frame_estatico(e, txt))
    assert _colores(glow.estilizar(e, txt, t=e.periodo_s + 0.5)) == est      # en la pausa
    assert _colores(glow.estilizar(e, txt, t=e.periodo_s + 1.0 + e.periodo_s / 2)) != est


def test_pulso_es_uniforme_y_arranca_en_el_color_base():
    e = _estilo(anim_tipo="pulso")
    txt = "cognia"
    c0 = _colores(glow.estilizar(e, txt, t=0.0))
    assert len({h for h, _ in c0}) == 1 and c0[0][0] == "#7ee62a"
    cm = _colores(glow.estilizar(e, txt, t=e.periodo_s / 2))
    assert len({h for h, _ in cm}) == 1 and _k(cm[0][0]) > 0


def test_glow_estatico_campana_y_negrita_desde_intensidad_2():
    txt = "cognia"
    i1 = glow.frame_estatico(EstiloGlow(color="#7ee62a", glow_intensidad=1), txt)
    i2 = glow.frame_estatico(EstiloGlow(color="#7ee62a", glow_intensidad=2), txt)
    c1, c2 = _colores(i1), _colores(i2)
    assert not any(b for _, b in c1) and all(b for _, b in c2)
    assert _k(c1[0][0]) < _k(c1[2][0]) and _k(c1[-1][0]) < _k(c1[3][0])   # pico en el centro
    assert _k(c2[2][0]) > _k(c1[2][0])                                      # mas intensidad, mas mezcla


def test_glow_color_derivado_va_hacia_negro_en_claro():
    e = EstiloGlow(color="#1e5900", glow_intensidad=3)
    assert sum(glow.color_glow(e, "oscuro")) > sum(glow.color_glow(e, "claro"))


def test_curvas_de_intensidad_distintas():
    txt = "x" * 20
    t = 1.0
    c = _colores(glow.estilizar(_estilo(anim_curva="campana"), txt, t=t))
    tr = _colores(glow.estilizar(_estilo(anim_curva="triangulo"), txt, t=t))
    m = _colores(glow.estilizar(_estilo(anim_curva="meseta"), txt, t=t))
    assert c != tr and c != m


def test_config_invalida_es_ruidosa():
    with pytest.raises(ValueError, match="glow_intensidad"):
        EstiloGlow(glow_intensidad=7)
    with pytest.raises(ValueError, match="anim_direccion"):
        EstiloGlow(anim_direccion="diagonal")
    with pytest.raises(ValueError, match="no es un color"):
        EstiloGlow(color="verde-lima")
    with pytest.raises(ValueError, match="anim_velocidad"):
        EstiloGlow(anim_velocidad=9)


# ---------------------------------------------------------------------------
# byte-identico por defecto y degradacion
# ---------------------------------------------------------------------------

def test_sin_glow_ni_animacion_es_un_solo_span_con_el_token():
    e = EstiloGlow(token="spinner")
    t = glow.frame_estatico(e, "· pensando…")
    assert t.plain == "· pensando…" and t.spans[0].style == "spinner" and len(t.spans) == 1
    assert glow.estilo_rich(e) == "spinner"
    assert glow.estilizar_pt(e, "hola") == [("class:spinner", "hola")]


def test_sin_tty_frame_estatico_sin_barrido():
    glow.forzar_capacidades(Caps("truecolor", False, "sin tty (stdout no es una terminal)"))
    e = _estilo(glow_intensidad=1)
    vivo = glow.estilizar(e, "cognia", t=1.0)
    assert _colores(vivo) == _colores(glow.frame_estatico(e, "cognia"))
    salida = io.StringIO()
    Console(file=salida, force_terminal=True, color_system="truecolor",
            legacy_windows=False, width=80).print(vivo)
    crudo = salida.getvalue()
    assert "\x1b[A" not in crudo and crudo.count("\n") == 1
    # el glow fijo pinta la campana UNA vez (nada repetido por frame)
    assert 1 <= len(re.findall(r"38;2;", crudo)) <= len("cognia")


def test_no_color_sin_color_y_glow_en_negrita():
    glow.forzar_capacidades(Caps("none", False, "NO_COLOR"))
    e = _estilo(glow_intensidad=2)
    t = glow.estilizar(e, "cognia", t=1.0)
    assert all(h is None and b for h, b in _colores(t))
    assert glow.estilizar_pt(e, "cognia", t=1.0) == [("bold", "cognia")]


def test_clase_pt_y_estilo_rich_plano():
    e = EstiloGlow(color="#7ee62a", negrita=True)
    assert glow.clase_pt(e) == "fg:#7ee62a bold"
    st = glow.estilo_rich(e)
    assert st.color.triplet.hex == "#7ee62a" and st.bold
    assert glow.clase_pt(EstiloGlow(color="bright_cyan", italica=True)) == "fg:ansibrightcyan italic"
    assert glow.clase_pt(EstiloGlow(token="spinner")) == ""


def test_gradiente_lineas_sin_override_es_el_gradiente_de_la_paleta():
    from cognia.ux import paleta
    lineas = ["aaaa", "bbbb", "cccc"]
    out = glow.gradiente_lineas(EstiloGlow(), lineas, variante="oscuro")
    tonos = paleta.gradiente_banner(3, "oscuro")
    for texto, tono, linea in zip(out, tonos, lineas):
        assert texto.plain == linea and len(texto.spans) == 1
        assert texto.spans[0].style.color.triplet.hex == tono
    # con gradiente propio: extremos exactos
    out2 = glow.gradiente_lineas(EstiloGlow(gradiente=("#000000", "#ffffff")), lineas)
    assert out2[0].spans[0].style.color.triplet.hex == "#000000"
    assert out2[-1].spans[0].style.color.triplet.hex == "#ffffff"


def test_ancho_recorta_el_texto():
    assert glow.frame_estatico(EstiloGlow(color="#7ee62a"), "0123456789", ancho=4).plain == "0123"


# ---------------------------------------------------------------------------
# capacidades(): orden D8
# ---------------------------------------------------------------------------

def _caps_reales(monkeypatch, tty=True, **env):
    glow.forzar_capacidades(None)
    for k in ("COGNIA_ANIMACION", "NO_COLOR", "COGNIA_REMOTO", "SSH_TTY", "SSH_CONNECTION"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(glow, "_es_tty", lambda: tty)
    monkeypatch.setattr(glow, "_deteccion_rich", lambda: ("truecolor", False))
    return glow.capacidades()


def test_capacidades_apaga_por_cada_variable_con_motivo(monkeypatch):
    assert _caps_reales(monkeypatch).animar
    for env, esperado in (({"COGNIA_ANIMACION": "0"}, "COGNIA_ANIMACION=0"),
                          ({"NO_COLOR": "1"}, "NO_COLOR"),
                          ({"COGNIA_REMOTO": "1"}, "COGNIA_REMOTO=1"),
                          ({"SSH_TTY": "/dev/pts/1"}, "SSH")):
        c = _caps_reales(monkeypatch, **env)
        assert not c.animar and esperado in c.motivo, (env, c)
    c = _caps_reales(monkeypatch, tty=False)
    assert not c.animar and "tty" in c.motivo
    assert _caps_reales(monkeypatch, NO_COLOR="1").nivel == "none"


def test_capacidades_config_off_y_env_gana(monkeypatch):
    monkeypatch.setattr(glow, "LEER_CONFIG", lambda: {"estilo_animacion": "off"})
    c = _caps_reales(monkeypatch)
    assert not c.animar and "estilo_animacion" in c.motivo
    # COGNIA_ANIMACION=1 fuerza sobre config y sobre 'sin tty'
    assert _caps_reales(monkeypatch, tty=False, COGNIA_ANIMACION="1").animar
    # ...pero no sobre NO_COLOR
    assert not _caps_reales(monkeypatch, COGNIA_ANIMACION="1", NO_COLOR="1").animar


def test_capacidades_legacy_windows(monkeypatch):
    glow.forzar_capacidades(None)
    for k in ("COGNIA_ANIMACION", "NO_COLOR", "WT_SESSION", "COLORTERM", "TERM_PROGRAM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(glow, "_es_tty", lambda: True)
    monkeypatch.setattr(glow, "_deteccion_rich", lambda: ("windows", True))
    c = glow.capacidades()
    assert not c.animar and "legacy" in c.motivo and c.nivel == "16"


# ---------------------------------------------------------------------------
# memo por cuadro y degradacion ruidosa del resolver
# ---------------------------------------------------------------------------

def test_memo_diez_llamadas_del_mismo_cuadro_un_calculo():
    e = _estilo()
    antes = glow.CALCULOS
    for _ in range(10):
        glow.estilizar(e, "cognia", cuadro=7)
        glow.estilizar_pt(e, "cognia", cuadro=7)
    assert glow.CALCULOS - antes == 2          # uno rich + uno PT
    glow.estilizar(e, "cognia", cuadro=8)
    assert glow.CALCULOS - antes == 3


def test_memo_caduca_con_la_version_del_registro(monkeypatch):
    e = _estilo()
    v = [1]
    monkeypatch.setattr(glow, "VERSION", lambda: v[0])
    antes = glow.CALCULOS
    glow.estilizar(e, "cognia", cuadro=3)
    glow.estilizar(e, "cognia", cuadro=3)
    v[0] = 2
    glow.estilizar(e, "cognia", cuadro=3)
    assert glow.CALCULOS - antes == 2


def test_estilizar_devuelve_copia_y_no_ensucia_la_memo():
    e = _estilo()
    a = glow.estilizar(e, "cognia", cuadro=1)
    a.append("!!!")
    assert glow.estilizar(e, "cognia", cuadro=1).plain == "cognia"


def test_id_sin_resolver_avisa_por_stderr_y_pinta_sin_estilo(capsys, monkeypatch):
    # Sin cli cargado el aviso va a stderr; si otro test dejo cognia.cli en
    # sys.modules (test_ux_aspecto lo importa), iria a _aviso_degradado y el
    # test dependeria del ORDEN de la bateria.
    monkeypatch.delitem(sys.modules, "cognia.cli", raising=False)
    monkeypatch.setattr(glow, "RESOLVER", None)
    glow._AVISOS_STDERR.clear()
    t = glow.estilizar("prompt.etiqueta", "cognia", t=1.0)
    assert t.plain == "cognia" and not t.spans
    err = capsys.readouterr().err
    assert "degradado" in err and "glow" in err and "RESOLVER" in err


def test_id_con_resolver_inyectado_y_aviso_por_el_cli(monkeypatch):
    avisos = []
    falso_cli = types.SimpleNamespace(
        _aviso_degradado=lambda via, det="": avisos.append((via, det)),
        _load_config=lambda: {}, _variante_actual=lambda: "oscuro")
    monkeypatch.setitem(sys.modules, "cognia.cli", falso_cli)
    monkeypatch.setattr(glow, "RESOLVER", lambda id, variante, estado: EstiloGlow(color="#ff0000"))
    t = glow.frame_estatico("x.y", "hola")
    assert t.spans[0].style.color.triplet.hex == "#ff0000"

    def roto(id, variante, estado):
        raise KeyError(id)
    monkeypatch.setattr(glow, "RESOLVER", roto)
    glow.vaciar_memo()
    t = glow.frame_estatico("x.y", "hola")
    assert not t.spans
    assert avisos and avisos[-1][0] == "glow" and "x.y" in avisos[-1][1]


# ---------------------------------------------------------------------------
# LineaViva: dentro del status, sin Live propia
# ---------------------------------------------------------------------------

def _console_grabando():
    salida = io.StringIO()
    return Console(file=salida, force_terminal=True, color_system="truecolor",
                   legacy_windows=False, width=80, theme=_tema()), salida


def _tema():
    from rich.theme import Theme
    from cognia.ux import paleta
    return Theme(paleta.tema_cli("oscuro"))


def test_linea_viva_sin_animar_es_byte_identica_al_markup_de_hoy():
    lv = glow.LineaViva("Maullando ideas… (3s · ctrl+c corta)", EstiloGlow(token="spinner"),
                        animar=False)
    hoy = Text.from_markup("[spinner]· Maullando ideas… (3s · ctrl+c corta)[/spinner]")
    c, s1 = _console_grabando()
    c.print(lv)
    c2, s2 = _console_grabando()
    c2.print(hoy)
    assert s1.getvalue() == s2.getvalue()
    # y dentro del status de rich (Spinner.render hace Text.assemble)
    from rich.spinner import Spinner
    a = Spinner("dots", lv).render(0.0)
    b = Spinner("dots", hoy).render(0.0)
    assert isinstance(a, Text) and a.plain == b.plain and a.spans == b.spans


def test_linea_viva_anima_dentro_de_un_status_sin_abrir_otra_live(monkeypatch):
    from rich import live as rich_live
    reloj = Reloj(ahora=lambda: 0.0)
    e = _estilo()
    lv = glow.LineaViva("Maullando ideas", e, reloj=reloj, fps=10)
    assert lv.animar
    c, salida = _console_grabando()
    abiertas = []
    original = rich_live.Live.start

    def _start(self, *a, **k):
        abiertas.append(self)
        return original(self, *a, **k)
    monkeypatch.setattr(rich_live.Live, "start", _start)
    # el status del renderer es la UNICA Live; LineaViva no abre otra
    with c.status(lv, spinner="dots", refresh_per_second=lv.fps) as st:
        f1 = lv.plain
        reloj.ahora = lambda: e.periodo_s / 2
        st.update(lv)                         # lo que hace el ticker del renderer
        lv.set("Maullando ideas")
        _ = len(lv)
    assert len(abiertas) == 1 and lv.frames >= 2
    assert lv.plain == "· Maullando ideas"
    # a medio periodo el pico esta en el medio de '· Maullando ideas'
    assert _pico(Text(lv.plain, spans=list(lv.spans))) == len(lv.plain) // 2


def test_linea_viva_set_cambia_el_texto_y_frame_final_es_estatico():
    reloj = Reloj(ahora=lambda: 0.0)
    e = _estilo(glow_intensidad=1)
    lv = glow.LineaViva("uno", e, reloj=reloj)
    lv.set("dos (4s)")
    assert lv.plain == "· dos (4s)"
    fin = lv.frame_final()
    assert _colores(fin) == _colores(glow.frame_estatico(e, "· dos (4s)"))


def test_linea_viva_sin_capacidad_de_animar_cae_al_markup():
    glow.forzar_capacidades(Caps("truecolor", False, "sin tty"))
    lv = glow.LineaViva("x", _estilo(), token="pensar")
    assert not lv.animar and lv.spans == [Text.from_markup("[pensar]· x[/pensar]").spans[0]]


# ---------------------------------------------------------------------------
# BannerVivo
# ---------------------------------------------------------------------------

def test_banner_vivo_frame_y_sin_altura_no_abre_live(monkeypatch):
    from rich import live as rich_live
    lineas = ["⣠⣤⣤⣄ COGNIA", "⣾⣿⣿⣷ v1", "⠻⣿⣿⠟ ..."]
    e = _estilo(anim_solo_al_llegar=True, glow_intensidad=1)
    reloj = Reloj(ahora=lambda: 0.0)
    bv = glow.BannerVivo(lineas, e, reloj=reloj, fps=10)
    fr = bv.frame(t=e.periodo_s / 2)
    assert fr.plain == "\n".join(lineas)
    assert bv.duracion_s() == e.periodo_s
    abiertas = []
    monkeypatch.setattr(rich_live.Live, "start", lambda self, *a, **k: abiertas.append(self))
    salida = io.StringIO()
    c = Console(file=salida, force_terminal=True, color_system="truecolor", legacy_windows=False,
                width=80, height=3)
    assert bv.mostrar(c) is False and not abiertas       # 3 filas < 3 lineas + 2 (E7)
    assert "\x1b[A" not in salida.getvalue() and salida.getvalue().count("\n") == 3
    glow.forzar_capacidades(Caps("truecolor", False, "sin tty"))
    c2 = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor",
                 legacy_windows=False, width=80, height=40)
    assert bv.mostrar(c2) is False and not abiertas


def test_banner_vivo_con_live_termina_en_frame_estatico():
    lineas = ["COGNIA", "cognia"]
    e = _estilo(anim_velocidad=5, anim_solo_al_llegar=True, glow_intensidad=1)
    bv = glow.BannerVivo(lineas, e, fps=20)
    salida = io.StringIO()
    c = Console(file=salida, force_terminal=True, color_system="truecolor", legacy_windows=False,
                width=80, height=40)
    t0 = time.monotonic()
    assert bv.mostrar(c) is True
    assert time.monotonic() - t0 < e.periodo_s + 1.5
    assert bv.frames >= 2
    crudo = salida.getvalue()
    # el ultimo frame escrito es el estatico (glow fijo, sin ventana)
    estatico = io.StringIO()
    Console(file=estatico, force_terminal=True, color_system="truecolor", legacy_windows=False,
            width=80).print(bv.frame_final())
    crudo = crudo.replace("[?25h", "").replace("[?25l", "").rstrip()
    assert crudo.endswith(estatico.getvalue().rstrip()[-40:])


# ---------------------------------------------------------------------------
# pulso_prompt: un hilo, finito, sin refresh_interval
# ---------------------------------------------------------------------------

class _App:
    def __init__(self):
        self.n = 0
        self.ultimo_animando = None

    def invalidate(self):
        self.n += 1
        self.ultimo_animando = glow.animando()


def test_pulso_prompt_termina_solo_y_no_deja_hilos(monkeypatch):
    monkeypatch.setattr(glow, "RELOJ", Reloj())       # reloj real: el pulso dura de verdad
    app = _App()
    antes = {th.name for th in threading.enumerate()}
    assert glow.pulso_prompt(app, segundos=0.3, fps=20) is True
    assert glow.animando()
    assert glow.pulso_prompt(app, segundos=0.3, fps=20) is False       # UNICO
    hilo = glow._PULSO["hilo"]
    hilo.join(timeout=3.0)
    assert not hilo.is_alive()
    assert not glow.animando()
    assert 3 <= app.n <= 12
    assert app.ultimo_animando is False, "el ultimo invalidate ve animando()=False: frame estatico"
    vivos = {th.name for th in threading.enumerate()} - antes
    assert not [n for n in vivos if "pulso" in n]


def test_pulso_prompt_acotado_y_sin_capacidad_no_arranca(monkeypatch):
    glow.forzar_capacidades(Caps("truecolor", False, "sin tty"))
    app = _App()
    assert glow.pulso_prompt(app, segundos=1.0) is False and app.n == 0 and not glow.animando()
    assert glow.pulso_prompt(None, segundos=1.0) is False
    e = _estilo(anim_repetir=0)
    assert e.duracion_s() == glow.PULSO_MAX_S
    assert glow.duracion_pulso([e, _estilo(anim_repetir=1)]) == glow.PULSO_MAX_S
    assert glow.duracion_pulso([EstiloGlow()]) == 0.0


def test_estilizar_pt_sin_t_usa_el_pulso_o_el_estatico(monkeypatch):
    e = _estilo(glow_intensidad=1)
    est = glow.frame_estatico_pt(e, "cognia")
    assert glow.estilizar_pt(e, "cognia") == est            # sin pulso: estatico
    monkeypatch.setitem(glow._PULSO, "activo", True)
    monkeypatch.setitem(glow._PULSO, "t0", 0.0)
    glow.RELOJ.ahora = lambda: e.periodo_s / 2
    vivo = glow.estilizar_pt(e, "cognia")
    assert vivo != est and all(f[0].startswith("fg:#") and "bold" in f[0] for f in vivo)


# ---------------------------------------------------------------------------
# niveles 256 / 16 / none en SUBPROCESOS (cache _ansi de rich por proceso)
# ---------------------------------------------------------------------------

_CODIGO_NIVEL = """
import io, sys
from rich.console import Console
from cognia.ux import glow
nivel = sys.argv[1]
glow.forzar_capacidades(glow.Caps(nivel, True))
e = glow.EstiloGlow(color='#7ee62a', anim_activa=True, anim_velocidad=2, anim_ancho=5, glow_intensidad=1)
cs = {'truecolor': 'truecolor', '256': '256', '16': 'standard', 'none': None}[nivel]
buf = io.StringIO()
c = Console(file=buf, force_terminal=True, color_system=cs, legacy_windows=False, width=200)
c.print(glow.estilizar(e, 'Maullando ideas', t=1.0))
sys.stdout.write(repr(buf.getvalue()))
"""


def _nivel(nivel: str) -> str:
    out = subprocess.run([PY, "-c", _CODIGO_NIVEL, nivel], capture_output=True, text=True,
                         cwd=RAIZ, env=dict(os.environ, PYTHONUTF8="1", PYTHONPATH=RAIZ),
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return eval(out.stdout)


def test_nivel_256_degrada_a_38_5_y_mantiene_el_barrido():
    crudo = _nivel("256")
    assert "38;2;" not in crudo and len(set(re.findall(r"38;5;\d+", crudo))) >= 2


def test_nivel_16_tres_escalones_sobre_el_nombre_base():
    crudo = _nivel("16")
    assert "38;2;" not in crudo and "38;5;" not in crudo
    assert "\x1b[1;" in crudo or ";1m" in crudo         # bold en la ventana
    assert "\x1b[2;" in crudo or ";2m" in crudo         # dim fuera
    assert re.search(r"\x1b\[[0-9;]*3[0-7]m", crudo)    # color de 16


def test_nivel_none_solo_negrita():
    crudo = _nivel("none")
    assert "38;" not in crudo and "[3" not in crudo
    assert crudo.strip() and "Maullando ideas" in crudo


def test_los_nombres_ansi_de_la_tabla_existen_en_prompt_toolkit():
    """P5: 'white' es 'ansigray' y 'bright_white' es 'ansiwhite' en PT;
    'ansibrightwhite' no existe (Wrong color format). Cazado con /tema
    alto_contraste, cuyo 'mod' es 'bold bright_white'."""
    from prompt_toolkit.styles.base import ANSI_COLOR_NAMES
    from rich.style import Style
    assert set(glow._PT_ANSI.values()) <= set(ANSI_COLOR_NAMES)
    assert glow._pt_de_style(Style.parse("bold bright_white"), "oscuro") == "fg:ansiwhite bold"
    assert glow._pt_de_style(Style.parse("white"), "oscuro") == "fg:ansigray"
