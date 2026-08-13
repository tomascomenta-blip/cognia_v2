# -*- coding: utf-8 -*-
"""Regresion de cognia/harness/registro_dinamico.py (2026-08-12).

Sin el modulo estos tests fallan en el import (no existe el fichero); con el
modulo pasan. NO se importa cognia.agent.tools: el catalogo se pasa por
parametro, y hay un test que verifica que el modulo tampoco lo importa.

El CATALOGO de abajo copia (a mano) las descripciones REALES del registry del
repo — mismas frases que ve el modelo — para que el ranking se mida contra el
texto de produccion y no contra un fixture escrito para aprobar.
"""

from __future__ import annotations

import pathlib

from cognia.harness.registro_dinamico import (
    ESQUEMA_BUSCAR_HERRAMIENTAS,
    MAX_ACTIVAS,
    activar,
    activas,
    buscar,
    catalogo_efectivo,
    huella_catalogo,
    indexar,
    nueva_sesion,
    texto_resultado_busqueda,
    tokenizar,
)

import pytest


def _t(nombre, descripcion, danger=False):
    return {"nombre": nombre, "descripcion": descripcion, "params": [], "danger": danger}


# 32 herramientas con las descripciones reales de cognia/agent/tools.py.
CATALOGO = [
    _t("leer_archivo",
       "Lee un archivo de texto y devuelve su contenido TAL CUAL (para poder "
       "editarlo despues con editar_archivo). Por defecto muestra 2000 lineas "
       "desde la primera."),
    _t("escribir_archivo",
       "Crea un archivo nuevo (o SOBRESCRIBE uno existente ENTERO) con el "
       "contenido dado; crea los directorios intermedios. Para cambiar solo una "
       "parte de un archivo existente usa editar_archivo."),
    _t("editar_archivo",
       "Edita un archivo existente reemplazando bloques SEARCH/REPLACE. El SEARCH "
       "debe copiar TEXTO EXACTO que viste con leer_archivo y ser UNICO en el archivo."),
    _t("apendar_archivo",
       "Agrega una linea de texto AL FINAL de un archivo sin tocar el resto del contenido."),
    _t("borrar_archivo",
       "Borra un archivo del workspace del agente. Solo archivos, no directorios.", True),
    _t("copiar_archivo", "copiar_archivo <src> | <dst> -- copia un archivo (dst en el workspace)"),
    _t("listar", "Lista los archivos y carpetas de un directorio (no recursivo)."),
    _t("arbol", "arbol <directorio> -- arbol de archivos (2 niveles)"),
    _t("contar_lineas", "contar_lineas <path> -- cuenta lineas de un archivo"),
    _t("buscar", "Busca un patron de texto (regex o literal) dentro de los archivos "
                 "de un directorio."),
    _t("ejecutar", "Ejecuta un comando de shell y devuelve stdout+stderr (si el output "
                   "es largo se comprime).", True),
    _t("tests", "Corre pytest sobre UNA ruta especifica (archivo o directorio de tests)."),
    _t("py_validar", "py_validar <path> -- chequea sintaxis de un .py"),
    _t("json_validar", "json_validar <path> -- valida un archivo JSON"),
    _t("git_estado", "git_estado -- git status resumido"),
    _t("git_diff", "git_diff [ruta] -- git diff (cambios sin commitear)"),
    _t("git_log", "git_log -- ultimos 5 commits"),
    _t("calcular", "calcular <expresion> -- aritmetica exacta (+ - * / // % **)"),
    _t("fecha", "fecha -- fecha y hora actual"),
    _t("http_get", "http_get <url> -- descarga texto de una URL (http/https)"),
    _t("abrir", "abrir <url-o-ruta-o-app> -- abre una URL/archivo/app en el sistema "
                "(Chrome, YouTube, un archivo, una app)"),
    _t("recordar", "Busca en la memoria episodica de Cognia (lo que el usuario y las "
                   "sesiones anteriores dijeron)."),
    _t("memorizar", "memorizar <texto> -- guarda en memoria episodica"),
    _t("kg_buscar", "kg_buscar <concepto> -- hechos del grafo sobre un concepto"),
    _t("anotar", "anotar <clave> | <valor> -- guarda nota en memoria de trabajo"),
    _t("notas", "notas -- lee la memoria de trabajo"),
    _t("resumir", "resumir <texto> -- resume un texto con el modelo"),
    _t("generar_codigo", "Escribe una FUNCION Python nueva a partir de una descripcion "
                         "en lenguaje natural y la valida."),
    _t("repo_map", "repo_map [ruta] -- mapa del repositorio: ficheros y simbolos mas importantes"),
    _t("code_grafo", "code_grafo <simbolo> -- quien llama a quien alrededor de un simbolo"),
    _t("delegar_subtarea", "Delega una SUBTAREA autocontenida a un sub-agente con contexto propio."),
    _t("crear_herramienta", "crear_herramienta <nombre> | <codigo> -- registra una "
                            "herramienta nueva", True),
]

# El catalogo BASE que ve el modelo (CORE chico) + buscar_herramientas.
BASE = [t for t in CATALOGO if t["nombre"] in
        {"leer_archivo", "escribir_archivo", "editar_archivo", "listar", "buscar",
         "ejecutar"}] + [ESQUEMA_BUSCAR_HERRAMIENTAS]


@pytest.fixture()
def indice():
    return indexar(CATALOGO)


@pytest.fixture()
def sesion(indice):
    return nueva_sesion(indice)


def primeros(resultados):
    return [r[0] for r in resultados]


# ── tokenizacion ───────────────────────────────────────────────────────
def test_tokeniza_partiendo_por_guionbajo_camelcase_y_acentos():
    assert tokenizar("git_estado") == ["repositorio", "estado"]
    # camelCase se parte; 'Archivo' y 'escribir' caen en sus clases canonicas.
    assert tokenizar("escribirArchivoNuevo") == ["escribir", "archivo", "nuevo"]
    # acentos fuera y stopwords es/en fuera ('de', 'un', 'the', 'of').
    assert tokenizar("descripción de un módulo") == ["descripcion", "modulo"]
    assert tokenizar("the state of the repo") == ["estado", "repositorio"]


# ── busqueda (los 2 casos EXIGIDOS + 3 elegidos) ───────────────────────
def test_encuentra_escribir_archivo_por_guardar_texto_en_un_fichero(indice):
    res = buscar(indice, "guardar texto en un fichero")
    assert res and res[0][0] == "escribir_archivo"
    assert res[0][1] > 0
    assert "SOBRESCRIBE" in res[0][2]      # devuelve la descripcion, no solo el nombre


def test_encuentra_git_estado_por_ver_que_cambio_en_el_repositorio(indice):
    res = buscar(indice, "ver que cambio en el repositorio")
    assert res and res[0][0] == "git_estado"


def test_encuentra_tests_por_correr_las_pruebas_de_un_modulo(indice):
    assert primeros(buscar(indice, "correr las pruebas de un modulo"))[0] == "tests"


def test_encuentra_borrar_archivo_por_eliminar_un_fichero(indice):
    assert primeros(buscar(indice, "eliminar un fichero del workspace"))[0] == "borrar_archivo"


def test_encuentra_code_grafo_por_quien_llama_a_esta_funcion(indice):
    assert primeros(buscar(indice, "quien llama a esta funcion"))[0] == "code_grafo"


def test_consulta_en_ingles_tambien_casa(indice):
    # La tabla de sinonimos es bilingue: 'download'/'url' -> clase web.
    assert "http_get" in primeros(buscar(indice, "download text from a url"))


def test_limite_y_excluir(indice):
    assert len(buscar(indice, "archivo", limite=3)) == 3
    assert buscar(indice, "archivo", limite=0) == []
    fuera = ("escribir_archivo", "leer_archivo")
    res = primeros(buscar(indice, "guardar texto en un fichero", excluir=fuera))
    assert res and not (set(res) & set(fuera))


def test_excluir_acepta_un_solo_nombre_como_str(indice):
    # REGRESION: excluir="escribir_archivo" se volvia set("escribir_archivo") —
    # un conjunto de LETRAS. No excluia nada y no se quejaba (activar() SI acepta
    # str, asi que la asimetria era una trampa).
    assert primeros(buscar(indice, "guardar texto en un fichero"))[0] == "escribir_archivo"
    res = primeros(buscar(indice, "guardar texto en un fichero", excluir="escribir_archivo"))
    assert res and "escribir_archivo" not in res


def test_limite_none_devuelve_todos_los_que_puntuaron(indice):
    todos = buscar(indice, "archivo", limite=None)
    assert len(todos) > 5
    assert buscar(indice, "archivo", limite=5) == todos[:5]


def test_sin_coincidencia_devuelve_vacio_no_ruido(indice):
    # Score 0 no se devuelve: preferimos "no hay" a inventar relevancia.
    assert buscar(indice, "zzzqqq vwxyz") == []
    assert buscar(indice, "") == []


def test_orden_determinista_y_saturacion_de_frecuencia(indice):
    # (a) dos corridas identicas dan el MISMO orden (el prompt debe cachear).
    a = buscar(indice, "archivo de texto", limite=5)
    assert a == buscar(indice, "archivo de texto", limite=5)
    # (b) k1=1.2 satura: repetir el termino 12 veces NO da 12x el score de 1 vez.
    cat = [_t("repetidor", " ".join(["cuaderno"] * 12)),
           _t("unico", "cuaderno"),
           _t("ajeno", "una herramienta cualquiera sin relacion")]
    ix2 = indexar(cat)
    puntajes = {n: s for n, s, _ in buscar(ix2, "cuaderno")}
    assert puntajes["repetidor"] > puntajes["unico"]
    assert puntajes["repetidor"] < 3 * puntajes["unico"]


def test_termino_en_todos_los_documentos_no_ordena():
    # idf ~0 para lo ubicuo: si TODAS dicen 'archivo', 'archivo' no discrimina.
    cat = [_t("uno", "archivo uno"), _t("dos", "archivo dos"), _t("tres", "archivo tres")]
    ix2 = indexar(cat)
    for _n, score, _d in buscar(ix2, "archivo"):
        assert score < 0.5


# ── cache del indice ───────────────────────────────────────────────────
def test_indice_cacheado_por_hash_del_catalogo():
    copia = [dict(t) for t in CATALOGO]
    assert huella_catalogo(CATALOGO) == huella_catalogo(copia)
    assert indexar(CATALOGO) is indexar(copia)          # mismo contenido -> mismo indice
    otro = copia + [_t("herramienta_nueva", "hace algo distinto")]
    assert huella_catalogo(otro) != huella_catalogo(CATALOGO)
    assert indexar(otro) is not indexar(CATALOGO)


def test_cache_no_confunde_catalogos_que_solo_difieren_en_params_o_danger():
    # REGRESION: la huella hasheaba solo nombre+descripcion, asi que estos dos
    # colisionaban y el cache servia el spec VIEJO — se le anunciaba al modelo
    # una firma equivocada y, peor, un 'danger' equivocado (lo que decide si la
    # tool pide confirmacion).
    v1 = [{"nombre": "ejecutar", "descripcion": "Ejecuta un comando de shell",
           "params": [{"nombre": "cmd"}], "danger": True}]
    v2 = [{"nombre": "ejecutar", "descripcion": "Ejecuta un comando de shell",
           "params": [{"nombre": "cmd"}, {"nombre": "timeout"}], "danger": False}]
    assert huella_catalogo(v1) != huella_catalogo(v2)
    assert indexar(v2)["specs"]["ejecutar"]["danger"] is False
    assert len(indexar(v2)["specs"]["ejecutar"]["params"]) == 2
    assert indexar(v1)["specs"]["ejecutar"]["danger"] is True


def test_huella_estable_con_valores_no_serializables():
    # Un spec con un callable no debe romper la huella NI hacerla cambiar entre
    # llamadas (str(funcion) trae la direccion de memoria: seria un cache miss
    # permanente y un 'is' que nunca se cumple).
    cat = [{"nombre": "raro", "descripcion": "tiene un handler", "handler": len}]
    assert huella_catalogo(cat) == huella_catalogo([dict(cat[0])])
    assert indexar(cat) is indexar([dict(cat[0])])


def test_catalogo_iterable_no_produce_indice_vacio_en_silencio():
    # REGRESION: indexar() recorre el catalogo dos veces (huella + indexado). Con
    # un generador la segunda pasada salia vacia y devolvia un indice de 0 docs
    # SIN error: el modelo no encontraba NINGUNA herramienta y nadie se enteraba.
    gen = (t for t in [_t("aaa_uno", "primera zzz"), _t("aaa_dos", "segunda zzz")])
    ix = indexar(gen)
    assert ix["n"] == 2
    assert set(primeros(buscar(ix, "zzz"))) == {"aaa_uno", "aaa_dos"}


def test_entradas_que_no_son_dict_se_ignoran_sin_reventar():
    ix = indexar(["no_soy_un_dict", None, 42, _t("ok", "una herramienta de verdad")])
    assert ix["n"] == 1 and "ok" in ix["specs"]


# ── sesion de catalogo activo ──────────────────────────────────────────
def test_activar_agrega_y_reporta_desconocidas(sesion):
    r = activar(sesion, ["git_estado", "tests", "no_existe_esta"])
    assert r["activadas"] == ["git_estado", "tests"]
    assert r["desconocidas"] == ["no_existe_esta"]
    assert r["desalojadas"] == []
    assert activas(sesion) == ["git_estado", "tests"]


def test_reactivar_refresca_lru_sin_consumir_cupo(sesion):
    activar(sesion, ["git_estado", "tests", "fecha"])
    activar(sesion, ["git_estado"])
    assert activas(sesion) == ["tests", "fecha", "git_estado"]   # va al final


def test_tope_duro_desaloja_por_lru(sesion):
    nombres = ["git_estado", "git_diff", "git_log", "tests", "fecha", "calcular",
               "resumir", "notas"]
    activar(sesion, nombres)
    assert len(activas(sesion)) == MAX_ACTIVAS == 8
    r = activar(sesion, ["repo_map", "code_grafo"])
    assert r["desalojadas"] == ["git_estado", "git_diff"]        # las mas viejas
    assert len(activas(sesion)) == 8
    assert activas(sesion)[-2:] == ["repo_map", "code_grafo"]


def test_lote_mas_grande_que_el_tope_conserva_los_ultimos(indice):
    s = nueva_sesion(indice, max_activas=3)
    r = activar(s, ["git_estado", "git_diff", "git_log", "tests", "fecha"])
    assert activas(s) == ["git_log", "tests", "fecha"]
    assert r["desalojadas"] == ["git_estado", "git_diff"]


def test_catalogo_efectivo_es_base_mas_activadas_sin_duplicar(sesion):
    # 'buscar' YA esta en el catalogo base: activarla no debe duplicarla.
    activar(sesion, ["git_estado", "buscar"])
    efectivo = catalogo_efectivo(sesion, BASE)
    nombres = [t["nombre"] for t in efectivo]
    assert nombres[: len(BASE)] == [t["nombre"] for t in BASE]   # base intacta y primero
    assert nombres.count("buscar") == 1
    assert nombres[-1] == "git_estado"
    assert len(efectivo) == len(BASE) + 1
    # las specs inyectadas son las del catalogo (schema completo, no solo el nombre)
    inyectada = efectivo[-1]
    assert inyectada["descripcion"] == "git_estado -- git status resumido"
    assert set(inyectada) >= {"nombre", "descripcion", "params", "danger"}


def test_catalogo_efectivo_nunca_pasa_el_tope(sesion):
    activar(sesion, [t["nombre"] for t in CATALOGO])
    assert len(catalogo_efectivo(sesion, BASE)) <= len(BASE) + MAX_ACTIVAS


def test_catalogo_efectivo_no_muta_la_base(sesion):
    antes = [dict(t) for t in BASE]
    activar(sesion, ["fecha"])
    efectivo = catalogo_efectivo(sesion, BASE)
    assert BASE == antes
    # y tampoco al reves: recortar la lista devuelta no debe recortar la base.
    efectivo.pop()
    assert len(BASE) == len(antes)


def test_spec_inyectada_es_copia_profunda_no_envenena_el_cache():
    # REGRESION: specs[nombre] = dict(entrada) es copia SUPERFICIAL. El indice
    # vive en un cache global de modulo, asi que quien recibiera el spec y tocara
    # su lista 'params' corrompia el catalogo de TODAS las sesiones siguientes.
    cat = [{"nombre": "ejecutar_x", "descripcion": "Ejecuta algo",
            "params": [{"nombre": "cmd"}], "danger": True}]
    ix = indexar(cat)
    s = nueva_sesion(ix)
    activar(s, "ejecutar_x")
    spec = catalogo_efectivo(s, [])[0]
    spec["params"].append({"nombre": "INYECTADO"})
    spec["danger"] = False
    assert ix["specs"]["ejecutar_x"]["params"] == [{"nombre": "cmd"}]
    assert ix["specs"]["ejecutar_x"]["danger"] is True
    assert catalogo_efectivo(s, [])[0]["danger"] is True     # la siguiente lectura, sana


def test_sesion_sin_indice_reporta_desconocidas_en_vez_de_reventar():
    s = nueva_sesion(None)
    assert activar(s, "git_estado") == {"activadas": [], "desalojadas": [],
                                        "desconocidas": ["git_estado"]}
    assert activas(s) == [] and catalogo_efectivo(s, BASE) == BASE


# ── el texto que ve el modelo ──────────────────────────────────────────
def test_texto_resultado_lista_nombres_y_dice_que_ya_estan_disponibles(indice):
    res = buscar(indice, "ver que cambio en el repositorio", limite=3)
    txt = texto_resultado_busqueda(res)
    for nombre, _s, _d in res:
        assert nombre in txt
    assert "git status resumido" in txt
    assert "disponibles" in txt
    # una linea por herramienta + linea en blanco + la frase final; sin adornos.
    lineas = [l for l in txt.splitlines() if l.strip()]
    assert len(lineas) == len(res) + 1
    # "sin adornos" se comprueba sobre la FORMA (cada item es '- nombre: desc'),
    # no con "'*' not in txt": las descripciones reales traen esos caracteres
    # (calcular dice "(+ - * / // % **)") y esa asercion pasaba de casualidad.
    for linea, (nombre, _s, _d) in zip(lineas, res):
        assert linea.startswith(f"- {nombre}: ")
    assert not txt.startswith("#") and "**" not in lineas[-1]


def test_texto_resultado_no_rompe_con_descripciones_con_simbolos(indice):
    # 'calcular' describe "(+ - * / // % **)": debe salir tal cual, sin escapes.
    txt = texto_resultado_busqueda(buscar(indice, "sumar dos numeros", limite=1))
    assert txt.startswith("- calcular: ") and "**" in txt


def test_descripcion_larga_se_recorta_a_una_linea():
    largo = ("palabra " * 60).strip() + "\n\tsegunda linea"
    txt = texto_resultado_busqueda([("tool_x", 1.0, largo)])
    primera = txt.splitlines()[0]
    assert primera.endswith("...") and len(primera) <= 175
    assert "\t" not in txt


def test_texto_resultado_vacio_pide_reformular():
    txt = texto_resultado_busqueda([])
    assert "Sin herramientas" in txt and "Reformula" in txt


def test_esquema_de_buscar_herramientas_tiene_la_forma_del_catalogo():
    assert ESQUEMA_BUSCAR_HERRAMIENTAS["nombre"] == "buscar_herramientas"
    assert set(ESQUEMA_BUSCAR_HERRAMIENTAS) >= {"nombre", "descripcion", "params", "danger"}
    assert ESQUEMA_BUSCAR_HERRAMIENTAS["params"][0]["nombre"] == "consulta"
    assert ESQUEMA_BUSCAR_HERRAMIENTAS["danger"] is False


# ── contrato de aislamiento (encargo: NO importar el registry) ──────────
def test_el_modulo_no_importa_cognia_agent_tools():
    import cognia.harness.registro_dinamico as mod
    fuente = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    importes = [l.strip() for l in fuente.splitlines()
                if l.startswith(("import ", "from "))]
    assert importes, "el modulo deberia importar al menos stdlib"
    # Ni el registry ni NINGUN modulo del proyecto: autocontenido sobre stdlib.
    assert not [l for l in importes if "cognia" in l], importes


# ── ciclo completo: buscar -> activar -> el modelo la ve ───────────────
def test_ciclo_buscar_activar_ver(indice):
    s = nueva_sesion(indice)
    base_nombres = {t["nombre"] for t in BASE}
    assert "git_estado" not in base_nombres                 # el modelo NO la tiene
    res = buscar(indice, "ver que cambio en el repositorio", limite=3,
                 excluir=tuple(base_nombres))
    activar(s, [n for n, _s, _d in res])
    texto = texto_resultado_busqueda(res)
    assert "git_estado" in texto
    assert "git_estado" in {t["nombre"] for t in catalogo_efectivo(s, BASE)}
