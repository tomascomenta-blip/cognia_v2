# -*- coding: utf-8 -*-
"""
Regresion (2026-08-12): una salida de tool GRANDE entraba entera al historial.

Un `leer_archivo` de 400 KB se comia la ventana en una sola observacion, y lo
unico que existia para evitarlo (`cognia/compresion_salidas.comprimir`) RECORTA:
lo tirado no vuelve nunca y el agente que necesitaba la linea 4000 se estanca
repitiendo la misma llamada. Estos tests fijan el contrato de
`cognia/harness/offloading.py`: por debajo del umbral el contenido pasa INTACTO,
por encima al modelo le llega un resumen con handle y el contenido COMPLETO se
puede recuperar byte a byte (compresion restaurable, no truncado).

Sin el modulo, el fichero entero falla en el import.

Todo corre contra DISCO REAL (tmp_path): sin mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognia.harness import offloading as off


@pytest.fixture(autouse=True)
def almacen_aislado(tmp_path, monkeypatch):
    """El almacen NUNCA es el ~/.cognia real y cada test tiene su sesion."""
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "offload"))
    for var in ("COGNIA_TOOL_RESULT_MAX", "COGNIA_OFFLOAD",
                "COGNIA_OFFLOAD_CABEZA", "COGNIA_OFFLOAD_COLA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(off, "_AVISADOR", None)
    off._ULTIMO_SPILL.clear()
    off._ULTIMO_ERROR.clear()
    off.nueva_sesion()


def _texto_largo(n: int = 4000) -> str:
    """Algo con forma de salida real: numerado, para poder verificar rangos."""
    return "\n".join(f"linea {i:05d} contenido de la salida" for i in range(1, n + 1))


# ── Lo corto no se toca ───────────────────────────────────────────────────────

def test_lo_corto_pasa_intacto_y_no_toca_disco(tmp_path):
    """El 90% de las observaciones son 'OK': tienen que seguir siendo 'OK'."""
    corto = "OK (3 ficheros)\n  a.py\n  b.py\n"
    assert off.formatear_observacion(corto, "listar", ".") == corto
    # Ni cabecera, ni handle, ni un solo byte en disco.
    assert off.listar() == []
    assert list((tmp_path / "offload").rglob("*.txt")) == []


def test_resumir_no_toca_lo_que_cabe_bajo_el_umbral():
    justo = "x" * (off.umbral_bytes() - 1)
    assert off.resumir_para_modelo(justo, "leer_archivo", "res:abc123") == justo


def test_el_umbral_sale_del_env(monkeypatch):
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "120")
    assert off.umbral_bytes() == 120
    texto = "\n".join(f"linea {i}" for i in range(1, 60))     # ~500 B
    salida = off.formatear_observacion(texto, "ejecutar", "pytest")
    assert "SALIDA GRANDE" in salida and "res:" in salida
    # Y un valor basura o <= 0 no convierte cada 'OK' en un round-trip a disco.
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "0")
    assert off.umbral_bytes() == off.UMBRAL_BYTES
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "ocho mil")
    assert off.umbral_bytes() == off.UMBRAL_BYTES


# ── Lo grande: resumen + handle ───────────────────────────────────────────────

def test_lo_grande_no_entra_al_historial():
    crudo = _texto_largo()
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    assert len(salida.encode("utf-8")) < len(crudo.encode("utf-8")) / 20
    # El presupuesto es el umbral + el andamiaje declarado (~1.2 KB: la
    # referencia lleva handle, ruta real del fichero y bytes exactos).
    assert len(salida.encode("utf-8")) <= off.umbral_bytes() + 1200


def test_el_resumen_lleva_principio_y_final():
    crudo = _texto_largo()
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    assert "linea 00001 " in salida          # el principio
    assert "linea 00015 " in salida          # las 15 primeras
    assert "linea 04000 " in salida          # y el FINAL, que es la conclusion
    assert "linea 03996 " in salida          # las 5 ultimas
    assert "linea 02000 " not in salida      # el medio no


def test_la_cuenta_de_omitidos_es_honesta():
    crudo = _texto_largo(4000)
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    assert "4000 lineas" in salida
    assert "faltan 3980 lineas" in salida    # 4000 - (15 cabeza + 5 cola)


def test_el_resumen_dice_como_leer_mas():
    crudo = _texto_largo()
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]
    assert handle in salida
    assert f"recuperar {handle} lineas 16-75" in salida
    assert f"recuperar {handle} buscar=" in salida


def test_sin_handle_el_resumen_lo_dice_en_vez_de_mentir():
    salida = off.resumir_para_modelo(_texto_largo(), "leer_archivo", handle="")
    assert "NO esta disponible" in salida


# ── La informacion NO se pierde ───────────────────────────────────────────────

def test_recuperar_devuelve_exactamente_el_rango_pedido():
    crudo = _texto_largo()
    off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]

    trozo = off.recuperar(handle, desde=200, hasta=204)
    cuerpo = trozo.split("\n", 1)[1]
    assert cuerpo == "\n".join(f"linea {i:05d} contenido de la salida"
                               for i in range(200, 205))
    assert "lineas 200-204 de 4000" in trozo.splitlines()[0]


def test_el_contenido_completo_se_reconstruye_byte_a_byte():
    """El corazon de 'compresion RESTAURABLE': nada se perdio."""
    crudo = _texto_largo(500)
    off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]
    entero = off.recuperar(handle, desde=1, hasta=500, max_bytes=10_000_000)
    assert entero.split("\n", 1)[1] == crudo


def test_round_trip_utf8_con_acentos_y_emoji():
    crudo = ("cabecera con nadie\n" + "ñ á é í ó ú ü ¿? 日本語 🚀\n" * 400)
    off.formatear_observacion(crudo, "leer_archivo", "acentos.txt")
    handle = off.listar()[0]["handle"]
    entero = off.recuperar(handle, desde=1, hasta=401, max_bytes=10_000_000)
    assert entero.split("\n", 1)[1] == crudo.rstrip("\n")


def test_round_trip_exacto_con_crlf_y_separadores_raros():
    """Regresion: `splitlines()` partia por '\\r', '\\f', '\\x85' y '\\u2028' y
    `recuperar` re-unia con '\\n'. Una salida CRLF (lo normal en Windows si el
    que la leyo no traduce) perdia UN BYTE POR LINEA en el round-trip, y un
    '\\f' dentro de un log sumaba una linea que despues no estaba en ese numero.
    El modulo escribe con newline='' justo para no mentir en los bytes."""
    crlf = "\r\n".join(f"linea {i:04d} del log" for i in range(1, 300))
    off.formatear_observacion(crlf, "ejecutar", "pytest -q")
    handle = off.listar()[0]["handle"]
    assert off.recuperar(handle, desde=1, hasta=299,
                         max_bytes=10_000_000).split("\n", 1)[1] == crlf

    for sep in ("\f", "\x85", " ", "\r", "\x0b"):
        crudo = ("A" * 1500) + sep + ("B" * 1500)
        h = off.guardar(crudo, "leer_archivo", "raro.txt")
        assert off.recuperar(h, desde=1, hasta=9, max_bytes=10_000_000
                             ).split("\n", 1)[1] == crudo, repr(sep)
        # Y el conteo que se le promete al modelo es UNA linea, no dos.
        assert "de 1]" in off.recuperar(h, desde=1, hasta=1).splitlines()[0]


def test_surrogates_sueltos_no_matan_la_observacion():
    """Un str con surrogates (errors='surrogateescape' en subprocess/os) hacia
    lanzar UnicodeEncodeError DENTRO del formateador de observaciones: no se
    degradaba el offloading, se perdia el turno entero."""
    veneno = "salida rara " + "\udcff" * 3000
    salida = off.formatear_observacion(veneno, "ejecutar", "cmd /c dir")
    assert "SALIDA GRANDE" in salida
    handle = off.listar()[0]["handle"]
    assert off.recuperar(handle, desde=1, hasta=1).startswith("[" + handle)
    # Y lo corto con surrogates tambien pasa, saneado y sin excepcion.
    assert off.formatear_observacion("ok \udcff", "ejecutar", "x")


def test_el_resumen_respeta_el_presupuesto_aunque_sea_multibyte():
    """El tope por linea era de 300 CHARS: 300 emoji son 1200 bytes y el
    resumen se iba a 2966 B con umbral 2000 (el modulo promete umbral+~0.5 KB).
    """
    emoji = "\n".join("\U0001F680" * 400 for _ in range(40))
    salida = off.formatear_observacion(emoji, "leer_archivo", "emoji.txt")
    assert len(salida.encode("utf-8")) <= off.umbral_bytes() + 1200
    assert "chars en esta linea" in salida


def test_una_salida_vacia_no_pide_un_rango_imposible():
    """Devolvia 'pedi un rango dentro de 1-0', que no se puede cumplir."""
    handle = off.guardar("", "ejecutar", "comando sin salida")
    res = off.recuperar(handle)
    assert "VACIA" in res and "1-0" not in res


def test_buscar_devuelve_la_linea_con_contexto_y_numero():
    lineas = [f"linea {i:05d}" for i in range(1, 400)]
    lineas[249] = "ERROR: connection timeout en el worker 7"
    crudo = "\n".join(lineas)
    off.formatear_observacion(crudo, "ejecutar", "pytest -q")
    handle = off.listar()[0]["handle"]

    res = off.recuperar(handle, buscar="TIMEOUT")     # sin distinguir mayusculas
    assert "connection timeout" in res
    assert "1 lineas casan" in res
    assert "> 250:" in res                            # el numero para pedir rango
    assert "248:" in res and "252:" in res            # +-2 de contexto
    assert "247:" not in res


def test_buscar_sin_aciertos_no_miente():
    off.formatear_observacion(_texto_largo(), "ejecutar", "pytest")
    handle = off.listar()[0]["handle"]
    res = off.recuperar(handle, buscar="zzz-no-esta-zzz")
    assert "0 lineas casan" in res
    assert "No esta" in res


def test_recuperar_tiene_tope_de_bytes():
    off.formatear_observacion(_texto_largo(), "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]
    res = off.recuperar(handle, desde=1, hasta=4000, max_bytes=500)
    assert "recortado a 500 bytes" in res
    assert len(res.encode("utf-8")) < 500 + 300      # cabecera aparte
    # El corte es por LINEA ENTERA: media linea se lee como un dato, no como
    # un corte (el buscar dejaba colgado un '  2' al final).
    assert res.splitlines()[-1].endswith("contenido de la salida")


def test_una_sola_linea_gigante_no_revienta_el_resumen():
    """400 KB minificados en UNA linea: 'resumir por lineas' no aplica, pero el
    resumen tiene que seguir siendo chico y decir cuanto falta."""
    crudo = "a" * 400_000
    salida = off.formatear_observacion(crudo, "leer_archivo", "bundle.min.js")
    assert len(salida.encode("utf-8")) <= off.umbral_bytes() + 1200
    assert "chars en esta linea" in salida            # la marca de corte
    assert "390.6 KB" in salida
    handle = off.listar()[0]["handle"]
    assert off.recuperar(handle, desde=1, hasta=1, max_bytes=10_000_000
                         ).split("\n", 1)[1] == crudo


# ── Errores: texto para el modelo, nunca una excepcion ────────────────────────

def test_handle_inexistente_devuelve_error_y_no_lanza():
    res = off.recuperar("res:aaaaaa")
    assert res.startswith("ERROR:")
    assert "no existe" in res


def test_handle_invalido_no_construye_rutas(tmp_path):
    """El handle lo escribe el MODELO: es texto no confiable."""
    off.formatear_observacion(_texto_largo(50), "leer_archivo", "x.log")
    antes = sorted(p.name for p in (tmp_path / "offload").rglob("*"))
    for veneno in ("../../../etc/passwd", "res:../../x", "C:/Windows/win.ini",
                   r"res:..\..\x", "res:zzzz", "res:aaaaaa/../../x", ""):
        res = off.recuperar(veneno)
        assert res.startswith("ERROR:"), veneno
        assert "no es un handle valido" in res or "no existe" in res
    # Y ni la lectura fallida ni el error tocaron el almacen.
    assert sorted(p.name for p in (tmp_path / "offload").rglob("*")) == antes


def test_rango_invertido_y_fuera_de_rango_se_explican():
    off.formatear_observacion(_texto_largo(100), "leer_archivo", "x.log")
    handle = off.listar()[0]["handle"]
    assert "rango invertido" in off.recuperar(handle, desde=50, hasta=10)
    fuera = off.recuperar(handle, desde=900, hasta=950)
    assert fuera.startswith("ERROR:") and "100 lineas" in fuera


def test_el_error_lista_los_handles_vivos():
    off.formatear_observacion(_texto_largo(), "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]
    assert handle in off.recuperar("res:000000")


# ── Almacen: dedup, atomicidad, inventario, poda ──────────────────────────────

def test_mismo_contenido_mismo_handle_y_un_solo_fichero(tmp_path):
    crudo = _texto_largo()
    h1 = off.guardar(crudo, "leer_archivo", "gigante.log")
    h2 = off.guardar(crudo, "leer_archivo", "gigante.log")
    assert h1 == h2
    assert h1.startswith("res:") and len(h1) == 10          # "res:" + 6 hex
    assert len(list((tmp_path / "offload").rglob("*.txt"))) == 1
    # Contenido distinto = handle distinto.
    assert off.guardar(crudo + "x", "leer_archivo", "gigante.log") != h1


def test_no_quedan_temporales_de_la_escritura_atomica(tmp_path):
    off.guardar(_texto_largo(), "leer_archivo", "gigante.log")
    assert [p.name for p in (tmp_path / "offload").rglob("*.tmp*")] == []


def test_listar_da_tool_tamano_y_edad():
    off.formatear_observacion(_texto_largo(300), "ejecutar", "pytest -q")
    vivos = off.listar()
    assert len(vivos) == 1
    e = vivos[0]
    assert e["tool"] == "ejecutar"
    assert e["lineas"] == 300
    assert e["bytes"] > 5000
    assert e["edad_s"] >= 0
    assert Path(e["ruta"]).exists()
    assert e["handle"] in off.resumen_listado()


def test_un_handle_de_sesion_anterior_sigue_resolviendo():
    handle = off.guardar(_texto_largo(50), "leer_archivo", "viejo.log")
    off.nueva_sesion()
    assert off.listar() == []                     # la sesion nueva esta limpia
    assert "linea 00003" in off.recuperar(handle, desde=1, hasta=5)


def test_podar_borra_sesiones_viejas_y_nunca_la_actual():
    viejas = []
    for i in range(3):
        off.guardar(f"contenido {i}\n" * 100, "leer_archivo", f"f{i}.log")
        viejas.append(off.sesion_actual())
        off.nueva_sesion()
    actual = off.sesion_actual()
    off.guardar("de la sesion en curso\n" * 100, "leer_archivo", "curso.log")

    res = off.podar(max_sesiones=1, max_mb=200)
    assert set(res["sesiones_borradas"]) == set(viejas)
    assert actual not in res["sesiones_borradas"]
    assert res["bytes_liberados"] > 0
    assert off.listar()                            # lo de la sesion en curso vive


def test_podar_por_tamano_declara_el_exceso_en_vez_de_borrar_lo_vivo():
    off.guardar("vieja\n" * 100, "leer_archivo", "vieja.log")
    vieja = off.sesion_actual()
    off.nueva_sesion()
    off.guardar("en curso\n" * 100, "leer_archivo", "curso.log")

    res = off.podar(max_sesiones=20, max_mb=0)
    assert vieja in res["sesiones_borradas"]
    assert res["excedido"] is True                 # honesto: no borro lo vivo
    assert off.listar()


# ── El adaptador de tool (lo que el integrador registra) ──────────────────────

def test_la_tool_parsea_lo_que_escribe_el_modelo():
    off.formatear_observacion(_texto_largo(), "leer_archivo", "gigante.log")
    h = off.listar()[0]["handle"]
    for args in (f"{h} | 200-204", f"{h} lineas 200-204", f"{h} lineas=200-204"):
        res = off.herramienta_recuperar(args)
        assert "lineas 200-204 de 4000" in res.splitlines()[0], args
        assert "linea 00202" in res
    # Sin rango: las primeras 60 lineas, no un error.
    assert "lineas 1-60" in off.herramienta_recuperar(h)
    # Y el prefijo comido / las comillas del modelo se perdonan.
    assert "lineas 1-60" in off.herramienta_recuperar(f"'{h[4:]}'")
    assert "linea 00250" in off.herramienta_recuperar(f"{h} buscar=linea 00250")


def test_la_tool_perdona_el_nombre_repetido_y_el_rango_partido():
    """Dos formas que el modelo escribe y que fallaban: repetir el nombre de la
    tool delante del handle (daba \"'recuperar' no es un handle valido\" con el
    handle ahi al lado) y el rango con espacio, que el split partia en dos y
    servia 200-259 en vez de 200-260 SIN decirlo."""
    off.formatear_observacion(_texto_largo(), "leer_archivo", "gigante.log")
    h = off.listar()[0]["handle"]
    assert "lineas 1-5 de 4000" in off.herramienta_recuperar(
        f"recuperar {h} lineas 1-5").splitlines()[0]
    assert "lineas 200-260 de 4000" in off.herramienta_recuperar(
        f"{h} 200 260").splitlines()[0]


def test_la_tool_esta_documentada_para_el_registro_nativo():
    """Sin desc/params no se puede registrar en el tool-calling nativo."""
    assert "res:3f2a1b" in off.DESC_RECUPERAR
    nombres = [p["nombre"] for p in off.PARAMS_RECUPERAR]
    assert nombres == ["handle", "lineas", "buscar"]
    assert off.PARAMS_RECUPERAR[0]["requerido"] is True
    assert all(p["descripcion"] for p in off.PARAMS_RECUPERAR)
    assert "recuperar" in off.recuperar.__doc__


# ── F3: contrato deepseek-harness completo (2026-08-23) ───────────────────────

def test_la_referencia_lleva_ruta_bytes_exactos_y_tools_reales():
    """El contrato dsh: la referencia dice DONDE esta el fichero, CUANTO pesa
    (bytes exactos, no '117.2 KB') y COMO recuperarlo con tools que existen de
    verdad en agent/tools.py (recuperar, leer_archivo, buscar)."""
    crudo = _texto_largo()
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    handle = off.listar()[0]["handle"]
    ruta = off.ruta_de(handle)
    assert ruta and Path(ruta).is_file()
    assert ruta in salida                                     # la ruta real
    assert f"{len(crudo.encode('utf-8'))} bytes exactos" in salida
    assert f"leer_archivo {ruta} offset=16" in salida         # tool real
    assert f"buscar <texto> | {ruta}" in salida               # tool real
    # Y la ruta que publica la referencia contiene el original byte a byte.
    with open(ruta, encoding="utf-8", newline="") as fh:
        assert fh.read() == crudo


def test_fallo_de_escritura_conserva_inline_cabeza_y_cola_y_avisa(monkeypatch):
    """Regla de resiliencia dsh: un fallo de ALMACENAMIENTO jamas convierte una
    llamada exitosa en error. Si el disco falla: (a) no se lanza, (b) el modelo
    conserva el resultado inline truncado al umbral — y con cabeza Y cola,
    porque el truncado clasico solo conserva cabeza y ese es el bug de clase
    que esto mata — y (c) el fallo se AVISA (nada de vacio silencioso)."""
    avisos = []
    off.registrar_avisador(lambda origen, motivo: avisos.append((origen, motivo)))
    monkeypatch.setattr(off, "_escribir_atomico",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError("disco lleno")))
    crudo = _texto_largo(4000)
    salida = off.formatear_observacion(crudo, "leer_archivo", "gigante.log")
    # (b) inline conservado: cabeza Y cola, dentro del presupuesto.
    assert "linea 00001 " in salida and "linea 04000 " in salida
    assert len(salida.encode("utf-8")) <= off.umbral_bytes() + 1200
    assert "NO esta disponible" in salida        # honesto: no hay handle
    assert "res:" not in salida                  # ni un handle inventado
    # (c) el fallo se ve: avisador del CLI + telemetria para /offload.
    assert avisos and avisos[0][0] == "offloading"
    assert "OSError" in avisos[0][1] and "disco lleno" in avisos[0][1]
    assert "disco lleno" in off.estado()["ultimo_error"]["motivo"]
    # Y un avisador ROTO tampoco mata la observacion (el aviso no puede
    # romper el camino que esta avisando).
    off.registrar_avisador(lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert "linea 00001 " in off.formatear_observacion(
        crudo + "y", "leer_archivo", "g2.log")


def test_el_nombre_del_spill_es_un_solo_segmento():
    """El nombre en disco JAMAS puede salirse del directorio de su sesion:
    cualquier separador o char raro se sanea a '_' (ultima linea de defensa;
    los handles validos ya son hex)."""
    for veneno in ("res:abc123", "res:../../etc", r"a/b\c:d", r"..\..\x",
                   "res:aaa/../bbb"):
        ruta = off._ruta_txt("ses", veneno)
        assert ruta.parent.name == "ses", veneno
        assert "/" not in ruta.name and "\\" not in ruta.name, veneno
        assert ":" not in ruta.name, veneno       # ADS de NTFS


def test_el_preview_se_configura_por_entorno(monkeypatch):
    """N/M de preview persisten en la config del CLI y llegan aca por env
    (COGNIA_OFFLOAD_CABEZA/COLA, propagadas por _aplicar_config_offload)."""
    monkeypatch.setenv("COGNIA_OFFLOAD_CABEZA", "3")
    monkeypatch.setenv("COGNIA_OFFLOAD_COLA", "2")
    salida = off.formatear_observacion(_texto_largo(), "leer_archivo", "g.log")
    assert "primeras 3 lineas" in salida and "ultimas 2 lineas" in salida
    assert "linea 00003 " in salida and "linea 00004 " not in salida
    assert "linea 03999 " in salida and "linea 03998 " not in salida
    # Basura o negativo caen al defecto en vez de reventar el formateador.
    monkeypatch.setenv("COGNIA_OFFLOAD_CABEZA", "basura")
    monkeypatch.setenv("COGNIA_OFFLOAD_COLA", "-1")
    assert off.cabeza_defecto() == off.CABEZA_DEFECTO
    assert off.cola_defecto() == off.COLA_DEFECTO


def test_activo_es_el_env_y_el_env_lo_pone_el_cli(monkeypatch):
    """El lector del flag es el ENV (COGNIA_OFFLOAD); el default 'on' del
    producto lo propaga el CLI al arrancar (_aplicar_config_offload). Leer
    aca la config real contaminaria cualquier proceso con la config del
    dueno de la maquina — por eso sin env es APAGADO."""
    monkeypatch.delenv("COGNIA_OFFLOAD", raising=False)
    assert off.activo() is False
    monkeypatch.setenv("COGNIA_OFFLOAD", "1")
    assert off.activo() is True
    monkeypatch.setenv("COGNIA_OFFLOAD", "0")
    assert off.activo() is False
    monkeypatch.setenv("COGNIA_OFFLOAD", "on")
    assert off.activo() is True


def test_estado_publica_dir_umbral_y_ultimo_spill():
    est = off.estado()
    assert est["handles"] == 0 and est["ultimo_spill"] == {}
    off.formatear_observacion(_texto_largo(300), "ejecutar", "pytest -q")
    est = off.estado()
    assert est["umbral"] == off.umbral_bytes()
    assert est["handles"] == 1 and est["bytes_sesion"] > 5000
    assert est["ultimo_spill"]["tool"] == "ejecutar"
    assert est["ultimo_spill"]["bytes"] == est["bytes_sesion"]
    assert Path(est["ultimo_spill"]["ruta"]).is_file()
    assert est["ultimo_error"] == {}


# ── Regresion 2026-08-23 (revision adversarial): el spill del spill ──────────

def test_recuperar_no_se_re_offloadea_por_el_interceptor(monkeypatch):
    """`recuperar` es LA via de recuperacion del offload: si el interceptor
    la vuelve a offloadear, cada intento acuna un handle anidado y el modelo
    nunca ve el trozo que pidio (el contrato RESTAURABLE queda irrestaurable).
    Reproducia el bucle: leer_archivo grande -> spill -> recuperar -> OTRO
    spill con handle nuevo."""
    from cognia.harness import interceptor
    monkeypatch.setenv("COGNIA_OFFLOAD", "1")
    grande = _texto_largo(300)
    resumen = interceptor.despues("leer_archivo", "f.txt", {}, grande, True)
    assert resumen.startswith("[SALIDA GRANDE")
    import re
    handle = re.search(r"res:[0-9a-f]{6,40}", resumen).group(0)
    trozo = off.recuperar(handle, desde=16, hasta=160)      # ~5 KB, > umbral
    final = interceptor.despues("recuperar", f"{handle} lineas 16-160",
                                {}, trozo, True)
    assert not final.startswith("[SALIDA GRANDE")
    assert final == trozo                       # byte a byte, sin recorte
    assert "linea 00100" in final               # el medio del rango pedido


def test_recuperar_esta_exenta_del_aci_trim():
    """La otra mitad del mismo bug: sin la exencion en ACI_EXENTAS, aci_trim
    le comia el MEDIO al trozo recuperado (hasta 4x umbral por diseno) y el
    modelo editaba con SEARCH/REPLACE texto que jamas vio."""
    from cognia.agent.tools import ACI_EXENTAS
    assert "recuperar" in ACI_EXENTAS
    assert "recuperar" in off.EXENTAS_OFFLOAD


def test_la_cabecera_del_spill_propaga_el_marcador_de_fallo():
    """Una tool FALLIDA cuyo output grande se spillea NO puede clasificarse
    como exito: los clasificadores de rio abajo (cli legacy result[:120],
    especulacion de loop.py, _linea_tool de compactacion) leen \bERROR\b en
    la primera linea, y la cabecera '[SALIDA GRANDE...' lo enterraba."""
    fallo = ("RESULTADO ejecutar ERROR (exit 1): Traceback...\n"
             + "\n".join(f"  traza {i}" for i in range(300)))
    salida = off.formatear_observacion(fallo, "ejecutar", "python x.py")
    import re
    assert salida.startswith("[SALIDA GRANDE")
    assert re.search(r"\bERROR\b", salida[:120])
    # Y el (exit N) sin la palabra ERROR tambien es fallo.
    solo_exit = ("RESULTADO ejecutar (exit 2): boom\n"
                 + "\n".join(f"  linea {i}" for i in range(300)))
    assert re.search(r"\bERROR\b",
                     off.formatear_observacion(solo_exit, "ejecutar", "x")[:120])
    # Un exito grande NO gana el marcador (exit 0 no es fallo).
    exito = ("RESULTADO ejecutar (exit 0): ok\n"
             + "\n".join(f"  linea {i}" for i in range(300)))
    assert not re.search(r"\bERROR\b",
                         off.formatear_observacion(exito, "ejecutar", "x")[:120])
    assert off.es_fallo_primera_linea("RESULTADO ejecutar (exit 0): ok") is False
    assert off.es_fallo_primera_linea("RESULTADO x ERROR: y") is True
