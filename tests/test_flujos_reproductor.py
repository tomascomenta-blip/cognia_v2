"""
tests/test_flujos_reproductor.py
================================
Tests en seco de cognia/flujos/reproductor.py: sin modelo, sin red y sin tocar
el registry real (run_tool_fn / agente_fn / ejecutar_fn se INYECTAN).

Lo unico que NO se finge son las postcondiciones: se crean ficheros de verdad en
tmp_path y se corre un comando de verdad, porque el modulo existe precisamente
para que el veredicto salga del disco y no del texto de un modelo.
"""
from __future__ import annotations

import os
import sys

from cognia.flujos.reproductor import (
    coste,
    ligar,
    params_declarados,
    reproducir,
    reproducir_hibrido,
    resumen_linea,
    verificar_postcondiciones,
)


# --- utilidades de test -----------------------------------------------------

def _run_tool_falso(registro, respuestas=None):
    """run_tool_fn falso que REGISTRA (nombre, args, ctx) y devuelve lo pactado.

    respuestas: dict tool -> str (o callable(args) -> str). Por defecto un OK.
    """
    respuestas = respuestas or {}

    def _run(nombre, args, ctx):
        registro.append({"tool": nombre, "args": args, "ctx": dict(ctx or {})})
        r = respuestas.get(nombre, f"RESULTADO {nombre} OK")
        return r(args) if callable(r) else r

    return _run


def _flujo_basico():
    return {
        "nombre": "escribir_y_leer",
        "params": ["ruta", {"nombre": "saludo", "default": "hola"}],
        "pasos": [
            {"tool": "escribir_archivo", "args_plantilla": "{ruta} | {saludo}"},
            {"tool": "leer_archivo", "args_plantilla": "{ruta}"},
        ],
        "postcondiciones": [{"tipo": "fichero_existe", "ruta": "{ruta}"}],
    }


# --- ligado -----------------------------------------------------------------

def test_ligado_feliz_sustituye_pasos_y_postcondiciones():
    lig = ligar(_flujo_basico(), {"ruta": "salida.txt"})
    assert lig["ok"] is True
    assert lig["error"] == ""
    assert lig["pasos"][0]["args"] == "salida.txt | hola"      # default aplicado
    assert lig["pasos"][1]["args"] == "salida.txt"
    assert lig["postcondiciones"][0]["ruta"] == "salida.txt"


def test_ligado_incompleto_falta_obligatorio_falla_ruidoso():
    lig = ligar(_flujo_basico(), {})
    assert lig["ok"] is False
    assert lig["faltan"] == ["ruta"]
    assert "ruta" in lig["error"]
    assert lig["pasos"] == []            # nada a medio ligar sale de aqui


def test_ligado_incompleto_marcador_no_declarado_falla_ruidoso():
    # El peor caso: params dice que todo esta, pero un paso usa {destino}.
    flujo = {
        "nombre": "f", "params": ["ruta"],
        "pasos": [{"tool": "copiar_archivo",
                   "args_plantilla": "{ruta} | {destino}/x.txt"}],
        "postcondiciones": [],
    }
    lig = ligar(flujo, {"ruta": "a.txt"})
    assert lig["ok"] is False
    assert lig["sin_ligar"] == ["destino"]
    assert "{destino}" in lig["error"]


def test_ligado_respeta_llaves_escapadas_y_json():
    flujo = {
        "nombre": "f", "params": ["ruta"],
        "pasos": [{"tool": "shell",
                   "args_plantilla": 'echo {{literal}} {"a": 1} {ruta}'}],
        "postcondiciones": [],
    }
    lig = ligar(flujo, {"ruta": "x"})
    assert lig["ok"] is True
    assert lig["pasos"][0]["args"] == 'echo {literal} {"a": 1} x'


def test_params_declarados_acepta_las_tres_formas():
    assert params_declarados({"params": ["a"]})[0]["obligatorio"] is True
    p = params_declarados({"params": [{"nombre": "a", "default": "z"}]})[0]
    assert (p["obligatorio"], p["default"]) == (False, "z")
    d = params_declarados({"params": {"a": "z"}})[0]
    assert (d["nombre"], d["default"]) == ("a", "z")


# --- reproduccion con run_tool falso ---------------------------------------

def test_reproduccion_llama_a_las_tools_en_orden_con_args_ligados(tmp_path):
    llamadas = []
    flujo = _flujo_basico()
    flujo["postcondiciones"] = []
    inf = reproducir(flujo, {"ruta": "salida.txt"},
                     _run_tool_falso(llamadas), workspace=tmp_path)
    assert [c["tool"] for c in llamadas] == ["escribir_archivo", "leer_archivo"]
    assert llamadas[0]["args"] == "salida.txt | hola"
    assert llamadas[0]["ctx"]["cwd"] == str(tmp_path)   # el flujo corre EN el ws
    assert inf["ok"] is True
    assert [p["ok"] for p in inf["pasos"]] == [True, True]
    assert inf["razon_parada"] == ""
    assert inf["duracion_total_s"] >= 0.0


def test_ancla_el_workspace_por_env_y_lo_restaura(tmp_path, monkeypatch):
    # El registry REAL confina las escrituras por COGNIA_AGENT_WORKSPACE (o cwd),
    # NO por el ctx: sin este anclaje el flujo escribia en el dir del REPL y las
    # postcondiciones lo reprobaban buscando en tmp un fichero que si existia.
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", "el_de_antes")
    visto = {}

    def _run(nombre, args, ctx):
        visto["env"] = os.environ.get("COGNIA_AGENT_WORKSPACE")
        return "RESULTADO ok"

    flujo = _flujo_basico()
    flujo["postcondiciones"] = []
    reproducir(flujo, {"ruta": "x.txt"}, _run, workspace=tmp_path)
    assert visto["env"] == str(tmp_path)
    assert os.environ["COGNIA_AGENT_WORKSPACE"] == "el_de_antes"


def test_ligado_fallido_no_ejecuta_ni_una_tool():
    llamadas = []
    inf = reproducir(_flujo_basico(), {}, _run_tool_falso(llamadas))
    assert llamadas == []
    assert inf["ok"] is False
    assert "ligado fallido" in inf["razon_parada"]


def test_una_excepcion_de_run_tool_no_se_propaga():
    def _boom(nombre, args, ctx):
        raise RuntimeError("el registry exploto")

    flujo = _flujo_basico()
    flujo["postcondiciones"] = []
    inf = reproducir(flujo, {"ruta": "x"}, _boom)
    assert inf["ok"] is False
    assert "EXCEPCION" in inf["pasos"][0]["resultado_head"]


# --- parar_en_fallo ---------------------------------------------------------

def _flujo_tres_pasos():
    return {
        "nombre": "tres", "params": [],
        "pasos": [{"tool": "uno", "args_plantilla": "a"},
                  {"tool": "dos", "args_plantilla": "b"},
                  {"tool": "tres", "args_plantilla": "c"}],
        "postcondiciones": [],
    }


def test_parar_en_fallo_true_corta_en_el_paso_malo():
    llamadas = []
    run = _run_tool_falso(llamadas, {"dos": "RESULTADO dos ERROR: no existe"})
    inf = reproducir(_flujo_tres_pasos(), {}, run, parar_en_fallo=True)
    assert [c["tool"] for c in llamadas] == ["uno", "dos"]
    assert len(inf["pasos"]) == 2
    assert inf["ok"] is False
    assert inf["razon_parada"] == "paso 2 fallo (dos)"


def test_parar_en_fallo_false_ejecuta_todo_y_sigue_reprobando():
    llamadas = []
    run = _run_tool_falso(llamadas, {"dos": "RESULTADO dos ERROR: no existe"})
    inf = reproducir(_flujo_tres_pasos(), {}, run, parar_en_fallo=False)
    assert [c["tool"] for c in llamadas] == ["uno", "dos", "tres"]
    assert [p["ok"] for p in inf["pasos"]] == [True, False, True]
    assert inf["ok"] is False
    assert "2" in inf["razon_parada"]


def test_la_palabra_error_en_el_cuerpo_no_reprueba_el_paso():
    # Un grep sobre un log lleno de ERROR salio bien: el estado va en la cabecera.
    run = _run_tool_falso([], {"uno": "RESULTADO uno OK\nlinea: ERROR de ayer"})
    inf = reproducir({"nombre": "g", "params": [],
                      "pasos": [{"tool": "uno", "args_plantilla": ""}],
                      "postcondiciones": []}, {}, run)
    assert inf["pasos"][0]["ok"] is True


# --- postcondiciones: en DISCO y EJECUTANDO de verdad ------------------------

def test_fichero_existe_y_contiene_se_miden_en_disco(tmp_path):
    (tmp_path / "hecho.txt").write_text("hola mundo\n", encoding="utf-8")
    post = verificar_postcondiciones(
        [{"tipo": "fichero_existe", "ruta": "hecho.txt"},
         {"tipo": "fichero_existe", "ruta": "fantasma.txt"},
         {"tipo": "fichero_contiene", "ruta": "hecho.txt", "texto": "mundo"},
         {"tipo": "fichero_contiene", "ruta": "hecho.txt", "texto": "adios"},
         {"tipo": "fichero_contiene", "ruta": "hecho.txt",
          "patron": r"h\w+ m\w+", "regex": True}],
        tmp_path)
    assert [p["ok"] for p in post] == [True, False, True, False, True]
    assert "NO existe" in post[1]["detalle"]


def test_comando_exit0_ejecuta_de_verdad(tmp_path):
    (tmp_path / "prueba.py").write_text("print('vivo')\n", encoding="utf-8")
    post = verificar_postcondiciones(
        [{"tipo": "comando_exit0",
          "comando": f'"{sys.executable}" prueba.py'},
         {"tipo": "comando_exit0",
          "comando": f'"{sys.executable}" -c "import sys; sys.exit(3)"'}],
        tmp_path)
    assert post[0]["ok"] is True
    assert post[1]["ok"] is False
    assert "exit 3" in post[1]["detalle"]


def test_postcondicion_de_tipo_desconocido_no_se_aprueba():
    post = verificar_postcondiciones([{"tipo": "el_modelo_dijo_que_si"}], None)
    assert post[0]["ok"] is False


def test_el_flujo_verde_con_postcondicion_falsa_sale_reprobado(tmp_path):
    # El caso que motiva el modulo: todas las tools dicen OK y el disco esta vacio.
    flujo = _flujo_basico()
    inf = reproducir(flujo, {"ruta": "salida.txt"}, _run_tool_falso([]),
                     workspace=tmp_path)
    assert [p["ok"] for p in inf["pasos"]] == [True, True]
    assert inf["ok"] is False
    assert "postcondicion fallida" in inf["razon_parada"]


def test_las_postcondiciones_se_verifican_aunque_un_paso_falle(tmp_path):
    (tmp_path / "salida.txt").write_text("hola", encoding="utf-8")
    flujo = _flujo_basico()
    run = _run_tool_falso([], {"escribir_archivo": "RESULTADO x ERROR: feo"})
    inf = reproducir(flujo, {"ruta": "salida.txt"}, run, workspace=tmp_path)
    assert inf["postcondiciones"][0]["ok"] is True      # el disco esta bien
    assert inf["ok"] is False                           # pero el flujo no paso


def test_ejecutar_fn_inyectado_se_usa_en_vez_del_subprocess():
    vistos = []

    def _fake(comando, cwd=None):
        vistos.append(comando)
        return 0, "salida falsa"

    post = verificar_postcondiciones(
        [{"tipo": "comando_exit0", "comando": "haz_algo"}], None, _fake)
    assert vistos == ["haz_algo"] and post[0]["ok"] is True


# --- hibrido ----------------------------------------------------------------

def _flujo_hibrido():
    return {
        "nombre": "hibrido", "params": ["ruta"],
        "pasos": [
            {"tool": "leer_archivo", "args_plantilla": "{ruta}"},
            {"tipo": "modelo", "instruccion": "elige un nombre para {ruta}"},
            {"tool": "escribir_archivo", "args_plantilla": "{ruta} | fin"},
        ],
        "postcondiciones": [],
    }


def test_el_hibrido_llama_a_agente_fn_exactamente_una_vez():
    llamadas_tool = []
    llamadas_agente = []

    def _agente(instruccion, ctx):
        llamadas_agente.append(instruccion)
        return "elegido: motor.py"

    inf = reproducir_hibrido(_flujo_hibrido(), {"ruta": "a.txt"},
                             _run_tool_falso(llamadas_tool), _agente)
    assert len(llamadas_agente) == 1
    assert llamadas_agente[0] == "elige un nombre para a.txt"   # ligado tambien
    assert [c["tool"] for c in llamadas_tool] == ["leer_archivo",
                                                  "escribir_archivo"]
    assert inf["ok"] is True
    assert inf["pasos"][1]["tipo"] == "modelo"
    assert "motor.py" in inf["pasos"][1]["resultado_head"]


def test_paso_de_modelo_sin_agente_fn_falla_ruidoso_no_se_salta():
    llamadas = []
    inf = reproducir(_flujo_hibrido(), {"ruta": "a.txt"},
                     _run_tool_falso(llamadas))
    assert inf["ok"] is False
    assert inf["pasos"][1]["ok"] is False
    assert [c["tool"] for c in llamadas] == ["leer_archivo"]   # corto ahi


def test_una_excepcion_de_agente_fn_no_se_propaga():
    def _boom(instruccion, ctx):
        raise RuntimeError("modelo caido")

    inf = reproducir_hibrido(_flujo_hibrido(), {"ruta": "a.txt"},
                             _run_tool_falso([]), _boom)
    assert inf["ok"] is False
    assert "EXCEPCION" in inf["pasos"][1]["resultado_head"]


# --- coste (el contrafactual) ----------------------------------------------

def test_coste_cuenta_pasos_modelo_y_pared(tmp_path):
    def _agente(instruccion, ctx):
        return "ok"

    inf = reproducir_hibrido(_flujo_hibrido(), {"ruta": "a.txt"},
                             _run_tool_falso([]), _agente, workspace=tmp_path)
    c = coste(inf)
    assert c["pasos"] == 3 and c["pasos_ok"] == 3 and c["pasos_modelo"] == 1
    assert c["pared_s"] >= c["pared_pasos_s"] >= 0.0
    assert c["pared_examen_s"] >= 0.0
    assert "hibrido" in resumen_linea(inf)


def test_print_fn_recibe_una_linea_por_paso_y_no_puede_romper_nada():
    lineas = []

    def _print_roto(linea):
        lineas.append(linea)
        raise RuntimeError("el renderer exploto")

    inf = reproducir(_flujo_tres_pasos(), {}, _run_tool_falso([]),
                     print_fn=_print_roto)
    assert len(lineas) == 3 and inf["ok"] is True
