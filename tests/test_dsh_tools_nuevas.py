# -*- coding: utf-8 -*-
"""Regresion de las tools que le faltaban al agente (2026-08-18).

Tres huecos que cualquier harness de programacion da por sentados y este no
tenia:

  1. EJECUCION EN SEGUNDO PLANO. `ejecutar` es bloqueante y muere a los 600s:
     un servidor, un build largo o un watcher eran imposibles. Tools nuevas:
     ejecutar_fondo / ver_salida / matar_proceso / procesos, sobre la
     infraestructura que ya existia para el humano (console/proc_registry.py).
  2. GIT ESCRIBIBLE Y DIFF DE VERDAD. Las tres tools git eran de solo lectura y
     git_diff mostraba --stat: el agente no podia revisar su propio cambio
     linea a linea. Ahora git_diff trae el PATCH, y hay git_add / git_commit /
     git_branch / git_stash. Nunca push, nunca reset --hard, nunca --force.
  3. EL PAQUETE BASICO: mover_archivo, crear_directorio, buscar_ficheros
     (glob de primera clase), leer_lote y el parametro cwd de la ejecucion.

Cada test falla sin su tool (con la tool ausente, run_tool devuelve el mensaje
de "no existe" y la postcondicion — el archivo movido, el commit creado, el
patch con sus hunks — no se cumple). Los tests de git usan un repo de VERDAD
creado con `git init` en tmp_path: cero mocks.
"""
import subprocess
import sys
import time

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Workspace del agente = tmp_path (mismo patron que test_agent_tools)."""
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def lanzados():
    """Ids de procesos lanzados en el test; se matan al terminar aunque falle."""
    ids = []
    yield ids
    from cognia.console.proc_registry import kill_shell
    for sid in ids:
        try:
            kill_shell(sid)
        except Exception:
            pass


def _id_de(salida: str) -> int:
    """El id que devolvio ejecutar_fondo."""
    assert "id=" in salida, salida
    return int(salida.split("id=")[1].split()[0].rstrip(")."))


def _esperar(cond, seg=15.0) -> bool:
    fin = time.time() + seg
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _py(codigo: str) -> str:
    """Comando que corre `codigo` con ESTE interprete (nunca 'python' pelado:
    el del PATH puede ser el venv roto del repo).

    OJO con los ';' dentro del codigo: el sentinel parte el comando por ';' y
    '&&' para cazar encadenados, asi que un 'import time; time.sleep(1)' se
    reclasifica a CONFIRM y no llega a correr (comportamiento previo y
    correcto). Por eso los comandos de aqui usan __import__/exec en vez de
    puntos y coma."""
    return f'"{sys.executable}" -c "{codigo}"'


# Codigo de los procesos de prueba, sin ';' (ver _py) y con comillas simples
# para no pelear con el entrecomillado de la linea de comandos de Windows.
_DORMIR = "__import__('time').sleep({})"
_CWD = "print(__import__('os').getcwd())"


# ══════════════════════════════════════════════════════════════════════
# 1. EJECUCION EN SEGUNDO PLANO
# ══════════════════════════════════════════════════════════════════════

def test_ejecutar_fondo_devuelve_enseguida_y_el_proceso_sigue_vivo(lanzados):
    """Lo que `ejecutar` no puede hacer: volver ANTES de que el comando acabe."""
    from cognia.console.proc_registry import get_info
    t0 = time.time()
    out = T.run_tool("ejecutar_fondo", _py(_DORMIR.format(20)), _ctx())
    tardo = time.time() - t0
    sid = _id_de(out)
    lanzados.append(sid)
    assert tardo < 5, f"ejecutar_fondo bloqueo {tardo:.1f}s"
    assert get_info(sid)["status"] == "running"
    # el resultado NOMBRA a sus companeras: asi se descubren sin gastar una
    # linea del catalogo del prompt
    assert "ver_salida" in out and "matar_proceso" in out


def test_ver_salida_devuelve_la_salida_acumulada(lanzados):
    codigo = "exec('import time\\nfor i in range(30):\\n print(chr(76)+str(i))\\n time.sleep(0.1)')"
    out = T.run_tool("ejecutar_fondo", _py(codigo), _ctx())
    sid = _id_de(out)
    lanzados.append(sid)
    assert _esperar(lambda: "L3" in T.run_tool("ver_salida", str(sid), _ctx())), \
        T.run_tool("ver_salida", str(sid), _ctx())
    vista = T.run_tool("ver_salida", str(sid), _ctx())
    assert "L0" in vista and "CORRIENDO" in vista
    # lineas=N acota a la cola
    corta = T.run_tool("ver_salida", f"{sid} | lineas=2", _ctx())
    assert corta.count("L") <= 3, corta


def test_ver_salida_avisa_cuando_recorta(monkeypatch, lanzados):
    """Un truncado silencioso haria concluir al agente sobre una salida que no vio."""
    monkeypatch.setattr(T, "_VER_SALIDA_CAP", 40)
    out = T.run_tool("ejecutar_fondo",
                     _py("exec('for i in range(200): print(chr(76)*20)')"), _ctx())
    sid = _id_de(out)
    lanzados.append(sid)
    from cognia.console.proc_registry import get_info
    assert _esperar(lambda: get_info(sid)["status"] != "running")
    vista = T.run_tool("ver_salida", str(sid), _ctx())
    assert "recortados" in vista, vista


def test_ver_salida_id_inexistente_no_finge(lanzados):
    out = T.run_tool("ver_salida", "999999", _ctx())
    assert "ERROR" in out and "999999" in out


def test_matar_proceso_termina_de_verdad(lanzados):
    from cognia.console.proc_registry import get_info
    out = T.run_tool("ejecutar_fondo", _py(_DORMIR.format(60)), _ctx())
    sid = _id_de(out)
    lanzados.append(sid)
    assert get_info(sid)["status"] == "running"
    res = T.run_tool("matar_proceso", str(sid), _ctx())
    assert "ERROR" not in res, res
    assert _esperar(lambda: get_info(sid)["status"] != "running"), get_info(sid)


def test_matar_proceso_no_miente_si_el_proceso_sobrevive(monkeypatch, lanzados):
    """kill_shell devuelve el estado REAL; la tool tiene que DECIRLO.

    Se fuerza el False (un proceso que sobrevive a terminate+kill no se puede
    fabricar de forma determinista: hace falta uno elevado o colgado en E/S del
    kernel). Lo que se prueba es la unica parte que es codigo nuestro: que un
    False NO se presente como 'proceso terminado'.
    """
    import cognia.console.proc_registry as pr
    out = T.run_tool("ejecutar_fondo", _py(_DORMIR.format(60)), _ctx())
    sid = _id_de(out)
    lanzados.append(sid)
    monkeypatch.setattr(pr, "kill_shell", lambda _id: False)
    res = T.run_tool("matar_proceso", str(sid), _ctx())
    assert "ERROR" in res and "SIGUE VIVO" in res, res


def test_procesos_lista_lo_lanzado(lanzados):
    out = T.run_tool("ejecutar_fondo", _py(_DORMIR.format(20)), _ctx())
    sid = _id_de(out)
    lanzados.append(sid)
    listado = T.run_tool("procesos", "", _ctx())
    assert f"id={sid}" in listado and "running" in listado


def test_ejecutar_fondo_respeta_el_gate_de_seguridad(lanzados):
    """El background no puede ser el agujero por el que pasa lo que el
    sentinel frena en primer plano."""
    out = T.run_tool("ejecutar_fondo", "rm -rf /", _ctx())
    assert "BLOQUEADO" in out, out
    assert "id=" not in out


# ══════════════════════════════════════════════════════════════════════
# 2. GIT (repo de verdad, sin mocks)
# ══════════════════════════════════════════════════════════════════════

def _git_raw(cwd, *args):
    r = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"git {args}: {r.stdout}{r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo git REAL con un commit base, y el cwd puesto dentro."""
    r = tmp_path / "repo"
    r.mkdir()
    _git_raw(r, "init", "-q")
    _git_raw(r, "config", "user.email", "test@cognia.local")
    _git_raw(r, "config", "user.name", "test")
    (r / "m.py").write_text("x = 1\n", encoding="utf-8")
    _git_raw(r, "add", "m.py")
    _git_raw(r, "commit", "-q", "-m", "base")
    monkeypatch.chdir(r)
    return r


def test_git_diff_trae_el_patch_no_solo_el_stat(repo):
    """El ciclo edito -> REVISO el diff -> commiteo: con --stat era imposible."""
    (repo / "m.py").write_text("x = 2\ny = 3\n", encoding="utf-8")
    out = T.run_tool("git_diff", "", _ctx())
    assert "@@" in out, out            # hunk header: no existe en --stat
    assert "-x = 1" in out and "+x = 2" in out, out


def test_git_diff_stat_y_staged_siguen_disponibles(repo):
    (repo / "m.py").write_text("x = 2\n", encoding="utf-8")
    stat = T.run_tool("git_diff", "| stat", _ctx())
    assert "1 file changed" in stat and "@@" not in stat, stat
    _git_raw(repo, "add", "m.py")
    # ya en el indice: el diff normal esta vacio y el de staged trae el patch
    assert "sin cambios" in T.run_tool("git_diff", "", _ctx())
    assert "@@" in T.run_tool("git_diff", "| staged", _ctx())


def test_git_diff_no_pasa_por_aci_trim(repo, monkeypatch):
    """Un diff largo NO se puede recortar por el medio: el modelo copia lo que
    ve en bloques SEARCH. Por eso git_diff esta en ACI_EXENTAS."""
    assert "git_diff" in T.ACI_EXENTAS
    (repo / "m.py").write_text("\n".join(f"linea {i}" for i in range(400)),
                               encoding="utf-8")
    out = T.run_tool("git_diff", "", _ctx())
    assert len(out) > T._ACI_CAP, (len(out), T._ACI_CAP)
    assert "cabeza+cola" not in out and "omitidos (tope" not in out


def test_git_add_pone_los_cambios_en_el_indice(repo):
    (repo / "nuevo.py").write_text("z = 0\n", encoding="utf-8")
    out = T.run_tool("git_add", "nuevo.py", _ctx())
    assert "ERROR" not in out, out
    assert "nuevo.py" in _git_raw(repo, "diff", "--cached", "--name-only")


def test_git_add_exige_una_ruta(repo):
    out = T.run_tool("git_add", "", _ctx())
    assert "ERROR" in out and "ruta" in out


def test_git_commit_crea_el_commit_y_exige_mensaje(repo):
    (repo / "m.py").write_text("x = 9\n", encoding="utf-8")
    T.run_tool("git_add", "m.py", _ctx())
    assert "ERROR" in T.run_tool("git_commit", "   ", _ctx())
    out = T.run_tool("git_commit", "sube x a 9", _ctx())
    assert "ERROR" not in out, out
    assert "sube x a 9" in _git_raw(repo, "log", "--oneline", "-1")


def test_git_commit_sin_nada_en_el_indice_lo_dice(repo):
    out = T.run_tool("git_commit", "commit vacio", _ctx())
    assert "ERROR" in out and "git_add" in out, out


def test_git_branch_lista_y_crea(repo):
    listado = T.run_tool("git_branch", "", _ctx())
    assert "*" in listado, listado
    out = T.run_tool("git_branch", "feature/nueva", _ctx())
    assert "ERROR" not in out, out
    assert _git_raw(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature/nueva"


def test_git_branch_rechaza_un_nombre_con_metacaracteres(repo):
    """El argumento viene del modelo: 'x; git push --force' no puede colarse."""
    out = T.run_tool("git_branch", "x; git push --force", _ctx())
    assert "ERROR" in out
    assert "feature" not in _git_raw(repo, "branch", "--list")


def test_git_stash_guarda_y_recupera(repo):
    (repo / "m.py").write_text("x = 77\n", encoding="utf-8")
    out = T.run_tool("git_stash", "", _ctx())
    assert "ERROR" not in out, out
    assert (repo / "m.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "ERROR" not in T.run_tool("git_stash", "pop", _ctx())
    assert (repo / "m.py").read_text(encoding="utf-8") == "x = 77\n"


def test_git_stash_no_deja_tirar_trabajo(repo):
    out = T.run_tool("git_stash", "drop", _ctx())
    assert "ERROR" in out and "drop" in out


def test_no_hay_tool_de_push_ni_de_reset(repo):
    """Publicar y destruir historia siguen siendo del humano."""
    assert not [n for n in T.TOOLS if "push" in n or "reset" in n]
    # y el sentinel sigue bloqueando el camino largo (ejecutar)
    assert "BLOQUEADO" in T.run_tool("ejecutar", "git reset --hard HEAD~1", _ctx())


# ══════════════════════════════════════════════════════════════════════
# 3. EL PAQUETE BASICO
# ══════════════════════════════════════════════════════════════════════

def test_mover_archivo_mueve_y_borra_el_origen(workspace):
    src = workspace / "viejo.txt"
    src.write_text("contenido", encoding="utf-8")
    out = T.run_tool("mover_archivo",
                     f"{src} | {workspace / 'sub' / 'nuevo.txt'}", _ctx())
    assert "ERROR" not in out, out
    assert not src.exists()
    assert (workspace / "sub" / "nuevo.txt").read_text(encoding="utf-8") == "contenido"


def test_mover_archivo_a_un_directorio_existente_conserva_el_nombre(workspace):
    src = workspace / "dato.txt"
    src.write_text("x", encoding="utf-8")
    (workspace / "destino").mkdir()
    T.run_tool("mover_archivo", f"{src} | {workspace / 'destino'}", _ctx())
    assert (workspace / "destino" / "dato.txt").exists()


def test_mover_archivo_confinado_al_workspace(workspace, tmp_path):
    src = workspace / "a.txt"
    src.write_text("x", encoding="utf-8")
    fuera = tmp_path.parent / "fuera_del_workspace.txt"
    out = T.run_tool("mover_archivo", f"{src} | {fuera}", _ctx())
    assert "ERROR" in out, out
    assert src.exists() and not fuera.exists()


def test_crear_directorio_crea_los_intermedios(workspace):
    out = T.run_tool("crear_directorio", str(workspace / "a" / "b" / "c"), _ctx())
    assert "ERROR" not in out, out
    assert (workspace / "a" / "b" / "c").is_dir()
    # idempotente: repetirlo no es un error
    assert "ya existia" in T.run_tool("crear_directorio",
                                      str(workspace / "a" / "b" / "c"), _ctx())


def test_buscar_ficheros_encuentra_por_nombre(workspace):
    """El glob como pregunta de primera clase: dentro de `buscar` era un
    fallback que solo corria si el scan por CONTENIDO no devolvia nada — y
    aqui devuelve algo (el nombre esta citado en el README), asi que por ese
    camino el fichero no aparecia nunca."""
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "config.json").write_text("{}", encoding="utf-8")
    (workspace / "README.md").write_text("mira config.json", encoding="utf-8")
    out = T.run_tool("buscar_ficheros", f"config.json | {workspace}", _ctx())
    assert "pkg/config.json" in out.replace("\\", "/"), out
    # y el glob real tambien
    assert "pkg/config.json" in T.run_tool(
        "buscar_ficheros", f"*.json | {workspace}", _ctx()).replace("\\", "/")


def test_buscar_ficheros_sin_resultados_no_confunde_con_buscar(workspace):
    out = T.run_tool("buscar_ficheros", f"*.rs | {workspace}", _ctx())
    assert "ningun archivo" in out and "buscar" in out


def test_leer_lote_lee_varios_en_una_llamada(workspace):
    for n in ("uno.py", "dos.py", "tres.py"):
        (workspace / n).write_text(f"# soy {n}\n", encoding="utf-8")
    args = " | ".join(str(workspace / n) for n in ("uno.py", "dos.py", "tres.py"))
    out = T.run_tool("leer_lote", args, _ctx())
    for n in ("uno.py", "dos.py", "tres.py"):
        assert f"# soy {n}" in out, out


def test_leer_lote_reporta_lo_que_falta_sin_tumbar_el_resto(workspace):
    (workspace / "hay.py").write_text("ok = 1\n", encoding="utf-8")
    out = T.run_tool("leer_lote",
                     f"{workspace / 'hay.py'} | {workspace / 'no_hay.py'}", _ctx())
    assert "ok = 1" in out
    assert "no existe" in out


def test_leer_lote_tiene_tope_de_ficheros(workspace):
    rutas = []
    for i in range(12):
        p = workspace / f"f{i}.txt"
        p.write_text(str(i), encoding="utf-8")
        rutas.append(str(p))
    out = T.run_tool("leer_lote", " | ".join(rutas), _ctx())
    assert "se ignoraron 4 rutas" in out, out


def test_ejecutar_acepta_cwd(workspace):
    """Sin el parametro habia que prefijar 'cd ... &&' — que ademas el sentinel
    reclasifica a CONFIRM por ser un encadenado."""
    out = T.run_tool(
        "ejecutar",
        f'"{sys.executable}" -c "{_CWD}" | cwd={workspace}',
        _ctx())
    assert str(workspace).lower() in out.lower(), out


def test_ejecutar_con_cwd_inexistente_dice_que_es_el_cwd(workspace):
    out = T.run_tool("ejecutar",
                     f'"{sys.executable}" -c "print(1)" | cwd={workspace / "no_existe"}',
                     _ctx())
    assert "ERROR" in out and "cwd" in out, out


def test_ejecutar_con_timeout_y_cwd_juntos(workspace):
    """armar_args (tool-calling nativo) pone las dos claves; el parser tiene que
    entender las dos, en cualquier orden."""
    args = T.armar_args("ejecutar", {"comando": 'echo hola',
                                     "timeout": 45, "cwd": str(workspace)})
    cmd, timeout, cwd = T._partir_ejec(args)
    assert (cmd, timeout, cwd) == ("echo hola", 45, str(workspace))


# ══════════════════════════════════════════════════════════════════════
# PRESUPUESTO DE ATENCION: el catalogo anunciado crece en UNA sola tool
# ══════════════════════════════════════════════════════════════════════

def test_core_tools_solo_crece_con_ejecutar_fondo():
    """El A/B del repo (2026-07-25) midio que un catalogo de 46 tools baja el
    camino feliz de 4.25/5 a 2.5/5. De las 12 tools nuevas solo entra la que
    habilita algo IMPOSIBLE hoy; las demas son atajos de algo ya posible."""
    assert "ejecutar_fondo" in T.CORE_TOOLS
    nuevas = {"ver_salida", "matar_proceso", "procesos", "git_add", "git_commit",
              "git_branch", "git_stash", "mover_archivo", "crear_directorio",
              "buscar_ficheros", "leer_lote"}
    assert not (nuevas & T.CORE_TOOLS), nuevas & T.CORE_TOOLS
    assert len(T.CORE_TOOLS) == 14


def test_las_tools_nuevas_siguen_siendo_invocables_fuera_del_core():
    """No estar en CORE_TOOLS es dejar de ANUNCIARSE, no dejar de existir:
    run_tool no filtra por el catalogo."""
    from cognia.simple_mode import visible_tools
    vis = visible_tools(set(T.TOOLS), override="sencillo")
    assert "procesos" not in vis and "leer_lote" not in vis
    assert "ejecutar_fondo" in vis
    for n in ("procesos", "leer_lote", "git_add"):
        assert n in T.TOOLS
