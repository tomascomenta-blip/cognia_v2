"""
banco_rutas.py — el banco ETIQUETADO del enrutado chat vs agente.

Por que existe (dossier f2_enrutador-chat-agente): hoy no hay forma de saber
si un cambio en los guards o en el prompt del enrutador mejoro o empeoro. El
enrutador acierta, pero cuesta 1.841-27.121 ms con varianza de 3x sobre el
MISMO mensaje, asi que comparar corridas distintas no prueba nada: la varianza
ENTRE corridas se come cualquier efecto. Por eso este banco corre LOS DOS
BRAZOS EN LA MISMA CORRIDA, intercalados y sobre los MISMOS mensajes, y
compara los netos APAREADOS.

  ANTES    = el camino de hoy: siempre el modelo, con el pensamiento en su
             default y max_tokens=400 (lo que hacia `cli._inferir_para_agente`).
             Se fuerza anulando el camino determinista, no reimplementando el
             parser: asi se mide el enrutador de verdad y no una maqueta.
  PRODUCTO = el camino REAL del REPL, replicado call site por call site (ver
             `_ruta_producto`): `intent.detect` primero, el gate de
             `reason != "conversacional"`, el gate de >=3 palabras, y solo
             entonces `decidir(raw, None, catalogo, contexto=...)` — SIN
             `turno_previo_agente`, porque `cli.py` no lo pasa.

  escalon3 = brazo APARTE, opt-in con `--escalon3`, que mide lo que el
             escalon 3 VALDRIA si alguien lo cableara. NO es el producto: hoy
             ningun camino de `cli.py` pone `turno_previo_agente=True`
             (revision adversarial 2026-08-29). El brazo va etiquetado y no
             entra en el veredicto, para no medir de mas: el banco anterior
             pasaba `previo=True` en dos casos y anunciaba un ahorro que en
             produccion es CERO.

Uso:
    PYTHONUTF8=1 venv312/Scripts/python.exe scripts/banco_rutas.py
    ... --solo-determinista   (sin backend: mide y verifica solo lo barato)
    ... --escalon3            (anade el brazo NO CABLEADO, etiquetado)
    ... --json ruta.json      (vuelca los resultados crudos)

La etiqueta es ACCION vs CHAT, que es la decision del producto: "agente" y
"/comando" son las dos formas de actuar, y confundir una con otra no le cuesta
al dueno lo mismo que irse al chat sin hacer nada. La ruta exacta se imprime
igual, para ver si el camino barato le quito comandos a alguien.

Hay una tercera etiqueta, RESCATE: mensajes que ninguna regla determinista
reclama y que por eso TIENEN que llegar al modelo. Existe porque el modo de
fallo caro no es "se fue al chat": es `reason == "conversacional"`, que ademas
VETA EL ENRUTADOR ENTERO (cli.py:22654) y deja la accion sin agente Y sin
rescate. Un mensaje etiquetado `rescate` que sale `conversacional` es un fallo
del banco aunque la ruta final coincida.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

# El banco NO puede escribir en la memoria del dueno (leccion de la casa:
# "las pruebas contaminan la memoria del dueno"). Va antes de importar cognia.
os.environ.setdefault("COGNIA_EFIMERO", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cognia.enrutador as enr           # noqa: E402


# (mensaje, etiqueta) — etiqueta: "accion" | "chat" | "rescate".
#
# 69 mensajes. Los 9 primeros son los que uso la revision adversarial del
# 2026-08-29 para destapar que los guards ensanchados mataban acciones; el
# bloque "objeto NO-fichero" existe porque ESA fue la ceguera: los 8 casos
# adversarios de `tests/test_intent.py` llevaban todos una extension o un
# objeto del sistema de ficheros, asi que todos disparaban la contra-regla y
# ninguno cubria una accion sobre tests, git, un calculo o un proceso.
CASOS = [
    # -- los 9 de la revision adversarial (hallazgo 1) ---------------------
    ("cuentame el resultado de correr los tests", "accion"),
    ("cuentame que error da al ejecutar los tests", "accion"),
    ("cuentame si el build paso", "rescate"),
    ("cuentame el estado de git", "rescate"),
    ("cuentame que dice el log", "rescate"),
    ("cuentame cuanto es 2+2", "accion"),
    ("cuentame el resumen de la reunion", "rescate"),
    ("cuentame lo que devuelve git status", "accion"),
    ("cuentame el diff de git", "rescate"),
    # -- los 10 mensajes del dueno que midio el dossier --------------------
    ("crea un juego de flappy bird", "accion"),
    ("arregla el bug de la funcion de pago", "rescate"),
    ("abre chrome y busca gatos", "accion"),
    ("hazme un script que ordene mis descargas", "accion"),
    ("lee mis notas y resumelas en un fichero", "accion"),
    ("que es un DAG", "chat"),
    ("como estas hoy", "chat"),
    ("explicame la diferencia entre un hilo y un proceso", "chat"),
    ("que opinas de la inteligencia artificial", "chat"),
    ("cuentame un chiste", "chat"),
    # -- ACCIONES con objeto NO-fichero: tests, git, calculos, procesos, web
    ("corre los tests", "accion"),
    ("ejecuta los tests del modulo de pagos", "accion"),
    ("cuentame cuanto es 25 * 13", "accion"),
    ("cuentame que devuelve git diff", "accion"),
    ("cuentame el resultado de ejecutar el script de migracion", "accion"),
    ("que opinas de correr el benchmark ahora", "accion"),
    ("que opinas de resumir el libro", "accion"),
    ("cuentame que procesos estan consumiendo cpu", "rescate"),
    ("cuentame que tal va el servidor web", "rescate"),
    ("cuentame cuantos commits hice esta semana", "rescate"),
    ("que opinas, mata el proceso de python que se colgo", "rescate"),
    ("revisa el codigo y dime que opinas", "rescate"),
    # -- adversarios de los guards ensanchados (objeto de FICHERO) ---------
    ("cuentame que archivos hay en mi escritorio", "accion"),
    ("cuentame que hay en la carpeta descargas", "accion"),
    ("cuentame cuantos ficheros tengo en el escritorio", "accion"),
    ("cuentame el contenido de notas.txt", "rescate"),
    ("que opinas de C:/Users/usuario/Desktop/informe.md", "rescate"),
    ("que piensas, borra los logs viejos del proyecto", "rescate"),
    # -- comandos del catalogo ---------------------------------------------
    ("muestrame tus estadisticas", "accion"),
    ("investiga sobre transformers de vision", "accion"),
    # -- charla que NO puede acabar en el agente ---------------------------
    ("cual es la capital de Francia", "chat"),
    ("por que el cielo es azul", "chat"),
    ("gracias por la ayuda de antes", "chat"),
    ("me gusta como quedo el informe", "chat"),
    ("que comandos usaria para limpiar la papelera", "chat"),
    ("cuentame algo interesante", "chat"),
    ("te parece bien esa idea", "chat"),
    # -- accion sobre el sistema y peticion larga --------------------------
    ("organiza las capturas de pantalla de mi escritorio", "accion"),
    ("borra la ultima linea del archivo notas.txt", "accion"),
    # -- CHARLA CORRIENTE que pagaba el modelo (verificacion de cierre) ----
    # Los 15 medidos: de 30 mensajes de charla del dia a dia, la mitad salia
    # con reason="chat" y, con >=3 palabras, el REPL le preguntaba al modelo.
    # Coste con el backend vivo: 784 ms, 801 ms y 3.019 ms ANTES de empezar a
    # contestar "que tal estas". La ruta salia BIEN en los tres, asi que la
    # fuga era de COSTE. Aqui abajo son el brazo de regresion permanente: si
    # alguien estrecha los guards, vuelven a costar ~900 ms cada uno y la
    # columna 'sin modelo' del resumen lo canta.
    ("que tal estas", "chat"),
    ("que tal tu dia", "chat"),
    ("jaja muy bueno", "chat"),
    ("muchas gracias por todo", "chat"),
    ("eres muy util gracias", "chat"),
    ("me siento un poco cansado hoy", "chat"),
    ("hablame de la segunda guerra mundial", "chat"),
    ("dime algo bonito", "chat"),
    ("no entendi lo anterior", "chat"),
    ("no se que hacer hoy", "chat"),
    ("de que hablabamos", "chat"),
    ("tienes razon en eso", "chat"),
    ("me encanta como explicas", "chat"),
    ("que raro no?", "chat"),
    ("sabes cocinar paella", "chat"),
    # -- y sus ADVERSARIOS: el mismo arranque con trabajo detras -----------
    ("sabes si el build paso", "rescate"),
    ("hablame del error del servidor", "rescate"),
    ("cuentame de git", "rescate"),
    ("no se donde deje el informe", "rescate"),
    ("que curioso el error del log", "rescate"),
    ("muchas gracias, ahora ejecuta el script de migracion", "accion"),
]

# El brazo del escalon 3, APARTE y etiquetado: (mensaje, etiqueta, contexto).
# NO forman parte de CASOS y no entran en el veredicto: hoy `cli.py` no pone
# `turno_previo_agente=True` en ningun sitio, asi que este brazo mide una
# capacidad NO CABLEADA. Lo que falta cablear esta en el docstring de
# `cognia.agent.intent.detect`.
CASOS_ESCALON3 = [
    ("y ahora borralo", "accion",
     "usuario: crea un fichero prueba.txt en el escritorio\n"
     "cognia: escrito prueba.txt (12 bytes)"),
    ("otra vez pero en descargas", "accion",
     "usuario: organiza las capturas del escritorio\n"
     "cognia: movidas 8 capturas a capturas/"),
    ("hazlo", "accion",
     "usuario: renombra las fotos por fecha\ncognia: renombradas 14 fotos"),
    ("sigue", "accion",
     "usuario: convierte los csv a json\ncognia: convertidos 3 de 9"),
]


def _catalogo() -> str:
    """El catalogo REAL del CLI (82 comandos): si el banco usa un catalogo de
    juguete, mide otra cosa (el dossier lo comprobo: real vs mini cambia los
    tiempos)."""
    try:
        from cognia import cli
        return enr.catalogo_compacto(cli._cmds_visibles())
    except Exception as exc:
        print(f"[aviso] sin catalogo real ({type(exc).__name__}: {exc}); "
              f"se usa uno minimo")
        return "\n".join([
            "/pensar — Razonamiento PROFUNDO con modelo thinking",
            "/investigar — Investigar en GitHub <query>",
            "/crear — Crear programa ahora <idea>",
            "/stats — Estadisticas de la sesion",
        ])


def _backend_vivo() -> tuple:
    """(vivo, detalle). Mira /health y /slots: con UN solo slot, un banco
    lanzado mientras corre otra cosa mide la COLA, no el enrutador."""
    try:
        import urllib.request
        from cognia.agent.model_profiles import url_del_backend
    except Exception as exc:
        return False, f"sin cliente: {exc}"
    base = ""
    try:
        base = url_del_backend().rstrip("/")
        for suf in ("/v1/models", "/health"):
            with urllib.request.urlopen(base + suf, timeout=5) as r:
                if r.status != 200:
                    return False, f"{suf} devolvio {r.status}"
        ocupado = ""
        try:
            with urllib.request.urlopen(base + "/slots", timeout=5) as r:
                slots = json.loads(r.read().decode("utf-8", "replace"))
            if any(s.get("is_processing") for s in slots):
                ocupado = " (OJO: hay un slot PROCESANDO; los tiempos serian cola)"
        except Exception:
            pass
        return True, base + ocupado
    except Exception as exc:
        return False, f"{base or 'backend'}: {type(exc).__name__}: {exc}"


def _infer_viejo(prompt: str) -> str:
    """Lo que hacia el CLI antes: llm_local.generar con el pensamiento en su
    default y max_tokens=400."""
    from cognia import llm_local
    return llm_local.generar(prompt, temperature=0.2, max_tokens=400) or ""


def _acierta(ruta: str, etiqueta: str, reason: str) -> bool:
    """Un `rescate` acierta si NO se cerro en falso: ni agente inventado ni
    'conversacional' (que apaga el rescate). Que acabe en chat tras preguntarle
    al modelo es exactamente lo que tiene que pasar."""
    if etiqueta == "rescate":
        return reason != "conversacional"
    return (etiqueta == "chat") == (ruta == "chat")


# -- EL CAMINO DEL PRODUCTO, replicado call site por call site ---------------
# cli.py, rama de texto libre (~22610-22700):
#     _intent = _detect_intent(raw, respuesta_previa=_prev_chat)
#     _needs_tool = bool(_intent and _intent.needs_agent)
#     if (not _needs_tool and _conf_inv is None
#             and (_intent is None or _intent.reason != "conversacional")
#             and len(raw.split()) >= 3):
#         _ruta, _extra = decidir(raw, None, _cat_r,
#                                 contexto=_contexto_para_enrutador())
# Los tres gates importan: sin ellos el banco mide llamadas a `decidir` que el
# producto no hace nunca (p.ej. cualquier mensaje de <3 palabras).
GATE_PALABRAS = 3


def _ruta_producto(mensaje: str, infer, catalogo: str, *,
                   contexto: str = "", turno_previo_agente: bool = False):
    """(ruta, extra, via, reason) por el camino REAL del REPL."""
    from cognia.agent.intent import detect
    try:
        it = detect(mensaje, turno_previo_agente=turno_previo_agente)
    except Exception:
        it = None
    reason = getattr(it, "reason", "")
    if it is not None and it.needs_agent:
        return "agente", "", "intent", reason
    if reason == "conversacional":
        return "chat", "", "intent:conversacional", reason
    if len(mensaje.split()) < GATE_PALABRAS:
        return "chat", "", "gate:corto", reason
    # El REPL NO pasa `turno_previo_agente` a `decidir` (y no hace falta: si
    # el escalon 3 disparara, `detect` ya habria devuelto needs_agent).
    ruta, extra = enr.decidir(mensaje, infer, catalogo, contexto=contexto)
    return ruta, extra, enr.ultimo_enrutado().get("via", ""), reason


def _corre_brazo(nombre: str, catalogo: str, *, con_modelo: bool,
                 viejo: bool = False, casos=None, escalon3: bool = False) -> list:
    """Un brazo entero. `viejo`=True anula el camino determinista (mide el
    enrutador de antes); `escalon3`=True pasa turno_previo_agente=True, que es
    lo que el producto NO hace."""
    filas = []
    casos = casos if casos is not None else [(m, e, "") for m, e in CASOS]
    original = enr.ruta_determinista
    if viejo:
        enr.ruta_determinista = lambda *a, **k: None
    try:
        for mensaje, etiqueta, contexto in casos:
            if viejo:
                enr.invalidar_cache()   # el enrutador de antes no tenia cache
            if not con_modelo:
                infer = lambda _p: ""
            else:
                infer = _infer_viejo if viejo else enr.inferir_ruta
            t0 = time.perf_counter()
            if viejo:
                # brazo ANTES: el mismo gate del REPL, pero `decidir` sin
                # camino barato. Se mide el enrutador, no una maqueta.
                ruta, extra = enr.decidir(mensaje, infer, catalogo)
                via, reason = enr.ultimo_enrutado().get("via", ""), ""
            else:
                ruta, extra, via, reason = _ruta_producto(
                    mensaje, infer, catalogo, contexto=contexto,
                    turno_previo_agente=escalon3)
            ms = (time.perf_counter() - t0) * 1000.0
            ok = _acierta(ruta, etiqueta, reason)
            filas.append({"mensaje": mensaje, "etiqueta": etiqueta,
                          "ruta": ruta, "extra": extra, "ms": ms,
                          "via": via, "reason": reason, "ok": ok,
                          "brazo": nombre})
            print(f"  {'OK ' if ok else 'MAL'} {ms:9.1f} ms  {via:<21} "
                  f"{ruta:<8} {mensaje[:44]}")
    finally:
        enr.ruta_determinista = original
    return filas


def _resumen(nombre: str, filas: list) -> dict:
    ms = sorted(f["ms"] for f in filas)
    aciertos = sum(1 for f in filas if f["ok"])
    p = lambda q: ms[min(len(ms) - 1, int(round(q * (len(ms) - 1))))]
    return {"brazo": nombre, "n": len(filas), "aciertos": aciertos,
            "precision": aciertos / len(filas) if filas else 0.0,
            "p50_ms": p(0.5), "p95_ms": p(0.95),
            "media_ms": statistics.fmean(ms) if ms else 0.0,
            "max_ms": ms[-1] if ms else 0.0,
            "sin_modelo": sum(1 for f in filas if f["via"] not in ("modelo",)),
            "vetados": sum(1 for f in filas
                           if f["etiqueta"] != "chat"
                           and f["reason"] == "conversacional")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-determinista", action="store_true")
    ap.add_argument("--escalon3", action="store_true",
                    help="anade el brazo NO CABLEADO del escalon 3")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    catalogo = _catalogo()
    print(f"catalogo: {len(catalogo.splitlines())} comandos, "
          f"{len(catalogo)} chars")
    vivo, detalle = _backend_vivo()
    print(f"backend: {'VIVO' if vivo else 'NO DISPONIBLE'} - {detalle}")
    con_modelo = vivo and not args.solo_determinista
    if not con_modelo:
        print("\n*** Sin modelo: se mide SOLO el camino determinista. Los "
              "casos que necesitan el modelo cuentan como chat (que es el "
              "fallback honesto) y no se pueden usar para juzgar la "
              "precision del brazo del modelo. ***")

    todo = []
    if con_modelo:
        print("\n[ANTES] enrutador de antes: siempre modelo, pensando, 400 tok")
        enr.reset_contadores(); enr.invalidar_cache()
        antes = _corre_brazo("antes", catalogo, con_modelo=True, viejo=True)
        todo += antes
    else:
        antes = []

    print("\n[PRODUCTO] el camino REAL del REPL (intent -> gates -> decidir)")
    enr.reset_contadores(); enr.invalidar_cache()
    producto = _corre_brazo("producto", catalogo, con_modelo=con_modelo)
    todo += producto

    esc3 = []
    if args.escalon3:
        print("\n[escalon3] NO CABLEADO EN PRODUCCION: cli.py nunca pone "
              "turno_previo_agente=True.")
        print("           Este brazo mide lo que VALDRIA cablearlo; no entra "
              "en el veredicto.")
        enr.reset_contadores(); enr.invalidar_cache()
        esc3 = _corre_brazo("escalon3", catalogo, con_modelo=con_modelo,
                            casos=CASOS_ESCALON3, escalon3=True)
        print("\n[escalon3-hoy] los MISMOS mensajes por el camino de HOY "
              "(turno_previo_agente=False), que es lo que el dueno tiene:")
        enr.reset_contadores(); enr.invalidar_cache()
        esc3_hoy = _corre_brazo("escalon3_hoy", catalogo,
                                con_modelo=con_modelo, casos=CASOS_ESCALON3)
        todo += esc3 + esc3_hoy
    else:
        esc3_hoy = []

    print("\n" + "=" * 78)
    print(f"{'brazo':<13} {'precision':>10} {'p50 ms':>10} {'p95 ms':>10} "
          f"{'max ms':>10} {'sin modelo':>11} {'vetados':>8}")
    resumenes = []
    for nombre, filas in (("antes", antes), ("producto", producto),
                          ("escalon3", esc3), ("escalon3_hoy", esc3_hoy)):
        if not filas:
            continue
        r = _resumen(nombre, filas)
        resumenes.append(r)
        print(f"{nombre:<13} {r['aciertos']:>3}/{r['n']:<6} "
              f"{r['p50_ms']:>10.1f} {r['p95_ms']:>10.1f} "
              f"{r['max_ms']:>10.1f} {r['sin_modelo']:>7}/{r['n']} "
              f"{r['vetados']:>8}")
    print("\n'vetados' = mensajes de accion/rescate marcados 'conversacional'. "
          "Ese es\nel fallo caro: apaga el agente Y el rescate del enrutador "
          "(cli.py:22654).")

    if antes:
        # NETOS APAREADOS: el mismo mensaje en la misma corrida. Comparar
        # medias de corridas distintas no dice nada con varianza de 3x.
        pares = [(a["ms"] - d["ms"], a["ok"], d["ok"], a["mensaje"])
                 for a, d in zip(antes, producto)]
        ganados = [m for m, _, _, _ in pares if m > 0]
        print(f"\nnetos APAREADOS (mismo mensaje, misma corrida): "
              f"{len(ganados)}/{len(pares)} mas rapidos; "
              f"mediana del ahorro {statistics.median(m for m,_,_,_ in pares):.0f} ms")
        regres = [m for m in pares if m[1] and not m[2]]
        print(f"regresiones de acierto (acertaba ANTES y falla el PRODUCTO): "
              f"{len(regres)}")
        for _, _, _, msg in regres:
            print(f"   - {msg}")

    malos = [f for f in producto if not f["ok"]]
    if malos:
        print(f"\nfallos del brazo PRODUCTO ({len(malos)}):")
        for f in malos:
            print(f"   - [{f['etiqueta']}->{f['ruta']}/{f['reason']}] "
                  f"{f['mensaje']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"resumenes": resumenes, "filas": todo}, fh,
                      ensure_ascii=False, indent=1)
        print(f"\ncrudo en {args.json}")

    # El veredicto lo da el brazo PRODUCTO, y solo el: el brazo escalon3 mide
    # una capacidad que el producto no toma.
    r_pro = _resumen("producto", producto)
    if r_pro["vetados"]:
        print(f"\nVEREDICTO: {r_pro['vetados']} mensajes de accion/rescate "
              f"salieron 'conversacional' (accion sin agente y sin rescate)")
        return 1
    if antes and _resumen("antes", antes)["aciertos"] > r_pro["aciertos"]:
        print("\nVEREDICTO: el brazo nuevo PIERDE aciertos contra el viejo")
        return 1
    if con_modelo and r_pro["precision"] < 1.0:
        print(f"\nVEREDICTO: el brazo del producto no llega a "
              f"{r_pro['n']}/{r_pro['n']}")
        return 1
    print("\nVEREDICTO: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
