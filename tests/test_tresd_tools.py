# -*- coding: utf-8 -*-
"""Tests de tresd_tools + triposr_backend + shim del CLI (ola 1, CPU puro).

Que cubren (cada uno falla sin su pieza):
- triposr_backend: tresd_disponible (vendor/python/deps ausentes -> motivo
  accionable), generar_malla con subprocess mockeado (comando exacto, JSON
  parseado, stdout contaminado, exit != 0, ok:false, timeout mata y reporta,
  formato/salida incoherentes).
- CLI: instalar_shim_torchmcubes inyecta el modulo en sys.modules ANTES de
  cualquier import de tsr (idempotente, importable); cargar_imagen aplana
  RGBA sobre gris y avisa por stderr sin alfa (solo si PIL esta).
- tresd_generar (tool): registro manual, parseo de opciones k=v, rutas y
  extensiones malas -> ERROR legible (nunca excepcion), backend no
  disponible -> motivo visible SIN reservar VRAM, gate mockeado (pide rol
  'tresd' 4000 y suelta en finally INCLUSO con excepcion), nombre md5
  estable bajo <workspace>/tresd/, fallback sin _backend_gate con aviso.
- flag apagado: la tool no corre sin COGNIA_3D_TOOLS (asercion condicional
  hasta que la ola 2 cablee el prefijo).

Sin GPU, sin red, sin descargas: todo subprocess/backend esta mockeado.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from cognia.tresd import triposr_backend as tb
from cognia.agent import tresd_tools

_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / "scripts" / "tresd_generar_cli.py"


# ── helpers ────────────────────────────────────────────────────────────────

def _png(tmp_path: Path, nombre: str = "obj.png") -> Path:
    """PNG minimo en disco (el contenido no se decodifica: CLI mockeado)."""
    p = tmp_path / nombre
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return p


def _vendor_falso(tmp_path: Path, monkeypatch) -> Path:
    """Arma vendor TripoSR + python GPU falsos y apunta los env a ellos."""
    vendor = tmp_path / "TripoSR"
    (vendor / "tsr").mkdir(parents=True)
    (vendor / "tsr" / "system.py").write_text("# fake", encoding="utf-8")
    py = tmp_path / "venvgpu" / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_bytes(b"MZ")
    monkeypatch.setenv("COGNIA_TRIPOSR_SRC", str(vendor))
    monkeypatch.setenv("COGNIA_GPU_PYTHON", str(py))
    return vendor


class _ProcFalso:
    """Doble de subprocess.Popen que devuelve stdout/stderr fijos."""

    def __init__(self, out="", err="", rc=0, expira=False):
        self.out, self.err, self.returncode = out, err, rc
        self._expira = expira
        self.matado = False

    def communicate(self, timeout=None):
        if self._expira and not self.matado:
            raise subprocess.TimeoutExpired(cmd="cli", timeout=timeout or 0)
        return self.out, self.err

    def kill(self):
        self.matado = True


def _popen_falso(monkeypatch, proc):
    """Intercepta Popen del backend y captura el comando lanzado."""
    visto = {}

    def fake_popen(cmd, **kw):
        visto["cmd"] = cmd
        visto["kw"] = kw
        return proc

    monkeypatch.setattr(tb.subprocess, "Popen", fake_popen)
    return visto


def _registrar():
    """Registra tresd_tools con un decorador de mentira; devuelve registry."""
    tools = {}

    def tool(name, doc, danger=False, desc="", params=None):
        def deco(fn):
            tools[name] = {"fn": fn, "doc": doc}
            return fn
        return deco

    tresd_tools.register(tool)
    return tools


def _gate_falso(monkeypatch, *, ok=True, motivo=""):
    """cognia.agent._backend_gate falso en sys.modules; espia las llamadas."""
    llamadas = []
    mod = types.ModuleType("cognia.agent._backend_gate")

    def pedir_backend(rol, mib):
        llamadas.append(("pedir", rol, mib))
        return ok, "", motivo

    def soltar_backend(rol):
        llamadas.append(("soltar", rol, None))

    mod.pedir_backend = pedir_backend
    mod.soltar_backend = soltar_backend
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", mod)
    return llamadas


def _backend_ok(monkeypatch, resultado=None, explota=None):
    """tresd_disponible -> ok y generar_malla mockeada en cognia.tresd."""
    import cognia.tresd as ct
    monkeypatch.setattr(ct, "tresd_disponible", lambda: (True, ""))
    visto = {}

    def fake_generar(imagen, salida, *, formato="glb", resolucion=256,
                     timeout=600):
        visto.update(imagen=imagen, salida=salida, formato=formato,
                     resolucion=resolucion)
        if explota is not None:
            raise explota
        return resultado or {"ruta": salida, "verts": 100, "caras": 200,
                             "seg": 12.3}

    monkeypatch.setattr(ct, "generar_malla", fake_generar)
    return visto


# ── triposr_backend: tresd_disponible ──────────────────────────────────────

def test_disponible_sin_vendor_motivo_accionable(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TRIPOSR_SRC", str(tmp_path / "no_esta"))
    ok, motivo = tb.tresd_disponible()
    assert not ok
    assert "COGNIA_TRIPOSR_SRC" in motivo and "TripoSR" in motivo


def test_disponible_sin_python_gpu(tmp_path, monkeypatch):
    _vendor_falso(tmp_path, monkeypatch)
    monkeypatch.setenv("COGNIA_GPU_PYTHON", str(tmp_path / "no_python.exe"))
    ok, motivo = tb.tresd_disponible()
    assert not ok and "python GPU" in motivo


def test_disponible_ok_con_vendor_y_python(tmp_path, monkeypatch):
    # El venv falso no tiene Lib/site-packages -> el chequeo de deps se salta
    # (no se puede verificar barato; no bloquea por eso).
    _vendor_falso(tmp_path, monkeypatch)
    assert tb.tresd_disponible() == (True, "")


def test_disponible_detecta_dep_faltante(tmp_path, monkeypatch):
    _vendor_falso(tmp_path, monkeypatch)
    py = Path(tmp_path / "venvgpu" / "Scripts" / "python.exe")
    site = py.parent.parent / "Lib" / "site-packages"
    (site / "torch").mkdir(parents=True)
    (site / "torch" / "__init__.py").write_text("", encoding="utf-8")
    # torch esta pero skimage no -> motivo con el pip exacto
    ok, motivo = tb.tresd_disponible()
    assert not ok and "skimage" in motivo and "scikit-image" in motivo


# ── triposr_backend: generar_malla (subprocess mockeado) ───────────────────

def test_generar_malla_comando_y_json(tmp_path, monkeypatch):
    img = _png(tmp_path)
    salida = tmp_path / "malla.glb"
    monkeypatch.setenv("COGNIA_GPU_PYTHON", r"C:\gpu\python.exe")
    out = json.dumps({"ok": True, "ruta": str(salida), "verts": 5000,
                      "caras": 9000, "seg": 33.2})
    visto = _popen_falso(monkeypatch, _ProcFalso(out=out))
    r = tb.generar_malla(str(img), str(salida), formato="glb",
                         resolucion=128, timeout=99)
    assert r == {"ruta": str(salida), "verts": 5000, "caras": 9000,
                 "seg": 33.2}
    cmd = visto["cmd"]
    assert cmd[0] == r"C:\gpu\python.exe"
    assert cmd[1].endswith("tresd_generar_cli.py")
    assert cmd[cmd.index("--imagen") + 1] == str(img.resolve())
    assert cmd[cmd.index("--salida") + 1] == str(salida.resolve())
    assert cmd[cmd.index("--formato") + 1] == "glb"
    assert cmd[cmd.index("--resolucion") + 1] == "128"


def test_generar_malla_usa_ultima_linea_json(tmp_path, monkeypatch):
    """Progreso escapado antes del JSON no rompe el contrato (ultima linea)."""
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    out = ("algo que se escapo del redirect\n"
           + json.dumps({"ok": True, "ruta": str(salida), "verts": 1,
                         "caras": 1, "seg": 0.5}))
    _popen_falso(monkeypatch, _ProcFalso(out=out))
    assert tb.generar_malla(str(img), str(salida))["verts"] == 1


def test_generar_malla_stdout_contaminado(tmp_path, monkeypatch):
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    _popen_falso(monkeypatch, _ProcFalso(out="Loading checkpoint shards..."))
    with pytest.raises(RuntimeError, match="contaminado"):
        tb.generar_malla(str(img), str(salida))


def test_generar_malla_exit_code_con_stderr(tmp_path, monkeypatch):
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    _popen_falso(monkeypatch,
                 _ProcFalso(out="", err="CUDA out of memory", rc=1))
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        tb.generar_malla(str(img), str(salida))


def test_generar_malla_exit_code_prefiere_error_json(tmp_path, monkeypatch):
    """El CLI reporta su fallo como JSON incluso con exit != 0."""
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    out = json.dumps({"ok": False, "error": "no pude cargar TripoSR"})
    _popen_falso(monkeypatch, _ProcFalso(out=out, err="traceback...", rc=1))
    with pytest.raises(RuntimeError, match="no pude cargar TripoSR"):
        tb.generar_malla(str(img), str(salida))


def test_generar_malla_ok_false(tmp_path, monkeypatch):
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    _popen_falso(monkeypatch, _ProcFalso(
        out=json.dumps({"ok": False, "error": "malla vacia"})))
    with pytest.raises(RuntimeError, match="malla vacia"):
        tb.generar_malla(str(img), str(salida))


def test_generar_malla_timeout_mata_y_reporta(tmp_path, monkeypatch):
    img, salida = _png(tmp_path), tmp_path / "m.glb"
    proc = _ProcFalso(expira=True)
    _popen_falso(monkeypatch, proc)
    with pytest.raises(RuntimeError, match="timeout tras 5s"):
        tb.generar_malla(str(img), str(salida), timeout=5)
    assert proc.matado    # jamas cuelga: el hijo muere con kill()


def test_generar_malla_validaciones(tmp_path, monkeypatch):
    img = _png(tmp_path)
    _popen_falso(monkeypatch, _ProcFalso(out="{}"))
    with pytest.raises(RuntimeError, match="no existe la imagen"):
        tb.generar_malla(str(tmp_path / "nada.png"), str(tmp_path / "m.glb"))
    with pytest.raises(RuntimeError, match="formato 'stl' no soportado"):
        tb.generar_malla(str(img), str(tmp_path / "m.stl"), formato="stl")
    # salida .glb con formato obj: incoherencia visible, no malla mentirosa
    with pytest.raises(RuntimeError, match="no termina en .obj"):
        tb.generar_malla(str(img), str(tmp_path / "m.glb"), formato="obj")


# ── CLI: shim torchmcubes + carga de imagen ────────────────────────────────

def _cargar_cli():
    spec = importlib.util.spec_from_file_location("tresd_generar_cli", _CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_shim_torchmcubes_se_inyecta_en_sys_modules(monkeypatch):
    cli = _cargar_cli()
    monkeypatch.delitem(sys.modules, "torchmcubes", raising=False)
    cli.instalar_shim_torchmcubes()
    try:
        assert "torchmcubes" in sys.modules
        import torchmcubes
        assert callable(torchmcubes.marching_cubes)
        # Idempotente: una segunda llamada no reemplaza el modulo (si tsr ya
        # capturo la referencia, cambiarla seria un bug silencioso).
        antes = sys.modules["torchmcubes"]
        cli.instalar_shim_torchmcubes()
        assert sys.modules["torchmcubes"] is antes
    finally:
        sys.modules.pop("torchmcubes", None)


def test_shim_marching_cubes_esfera():
    """Contrato del shim con torch+skimage reales (skip si el venv no los
    tiene: el shim corre en venv312gpu, este test es oportunista)."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("skimage")
    cli = _cargar_cli()
    sys.modules.pop("torchmcubes", None)
    try:
        cli.instalar_shim_torchmcubes()
        import torchmcubes
        n = 24
        ejes = torch.linspace(-1, 1, n)
        x, y, z = torch.meshgrid(ejes, ejes, ejes, indexing="ij")
        campo = 0.6 - (x ** 2 + y ** 2 + z ** 2).sqrt()   # esfera r=0.6
        v, f = torchmcubes.marching_cubes(campo, 0.0)
        assert v.dtype == torch.float32 and f.dtype == torch.int64
        assert len(v) > 0 and len(f) > 0
        assert v.min() >= 0 and v.max() <= n - 1   # coordenadas de voxel
    finally:
        sys.modules.pop("torchmcubes", None)


def test_cargar_imagen_rgba_aplana_sobre_gris(tmp_path, capsys):
    Image = pytest.importorskip("PIL.Image")
    cli = _cargar_cli()
    p = tmp_path / "rgba.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 0)).save(p)   # todo transparente
    img = cli.cargar_imagen(str(p))
    assert img.mode == "RGB"
    assert img.getpixel((8, 8)) == (127, 127, 127)   # gris 0.5, no rojo


def test_cargar_imagen_sin_alfa_avisa(tmp_path, capsys):
    Image = pytest.importorskip("PIL.Image")
    cli = _cargar_cli()
    p = tmp_path / "rgb.png"
    Image.new("RGB", (2048, 1024), (10, 20, 30)).save(p)
    img = cli.cargar_imagen(str(p))
    assert img.mode == "RGB"
    assert max(img.size) <= 512          # acotada, proporcion conservada
    assert "no tiene canal alfa" in capsys.readouterr().err


# ── tool tresd_generar: registro y parseo ──────────────────────────────────

def test_registro_manual_nombre_y_doc():
    tools = _registrar()
    assert set(tools) == {"tresd_generar"}
    doc = tools["tresd_generar"]["doc"]
    assert "tresd_generar <ruta_imagen>" in doc
    assert "formato=obj|glb" in doc and "TripoSR" in doc


def test_falta_ruta_y_ruta_inexistente(tmp_path):
    fn = _registrar()["tresd_generar"]["fn"]
    assert "ERROR" in fn("", {}) and "falta la ruta" in fn("", {})
    out = fn(str(tmp_path / "nada.png"), {})
    assert out.startswith("RESULTADO tresd_generar ERROR")
    assert "no existe" in out


def test_extension_no_soportada(tmp_path):
    fn = _registrar()["tresd_generar"]["fn"]
    raro = tmp_path / "cosa.gif"
    raro.write_bytes(b"GIF89a")
    out = fn(str(raro), {})
    assert "ERROR" in out and "no soportada" in out and ".png" in out


def test_opciones_invalidas_error_legible(tmp_path):
    fn = _registrar()["tresd_generar"]["fn"]
    img = _png(tmp_path)
    out = fn(f"{img} | formato=stl", {})
    assert "ERROR" in out and "'stl'" in out and "glb" in out
    out = fn(f"{img} | resolucion=9999", {})
    assert "ERROR" in out and "fuera de rango" in out
    out = fn(f"{img} | turbo=1", {})
    assert "ERROR" in out and "no reconocida" in out and "turbo=1" in out


def test_parseo_opciones_en_orden_libre(tmp_path, monkeypatch):
    _gate_falso(monkeypatch, ok=True)
    visto = _backend_ok(monkeypatch)
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path))
    img = _png(tmp_path)
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(f"{img} | resolucion=64 | formato=obj", {})
    assert out.startswith("RESULTADO tresd_generar OK:")
    assert "100 verts" in out and "200 caras" in out
    assert visto["formato"] == "obj" and visto["resolucion"] == 64
    assert visto["imagen"] == str(img)


def test_salida_md5_estable_en_workspace(tmp_path, monkeypatch):
    """El nombre sale de hashlib (no hash(): PYTHONHASHSEED) y vive bajo
    <workspace>/tresd/ — dos corridas iguales dan la MISMA ruta."""
    _gate_falso(monkeypatch, ok=True)
    visto = _backend_ok(monkeypatch)
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path))
    img = _png(tmp_path)
    fn = _registrar()["tresd_generar"]["fn"]
    fn(str(img), {})
    primera = visto["salida"]
    fn(str(img), {})
    assert visto["salida"] == primera
    ruta = Path(primera)
    assert ruta.parent == tmp_path / "tresd"
    assert ruta.name.startswith("malla_") and ruta.suffix == ".glb"


# ── tool tresd_generar: gate del backend ───────────────────────────────────

def test_backend_no_disponible_sin_reservar_vram(tmp_path, monkeypatch):
    """tresd_disponible -> False corta ANTES del gate: motivo visible y ni
    reserva ni liberacion de VRAM."""
    llamadas = _gate_falso(monkeypatch, ok=True)
    import cognia.tresd as ct
    monkeypatch.setattr(ct, "tresd_disponible",
                        lambda: (False, "vendor TripoSR no esta en X"))
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "vendor TripoSR no esta" in out
    assert llamadas == []


def test_sin_vram_motivo_visible_y_no_suelta(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=False,
                           motivo="VRAM insuficiente: 900 MiB libres")
    _backend_ok(monkeypatch)
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "VRAM insuficiente" in out
    assert ("pedir", "tresd", 4000) in llamadas
    assert not any(c[0] == "soltar" for c in llamadas)


def test_ok_pide_rol_tresd_y_suelta_en_finally(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=True)
    _backend_ok(monkeypatch)
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path))
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert out.startswith("RESULTADO tresd_generar OK:")
    assert llamadas == [("pedir", "tresd", 4000), ("soltar", "tresd", None)]


def test_suelta_incluso_si_el_backend_revienta(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=True)
    _backend_ok(monkeypatch,
                explota=RuntimeError("tresd: timeout tras 600s"))
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path))
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "timeout tras 600s" in out   # legible, sin traceback
    assert ("soltar", "tresd", None) in llamadas           # finally SIEMPRE


def test_fallback_sin_backend_gate_avisa_y_sigue(tmp_path, monkeypatch,
                                                 capsys):
    """Sin _backend_gate (ola 1 en paralelo) la tool NO se bloquea: sigue con
    AVISO por stderr (el CLI fallara visible si de verdad no hay VRAM)."""
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", None)
    _backend_ok(monkeypatch)
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path))
    fn = _registrar()["tresd_generar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert out.startswith("RESULTADO tresd_generar OK:")
    assert "sin _backend_gate" in capsys.readouterr().err


# ── flag apagado (gate de tools.py, cableado en ola 2) ─────────────────────

def test_flag_apagado_no_ejecuta(monkeypatch):
    """Con COGNIA_3D_TOOLS apagado la tool JAMAS corre via run_tool. Cuando
    la ola 2 cablee el prefijo tresd_ en _OPTIN_PREFIJOS el mensaje ademas
    dice como encenderla (asercion condicional: no depende de ola 2)."""
    monkeypatch.delenv("COGNIA_3D_TOOLS", raising=False)
    from cognia.agent import tools as T
    import cognia.agent.background_research as br
    monkeypatch.setattr(br, "record_wanted_tool", lambda name, hint="": None)
    out = T.run_tool("tresd_generar", "loquesea.png", {})
    assert out.startswith("ERROR")
    if T.flag_de_optin("tresd_generar"):    # integracion ola 2 ya cableada
        assert "DESHABILITADA" in out and "COGNIA_3D_TOOLS=1" in out
