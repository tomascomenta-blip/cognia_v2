# -*- coding: utf-8 -*-
"""El AGENTE sabe en que sistema y en que shell corre (2026-08-25).

EL FALLO QUE ESTOS TESTS FIJAN. Corrida real del 2026-08-25 en la maquina del
dueno (Windows 11): el agente ejecuto `uname -s`, `find` y `ls -R`, gasto 6 de
sus pasos y cerro "sin progreso verificado". Su system prompt no decia ni el
sistema operativo, ni el shell, ni el cwd — el prompt del CHAT si lo dice desde
esa misma manana (system_prompt.entorno_usuario), el del agente no tenia nada.

EL TOPE ES LA MITAD DEL ARREGLO. El A/B del 2026-07-23 sobre el gate del camino
feliz midio que prosa extra en el prompt del agente lo hunde de 10/10 a 1/4
corridas perfectas. Lo que entra aqui es UN DATO de <=120 chars, y estos tests
son los que impiden que manana sea un parrafo:
    - test_la_linea_de_entorno_no_pasa_del_tope
    - test_el_agente_crece_como_mucho_el_tope   (los dos caminos del prompt)
    - test_con_el_kill_switch_el_prompt_es_byte_identico

Y EL SHELL SE MIDE, NO SE SUPONE. `ejecutar` corre en subprocess(shell=True):
en Windows eso es %COMSPEC% = cmd.exe, NO el PowerShell donde escribe el dueno.
Medido con la propia tool el 2026-08-25 en esta maquina:
    echo %COMSPEC% -> C:\\WINDOWS\\system32\\cmd.exe
    Get-ChildItem  -> exit 1, "no se reconoce como un comando interno o externo"
    uname -s       -> MINGW64_NT-10.0-26200   (Git for Windows en el PATH)
    ls -la / find / grep / head  -> OK, por C:\\Program Files\\Git\\usr\\bin
O sea, al reves de lo que uno adivinaria: aqui fallan los cmdlets, no los
POSIX. Por eso la pista de la tool se dispara con el ERROR REAL del interprete
(test_la_pista_sale_del_error_del_shell_no_de_la_pinta_del_comando).
"""
import os
import platform

import pytest

from cognia import system_prompt as sp
from cognia.agent import model_profiles as mp


# ── 1. La linea de entorno del agente ─────────────────────────────────────

def test_la_linea_de_entorno_no_pasa_del_tope(monkeypatch):
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    linea = sp.entorno_agente()
    assert linea, "sin kill-switch la linea tiene que existir"
    # +2 por el "\n\n" con el que se pega al prompt.
    assert len(linea) + 2 <= sp.TOPE_ENTORNO_AGENTE, \
        f"la linea del agente crecio a {len(linea) + 2} chars: {linea!r}"
    assert "\n" not in linea, "es UNA linea, no un bloque de prosa"
    # Datos verdaderos en ESTA maquina, sin hardcodear el SO del CI.
    assert platform.system().split()[0] in linea or "desconocido" in linea
    assert sp.shell_de_ejecutar() in linea


def test_la_linea_nombra_el_shell_de_la_TOOL_no_el_del_dueno(monkeypatch):
    """En Windows el dueno vive en PowerShell y la tool corre en cmd.exe.
    Decirle 'PowerShell' al agente seria mentirle sobre donde van sus comandos
    (medido: Get-ChildItem da exit 1 por la tool)."""
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    if platform.system() != "Windows":
        pytest.skip("la divergencia PowerShell/cmd.exe es de Windows")
    monkeypatch.setenv("PSModulePath", r"C:\fake\Modules")
    monkeypatch.setenv("COMSPEC", r"C:\WINDOWS\system32\cmd.exe")
    assert sp.shell_de_ejecutar() == "cmd.exe"
    linea = sp.entorno_agente()
    assert "cmd.exe" in linea and "PowerShell" not in linea
    # ...y el bloque del CHAT sigue diciendo PowerShell, que ahi SI es cierto.
    assert "PowerShell" in sp.entorno_usuario()


def test_el_cwd_larguisimo_se_recorta_para_entrar_en_el_tope(monkeypatch):
    """Un proyecto anidado da un cwd de 200 chars y la linea NO puede desbordar.

    El cwd se INYECTA en vez de crear las carpetas de verdad: en Windows
    os.mkdir revienta con WinError 3 pasados los 260 chars de MAX_PATH, o sea
    el test no podia construir el caso que quiere fijar."""
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    hondo = "C:\\" + "\\".join(["subcarpeta_con_nombre_largo"] * 12)
    monkeypatch.setattr(sp, "_medir_entorno",
                        lambda: ("Windows 11", "PowerShell", hondo))
    linea = sp.entorno_agente()
    assert len(linea) + 2 <= sp.TOPE_ENTORNO_AGENTE, repr(linea)
    assert "..." in linea, "el recorte del cwd tiene que ser visible"
    # Se recorta por la IZQUIERDA: la cola del cwd es la parte que informa.
    assert linea.split("...", 1)[1].startswith(hondo[-10:][:1]) or \
        "subcarpeta_con_nombre_largo;" in linea


def test_entorno_agente_nunca_lanza(monkeypatch):
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    monkeypatch.setattr(sp, "_medir_entorno",
                        lambda: (_ for _ in ()).throw(OSError("cwd borrado")))
    assert sp.entorno_agente() == ""


# ── 2. Los DOS caminos del prompt del agente ──────────────────────────────

def _prompts_del_agente():
    """(nombre, callable) de cada camino que arma un system del agente."""
    yield "nativo", lambda: mp.system_agente_nativo()
    for perfil in ("minimo", "compacto", "completo"):
        yield f"texto:{perfil}", (
            lambda p=perfil: sp.build_system_prompt(rol="agente", perfil=p))


@pytest.mark.parametrize("nombre,arma", list(_prompts_del_agente()))
def test_el_agente_crece_como_mucho_el_tope(nombre, arma, monkeypatch):
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    con = arma()
    monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
    sin = arma()
    crecimiento = len(con) - len(sin)
    assert 0 < crecimiento <= sp.TOPE_ENTORNO_AGENTE, \
        f"{nombre}: el prompt del agente crecio {crecimiento} chars"
    # Es un DATO, no el bloque de prosa del chat.
    assert "ENTORNO DEL USUARIO" not in con
    assert "NO ejecutas nada" not in con


@pytest.mark.parametrize("nombre,arma", list(_prompts_del_agente()))
def test_con_el_kill_switch_el_prompt_es_byte_identico(nombre, arma, monkeypatch):
    """COGNIA_ENTORNO_PROMPT=0 devuelve el prompt de antes de este cambio,
    byte a byte: el contrafactual del A/B vive apagando el env, no revirtiendo
    el commit."""
    monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
    sin = arma()
    if nombre == "nativo":
        hoy = "\n\n".join([sp._IDENTIDAD.strip(), sp._CONDUCTA_COMPLETA.strip(),
                           mp._ROL_AGENTE_NATIVO.strip()])
    else:
        perfil = nombre.split(":", 1)[1]
        if perfil == "minimo":
            hoy = sp._IDENTIDAD
        else:
            conducta = (sp._CONDUCTA_COMPLETA if perfil == "completo"
                        else sp._CONDUCTA_COMPACTA)
            hoy = "\n\n".join(p.strip() for p in
                              (sp._IDENTIDAD, conducta, sp._AGENTE))
    assert sin == hoy


def test_el_sufijo_del_harness_sigue_siendo_LO_ULTIMO(monkeypatch):
    """El entorno se cuela ANTES del sufijo: deepagents cuelga el suyo al final
    y ese contrato ya tiene test propio (test_deepagents_bucle::test_p8)."""
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    texto = mp.system_agente_nativo({"harness": {"sufijo_prompt": "SUFIJO"}})
    assert texto.endswith("\n\nSUFIJO")
    assert sp.entorno_agente() in texto


# ── 3. El CHAT no se toca ─────────────────────────────────────────────────

def test_el_bloque_del_chat_queda_igual(monkeypatch):
    """entorno_usuario se refactorizo para compartir la medicion; su texto NO
    cambia (es el arreglo del transcript del dueno, de esta misma manana)."""
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    ent = sp.entorno_usuario()
    assert ent.startswith("ENTORNO DEL USUARIO\n")
    assert "Sistema operativo: " in ent and "Shell: " in ent
    assert os.getcwd() in ent
    assert "NO ejecutas nada" in ent and "/hacer" in ent
    assert "JAMAS afirmes haber ejecutado" in ent
    cerebro = sp.build_system_prompt(rol="cerebro")
    assert ent in cerebro


# ── 4. La tool 'ejecutar' dice su shell y avisa cuando no existe ──────────

def test_la_tool_ejecutar_declara_su_shell_real():
    from cognia.agent.tools import TOOLS, _SHELL_REAL
    assert _SHELL_REAL == sp.shell_de_ejecutar()
    spec = TOOLS["ejecutar"]
    assert _SHELL_REAL in spec["doc"], spec["doc"]
    assert _SHELL_REAL in spec["desc"], spec["desc"]


def test_la_pista_sale_del_error_del_shell_no_de_la_pinta_del_comando():
    """La pista NO se dispara por 'este comando parece de Linux' (en esta
    maquina `uname`/`ls`/`find` funcionan): se dispara con el texto que
    imprimio el interprete."""
    from cognia.agent import tools
    if os.name != "nt":
        pytest.skip("los mensajes de cmd.exe son de Windows")
    cmd_dice = ('"Get-ChildItem" no se reconoce como un comando interno o '
                'externo,\nprograma o archivo por lotes ejecutable.')
    pista = tools._pista_shell(cmd_dice, 1)
    assert "cmd.exe" in pista and "Get-ChildItem" in pista
    assert "powershell -NoProfile -c" in pista
    # Salida normal, o exit != 0 por OTRO motivo: ni una palabra de mas.
    assert tools._pista_shell(cmd_dice, 0) == ""
    assert tools._pista_shell("No se encuentra el archivo", 1) == ""
    assert tools._pista_shell("Traceback (most recent call last):", 1) == ""
    assert tools._pista_shell("", 1) == ""


def test_la_pista_da_el_equivalente_cuando_lo_conoce():
    """Version en ingles y comando POSIX: en una maquina SIN Git for Windows
    `ls` no existe y ahi el equivalente concreto vale mas que el consejo."""
    from cognia.agent import tools
    if os.name != "nt":
        pytest.skip("los mensajes de cmd.exe son de Windows")
    pista = tools._pista_shell(
        "'ls' is not recognized as an internal or external command,", 1)
    assert "dir /b" in pista and "'ls'" in pista


def test_la_pista_entiende_los_DOS_dialectos_de_error(monkeypatch):
    """cmd.exe dice "X" no se reconoce...; sh dice `bash: X: command not found`.

    El nombre que falta va en OTRO sitio de la linea en cada uno, y con una
    sola alternativa de regex el caso POSIX se perdia siempre (medido al
    escribir esto: devolvia "")."""
    from cognia.agent import tools
    monkeypatch.setattr(tools.os, "name", "posix")
    monkeypatch.setattr(sp, "shell_de_ejecutar", lambda: "/bin/sh")
    pista = tools._pista_shell("bash: uname: command not found", 1)
    assert "uname" in pista and "PATH" in pista and "/bin/sh" in pista
    assert tools._pista_shell("No se encuentra el archivo", 1) == ""


def test_la_pista_se_pega_al_resultado_de_la_tool(monkeypatch):
    """De punta a punta por la tool de verdad, no por el helper suelto."""
    if os.name != "nt":
        pytest.skip("Get-ChildItem solo falla asi en cmd.exe")
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    from cognia.agent.tools import TOOLS
    salida = TOOLS["ejecutar"]["fn"]("Get-ChildItem", {})
    assert salida.startswith("RESULTADO ejecutar (exit 1):")
    assert "no se reconoce" in salida
    assert "\nNOTA: esta maquina es Windows" in salida
    assert "cmd.exe" in salida
