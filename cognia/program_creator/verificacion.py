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

import hashlib
import json
import os
import re
import tempfile
import time
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
from ..disciplina import DIR_ESTADO, Disyuntor, huella_de_texto

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


# ── 2b. EL LAZO probar -> reparar -> reprobar ──────────────────────────────────
#
# Esto es lo que faltaba: hasta el 2026-08-29 reintentar_si_falla() NO TENIA UN
# SOLO LLAMADOR en todo el repo (el cableado estaba escrito como COMENTARIO al
# final de este archivo y nunca se aplico), asi que la maquinaria entera existia
# desconectada y quedaban 24 productos con verificado=false intactos en disco
# desde julio. Aqui vive el lazo; program_creator le inyecta el reparador.

# TOPE 2 y no 3: el tercer intento del creador ya esta MEDIDO como parcheo a
# ciegas (por eso existe el Disyuntor y por eso el umbral de Aider es
# max_reflections=3 contando el intento original). Dos reparaciones y se para.
MAX_REPARACIONES_LAZO = 2

# Presupuesto total del lazo, en segundos. /crear ya es lento; un lazo que llama
# al modelo en el camino critico sin techo lo vuelve interminable.
PRESUPUESTO_LAZO_SEG = 120.0

# Un error es ACCIONABLE si nombra DONDE mirar. Sin esto, el pedido de
# correccion es "el programa falla, arreglalo", que es exactamente el parcheo a
# ciegas que la regla 11 del repo prohibe.
_RE_FICHERO_LINEA = re.compile(r'File "[^"]+", line \d+|^\S+\.py:\d+', re.MULTILINE)
_RE_ERROR_JS = re.compile(
    r"ReferenceError|TypeError|SyntaxError|RangeError|Uncaught|"
    r"is not defined|is not a function|Cannot read|Cannot set", re.IGNORECASE)


def error_accionable(ver):
    """
    (bool, motivo) — si el fallo de `ver` se puede mandar a reparar.

    Reglas, todas explicitas:
      - solo fallos DUROS de compila/importa/arranca. `stubs` NO: un producto
        hueco CORRE, y repararlo por eso significa llamar al modelo por
        productos que funcionan. `sin_codigo`/`sin_producto` tampoco: no hay
        archivo que corregir.
      - el error tiene que NOMBRAR un sitio: traceback con fichero+linea (o
        "archivo.py:12:" del ast.parse) para Python, un error de JS para web.
      - un INDETERMINADO (el guion de teclado se quedo corto) no es reparable:
        no hay nada medido que corregir.
    """
    # El indeterminado va PRIMERO: es el que dice "no sabemos", y saberlo cambia
    # que se hace despues. Si lo tapara un 'stubs' se mandaria a reparar (o a
    # regenerar) un producto del que ni siquiera se midio si arranca.
    if (ver.get("resultado") or {}).get("indeterminado"):
        return False, "indeterminado: no hay error medido que mandar a reparar"
    fallo = ver.get("fallo_duro")
    if fallo in (None, ""):
        return False, "no hay fallo duro"
    if fallo in ("stubs",):
        return False, "esta hueco pero CORRE: reparar por stubs llamaria al modelo por productos que funcionan"
    if fallo in ("sin_codigo", "sin_producto"):
        return False, f"{fallo}: no hay archivo que corregir"

    _archivo, error, _espera = _archivo_y_error(ver)
    if not (error or "").strip():
        return False, "el fallo no dejo ni una linea de error"
    if ver.get("lenguaje") == "html":
        if _RE_ERROR_JS.search(error):
            return True, "error de JavaScript con nombre"
        if fallo == "compila":
            return True, "documento HTML incompleto (se sabe que falta)"
        return False, "la pagina falla pero sin un error de JS que citar"
    if _RE_FICHERO_LINEA.search(error):
        return True, "traceback con fichero y linea"
    return False, "el error no nombra fichero ni linea: pedir una correccion seria adivinar"


def _ruta_del_archivo(directorio, nombre, ver):
    """La ruta REAL del archivo a reparar (o None). Nunca sale de la carpeta."""
    carpeta = Path(directorio).resolve()
    candidatos = []
    if nombre:
        candidatos.append(carpeta / Path(str(nombre)).name)
    if ver.get("entrypoint"):
        candidatos.append(Path(ver["entrypoint"]))
    for ruta in candidatos:
        try:
            ruta = Path(ruta).resolve()
        except Exception:
            continue
        if ruta.is_file() and carpeta in ruta.parents:
            return ruta
    return None


def lazo_reparacion(directorio_producto, reparar_fn, verificacion=None,
                    max_reparaciones=MAX_REPARACIONES_LAZO,
                    presupuesto_seg=PRESUPUESTO_LAZO_SEG,
                    timeout_arranque=TIMEOUT_ARRANQUE_SEG,
                    tocar_index=True, log=None):
    """
    verificar -> (si falla duro y es accionable) reparar -> reescribir -> RE-verificar.

    `reparar_fn(pedido=..., codigo=..., archivo=..., lenguaje=...) -> str | None`
    es el unico punto donde se habla con el modelo: se INYECTA para que este
    modulo siga siendo puro y testeable sin backend (los tests le pasan una
    funcion que devuelve codigo sano).

    Topes, todos duros: `max_reparaciones` vueltas, `presupuesto_seg` de reloj, y
    el Disyuntor del repo (si el sintoma no se mueve, corta antes).

    SEGURIDAD: si al terminar el producto sigue sin verificarse Y su puntaje NO
    SUBIO respecto al original (`<=`, no `<`), se restaura el archivo tal y como
    estaba. Una reparacion que empeora — o que empata — no se queda en disco:
    cambiar el fuente del dueno por una reescritura del modelo que no mejora
    nada es perder el original a cambio de nada.

    Devuelve {ok, intentos, error_inicial, error_final, motivo_corte,
              reparaciones:[...], verificacion, sello, restaurado}.
    Nunca lanza: un fallo del reparador se reporta en `motivo_corte`.
    """
    t0 = time.monotonic()
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    carpeta = Path(directorio_producto)
    ver = verificacion or verificar_al_crear(carpeta, timeout_arranque=timeout_arranque)
    puntaje_inicial = ver.get("puntaje", 0.0)
    error_inicial = "" if ver.get("ok") else (_archivo_y_error(ver)[1] or "")[:600]

    salida = {
        "ok": bool(ver.get("ok")), "intentos": 0,
        "error_inicial": error_inicial, "error_final": error_inicial,
        "motivo_corte": "", "reparaciones": [], "verificacion": ver,
        "sello": None, "restaurado": False, "directorio": str(carpeta),
    }

    if ver.get("ok"):
        salida["motivo_corte"] = "verificado a la primera: no hizo falta reparar"
        salida["sello"] = _sellar(carpeta, ver, salida, tocar_index)
        return salida

    accionable, motivo_acc = error_accionable(ver)
    if not accionable or reparar_fn is None:
        salida["motivo_corte"] = ("no se intento reparar: " + (
            motivo_acc if not accionable
            else "solo sello: esta via mide y sella, no repara (sin reparador inyectado)"))
        salida["sello"] = _sellar(carpeta, ver, salida, tocar_index)
        return salida

    tarea = f"autoprueba {carpeta.name}"[:60]
    ruta_log = DIR_ESTADO / f"lazo_{hashlib.sha1(tarea.encode('utf-8')).hexdigest()[:10]}.jsonl"
    disyuntor = Disyuntor(tarea, ruta_log=ruta_log)
    # El fallo ORIGINAL no es un parche: el modelo todavia no toco nada. Con
    # hubo_cambio=True gastaba una de las dos huellas que dispara D6 y el
    # disyuntor cortaba tras UNA sola reparacion (mismo bug que ya se corrigio
    # en program_creator.py).
    disyuntor.registrar(huella_de_texto(error_inicial), ok=False, hubo_cambio=False)

    respaldo = None       # (ruta, texto_original) para poder deshacer
    for intento in range(1, int(max_reparaciones) + 1):
        transcurrido = time.monotonic() - t0
        if transcurrido > presupuesto_seg:
            salida["motivo_corte"] = (f"presupuesto agotado ({transcurrido:.0f}s de "
                                      f"{presupuesto_seg:.0f}s) tras {intento - 1} reparaciones")
            break
        corte = disyuntor.motivo_corte()
        if corte:
            disyuntor.persistir_evento("disparo", motivo=corte, intento=len(disyuntor.intentos))
            salida["motivo_corte"] = f"Disyuntor ({corte}): dejo de parchear a ciegas"
            _log(f"   Disyuntor ({corte}): se corta el lazo de reparacion.")
            break

        pedido = reintentar_si_falla(carpeta, verificacion=ver, intento=intento,
                                     max_intentos=int(max_reparaciones))
        if not pedido.get("necesita_reintento"):
            salida["motivo_corte"] = pedido.get("error") or "no hay nada que reparar"
            break

        ruta = _ruta_del_archivo(carpeta, pedido.get("archivo"), ver)
        if ruta is None:
            salida["motivo_corte"] = (f"no encontre el archivo a reparar "
                                      f"({pedido.get('archivo')}) dentro de {carpeta.name}")
            break

        try:
            codigo = ruta.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            salida["motivo_corte"] = f"no pude leer {ruta.name}: {exc}"
            break
        _log(f"   Reparacion {intento}/{max_reparaciones} de '{carpeta.name}' "
             f"({ver.get('fallo_duro')} en {ruta.name})...")
        try:
            nuevo = reparar_fn(pedido=pedido["pedido"], codigo=codigo,
                               archivo=str(ruta), lenguaje=ver.get("lenguaje"))
        except Exception as exc:
            salida["motivo_corte"] = f"el reparador reviento: {type(exc).__name__}: {exc}"
            break
        if not nuevo or not str(nuevo).strip() or str(nuevo) == codigo:
            salida["motivo_corte"] = "el reparador no devolvio codigo nuevo"
            break

        try:
            ruta.write_text(str(nuevo), encoding="utf-8")
        except Exception as exc:
            salida["motivo_corte"] = f"no pude escribir {ruta.name}: {exc}"
            break
        # El respaldo se guarda DESPUES de escribir, no antes: si el reparador
        # revienta o no devuelve nada, el fichero sigue intacto y no hay nada
        # que restaurar. Guardarlo antes hacia que la restauracion de mas abajo
        # se disparara sin haber tocado el disco (y con `reparaciones` vacia).
        if respaldo is None:
            respaldo = (ruta, codigo)

        ver = verificar_al_crear(carpeta, timeout_arranque=timeout_arranque)
        salida["intentos"] = intento
        error_ahora = "" if ver.get("ok") else (_archivo_y_error(ver)[1] or "")[:600]
        salida["reparaciones"].append({
            "intento": intento, "archivo": ruta.name,
            "fallo_antes": pedido.get("fallo_duro"),
            "fallo_despues": ver.get("fallo_duro"),
            "puntaje_despues": ver.get("puntaje"),
            "ok": bool(ver.get("ok")),
        })
        disyuntor.registrar(huella_de_texto(error_ahora), ok=bool(ver.get("ok")))
        if ver.get("ok"):
            salida["motivo_corte"] = f"reparado al intento {intento}"
            _log(f"   Reparado al intento {intento}.")
            break
    else:
        salida["motivo_corte"] = f"agotadas las {max_reparaciones} reparaciones"

    salida["ok"] = bool(ver.get("ok"))
    salida["error_final"] = "" if ver.get("ok") else (_archivo_y_error(ver)[1] or "")[:600]

    # Una reparacion que no MEJORA no se queda en disco. El corte es <=, no <:
    # empatar no es empeorar, pero perder el fuente original a cambio de NADA
    # tampoco es lo que promete el docstring. Medido el 2026-08-29: un reparador
    # inutil dio 5.5 contra 5.5 inicial en sus dos intentos, no se restauraba, y
    # el dueno se quedaba con la reescritura del modelo en vez de su fichero.
    despues = (salida["reparaciones"][-1].get("puntaje_despues")
               if salida["reparaciones"] else None)
    if (not salida["ok"] and respaldo is not None
            and ver.get("puntaje", 0.0) <= puntaje_inicial):
        ruta, original = respaldo
        try:
            ruta.write_text(original, encoding="utf-8")
            ver = verificar_al_crear(carpeta, timeout_arranque=timeout_arranque)
            salida["restaurado"] = True
            movimiento = ("bajaba" if (despues is not None and despues < puntaje_inicial)
                          else "no subia")
            salida["motivo_corte"] += (f"; RESTAURADO {ruta.name}: la reparacion "
                                       f"{movimiento} el puntaje de {puntaje_inicial} "
                                       f"a {despues}")
            salida["error_final"] = (_archivo_y_error(ver)[1] or "")[:600]
        except Exception:
            pass

    salida["verificacion"] = ver
    salida["sello"] = _sellar(carpeta, ver, salida, tocar_index)
    return salida


def _sellar(carpeta, ver, salida, tocar_index):
    """
    Escribe el sello Y refleja en el index EN LA MISMA transaccion.

    El sello lleva la historia del lazo (intentos, error_inicial, error_final):
    un `verificado: false` sin decir cuantas veces se intento ni con que error
    es justo el sello rancio que dejo 24 productos sin explicacion desde julio.
    """
    try:
        sello = sello_de_calidad(ver)
        sello["intentos"] = salida.get("intentos", 0)
        sello["error_inicial"] = salida.get("error_inicial", "")
        sello["error_final"] = salida.get("error_final", "")
        sello["motivo_corte"] = salida.get("motivo_corte", "")
        sello["restaurado"] = bool(salida.get("restaurado"))
        sello["_archivo"] = escribir_sello(carpeta, sello)
        if tocar_index:
            sello["_index"] = bool(reflejar_en_index(sello, Path(carpeta).parent))
        return sello
    except Exception:
        return None


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


# ── Enganche: YA CABLEADO (2026-08-29) ─────────────────────────────────────────
#
# Durante un mes esta seccion fue un COMENTARIO que describia el cableado y
# nadie lo aplico: reintentar_si_falla() no tenia un solo llamador y 24
# productos con verificado=false llevaban en disco desde julio. Ahora el lazo
# vive en lazo_reparacion() (arriba) y lo llama run_program_hobby() al final,
# FUERA del `except Exception: pass` que se tragaba todo:
#
#     from .verificacion import lazo_reparacion
#     res = lazo_reparacion(dir_final, reparar_fn=_reparador_de(program, llm))
#
# Este modulo sigue sin hablar con el LLM: el reparador se INYECTA. El que sabe
# reparar (reparar_python/reparar_web) es generator.py, y quien lo compone es
# program_creator, que es donde vive el presupuesto y el disyuntor del creador.
