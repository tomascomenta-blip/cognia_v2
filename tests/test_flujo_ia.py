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
                         registro):
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
