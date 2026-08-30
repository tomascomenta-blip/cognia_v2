# -*- coding: utf-8 -*-
"""
tests/test_flujo_ia.py
======================
Tests de `cognia/agent/flujo_ia.py` (editar un flujo hablando y sacar un flujo
de una sesion de trabajo).

POR QUE ESTAN ESCRITOS ASI
--------------------------
1. TODO test inyecta `generar_fn`. El modulo solo toca el backend cuando
   `generar_fn is None`; con la funcion inyectada esa rama ni se pisa. Un test
   que dependiera del backend mediria la maquina, no el modulo.
2. La fixture mueve COGNIA_FLUJOTECA_DIR a tmp_path. `editar()` importa
   `flujoteca` para describir el flujo, y un descuido futuro (guardar, listar)
   escribiria en la biblioteca REAL del dueno.
3. Lo que mas se comprueba es la FRONTERA entre lo que se arregla y lo que se
   rechaza: es la regla que gobierna el fichero y la que el modelo pone a
   prueba en cada llamada.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from cognia.agent import flujo_ia as fia
from cognia.agent.flujo_ia import Resultado, de_sesion, editar, sanear_flujo


TOOLS = ["buscar_web", "escribir_archivo", "leer_archivo"]

FLUJO_BASE = {
    "nombre": "informe diario",
    "nodos": [
        {"id": "buscar", "tool": "buscar_web", "args": "tendencias IA 2026",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md\n{{buscar}}", "wires": []},
    ],
}


@pytest.fixture(autouse=True)
def flujoteca_aislada(tmp_path, monkeypatch):
    """La flujoteca vive en disco: sin esto un test podria escribir en
    ~/.cognia/flujoteca, que es la biblioteca real del dueno."""
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    return tmp_path


class Espia:
    """generar_fn de mentira: guarda lo que se le manda y devuelve un guion.

    Guardar el prompt es la unica forma de comprobar que el modelo recibe el
    contexto del que depende la calidad de su respuesta (tools, JSON actual).
    """

    def __init__(self, respuesta="", *, explota=None):
        self.respuesta = respuesta
        self.explota = explota
        self.llamadas = []

    def __call__(self, prompt, system):
        self.llamadas.append((prompt, system))
        if self.explota is not None:
            raise self.explota
        return self.respuesta

    @property
    def prompt(self) -> str:
        return self.llamadas[-1][0]

    @property
    def system(self) -> str:
        return self.llamadas[-1][1]


def _flujo_json(nodos, nombre="informe diario", resumen="hecho") -> str:
    return json.dumps({"nombre": nombre, "resumen": resumen, "nodos": nodos},
                      ensure_ascii=False)


def _copia(flujo: dict) -> dict:
    return json.loads(json.dumps(flujo))


# ---------------------------------------------------------------------------
# 1. _extraer_json
# ---------------------------------------------------------------------------

def test_extraer_json_con_prosa_alrededor():
    bruto = ('Claro, aqui tienes el flujo actualizado:\n'
             '{"nombre": "x", "nodos": []}\n'
             'Avisame si queres otra cosa.')
    assert fia._extraer_json(bruto) == {"nombre": "x", "nodos": []}


def test_extraer_json_con_valla_de_codigo():
    bruto = '```json\n{"nombre": "x", "nodos": [{"id": "a"}]}\n```'
    assert fia._extraer_json(bruto) == {"nombre": "x", "nodos": [{"id": "a"}]}


def test_extraer_json_con_valla_sin_etiqueta():
    bruto = '```\n{"nombre": "y", "nodos": []}\n```'
    assert fia._extraer_json(bruto) == {"nombre": "y", "nodos": []}


def test_extraer_json_ignora_el_razonamiento_delante():
    # El bloque de razonamiento trae llaves propias: si no se borra, el primer
    # "{" del texto es el del razonamiento y el flujo sale de un borrador.
    bruto = ('<think>el usuario quiere {un nodo mas} asi que devuelvo '
             '{"borrador": 1}</think>\n'
             '{"nombre": "real", "nodos": []}')
    assert fia._extraer_json(bruto) == {"nombre": "real", "nodos": []}


def test_extraer_json_de_basura_da_dict_vacio():
    assert fia._extraer_json("no puedo hacer eso, lo siento") == {}
    assert fia._extraer_json("") == {}
    assert fia._extraer_json(None) == {}


def test_extraer_json_sin_cerrar_da_dict_vacio():
    # Se corto por presupuesto de tokens: medio DAG es peor que ninguno.
    assert fia._extraer_json('{"nombre": "x", "nodos": [{"id": "a",') == {}


def test_extraer_json_devuelve_solo_el_primer_objeto_entero():
    bruto = '{"nombre": "uno", "nodos": []}{"nombre": "dos", "nodos": []}'
    assert fia._extraer_json(bruto) == {"nombre": "uno", "nodos": []}


def test_extraer_json_respeta_las_llaves_de_interpolacion():
    bruto = ('{"nombre": "x", "nodos": [{"id": "a", "tool": "escribir_archivo",'
             ' "args": "informe.md {{buscar}}", "wires": []}]}')
    assert fia._extraer_json(bruto)["nodos"][0]["args"].endswith("{{buscar}}")


# ---------------------------------------------------------------------------
# 2. sanear_flujo(): la frontera entre arreglar y rechazar
# ---------------------------------------------------------------------------

def test_sanear_arregla_wires_como_string_suelto():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": "b"},
        {"id": "b", "tool": "escribir_archivo", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    assert flujo["nodos"][0]["wires"] == ["b"]


def test_sanear_arregla_wires_duplicados():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": ["b", "b", "b"]},
        {"id": "b", "tool": "escribir_archivo", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    assert flujo["nodos"][0]["wires"] == ["b"]


def test_sanear_arregla_ids_con_caracteres_raros_y_sus_wires():
    crudo = {"nombre": "x", "nodos": [
        {"id": "Buscar en la web!", "tool": "buscar_web",
         "wires": ["escribir informe"]},
        {"id": "escribir informe", "tool": "escribir_archivo", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    assert [n["id"] for n in flujo["nodos"]] == ["Buscar_en_la_web",
                                                 "escribir_informe"]
    # el wire tiene que apuntar al id YA saneado, si no queda colgado
    assert flujo["nodos"][0]["wires"] == ["escribir_informe"]


def test_sanear_arregla_opcionales_con_el_tipo_mal():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": [],
         "reintentos": "2", "timeout_s": "1.5", "saltar_si": 7, "modelo": 3},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    n = flujo["nodos"][0]
    assert n["reintentos"] == 2 and isinstance(n["reintentos"], int)
    assert n["timeout_s"] == 1.5 and isinstance(n["timeout_s"], float)
    assert n["saltar_si"] == "7" and n["modelo"] == "3"


def test_sanear_descarta_el_opcional_inconvertible_sin_romper_el_flujo():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": [], "reintentos": "muchos"},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    assert "reintentos" not in flujo["nodos"][0]


def test_sanear_arregla_args_que_no_son_texto():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "args": 2026, "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert motivo == ""
    assert flujo["nodos"][0]["args"] == "2026"


def test_sanear_rechaza_un_ciclo():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": ["b"]},
        {"id": "b", "tool": "escribir_archivo", "wires": ["a"]},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert "CICLO" in motivo


def test_sanear_rechaza_un_wire_a_un_nodo_que_no_existe():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": ["fantasma"]},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert "fantasma" in motivo


def test_sanear_rechaza_una_tool_que_no_esta_en_la_lista():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "descargar_pdf", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert "descargar_pdf" in motivo


def test_sanear_rechaza_un_nodo_sin_id():
    crudo = {"nombre": "x", "nodos": [{"tool": "buscar_web", "wires": []}]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert motivo


def test_sanear_rechaza_un_nodo_sin_tool():
    crudo = {"nombre": "x", "nodos": [{"id": "a", "wires": []}]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert motivo


def test_sanear_rechaza_el_nodo_malo_aunque_los_demas_esten_bien():
    # El fallo caro no es el flujo entero roto: es entregar como bueno un
    # flujo al que le falta EN SILENCIO justo el nodo que se pidio anadir.
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": []},
        {"id": "publicar", "wires": []},          # el modelo se dejo la tool
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}, "un flujo mutilado no se entrega como bueno"
    assert motivo


def test_sanear_rechaza_ids_duplicados():
    # flows.validar() los rechaza; quedarse con el primero le escondia el
    # error al unico validador que manda.
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": []},
        {"id": "a", "tool": "escribir_archivo", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert motivo


def test_sanear_rechaza_un_nodo_que_no_es_un_objeto():
    crudo = {"nombre": "x", "nodos": [
        {"id": "a", "tool": "buscar_web", "wires": []},
        "escribir_archivo informe.md",
    ]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS)
    assert flujo == {}
    assert motivo


def test_sanear_rechaza_la_lista_de_nodos_vacia():
    flujo, motivo = sanear_flujo({"nombre": "x", "nodos": []})
    assert motivo == "el modelo devolvio un flujo vacio"
    assert flujo["nodos"] == []


def test_sanear_rechaza_lo_que_ni_siquiera_es_un_flujo():
    assert sanear_flujo("hola")[1]
    assert sanear_flujo(None)[1]
    assert sanear_flujo([])[1]
    assert sanear_flujo({"nombre": "x"})[1] == "el JSON no trae una lista 'nodos'"
    assert sanear_flujo({"nombre": "x", "nodos": "a,b"})[1]


def test_sanear_hereda_el_nombre_previo_si_el_modelo_no_lo_pone():
    crudo = {"nodos": [{"id": "a", "tool": "buscar_web", "wires": []}]}
    flujo, motivo = sanear_flujo(crudo, tool_existe=lambda t: t in TOOLS,
                                 nombre_previo="informe diario")
    assert motivo == ""
    assert flujo["nombre"] == "informe diario"


# ---------------------------------------------------------------------------
# 3. editar(): con ok=False el flujo vuelve EXACTAMENTE como entro
# ---------------------------------------------------------------------------

def _asserta_intacto(res: Resultado, entrada: dict):
    assert res.ok is False
    assert res.flujo == entrada, "el flujo tiene que volver identico"
    assert res.flujo is not entrada, "y no ser el mismo objeto que entro"
    assert res.motivo


def test_editar_instruccion_vacia_no_llama_al_modelo():
    espia = Espia(_flujo_json([]))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "   ", generar_fn=espia, listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))
    assert res.motivo == "no dijiste que cambiar"
    assert espia.llamadas == []


def test_editar_flujo_vacio_no_llama_al_modelo():
    espia = Espia(_flujo_json([]))
    res = editar({"nombre": "vacio", "nodos": []}, "anade un nodo",
                 generar_fn=espia, listar_tools=lambda: TOOLS)
    _asserta_intacto(res, {"nombre": "vacio", "nodos": []})
    assert "vacio" in res.motivo
    assert espia.llamadas == []


def test_editar_con_ciclo_devuelve_el_flujo_original():
    espia = Espia(_flujo_json([
        {"id": "buscar", "tool": "buscar_web", "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo", "wires": ["buscar"]},
    ]))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "que se repita en bucle", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))
    assert "CICLO" in res.motivo


def test_editar_con_tool_inventada_devuelve_el_flujo_original():
    espia = Espia(_flujo_json([
        {"id": "buscar", "tool": "buscar_web", "wires": ["pdf"]},
        {"id": "pdf", "tool": "descargar_pdf", "wires": []},
    ]))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "descarga el pdf", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))
    assert "descargar_pdf" in res.motivo


def test_editar_con_basura_devuelve_el_flujo_original():
    espia = Espia("perdon, no entendi la instruccion")
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "cambia algo", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))
    assert res.bruto, "el crudo se guarda para poder diagnosticar"


def test_editar_con_json_cortado_devuelve_el_flujo_original():
    espia = Espia('{"nombre": "informe diario", "nodos": [{"id": "a",')
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "cambia algo", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))


def test_editar_el_flujo_quedo_igual_no_es_un_error():
    # El modelo puede decidir que la instruccion no se puede cumplir. Eso se
    # cuenta con ok=False y su resumen, no con un mensaje de error.
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"],
                              resumen="no se puede: no hay tool de correo"))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "mandalo por correo", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.motivo == "el flujo quedo igual"
    assert res.resumen == "no se puede: no hay tool de correo"
    assert res.flujo == _copia(FLUJO_BASE)
    assert res.flujo is not entrada


def test_editar_caso_feliz():
    nuevos = [
        {"id": "buscar", "tool": "buscar_web", "args": "tendencias IA 2026",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md\n{{buscar}}", "wires": ["leer"]},
        {"id": "leer", "tool": "leer_archivo", "args": "informe.md",
         "wires": []},
    ]
    espia = Espia(_flujo_json(nuevos, resumen="anadi el nodo de lectura"))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "al final lee el informe", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    assert res.ok is True
    assert res.motivo == "ok"
    assert res.resumen == "anadi el nodo de lectura"
    assert [n["id"] for n in res.flujo["nodos"]] == ["buscar", "escribir",
                                                     "leer"]
    assert res.flujo["nombre"] == "informe diario"
    assert entrada == _copia(FLUJO_BASE), "el flujo de entrada no se muta"
    assert res.ms >= 0
    assert res.a_dict()["ok"] is True


def test_editar_acepta_la_respuesta_envuelta_en_prosa_y_vallas():
    nuevos = [{"id": "leer", "tool": "leer_archivo", "args": "a.md",
               "wires": []}]
    espia = Espia("Listo:\n```json\n" + _flujo_json(nuevos) + "\n```\n"
                  "Espero que sirva.")
    res = editar(_copia(FLUJO_BASE), "dejalo en un solo nodo de lectura",
                 generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is True
    assert [n["id"] for n in res.flujo["nodos"]] == ["leer"]


# ---------------------------------------------------------------------------
# 4. editar() NUNCA lanza
# ---------------------------------------------------------------------------

class _ExplosionRara(Exception):
    pass


@pytest.mark.parametrize("exc", [
    ValueError("json malo"),
    RuntimeError("sin backend local"),
    TimeoutError("se paso de 90s"),
    OSError("conexion rechazada"),
    ConnectionError("no hay ruta al host"),
    ZeroDivisionError("division por cero"),
    KeyError("modelo"),
    _ExplosionRara("cualquier cosa"),
])
def test_editar_nunca_lanza_aunque_generar_explote(exc):
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "cambia algo", generar_fn=Espia(explota=exc),
                 listar_tools=lambda: TOOLS)
    _asserta_intacto(res, _copia(FLUJO_BASE))
    assert type(exc).__name__ in res.motivo


@pytest.mark.parametrize("exc", [RuntimeError("boom"), OSError("red caida")])
def test_de_sesion_nunca_lanza_aunque_generar_explote(exc):
    res = de_sesion([{"role": "user", "content": "hace algo"}],
                    generar_fn=Espia(explota=exc), listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.flujo == {}
    assert type(exc).__name__ in res.motivo


def test_editar_avisa_cuando_la_respuesta_se_corto_por_presupuesto(monkeypatch):
    # finish_reason lo escribe el backend real en `registro`; el unico modo de
    # imitarlo sin backend es entrar por _generar, que es quien lo recibe.
    def _generar_cortado(prompt, system, *, url, timeout_s, generar_fn,
                         registro, completar_fn=None, **kw):
        registro["finish_reason"] = "length"
        return generar_fn(prompt, system)

    monkeypatch.setattr(fia, "_generar", _generar_cortado)
    espia = Espia(_flujo_json([{"id": "a", "tool": "buscar_web",
                                "wires": []}]))
    entrada = _copia(FLUJO_BASE)
    res = editar(entrada, "hace un flujo enorme", generar_fn=espia,
                 listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert "presupuesto de tokens" in res.motivo
    assert res.flujo == _copia(FLUJO_BASE)


# ---------------------------------------------------------------------------
# 5. El prompt que recibe el modelo
# ---------------------------------------------------------------------------

def test_el_prompt_de_editar_lleva_descripcion_json_tools_e_instruccion():
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "anade un nodo que lea el informe",
           generar_fn=espia, listar_tools=lambda: TOOLS)
    assert len(espia.llamadas) == 1
    p = espia.prompt

    from cognia.agent import flujoteca as _ft
    assert _ft.describir(FLUJO_BASE) in p, "falta la descripcion legible"
    assert json.dumps(FLUJO_BASE, ensure_ascii=False) in p, "falta el JSON"
    for t in TOOLS:
        assert t in p, f"falta la tool {t} en la lista"
    assert "usa SOLO estas" in p
    assert "Instruccion del usuario:" in p
    assert "anade un nodo que lea el informe" in p

    # y el system es el del editor, con el formato y las reglas duras
    assert "editor de flujos" in espia.system
    assert "ACICLICO" in espia.system


def test_el_prompt_de_editar_no_inventa_lista_de_tools_si_no_hay():
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: [])
    assert "Tools disponibles" not in espia.prompt


# ---------------------------------------------------------------------------
# 6. resumir_sesion(): recorta por el MEDIO
# ---------------------------------------------------------------------------

def test_resumir_sesion_recorta_por_el_medio_no_por_el_final():
    historial = [{"role": "user" if i % 2 == 0 else "assistant",
                  "content": f"turno-{i:02d}"} for i in range(60)]
    texto = fia.resumir_sesion(historial)

    assert "turno-00" in texto, "el principio trae el objetivo"
    assert "turno-59" in texto, "el final trae el resultado"
    assert "turno-30" not in texto, "lo de en medio es lo que sobra"
    assert "omitidos" in texto and "20 turnos" in texto

    i_ini = texto.index("turno-00")
    i_marca = texto.index("omitidos")
    i_fin = texto.index("turno-59")
    assert i_ini < i_marca < i_fin


def test_resumir_sesion_corta_no_toca_nada():
    historial = [{"role": "user", "content": "hola"},
                 {"role": "assistant", "content": "que tal"}]
    assert fia.resumir_sesion(historial) == "USUARIO: hola\nCOGNIA: que tal"


def test_resumir_sesion_vacia_da_cadena_vacia():
    assert fia.resumir_sesion([]) == ""
    assert fia.resumir_sesion(None) == ""
    assert fia.resumir_sesion([{"role": "user", "content": "   "}]) == ""
    assert fia.resumir_sesion(["no soy un turno"]) == ""


def test_resumir_sesion_respeta_el_tope_de_chars():
    historial = [{"role": "user", "content": "x" * 300} for _ in range(30)]
    assert len(fia.resumir_sesion(historial, tope_chars=500)) == 500


# ---------------------------------------------------------------------------
# 7. de_sesion()
# ---------------------------------------------------------------------------

HISTORIAL = [
    {"role": "user", "content": "busca tendencias de IA y escribime informe.md"},
    {"role": "assistant", "content": "listo, quedo en informe.md"},
]


def test_de_sesion_caso_feliz():
    nodos = [
        {"id": "buscar", "tool": "buscar_web", "args": "tendencias IA",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md\n{{buscar}}", "wires": []},
    ]
    espia = Espia(_flujo_json(nodos, nombre="informe semanal",
                              resumen="dos pasos: buscar y escribir"))
    res = de_sesion(HISTORIAL, nombre="informe semanal", generar_fn=espia,
                    listar_tools=lambda: TOOLS)
    assert res.ok is True
    assert res.motivo == "ok"
    assert res.flujo["nombre"] == "informe semanal"
    assert [n["id"] for n in res.flujo["nodos"]] == ["buscar", "escribir"]
    assert res.resumen == "dos pasos: buscar y escribir"
    assert "analista" in espia.system


def test_de_sesion_vacia_y_sin_pasos_no_llama_al_modelo():
    espia = Espia(_flujo_json([]))
    res = de_sesion([], generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.flujo == {}
    assert "vacia" in res.motivo
    assert espia.llamadas == []


def test_de_sesion_con_nodos_vacios_da_el_motivo_DEL_MODELO():
    # El prompt contempla "si la sesion no tiene trabajo reproducible": un
    # error generico taparia la unica explicacion util que hay.
    espia = Espia(json.dumps({
        "nombre": "", "nodos": [],
        "resumen": "solo hubo preguntas, no se ejecuto ningun trabajo"}))
    res = de_sesion(HISTORIAL, generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.motivo == "solo hubo preguntas, no se ejecuto ningun trabajo"
    assert "flujo vacio" not in res.motivo


def test_de_sesion_con_nodos_vacios_y_sin_resumen_da_una_frase_util():
    espia = Espia(json.dumps({"nombre": "", "nodos": []}))
    res = de_sesion(HISTORIAL, generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.motivo == "esta sesion no tiene trabajo reproducible"


def test_de_sesion_pone_los_pasos_reales_como_lo_que_mas_pesa():
    pasos = [{"tool": "buscar_web", "args": "tendencias IA", "ok": True},
             {"tool": "escribir_archivo", "args": "informe.md", "ok": False}]
    espia = Espia(_flujo_json([{"id": "a", "tool": "buscar_web", "wires": []}]))
    de_sesion(HISTORIAL, pasos_reales=pasos, generar_fn=espia,
              listar_tools=lambda: TOOLS)
    p = espia.prompt
    assert "se EJECUTARON de verdad" in p
    assert "esto es lo que mas peso tiene" in p
    assert "1. buscar_web" in p and "2. escribir_archivo" in p
    assert "[fallo]" in p, "un paso que fallo se marca"
    # y van ANTES de la conversacion: lo ejecutado es un hecho, lo dicho una
    # intencion
    assert p.index("se EJECUTARON") < p.index("Conversacion de la sesion")
    assert "tendencias de IA" in p


def test_de_sesion_solo_con_pasos_reales_sigue_funcionando():
    espia = Espia(_flujo_json([{"id": "a", "tool": "buscar_web", "wires": []}]))
    res = de_sesion([], pasos_reales=["buscar_web tendencias"],
                    generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is True
    assert "buscar_web tendencias" in espia.prompt


def test_de_sesion_rechaza_un_flujo_con_ciclo():
    espia = Espia(_flujo_json([
        {"id": "a", "tool": "buscar_web", "wires": ["b"]},
        {"id": "b", "tool": "escribir_archivo", "wires": ["a"]},
    ]))
    res = de_sesion(HISTORIAL, generar_fn=espia, listar_tools=lambda: TOOLS)
    assert res.ok is False
    assert res.flujo == {}
    assert "CICLO" in res.motivo


# ---------------------------------------------------------------------------
# 8. Contrato de pureza
# ---------------------------------------------------------------------------

def _arbol():
    return ast.parse(Path(fia.__file__).read_text(encoding="utf-8"))


def test_el_modulo_no_importa_el_cli():
    # Es un modulo PURO: si importa el CLI deja de poder usarse desde un
    # workflow, un test o el servidor, que es donde mas falta hace.
    for nodo in ast.walk(_arbol()):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                assert not a.name.startswith("cognia.cli"), a.name
        elif isinstance(nodo, ast.ImportFrom):
            mod = nodo.module or ""
            assert not mod.startswith("cognia.cli"), mod
            if mod == "cognia":
                assert all(a.name != "cli" for a in nodo.names)


def test_el_modulo_no_imprime():
    # Quien llama decide como se muestra el resultado (Rich, JSON, log). Un
    # print aqui ensucia el stdout de cualquier consumidor no interactivo.
    for nodo in ast.walk(_arbol()):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            assert nodo.func.id != "print", f"print en la linea {nodo.lineno}"


# ---------------------------------------------------------------------------
# El ejemplo del prompt tiene que usar tools que EXISTAN
# ---------------------------------------------------------------------------

def test_el_ejemplo_del_prompt_usa_tools_reales():
    """REGRESION del bug que cazo el e2e del 2026-08-28.

    El ejemplo de _FORMATO decia "buscar_web", que no esta en el registro. El
    modelo copia los nombres del ejemplo, asi que TODOS los flujos generados
    salian con esa tool y `flows.validar()` los rechazaba enteros: sesion ->
    flujo y edicion conversacional no funcionaban NUNCA contra el modelo real,
    aunque los tests con generar_fn inyectado pasaran todos.
    """
    import re

    from cognia.agent import flujo_ia as fia

    reales = set(fia._tools_disponibles())
    if not reales:
        import pytest
        pytest.skip("no se pudo leer el registro de tools")
    usadas = set(re.findall(r'"tool":\s*"([a-z_]+)"', fia._FORMATO))
    assert usadas, "el ejemplo del prompt no declara ninguna tool"
    inventadas = usadas - reales
    assert not inventadas, (
        f"el ejemplo del prompt usa tools que no existen: {sorted(inventadas)}. "
        f"El modelo las copia y todos los flujos generados se rechazan.")


def test_el_ejemplo_del_prompt_separa_los_args_con_barra_y_no_con_salto():
    """LA CAUSA RAIZ de "los workflows no entregan nada" (PLAN2 5.1).

    Los dos ejemplos de este modulo ensenaban un args con un SALTO DE LINEA
    entre la ruta y el contenido, y `escribir_archivo` exige "ruta | texto".
    El modelo copia la FORMA del ejemplo igual que copia los nombres, asi que
    todo flujo que escribiera un fichero moria en ejecucion con "ERROR:
    formato" -- y el dueno veia un flujo que "no hace nada en mi PC".
    Contrafactual medido el 2026-08-29: el mismo flujo, con lo unico cambiado
    el separador, deja informe.md de 1001 bytes y 0 errores.

    Se miran los DOS prompts porque el que corre primero es el del delta
    (`_SYSTEM_DELTA`), que tiene su propio ejemplo de `cambiar_args` y no
    incluye `_FORMATO`.
    """
    import re

    from cognia.agent import flujo_ia as fia

    salto = chr(92) + "n"          # el literal de dos caracteres del prompt
    rx = re.compile(r'"args"\s*:\s*"([^"]*)"')
    for nombre, texto in (("_FORMATO", fia._FORMATO),
                          ("_SYSTEM_DELTA", fia._SYSTEM_DELTA)):
        ejemplos = rx.findall(texto)
        assert ejemplos, f"{nombre} no trae ni un ejemplo de args"
        con_pipe = [a for a in ejemplos if " | " in a]
        assert con_pipe, (
            f"{nombre} no ensena ni una vez el separador ' | ': el modelo no "
            f"tiene de donde copiar la forma de los args posicionales")
        con_salto = [a for a in ejemplos if salto in a]
        assert con_salto == [], (
            f"{nombre} sigue ensenando el salto de linea como separador de "
            f"argumentos: {con_salto}. La tool recibe UN solo argumento y "
            f"el nodo muere en ejecucion.")

    # Y la convencion esta DECLARADA como regla, no solo insinuada en un
    # ejemplo: un ejemplo correcto sin regla se pierde en cuanto la tarea no
    # se parece al ejemplo.
    for nombre, texto in (("_FORMATO", fia._FORMATO),
                          ("_SYSTEM_DELTA", fia._SYSTEM_DELTA)):
        plano = " ".join(texto.upper().split())
        assert "SALTO DE LINEA NO SEPARA ARGUMENTOS" in plano, nombre
        assert '" | "' in texto, nombre


# ---------------------------------------------------------------------------
# 9. El catalogo RICO en el prompt de editar()
# ---------------------------------------------------------------------------
# Antes, el prompt daba solo nombres: ", ".join(sorted(tools)[:120]). El
# modelo acertaba la tool y se inventaba la FORMA de los args, que en Cognia
# es un protocolo de texto posicional ("path | contenido"), no un JSON. Ahora
# va la firma y una linea de descripcion. `catalogo_nodos` es de otro
# subsistema (la paleta del editor visual), asi que se importa TOLERANTE:
# estos tests fijan que editar() funcione con el catalogo y sin el.

_CATALOGO_FALSO = [
    {"nombre": "escribir_archivo",
     "descripcion": "Escribe un fichero entero.\nPisa lo que hubiera.",
     "params": [{"nombre": "path", "requerido": True},
                {"nombre": "contenido", "requerido": True}]},
    {"nombre": "leer_archivo", "descripcion": "Lee un fichero de texto.",
     "params": [{"nombre": "path", "requerido": True},
                {"nombre": "limit", "requerido": False}]},
]


def _catalogo(monkeypatch, entradas):
    from cognia.agent import catalogo_nodos as cn
    monkeypatch.setattr(cn, "catalogo", lambda allowed=None: entradas)


def test_el_prompt_de_editar_lleva_la_firma_de_cada_tool(monkeypatch):
    _catalogo(monkeypatch, _CATALOGO_FALSO)
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))

    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: TOOLS)
    p = espia.prompt

    assert "escribir_archivo(path, contenido)" in p
    assert "leer_archivo(path, limit?)" in p, "el opcional se marca con ?"
    assert "Escribe un fichero entero. Pisa lo que hubiera." in p, \
        "la descripcion va en UNA linea: un salto rompe la lista"
    # y la tool que no esta en el catalogo se sigue nombrando
    assert "- buscar_web" in p
    assert "usa SOLO estas" in p


def test_el_prompt_cae_a_los_nombres_si_el_catalogo_falla(monkeypatch):
    """El catalogo puede no estar implementado todavia, o reventar leyendo el
    registro. Eso NO puede dejar sin editor conversacional al dueno."""
    def _explota(allowed=None):
        raise NotImplementedError("todavia no")

    _catalogo(monkeypatch, None)                      # devuelve None -> vacio
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: TOOLS)
    assert ", ".join(sorted(TOOLS)) in espia.prompt

    from cognia.agent import catalogo_nodos as cn
    monkeypatch.setattr(cn, "catalogo", _explota)
    espia2 = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia2,
           listar_tools=lambda: TOOLS)

    p = espia2.prompt
    assert ", ".join(sorted(TOOLS)) in p
    assert "usa SOLO estas" in p
    for t in TOOLS:
        assert t in p


def test_el_prompt_cae_a_los_nombres_si_el_modulo_no_existe(monkeypatch):
    """El caso del dia que se escribio esto: `catalogo_nodos` lo esta
    escribiendo otro agente y puede no estar en el arbol."""
    import sys

    monkeypatch.setitem(sys.modules, "cognia.agent.catalogo_nodos", None)
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))

    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: TOOLS)

    assert ", ".join(sorted(TOOLS)) in espia.prompt


def test_el_catalogo_rico_respeta_el_tope_y_la_lista_de_quien_llama(monkeypatch):
    """La lista la manda quien llama (listar_tools), no el catalogo: el
    editor puede estar sirviendo un subconjunto, y ofrecerle al modelo tools
    de mas hace que el flujo se rechace entero al validarlo."""
    _catalogo(monkeypatch, _CATALOGO_FALSO + [
        {"nombre": "borrar_archivo", "descripcion": "Borra.", "params": []}])
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))

    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: ["leer_archivo"])

    p = espia.prompt
    assert "leer_archivo(path, limit?)" in p
    assert "borrar_archivo" not in p

    muchas = ["tool_%03d" % i for i in range(200)]
    espia2 = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia2,
           listar_tools=lambda: muchas)
    assert "tool_119" in espia2.prompt
    assert "tool_120" not in espia2.prompt


# ---------------------------------------------------------------------------
# 10. completar_fn: JSON por gramatica, opcional y retro-compatible
# ---------------------------------------------------------------------------

class _Resp:
    """Lo que devuelve chat_client.completar, en lo que mira flujo_ia."""

    def __init__(self, texto="", error="", finish_reason="stop", modelo="fake"):
        self.texto = texto
        self.error = error
        self.finish_reason = finish_reason
        self.modelo = modelo


class Completador:
    def __init__(self, resp):
        self.resp = resp
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append((mensajes, kw))
        return self.resp


def test_completar_fn_pide_json_schema_strict_con_el_esquema_del_dag():
    """El RESPALDO (pedir el DAG entero) sigue pidiendolo por gramatica.

    Es la segunda llamada, no la primera: desde el 2026-08-29 el primer
    intento es el delta. Un `completar_fn` que contesta con el flujo entero
    (como este) no trae 'ops', el delta se descarta y entra el respaldo -- que
    es exactamente el camino que este test fija.
    """
    nodos = _copia(FLUJO_BASE)["nodos"] + [
        {"id": "leer", "tool": "leer_archivo", "args": "informe.md",
         "wires": []}]
    comp = Completador(_Resp(_flujo_json(nodos)))

    res = editar(_copia(FLUJO_BASE), "al final lee el informe",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "flujo entero"
    assert [n["id"] for n in res.flujo["nodos"]] == ["buscar", "escribir",
                                                     "leer"]

    assert len(comp.llamadas) == 2
    mensajes, kw = comp.llamadas[1]
    assert [m["role"] for m in mensajes] == ["system", "user"]
    assert "editor de flujos" in mensajes[0]["content"]
    assert "Devuelves el flujo COMPLETO" in mensajes[0]["content"]
    assert "al final lee el informe" in mensajes[1]["content"]
    rf = kw["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "flujo"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] is fia.ESQUEMA_FLUJO
    assert kw["max_tokens"] == fia.N_PREDICT
    assert kw["temperature"] == fia.TEMPERATURA


def test_generar_fn_gana_a_completar_fn():
    """Los ~25 tests del modulo inyectan generar_fn: si completar_fn se le
    adelantara, este fichero entero mediria otra cosa."""
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"][:1]))
    comp = Completador(_Resp("{}"))

    editar(_copia(FLUJO_BASE), "quita el ultimo paso", generar_fn=espia,
           completar_fn=comp, listar_tools=lambda: TOOLS)

    assert len(espia.llamadas) == 1
    assert comp.llamadas == []


def test_completar_fn_con_error_devuelve_el_flujo_intacto():
    comp = Completador(_Resp(error="connection refused"))
    entrada = _copia(FLUJO_BASE)

    res = editar(entrada, "cambia algo", completar_fn=comp,
                 listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert "connection refused" in res.motivo
    assert res.flujo == FLUJO_BASE


def test_completar_fn_cortado_por_presupuesto_lo_dice():
    comp = Completador(_Resp('{"nombre": "x", "nodos": [',
                             finish_reason="length"))

    res = editar(_copia(FLUJO_BASE), "hace un flujo enorme",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert "presupuesto de tokens" in res.motivo


def test_de_sesion_tambien_acepta_completar_fn():
    comp = Completador(_Resp(_flujo_json(FLUJO_BASE["nodos"],
                                         nombre="sesion")))

    res = de_sesion([{"role": "user", "content": "busca y escribe informe"}],
                    nombre="sesion", completar_fn=comp,
                    listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.flujo["nombre"] == "sesion"
    assert comp.llamadas[0][1]["response_format"]["type"] == "json_schema"


def test_el_esquema_declara_lo_mismo_que_acepta_sanear_flujo():
    """ANTICUERPO: el esquema y el saneador son dos descripciones de la misma
    forma. Si alguien anade un campo al nodo y solo toca una de las dos, el
    modelo con gramatica no podra emitirlo NUNCA y el fallo sera invisible
    (saldra un flujo valido, sin ese campo)."""
    items = fia.ESQUEMA_FLUJO["properties"]["nodos"]["items"]
    props = items["properties"]

    assert set(props) == {"id", "tool", "args", "wires", "saltar_si",
                          "reintentos", "timeout_s", "modelo"}
    assert set(items["required"]) == {"id", "tool", "args", "wires"}
    assert set(fia.ESQUEMA_FLUJO["required"]) == {"nombre", "resumen", "nodos"}

    # y lo que produce sanear_flujo cabe en el esquema, campo a campo
    limpio, motivo = sanear_flujo(
        {"nombre": "x", "nodos": [
            {"id": "a", "tool": "leer_archivo", "args": "x", "wires": [],
             "saltar_si": "ERROR", "reintentos": 2, "timeout_s": 1.5,
             "modelo": "27b"}]},
        tool_existe=lambda t: True)
    assert motivo == ""
    assert set(limpio["nodos"][0]) <= set(props)


# ---------------------------------------------------------------------------
# 11. La firma no puede AFIRMAR que una tool no lleva argumentos
# ---------------------------------------------------------------------------
# Los tests de la seccion 9 inyectan un catalogo FALSO en el que todas las
# entradas traen `params` declarados. Ninguno cruzaba contra el registro REAL,
# y por eso pasaban por el motivo equivocado: en `tools.catalogo_schemas` la
# lista vacia de params significa "la tool solo declara su doc de una linea"
# (params NO declarados), y `_firma_de` la leia como "cero parametros" y
# emitia "tool()". Medido el 2026-08-29: 33 de las 70 tools del registro por
# defecto. Estos tests corren contra el registro de verdad.

def _entrada_real(nombre: str) -> dict:
    from cognia.agent import catalogo_nodos as cn
    for e in cn.catalogo():
        if e.get("nombre") == nombre:
            return e
    raise AssertionError(f"la tool '{nombre}' ya no esta en el catalogo real")


def test_la_firma_saca_la_forma_de_los_args_del_doc_si_no_hay_params():
    """El doc es el UNICO sitio donde vive la forma de los args de esas 33
    tools, y `catalogo_nodos._una_linea` se queda solo con lo de despues del
    ' -- ', que es justo la mitad que NO la trae."""
    docs = fia._docs_de_tools()
    for nombre, esperado in (
            ("copiar_archivo", "copiar_archivo <src> | <dst>"),
            ("kg_agregar", "kg_agregar <sujeto> | <relacion> | <objeto>"),
            ("http_get", "http_get <url>")):
        e = _entrada_real(nombre)
        assert e["params"] == [], f"{nombre} ya declara params: elegi otra"
        assert fia._firma_de(e, docs[nombre]) == esperado


def test_la_tool_que_de_verdad_no_lleva_args_sale_a_secas():
    """Sin plantilla que sacar, el nombre pelado: es NEUTRO. '()' seria una
    afirmacion, y la afirmacion es lo que se le cuela al modelo."""
    docs = fia._docs_de_tools()
    for nombre in ("fecha", "git_estado", "notas", "procesos"):
        firma = fia._firma_de(_entrada_real(nombre), docs[nombre])
        assert firma == nombre
        assert "(" not in firma


def test_ninguna_tool_del_registro_real_se_anuncia_como_si_no_llevara_args():
    """ANTICUERPO contra el fallo de hoy, con el registro REAL (no un fake).

    Escenario que evita: "copia notas.md a notas.bak" -> el prompt dice
    'copiar_archivo(): copia un archivo' -> el modelo emite args vacios ->
    flows.validar no mira los args -> el flujo se guarda con 200 y el dueno
    lo descubre al EJECUTARLO.
    """
    from cognia.agent import tools as _tools

    nombres = sorted(_tools.TOOLS)[:fia.TOPE_TOOLS_PROMPT]
    lineas = fia._lineas_de_tools(nombres)
    assert len(lineas) == len(nombres), \
        "el catalogo real no llego: esto estaria midiendo el fallback"

    vacias = [l for l in lineas if "()" in l]
    assert vacias == [], (
        f"{len(vacias)} tools se anuncian como si no llevaran argumentos: "
        f"{vacias[:3]}")

    docs = fia._docs_de_tools()
    esquemas = {e["nombre"]: e for e in _tools.catalogo_schemas()}
    sin_params = [n for n in nombres if not esquemas[n]["params"]]
    assert len(sin_params) >= 20, (
        "si casi ninguna tool tiene los params sin declarar, este test ya no "
        "vigila nada: revisar")

    por_nombre = {}
    for linea in lineas:
        cuerpo = linea[2:]
        por_nombre[re.split(r"[ (:]", cuerpo, maxsplit=1)[0]] = cuerpo
    mudas = []
    for n in sin_params:
        uso = fia._sintaxis_de_doc(n, docs.get(n, ""))
        if uso and uso != n and not por_nombre[n].startswith(uso):
            mudas.append((n, uso, por_nombre[n][:60]))
    assert mudas == [], f"la plantilla de uso no llego al prompt: {mudas}"


def test_el_prompt_de_editar_lleva_la_forma_real_de_los_args():
    """De punta a punta con el catalogo de verdad, sin monkeypatch: es lo que
    ve el modelo cuando el editor pide una edicion."""
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))

    editar(_copia(FLUJO_BASE), "copia el informe a informe.bak",
           generar_fn=espia,
           listar_tools=lambda: ["copiar_archivo", "escribir_archivo",
                                 "http_get", "buscar_web"])
    p = espia.prompt

    assert "copiar_archivo <src> | <dst>" in p
    assert "copiar_archivo()" not in p
    assert "http_get <url>" in p
    assert "http_get()" not in p


def test_la_sintaxis_solo_se_saca_de_un_doc_con_plantilla_de_verdad():
    """Un doc sin ' -- ' o que no empieza por el nombre NO es una plantilla de
    uso: devolverlo como firma seria inventarle una forma a los args."""
    assert fia._sintaxis_de_doc("x", "x <a> | <b>  -- hace algo") == \
        "x <a> | <b>"
    assert fia._sintaxis_de_doc("x", "hace algo con <a>") == ""
    assert fia._sintaxis_de_doc("x", "otra <a> -- hace algo") == ""
    assert fia._sintaxis_de_doc("x", "x <a> --") == ""
    assert fia._sintaxis_de_doc("x", "") == ""
    assert fia._sintaxis_de_doc("", "x <a> -- y") == ""


def test_una_entrada_con_params_que_no_son_lista_no_rompe_la_firma():
    """`_firma_de` corre FUERA del try que envuelve al modelo: un TypeError
    aqui rompe el 'editar() NUNCA lanza' del contrato publico."""
    assert fia._firma_de({"nombre": "t", "params": 7}) == "t"
    assert fia._firma_de({"nombre": "t", "params": "path|texto"}) == "t"
    assert fia._firma_de({"nombre": "t", "params": [None, 3],
                          "doc": "t <a> -- hace algo"}) == "t <a>"


# El flujo de un solo nodo, con el wire ya quitado: recortar
# FLUJO_BASE["nodos"][:1] deja el wire colgado a "escribir" y flows.validar
# lo rechaza (con razon).
_SOLO_BUSCAR = [{"id": "buscar", "tool": "buscar_web",
                 "args": "tendencias IA 2026", "wires": []}]


def test_si_el_armado_de_la_lista_revienta_editar_sigue_editando(monkeypatch):
    """Lo mismo, pero por el camino publico y para cualquier fallo del armado,
    no solo el de los params: se degrada a la lista de nombres de siempre."""
    def _explota(entrada, doc=""):
        raise TypeError("params no iterable")

    _catalogo(monkeypatch, _CATALOGO_FALSO)
    monkeypatch.setattr(fia, "_firma_de", _explota)
    espia = Espia(_flujo_json(_SOLO_BUSCAR))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso", generar_fn=espia,
                 listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert ", ".join(sorted(TOOLS)) in espia.prompt


# ---------------------------------------------------------------------------
# 12. De que modelo salio la edicion
# ---------------------------------------------------------------------------
# `RespuestaChat` NO tiene campo `modelo` (texto, tool_calls, finish_reason,
# usage, reasoning_content, error, duracion_s, cortado, tool_calls_parciales,
# usage_estimado, usage_via, frames_malformados). El getattr con default ""
# lo tapaba: por la via estructurada -- la de por DEFECTO en el editor -- el
# chat devolvia siempre modelo vacio y no se distinguia de "no se sabe nada".

class _RespSinModelo:
    """Como la RespuestaChat de verdad: sin campo `modelo`."""

    def __init__(self, texto=""):
        self.texto = texto
        self.error = ""
        self.finish_reason = "stop"


def test_el_modelo_sale_de_la_respuesta_cuando_la_respuesta_lo_trae():
    assert fia._modelo_de(_Resp(modelo="qwen3.8-27b")) == "qwen3.8-27b"


def test_la_via_estructurada_saca_el_modelo_del_backend(monkeypatch):
    """Es de donde lo saca la via de texto plano: el `model` que devuelve
    llama-server. Las dos ramas tienen que contestar lo mismo."""
    from cognia.agent import chat_client as cc
    monkeypatch.setattr(cc, "_modelo_servido",
                        lambda url="": "qwen3.8-27b-q4.gguf")
    comp = Completador(_RespSinModelo(_flujo_json(_SOLO_BUSCAR)))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.modelo == "qwen3.8-27b-q4.gguf"


def test_si_no_se_puede_saber_el_modelo_se_dice_en_vez_de_dejarlo_vacio(
        monkeypatch):
    from cognia.agent import chat_client as cc
    monkeypatch.setattr(cc, "_modelo_servido", lambda url="": "")
    comp = Completador(_RespSinModelo(_flujo_json(_SOLO_BUSCAR)))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.modelo == fia.MODELO_DESCONOCIDO == "desconocido"
    assert res.a_dict()["modelo"] == "desconocido"


# ---------------------------------------------------------------------------
# 12. EL DELTA (2026-08-29): pedir OPERACIONES en vez del DAG entero
#
# POR QUE, MEDIDO contra el :8080 con Qwen3.8-27B-Ridge: el chat del editor
# visual no podia editar un flujo de 7 nodos (5 de 6 casos daban "no cupo en
# el presupuesto de tokens"). Instrumentado, el JSON de salida costaba 82-405
# tokens y el RAZONAMIENTO 1.300-8.192. Dos arreglos distintos, los dos aqui:
# el delta hace el coste de salida constante (244-309 tokens para flujos de 2
# a 20 nodos) y `_kwargs_sin_pensar` apaga el canal que se comia el resto.
#
# Estos tests NO tocan el backend: inyectan `completar_fn`, igual que los del
# apartado 10.
# ---------------------------------------------------------------------------

def _delta_json(ops, resumen="lo que pediste"):
    return json.dumps({"resumen": resumen, "ops": ops}, ensure_ascii=False)


class Turnos:
    """completar_fn que contesta una cosa distinta en cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append((mensajes, kw))
        i = min(len(self.llamadas) - 1, len(self.respuestas) - 1)
        return self.respuestas[i]


@pytest.fixture(autouse=True)
def perfil_con_pensamiento(monkeypatch):
    """El perfil del modelo decide COMO se apaga el pensamiento. Se fija aqui
    para que estos tests midan el modulo y no el modelo que este servido."""
    from cognia.agent import model_profiles as _mp
    monkeypatch.setattr(_mp, "perfil_del_agente",
                        lambda *a, **k: {"kwargs_plantilla":
                                         {"enable_thinking": True}})


def test_el_primer_intento_es_el_delta_con_su_esquema_y_su_presupuesto():
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "escribir",
                                      "args": "otro.md"}])))

    res = editar(_copia(FLUJO_BASE), "guarda en otro.md",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "delta"
    assert len(comp.llamadas) == 1, "el respaldo no tiene que llegar a correr"
    mensajes, kw = comp.llamadas[0]
    assert "SOLO la lista de OPERACIONES" in mensajes[0]["content"]
    rf = kw["response_format"]
    assert rf["json_schema"]["name"] == "delta"
    assert rf["json_schema"]["schema"] is fia.ESQUEMA_DELTA
    assert rf["json_schema"]["strict"] is True
    assert kw["max_tokens"] == fia.N_PREDICT_DELTA


def test_un_delta_valido_se_aplica_sobre_el_flujo_real():
    comp = Turnos(_Resp(_delta_json([
        {"op": "anadir_nodo", "id": "leer", "tool": "leer_archivo",
         "args": "informe.md"},
        {"op": "conectar", "de": "escribir", "a": "leer"}],
        resumen="anadi la lectura final")))

    res = editar(_copia(FLUJO_BASE), "al final lee el informe",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "delta"
    assert res.resumen == "anadi la lectura final"
    assert [n["id"] for n in res.flujo["nodos"]] == ["buscar", "escribir",
                                                     "leer"]
    assert res.flujo["nodos"][1]["wires"] == ["leer"]
    assert res.flujo["nodos"][2] == {"id": "leer", "tool": "leer_archivo",
                                     "args": "informe.md", "wires": []}
    assert res.flujo["nombre"] == "informe diario"


def test_el_delta_intercala_un_nodo_entre_dos_con_las_cuatro_operaciones():
    """El caso que el editor ofrece en su primera pantalla ('mete una busqueda
    web antes de resumir'): el nodo nuevo va EN MEDIO, no al final."""
    comp = Turnos(_Resp(_delta_json([
        {"op": "anadir_nodo", "id": "medio", "tool": "leer_archivo",
         "args": "notas.md"},
        {"op": "desconectar", "de": "buscar", "a": "escribir"},
        {"op": "conectar", "de": "buscar", "a": "medio"},
        {"op": "conectar", "de": "medio", "a": "escribir"}])))

    res = editar(_copia(FLUJO_BASE), "mete un paso en medio",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    porid = {n["id"]: n for n in res.flujo["nodos"]}
    assert porid["buscar"]["wires"] == ["medio"]
    assert porid["medio"]["wires"] == ["escribir"]
    assert porid["escribir"]["wires"] == []


def test_el_delta_conecta_aunque_el_nodo_destino_se_cree_despues():
    """El modelo emite el `conectar` antes del `anadir_nodo` mas a menudo de
    lo que parece. Un delta correcto no se puede rechazar por el ORDEN."""
    comp = Turnos(_Resp(_delta_json([
        {"op": "conectar", "de": "escribir", "a": "leer"},
        {"op": "anadir_nodo", "id": "leer", "tool": "leer_archivo",
         "args": "informe.md"}])))

    res = editar(_copia(FLUJO_BASE), "al final lee el informe",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert {n["id"] for n in res.flujo["nodos"]} == {"buscar", "escribir",
                                                     "leer"}


def test_un_delta_que_no_se_aplica_no_toca_el_flujo_y_entra_el_respaldo():
    entrada = _copia(FLUJO_BASE)
    nodos = _copia(FLUJO_BASE)["nodos"] + [
        {"id": "leer", "tool": "leer_archivo", "args": "informe.md",
         "wires": []}]
    comp = Turnos(
        _Resp(_delta_json([{"op": "borrar_nodo", "id": "fantasma"}])),
        _Resp(_flujo_json(nodos)))

    res = editar(entrada, "al final lee el informe",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert entrada == FLUJO_BASE, "el delta invalido no puede tocar la entrada"
    assert len(comp.llamadas) == 2
    segundo = comp.llamadas[1][1]["response_format"]["json_schema"]["name"]
    assert segundo == "flujo"
    assert res.ok, res.motivo
    assert res.via == "flujo entero"
    assert [n["id"] for n in res.flujo["nodos"]] == ["buscar", "escribir",
                                                     "leer"]


def test_el_respaldo_entra_cuando_el_modelo_no_devuelve_ops():
    nodos = _copia(FLUJO_BASE)["nodos"][:1]
    nodos[0] = dict(nodos[0], wires=[])
    comp = Turnos(_Resp('{"resumen": "hecho"}'), _Resp(_flujo_json(nodos)))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "flujo entero"
    assert len(comp.llamadas) == 2


def test_si_el_respaldo_tambien_falla_el_motivo_cuenta_los_DOS_fallos():
    """Un "no se pudo" a secas esconde cual de los dos caminos se rompio, que
    es justo lo que hace falta para arreglarlo."""
    comp = Turnos(
        _Resp(_delta_json([{"op": "borrar_nodo", "id": "fantasma"}])),
        _Resp('{"nombre": "x", "nodos": "esto no es una lista"}'))

    res = editar(_copia(FLUJO_BASE), "hace magia",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert res.via == "flujo entero"
    assert "no trae una lista 'nodos'" in res.motivo
    assert "por operaciones" in res.motivo and "fantasma" in res.motivo
    assert res.flujo == FLUJO_BASE


def test_ops_vacio_es_legitimo_y_NO_dispara_el_respaldo():
    """El caso 3 del e2e: 'anade un paso que escriba en informe.md' sobre un
    flujo que ya lo escribe. Reintentar con el DAG entero seria pagar otro
    turno de modelo por preguntar lo mismo."""
    comp = Turnos(_Resp(_delta_json([], resumen="ya existe 'escribir'")))

    res = editar(_copia(FLUJO_BASE), "escribi el resultado en informe.md",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert res.motivo == "el flujo quedo igual"
    assert res.resumen == "ya existe 'escribir'"
    assert res.via == "delta"
    assert len(comp.llamadas) == 1
    assert res.flujo == FLUJO_BASE


def test_generar_fn_no_pasa_por_el_delta_y_sigue_haciendo_UNA_llamada():
    """Su contrato es 'un prompt, un texto'. Los ~25 tests que lo inyectan
    miden el camino del DAG entero: meterles una llamada extra por dentro
    cambiaria lo que miden sin que nadie lo pidiera."""
    nodos = _copia(FLUJO_BASE)["nodos"][:1]
    nodos[0]["wires"] = []
    espia = Espia(_flujo_json(nodos))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso", generar_fn=espia,
                 listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "flujo entero"
    assert len(espia.llamadas) == 1


def test_COGNIA_FLUJO_DELTA_0_vuelve_al_camino_de_antes(monkeypatch):
    monkeypatch.setenv("COGNIA_FLUJO_DELTA", "0")
    nodos = _copia(FLUJO_BASE)["nodos"][:1]
    nodos[0] = dict(nodos[0], wires=[])
    comp = Turnos(_Resp(_flujo_json(nodos)))

    res = editar(_copia(FLUJO_BASE), "quita el ultimo paso",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok, res.motivo
    assert res.via == "flujo entero"
    assert len(comp.llamadas) == 1
    primero = comp.llamadas[0][1]["response_format"]["json_schema"]["name"]
    assert primero == "flujo"


def test_un_flujo_SIN_nombre_que_no_cambia_no_se_anuncia_como_cambio():
    """sanear_flujo bautiza "flujo" a lo que llega sin nombre. Comparando el
    nombre a pelo, un delta que no toco nada saldria como ok=True."""
    sin_nombre = {"nodos": [{"id": "buscar", "tool": "buscar_web",
                             "args": "a", "wires": []}]}
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "buscar",
                                      "args": "a"}], resumen="no hacia falta")))

    res = editar(dict(sin_nombre), "deja los args como estan",
                 completar_fn=comp, listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert res.motivo == "el flujo quedo igual"
    assert res.via == "delta"


# ---------------------------------------------------------------------------
# 13. El razonamiento se APAGA (la otra mitad del arreglo)
# ---------------------------------------------------------------------------

def test_las_llamadas_al_modelo_piden_NO_razonar():
    """MEDIDO: con el pensamiento en su default (`xhigh` en la plantilla de
    Qwen3.8) el mismo turno cuesta 2.774 tokens y 69,7 s y falla; apagado
    cuesta 470 y 10,2 s y sale bien."""
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "escribir",
                                      "args": "otro.md"}])))

    editar(_copia(FLUJO_BASE), "guarda en otro.md", completar_fn=comp,
           listar_tools=lambda: TOOLS)

    assert comp.llamadas[0][1]["kwargs_plantilla"] == {"enable_thinking": False}


def test_COGNIA_FLUJO_PENSAR_1_deja_pensar(monkeypatch):
    monkeypatch.setenv("COGNIA_FLUJO_PENSAR", "1")
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "escribir",
                                      "args": "otro.md"}])))

    editar(_copia(FLUJO_BASE), "guarda en otro.md", completar_fn=comp,
           listar_tools=lambda: TOOLS)

    assert "kwargs_plantilla" not in comp.llamadas[0][1]


def test_sin_perfil_no_se_manda_una_clave_a_ciegas(monkeypatch):
    """La clave que apaga el pensamiento es distinta por familia: mandarla a
    un modelo cuya plantilla no la conoce no apaga nada y ensucia el body."""
    from cognia.agent import model_profiles as _mp
    monkeypatch.setattr(_mp, "perfil_del_agente",
                        lambda *a, **k: {"kwargs_plantilla": {}})
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "escribir",
                                      "args": "otro.md"}])))

    editar(_copia(FLUJO_BASE), "guarda en otro.md", completar_fn=comp,
           listar_tools=lambda: TOOLS)

    assert "kwargs_plantilla" not in comp.llamadas[0][1]


# ---------------------------------------------------------------------------
# 14. El motivo de "no cupo" tiene que decir la VERDAD MEDIDA
# ---------------------------------------------------------------------------

class _RespCortada:
    def __init__(self, razon="", texto="", tokens=1600):
        self.texto = texto
        self.error = ""
        self.finish_reason = "length"
        self.reasoning_content = razon
        self.usage = {"completion_tokens": tokens}


def test_el_motivo_de_presupuesto_NO_culpa_al_tamano_del_flujo():
    """El mensaje viejo decia 'proba ... un flujo mas chico' y el e2e del
    2026-08-29 midio que el flujo de 2 nodos fallaba IGUAL: lo que se comia el
    presupuesto era el razonamiento, no el flujo."""
    comp = Turnos(_RespCortada(razon="x" * 5000))

    res = editar(_copia(FLUJO_BASE), "anade un paso", completar_fn=comp,
                 listar_tools=lambda: TOOLS)

    assert res.ok is False
    assert "flujo mas chico" not in res.motivo
    assert "instruccion mas acotada" not in res.motivo
    assert res.flujo == FLUJO_BASE


def test_el_motivo_dice_cuantos_tokens_y_en_que_se_fueron():
    comp = Turnos(_RespCortada(razon="x" * 5000, tokens=1600))

    res = editar(_copia(FLUJO_BASE), "anade un paso", completar_fn=comp,
                 listar_tools=lambda: TOOLS)

    assert "1600" in res.motivo
    assert "5000 caracteres de razonamiento" in res.motivo
    assert "no llego a escribir ni el primer caracter" in res.motivo


def test_el_motivo_distingue_el_JSON_a_medias_del_razonamiento_infinito():
    comp = Turnos(_RespCortada(razon="x" * 10, texto='{"resumen": "a", "ops"',
                               tokens=1600))

    res = editar(_copia(FLUJO_BASE), "anade un paso", completar_fn=comp,
                 listar_tools=lambda: TOOLS)

    assert "quedo a medias" in res.motivo
    assert "10 caracteres de razonamiento" in res.motivo


# ---------------------------------------------------------------------------
# 15. aplicar_ops: la frontera entre lo que se aplica y lo que se rechaza
# ---------------------------------------------------------------------------

def _ok_ops(ops, flujo=None):
    nuevo, motivo = fia.aplicar_ops(flujo or _copia(FLUJO_BASE), ops,
                                    tool_existe=lambda t: t in TOOLS)
    assert motivo == "", motivo
    return nuevo


def _rechaza_ops(ops, flujo=None):
    nuevo, motivo = fia.aplicar_ops(flujo or _copia(FLUJO_BASE), ops,
                                    tool_existe=lambda t: t in TOOLS)
    assert motivo, "esto tenia que rechazarse"
    assert nuevo == {}
    return motivo


def test_aplicar_ops_no_toca_el_flujo_de_entrada():
    entrada = _copia(FLUJO_BASE)
    _ok_ops([{"op": "borrar_nodo", "id": "escribir"}], entrada)
    assert entrada == FLUJO_BASE


def test_borrar_nodo_se_lleva_los_cables_que_apuntaban_a_el():
    nuevo = _ok_ops([{"op": "borrar_nodo", "id": "escribir"}])
    assert [n["id"] for n in nuevo["nodos"]] == ["buscar"]
    assert nuevo["nodos"][0]["wires"] == []


def test_cambiar_args_y_cambiar_tool():
    nuevo = _ok_ops([{"op": "cambiar_args", "id": "escribir",
                      "args": "otro.md"},
                     {"op": "cambiar_tool", "id": "buscar",
                      "tool": "leer_archivo"}])
    porid = {n["id"]: n for n in nuevo["nodos"]}
    assert porid["escribir"]["args"] == "otro.md"
    assert porid["buscar"]["tool"] == "leer_archivo"


def test_renombrar_cambia_solo_el_nombre():
    nuevo = _ok_ops([{"op": "renombrar", "nombre": "informe semanal"}])
    assert nuevo["nombre"] == "informe semanal"
    assert nuevo["nodos"] == FLUJO_BASE["nodos"]


def test_desconectar_quita_el_cable_y_conectar_no_lo_duplica():
    nuevo = _ok_ops([{"op": "desconectar", "de": "buscar", "a": "escribir"},
                     {"op": "conectar", "de": "buscar", "a": "escribir"},
                     {"op": "conectar", "de": "buscar", "a": "escribir"}])
    assert nuevo["nodos"][0]["wires"] == ["escribir"]


def test_TODO_O_NADA_una_op_mala_al_final_anula_las_buenas():
    """Aplicar las que se pueden y callar el resto le devolveria al dueno un
    flujo con cara de bueno al que le falta justo lo que pidio."""
    motivo = _rechaza_ops([{"op": "cambiar_args", "id": "escribir",
                            "args": "ok"},
                           {"op": "borrar_nodo", "id": "fantasma"}])
    assert "fantasma" in motivo


def test_aplicar_ops_rechaza_lo_que_no_se_puede_aplicar():
    assert "ya hay uno con ese id" in _rechaza_ops(
        [{"op": "anadir_nodo", "id": "buscar", "tool": "leer_archivo"}])
    assert "sin decir con que tool" in _rechaza_ops(
        [{"op": "anadir_nodo", "id": "nuevo"}])
    assert "no trae 'id'" in _rechaza_ops(
        [{"op": "anadir_nodo", "tool": "buscar_web"}])
    assert "que no existe" in _rechaza_ops(
        [{"op": "cambiar_args", "id": "fantasma", "args": "x"}])
    assert "que no existe" in _rechaza_ops(
        [{"op": "conectar", "de": "buscar", "a": "fantasma"}])
    assert "necesita 'de' y 'a'" in _rechaza_ops(
        [{"op": "conectar", "de": "buscar"}])
    assert "no es una operacion conocida" in _rechaza_ops([{"op": "explotar"}])
    assert "no es un objeto JSON" in _rechaza_ops(["borrar todo"])
    assert "lista 'ops'" in _rechaza_ops({"op": "renombrar", "nombre": "x"})



def test_cambiar_control_pone_y_QUITA_reintentos_timeout_y_saltar_si():
    """'hazlo reintentable' es una de las tres sugerencias que el editor pinta
    en su primera pantalla. Sin esta op el delta no sabia expresarla y el turno
    caia siempre al respaldo caro (15,6 s medidos contra 3-9 s del delta)."""
    nuevo = _ok_ops([{"op": "cambiar_control", "id": "buscar",
                      "reintentos": 3, "timeout_s": 30,
                      "saltar_si": "{{escribir}}"}])
    b = [n for n in nuevo["nodos"] if n["id"] == "buscar"][0]
    assert b["reintentos"] == 3 and b["timeout_s"] == 30.0
    assert b["saltar_si"] == "{{escribir}}"

    conreintentos = {"nombre": "x", "nodos": [
        {"id": "buscar", "tool": "buscar_web", "args": "a", "wires": [],
         "reintentos": 3, "saltar_si": "{{x}}"}]}
    vacio = _ok_ops([{"op": "cambiar_control", "id": "buscar",
                      "reintentos": 0, "saltar_si": ""}], conreintentos)
    assert "reintentos" not in vacio["nodos"][0]
    assert "saltar_si" not in vacio["nodos"][0]


def test_cambiar_control_sin_decir_que_cambiar_se_rechaza():
    assert "no dice que cambiarle" in _rechaza_ops(
        [{"op": "cambiar_control", "id": "buscar"}])
    assert "que no existe" in _rechaza_ops(
        [{"op": "cambiar_control", "id": "fantasma", "reintentos": 2}])

def test_aplicar_ops_rechaza_una_tool_que_no_existe():
    """La misma frontera de sanear_flujo: el delta pasa por flows.validar."""
    motivo = _rechaza_ops([{"op": "anadir_nodo", "id": "x",
                            "tool": "tool_fantasma"}])
    assert "tool_fantasma" in motivo


def test_aplicar_ops_rechaza_un_ciclo():
    motivo = _rechaza_ops([{"op": "conectar", "de": "escribir",
                            "a": "buscar"}])
    assert "ciclo" in motivo.lower()


def test_aplicar_ops_tiene_tope_de_operaciones():
    ops = [{"op": "cambiar_args", "id": "escribir", "args": str(i)}
           for i in range(fia.TOPE_OPS + 1)]
    assert "el tope es" in _rechaza_ops(ops)


def test_el_id_se_normaliza_igual_en_las_ops_que_en_los_nodos():
    """Si aqui se aceptara 'mi nodo' crudo y sanear_flujo lo volviera
    'mi_nodo', el `conectar` apuntaria a un nodo que no existe."""
    nuevo = _ok_ops([{"op": "anadir_nodo", "id": "mi nodo",
                      "tool": "leer_archivo", "args": "x"},
                     {"op": "conectar", "de": "escribir", "a": "mi nodo"}])
    porid = {n["id"]: n for n in nuevo["nodos"]}
    assert "mi_nodo" in porid
    assert porid["escribir"]["wires"] == ["mi_nodo"]


def test_anadir_nodo_conserva_los_campos_de_control_de_flujo():
    nuevo = _ok_ops([{"op": "anadir_nodo", "id": "x", "tool": "leer_archivo",
                      "args": "a.md", "reintentos": 3, "timeout_s": 12,
                      "saltar_si": "{{buscar}}"}])
    x = [n for n in nuevo["nodos"] if n["id"] == "x"][0]
    assert x["reintentos"] == 3 and x["timeout_s"] == 12.0
    assert x["saltar_si"] == "{{buscar}}"


def test_el_ejemplo_del_prompt_DELTA_usa_tools_reales():
    """El mismo guardian que el de _FORMATO: el modelo copia los nombres del
    ejemplo, y un ejemplo con una tool inventada rechaza TODOS los deltas."""
    reales = set(fia._tools_disponibles())
    if not reales:
        pytest.skip("no se pudo leer el registro de tools")
    usadas = set(re.findall(r'"tool":\s*"([a-z_]+)"', fia._SYSTEM_DELTA))
    assert usadas, "el ejemplo del delta no declara ninguna tool"
    assert not (usadas - reales), (
        f"el ejemplo del delta usa tools que no existen: "
        f"{sorted(usadas - reales)}")


def test_el_esquema_del_delta_declara_las_MISMAS_ops_que_aplicar_ops():
    """Un `enum` y un `if` desincronizados dan el fallo mas caro de esta casa:
    el modelo emite una op que el schema acepta y Python rechaza."""
    enum = (fia.ESQUEMA_DELTA["properties"]["ops"]["items"]
            ["properties"]["op"]["enum"])
    fuente = Path(fia.__file__).read_text(encoding="utf-8")
    cuerpo = fuente.split("def aplicar_ops(")[1].split("\ndef ")[0]
    for op in enum:
        assert f'"{op}"' in cuerpo, f"el schema declara '{op}' y aplicar_ops no"


# ---------------------------------------------------------------------------
# 12. La FIRMA POSICIONAL de TODA tool de >=2 params, con el catalogo REAL
# ---------------------------------------------------------------------------
# El bloque 9 fija que la firma sale para un punado de tools elegidas a mano.
# Este barre el catalogo ENTERO: la forma de los args es un protocolo de texto
# posicional ("ruta | contenido"), y una sola tool de dos params anunciada sin
# su firma es una tool cuya forma el modelo tiene que adivinar. Es el mismo
# fallo que costo la causa raiz del pedido 5, medido en otra tool.

def test_toda_tool_de_dos_params_llega_al_prompt_con_su_firma_posicional():
    from cognia.agent import catalogo_nodos as cn

    fichas = {e["nombre"]: e for e in cn.catalogo()}
    con_params = sorted(n for n, e in fichas.items() if len(e["params"]) >= 2)
    assert len(con_params) >= 8, (
        "el catalogo real trae %d tools de >=2 params: este test no estaria "
        "midiendo nada" % len(con_params))

    lineas = fia._lineas_de_tools(con_params)
    assert len(lineas) == len(con_params), (
        "el catalogo no llego: esto estaria midiendo el fallback de nombres")

    sin_firma = []
    for nombre in con_params:
        firma = "%s(%s)" % (nombre, ", ".join(
            p["nombre"] if p.get("requerido") else p["nombre"] + "?"
            for p in fichas[nombre]["params"]))
        if not any(l == "- " + firma or l.startswith("- " + firma + ":")
                   for l in lineas):
            sin_firma.append(firma)
    assert sin_firma == [], (
        "%d tools de dos o mas argumentos llegan al modelo sin decirle en que "
        "orden van: %s. El modelo se inventa la forma de los args." % (
            len(sin_firma), sin_firma[:4]))


def test_la_firma_de_escribir_archivo_llega_ENTERA_por_editar(monkeypatch):
    """De punta a punta y sin monkeypatch del catalogo: es lo que ve el modelo
    cuando el editor le pide "guarda el resultado en un fichero"."""
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "guarda el resultado en informe.md",
           generar_fn=espia,
           listar_tools=lambda: ["escribir_archivo", "apendar_archivo",
                                 "leer_archivo"])
    p = espia.prompt
    assert "escribir_archivo(path, contenido)" in p, p[-800:]
    assert "escribir_archivo()" not in p


# ---------------------------------------------------------------------------
# 13. sanear_flujo CONSERVA el nodo de ENTRADA (PLAN2, PEDIDO 3)
# ---------------------------------------------------------------------------
# El modo del prompt (variable vs constante) vive en el NOMBRE DE LA TOOL y
# no en un campo nuevo del nodo, y la razon es exactamente esta funcion: su
# whitelist reconstruye cada nodo como {id, tool, args, wires} + cuatro
# campos de control, asi que un `prompt_modo` moriria SIN ERROR en la primera
# edicion conversacional. Estos tests fijan que la decision se sostiene.

def _existe(nombres):
    return lambda t: t in set(nombres)


def test_sanear_conserva_los_nodos_prompt_y_prompt_fijo():
    crudo = {"nombre": "informe", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "tendencias IA",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md | {{prompt}}", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(
        crudo, tool_existe=_existe(["prompt", "escribir_archivo"]))
    assert motivo == "", motivo
    por_id = {n["id"]: n for n in flujo["nodos"]}
    assert por_id["prompt"]["tool"] == "prompt"
    assert por_id["prompt"]["args"] == "tendencias IA"
    assert por_id["prompt"]["wires"] == ["escribir"]


def test_sanear_NO_degrada_prompt_fijo_a_prompt():
    """El caso que decide si "que el prompt sea fijo" se puede pedir por chat.

    `prompt_fijo` es la CONSTANTE: ignora el argumento de
    `/flujoteca ejecutar`. Si el saneado lo normalizara a `prompt`, el flujo
    volveria a aceptar cualquier prompt del CLI y el dueno no se enteraria --
    el vacio silencioso de siempre, pero cambiando lo que hace su flujo.
    """
    crudo = {"nombre": "informe", "nodos": [
        {"id": "prompt", "tool": "prompt_fijo", "args": "SIEMPRE ESTO",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md | {{prompt}}", "wires": []},
    ]}
    flujo, motivo = sanear_flujo(
        crudo, tool_existe=_existe(["prompt_fijo", "escribir_archivo"]))
    assert motivo == "", motivo
    por_id = {n["id"]: n for n in flujo["nodos"]}
    assert por_id["prompt"]["tool"] == "prompt_fijo", (
        "el saneado degrado la constante a variable: el flujo pasa a aceptar "
        "el prompt del CLI sin que nadie lo pida")
    assert por_id["prompt"]["args"] == "SIEMPRE ESTO"


def test_el_modo_del_prompt_sobrevive_a_una_edicion_conversacional_entera():
    """El ciclo que mata a los campos nuevos: el modelo devuelve el flujo, el
    saneado lo reconstruye y lo que no este en la whitelist desaparece.

    Se ejerce con el registro REAL (`tool_existe=None` deja que valide contra
    el registro que use `flows.validar`), y ademas se comprueba lo contrario:
    un campo `prompt_modo` al lado SI se pierde. Ese contraste es lo que
    justifica que el modo viva en `tool`.
    """
    nodos = [
        {"id": "prompt", "tool": "prompt_fijo", "args": "la constante",
         "prompt_modo": "fijo", "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md | {{prompt}}", "wires": []},
    ]
    espia = Espia(_flujo_json(nodos, nombre="informe"))
    res = editar({"nombre": "informe", "nodos": _copia({"n": nodos})["n"]},
                 "cambia el fichero a otro.md", generar_fn=espia,
                 listar_tools=lambda: ["prompt", "prompt_fijo",
                                       "escribir_archivo"])
    assert res.ok is True, res.motivo
    por_id = {n["id"]: n for n in res.flujo["nodos"]}
    # La tool -> sobrevive. Es donde vive el modo.
    assert por_id["prompt"]["tool"] == "prompt_fijo"
    # Un campo suelto -> NO sobrevive, y sin un solo error.
    assert "prompt_modo" not in por_id["prompt"], (
        "si esto pasa, la whitelist de sanear_flujo se abrio y hay que "
        "revisar por que el modo vive en `tool`")


# ---------------------------------------------------------------------------
# 14. EL DISCO: lo que el prompt ENSENA, la tool REAL lo acepta
# ---------------------------------------------------------------------------
# La razon de que este fallo llegara a produccion con 288 tests en verde es
# que TODOS los tests de flujos usan un `run_tool` falso que acepta cualquier
# cadena y ninguno mira el disco. Este coge el args LITERAL del ejemplo del
# prompt -- no una copia a mano, el que de verdad lee el modelo -- y se lo da
# al registro REAL de tools, y despues mira si el fichero esta.

def test_el_args_QUE_ENSENA_EL_PROMPT_lo_acepta_la_tool_REAL(tmp_path,
                                                             monkeypatch):
    """Efecto OBSERVABLE: un fichero en disco con el contenido esperado.

    Contrafactual medido el 2026-08-29 y fijado abajo: con el separador viejo
    (salto de linea) la MISMA tool devuelve "ERROR: formato" y no escribe
    nada. Ese era el flujo del dueno entero: nodos verdes en la vista, cero
    ficheros en el PC.
    """
    from cognia.agent import tools as T
    from cognia.agents.workers import dev_tools

    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))

    # El args del ejemplo del prompt, tal cual, con el marcador interpolado
    # como lo haria `flows._interpolar`.
    ejemplos = re.findall(r'"args"\s*:\s*"([^"]*)"', fia._FORMATO)
    con_pipe = [a for a in ejemplos if " | " in a]
    assert con_pipe, "el ejemplo del prompt no ensena ningun args de 2 partes"
    args = con_pipe[0].replace("{{hallar}}", "tendencias de IA en 2026")

    res = T.run_tool("escribir_archivo", args, {})
    assert "ERROR" not in res, res
    escrito = list(tmp_path.glob("*.md"))
    assert escrito, "la tool dijo OK y no hay ni un fichero: %s" % res
    assert escrito[0].read_text(encoding="utf-8") == "tendencias de IA en 2026"

    # CONTRAFACTUAL: el separador viejo, la misma tool, el mismo contenido.
    viejo = args.replace(" | ", "\n", 1)
    res2 = T.run_tool("escribir_archivo", viejo, {})
    assert "ERROR" in res2, (
        "si esto pasa, la tool ya acepta el salto de linea y este test deja "
        "de vigilar nada: %s" % res2)
    assert len(list(tmp_path.glob("*.md"))) == 1, (
        "el separador viejo escribio algo: " + str(list(tmp_path.iterdir())))


# ---------------------------------------------------------------------------
# 15. EL NODO DE ENTRADA, CABLEADO (2026-08-30)
# ---------------------------------------------------------------------------
# EL DEFECTO, reproducido por el revisor adversarial sobre el flujo REAL del
# dueno: `flujoteca.guardar` llama a `flows.asegurar_prompt` en TODO guardado,
# asi que el flujo sale del editor con un nodo `prompt` con args:"" -- y
# NINGUN nodo lo referencia. El cableado semantico ({{prompt}} dentro de los
# args del nodo que depende del objetivo) solo lo puede poner el modelo, y
# estos dos prompts no nombraban ni una vez `prompt`, `prompt_fijo` ni
# `{{prompt}}`. Resultado medido: `/flujoteca ejecutar <flujo> "ESTO ES LO QUE
# QUIERO"` decia "OK | 3 nodos | 0 con error" y notas.txt seguia diciendo
# PRUEBA. Peor que antes: como el nodo YA existe, tampoco salta el aviso de
# "este flujo no tiene nodo de entrada".
#
# Medido contra el :8080 (Qwen3.8-27B-Ridge) el 2026-08-30, mismo montaje, lo
# unico que cambia son estos dos prompts:
#   "que el fichero guarde lo que yo escriba al ejecutar el flujo"
#     ANTES:   args "notas.txt | {{texto_usuario}}"  <- marcador INVENTADO,
#              que `_interpolar` sustituye por "" -> fichero VACIO, 0 errores
#     DESPUES: nodo {"id":"prompt","tool":"prompt"} + "notas.txt | {{prompt}}"
#   de_sesion (el flujo NUEVO que sale de una sesion de trabajo)
#     ANTES:   sin nodo de entrada (y `asegurar_prompt` le colgaba uno muerto)
#     DESPUES: {"id":"prompt",...} + "{{prompt}}" en el nodo que busca
#
# Estos tests NO leen el fuente: capturan el system prompt QUE SE MANDA de
# verdad y ejecutan el flujo resultante mirando el disco.

_ENTRADA = ("prompt", "prompt_fijo")


def _system_de_editar() -> str:
    """El system prompt que editar() manda de verdad por la via del DAG."""
    espia = Espia(_flujo_json(FLUJO_BASE["nodos"]))
    editar(_copia(FLUJO_BASE), "cambia algo", generar_fn=espia,
           listar_tools=lambda: TOOLS)
    return espia.system


def _system_del_delta() -> str:
    """El system prompt que editar() manda por la via por defecto (el delta)."""
    comp = Turnos(_Resp(_delta_json([{"op": "cambiar_args", "id": "escribir",
                                      "args": "otro.md"}])))
    editar(_copia(FLUJO_BASE), "guarda en otro.md", completar_fn=comp,
           listar_tools=lambda: TOOLS)
    return comp.llamadas[0][0][0]["content"]


def test_el_system_QUE_SE_MANDA_ordena_cablear_el_prompt_en_las_DOS_vias():
    """Lo que el modelo RECIBE -- no lo que dice el fuente -- tiene que
    nombrar el nodo de entrada, su marcador y la OBLIGACION de interpolarlo.

    Sin esto la edicion conversacional no cablea {{prompt}} JAMAS, y el nodo
    que `asegurar_prompt` anade en cada guardado se queda de adorno.
    """
    for via, system in (("DAG entero", _system_de_editar()),
                        ("delta", _system_del_delta())):
        plano = " ".join(system.split()).upper()
        assert '"prompt"' in system, f"{via}: no nombra la tool de entrada"
        assert "prompt_fijo" in system, f"{via}: no nombra el modo constante"
        assert "{{prompt}}" in system, (
            f"{via}: no ensena el marcador con el que se usa la salida del "
            f"nodo de entrada")
        assert "DEPENDA DEL OBJETIVO DEL USUARIO" in plano, (
            f"{via}: no dice CUANDO hay que interpolarlo. Un ejemplo sin "
            f"regla se pierde en cuanto la tarea no se parece al ejemplo")
        # Y el marcador inventado queda prohibido POR SU CONSECUENCIA: es lo
        # que el modelo hizo de verdad antes de este cambio.
        assert "CADENA VACIA" in plano, (
            f"{via}: no dice que un marcador que no es id de ningun nodo se "
            f"sustituye por vacio (el modelo invento texto_usuario)")


def _ejemplo_del_formato() -> dict:
    """El flujo del EJEMPLO tal y como viaja dentro del system prompt."""
    system = _system_de_editar()
    ini = system.index("{", system.index("FORMATO DE SALIDA"))
    hondo, fin = 0, -1
    for k in range(ini, len(system)):
        if system[k] == "{":
            hondo += 1
        elif system[k] == "}":
            hondo -= 1
            if hondo == 0:
                fin = k
                break
    assert fin > ini, "el ejemplo del system prompt no es un JSON equilibrado"
    return json.loads(system[ini:fin + 1])


def test_el_ejemplo_QUE_VIAJA_trae_el_nodo_de_entrada_interpolado_y_VALIDA():
    """El modelo copia la FORMA del ejemplo: si el ejemplo no lleva el nodo de
    entrada cableado, los flujos que devuelve tampoco. Y el ejemplo se valida
    contra el registro REAL, que es el que rechazara lo que copie."""
    ejemplo = _ejemplo_del_formato()
    nodos = ejemplo["nodos"]
    entrada = [n for n in nodos if n.get("tool") in _ENTRADA]
    assert entrada, ("el ejemplo del prompt no trae nodo de entrada: %s"
                     % [n.get("tool") for n in nodos])
    ent = entrada[0]
    assert nodos[0] is ent, "el nodo de entrada tiene que ir el PRIMERO"
    marca = "{{%s}}" % ent["id"]
    usan = [n["id"] for n in nodos
            if n is not ent and marca in n.get("args", "")]
    assert usan, (
        "el ejemplo trae el nodo de entrada y no lo usa NADIE: es justo el "
        "flujo muerto que produce asegurar_prompt")
    # Y es un flujo VALIDO de verdad: sin tool_existe, `sanear_flujo` valida
    # contra el registro real de tools.
    flujo, motivo = sanear_flujo({"nombre": "x", "nodos": nodos})
    assert motivo == "", "el ejemplo del prompt no valida: %s" % motivo
    assert [n["id"] for n in flujo["nodos"]] == [n["id"] for n in nodos]


def test_el_ejemplo_DEL_PROMPT_ejecutado_le_da_al_nodo_el_texto_del_DUENO():
    """EJERCE el ejemplo: se ejecuta el flujo que viaja en el system prompt con
    el texto que el dueno teclearia en `/flujoteca ejecutar`, y se mira QUE
    ARGS le llegan al nodo que depende del objetivo. Las tools de entrada
    corren las de VERDAD (registro real); las demas se graban."""
    from cognia.agent import flows as _flows
    from cognia.agent import tools as T

    nodos = _ejemplo_del_formato()["nodos"]
    ent = [n for n in nodos if n.get("tool") in _ENTRADA][0]
    marca = "{{%s}}" % ent["id"]
    dependiente = [n for n in nodos
                   if n is not ent and marca in n.get("args", "")][0]

    visto = {}

    def run_tool(nombre, args, ctx):
        if nombre in _ENTRADA:
            return T.run_tool(nombre, args, ctx)      # la tool REAL
        visto[nombre] = args
        return "RESULTADO %s: ok" % nombre

    res = _flows.ejecutar({"nombre": "ejemplo", "nodos": nodos},
                          {"prompt_flujo": "ESTO ES LO QUE QUIERO"}, run_tool,
                          tool_existe=lambda n: True)
    assert res["errores"] == {}, res["errores"]
    assert visto.get(dependiente["tool"]) == "ESTO ES LO QUE QUIERO", (
        "el texto del dueno no llego al nodo '%s': recibio %r"
        % (dependiente["id"], visto.get(dependiente["tool"])))


def test_un_delta_que_depende_del_objetivo_lo_CABLEA_y_el_fichero_lo_PRUEBA(
        tmp_path, monkeypatch):
    """INTEGRACION: el escenario exacto del revisor, con su CONTRAFACTUAL.

    El flujo REAL del dueno tal y como lo deja `asegurar_prompt` (nodo de
    entrada con args:"" que no usa nadie). El delta del modelo cablea
    {{prompt}}; se ejecuta con el registro REAL de tools y se mira el fichero
    EN DISCO, que es donde el dueno vio el fallo.
    """
    from cognia.agent import flows as _flows
    from cognia.agent import tools as T
    from cognia.agents.workers import dev_tools

    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))

    guardado = {"nombre": "crear y verificar fichero", "nodos": [
        {"id": "prompt", "tool": "prompt", "args": "", "wires": ["crear"]},
        {"id": "crear", "tool": "escribir_archivo",
         "args": "notas.txt | PRUEBA", "wires": []},
    ]}
    ctx = {"prompt_flujo": "ESTO ES LO QUE QUIERO"}
    notas = tmp_path / "notas.txt"

    # CONTRAFACTUAL: tal y como sale hoy del guardado, el prompt NO llega.
    _flows.ejecutar(_copia(guardado), dict(ctx), T.run_tool,
                    tool_existe=lambda n: n in T.TOOLS)
    assert notas.read_text(encoding="utf-8") == "PRUEBA", (
        "si esto cambia, el flujo ya usaba el prompt sin cablearlo y este "
        "test no vigila nada")

    # El delta que manda el modelo cuando el prompt le ensena la regla.
    comp = Turnos(_Resp(_delta_json(
        [{"op": "cambiar_args", "id": "crear",
          "args": "notas.txt | {{prompt}}"}],
        resumen="cablee el objetivo del dueno al fichero")))
    res = editar(_copia(guardado),
                 "que el fichero guarde lo que yo escriba al ejecutar",
                 completar_fn=comp,
                 listar_tools=lambda: ["prompt", "escribir_archivo"])
    assert res.ok, res.motivo
    assert res.via == "delta"
    porid = {n["id"]: n for n in res.flujo["nodos"]}
    # el nodo de ENTRADA sobrevive intacto al saneado (whitelist de `tool`)
    assert porid["prompt"]["tool"] == "prompt"
    assert porid["prompt"]["wires"] == ["crear"]
    assert "{{prompt}}" in porid["crear"]["args"]

    _flows.ejecutar(res.flujo, dict(ctx), T.run_tool,
                    tool_existe=lambda n: n in T.TOOLS)
    assert notas.read_text(encoding="utf-8") == "ESTO ES LO QUE QUIERO", (
        "el flujo corrio con el prompt cableado y el fichero no lo tiene: %r"
        % notas.read_text(encoding="utf-8"))


def test_aplicar_ops_NO_toca_el_nodo_de_entrada_ni_su_modo():
    """El delta es la via por DEFECTO: si `aplicar_ops` degradara el nodo de
    entrada (o su modo constante), el cableado duraria un turno de chat."""
    from cognia.agent.flujo_ia import aplicar_ops

    flujo = {"nombre": "informe", "nodos": [
        {"id": "prompt", "tool": "prompt_fijo", "args": "SIEMPRE ESTO",
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "informe.md | PRUEBA", "wires": []},
    ]}
    nuevo, motivo = aplicar_ops(
        flujo, [{"op": "cambiar_args", "id": "escribir",
                 "args": "informe.md | {{prompt}}"}],
        tool_existe=_existe(["prompt", "prompt_fijo", "escribir_archivo"]))
    assert motivo == "", motivo
    porid = {n["id"]: n for n in nuevo["nodos"]}
    assert porid["prompt"] == {"id": "prompt", "tool": "prompt_fijo",
                               "args": "SIEMPRE ESTO", "wires": ["escribir"]}
    assert porid["escribir"]["args"] == "informe.md | {{prompt}}"
