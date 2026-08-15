# -*- coding: utf-8 -*-
"""b5_banco_busqueda.py — ¿el contexto ancho encuentra lo que el snippet no?

LA PREGUNTA. El pipeline de investigación de Cognia lee 3 páginas × 2000
chars porque nació con una ventana de 8k. El cerebro de hoy sirve 1.048.576
tokens. ¿Cambia eso el ACIERTO, o solo la factura?

POR QUE EL BANCO ES OFFLINE. Medir esto contra la web real mezcla tres cosas
que se mueven solas: el buscador (que banea y reordena), la red (que falla) y
la página (que cambia). Aquí las páginas las escribe el propio banco y las
sirve un http.server local: el pajar es DETERMINISTA y lo único que varía
entre brazos es el pipeline. Lo que esto NO mide, y hay que decirlo: la
calidad del buscador y la del ranking. Mide el eje del contexto, que es el
que tiene la máquina a favor.

EL DISEÑO. N páginas de relleno; en `--agujas` de ellas, un dato único
sembrado a PROFUNDIDAD (más allá de donde corta el brazo estrecho). La
pregunta pide ese dato. El acierto es textual y estricto.

  BRAZO estrecho : 3 páginas × 2000 chars   <- el pipeline de hoy (NULO)
  BRAZO medio    : 12 páginas × ~9k chars
  BRAZO ancho    : 40 páginas × ~14k chars
  BRAZO ciego    : sin páginas              <- segundo NULO: ¿lo sabe de memoria?

Los brazos van INTERCALADOS por ítem, no en bloques: si el server se degrada
con el tiempo, en bloques el degradado se lo come entero el último brazo.

Uso:
  venv312\\Scripts\\python.exe scripts\\b5_banco_busqueda.py --items 8
  ... --brazos estrecho,ancho --profundidad 6000
"""
from __future__ import annotations

import argparse
import http.server
import json
import random
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEED = 20260814
_FRASES = [
    "El nodo {n} sincronizo su estado con el coordinador sin incidencias.",
    "La revision {n} quedo registrada en la bitacora del turno de la tarde.",
    "El operador anoto que el sensor {n} devolvio una lectura dentro de rango.",
    "Se archivo el expediente {n} tras verificar las firmas correspondientes.",
    "El lote {n} paso el control de calidad con una desviacion despreciable.",
]


def _pagina_html(titulo: str, cuerpo: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{titulo}</title></head><body>\n"
            f"<h1>{titulo}</h1>\n<p>" + cuerpo.replace("\n", "</p>\n<p>")
            + "</p>\n</body></html>\n")


def construir_sitio(dirbase: Path, n_paginas: int, n_agujas: int,
                    profundidad: int, chars_pagina: int) -> list:
    """Escribe el sitio y devuelve los ítems [{pregunta, dato, url, pagina}].

    La aguja va SIEMPRE más abajo de `profundidad` chars: ese número es lo
    que hace del banco una prueba y no un trámite. Con profundidad 6000 y el
    brazo estrecho leyendo 2000, el estrecho no puede verla ni con suerte.
    """
    rnd = random.Random(SEED)
    dirbase.mkdir(parents=True, exist_ok=True)
    items = []
    for i in range(n_paginas):
        lineas, largo, k = [], 0, 0
        aguja_puesta = False
        dato = ""
        es_aguja = i < n_agujas
        while largo < chars_pagina:
            if es_aguja and not aguja_puesta and largo >= profundidad:
                dato = "%08x" % rnd.getrandbits(32)
                linea = (f"El codigo de calibracion del equipo QX-{i:03d} "
                         f"es {dato} y solo aparece en este informe.")
                aguja_puesta = True
            else:
                linea = rnd.choice(_FRASES).format(n=k)
                k += 1
            lineas.append(linea)
            largo += len(linea) + 1
        ruta = dirbase / f"informe_{i:03d}.html"
        ruta.write_text(_pagina_html(f"Informe tecnico QX-{i:03d}",
                                     "\n".join(lineas)), encoding="utf-8")
        if es_aguja:
            items.append({"pagina": i, "dato": dato,
                          "archivo": ruta.name,
                          "pregunta": (f"¿Cual es el codigo de calibracion "
                                       f"del equipo QX-{i:03d}?")})
    return items


def servir(dirbase: Path, puerto: int):
    """http.server en un hilo daemon. Devuelve (httpd, base_url)."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(dirbase), **kw)

        def log_message(self, *a):
            pass            # sin ruido: el banco ya imprime lo suyo

    httpd = socketserver.TCPServer(("127.0.0.1", puerto), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{puerto}"


def preguntar(pregunta: str, paginas: list, url_backend: str,
              max_tokens: int = 256) -> tuple:
    """Una pregunta con ese contexto. Devuelve (respuesta, segundos, tokens)."""
    import urllib.request
    if paginas:
        bloques = "\n\n".join(
            f"=== FUENTE {i + 1}: {p['url']} ===\n{p['texto']}"
            for i, p in enumerate(paginas))
        contenido = (f"{bloques}\n\n===\nPregunta: {pregunta}\n"
                     f"Responde SOLO con el codigo hexadecimal de 8 "
                     f"caracteres. Si no esta en las fuentes, responde "
                     f"NO_ENCONTRADO.")
    else:
        contenido = (f"Pregunta: {pregunta}\nResponde SOLO con el codigo "
                     f"hexadecimal de 8 caracteres. Si no lo sabes, responde "
                     f"NO_ENCONTRADO.")
    cuerpo = json.dumps({
        "messages": [{"role": "user", "content": contenido}],
        "max_tokens": max_tokens, "temperature": 0.0,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url_backend + "/v1/chat/completions",
                                 data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    m = d["choices"][0]["message"]
    texto = (m.get("content") or "") + " " + (m.get("reasoning_content") or "")
    return texto, time.time() - t0, (d.get("usage") or {}).get("prompt_tokens", 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items", type=int, default=8, help="preguntas (agujas)")
    ap.add_argument("--paginas", type=int, default=40)
    ap.add_argument("--profundidad", type=int, default=6000,
                    help="chars antes de la aguja (el estrecho lee 2000)")
    ap.add_argument("--chars-pagina", type=int, default=14000)
    ap.add_argument("--puerto", type=int, default=8791)
    ap.add_argument("--brazos", default="ciego,estrecho,medio,ancho")
    ap.add_argument("--backend", default="http://127.0.0.1:8080")
    ap.add_argument("--salida", default="b5_banco_busqueda.json")
    ap.add_argument("--aguja-fija", action="store_true",
                    help="aguja siempre en la posicion 3 (el comportamiento "
                         "viejo, para comparar con corridas ya publicadas)")
    args = ap.parse_args()

    from cognia.search import contexto as CTX
    from cognia.knowledge.navegador import extraer_muchas

    base = Path(__file__).resolve().parent.parent / ".banco_busqueda"
    items = construir_sitio(base, args.paginas, args.items,
                            args.profundidad, args.chars_pagina)
    httpd, raiz = servir(base, args.puerto)
    print(f"sitio: {args.paginas} páginas en {raiz} "
          f"({args.items} con aguja a >{args.profundidad} chars)")

    # Las páginas se descargan UNA vez y se reusan en todos los brazos: lo
    # que se compara es el pipeline de contexto, no la velocidad de httpx.
    urls = [f"{raiz}/informe_{i:03d}.html" for i in range(args.paginas)]
    t0 = time.time()
    lote = extraer_muchas(urls, cap=8)
    print(f"extracción: {lote.resumen()} en {time.time() - t0:.1f}s")
    textos = {s.spec: (s.valor or {}).get("texto", "") for s in lote.ok}

    brazos = [b.strip() for b in args.brazos.split(",") if b.strip()]
    filas = []
    for item in items:
        # DÓNDE va la página con la aguja. Nunca primera (el brazo estrecho
        # la leería por orden y el banco mediría el orden, no el contexto),
        # pero tampoco SIEMPRE en la 3: con la posición fija, el brazo ancho
        # se mide en su mejor caso y nunca tiene que buscar de verdad — lo
        # señaló la revisión adversarial del 2026-08-15.
        #
        # La posición se sortea con una semilla DERIVADA del ítem: cambia
        # entre ítems y es reproducible entre corridas, que es lo que un
        # brazo apareado necesita. `--aguja-fija` recupera el comportamiento
        # viejo para comparar contra las corridas ya publicadas.
        url_aguja = f"{raiz}/{item['archivo']}"
        otras = [u for u in urls if u != url_aguja]
        if args.aguja_fija:
            pos = 2
        else:
            pos = random.Random(SEED + item["pagina"]).randrange(
                1, max(2, len(otras)))
        orden = otras[:pos] + [url_aguja] + otras[pos:]
        paginas = [{"url": u, "texto": textos.get(u, "")} for u in orden
                   if textos.get(u)]

        for nombre in brazos:      # INTERCALADOS por ítem, no en bloques
            if nombre == "ciego":
                dadas = []
            else:
                modo = CTX.MODOS[nombre]
                dadas = CTX.repartir(paginas, modo)
            try:
                resp, seg, tok = preguntar(item["pregunta"], dadas,
                                           args.backend)
            except Exception as exc:
                print(f"  [{nombre:8}] EXCEPCION {type(exc).__name__}: {exc}")
                filas.append({"item": item["pagina"], "brazo": nombre,
                              "ok": False, "seg": 0, "tokens": 0,
                              "error": str(exc)[:200]})
                continue
            ok = item["dato"] in resp.lower()
            filas.append({"item": item["pagina"], "brazo": nombre, "ok": ok,
                          "seg": round(seg, 1), "tokens": tok,
                          "paginas": len(dadas), "pos_aguja": pos,
                          "aguja_dada": url_aguja in [d["url"] for d in dadas]})
            print(f"  QX-{item['pagina']:03d} [{nombre:8}] "
                  f"{'OK  ' if ok else 'FALLA'} {seg:6.1f}s "
                  f"{tok:>7,} tok  {len(dadas)} pág", flush=True)

    httpd.shutdown()

    print("\n" + "=" * 66)
    print(f"{'brazo':>10} {'acierto':>10} {'seg/ítem':>10} {'tok/ítem':>10} "
          f"{'acierto/min':>12}")
    resumen = {}
    for nombre in brazos:
        f = [x for x in filas if x["brazo"] == nombre]
        if not f:
            continue
        aciertos = sum(1 for x in f if x["ok"])
        seg = sum(x["seg"] for x in f) / len(f)
        tok = sum(x["tokens"] for x in f) / len(f)
        por_min = (aciertos / (sum(x["seg"] for x in f) / 60)) if seg else 0
        resumen[nombre] = {"aciertos": aciertos, "n": len(f),
                           "seg_medio": round(seg, 1),
                           "tokens_medio": int(tok)}
        print(f"{nombre:>10} {aciertos:>4}/{len(f):<5} {seg:>10.1f} "
              f"{int(tok):>10,} {por_min:>12.2f}")

    Path(args.salida).write_text(
        json.dumps({"config": vars(args), "filas": filas,
                    "resumen": resumen}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"\ndetalle -> {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
