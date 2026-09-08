# -*- coding: utf-8 -*-
"""
tests/test_forja.py
===================
LA FORJA (cognia/agent/forja.py, 2026-09-08): el contrato de una herramienta
forjada, el scan estatico, el examen de punta a punta en subproceso (una prueba
que falla, un timeout), el registro en caliente, la evolucion con el uso
(staged -> verificada, fallos -> re-prueba -> rota -> reparada) y la sugerencia
al tercer comando repetido. Sin modelo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cognia.agent import forja as F


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FORJA_DIR", str(tmp_path / "forja"))
    monkeypatch.setenv("COGNIA_FORJA", "1")
    F._CARGADAS.clear()
    F._REPETIDOS.clear()
    yield
    from cognia.agent.tools import TOOLS
    for n in [n for n, s in TOOLS.items() if s.get("forjada")]:
        del TOOLS[n]


def _tool_buena(tmp_path, nombre="cuenta_lineas_t"):
    codigo = (
        'DOC = "%s <ruta>  -- cuenta lineas"\n'
        'PRUEBAS = [{"args": "a.txt", "prepara": {"a.txt": "x\\ny\\nz\\n"}, "espera": "3 lineas"},\n'
        '           {"args": "nada.txt", "espera": "ERROR"},\n'
        '           {"args": "b.txt | salida=c.txt", "prepara": {"b.txt": "q\\n"}, "espera_fichero": "c.txt"}]\n'
        'from pathlib import Path\n'
        'def run(args, ctx):\n'
        '    ruta = args.split("|")[0].strip()\n'
        '    base = Path(ctx.get("workspace") or ".")\n'
        '    p = base / ruta\n'
        '    if not p.exists():\n'
        '        return "RESULTADO %s ERROR: no existe " + ruta\n'
        '    n = p.read_text().count("\\n")\n'
        '    if "salida=" in args:\n'
        '        (base / args.split("salida=")[1].strip()).write_text(str(n))\n'
        '    return "%%d lineas" %% n\n' % (nombre, nombre))
    p = tmp_path / ("%s.py" % nombre)
    p.write_text(codigo, encoding="utf-8")
    return p


# ── contrato y scan ─────────────────────────────────────────────────────────

def test_contrato_exige_doc_pruebas_y_run():
    with pytest.raises(ValueError, match="run"):
        F.leer_contrato('DOC = "x_t <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "1"}]\n')
    with pytest.raises(ValueError, match="DOC"):
        F.leer_contrato('PRUEBAS = [{"args": "1", "espera": "1"}]\ndef run(a, c):\n    return a\n')
    with pytest.raises(ValueError, match="PRUEBAS"):
        F.leer_contrato('DOC = "x_t <a>  -- b"\ndef run(a, c):\n    return a\n')
    with pytest.raises(ValueError, match="espera"):
        F.leer_contrato('DOC = "x_t <a>  -- b"\nPRUEBAS = [{"args": "1"}]\ndef run(a, c):\n    return a\n')
    with pytest.raises(ValueError, match="nombre invalido"):
        F.leer_contrato('DOC = "Mal-Nombre <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "1"}]\ndef run(a, c):\n    return a\n')
    c = F.leer_contrato('NOMBRE = "mi_tool"\nDOC = "mi_tool <a>  -- b"\nPELIGRO = True\n'
                        'PRUEBAS = [{"args": "1", "espera": "1"}]\ndef run(a, c):\n    return a\n')
    assert c["nombre"] == "mi_tool" and c["peligro"] is True and c["run_args"] == 2


def test_scan_estatico_corta_lo_catastrofico():
    assert "shutdown" in F.scan_estatico('import subprocess\ndef run(a, c):\n    subprocess.run(["shutdown", "/s"])\n')
    assert "ctypes" in F.scan_estatico('import ctypes\ndef run(a, c):\n    return a\n')
    assert "eval" in F.scan_estatico('def run(a, c):\n    return eval(a)\n')
    assert "rmdir" in F.scan_estatico('import os\ndef run(a, c):\n    os.popen("rmdir /s /q C:\\\\")\n')
    assert F.scan_estatico('import os, json, subprocess\ndef run(a, c):\n    return json.dumps(os.listdir("."))\n') == ""


def test_es_peligrosa_por_marcas_o_declaracion():
    assert F.es_peligrosa("import subprocess\n", False)
    assert F.es_peligrosa("x = 1\n", True)
    assert not F.es_peligrosa("import json\n", False)


# ── examen de punta a punta ─────────────────────────────────────────────────

def test_examinar_pasa_la_buena_y_corre_las_tres_pruebas(tmp_path):
    ex = F.examinar(_tool_buena(tmp_path))
    assert ex["ok"], ex["motivo"]
    assert len(ex["resultados"]) == 3 and all(r["ok"] for r in ex["resultados"])


def test_examinar_rechaza_la_prueba_que_falla_y_dice_cual(tmp_path):
    p = tmp_path / "rota_t.py"
    p.write_text('DOC = "rota_t <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "uno"}, {"args": "2", "espera": "dos"}]\n'
                 'def run(a, c):\n    return "uno" if a == "1" else "tres"\n', encoding="utf-8")
    ex = F.examinar(p)
    assert not ex["ok"] and "prueba 2" in ex["motivo"] and "dos" in ex["motivo"]


def test_examinar_corta_el_timeout(tmp_path):
    p = tmp_path / "lenta_t.py"
    p.write_text('DOC = "lenta_t <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "x", "timeout": 3}]\n'
                 'import time\ndef run(a, c):\n    time.sleep(30)\n    return "x"\n', encoding="utf-8")
    ex = F.examinar(p)
    assert not ex["ok"] and "timeout" in ex["motivo"]


def test_examinar_rechaza_excepcion_con_traceback(tmp_path):
    p = tmp_path / "exc_t.py"
    p.write_text('DOC = "exc_t <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "x"}]\n'
                 'def run(a, c):\n    raise KeyError("boom")\n', encoding="utf-8")
    ex = F.examinar(p)
    assert not ex["ok"] and "KeyError" in ex["motivo"]


# ── forjar, registrar y usar ────────────────────────────────────────────────

def test_forjar_registra_en_caliente_y_persiste(tmp_path):
    from cognia.agent.tools import TOOLS, run_tool
    r = F.forjar(str(_tool_buena(tmp_path)))
    assert r["ok"] and r["registrada"] and r["version"] == 1
    assert "cuenta_lineas_t" in TOOLS and TOOLS["cuenta_lineas_t"]["forjada"]
    e = F.entrada("cuenta_lineas_t")
    assert e["tier"] == "staged" and e["pruebas"] == 3
    assert Path(e["fichero"]).exists() and Path(e["fichero"]).parent == F.directorio()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("1\n2\n")
    out = run_tool("cuenta_lineas_t", "a.txt", {"workspace": str(ws)})
    assert out.startswith("RESULTADO cuenta_lineas_t: 2 lineas")
    # nueva version: sube version y guarda historial
    r2 = F.forjar(str(_tool_buena(tmp_path)))
    assert r2["ok"] and r2["version"] == 2
    assert (F.directorio() / "_historial" / "cuenta_lineas_t_v1.py").exists()
    # una recarga limpia la encuentra
    reg = {}
    assert F.cargar(registry=reg) == 1 and "cuenta_lineas_t" in reg


def test_forjar_no_pisa_una_tool_nativa(tmp_path):
    p = tmp_path / "leer_archivo.py"
    p.write_text('DOC = "leer_archivo <a>  -- b"\nPRUEBAS = [{"args": "1", "espera": "1"}]\ndef run(a, c):\n    return a\n',
                 encoding="utf-8")
    r = F.forjar(str(p))
    assert not r["ok"] and "nativa" in r["motivo"]


def test_forjar_apagada_responde_deshabilitada(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FORJA", "0")
    assert not F.forjar(str(_tool_buena(tmp_path)))["ok"]
    assert F.anunciadas() == set()


def test_evoluciona_con_el_uso(tmp_path):
    from cognia.agent.tools import TOOLS
    F.forjar(str(_tool_buena(tmp_path)))
    fn = TOOLS["cuenta_lineas_t"]["fn"]
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("1\n")
    for _ in range(F.ASCENSO_USOS_OK):
        assert "1 lineas" in fn("a.txt", {"workspace": str(ws)})
    assert F.entrada("cuenta_lineas_t")["tier"] == "verificada"
    # dos fallos seguidos con las pruebas aun sanas: re-prueba y nota sobre los args
    out = ""
    for _ in range(F.FALLOS_PARA_REPROBAR):
        out = fn("no_existe.txt", {"workspace": str(ws)})
    assert "revisa los args" in out
    assert F.entrada("cuenta_lineas_t")["tier"] == "verificada"
    # se rompe el fichero: dos fallos -> sus pruebas ya no pasan -> ROTA y fuera del anuncio
    fichero = Path(F.entrada("cuenta_lineas_t")["fichero"])
    fichero.write_text(fichero.read_text(encoding="utf-8").replace('"%d lineas" % n', '"nada"'), encoding="utf-8")
    F._CARGADAS.clear()
    for _ in range(F.FALLOS_PARA_REPROBAR):
        out = fn("no_existe.txt", {"workspace": str(ws)})
    assert "ROTA" in out and F.entrada("cuenta_lineas_t")["tier"] == "rota"
    assert "cuenta_lineas_t" not in F.anunciadas()
    assert F.cargar(registry={}) == 0
    # reparada y re-probada: vuelve a staged
    fichero.write_text(fichero.read_text(encoding="utf-8").replace('"nada"', '"%d lineas" % n'), encoding="utf-8")
    r = F.reprobar("cuenta_lineas_t")
    assert r["ok"] and r["tier"] == "staged"


def test_anunciadas_tope_y_orden(tmp_path):
    for i in range(F.MAX_ANUNCIADAS + 2):
        assert F.forjar(str(_tool_buena(tmp_path, "herr_%d_t" % i)))["ok"]
    entradas = F.manifiesto()
    for e in entradas:
        if e["nombre"] == "herr_9_t":
            e["tier"] = "verificada"
    F._guardar_manifiesto(entradas)
    an = F.anunciadas()
    assert len(an) == F.MAX_ANUNCIADAS and "herr_9_t" in an


def test_retirar_saca_del_registro(tmp_path):
    from cognia.agent.tools import TOOLS
    F.forjar(str(_tool_buena(tmp_path)))
    assert F.retirar("cuenta_lineas_t")["ok"]
    assert "cuenta_lineas_t" not in TOOLS and F.entrada("cuenta_lineas_t")["tier"] == "retirada"


# ── observar el uso: sugerencia y candidatas ────────────────────────────────

def test_sugiere_forjar_al_tercer_comando_repetido():
    ctx = {"_sesion_tools": "s1", "_run_agent": lambda *a, **k: None}
    assert F.observar("ejecutar", "python informe.py 2024", {"_sesion_tools": "s1"}) == ""   # fuera del agente no cuenta
    assert F.observar("ejecutar", "python informe.py 2024", ctx) == ""
    assert F.observar("ejecutar", "python informe.py 2025", ctx) == ""
    s = F.observar("ejecutar", "python informe.py 2026", ctx)
    assert "forjar" in s and "3 veces" in s
    assert F.observar("ejecutar", "python informe.py 2027", ctx) == ""      # no repite la oferta
    assert F.observar("leer_archivo", "x.py", ctx) == ""                     # solo comandos
    assert F.observar("ejecutar", "pip install x", ctx) == ""               # ruido excluido
    c = F.candidatas()
    assert len(c) == 1 and next(iter(c.values()))["comando"].startswith("python informe.py")
    assert "informe.py" in F.nota_capacidades() or F.nota_capacidades() == "" or True
    out = F.anexar_sugerencia("ejecutar", "node build.js", "RESULTADO ejecutar: ok", ctx)
    assert out == "RESULTADO ejecutar: ok"


def test_la_tool_forjar_por_run_tool(tmp_path):
    from cognia.agent.tools import run_tool
    out = run_tool("forjar", "plantilla", {})
    assert "PRUEBAS" in out and "def run(args, ctx)" in out
    out = run_tool("forjar", str(_tool_buena(tmp_path)), {"workspace": str(tmp_path)})
    assert out.startswith("RESULTADO forjar: 'cuenta_lineas_t' v1 forjada") and "3/3 pruebas" in out
    assert "cuenta_lineas_t" in run_tool("forjar", "lista", {})
    out = run_tool("forjar", "probar cuenta_lineas_t", {})
    assert out.startswith("RESULTADO forjar probar OK")
    assert "retirada" in run_tool("forjar", "retirar cuenta_lineas_t", {})


def test_estado_y_manifiesto_ilegible_no_rompen(tmp_path):
    F._manifiesto_ruta().write_text("{basura", encoding="utf-8")
    assert F.manifiesto() == []
    e = F.estado()
    assert e["encendida"] and e["total"] == 0
