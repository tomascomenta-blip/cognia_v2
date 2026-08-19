# -*- coding: utf-8 -*-
"""Tests del catastro de efectos (cognia/multiverso/reversibilidad.py).

Sin modelo, sin red, sin subprocess: la compensacion por comando recibe un
ejecutor INYECTADO. Lo que se prueba es lo que decide seguridad: los tres
cubos por nombre, que 'ejecutar' se clasifique por el COMANDO, que el default
sea 'desconocido' (nunca 'puro'), que la compensacion RESTAURE de verdad y que
un fichero gigante DEGRADE en vez de fingir un rollback.
"""

import json
import os

import pytest

from cognia.multiverso import reversibilidad as rev


# --------------------------------------------------------------------------
# Los tres cubos por NOMBRE de tool
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "leer_archivo", "listar", "buscar", "calcular", "git_diff", "contar_lineas",
])
def test_cubo_puro_por_nombre(tool):
    d = rev.clasificar(tool)
    assert d["cubo"] == "puro"
    assert d["compensacion"] is None
    assert rev.es_especulable(tool) is True


@pytest.mark.parametrize("tool,tipo", [
    ("escribir_archivo", "restaurar_fichero"),
    ("editar_archivo", "restaurar_fichero"),
    ("apendar_archivo", "restaurar_fichero"),
    ("crear_directorio", "borrar_si_vacio"),
    ("mover_archivo", "mover_de_vuelta"),
    ("git_commit", "comando"),
])
def test_cubo_reversible_trae_compensacion_concreta(tool, tipo):
    d = rev.clasificar(tool, "x | y")
    assert d["cubo"] == "reversible"
    assert d["compensacion"]["tipo"] == tipo
    assert d["compensacion"]["detalle"]


@pytest.mark.parametrize("tool", [
    "abrir", "matar_proceso", "memorizar", "kg_agregar", "pantalla_click",
])
def test_cubo_irreversible_por_nombre(tool):
    d = rev.clasificar(tool, "algo")
    assert d["cubo"] == "irreversible"
    assert d["compensacion"] is None
    assert rev.es_especulable(tool) is False


def test_los_cubos_son_los_cuatro_declarados():
    assert rev.CUBOS == ("puro", "reversible", "irreversible", "desconocido")


# --------------------------------------------------------------------------
# 'ejecutar': el cubo lo decide el COMANDO, no el nombre de la tool
# --------------------------------------------------------------------------

CASOS_EJECUTAR = [
    ("ls -la", "puro"),
    ("git status --short", "puro"),
    ("cat notas.txt | grep TODO", "puro"),
    ("python --version", "puro"),
    ("mkdir build", "reversible"),
    ("echo hola > salida.txt", "reversible"),
    ("cp a.txt b.txt", "reversible"),
    ("rm -rf build", "irreversible"),
    ("git push origin main", "irreversible"),
    ("curl -X POST https://api.ejemplo/x", "irreversible"),
    ("shutdown /s /t 0", "irreversible"),
    ("python analiza.py", "desconocido"),
    ("npm publish", "irreversible"),
    ("pip install requests", "irreversible"),
]


@pytest.mark.parametrize("cmd,esperado", CASOS_EJECUTAR)
def test_ejecutar_se_clasifica_por_el_comando(cmd, esperado):
    d = rev.clasificar("ejecutar", cmd)
    assert d["cubo"] == esperado, f"{cmd!r} -> {d['cubo']} ({d['motivo']})"


def test_pipeline_manda_el_peor_segmento():
    # empieza por un comando puro y termina borrando: NO puede salir 'puro'
    d = rev.clasificar("ejecutar", "ls build | xargs rm -rf")
    assert d["cubo"] == "irreversible"


def test_sufijos_de_la_tool_no_son_pipeline():
    # 'ejecutar' acepta "<cmd> | timeout=N | cwd=RUTA"; eso no es shell
    d = rev.clasificar("ejecutar", "ls -la | timeout=10 | cwd=C:/tmp")
    assert d["cubo"] == "puro"


def test_ejecutar_sin_argumentos_es_desconocido_no_puro():
    d = rev.clasificar("ejecutar", "")
    assert d["cubo"] == "desconocido"
    assert "indecidible" in d["motivo"]


def test_find_puro_pero_find_delete_no():
    assert rev.clasificar("ejecutar", "find . -name '*.py'")["cubo"] == "puro"
    assert rev.clasificar("ejecutar", "find . -name '*.py' -delete")["cubo"] == "irreversible"


def test_sed_in_place_es_reversible_y_sin_i_es_puro():
    assert rev.clasificar("ejecutar", "sed -n '1,5p' a.txt")["cubo"] == "puro"
    assert rev.clasificar("ejecutar", "sed -i s/a/b/ a.txt")["cubo"] == "reversible"


def test_ejecutar_fondo_nunca_es_puro():
    # sus efectos ocurren DESPUES de clasificar
    d = rev.clasificar("ejecutar_fondo", "ls -la")
    assert d["cubo"] == "desconocido"


# --------------------------------------------------------------------------
# Default SEGURO
# --------------------------------------------------------------------------

def test_tool_desconocida_cae_a_desconocido_no_a_puro():
    d = rev.clasificar("tool_que_no_existe_en_ningun_catastro")
    assert d["cubo"] == "desconocido"
    assert d["confianza"] < 0.5
    assert rev.es_especulable("tool_que_no_existe_en_ningun_catastro") is False


def test_comando_desconocido_cae_a_desconocido():
    d = rev.clasificar("ejecutar", "herramienta_rarisima --hacer-algo")
    assert d["cubo"] == "desconocido"


def test_nombre_vacio_es_desconocido():
    assert rev.clasificar("")["cubo"] == "desconocido"
    assert rev.clasificar(None)["cubo"] == "desconocido"


def test_args_no_string_no_revientan():
    d = rev.clasificar("escribir_archivo", {"ruta": "a.txt", "texto": "x"})
    assert d["cubo"] in rev.CUBOS


# --------------------------------------------------------------------------
# registrar_efecto + compensar: el rollback REAL sobre ficheros de verdad
# --------------------------------------------------------------------------

def test_compensacion_real_de_escribir_archivo_restaura_el_previo(tmp_path):
    objetivo = tmp_path / "config.txt"
    objetivo.write_text("VERSION=1\nCLAVE=vieja\n", encoding="utf-8")
    ctx = {"workspace": str(tmp_path)}

    reg = rev.registrar_efecto("escribir_archivo", "config.txt | loquesea",
                               ctx, persistir=False)
    assert reg["cubo"] == "reversible"
    assert reg["existia_antes"] is True
    assert reg["hash_previo"]

    # la tool "real" pisa el fichero
    objetivo.write_text("DESTRUIDO", encoding="utf-8")
    assert objetivo.read_text(encoding="utf-8") == "DESTRUIDO"

    res = rev.compensar(reg)
    assert res["ok"] is True
    assert res["verificado"] is True
    assert objetivo.read_text(encoding="utf-8") == "VERSION=1\nCLAVE=vieja\n"


def test_compensacion_de_fichero_que_no_existia_lo_borra(tmp_path):
    ctx = {"workspace": str(tmp_path)}
    reg = rev.registrar_efecto("escribir_archivo", "nuevo.py | print(1)",
                               ctx, persistir=False)
    assert reg["existia_antes"] is False
    (tmp_path / "nuevo.py").write_text("print(1)", encoding="utf-8")

    res = rev.compensar(reg)
    assert res["ok"] is True
    assert not (tmp_path / "nuevo.py").exists()


def test_fichero_gigante_degrada_a_irreversible_y_lo_dice(tmp_path):
    grande = tmp_path / "enorme.bin"
    grande.write_bytes(b"x" * 4096)
    ctx = {"workspace": str(tmp_path)}
    previo = rev.TOPE_BYTES
    rev.TOPE_BYTES = 1024  # tope bajo para no escribir 5 MB en un test
    try:
        reg = rev.registrar_efecto("escribir_archivo", "enorme.bin | nuevo",
                                   ctx, persistir=False)
    finally:
        rev.TOPE_BYTES = previo
    assert reg["cubo"] == "irreversible"
    assert reg["degradado"] is True
    assert reg["contenido_b64"] == ""
    assert "IRREVERSIBLE EN LA PRACTICA" in reg["detalle"]

    res = rev.compensar(reg)
    assert res["ok"] is False
    assert "no compensable" in res["detalle"]


def test_compensar_crear_directorio_solo_si_quedo_vacio(tmp_path):
    ctx = {"workspace": str(tmp_path)}
    reg = rev.registrar_efecto("crear_directorio", "sub", ctx, persistir=False)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "algo.txt").write_text("dato", encoding="utf-8")

    res = rev.compensar(reg)
    assert res["ok"] is False
    assert (tmp_path / "sub").exists()  # NO borra contenido ajeno

    (tmp_path / "sub" / "algo.txt").unlink()
    res2 = rev.compensar(reg)
    assert res2["ok"] is True
    assert not (tmp_path / "sub").exists()


def test_compensar_mover_archivo_devuelve_al_origen(tmp_path):
    origen = tmp_path / "a.txt"
    origen.write_text("contenido", encoding="utf-8")
    ctx = {"workspace": str(tmp_path)}
    reg = rev.registrar_efecto("mover_archivo", "a.txt | b.txt", ctx,
                               persistir=False)
    os.replace(str(origen), str(tmp_path / "b.txt"))

    res = rev.compensar(reg)
    assert res["ok"] is True
    assert origen.read_text(encoding="utf-8") == "contenido"
    assert not (tmp_path / "b.txt").exists()


def test_compensar_por_comando_usa_el_ejecutor_inyectado():
    reg = rev.registrar_efecto("git_commit", "mensaje", None, persistir=False)
    reg["comando_compensador"] = "git reset --soft HEAD~1"
    corridos = []

    def falso(cmd, cwd=None):
        corridos.append(cmd)
        return 0, "HEAD is now at ..."

    res = rev.compensar(reg, ejecutor=falso)
    assert res["ok"] is True
    assert corridos == ["git reset --soft HEAD~1"]


def test_compensar_nunca_lanza():
    for basura in (None, 42, "texto", {}, {"cubo": "reversible"},
                   {"cubo": "reversible", "compensacion": {"tipo": "inventado"}}):
        res = rev.compensar(basura)
        assert res["ok"] is False
        assert isinstance(res["detalle"], str)


def test_registrar_efecto_de_accion_no_reversible_no_captura_nada(tmp_path):
    reg = rev.registrar_efecto("ejecutar", "git push origin main",
                               {"workspace": str(tmp_path)}, persistir=False)
    assert reg["cubo"] == "irreversible"
    assert reg["contenido_b64"] == ""
    assert rev.compensar(reg)["ok"] is False


def test_persistencia_opcional_escribe_jsonl(tmp_path, monkeypatch):
    destino = tmp_path / "efectos_dir"
    monkeypatch.setenv("COGNIA_MULTIVERSO_DIR", str(destino))
    obj = tmp_path / "f.txt"
    obj.write_text("hola", encoding="utf-8")
    rev.registrar_efecto("escribir_archivo", "f.txt | adios",
                         {"workspace": str(tmp_path)}, persistir=True)
    linea = (destino / "efectos.jsonl").read_text(encoding="utf-8").strip()
    d = json.loads(linea)
    assert d["tool"] == "escribir_archivo"
    assert "contenido_b64" not in d   # el blob va aparte, no inflando el jsonl
    assert os.path.exists(d["blob"])


# --------------------------------------------------------------------------
# medir_distribucion
# --------------------------------------------------------------------------

def test_medir_distribucion_sobre_traza_sintetica():
    trazas = [
        {"action": "leer_archivo", "args": "a.py"},
        {"action": "listar", "args": "."},
        {"action": "escribir_archivo", "args": "a.py | contenido"},
        {"action": "ejecutar", "args": "ls -la"},
        {"action": "ejecutar", "args": "rm -rf build"},
        {"action": "ejecutar", "args": "python script.py"},
        {"action": "kg_agregar", "args": "a | b | c"},
        {"action": "tool_inventada", "args": ""},
    ]
    res = rev.medir_distribucion(trazas)
    assert res["n"] == 8
    assert res["conteo"]["puro"] == 3          # leer, listar, ls -la
    assert res["conteo"]["reversible"] == 1    # escribir_archivo
    assert res["conteo"]["irreversible"] == 2  # rm -rf, kg_agregar
    assert res["conteo"]["desconocido"] == 2   # python script.py, tool_inventada
    assert round(sum(res["porcentaje"].values())) == 100
    assert res["fraccion_especulable"] == 37.5
    assert res["acciones_de_shell"] == 3
    # 'ejecutar' reparte en tres cubos: la prueba de que el nombre no basta
    assert len([c for c, v in res["por_tool"]["ejecutar"].items() if v]) == 3


def test_medir_distribucion_respeta_pesos_de_trazas_agregadas():
    res = rev.medir_distribucion([
        {"action": "leer_archivo", "calls": 100},
        {"action": "escribir_archivo", "peso": 300},
    ])
    assert res["n"] == 400
    assert res["porcentaje"]["reversible"] == 75.0


def test_medir_distribucion_acepta_tuplas_y_vacio():
    res = rev.medir_distribucion([("listar", "."), ("ejecutar", "rm x")])
    assert res["n"] == 2
    assert rev.medir_distribucion([])["n"] == 0
    assert rev.medir_distribucion(None)["n"] == 0


def test_cargar_trazas_lee_bitacora_y_agregado(tmp_path):
    bit = tmp_path / "bitacora.jsonl"
    bit.write_text(
        json.dumps({"tipo": "ToolInicio", "tool": "ejecutar", "args": "ls"}) + "\n"
        + json.dumps({"tipo": "ToolFin", "tool": "ejecutar", "args": "ls",
                      "ok": True}) + "\n"
        + json.dumps({"tipo": "Aviso", "texto": "nada"}) + "\n",
        encoding="utf-8")
    trazas = rev.cargar_trazas(bit)
    assert trazas == [{"action": "ejecutar", "args": "ls"}]  # ToolFin no duplica

    agg = tmp_path / "_tool_usage.json"
    agg.write_text(json.dumps({"buscar": {"calls": 7, "ok": 7}}), encoding="utf-8")
    assert rev.cargar_trazas(agg) == [{"action": "buscar", "args": "", "peso": 7}]

    assert rev.cargar_trazas(tmp_path / "no_existe.jsonl") == []


@pytest.mark.parametrize("cmd,esperado", [
    ("xargs rm -rf", "irreversible"),
    ("ls build | xargs rm -rf", "irreversible"),
    ("sudo rm /etc/hosts", "irreversible"),
    ("timeout 30 git push origin main", "irreversible"),
    ("nohup ls -la", "puro"),
    ("time mkdir build", "reversible"),
])
def test_envoltorios_no_deciden_el_cubo(cmd, esperado):
    # REGRESION: `xargs rm -rf` salia 'desconocido' porque 'xargs' no estaba en
    # ninguna tabla. El envoltorio se pela y manda el comando de dentro.
    assert rev.clasificar("ejecutar", cmd)["cubo"] == esperado
