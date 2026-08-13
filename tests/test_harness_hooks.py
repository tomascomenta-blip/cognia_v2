# -*- coding: utf-8 -*-
"""Tests de cognia/harness/hooks.py — hooks de usuario PRE/POST herramienta.

Ejecucion REAL de subprocesos (nada de mocks): cada hook es un script Python
escrito en el tmp_path y corrido con el interprete del venv (sys.executable).
Pinea lo que un cambio no puede romper sin avisar: bloqueo de la llamada,
tolerancia a config ausente/corrupta, matching estilo permiso, sustitucion de
variables, cwd, stdin cerrado, timeout y tope de salida.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cognia.harness import hooks as H


def _escribir_config(raiz: Path, datos) -> Path:
    d = raiz / ".cognia"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "hooks.json"
    texto = datos if isinstance(datos, str) else json.dumps(datos, indent=2)
    f.write_text(texto, encoding="utf-8")
    return f


def _script(raiz: Path, nombre: str, cuerpo: str) -> str:
    """Escribe un script hook y devuelve el comando que lo invoca (con comillas)."""
    p = raiz / nombre
    p.write_text(cuerpo, encoding="utf-8")
    return f'"{sys.executable}" "{p}"'


@pytest.fixture(autouse=True)
def _hooks_encendidos(monkeypatch):
    # El kill-switch se prueba explicitamente; el resto corre con hooks ON.
    monkeypatch.delenv("COGNIA_HOOKS", raising=False)


# ── cargar(): tolerancia ──────────────────────────────────────────────────────

def test_cargar_sin_fichero_devuelve_vacio_sin_aviso(tmp_path):
    cfg = H.cargar(tmp_path)
    assert cfg["pre_tool"] == [] and cfg["post_tool"] == []
    assert cfg["avisos"] == []          # ausente es el caso NORMAL, no un problema


def test_cargar_json_corrupto_avisa_y_no_revienta(tmp_path):
    _escribir_config(tmp_path, "{esto no es json,,,")
    cfg = H.cargar(tmp_path)
    assert cfg["pre_tool"] == [] and cfg["post_tool"] == []
    assert cfg["avisos"] and "hooks.json" in cfg["avisos"][0]


def test_cargar_descarta_entradas_invalidas_con_aviso(tmp_path):
    _escribir_config(tmp_path, {
        "pre_tool": [{"match": "x"}, "no soy dict",
                     {"match": "escribir_archivo", "comando": "echo ok"}],
        "post_tool": "tampoco soy lista",
    })
    cfg = H.cargar(tmp_path)
    assert [h["comando"] for h in cfg["pre_tool"]] == ["echo ok"]
    assert cfg["pre_tool"][0]["bloqueante"] is False        # default explicito
    assert cfg["post_tool"] == []
    assert len(cfg["avisos"]) == 3


def test_cargar_tolera_bom_utf8(tmp_path):
    # En Windows `... | Out-File hooks.json` escribe UTF-8 CON BOM (EF BB BF) y
    # Notepad tambien: sin tolerarlo, la config del usuario se ignora entera con
    # un "JSON invalido" que no es culpa suya.
    d = tmp_path / ".cognia"
    d.mkdir()
    (d / "hooks.json").write_text(
        json.dumps({"pre_tool": [{"match": "*", "comando": "echo ok"}]}), encoding="utf-8-sig")
    cfg = H.cargar(tmp_path)
    assert [h["comando"] for h in cfg["pre_tool"]] == ["echo ok"]
    assert cfg["avisos"] == []


def test_cargar_tolera_utf16_con_bom_y_acentos(tmp_path):
    d = tmp_path / ".cognia"
    d.mkdir()
    (d / "hooks.json").write_text(
        json.dumps({"post_tool": [{"match": "*", "comando": "echo camión ñandú"}]},
                   ensure_ascii=False), encoding="utf-16")
    cfg = H.cargar(tmp_path)
    assert cfg["post_tool"][0]["comando"] == "echo camión ñandú"
    assert cfg["avisos"] == []


def test_cargar_avisa_si_el_glob_lleva_backslash(tmp_path):
    # Fail-open silencioso: los args se normalizan a '/', asi que 'prod\*' no
    # casa nunca y el veto de prod/ no se dispararia jamas.
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "escribir_archivo(prod\\*)", "comando": "echo x", "bloqueante": True}]})
    cfg = H.cargar(tmp_path)
    assert len(cfg["avisos"]) == 1 and "no casara nunca" in cfg["avisos"][0]
    assert cfg["pre_tool"] and cfg["pre_tool"][0]["bloqueante"] is True   # se conserva


def test_raiz_invalida_no_revienta(tmp_path):
    # cargar() promete ser tolerante; correr_pre() no puede tumbar el agente por
    # una raiz mal pasada por el integrador.
    cfg = H.cargar(None)
    assert cfg["pre_tool"] == [] and cfg["avisos"]
    assert H.correr_pre("editar_archivo", "a.py", None)["permitido"] is True
    assert H.correr_post("editar_archivo", "a.py", "r", None)["anexo"] == ""


def test_cargar_solo_mira_la_raiz_dada(tmp_path):
    otro = tmp_path / "otro_proyecto"
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    _escribir_config(otro, {"pre_tool": [{"match": "*", "comando": "echo intruso"}]})
    assert H.cargar(proyecto)["pre_tool"] == []


def test_kill_switch_desactiva_todo(tmp_path, monkeypatch):
    testigo = tmp_path / "corrio.txt"
    cmd = _script(tmp_path, "hook.py",
                  f"open(r'{testigo}', 'w', encoding='utf-8').write('x')\nraise SystemExit(1)\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd, "bloqueante": True}]})
    monkeypatch.setenv("COGNIA_HOOKS", "0")
    pre = H.correr_pre("escribir_archivo", "a.py", tmp_path)
    assert pre["permitido"] is True and pre["salidas"] == []
    assert not testigo.exists()


# ── matching estilo regla de permiso ──────────────────────────────────────────

@pytest.mark.parametrize("patron,herramienta,args,esperado", [
    ("escribir_archivo", "escribir_archivo", "a.py", True),
    ("escribir_archivo", "editar_archivo", "a.py", False),
    ("*", "lo_que_sea", "", True),
    ("escribir_*", "escribir_archivo", "a.py", True),
    ("editar_archivo(*.py)", "editar_archivo", "cognia/x.py | contenido", True),
    ("editar_archivo(*.py)", "editar_archivo", "notas.md | contenido", False),
    ("editar_archivo(*.py)", "escribir_archivo", "cognia/x.py", False),
    ("escribir_archivo(prod/*)", "escribir_archivo", "prod/config.yaml", True),
    ("escribir_archivo(prod/*)", "escribir_archivo", "dev/config.yaml", False),
    ("editar_archivo(*.py)", "editar_archivo", {"ruta": "src/main.py"}, True),
])
def test_patron_matchea(patron, herramienta, args, esperado):
    assert H.patron_matchea(patron, herramienta, args) is esperado


@pytest.mark.parametrize("patron,herramienta,args,esperado", [
    # La caja importa en TODOS los SO (fnmatch.fnmatch la normalizaria en Windows
    # y este hook bloquearia aqui y no en el CI de Linux).
    ("escribir_archivo(prod/*)", "escribir_archivo", "PROD/config.yaml", False),
    ("ESCRIBIR_archivo", "escribir_archivo", "a.py", False),
    # Una ruta de Windows casa el mismo glob que la POSIX (se normaliza a '/').
    ("escribir_archivo(prod/*)", "escribir_archivo", "prod\\config.yaml", True),
    ("escribir_archivo(prod/*)", "escribir_archivo", {"ruta": "prod\\sub\\x.yaml"}, False),
    # La barra es frontera: '*' no la cruza, '**' si (igual que en los permisos).
    ("x(src/*)", "x", "src/a/b.py", False),
    ("x(src/**)", "x", "src/a/b.py", True),
    ("x(**/*.py)", "x", "a/b/c.py", True),
    # Parentesis vacios = herramienta a secas, no un hook muerto.
    ("x()", "x", "a.py", True),
])
def test_patron_matchea_es_independiente_del_so(patron, herramienta, args, esperado):
    assert H.patron_matchea(patron, herramienta, args) is esperado


def test_glob_consistente_con_las_reglas_de_permiso():
    """El docstring promete "el MISMO formato que las reglas de permiso": se pina.

    Si permisos_reglas cambia su semantica de glob y hooks no, este test lo canta
    en vez de dejar que el mismo patron signifique dos cosas en el mismo .cognia/.
    """
    from cognia.harness import permisos_reglas as P

    casos = [
        ("prod/*", "prod/config.yaml"), ("prod/*", "prod/sub/x.yaml"),
        ("prod/*", "PROD/config.yaml"), ("prod/*", "prod\\config.yaml"),
        ("src/**", "src/a/b.py"), ("**/*.py", "a/b/c.py"), ("*.py", "x.py"),
        ("*.py", "cognia/x.py"), ("a?c.txt", "abc.txt"), ("a?c.txt", "a/c.txt"),
    ]
    for glob, objetivo in casos:
        mio = H.patron_matchea(f"herr({glob})", "herr", objetivo)
        suyo = P.casar(f"herr({glob})", "herr", objetivo)
        # Unica divergencia declarada: hooks prueba tambien el basename.
        if mio != suyo:
            assert mio and P.casar(f"herr({glob})", "herr", Path(objetivo).name), (glob, objetivo)


@pytest.mark.parametrize("args,esperado", [
    ("cognia/x.py | contenido nuevo", "cognia/x.py"),
    ({"ruta": "src/main.py", "texto": "hola"}, "src/main.py"),
    ({"texto": "hola", "destino": "out/a.txt"}, "out/a.txt"),
    ("--force notas.md", "notas.md"),
    ("solo texto sin rutas", ""),
    ("https://ejemplo.com/x.py", ""),        # URL no es ruta
    (None, ""),
])
def test_ruta_de_heuristica(args, esperado):
    assert H.ruta_de(args) == esperado


# ── correr_pre: bloqueo real ──────────────────────────────────────────────────

def test_pre_bloqueante_con_exit_no_cero_bloquea(tmp_path):
    cmd = _script(tmp_path, "veto.py",
                  "print('prod/ es intocable en este proyecto')\nraise SystemExit(2)\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "escribir_archivo(prod/*)", "comando": cmd, "bloqueante": True}]})
    pre = H.correr_pre("escribir_archivo", "prod/config.yaml | x", tmp_path)
    assert pre["permitido"] is False
    assert "prod/ es intocable" in pre["motivo"]
    assert pre["salidas"][0]["codigo"] == 2


def test_pre_bloqueante_no_matchea_deja_pasar(tmp_path):
    cmd = _script(tmp_path, "veto.py", "raise SystemExit(2)\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "escribir_archivo(prod/*)", "comando": cmd, "bloqueante": True}]})
    pre = H.correr_pre("escribir_archivo", "dev/config.yaml | x", tmp_path)
    assert pre["permitido"] is True and pre["salidas"] == []


def test_pre_no_bloqueante_que_falla_solo_registra(tmp_path):
    cmd = _script(tmp_path, "ruidoso.py", "print('me quejo')\nraise SystemExit(3)\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert pre["permitido"] is True and pre["motivo"] == ""
    assert pre["salidas"][0]["codigo"] == 3 and "me quejo" in pre["salidas"][0]["salida"]


def test_pre_bloqueante_ok_permite_y_corren_los_dos(tmp_path):
    ok = _script(tmp_path, "ok.py", "print('adelante')\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": ok, "bloqueante": True},
        {"match": "*", "comando": ok},
    ]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert pre["permitido"] is True and len(pre["salidas"]) == 2


def test_pre_bloqueo_corta_los_hooks_siguientes(tmp_path):
    veto = _script(tmp_path, "veto.py", "raise SystemExit(1)\n")
    testigo = tmp_path / "segundo.txt"
    segundo = _script(tmp_path, "segundo.py",
                      f"open(r'{testigo}', 'w', encoding='utf-8').write('x')\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": veto, "bloqueante": True},
        {"match": "*", "comando": segundo},
    ]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert pre["permitido"] is False and len(pre["salidas"]) == 1
    assert not testigo.exists()


def test_pre_bloqueante_que_agota_timeout_bloquea(tmp_path):
    cmd = _script(tmp_path, "lento.py", "import time\ntime.sleep(30)\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": cmd, "bloqueante": True}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path, timeout=1)
    assert pre["permitido"] is False
    assert pre["salidas"][0]["timeout"] is True
    assert "timeout" in pre["motivo"].lower()


def test_comando_inexistente_cuenta_como_fallo_del_hook(tmp_path):
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": "binario_que_no_existe_zzz --x", "bloqueante": True}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert pre["permitido"] is False and pre["salidas"][0]["codigo"] == 127


# ── correr_post: anexo y avisos ───────────────────────────────────────────────

def test_post_anexa_texto_al_resultado(tmp_path):
    cmd = _script(tmp_path, "fmt.py", "import sys\nprint('formateado:', sys.argv[1])\n")
    _escribir_config(tmp_path, {"post_tool": [
        {"match": "editar_archivo(*.py)", "comando": cmd + " {ruta}"}]})
    post = H.correr_post("editar_archivo", "cognia/x.py | contenido", "RESULTADO ok", tmp_path)
    assert "formateado: cognia/x.py" in post["anexo"]
    assert post["aviso"] == ""


def test_post_que_falla_avisa_pero_no_invalida(tmp_path):
    cmd = _script(tmp_path, "malo.py", "raise SystemExit(5)\n")
    _escribir_config(tmp_path, {"post_tool": [{"match": "*", "comando": cmd}]})
    post = H.correr_post("editar_archivo", "a.py", "RESULTADO ok", tmp_path)
    assert "exit 5" in post["aviso"]
    assert post["salidas"][0]["codigo"] == 5


def test_post_ve_el_resultado_por_entorno(tmp_path):
    cmd = _script(tmp_path, "leer_res.py",
                  "import os\nprint('vi:', os.environ['COGNIA_HOOK_RESULTADO'])\n")
    _escribir_config(tmp_path, {"post_tool": [{"match": "*", "comando": cmd}]})
    post = H.correr_post("editar_archivo", "a.py", "RESULTADO escribir_archivo: 3 lineas", tmp_path)
    assert "vi: RESULTADO escribir_archivo: 3 lineas" in post["anexo"]


# ── ejecucion: variables, cwd, stdin, tope de salida, shell ───────────────────

def test_sustitucion_de_variables(tmp_path):
    salida = tmp_path / "vars.txt"
    cmd = _script(tmp_path, "vars.py",
                  "import sys\n"
                  f"open(r'{salida}', 'w', encoding='utf-8').write('||'.join(sys.argv[1:]))\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": cmd + " {herramienta} {ruta} {raiz} {args}"}]})
    H.correr_pre("editar_archivo", "cognia/x.py | hola mundo", tmp_path)
    partes = salida.read_text(encoding="utf-8").split("||")
    assert partes[0] == "editar_archivo"
    assert partes[1] == "cognia/x.py"
    assert Path(partes[2]) == tmp_path
    # {args} entero viaja como UN solo argumento pese a tener espacios y '|'
    assert partes[3] == "cognia/x.py | hola mundo"


def test_valor_sustituido_no_se_vuelve_a_expandir(tmp_path):
    # Sustituir clave a clave dejaria que el VALOR de {args} aporte marcas: un
    # argumento con el texto "{raiz}" se expandiria en la segunda pasada y el
    # contenido de la llamada acabaria decidiendo la plantilla.
    argv, usa_shell = H._plan_comando("herr.exe {args}", {
        "herramienta": "t", "args": "hola {raiz} {ruta}", "ruta": "R.py", "raiz": "C:/SECRETO"})
    assert usa_shell is False
    assert argv == ["herr.exe", "hola {raiz} {ruta}"]


def test_entorno_del_hijo_apaga_los_hooks(tmp_path):
    # Guardia de recursion: un hook que invoque a Cognia no puede volver a
    # disparar hooks (bucle infinito de subprocesos).
    cmd = _script(tmp_path, "env.py",
                  "import os\nprint('HOOKS=' + os.environ.get('COGNIA_HOOKS', 'ausente'))\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert "HOOKS=0" in pre["salidas"][0]["salida"]


def test_timeout_ausente_usa_el_default_no_un_segundo(tmp_path):
    # `timeout=None` significa "el default (30 s)", no "matalo cuanto antes":
    # con el clamp a _TIMEOUT_MIN este hook de 2 s moriria por timeout.
    cmd = _script(tmp_path, "dos_seg.py", "import time\ntime.sleep(2)\nprint('vivo')\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path, timeout=None)
    assert pre["salidas"][0]["timeout"] is False
    assert "vivo" in pre["salidas"][0]["salida"]


def test_timeout_basura_no_revienta(tmp_path):
    cmd = _script(tmp_path, "ok.py", "print('ok')\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path, timeout="treinta")
    assert pre["salidas"][0]["codigo"] == 0


def test_ruta_con_acentos_viaja_entera(tmp_path):
    cmd = _script(tmp_path, "eco.py", "import sys\nprint('recibi:', sys.argv[1])\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd + " {ruta}"}]})
    pre = H.correr_pre("editar_archivo", {"ruta": "documentación/año/ñu.py"}, tmp_path)
    assert "recibi: documentación/año/ñu.py" in pre["salidas"][0]["salida"]


@pytest.mark.parametrize("codec", ["utf-8", "cp1252"])
def test_salida_del_hook_se_decodifica_en_su_codificacion(tmp_path, codec):
    # Un hook que escribe en la pagina de codigos de Windows (cualquier Python
    # sin PYTHONUTF8, o una herramienta vieja) daba 'cami�n' al decodificar
    # todo como UTF-8: el motivo del bloqueo llegaba roto al usuario.
    cmd = _script(tmp_path, "acentos.py",
                  "import sys\n"
                  f"sys.stdout.buffer.write('prohibido: camión ñandú'.encode({codec!r}))\n"
                  "raise SystemExit(1)\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": cmd, "bloqueante": True}]})
    pre = H.correr_pre("escribir_archivo", "a.py", tmp_path)
    assert pre["permitido"] is False
    assert "prohibido: camión ñandú" in pre["motivo"]


def test_ruta_vacia_no_deja_argumento_fantasma(tmp_path):
    salida = tmp_path / "argc.txt"
    cmd = _script(tmp_path, "argc.py",
                  "import sys\n"
                  f"open(r'{salida}', 'w', encoding='utf-8').write(str(len(sys.argv) - 1))\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd + " {ruta}"}]})
    H.correr_pre("pensar", "no hay rutas aqui", tmp_path)
    assert salida.read_text(encoding="utf-8") == "0"


def test_cwd_es_la_raiz_del_proyecto(tmp_path):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    cmd = _script(proyecto, "cwd.py", "import os\nprint(os.getcwd())\n")
    _escribir_config(proyecto, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", proyecto)
    assert Path(pre["salidas"][0]["salida"].strip()).resolve() == proyecto.resolve()


def test_stdin_no_se_hereda(tmp_path):
    # Sin DEVNULL esto colgaria la sesion entera; con DEVNULL lee EOF y termina.
    cmd = _script(tmp_path, "lee_stdin.py",
                  "import sys\nprint('leido:', repr(sys.stdin.read()))\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path, timeout=10)
    assert pre["salidas"][0]["codigo"] == 0
    assert "leido: ''" in pre["salidas"][0]["salida"]


def test_salida_gigante_se_recorta(tmp_path):
    cmd = _script(tmp_path, "verborragico.py", "print('x' * 50000)\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    salida = pre["salidas"][0]["salida"]
    assert len(salida) < H.TOPE_SALIDA + 200
    assert "omitidos" in salida


def test_comando_simple_no_usa_shell_y_con_pipe_si(tmp_path):
    argv, usa_shell = H._plan_comando('"C:\\py\\python.exe" fmt.py {ruta}', {
        "herramienta": "editar_archivo", "args": "a b", "ruta": "un dir/x.py", "raiz": "R"})
    assert usa_shell is False
    assert argv == ["C:\\py\\python.exe", "fmt.py", "un dir/x.py"]   # espacios sin romper argv
    _, con_pipe = H._plan_comando("ruff format {ruta} | tee log.txt", {
        "herramienta": "t", "args": "", "ruta": "x.py", "raiz": "R"})
    assert con_pipe is True


def test_valor_con_metacaracteres_no_inyecta_en_modo_argv(tmp_path):
    intruso = tmp_path / "intruso.txt"
    salida = tmp_path / "recibido.txt"
    cmd = _script(tmp_path, "eco.py",
                  "import sys\n"
                  f"open(r'{salida}', 'w', encoding='utf-8').write(sys.argv[1])\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd + " {ruta}"}]})
    veneno = f'a.py; echo pwned > "{intruso}"'
    H.correr_pre("editar_archivo", {"ruta": veneno}, tmp_path)
    # El valor llega ENTERO como un unico argv[1]: no hay shell que lo interprete.
    assert not intruso.exists()
    assert salida.read_text(encoding="utf-8") == veneno


def test_shell_true_con_redireccion_funciona(tmp_path):
    destino = tmp_path / "redirigido.txt"
    cmd = _script(tmp_path, "saluda.py", "print('hola shell')\n")
    _escribir_config(tmp_path, {"pre_tool": [
        {"match": "*", "comando": f'{cmd} > "{destino}"'}]})
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path)
    assert pre["salidas"][0]["shell"] is True
    assert "hola shell" in destino.read_text(encoding="utf-8")


def test_config_precargada_se_reutiliza(tmp_path):
    cmd = _script(tmp_path, "ok.py", "print('ok')\n")
    _escribir_config(tmp_path, {"pre_tool": [{"match": "*", "comando": cmd}]})
    cfg = H.cargar(tmp_path)
    (tmp_path / ".cognia" / "hooks.json").unlink()   # el fichero ya no esta...
    pre = H.correr_pre("editar_archivo", "a.py", tmp_path, config=cfg)
    assert len(pre["salidas"]) == 1                  # ...y aun asi corre la config dada
