# -*- coding: utf-8 -*-
"""EditorModelo (cognia/ux/editor_aspecto.py), el modelo PURO del editor
/estilo: se recorre entero por teclas, sin tty ni prompt_toolkit.

Lo que fija (seccion 6 del diseno, fila test_ux_editor_aspecto):
- un recorrido por teclas cambia prompt.etiqueta.texto a 'jarvis' y guarda
  por el callback inyectado; undo/redo (tope 100); filtro '/'; enum ciclico;
  color invalido rechazado CON mensaje; la preview cambia cuando cambia la
  propiedad; Esc con cambios exige confirmacion; NADA escribe al disco sin
  Ctrl-S (RUTA_ESTILO apuntada a tmp_path); presets en memoria (Ctrl-P) y
  preview de pantalla con Esc que revierte (Ctrl-L); los avisos ruidosos de
  aspecto (contraste, glifo no codificable) se ven, nunca se tragan.
"""
from __future__ import annotations

import dataclasses
import io
import json
import sys

import pytest

pytest.importorskip("rich")

from cognia.ux import aspecto as A  # noqa: E402
from cognia.ux import glow as G  # noqa: E402
from cognia.ux import editor_aspecto as E  # noqa: E402
from cognia.ux.editor_aspecto import EditorModelo, texto_plano  # noqa: E402


@pytest.fixture(autouse=True)
def _limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DIR_COGNIA", tmp_path)
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    monkeypatch.setattr(A, "DIR_PRESETS", tmp_path / "estilos")
    for k in ("COGNIA_REMOTO", "COGNIA_THEME", "COGNIA_ASCII", "COGNIA_ANIMACION", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    G.vaciar_memo()
    yield
    A.reset()


def _abrir(**kw) -> EditorModelo:
    return EditorModelo(ancho=60, **kw)


def _fila_prop(m: EditorModelo, ruta: str) -> int:
    for i, p in enumerate(m.props()):
        if p.ruta == ruta:
            return i
    raise AssertionError(f"{m.elemento_id} no tiene la fila {ruta}: {[p.ruta for p in m.props()]}")


def _ir_a_prop(m: EditorModelo, id: str, ruta: str) -> None:
    m.ir_a(id)
    m.panel = "propiedades"
    m.cursor_props = _fila_prop(m, ruta)


# ---------------------------------------------------------------------------
# El recorrido de la puerta: por teclas, sin atajos
# ---------------------------------------------------------------------------

def test_recorrido_por_teclas_cambia_la_etiqueta_y_guarda_por_callback():
    llamadas = []
    m = _abrir(guardar=lambda: llamadas.append(A.documento()) or "ruta-falsa")
    # banner (cabecera + 4) -> prompt (cabecera) -> marco -> etiqueta
    for _ in range(7):
        m.tecla("down")
    assert m.elemento_id == "prompt.etiqueta"
    m.tecla("enter")
    assert m.panel == "propiedades" and m.prop_actual().ruta == "texto"
    m.tecla("enter")
    assert m.modo == "texto" and m.buffer == "cognia"
    for _ in range(6):
        m.tecla("backspace")
    m.escribir("jarvis")
    m.tecla("enter")
    assert m.modo == "normal"
    assert A.texto("prompt.etiqueta") == "jarvis"
    assert m.mensaje() == "prompt.etiqueta.texto = jarvis"
    assert m.sucio
    assert not A.RUTA_ESTILO.exists()
    m.tecla("c-s")
    assert llamadas == [{"version": 1, "elementos": {"prompt.etiqueta": {"texto": "jarvis"}}}]
    assert not m.sucio
    assert "guardado" in m.mensaje() and "ruta-falsa" in m.mensaje()
    assert not A.RUTA_ESTILO.exists(), "el callback reemplaza a aspecto.guardar: nada en disco"


def test_guardar_por_defecto_escribe_estilo_json_y_llama_aplicar():
    aplicado = []
    m = _abrir(aplicar=lambda: aplicado.append(True))
    _ir_a_prop(m, "prompt.etiqueta", "texto")
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("gato")
    m.tecla("enter")
    assert not A.RUTA_ESTILO.exists()
    m.tecla("c-s")
    doc = json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))
    assert doc["elementos"] == {"prompt.etiqueta": {"texto": "gato"}}
    assert aplicado == [True]


def test_nada_escribe_al_disco_sin_ctrl_s(tmp_path):
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")
    _ir_a_prop(m, "prompt.marco", "posicion")
    m.tecla("enter")
    m.tecla("r")                      # reset del elemento
    m.tecla("c-p")                    # preset en memoria
    idx = [n for n, *_ in m._presets].index("neon")
    for _ in range(idx):
        m.tecla("down")
    m.tecla("enter")
    assert A.tiene_override("banner.arte")
    m.tecla("c-l")                    # preview de pantalla
    m.tecla("down")
    m.tecla("esc")
    m.tecla("c-z")
    m.tecla("R")
    m.tecla("s")
    assert not A.RUTA_ESTILO.exists()
    assert not (tmp_path / "estilos").exists()
    assert list(tmp_path.iterdir()) == []
    m.tecla("c-s")
    assert A.RUTA_ESTILO.exists()


# ---------------------------------------------------------------------------
# Undo / redo
# ---------------------------------------------------------------------------

def test_undo_redo_recorren_los_cambios_confirmados():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")                  # negrita -> False
    assert A.estilo_de("prompt.etiqueta").negrita is False
    _ir_a_prop(m, "prompt.etiqueta", "italica")
    m.tecla("space")                  # italica -> True
    assert A.estilo_de("prompt.etiqueta").italica is True
    m.tecla("c-z")
    assert A.estilo_de("prompt.etiqueta").italica is None
    assert A.estilo_de("prompt.etiqueta").negrita is False
    m.tecla("c-z")
    assert A.estilo_de("prompt.etiqueta").negrita is True
    m.tecla("c-z")
    assert m.mensaje() == "nada que deshacer"
    m.tecla("c-y")
    assert A.estilo_de("prompt.etiqueta").negrita is False
    m.tecla("c-y")
    assert A.estilo_de("prompt.etiqueta").italica is True
    m.tecla("c-y")
    assert m.mensaje() == "nada que rehacer"


def test_undo_tiene_tope_de_100_pasos():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    for _ in range(105):
        m.tecla("space")
    assert len(m.pila_undo) == E.MAX_UNDO == 100
    for _ in range(100):
        m.tecla("c-z")
    assert m.pila_undo == []
    # 105 alternancias -> False; 100 deshechas -> el estado tras 5 (False)
    assert A.estilo_de("prompt.etiqueta").negrita is False


def test_un_cambio_nuevo_vacia_la_pila_de_rehacer():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")
    m.tecla("c-z")
    assert m.pila_redo
    m.tecla("space")
    assert m.pila_redo == []


# ---------------------------------------------------------------------------
# Navegacion, filtro, grupos
# ---------------------------------------------------------------------------

def test_filtro_reduce_la_lista_y_esc_la_limpia():
    m = _abrir()
    m.tecla("/")
    m.escribir("etiq")
    filas = m.filas_elementos()
    assert [t.strip("> ").split()[0] for t, _, _ in filas] == ["etiqueta"]
    assert m.elemento_id == "prompt.etiqueta"
    m.tecla("enter")
    assert m.modo == "normal" and m.filtro == "etiq"
    m.tecla("/")
    m.tecla("esc")
    assert m.filtro == "" and len(m.filas_elementos()) > 50


def test_filtro_por_nombre_humano_y_sin_coincidencias():
    m = _abrir()
    m.tecla("/")
    m.escribir("gato braille")
    assert m.elemento_id == "banner.arte"
    m.tecla("delete")
    m.escribir("zzzz")
    filas = m.filas_elementos()
    assert len(filas) == 1 and "nada coincide" in filas[0][0]
    assert m.elemento_id is None
    assert m.filas_propiedades() == []
    assert m.preview().plain == ""


def test_enter_en_un_grupo_lo_pliega_y_despliega():
    m = _abrir()
    assert m.filas_elementos()[0][0] == "▾ banner"
    m.tecla("enter")
    assert m.filas_elementos()[0][0] == "▸ banner"
    assert m.filas_elementos()[1][0] == "▾ prompt"
    assert m.elemento_id == "banner.arte"        # un grupo selecciona su primer elemento
    m.tecla("enter")
    assert m.filas_elementos()[1][0].strip().startswith("arte")


def test_filas_elementos_llevan_marcas_mod_anim_y_contraste():
    m = _abrir()
    A.poner("prompt.etiqueta", "animacion.activa", True)
    A.poner("prompt.flecha", "color", "#101010")     # ilegible en oscuro
    m.ir_a("prompt.etiqueta")
    filas = {t.strip("> ").split()[0]: t for t, _, _ in m.filas_elementos()}
    assert filas["etiqueta"].rstrip().endswith("* mod")
    assert filas["flecha"].rstrip().endswith("mod !")
    assert "mod" not in filas["marco"]


def test_tab_y_flechas_cambian_de_panel():
    m = _abrir()
    assert m.panel == "elementos"
    m.tecla("tab")
    assert m.panel == "propiedades"
    m.tecla("left")                   # en 'color' (no ajustable) vuelve a elementos
    assert m.panel == "elementos"
    m.tecla("right")
    assert m.panel == "propiedades"


# ---------------------------------------------------------------------------
# Edicion por tipo
# ---------------------------------------------------------------------------

def test_enum_ciclico_con_enter_y_flechas():
    m = _abrir()
    _ir_a_prop(m, "prompt.marco", "posicion")
    assert A.estilo_de("prompt.marco").posicion == "ambos"
    m.tecla("enter")
    assert A.estilo_de("prompt.marco").posicion == "arriba"
    m.tecla("right")
    assert A.estilo_de("prompt.marco").posicion == "abajo"
    m.tecla("right")
    m.tecla("right")
    assert A.estilo_de("prompt.marco").posicion == "ambos", "cicla"
    m.tecla("left")
    assert A.estilo_de("prompt.marco").posicion == "ninguno"
    fila = m.filas_propiedades()[m.cursor_props][0]
    assert fila.startswith("posicion") and "ninguno" in fila and "(ambos / arriba / abajo)" in fila


def test_bool_con_space_y_enter():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "italica")
    assert "[ ]" in m.filas_propiedades()[m.cursor_props][0]
    m.tecla("space")
    assert A.estilo_de("prompt.etiqueta").italica is True
    assert "[x]" in m.filas_propiedades()[m.cursor_props][0]
    m.tecla("enter")
    assert A.estilo_de("prompt.etiqueta").italica is False


def test_numero_con_mas_menos_y_entrada_con_topes():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "glow.intensidad")
    m.tecla("+")
    m.tecla("+")
    assert A.estilo_de("prompt.etiqueta").glow.intensidad == 2
    m.tecla("+")
    m.tecla("+")
    assert A.estilo_de("prompt.etiqueta").glow.intensidad == 3
    assert "limite 0..3" in m.mensaje()
    m.tecla("enter")
    assert m.modo == "numero" and m.buffer == "3"
    m.tecla("backspace")
    m.escribir("1")
    m.tecla("enter")
    assert A.estilo_de("prompt.etiqueta").glow.intensidad == 1
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("9")
    m.tecla("enter")
    assert A.estilo_de("prompt.etiqueta").glow.intensidad == 1, "fuera de rango: no se escribe"
    assert "error" in m.mensaje()


def test_mas_menos_en_una_fila_no_numerica_avisa():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "texto")
    m.tecla("+")
    assert "no se ajusta" in m.mensaje()


def test_texto_esc_cancela_sin_tocar_nada():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "texto")
    m.tecla("enter")
    m.escribir("xxx")
    m.tecla("esc")
    assert A.texto("prompt.etiqueta") == "cognia" and not m.sucio


def test_texto_con_varias_claves_edita_cada_clave():
    m = _abrir()
    _ir_a_prop(m, "barra.modo", "texto.plan")
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("PLANIFICANDO")
    m.tecla("enter")
    assert A.texto("barra.modo", "plan") == "PLANIFICANDO"
    assert A.texto("barra.modo", "auto") == "auto"


def test_estilo_rapido_rellena_las_propiedades():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "rapido")
    m.tecla("enter")
    assert m.modo == "rapido" and "fg:@rampa.prompt" in m.buffer
    m.tecla("delete")
    m.escribir('italic texto:"gato" glow:/2')
    m.tecla("enter")
    est = A.estilo_de("prompt.etiqueta")
    assert est.texto == "gato" and est.italica is True and est.glow.intensidad == 2
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("pos:diagonal")
    m.tecla("enter")
    assert "error" in m.mensaje() and A.estilo_de("prompt.etiqueta").posicion == "linea"


# ---------------------------------------------------------------------------
# Color: sub-selector con contraste vivo; invalido rechazado con mensaje
# ---------------------------------------------------------------------------

def test_color_invalido_rechazado_con_mensaje():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    assert m.modo == "color" and m.color["pestana"] == "refs"
    m.tecla("tab")
    m.tecla("tab")
    assert m.color["pestana"] == "hex"
    m.color["buffer"] = ""
    m.escribir("#zz00")
    m.tecla("enter")
    assert m.modo == "color", "no fija: sigue en el selector"
    assert "error" in m.mensaje() and "#zz00" in m.mensaje()
    assert A.estilo_de("prompt.etiqueta").color == "@rampa.prompt"
    m.tecla("esc")
    assert m.modo == "normal" and not m.sucio


def test_color_hex_valido_se_aplica_al_teclear_y_enter_lo_fija_con_undo():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    m.tecla("tab")
    m.tecla("tab")
    m.color["buffer"] = ""
    m.escribir("#ff00ff")
    assert A.estilo_de("prompt.etiqueta").color == "#ff00ff", "tentativo: la preview ya lo ve"
    assert m.pila_undo == [], "tentativo: no entra en undo"
    filas = m.filas_flotante()
    assert filas[0][0].startswith("#ff00ff") and ":1 oscuro" in filas[0][0]
    m.tecla("enter")
    assert m.modo == "normal" and A.estilo_de("prompt.etiqueta").color == "#ff00ff"
    assert len(m.pila_undo) == 1
    m.tecla("c-z")
    assert A.estilo_de("prompt.etiqueta").color == "@rampa.prompt"


def test_color_por_refs_con_contraste_vivo_y_esc_revierte():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    refs = [t for t, _, _ in m.filas_flotante()]
    assert any("@rampa.prompt" in t and "#7ee62a" in t and ":1 oscuro" in t for t in refs)
    assert m.cursor_flotante == refs.index(next(t for t in refs if "@rampa.prompt" in t))
    m.tecla("down")
    nuevo = A.estilo_de("prompt.etiqueta").color
    assert nuevo != "@rampa.prompt" and nuevo.startswith("@")
    assert "(Enter fija)" in m.mensaje()
    m.tecla("esc")
    assert A.estilo_de("prompt.etiqueta").color == "@rampa.prompt"
    assert m.mensaje() == "color: sin cambios"


def test_color_t_pone_terminal_y_pestana_mi_sin_paleta_avisa():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    m.tecla("tab")
    assert m.color["pestana"] == "mi"
    assert "sin paleta local" in m.filas_flotante()[0][0]
    m.tecla("t")
    m.tecla("enter")
    assert A.estilo_de("prompt.etiqueta").color == "terminal"


def test_aviso_de_contraste_se_muestra_y_no_se_traga():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    m.tecla("tab")
    m.tecla("tab")
    m.color["buffer"] = ""
    m.escribir("#101010")
    assert "contraste" in m.mensaje() and "aviso" in m.mensaje()
    m.tecla("enter")
    assert A.estilo_de("prompt.etiqueta").color == "#101010", "aviso: se acepta"
    assert "contraste" in m.mensaje()
    fila = m.filas_propiedades()[_fila_prop(m, "color")][0]
    assert fila.rstrip().endswith("!")


# ---------------------------------------------------------------------------
# Glifos
# ---------------------------------------------------------------------------

def test_glifo_con_lista_ctrl_g_y_aviso_de_encoding(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    m = _abrir()
    _ir_a_prop(m, "prompt.flecha", "glifo")
    m.tecla("enter")
    assert m.modo == "texto" and m.buffer == "➤ "
    m.tecla("c-g")
    assert m.modo == "glifos"
    filas = m.filas_flotante()
    assert filas[0][0].startswith("> '➤ '") and "no codificable en cp1252" in filas[0][0]
    assert "no codificable" not in next(t for t, _, _ in filas if "'> '" in t)
    m.tecla("down")
    m.tecla("enter")
    assert m.modo == "normal"
    assert A.estilo_de("prompt.flecha").glifo == "─"
    assert "codificable" in m.mensaje()
    fila = m.filas_propiedades()[_fila_prop(m, "glifo")][0]
    assert "no codificable en cp1252" in fila


def test_glifo_enum_de_cajas_cicla():
    m = _abrir()
    _ir_a_prop(m, "panel.borde", "glifo")
    assert m.prop_actual().tipo == "enum"
    m.tecla("enter")
    assert A.estilo_de("panel.borde").glifo == "square"


# ---------------------------------------------------------------------------
# Vista previa
# ---------------------------------------------------------------------------

def test_preview_del_elemento_cambia_cuando_cambia_la_propiedad():
    m = _abrir()
    m.ir_a("prompt.etiqueta")
    antes = m.preview()
    assert " cognia➤ hola gato" in antes.plain
    _ir_a_prop(m, "prompt.etiqueta", "texto")
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("jarvis")
    m.tecla("enter")
    despues = m.preview()
    assert " jarvis➤ hola gato" in despues.plain and "cognia" not in despues.plain
    # y el color: mismo texto, spans distintos
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    m.tecla("tab")
    m.tecla("tab")
    m.color["buffer"] = ""
    m.escribir("#ff00ff")
    m.tecla("enter")
    con_color = m.preview()
    assert con_color.plain == despues.plain
    assert con_color.spans != despues.spans
    assert any(s.style.color and s.style.color.triplet == (255, 0, 255) for s in con_color.spans
               if s.style and not isinstance(s.style, str))


def test_preview_usa_el_motor_con_reloj_fijo_y_es_determinista():
    m = _abrir()
    A.poner("prompt.etiqueta", "animacion.activa", True)
    A.poner("prompt.etiqueta", "glow.intensidad", 2)
    m.ir_a("prompt.etiqueta")
    a = m.preview()
    b = m.preview()
    assert a.plain == b.plain and a.spans == b.spans
    otro = m.preview(t=0.2)
    assert otro.plain == a.plain
    assert otro.spans != a.spans, "con otro instante del reloj el barrido esta en otro sitio"


def test_preview_respeta_posicion_y_visibilidad():
    m = _abrir()
    m.ir_a("prompt.marco")
    assert m.preview().plain.count("─" * 60) == 2
    A.poner("prompt.marco", "posicion", "arriba")
    assert m.preview().plain.count("─" * 60) == 1
    A.poner("barra.estado", "posicion", "arriba")
    A.poner("barra.estado", "separador", " | ")
    lineas = m.preview().plain.split("\n")
    assert lineas[0].startswith("qwythos-27b | ~/proy | main")
    A.poner("prompt.etiqueta", "posicion", "arriba")
    lineas = m.preview().plain.split("\n")
    assert lineas[1].startswith("── cognia ──") and lineas[2].startswith("➤ hola gato")


@pytest.mark.parametrize("grupo", [g for g, _ in A.GRUPOS])
def test_todos_los_grupos_tienen_preview_no_vacio(grupo):
    m = _abrir()
    m.ir_a(dict(A.GRUPOS)[grupo][0])
    texto = m.preview()
    assert texto.plain.strip(), grupo
    frag = m.preview_pt()
    assert frag and "".join(t for _, t in frag) == texto.plain


def test_preview_pt_da_fragmentos_con_estilo_de_prompt_toolkit():
    m = _abrir()
    m.ir_a("prompt.etiqueta")
    frag = m.preview_pt()
    estilos = {s for s, t in frag if "cognia" in t}
    assert estilos and all("#7ee62a" in s and "bold" in s for s in estilos)


def test_variante_v_cicla_y_la_preview_la_sigue():
    m = _abrir()
    m.ir_a("prompt.etiqueta")
    assert m.variante_preview == "oscuro"
    oscuro = m.preview().spans
    m.tecla("v")
    assert m.variante_preview == "claro"
    assert m.preview().spans != oscuro
    m.tecla("v")
    assert m.variante_preview == "alto_contraste"
    m.tecla("v")
    assert m.variante_preview == "oscuro"


# ---------------------------------------------------------------------------
# Salir, reset, presets, exportar, ayuda, pie
# ---------------------------------------------------------------------------

def test_esc_sin_cambios_cierra_directo():
    m = _abrir()
    m.tecla("esc")
    assert m.cerrado and m.resultado == "cerrado"
    m.tecla("down")                   # cerrado: no hace nada
    assert m.cursor_elementos == 0


def test_esc_con_cambios_exige_confirmacion_y_descartar_restaura():
    m = _abrir()
    _ir_a_prop(m, "prompt.etiqueta", "texto")
    m.tecla("enter")
    m.tecla("delete")
    m.escribir("jarvis")
    m.tecla("enter")
    m.tecla("esc")
    assert m.modo == "confirmar_salir" and not m.cerrado
    assert len(m.filas_flotante()) == 3
    m.tecla("v")
    assert m.modo == "normal" and not m.cerrado
    m.tecla("q")
    assert m.modo == "confirmar_salir"
    m.tecla("d")
    assert m.cerrado and m.resultado == "descartado"
    assert A.texto("prompt.etiqueta") == "cognia"
    assert not A.RUTA_ESTILO.exists()


def test_esc_con_cambios_y_guardar_escribe_y_cierra():
    llamadas = []
    m = _abrir(guardar=lambda: llamadas.append(1))
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")
    m.tecla("esc")
    m.tecla("g")
    assert llamadas == [1] and m.cerrado and m.resultado == "guardado"


def test_guardar_con_callback_que_falla_lo_dice():
    def rompe():
        raise OSError("disco lleno")
    m = _abrir(guardar=rompe)
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")
    m.tecla("c-s")
    assert "error al guardar" in m.mensaje() and "disco lleno" in m.mensaje()
    assert m.sucio


def test_reset_r_del_elemento_y_R_de_todo_con_confirmacion():
    m = _abrir()
    A.poner("prompt.etiqueta", "texto", "jarvis")
    A.poner("prompt.marco", "posicion", "arriba")
    m.ir_a("prompt.etiqueta")
    m.tecla("r")
    assert A.texto("prompt.etiqueta") == "cognia"
    assert A.estilo_de("prompt.marco").posicion == "arriba"
    m.tecla("R")
    assert m.modo == "confirmar_reset"
    m.tecla("n")
    assert m.modo == "normal" and A.estilo_de("prompt.marco").posicion == "arriba"
    m.tecla("R")
    m.tecla("s")
    assert A.estilo_de("prompt.marco").posicion == "ambos"
    m.tecla("c-z")
    assert A.estilo_de("prompt.marco").posicion == "arriba", "el reset de todo se deshace"


def test_ctrl_p_aplica_un_preset_en_memoria_con_undo():
    m = _abrir()
    m.tecla("c-p")
    assert m.modo == "presets"
    nombres = [n for n, *_ in m._presets]
    assert set(A.PRESETS_PAQUETE) <= set(nombres)
    for _ in range(nombres.index("neon")):
        m.tecla("down")
    m.tecla("enter")
    assert m.modo == "normal"
    assert "neon" in m.mensaje() and "en memoria" in m.mensaje()
    assert A.estilo_de("banner.arte").glow.intensidad == 2
    assert A.documento().get("nombre") == "neon"
    assert not A.RUTA_ESTILO.exists()
    m.tecla("c-z")
    assert not A.tiene_override("banner.arte")


def test_ctrl_l_previsualiza_al_mover_y_esc_revierte():
    m = _abrir()
    A.poner("prompt.etiqueta", "texto", "jarvis")
    m.tecla("c-l")
    assert m.modo == "presets_preview"
    nombres = [n for n, *_ in m._presets]
    for _ in range(nombres.index("neon")):
        m.tecla("down")
    assert A.estilo_de("banner.arte").glow.intensidad == 2, "preview al mover"
    assert A.texto("prompt.etiqueta") == "cognia", "el preset reemplaza TODO el estilo"
    assert m.pila_undo == []
    m.tecla("esc")
    assert m.modo == "normal" and m.mensaje() == "preview revertido"
    assert not A.tiene_override("banner.arte")
    assert A.texto("prompt.etiqueta") == "jarvis"
    m.tecla("c-l")
    for _ in range(nombres.index("sobrio")):
        m.tecla("down")
    m.tecla("enter")
    assert A.estilo_de("prompt.flecha").glifo == "> " and len(m.pila_undo) == 1


def test_preset_invalido_se_nombra_y_no_cambia_nada(tmp_path):
    (tmp_path / "estilos").mkdir()
    (tmp_path / "estilos" / "roto.json").write_text(
        json.dumps({"version": 1, "elementos": {"prompt.etiquta": {"texto": "x"}}}), encoding="utf-8")
    m = _abrir()
    m.tecla("c-p")
    nombres = [n for n, *_ in m._presets]
    for _ in range(nombres.index("roto")):
        m.tecla("down")
    m.tecla("enter")
    assert "invalido" in m.mensaje() and "prompt.etiquta" in m.mensaje()
    assert not m.sucio and m.pila_undo == []


def test_ctrl_n_guarda_preset_y_ctrl_e_exporta(tmp_path):
    m = _abrir()
    A.poner("prompt.etiqueta", "texto", "jarvis")
    m.tecla("c-n")
    m.escribir("mio")
    m.tecla("enter")
    ruta = tmp_path / "estilos" / "mio.json"
    assert ruta.exists() and "mio" in m.mensaje()
    assert json.loads(ruta.read_text(encoding="utf-8"))["elementos"]["prompt.etiqueta"]["texto"] == "jarvis"
    m.tecla("c-e")
    assert m.modo == "exportar" and m.buffer.endswith("estilo-exportado.json")
    m.tecla("delete")
    destino = tmp_path / "ex.json"
    m.escribir(str(destino))
    m.tecla("enter")
    doc = json.loads(destino.read_text(encoding="utf-8"))
    assert len(doc["elementos"]) == len(A.REGISTRO)
    assert not A.RUTA_ESTILO.exists()


def test_ayuda_con_interrogacion_y_cualquier_tecla_cierra():
    m = _abrir()
    m.tecla("?")
    assert m.modo == "ayuda"
    filas = texto_plano(m.filas_flotante())
    assert "^S" in filas and "Esc / q" in filas
    m.tecla("x")
    assert m.modo == "normal"


def test_animacion_del_elemento_A_y_global_a():
    escrito = []
    m = _abrir(poner_config=lambda k, v: escrito.append((k, v)))
    m.ir_a("prompt.etiqueta")
    m.tecla("A")
    assert A.estilo_de("prompt.etiqueta").animacion.activa is True
    m.tecla("A")
    assert A.estilo_de("prompt.etiqueta").animacion.activa is False
    m.ir_a("tool.ok")
    m.tecla("A")
    assert "no tiene animacion" in m.mensaje()
    m.tecla("a")
    assert escrito == [("estilo_animacion", "off")] and m.animacion_global is False
    m2 = _abrir()
    m2.tecla("a")
    assert "/estilo animacion" in m2.mensaje()


def test_estado_pie_dice_las_teclas_y_el_estado_de_guardado():
    m = _abrir()
    pie = m.estado_pie()
    assert "^S guardar" in pie and "Esc salir" in pie and "sin guardar" in pie
    assert "CAMBIOS SIN GUARDAR" not in pie
    _ir_a_prop(m, "prompt.etiqueta", "negrita")
    m.tecla("space")
    assert "CAMBIOS SIN GUARDAR" in m.estado_pie() and "1 elemento con cambios" in m.estado_pie()
    m.tecla("enter")
    m.tecla("c-s")
    assert "guardado" in m.estado_pie()
    _ir_a_prop(m, "prompt.etiqueta", "color")
    m.tecla("enter")
    assert "Tab pestana" in m.estado_pie()


def test_animacion_en_elemento_no_vivo_sale_atenuada():
    e = dataclasses.replace(A.REGISTRO["prompt.etiqueta"], vivo=False)
    props = E._props_de(e)
    anim = [p for p in props if p.ruta.startswith("animacion.")]
    assert anim and all(p.atenuada for p in anim)
    assert "no animable: linea impresa" in anim[0].nota
    vivo = [p for p in E._props_de(A.REGISTRO["prompt.etiqueta"]) if p.ruta.startswith("animacion.")]
    assert not any(p.atenuada for p in vivo)


def test_las_props_solo_ofrecen_lo_que_el_elemento_acepta():
    for e in A.REGISTRO.values():
        for p in E._props_de(e):
            if p.ruta == "rapido":
                continue
            campo = p.ruta.split(".")[2] if p.ruta.startswith("estados.") else p.ruta.split(".")[0]
            assert A._CAP_DE_CAMPO[campo] in e.caps, (e.id, p.ruta)


def test_elemento_inicial_y_titulo():
    m = EditorModelo(elemento_inicial="spinner.pensar")
    assert m.elemento_id == "spinner.pensar"
    assert m.titulo_propiedades().startswith("PROPIEDADES: spinner.pensar")
    with pytest.raises(KeyError):
        EditorModelo(elemento_inicial="spinner.pensr")


# ---------------------------------------------------------------------------
# El puente con el motor (aspecto.estilo_glow / conectar_glow)
# ---------------------------------------------------------------------------

def test_estilo_glow_es_byte_identico_sin_override_y_resuelto_con_override():
    A.conectar_glow()
    assert G.RESOLVER is A.estilo_glow
    eg = A.estilo_glow("spinner.tool")
    assert eg.token == "spinner" and eg.color == "" and eg.negrita is False
    assert G.estilo_rich("spinner.tool") == "spinner"
    assert G.estilo_rich("pensando.prosa") == "pensar", "la italica del token no rompe el token"
    A.poner("spinner.tool", "color", "#ff00ff")
    eg2 = A.estilo_glow("spinner.tool")
    assert eg2.color == "#ff00ff"
    assert str(G.estilo_rich("spinner.tool")) == "#ff00ff"
    ok = A.estilo_glow("footer.turno", estado="ok")
    assert ok.token == "ok_cl" and ok.color == ""
    with pytest.raises(KeyError):
        A.estilo_glow("footer.turno", estado="zzz")


def test_instantanea_restaurar_y_aplicar_en_memoria():
    A.poner("prompt.etiqueta", "texto", "jarvis")
    inst = A.instantanea()
    A.poner("prompt.etiqueta", "texto", "otro")
    v = A.version()
    A.restaurar(inst)
    assert A.texto("prompt.etiqueta") == "jarvis" and A.version() > v
    avisos = A.aplicar_en_memoria({"version": 1, "nombre": "x", "paleta": {"lima": "#c8ff7a"},
                                   "elementos": {"prompt.flecha": {"color": "@mi.lima"}}})
    assert avisos == [] or all(a.nivel == "aviso" for a in avisos)
    assert A.texto("prompt.etiqueta") == "cognia", "un preset reemplaza todo"
    assert A.paleta_local() == {"lima": "#c8ff7a"}
    assert A.estilo_resuelto("prompt.flecha").color == "#c8ff7a"
    assert A.documento()["nombre"] == "x"
    with pytest.raises(A.EstiloInvalido):
        A.aplicar_en_memoria({"version": 1, "elementos": {"nadie": {}}})
    assert A.estilo_resuelto("prompt.flecha").color == "#c8ff7a", "invalido: no cambia nada"
