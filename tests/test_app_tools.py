# -*- coding: utf-8 -*-
"""
tests/test_app_tools.py
=======================
Apps graficas en el ESCRITORIO PROPIO (cognia/agent/app_tools.py +
escritorio_propio.py, 2026-09-07). Sin ventana real: el parser de pasos, la
politica de foco (nunca / inactivo / siempre) con la inactividad simulada, el
troceado de comandos con comillas (regresion del e2e de probar), la config y
el registro de apps. Con COGNIA_E2E_APP=1 ademas lanza un tkinter REAL, lo
muda al escritorio de Cognia, teclea, captura y cierra (Windows con pyvda).
"""
from __future__ import annotations

import os
import sys

import pytest

from cognia.agent import app_tools as AT
from cognia.agent import escritorio_propio as EP


# ── parser de pasos ──────────────────────────────────────────────────────────

def test_parsear_pasos_cubre_la_gramatica():
    pasos = AT.parsear_pasos('tecla derecha*3; teclas a,b; escribir "hola mundo"; clic 10,20; clic "Boton"; '
                             'dobleclic 5,5; espera 250; esperar "listo" 800; captura; captura fin; atajo ctrl+s; '
                             'texto; arbol; cerrar')
    ops = [p[0] for p in pasos]
    assert ops == ["tecla", "tecla", "tecla", "escribir", "clic", "clic", "dobleclic", "espera", "esperar",
                   "captura", "captura", "atajo", "texto", "arbol", "cerrar"]
    assert pasos[0] == ("tecla", "derecha", 3)
    assert pasos[3] == ("escribir", "hola mundo")
    assert pasos[4] == ("clic", 10, 20) and pasos[5] == ("clic", "Boton")
    assert pasos[8] == ("esperar", "listo", 800)
    assert pasos[10] == ("captura", "fin")


def test_parsear_pasos_rechaza_lo_desconocido():
    with pytest.raises(ValueError) as e:
        AT.parsear_pasos("tecla a; volar 3")
    assert "volar 3" in str(e.value)
    assert AT.parsear_pasos("") == []


def test_partir_comando_quita_comillas_envolventes():
    partes = AT._partir_comando('python "C:\\ruta con espacios\\gui.py" --x')
    assert partes == ["python", "C:\\ruta con espacios\\gui.py", "--x"]


# ── navegadores en la mesa: flags anti-oclusion + resolucion por App Paths ──

def test_resolver_via_app_paths_usa_el_registro(monkeypatch, tmp_path):
    import winreg
    falso = tmp_path / "msedge.exe"
    falso.write_bytes(b"")

    class FakeKey:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_open_key(hive, subkey):
        assert subkey.endswith(r"App Paths\msedge.exe")
        return FakeKey()

    def fake_query(_key, _name):
        return (str(falso), 1)

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query)
    assert AT._resolver_via_app_paths("msedge.exe") == str(falso)


def test_resolver_via_app_paths_sin_registro_devuelve_igual(monkeypatch):
    import winreg

    def fake_open_key(hive, subkey):
        raise OSError("no encontrado")

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    assert AT._resolver_via_app_paths("appinventada.exe") == "appinventada.exe"
    # ya viene con ruta: no toca el registro
    assert AT._resolver_via_app_paths("C:\\ya\\con\\ruta.exe") == "C:\\ya\\con\\ruta.exe"


def test_agregar_flags_sin_oclusion_navegador_conocido(monkeypatch):
    """Regresion 2026-09-09: msedge.exe/chrome.exe sueltos (sin ruta) SIEMPRE
    fallaban en el primer intento de lanzar() (CreateProcess directo no mira
    'App Paths'), y el fallback por shell perdia estas flags -> la pagina
    quedaba congelada en la mesa. Ademas, sin --disable-features=
    CalculateNativeWinOcclusion la ventana no repinta estando en un
    escritorio virtual no activo, y sin --no-first-run un --user-data-dir
    aislado (recien agregado en 4.32.2) mostraba el wizard de bienvenida en
    vez de navegar a la URL. Las tres cosas medidas en vivo, no adivinadas."""
    monkeypatch.setattr(AT, "_resolver_via_app_paths", lambda exe: exe)
    partes = AT._agregar_flags_sin_oclusion(["msedge.exe", "https://x.test"])
    assert partes[0] == "msedge.exe" and partes[1] == "https://x.test"
    for f in AT._FLAGS_SIN_OCLUSION:
        assert f in partes
    assert "--disable-features=CalculateNativeWinOcclusion" in partes
    assert "--no-first-run" in partes and "--no-default-browser-check" in partes
    assert any(p.startswith("--user-data-dir=") for p in partes)


def test_agregar_flags_sin_oclusion_no_navegador_queda_intacto():
    partes = AT._agregar_flags_sin_oclusion(["notepad.exe", "archivo.txt"])
    assert partes == ["notepad.exe", "archivo.txt"]


def test_lanzar_fallback_por_shell_conserva_las_flags(monkeypatch):
    """Regresion 2026-09-09: cuando el primer intento (lista, sin shell)
    fallaba con FileNotFoundError -- SIEMPRE, para 'msedge.exe url' sin ruta
    completa -- el fallback relanzaba con el 'comando' CRUDO, perdiendo las
    flags anti-oclusion. Y pasar 'partes' (una lista) con shell=True en
    Windows tampoco alcanza: Popen solo ejecuta el primer elemento como
    comando y trata el resto como argumentos SUELTOS de cmd.exe (mismo
    gotcha que en POSIX) -- hay que unirla con list2cmdline en una sola
    linea. Sin esto, la pagina quedaba congelada/en blanco en la mesa."""
    llamadas = []

    class FakeProc:
        pid = 999999
        returncode = None
        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        llamadas.append((args, bool(kwargs.get("shell"))))
        if not kwargs.get("shell"):
            raise FileNotFoundError("no encontrado")
        return FakeProc()

    monkeypatch.setattr(AT.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(AT, "_resolver_via_app_paths", lambda exe: exe)
    monkeypatch.setattr(AT, "_descendientes", lambda pid: {pid})
    monkeypatch.setattr(EP, "ventanas_visibles", lambda: [])
    monkeypatch.setattr(EP, "matar_arbol", lambda pid: None)

    with pytest.raises(ValueError):
        AT.lanzar("msedge.exe https://x.test", espera_ms=300)

    assert len(llamadas) == 2
    primer_args, primer_shell = llamadas[0]
    segundo_args, segundo_shell = llamadas[1]
    assert primer_shell is False and isinstance(primer_args, list)
    assert segundo_shell is True
    assert isinstance(segundo_args, str), "debe ser UNA linea (list2cmdline), no la lista suelta"
    assert "--disable-features=CalculateNativeWinOcclusion" in segundo_args
    assert "--no-first-run" in segundo_args and "https://x.test" in segundo_args


# ── politica de foco y config ────────────────────────────────────────────────

def test_config_por_defecto_y_env(monkeypatch):
    monkeypatch.setattr(EP, "_cfg", lambda: {})
    monkeypatch.delenv("COGNIA_ESCRITORIO", raising=False)
    monkeypatch.delenv("COGNIA_ESCRITORIO_FOCO", raising=False)
    c = EP.config()
    assert c == {"activo": True, "nombre": "Cognia", "foco": "nunca", "inactividad_s": 90}
    monkeypatch.setenv("COGNIA_ESCRITORIO", "0")
    assert EP.config()["activo"] is False
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "siempre", "escritorio_inactividad_s": 2,
                                            "escritorio_nombre": "Lab"})
    monkeypatch.delenv("COGNIA_ESCRITORIO")
    c = EP.config()
    assert c["foco"] == "siempre" and c["inactividad_s"] == 5 and c["nombre"] == "Lab"


def test_politica_de_foco(monkeypatch):
    monkeypatch.delenv("COGNIA_ESCRITORIO_FOCO", raising=False)
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "nunca"})
    ok, motivo = EP.puede_tomar_foco()
    assert ok is False and "nunca" in motivo
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "siempre"})
    assert EP.puede_tomar_foco()[0] is True
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "inactivo", "escritorio_inactividad_s": 60})
    monkeypatch.setattr(EP, "dueno_inactivo_s", lambda: 5.0)
    ok, motivo = EP.puede_tomar_foco()
    assert ok is False and "usando el equipo" in motivo
    monkeypatch.setattr(EP, "dueno_inactivo_s", lambda: 120.0)
    ok, motivo = EP.puede_tomar_foco()
    assert ok is True and "inactivo 120s" in motivo


def test_con_foco_no_cambia_si_la_politica_lo_prohibe(monkeypatch):
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "nunca"})
    monkeypatch.setattr(EP, "es_el_actual", lambda d=None: False)
    cambios = []
    monkeypatch.setattr(EP, "ir", lambda: cambios.append("ir"))
    monkeypatch.setattr(EP, "volver", lambda: cambios.append("volver"))
    with EP.con_foco() as (ok, motivo):
        assert ok is False and "nunca" in motivo
    assert cambios == []
    monkeypatch.setattr(EP, "_cfg", lambda: {"escritorio_foco": "siempre"})
    with EP.con_foco() as (ok, motivo):
        assert ok is True
    assert cambios == ["ir", "volver"]


def test_app_clic_con_foco_no_bypassea_politica_nunca(monkeypatch):
    """Regresion: antes, app_clic con foco=1 forzaba entrada_real (forzar=foco)
    aunque escritorio_foco=nunca, saltandose la politica del dueno y tomando
    su monitor de todos modos (queja 2026-09-09, 'a veces usa mi monitor').
    Ahora el clic siempre respeta EP.puede_tomar_foco(), sin importar foco=."""
    AT._APPS.clear()
    AT._APPS["a1"] = {"hwnd": 111, "pid": 1, "titulo": "x", "proc": None, "log": "", "capturas": []}
    monkeypatch.setattr(EP, "ventana_viva", lambda h: True)
    monkeypatch.setattr(EP, "puede_tomar_foco", lambda: (False, "politica escritorio_foco=nunca"))

    def _entrada_real_no_debe_llamarse(*a, **kw):
        raise AssertionError("entrada_real no debe llamarse bajo escritorio_foco=nunca")
    monkeypatch.setattr(EP, "entrada_real", _entrada_real_no_debe_llamarse)
    monkeypatch.setattr(EP, "clic", lambda hwnd, x, y, boton="izquierdo", doble=False: {"control": "Boton"})

    out = AT.ejecutar_paso("a1", ("clic", 10, 20), None, foco=True)
    assert not out["error"]
    assert "por mensajes" in out["texto"]


def test_vk_de_conoce_alias_en_castellano():
    if os.name != "nt":
        pytest.skip("VkKeyScanW es de Windows")
    assert EP.vk_de("intro") == (0x0D, "\r")
    assert EP.vk_de("derecha")[0] == 0x27 and EP.vk_de("ArrowRight")[0] == 0x27
    assert EP.vk_de("f5")[0] == 0x74
    vk, ch = EP.vk_de("a")
    assert ch == "a" and vk == 0x41
    with pytest.raises(ValueError):
        EP.vk_de("teclarara")


def test_estado_sin_pyvda_degrada_con_causa(monkeypatch):
    def sin():
        raise ValueError("falta pyvda (x). Instalalo con: pip install pyvda")
    monkeypatch.setattr(EP, "_vd", sin)
    e = EP.estado()
    assert e["activo"] is False and e["disponible"] is False and "pip install pyvda" in e["motivo"]
    assert EP.mover_ventana(123) is False
    assert "pip install pyvda" in EP.ultimo()["error"]


def test_app_desconocida_y_lista_sin_apps(tmp_path, monkeypatch):
    monkeypatch.setattr(EP, "_REGISTRO", tmp_path / "reg.json")
    AT._APPS.clear()
    from cognia.agent.tools import TOOLS
    out = TOOLS["app_ver"]["fn"]("a99", {"_scratchpad": str(tmp_path)})
    assert "ERROR" in out and "no hay app 'a99'" in out
    out = TOOLS["app_teclas"]["fn"]("a1 | volar", {"_scratchpad": str(tmp_path)})
    assert "ERROR" in out and "paso no entendido" in out


def test_lanzar_proceso_sin_ventana_devuelve_su_salida(tmp_path):
    if os.name != "nt":
        pytest.skip("EnumWindows es de Windows")
    with pytest.raises(ValueError) as e:
        AT.lanzar('python -c "print(123); raise SystemExit(4)"', espera_ms=2500)
    msg = str(e.value)
    assert "exit 4" in msg and "123" in msg and "ejecutar_guion" in msg


# ── e2e real (opt-in) ────────────────────────────────────────────────────────

SUJETO = """import tkinter as tk
r = tk.Tk(); r.title("Sujeto e2e Cognia"); r.geometry("300x200")
lab = tk.Label(r, text="esperando", font=("Arial", 18)); lab.pack(pady=30)
r.bind("<Key>", lambda ev: (lab.config(text="tecla " + ev.keysym), r.configure(bg="#3355ff")))
r.mainloop()
"""


@pytest.mark.skipif(os.environ.get("COGNIA_E2E_APP") != "1" or os.name != "nt",
                    reason="e2e real con ventana: COGNIA_E2E_APP=1 en Windows")
def test_e2e_tkinter_en_el_escritorio_propio(tmp_path):
    (tmp_path / "sujeto.py").write_text(SUJETO, encoding="utf-8")
    from cognia.agent.tools import TOOLS
    ctx = {"_scratchpad": str(tmp_path), "workspace": str(tmp_path)}
    actual_antes = EP.actual().number
    out = TOOLS["app_probar"]["fn"]("python sujeto.py | pasos=tecla a; espera 300; captura", ctx)
    assert "ventana 'Sujeto e2e Cognia'" in out, out
    assert "escritorio 'Cognia'" in out
    assert "pantalla cambio" in out
    assert "mosaico de" in out and "cerrada" in out
    assert EP.actual().number == actual_antes
