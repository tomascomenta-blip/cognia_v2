"""Regresion de cognia/harness/render_tools.py — el render de tool calls.

Antes de este modulo la actividad del agente salia como texto suelto y el
RESULTADO se volcaba entero o se perdia. Estos tests fijan el patron de los
harnesses punteros que Cognia no tenia: glifo de estado + tool(args resumidos),
resultado colgando en UNA linea con la pista de expansion, razonamiento plegado
y linea de progreso — todo dentro del ancho y con fallback ASCII.

Lo que mas se testea es `resumir_resultado`: es la funcion que decide QUE se ve,
y un resumen vacio o mentiroso es peor que no resumir.
"""
import os

import pytest

from cognia.harness import render_tools as rt


@pytest.fixture()
def unicode_on(monkeypatch):
    """Fuerza el juego Unicode (COGNIA_ASCII=0), sin depender de la consola."""
    monkeypatch.setenv("COGNIA_ASCII", "0")


@pytest.fixture()
def ascii_on(monkeypatch):
    monkeypatch.setenv("COGNIA_ASCII", "1")


# -- glifos y fallback --------------------------------------------------------

def test_glifos_unicode_por_estado(unicode_on):
    assert rt.glifo_estado("curso") == "·"
    assert rt.glifo_estado("ok") == "●"
    assert rt.glifo_estado("error") == "●"     # el COLOR distingue ok/error
    assert rt.conector() == "└"


def test_glifos_ascii_cambian_de_FORMA_no_solo_de_color(ascii_on):
    # Sin color garantizado, ok y error NO pueden compartir glifo.
    assert rt.glifo_estado("curso") == "o"
    assert rt.glifo_estado("ok") == "+"
    assert rt.glifo_estado("error") == "x"
    assert rt.conector() == "|_"


def test_cognia_ascii_manda_sobre_la_deteccion(monkeypatch):
    monkeypatch.setenv("COGNIA_ASCII", "1")
    assert rt.usar_ascii() is True
    monkeypatch.setenv("COGNIA_ASCII", "0")
    assert rt.usar_ascii() is False


def test_consola_que_no_codifica_cae_a_ascii(monkeypatch):
    monkeypatch.delenv("COGNIA_ASCII", raising=False)

    class _Cp1252:
        encoding = "cp1252"

    monkeypatch.setattr(rt.sys, "stdout", _Cp1252())
    assert rt.usar_ascii() is True


def test_estados_validos_y_estilos_logicos_del_tema():
    assert rt.estilo_estado("curso") == "info_dim"
    assert rt.estilo_estado("ok") == "ok_cl"
    assert rt.estilo_estado("error") == "err_cl"
    with pytest.raises(ValueError):
        rt.glifo_estado("terminada")


# -- ancho visual y elipsis en el MEDIO ---------------------------------------

def test_ancho_visual_cuenta_los_ideogramas_como_dos():
    assert rt.ancho_visual("abc") == 3
    assert rt.ancho_visual("你好") == 4          # 2 chars, 4 columnas


def test_truncar_medio_conserva_el_FINAL_que_es_lo_informativo(unicode_on):
    ruta = "cognia/harness/permisos_reglas.py"
    corto = rt.truncar_medio(ruta, 20)
    assert rt.ancho_visual(corto) <= 20
    assert corto.endswith("reglas.py")            # la cola sobrevive
    assert corto.startswith("cognia")
    assert "…" in corto


def test_truncar_medio_no_parte_caracteres_anchos(unicode_on):
    texto = "你好" * 20
    corto = rt.truncar_medio(texto, 11)
    assert rt.ancho_visual(corto) <= 11
    assert all(ord(c) for c in corto)             # sigue siendo texto valido


def test_truncar_medio_sin_sitio_para_la_elipsis(unicode_on):
    assert rt.truncar_medio("abcdefgh", 2) == "ab"


# -- resumir_args -------------------------------------------------------------

def test_ruta_bajo_la_raiz_se_vuelve_relativa(tmp_path):
    destino = tmp_path / "cognia" / "cli.py"
    assert rt.resumir_args("leer_archivo", str(destino),
                           raiz=str(tmp_path)) == "cognia/cli.py"


def test_ruta_fuera_de_la_raiz_se_deja_absoluta_y_normalizada(tmp_path):
    fuera = os.path.join(os.path.abspath(os.sep), "otro_arbol", "x.py")
    out = rt.resumir_args("leer_archivo", fuera, raiz=str(tmp_path))
    assert out.endswith("otro_arbol/x.py")
    assert "\\" not in out


def test_argumentos_con_espacios_van_entrecomillados():
    out = rt.resumir_args("buscar", "class Foo | cognia/agent")
    assert out == '"class Foo", cognia/agent'


def test_ejecutar_muestra_solo_el_comando_sin_el_cuerpo(unicode_on):
    cmd = "python - <<EOF\nprint('hola')\nEOF"
    out = rt.resumir_args("ejecutar", cmd)
    assert out == "python - <<EOF…"
    assert "print" not in out


def test_ejecutar_no_se_parte_por_el_pipe_del_shell():
    out = rt.resumir_args("ejecutar", "git log | head -3")
    assert out == "git log | head -3"


def test_escritura_muestra_la_ruta_y_JAMAS_el_payload(tmp_path):
    ruta = tmp_path / "notas.md"
    args = f"{ruta} | " + "linea de contenido\n" * 50
    out = rt.resumir_args("escribir_archivo", args, raiz=str(tmp_path))
    assert out == "notas.md"


def test_editar_archivo_no_filtra_los_bloques_search_replace(tmp_path):
    ruta = tmp_path / "motor.py"
    args = f"{ruta} | <<<<<<< SEARCH\nviejo\n=======\nnuevo\n>>>>>>> REPLACE"
    out = rt.resumir_args("editar_archivo", args, raiz=str(tmp_path))
    assert out == "motor.py"
    assert "SEARCH" not in out


def test_args_tipados_en_dict(tmp_path):
    assert rt.resumir_args("leer_archivo", {"path": "cognia/cli.py"}) == "cognia/cli.py"
    out = rt.resumir_args("buscar", {"patron": "tool", "dir": "cognia"})
    assert out == "patron=tool, dir=cognia"
    # con payload, la clave se cae y queda la ruta
    out = rt.resumir_args("escribir_archivo",
                          {"path": "docs/a.md", "contenido": "x" * 500})
    assert out == "docs/a.md"


def test_escritura_con_el_PAYLOAD_primero_sigue_mostrando_la_ruta():
    # Bug real: la ruta se tomaba por POSICION (partes[0]), así que un dict con
    # el contenido primero volcaba el payload en pantalla — exactamente lo que
    # este módulo promete no hacer.
    out = rt.resumir_args("escribir_archivo",
                          {"contenido": "SECRETO token=abc123", "path": "a.md"})
    assert out == "a.md"
    assert "SECRETO" not in out
    # sin clave reconocible, gana la que TIENE forma de ruta
    out = rt.resumir_args("editar_archivo",
                          {"bloque": "<<<<<<< SEARCH\nviejo", "obj": "motor.py"})
    assert out == "motor.py"
    # y si ninguna parece ruta, se conserva la primera (no se inventa nada)
    assert rt.resumir_args("escribir_archivo", "Makefile | contenido") == "Makefile"


def test_args_vacios_dan_cadena_vacia():
    assert rt.resumir_args("git_estado", "") == ""
    assert rt.resumir_args("git_estado", None) == ""


def test_resumir_args_respeta_el_ancho(unicode_on):
    largo = "cognia/" + "sub/" * 40 + "final.py"
    out = rt.resumir_args("leer_archivo", largo, ancho=30)
    assert rt.ancho_visual(out) <= 30
    assert out.endswith("final.py")


# -- linea_llamada ------------------------------------------------------------

def test_linea_llamada_forma_y_estilo(unicode_on):
    glifo, texto, estilo = rt.linea_llamada("leer_archivo", "cognia/cli.py", "ok")
    assert glifo == "●"
    assert texto == "leer_archivo(cognia/cli.py)"
    assert estilo == "ok_cl"


def test_linea_llamada_en_curso_es_gris(unicode_on):
    glifo, _, estilo = rt.linea_llamada("buscar", "tool | cognia", "curso")
    assert (glifo, estilo) == ("·", "info_dim")


def test_linea_llamada_cabe_en_el_ancho(unicode_on):
    glifo, texto, _ = rt.linea_llamada(
        "editar_archivo", "cognia/" + "muy_largo/" * 20 + "x.py", "ok", ancho=40)
    assert rt.ancho_visual(glifo + " " + texto) <= 40
    assert texto.startswith("editar_archivo(") and texto.endswith(")")


def test_linea_llamada_cabe_aunque_el_NOMBRE_no_quepa(unicode_on):
    # Bug real: el recorte final medía el TEXTO contra `ancho` olvidando el
    # glifo y su espacio, y la línea salía 2 columnas más ancha de lo pedido
    # (42 en un ancho de 40) justo cuando el nombre ya no cabía solo.
    glifo, texto, _ = rt.linea_llamada(
        "herramienta_con_un_nombre_absurdamente_largo_generado", "x.py",
        "ok", ancho=40)
    assert rt.ancho_visual(glifo + " " + texto) <= 40


def test_linea_llamada_sin_args_no_deja_basura():
    _, texto, _ = rt.linea_llamada("git_estado", "", "ok")
    assert texto == "git_estado()"


# -- resumir_resultado: lo que decide QUE se ve --------------------------------

def test_lectura_resume_en_lineas():
    res = "RESULTADO leer_archivo cognia/cli.py: uno\ndos\ntres"
    assert rt.resumir_resultado("leer_archivo", res) == "3 lineas"


def test_lectura_de_una_linea_va_en_SINGULAR():
    assert rt.resumir_resultado(
        "leer_archivo", "RESULTADO leer_archivo a.txt: sola") == "1 linea"


def test_lectura_de_archivo_vacio():
    res = "RESULTADO leer_archivo a.txt: (archivo vacio)"
    assert rt.resumir_resultado("leer_archivo", res) == "archivo vacio"


def test_lectura_no_cuenta_el_marcador_de_truncado():
    res = ("RESULTADO leer_archivo a.py: uno\ndos\n"
           "... [TRUNCADO: mostrando lineas 1-2 de 900 (archivo de 40 chars)]")
    assert rt.resumir_resultado("leer_archivo", res) == "2 lineas"


def test_el_CONTENIDO_no_dicta_el_veredicto_de_archivo_vacio():
    # Bug real (verificacion e2e con tools de verdad, 2026-08-12): leer un
    # fuente que MENCIONA '(archivo vacio)' se resumia como archivo vacio.
    res = ("RESULTADO leer_archivo render_tools.py: uno\n"
           "if '(archivo vacio)' in cuerpo:\ntres")
    assert rt.resumir_resultado("leer_archivo", res) == "3 lineas"


def test_contar_lineas_devuelve_SU_frase_no_las_lineas_del_resumen():
    # Bug real de la misma corrida: contar_lineas sobre un archivo de 660
    # lineas se resumia como '1 linea' (las lineas del propio resumen).
    res = "RESULTADO contar_lineas render_tools.py: 660 lineas"
    assert rt.resumir_resultado("contar_lineas", res) == "660 lineas"


def test_listado_cuenta_ENTRADAS_no_lineas():
    res = "RESULTADO listar cognia: cli.py\nharness/\nux/"
    assert rt.resumir_resultado("listar", res) == "3 entradas"
    assert rt.resumir_resultado("git_log", "RESULTADO git_log: a1 fix") == "1 entrada"


def test_la_CABECERA_no_se_cuenta_cuando_el_prefijo_acaba_en_salto():
    # Bug real: 'arbol', 'code_grafo', 'recordar' y 'cuaderno consultar' abren
    # con 'RESULTADO x:\n' (dos puntos y salto). El regex del prefijo exigía un
    # espacio detrás, no lo quitaba, y la cabecera se contaba como una entrada:
    # un árbol de 2 archivos se resumía como '3 entradas'.
    assert rt.resumir_resultado(
        "arbol", "RESULTADO arbol:\ncognia/\n  cli.py") == "2 entradas"
    assert rt.resumir_resultado(
        "recordar", "RESULTADO recordar 'x':\nhecho uno\nhecho dos") == "2 resultados"
    assert rt.resumir_resultado(
        "code_grafo", "RESULTADO code_grafo:\nA importa B\nB importa C") == "2 lineas"
    # y el ':' de una unidad de Windows sigue SIN cortar
    assert rt.resumir_resultado(
        "leer_archivo", "RESULTADO leer_archivo C:/x/cli.py: uno\ndos") == "2 lineas"


def test_busqueda_cuenta_los_hits_separados_por_pipe():
    res = ("RESULTADO buscar 'tool': a.py:1: x | b.py:9: y | c.py:3: z")
    assert rt.resumir_resultado("buscar", res) == "3 resultados"


def test_busqueda_de_un_hit_va_en_SINGULAR():
    res = "RESULTADO buscar 'tool': a.py:1: x"
    assert rt.resumir_resultado("buscar", res) == "1 resultado"


def test_busqueda_sin_coincidencias_lo_dice():
    res = ("RESULTADO buscar 'zzz': sin coincidencias en cognia "
           "(se busco en 900 archivos)")
    assert rt.resumir_resultado("buscar", res) == "sin resultados"


def test_escritura_con_diff_da_mas_y_menos():
    res = ("RESULTADO editar_archivo x.py: OK (1 bloque [exacto], 400 chars)\n"
           "--- antes\n+++ despues\n@@ -1,3 +1,4 @@\n ctx\n-viejo\n+nuevo\n+extra")
    assert rt.resumir_resultado("editar_archivo", res) == "+2 -1 lineas"


def test_escritura_sin_diff_reporta_lo_que_la_tool_declaro():
    res = "RESULTADO escribir_archivo notas.md: OK (1234 chars)"
    assert rt.resumir_resultado("escribir_archivo", res) == "1234 chars escritos"


def test_escritura_sin_cambios():
    res = "RESULTADO editar_archivo x.py: sin cambios (el REPLACE es igual)"
    assert rt.resumir_resultado("editar_archivo", res) == "sin cambios"


def test_ejecucion_muestra_la_primera_linea_UTIL():
    res = ("RESULTADO ejecutar: \n\n====================\n"
           "5 passed in 0.42s\nmas ruido")
    assert rt.resumir_resultado("ejecutar", res) == "5 passed in 0.42s"


def test_ejecucion_sin_output_no_queda_vacia():
    assert rt.resumir_resultado(
        "ejecutar", "RESULTADO ejecutar: (sin output)") == "(sin output)"


def test_error_de_tool_se_recorta_pero_NUNCA_queda_vacio():
    res = ("RESULTADO editar_archivo x.py ERROR: el bloque SEARCH no casa "
           "en el archivo; lineas parecidas: 12, 44")
    out = rt.resumir_resultado("editar_archivo", res)
    assert out.startswith("el bloque SEARCH no casa")
    assert "RESULTADO" not in out


def test_error_con_exit_code_es_error_aunque_no_diga_ERROR():
    res = "RESULTADO ejecutar (exit 1): ModuleNotFoundError: no such module"
    out = rt.resumir_resultado("ejecutar", res)
    assert "ModuleNotFoundError" in out


def test_traceback_resume_por_la_ULTIMA_linea():
    res = ("Traceback (most recent call last):\n"
           "  File \"x.py\", line 3, in <module>\n"
           "ValueError: patron invalido")
    assert rt.resumir_resultado("ejecutar", res) == "ValueError: patron invalido"


@pytest.mark.parametrize("tool,texto", [
    ("leer_archivo", ""),
    ("buscar", ""),
    ("editar_archivo", ""),
    ("ejecutar", ""),
    ("tool_desconocida", ""),
    ("leer_archivo", "   \n\n  "),
    ("ejecutar", "RESULTADO ejecutar ERROR:"),
    ("desconocida", "RESULTADO desconocida: \n\n"),
    ("buscar", None),
])
def test_resumir_resultado_JAMAS_devuelve_vacio(tool, texto):
    out = rt.resumir_resultado(tool, texto)
    assert out and out.strip(), f"{tool!r} devolvio un resumen vacio"


def test_tool_desconocida_no_miente_y_da_la_primera_linea():
    out = rt.resumir_resultado("musica_orquestar", "pista lista: 4 instrumentos\nmas")
    assert out == "pista lista: 4 instrumentos"


# -- linea_resultado ----------------------------------------------------------

def test_linea_resultado_unicode(unicode_on):
    res = "RESULTADO leer_archivo cli.py: " + "\n".join(str(i) for i in range(46))
    linea = rt.linea_resultado(res, tool="leer_archivo")
    assert linea == "  └ 46 lineas (ctrl+o para ver todo)"


def test_linea_resultado_ascii(ascii_on):
    res = "RESULTADO leer_archivo cli.py: a\nb"
    linea = rt.linea_resultado(res, tool="leer_archivo")
    assert linea == "  |_ 2 lineas (ctrl+o para ver todo)"
    linea.encode("ascii")            # no se cuela ningun glifo Unicode


def test_linea_resultado_no_expandible_sin_pista(unicode_on):
    linea = rt.linea_resultado("RESULTADO leer_archivo a: x", expandible=False,
                               tool="leer_archivo")
    assert linea == "  └ 1 linea"
    assert "ctrl+o" not in linea


def test_linea_resultado_respeta_el_ancho_y_sacrifica_la_PISTA(unicode_on):
    res = "RESULTADO editar_archivo x.py ERROR: " + "detalle larguisimo " * 20
    linea = rt.linea_resultado(res, ancho=30, tool="editar_archivo")
    assert rt.ancho_visual(linea) <= 30
    assert "detalle" in linea            # el resumen sobrevive, la pista no
    assert "ctrl+o" not in linea


def test_linea_resultado_sin_tool_usa_el_resumen_generico(unicode_on):
    linea = rt.linea_resultado("todo listo\nsegunda linea")
    assert linea.startswith("  └ todo listo")


# -- razonamiento -------------------------------------------------------------

def test_linea_razonamiento(unicode_on):
    assert rt.linea_razonamiento(4) == (
        "∴ pensó 4s (ctrl+o para ver el razonamiento)")


def test_linea_razonamiento_visible_invita_a_ocultar(unicode_on):
    assert "ocultar" in rt.linea_razonamiento(4, visible=True)


@pytest.mark.parametrize("segundos,esperado", [
    (0, "0s"), (0.4, "0.4s"), (4, "4s"), (12.7, "13s"), (65, "1m 5s"),
    (120, "2m"), (-3, "0s"), (None, "0s"),
    # 59,6 s se redondeaba a "60s": un reloj que nunca marcaba el minuto.
    (59.6, "1m"), (59.4, "59s"),
])
def test_formato_de_segundos(unicode_on, segundos, esperado):
    assert rt.linea_razonamiento(segundos).startswith(
        "∴ pensó " + esperado)


def test_linea_razonamiento_ascii_es_ascii(ascii_on):
    linea = rt.linea_razonamiento(4)
    linea.encode("ascii")
    assert "4s" in linea


# -- progreso -----------------------------------------------------------------

def test_linea_progreso_sin_siguiente_es_UNA_linea(unicode_on):
    lineas = rt.linea_progreso("Pensando")
    assert lineas == ("· Pensando… (esc para interrumpir)",)


def test_linea_progreso_con_siguiente_cuelga_la_sublinea(unicode_on):
    lineas = rt.linea_progreso("Editando", siguiente="correr los tests")
    assert len(lineas) == 2
    assert lineas[1] == "  └ Siguiente: correr los tests"


def test_linea_progreso_junta_varios_atajos(unicode_on):
    linea = rt.linea_progreso(
        "Buscando", atajos=("esc para interrumpir", "ctrl+p comandos"))[0]
    assert linea.endswith("(esc para interrumpir · ctrl+p comandos)")


def test_linea_progreso_sin_atajos(unicode_on):
    assert rt.linea_progreso("Pensando", atajos=())[0] == "· Pensando…"


def test_linea_progreso_respeta_el_ancho(unicode_on):
    lineas = rt.linea_progreso("Ejecutando " + "cosa " * 30,
                               siguiente="algo muy largo " * 10, ancho=40)
    assert all(rt.ancho_visual(l) <= 40 for l in lineas)


def test_linea_progreso_ascii(ascii_on):
    lineas = rt.linea_progreso("Pensando", siguiente="revisar")
    for l in lineas:
        l.encode("ascii")
    assert lineas[0].startswith("o Pensando...")
    assert lineas[1].startswith("  |_ Siguiente:")


# -- contrato del modulo ------------------------------------------------------

def test_el_modulo_NO_imprime_nada(capsys, unicode_on):
    rt.linea_llamada("leer_archivo", "a.py", "ok")
    rt.linea_resultado("RESULTADO leer_archivo a.py: x", tool="leer_archivo")
    rt.linea_razonamiento(3)
    rt.linea_progreso("Pensando", siguiente="x")
    assert capsys.readouterr().out == ""


def test_bloque_llamada_devuelve_lineas_y_estilos_en_paralelo(unicode_on):
    lineas, estilos = rt.bloque_llamada(
        "leer_archivo", "cognia/cli.py", "ok",
        resultado="RESULTADO leer_archivo cognia/cli.py: a\nb\nc")
    assert lineas[0] == "● leer_archivo(cognia/cli.py)"
    assert lineas[1] == "  └ 3 lineas (ctrl+o para ver todo)"
    assert estilos == ("ok_cl", "info_dim")


def test_con_estilo_envuelve_y_escapa_corchetes():
    assert rt.con_estilo("hola", "info_dim") == "[info_dim]hola[/info_dim]"
    assert rt.con_estilo("a[1]", "ok_cl") == "[ok_cl]a\\[1][/ok_cl]"
    assert rt.con_estilo("hola", "") == "hola"


def test_el_fuente_del_modulo_es_ASCII_puro():
    # Leccion del repo: editar en Latin-1 corrompe los acentos y en Windows se
    # detecta tarde. El fuente se mantiene ASCII y los glifos van escapados.
    ruta = rt.__file__.replace(".pyc", ".py")
    with open(ruta, "rb") as fh:
        crudo = fh.read()
    crudo.decode("ascii")


def test_todas_las_salidas_son_ascii_con_COGNIA_ASCII(ascii_on):
    salidas = [
        rt.linea_llamada("ejecutar", "pytest -q", "error")[1],
        rt.linea_resultado("RESULTADO ejecutar (exit 1): fallo", tool="ejecutar"),
        rt.linea_razonamiento(9.5),
        *rt.linea_progreso("Trabajando", siguiente="seguir"),
        rt.resumir_args("leer_archivo", "una ruta/muy larga/" * 10, ancho=20),
    ]
    for s in salidas:
        s.encode("ascii")


# ---------------------------------------------------------------------------
# bloque_colapsado: el idioma Claude Code (colapso a N lineas + /expandir)
# ---------------------------------------------------------------------------

def _resultado_lectura(n):
    return ("RESULTADO leer_archivo cli.py: "
            + "\n".join(f"linea {i} del fichero" for i in range(1, n + 1)))


def test_conector_colgante_unicode_y_ascii(monkeypatch):
    monkeypatch.setenv("COGNIA_ASCII", "0")
    assert rt.conector_colgante() == "⎿"
    monkeypatch.setenv("COGNIA_ASCII", "1")
    assert rt.conector_colgante() == "|_"


def test_bloque_colapsado_colapsa_a_N_y_cuenta_lo_oculto(unicode_on):
    lineas, estilos = rt.bloque_colapsado(
        "leer_archivo", "cognia/cli.py", True, _resultado_lectura(10),
        max_lineas=3)
    assert lineas[0] == "● leer_archivo(cognia/cli.py)"
    assert lineas[1] == "  ⎿ 10 lineas"                # resumen de UNA linea
    assert lineas[2:5] == ("    linea 1 del fichero",
                           "    linea 2 del fichero",
                           "    linea 3 del fichero")
    assert lineas[5] == "  ⎿ … +7 lineas (/expandir)"  # 10 - 3 vistas
    assert estilos[0] == "ok_cl"
    assert all(e == "info_dim" for e in estilos[1:])   # lo colgante va gris


def test_bloque_colapsado_corto_no_pone_linea_de_colapso(unicode_on):
    lineas, _ = rt.bloque_colapsado(
        "leer_archivo", "a.py", True, _resultado_lectura(2), max_lineas=3)
    assert not any("/expandir" in l for l in lineas)
    assert "    linea 2 del fichero" in lineas


def test_bloque_colapsado_indice_apunta_al_enesimo(unicode_on):
    lineas, _ = rt.bloque_colapsado(
        "leer_archivo", "a.py", True, _resultado_lectura(9), indice=4)
    assert lineas[-1].endswith("(/expandir 4)")


def test_bloque_colapsado_error_se_VE(unicode_on):
    res = "RESULTADO editar_archivo x.py ERROR: el bloque SEARCH no casa"
    lineas, estilos = rt.bloque_colapsado(
        "editar_archivo", "x.py", False, res, max_lineas=3)
    assert estilos[0] == "err_cl"
    assert estilos[1] == "err_cl"          # el resumen del fallo, en rojo
    assert "el bloque SEARCH no casa" in lineas[1]


def test_bloque_colapsado_no_repite_el_cuerpo_de_UNA_linea(unicode_on):
    # el resumen de 'ejecutar' ES la primera linea util: repetirla como
    # cuerpo la mostraba dos veces seguidas
    res = "RESULTADO ejecutar: 5 passed in 0.42s"
    lineas, _ = rt.bloque_colapsado("ejecutar", "pytest -q", True, res)
    assert sum("5 passed" in l for l in lineas) == 1
    # y lo deduplicado NO se cuenta como oculto: '+1 linea' que /expandir no
    # agranda es un resumen mentiroso (cazado en el REPL real, 2026-08-23)
    assert not any("/expandir" in l for l in lineas)


def test_bloque_colapsado_dedup_multilinea_cuenta_honesto(unicode_on):
    # cuerpo de 5 lineas cuya PRIMERA es el resumen: se muestra el resumen,
    # 3 lineas nuevas de cabeza, y quedan 5-1-3=1 oculta (no 2)
    res = "RESULTADO ejecutar: 643\n---\nuno\ndos\ntres"
    lineas, _ = rt.bloque_colapsado("ejecutar", "wc -l", True, res,
                                    max_lineas=3)
    assert lineas[1] == "  ⎿ 643"
    assert sum("643" in l for l in lineas) == 1             # sin duplicado
    assert lineas[2:5] == ("    ---", "    uno", "    dos")
    assert lineas[5].endswith("+1 linea (/expandir)")


def test_bloque_colapsado_max_lineas_cero_dedup_honesto(unicode_on):
    """Regresion (revision adversarial 2026-08-23): con '/expandir lineas 0'
    (max_lineas=0, '0 = solo el resumen') la deduplicacion exigia
    max_lineas > 0, asi que la UNICA linea del cuerpo — que ya esta en
    pantalla como resumen — se contaba como oculta: '643' y debajo
    '+1 linea (/expandir)' que /expandir no agrandaba. El mismo resumen
    mentiroso que F1 dice haber cazado, vivo en la rama max_lineas=0."""
    res = "RESULTADO ejecutar (exit 0): 643"
    lineas, _ = rt.bloque_colapsado("ejecutar", "ls tests | wc -l", True, res,
                                    max_lineas=0)
    assert lineas[1] == "  ⎿ 643"
    assert not any("/expandir" in l for l in lineas)
    # y con lineas ocultas DE VERDAD la cola sigue diciendo la cuenta honesta
    res2 = "RESULTADO ejecutar (exit 0): 643\nuno\ndos"
    lineas2, _ = rt.bloque_colapsado("ejecutar", "wc -l", True, res2,
                                     max_lineas=0)
    assert lineas2[-1].endswith("+2 lineas (/expandir)")


def test_bloque_colapsado_max_lineas_cero_solo_resumen(unicode_on):
    lineas, _ = rt.bloque_colapsado(
        "leer_archivo", "a.py", True, _resultado_lectura(6), max_lineas=0)
    assert lineas[1] == "  ⎿ 6 lineas"
    assert lineas[2] == "  ⎿ … +6 lineas (/expandir)"
    assert len(lineas) == 3


def test_bloque_colapsado_respeta_el_ancho(unicode_on):
    res = ("RESULTADO leer_archivo x: "
           + "\n".join("x" * 300 for _ in range(6)))
    lineas, _ = rt.bloque_colapsado(
        "leer_archivo", "cognia/" + "sub/" * 30 + "f.py", True, res,
        ancho=50)
    assert all(rt.ancho_visual(l) <= 50 for l in lineas)


def test_bloque_colapsado_ascii_es_ascii(ascii_on):
    lineas, _ = rt.bloque_colapsado(
        "leer_archivo", "a.py", True, _resultado_lectura(9))
    for l in lineas:
        l.encode("ascii")
    assert any("+6 lineas (/expandir)" in l for l in lineas)


# ---------------------------------------------------------------------------
# SNAPSHOTS del render a string ANSI (COLUMNS=60/80/120)
# ---------------------------------------------------------------------------
# Leccion del repo: el juicio visual sin medir no vale (el capturador de PNG
# pinto en blanco durante meses). El golden fija BYTES: glifo, estilo por
# linea, elipsis del ancho y la linea de colapso, con rich de verdad.

_ARGS_LARGOS = ("cognia/subsistema_de_render/con_un_camino/"
                "deliberadamente_larguisimo/hasta/el_fichero_final.py")

_GOLDEN_ANSI = {
    60: ("\x1b[32m● leer_archivo(cognia/subsistema_de_…ta/el_fichero_final.py)\x1b[0m\n"
         "\x1b[2m  ⎿ 7 lineas\x1b[0m\n"
         "\x1b[2m    linea 1 del fichero\x1b[0m\n"
         "\x1b[2m    linea 2 del fichero\x1b[0m\n"
         "\x1b[2m    linea 3 del fichero\x1b[0m\n"
         "\x1b[2m  ⎿ … +4 lineas (/expandir 1)\x1b[0m\n"),
    80: ("\x1b[32m● leer_archivo(cognia/subsistema_de_render/con…uisimo/hasta/el_fichero_final.py)\x1b[0m\n"
         "\x1b[2m  ⎿ 7 lineas\x1b[0m\n"
         "\x1b[2m    linea 1 del fichero\x1b[0m\n"
         "\x1b[2m    linea 2 del fichero\x1b[0m\n"
         "\x1b[2m    linea 3 del fichero\x1b[0m\n"
         "\x1b[2m  ⎿ … +4 lineas (/expandir 1)\x1b[0m\n"),
    120: ("\x1b[32m● leer_archivo(cognia/subsistema_de_render/con_un_camino/deliberadamente_larguisimo/hasta/el_fichero_final.py)\x1b[0m\n"
          "\x1b[2m  ⎿ 7 lineas\x1b[0m\n"
          "\x1b[2m    linea 1 del fichero\x1b[0m\n"
          "\x1b[2m    linea 2 del fichero\x1b[0m\n"
          "\x1b[2m    linea 3 del fichero\x1b[0m\n"
          "\x1b[2m  ⎿ … +4 lineas (/expandir 1)\x1b[0m\n"),
}


@pytest.mark.parametrize("columns", [60, 80, 120])
def test_snapshot_ansi_del_bloque_colapsado(unicode_on, monkeypatch, columns):
    import io
    rich = pytest.importorskip("rich")     # noqa: F841 (venv312 lo tiene)
    from rich.console import Console
    from rich.theme import Theme
    monkeypatch.setenv("COLUMNS", str(columns))
    buf = io.StringIO()
    con = Console(file=buf, width=columns, force_terminal=True,
                  color_system="standard", legacy_windows=False,
                  theme=Theme({"ok_cl": "green", "err_cl": "red",
                               "info_dim": "dim"}), highlight=False)
    res = ("RESULTADO leer_archivo x: "
           + "\n".join(f"linea {i} del fichero" for i in range(1, 8)))
    lineas, estilos = rt.bloque_colapsado(
        "leer_archivo", _ARGS_LARGOS, True, res, max_lineas=3,
        ancho=columns, raiz="C:/otro", indice=1)
    for l, e in zip(lineas, estilos):
        con.print(l, style=e, markup=False)
    assert buf.getvalue() == _GOLDEN_ANSI[columns]


# ---------------------------------------------------------------------------
# El CABLEADO al renderer vivo (ux/renderer + ux/tool_buffer)
# ---------------------------------------------------------------------------
# La regresion que motiva la tanda: render_tools estaba ESCRITO Y TESTEADO
# pero huerfano — nadie lo importaba y el renderer pintaba con su propio
# codigo. Estos tests fallan sin el cableado.

@pytest.fixture()
def renderer_local(monkeypatch):
    """Renderer local (sin remoto), colapso activo con umbral 3 fijo (la
    config del usuario no puede mover el resultado del test)."""
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.delenv("COGNIA_RENDER_COLAPSO", raising=False)
    monkeypatch.setenv("COGNIA_ASCII", "0")
    from cognia.ux import renderer as rmod
    from cognia.ux import tool_buffer
    monkeypatch.setattr(rmod, "_config_colapso", lambda: (True, 3))
    tool_buffer.nuevo_turno()
    yield rmod.Renderer(console=None), tool_buffer
    tool_buffer.nuevo_turno()


def test_renderer_delega_en_render_tools_con_el_output_completo(
        renderer_local, capsys):
    from cognia.ux import events
    r, tool_buffer = renderer_local
    res = _resultado_lectura(10)
    tool_buffer.registrar("leer_archivo", "motor.py", res, True)
    r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                     resumen=res[:200], paso=1))
    out = capsys.readouterr().out
    assert "● leer_archivo(motor.py)" in out
    assert "⎿ 10 lineas" in out
    assert "linea 3 del fichero" in out                # cabeza visible
    assert "linea 4 del fichero" not in out            # colapsado
    assert "⎿ … +7 lineas (/expandir 1)" in out
    assert "⏺" not in out                              # el render viejo no sale


def test_renderer_sin_buffer_cae_al_render_viejo_honesto(
        renderer_local, capsys):
    # sin output completo, resumir el resumen MENTIRIA (contarle las lineas
    # al recorte de 200 chars): se conserva el render clasico
    from cognia.ux import events
    r, _ = renderer_local
    r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                     resumen="42 lineas", paso=1))
    out = capsys.readouterr().out
    assert "⏺ Leyendo motor.py — 42 lineas" in out
    assert "/expandir" not in out


def test_renderer_colapso_apagado_por_env_conserva_el_render_viejo(
        capsys, monkeypatch):
    # SIN el fixture: aca actua la _config_colapso REAL, que lee el env
    from cognia.ux import events
    from cognia.ux import renderer as rmod
    from cognia.ux import tool_buffer
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_ASCII", "0")
    monkeypatch.setenv("COGNIA_RENDER_COLAPSO", "0")
    tool_buffer.nuevo_turno()
    r = rmod.Renderer(console=None)
    res = _resultado_lectura(10)
    tool_buffer.registrar("leer_archivo", "motor.py", res, True)
    r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                     resumen=res[:200], paso=1))
    out = capsys.readouterr().out
    tool_buffer.nuevo_turno()
    assert "⏺ Leyendo motor.py" in out
    assert "/expandir" not in out


def test_renderer_bajo_remoto_conserva_el_formato_del_movil(
        renderer_local, capsys, monkeypatch):
    # es_eco_renderer clasifica por ⏺/✗: las lineas nuevas llegarian al chat
    # del movil como prosa (contrato de remoto/sesiones.py)
    from cognia.ux import events
    from cognia.ux import renderer as rmod
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    _, tool_buffer = renderer_local
    r = rmod.Renderer(console=None)          # relee el env en __init__
    res = _resultado_lectura(10)
    tool_buffer.registrar("leer_archivo", "motor.py", res, True)
    r(events.ToolFin(tool="leer_archivo", args="motor.py", ok=True,
                     resumen=res[:200], paso=1))
    out = capsys.readouterr().out
    assert "⏺ Leyendo motor.py" in out
    assert "/expandir" not in out and "⎿" not in out


def test_ultimo_para_casa_por_tool_y_prefijo():
    from cognia.ux import tool_buffer
    tool_buffer.nuevo_turno()
    tool_buffer.registrar("leer_archivo", "a.py", "RESULTADO a: uno", True)
    tool_buffer.registrar("buscar", "x", "RESULTADO buscar: hit", True)
    idx, e = tool_buffer.ultimo_para("leer_archivo", "RESULTADO a: uno")
    assert (idx, e["args"]) == (1, "a.py")
    # el 'ultimo del buffer' es de OTRA tool: no se le cuelga su output
    idx, e = tool_buffer.ultimo_para("leer_archivo", "RESULTADO otro: x")
    assert (idx, e) == (0, None)
    tool_buffer.nuevo_turno()
    assert tool_buffer.obtener() is None
