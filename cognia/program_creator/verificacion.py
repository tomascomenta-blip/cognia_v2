# -*- coding: utf-8 -*-
"""
verificacion.py — CIERRA EL LAZO generar -> probar -> puntuar del creador de programas.

POR QUE EXISTE (medido hoy con scripts/e2e_autoprueba.py sobre la biblioteca real):
de 56 productos generados, 44 compilan y solo 36 arrancan, con una media de
6.71/10. El peor caso es cognia_game, cuyo main.py es literalmente
print("hello") al lado de un game.py de verdad, y que sin embargo esta
archivado con un total_score que puso un juez LLM. O sea: el creador genera,
un modelo OPINA, y nadie comprueba nunca que el producto corra.

Este modulo es la pieza que faltaba: agarra UN producto recien generado, le
corre la bateria real de cognia.autoprueba (compila -> importa -> arranca ->
sin_stubs, todo en subproceso con timeout), y devuelve tres cosas:

  1. verificar_al_crear(dir)  — el veredicto medido: {ok, puntaje, desglose, motivos, fallo_duro}
  2. reintentar_si_falla(dir) — si no arranca o esta hueco, el PEDIDO DE CORRECCION
                                (que archivo, que error exacto, que se espera) listo
                                para mandarselo al generador. Aca NO se llama al LLM:
                                el que reintenta es program_creator.py (ver 'enganche').
  3. sello_de_calidad(...)    — el .verificacion.json que queda JUNTO al producto, para
                                que la biblioteca diga si CORRE de verdad y no solo lo
                                que opino el juez.

Y sellar_biblioteca() para pasar por lo ya archivado y dejarle su sello.

CRITERIO DE 'verificado' (explicito, nada de numero magico):
  verificado = no hay fallo duro (compila/importa/arranca)  Y  no hay stub DURO.
Stub duro = archivos sin cuerpo (<5 lineas utiles) o mas del 40% de funciones
huecas. Se usa ese corte y no el estricto de autoprueba (que reprueba con UN
solo TODO) porque un TODO suelto no justifica mandar a regenerar el producto:
es el mismo escalon con el que evaluar_producto() ya da 0 en sin_stubs.
El caso cognia_game cae por aca: arranca con exit 0 y aun asi NO se verifica,
porque su main.py tiene 1 linea util.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from ..autoprueba import (
    DIR_PRODUCTOS,
    TIMEOUT_ARRANQUE_SEG,
    TIMEOUT_IMPORT_SEG,
    descubrir_productos,
    evaluar_producto,
    probar_producto,
)

# El sello vive DENTRO de la carpeta del producto: si alguien copia o mueve el
# producto, su veredicto viaja con el. El index es solo un reflejo.
NOMBRE_SELLO = ".verificacion.json"

# Un producto con mas del 40% de funciones huecas, o con algun archivo sin
# cuerpo, es un cascaron. Mismo escalon que usa evaluar_producto() para dar 0.
MAX_RATIO_HUECAS = 0.4

# Cuantas lineas de stderr real se le citan al generador en el pedido. Con una
# sola linea el modelo no ve el archivo:linea del traceback (medido el
# 2026-07-19 en el camino web: con solo el sintoma parcheo el sitio equivocado).
LINEAS_ERROR_EN_PEDIDO = 8


# ── Descubrir UN producto ──────────────────────────────────────────────────────

def _producto_de(directorio_producto):
    """
    Arma el dict de producto de UNA carpeta, con el mismo formato exacto que
    devuelve descubrir_productos() (probar_producto() espera esas claves).

    Se apoya en descubrir_productos(base=carpeta_padre) en vez de duplicar la
    eleccion de entrypoint: asi la regla de "quien es el main" es UNA sola en
    todo el repo, y de paso se hereda la metadata del index.json si el producto
    ya esta archivado.
    """
    carpeta = Path(directorio_producto).resolve()
    if not carpeta.is_dir():
        return None
    for prod in descubrir_productos(carpeta.parent):
        if Path(prod["directorio"]).resolve() == carpeta:
            return prod
    return None


# ── 1. Veredicto medido ────────────────────────────────────────────────────────

def _stub_duro(fase_stub):
    """
    (bool, motivos) — si el producto esta HUECO al punto de tener que regenerarlo.

    Distinto del sin_stubs["ok"] de autoprueba, que es estricto a proposito
    (un TODO ya lo reprueba). Aca se corta solo con cascarones.
    """
    if not isinstance(fase_stub, dict) or fase_stub.get("ok") is None:
        return False, []
    motivos = []
    vacios = fase_stub.get("vacios") or []
    if vacios:
        motivos.append("archivos sin cuerpo: " + ", ".join(str(v) for v in vacios[:3]))
    ratio = fase_stub.get("ratio_huecas") or 0.0
    huecas = fase_stub.get("funciones_huecas") or []
    if ratio > MAX_RATIO_HUECAS and huecas:
        motivos.append(f"{len(huecas)}/{fase_stub.get('funciones', 0)} funciones vacias "
                       f"({', '.join(huecas[:3])})")
    return bool(motivos), motivos


def verificar_al_crear(directorio_producto,
                       timeout_arranque=TIMEOUT_ARRANQUE_SEG,
                       timeout_import=TIMEOUT_IMPORT_SEG):
    """
    Corre la bateria real de cognia.autoprueba sobre UN producto recien generado.

    Devuelve {ok, puntaje, desglose, motivos, fallo_duro, ...}. `ok` es el
    veredicto duro (corre y no es un cascaron); `puntaje` es la nota 0-10 medida,
    NO la del juez LLM. Nunca lanza: un producto que no se puede ni descubrir
    devuelve ok=False con fallo_duro="sin_producto".
    """
    carpeta = Path(directorio_producto)
    prod = _producto_de(carpeta)
    if prod is None:
        return {
            "ok": False, "puntaje": 0.0, "desglose": {}, "fallo_duro": "sin_producto",
            "motivos": [f"no existe o no es una carpeta de producto: {carpeta}"],
            "id": carpeta.name, "directorio": str(carpeta), "entrypoint": None,
            "lenguaje": "vacio", "stub_duro": False, "resultado": None, "producto": None,
        }

    resultado = probar_producto(prod, timeout_arranque=timeout_arranque,
                                timeout_import=timeout_import)
    ev = evaluar_producto(prod, resultado)
    hueco, motivos_stub = _stub_duro(resultado["fases"].get("sin_stubs", {}))

    return {
        "ok": resultado["fallo_duro"] is None and not hueco,
        "puntaje": ev["puntaje"],
        "desglose": ev["desglose"],
        "motivos": list(ev["motivos"]) + [f"stub duro: {m}" for m in motivos_stub],
        "fallo_duro": resultado["fallo_duro"] or ("stubs" if hueco else None),
        "stub_duro": hueco,
        "id": prod["id"],
        "title": prod["title"],
        "lenguaje": prod["lenguaje"],
        "directorio": prod["directorio"],
        "entrypoint": prod["entrypoint"],
        "score_index": prod.get("score_index"),
        "producto": prod,
        "resultado": resultado,
    }


# ── 2. Pedido de correccion ────────────────────────────────────────────────────

def _ultimas_lineas(texto, n=LINEAS_ERROR_EN_PEDIDO):
    """Las ultimas n lineas no vacias de un stderr (donde vive el traceback util)."""
    lineas = [l.rstrip() for l in (texto or "").splitlines() if l.strip()]
    return "\n".join(lineas[-n:])


def _archivo_y_error(ver):
    """
    (archivo, error_exacto, que_se_espera) del fallo concreto.

    El pedido tiene que NOMBRAR el archivo y pegar el error literal: un pedido
    del estilo "el programa falla, arreglalo" es exactamente lo que produce el
    parcheo a ciegas que la regla 11 del repo prohibe.
    """
    fases = (ver.get("resultado") or {}).get("fases", {})
    entry = Path(ver["entrypoint"]).name if ver.get("entrypoint") else "(sin entrypoint)"
    fallo = ver.get("fallo_duro")
    # 21 de los 56 productos son paginas. Pedirle a un index.html que "corra sin
    # Traceback" (lo que salia en la primera corrida real sobre
    # dashboard_de_inversiones) es un pedido sin sentido: al generador hay que
    # hablarle en el criterio con el que se lo mide, que es revisar_html().
    es_web = ver.get("lenguaje") == "html"

    if fallo == "sin_codigo" or fallo == "sin_producto":
        return ("main.py",
                "la carpeta del producto no contiene ningun archivo .py ni .html",
                "entregar el programa completo en un unico archivo main.py que se "
                "pueda ejecutar con `python main.py`")

    if fallo == "compila":
        errores = fases.get("compila", {}).get("errores") or []
        primero = errores[0] if errores else fases.get("compila", {}).get("detalle", "")
        archivo = (entry if es_web else (primero.split(":")[0].strip() or entry))
        if es_web:
            espera = (f"que `{archivo}` sea un documento HTML completo: <html>, <head> "
                      "y <body> presentes y bien cerrados")
        else:
            espera = f"que `{archivo}` compile: ast.parse(...) sin SyntaxError"
        return (archivo, "\n".join(errores[:3]) or primero, espera)

    if fallo in ("importa", "arranca"):
        fase = fases.get(fallo, {})
        detalle = fase.get("detalle", "")
        stderr = _ultimas_lineas(fase.get("stderr", ""))
        error = (detalle + ("\n" + stderr if stderr else "")).strip()
        if fallo == "importa":
            espera = (f"que `{entry}` se pueda importar sin ejecutar nada peligroso: "
                      "poner el codigo de arranque bajo `if __name__ == \"__main__\":`")
        elif es_web:
            espera = (f"que `{entry}` pase revisar_html(): todo el CSS/JS/datos EMBEBIDOS "
                      "en el archivo (nada de http:// ni CDNs), sin errores de JS y con "
                      "el contenido renderizado")
        else:
            espera = (f"que `python {entry}` corra y termine sin Traceback "
                      "(si es interactivo puede quedarse esperando input(), eso cuenta "
                      "como arrancar bien)")
        return (entry, error, espera)

    if fallo == "stubs" or ver.get("stub_duro"):
        stub = fases.get("sin_stubs", {})
        vacios = stub.get("vacios") or []
        archivo = str(vacios[0]).split(" (")[0] if vacios else entry
        huecas = stub.get("funciones_huecas") or []
        error = stub.get("detalle", "el producto esta hueco")
        if huecas:
            error += " | funciones sin cuerpo: " + ", ".join(huecas[:6])
        if es_web:
            espera = (f"que `{archivo}` tenga la pagina DE VERDAD y no un esqueleto: "
                      "contenido, estilos y logica escritos (no un placeholder)")
        else:
            espera = (f"que `{archivo}` tenga el programa DE VERDAD, no un placeholder: "
                      "cada funcion con cuerpo real y el entrypoint ejecutando la logica "
                      "(nada de `print(\"hello\")`, `pass` ni `TODO`)")
        return (archivo, error, espera)

    return (entry, "sin fallo duro", "nada que corregir")


def reintentar_si_falla(directorio_producto, verificacion=None,
                        intento=1, max_intentos=3,
                        timeout_arranque=TIMEOUT_ARRANQUE_SEG):
    """
    Si el producto NO arranca o esta hueco, arma el PEDIDO DE CORRECCION.

    NO llama al LLM: devuelve el texto listo para que program_creator.py se lo
    mande al generador (ver 'enganche' al final del archivo). Asi el lazo queda
    donde ya viven las reparaciones (reparar_python/reparar_web) y este modulo
    sigue siendo puro y testeable sin modelo.

    Devuelve {necesita_reintento, pedido, archivo, error, que_se_espera,
              fallo_duro, intento, max_intentos, verificacion}.
    `verificacion` se puede pasar ya hecha para no volver a correr la bateria.
    """
    ver = verificacion or verificar_al_crear(directorio_producto,
                                             timeout_arranque=timeout_arranque)
    base = {
        "necesita_reintento": False, "pedido": "", "archivo": None, "error": "",
        "que_se_espera": "", "fallo_duro": ver.get("fallo_duro"),
        "intento": intento, "max_intentos": max_intentos, "verificacion": ver,
    }
    if ver.get("ok"):
        return base
    if intento > max_intentos:
        base["error"] = (f"agotados los {max_intentos} intentos de correccion "
                         f"(ultimo fallo: {ver.get('fallo_duro')})")
        return base

    archivo, error, espera = _archivo_y_error(ver)
    titulo = ver.get("title") or ver.get("id")
    pedido = "\n".join([
        f"PEDIDO DE CORRECCION (intento {intento}/{max_intentos}) — producto '{titulo}'",
        f"Carpeta : {ver.get('directorio')}",
        f"Archivo : {archivo}",
        f"Fase que fallo: {ver.get('fallo_duro')}"
        f"  (puntaje medido {ver.get('puntaje', 0.0)}/10)",
        "",
        "ERROR EXACTO (medido corriendolo, no es una opinion):",
        *[f"    {l}" for l in (error or "").splitlines()],
        "",
        f"QUE SE ESPERA: {espera}",
        "",
        "Devolve el archivo COMPLETO ya corregido, sin explicaciones ni markdown "
        "alrededor. No cambies el nombre del archivo ni el proposito del programa.",
    ])
    base.update(necesita_reintento=True, pedido=pedido, archivo=archivo,
                error=error, que_se_espera=espera)
    return base


# ── 3. Sello de calidad ────────────────────────────────────────────────────────

def sello_de_calidad(producto, resultado=None):
    """
    Arma el dict que se guarda como .verificacion.json junto al producto.

    Acepta las dos formas que hay dando vueltas en el repo:
      - sello_de_calidad(dir_o_prod, resultado_de_probar_producto)
      - sello_de_calidad(verificacion)   # lo que devuelve verificar_al_crear()
    porque probar_todos() ya tiene los resultados crudos y seria absurdo volver
    a correr los subprocesos solo para sellar.
    """
    # Caso 1: ya viene un veredicto de verificar_al_crear().
    if isinstance(producto, dict) and "ok" in producto and "desglose" in producto:
        ver = producto
    # Caso 2: prod + resultado crudo de probar_producto().
    elif isinstance(producto, dict) and "directorio" in producto and isinstance(resultado, dict) \
            and "fases" in resultado:
        ev = evaluar_producto(producto, resultado)
        hueco, motivos_stub = _stub_duro(resultado["fases"].get("sin_stubs", {}))
        ver = {
            "ok": resultado["fallo_duro"] is None and not hueco,
            "puntaje": ev["puntaje"], "desglose": ev["desglose"],
            "motivos": list(ev["motivos"]) + [f"stub duro: {m}" for m in motivos_stub],
            "fallo_duro": resultado["fallo_duro"] or ("stubs" if hueco else None),
            "stub_duro": hueco, "id": producto["id"], "title": producto["title"],
            "lenguaje": producto["lenguaje"], "directorio": producto["directorio"],
            "entrypoint": producto["entrypoint"],
            "score_index": producto.get("score_index"), "resultado": resultado,
        }
    # Caso 3: una ruta.
    else:
        ver = verificar_al_crear(producto)

    return {
        "verificado":    bool(ver.get("ok")),
        "puntaje_real":  ver.get("puntaje", 0.0),
        "fecha":         datetime.now().isoformat(timespec="seconds"),
        "motivos":       list(ver.get("motivos") or []),
        # Extras para poder auditar sin volver a correr nada.
        "id":            ver.get("id"),
        "title":         ver.get("title"),
        "lenguaje":      ver.get("lenguaje"),
        "entrypoint":    Path(ver["entrypoint"]).name if ver.get("entrypoint") else None,
        "fallo_duro":    ver.get("fallo_duro"),
        "desglose":      ver.get("desglose") or {},
        "score_juez":    ver.get("score_index"),   # lo que opino el juez LLM al guardarlo
        "verificador":   "cognia.autoprueba (compila/importa/arranca/sin_stubs)",
    }


def escribir_sello(directorio_producto, sello):
    """
    Deja el .verificacion.json en la carpeta del producto (escritura atomica).

    Idempotente: reescribe el archivo entero, no acumula. Best-effort: si la
    carpeta es de solo lectura devuelve None en vez de romper la generacion.
    """
    carpeta = Path(directorio_producto)
    destino = carpeta / NOMBRE_SELLO
    tmp = None
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(carpeta), prefix=".sello_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sello, f, ensure_ascii=False, indent=2)
        os.replace(tmp, destino)
        return str(destino)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)   # no dejar .sello_*.tmp sueltos en la biblioteca
            except Exception:
                pass
        return None


def leer_sello(directorio_producto):
    """El sello guardado, o None si el producto nunca se verifico."""
    ruta = Path(directorio_producto) / NOMBRE_SELLO
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None


def reflejar_en_index(sello, base=None):
    """
    Copia {verificado, puntaje_real, fecha} a la entrada del index.json.

    SOLO agrega claves: el total_score del juez no se toca (queda al lado del
    puntaje_real medido, que es justamente la comparacion interesante). Si el
    producto no esta en el index — medido: 13 carpetas reales no lo estan — no
    hace nada. Escritura atomica para no dejar el index a medio escribir.
    """
    base = Path(base) if base else DIR_PRODUCTOS
    ruta = base / "index.json"
    if not sello or not ruta.is_file():
        return False
    try:
        entradas = json.loads(ruta.read_text(encoding="utf-8"))
        if not isinstance(entradas, list):
            return False
    except Exception:
        return False

    clave = sello.get("id")
    tocadas = 0
    for e in entradas:
        if not isinstance(e, dict):
            continue
        if e.get("directory") == clave or e.get("id") == clave:
            e["verificado"]    = sello["verificado"]
            e["puntaje_real"]  = sello["puntaje_real"]
            e["verificado_en"] = sello["fecha"]
            tocadas += 1
    if not tocadas:
        return False
    try:
        fd, tmp = tempfile.mkstemp(dir=str(base), prefix=".index_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entradas, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta)
        return True
    except Exception:
        return False


# ── 4. Sellar lo ya archivado ──────────────────────────────────────────────────

def sellar_biblioteca(limite=None, base=None, filtro=None, solo_codigo=False,
                      tocar_index=True, timeout_arranque=TIMEOUT_ARRANQUE_SEG,
                      al_terminar_uno=None):
    """
    Pasa por los productos existentes y le deja a cada uno su .verificacion.json.

    Idempotente (reescribe el sello) y best-effort: un producto que revienta la
    verificacion no corta la pasada, se anota en 'errores'. NO borra nada — la
    limpieza de la biblioteca es de storage.auto_cleanup y no es asunto de esto.
    """
    productos = descubrir_productos(base)
    if solo_codigo:
        productos = [p for p in productos if p["lenguaje"] != "vacio"]
    if filtro:
        f = filtro.lower()
        productos = [p for p in productos
                     if f in p["id"].lower() or f in p["title"].lower()
                     or f in Path(p["directorio"]).name.lower()]
    if limite:
        productos = productos[:int(limite)]

    sellos, errores = [], []
    for prod in productos:
        try:
            resultado = probar_producto(prod, timeout_arranque=timeout_arranque)
            sello = sello_de_calidad(prod, resultado)
            ruta = escribir_sello(prod["directorio"], sello)
            sello["_archivo"] = ruta
            sello["_index"] = bool(tocar_index and reflejar_en_index(sello, base))
            sellos.append(sello)
            if al_terminar_uno:
                al_terminar_uno(sello)
        except Exception as exc:
            errores.append({"id": prod.get("id"), "error": f"{type(exc).__name__}: {exc}"})

    n = len(sellos)
    verificados = sum(1 for s in sellos if s["verificado"])
    return {
        "total": n,
        "verificados": verificados,
        "no_verificados": n - verificados,
        "escritos": sum(1 for s in sellos if s.get("_archivo")),
        "index_actualizado": sum(1 for s in sellos if s.get("_index")),
        "puntaje_medio": round(sum(s["puntaje_real"] for s in sellos) / n, 2) if n else 0.0,
        "errores": errores,
        "sellos": sellos,
    }


# ── Enganche (lo cablea el dueno en program_creator.py) ────────────────────────
#
# En run_program_hobby(), justo despues de `meta = save_program(...)`:
#
#     from .verificacion import verificar_al_crear, reintentar_si_falla, \
#         sello_de_calidad, escribir_sello, reflejar_en_index
#     dir_final = (storage_dir or DEFAULT_STORAGE_DIR) / meta.directory
#     ver = verificar_al_crear(dir_final)
#     escribir_sello(dir_final, sello_de_calidad(ver))
#     reflejar_en_index(sello_de_calidad(ver))
#     if not ver["ok"]:
#         pedido = reintentar_si_falla(dir_final, verificacion=ver)["pedido"]
#         # -> mandar `pedido` a reparar_python/reparar_web y reescribir el archivo
#
# Se deja fuera del flujo a proposito: meterlo aca significaria que este modulo
# llame al LLM, y el que sabe reparar (con disyuntor incluido) es program_creator.
