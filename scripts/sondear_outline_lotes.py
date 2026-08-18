"""Sondeo INDEPENDIENTE del outline por LOTES (_plan_outline) contra el :8080 vivo.

Que se mide y por que: el camino viejo (una sola llamada de outline para n
secciones) devolvia menos items de los pedidos sin avisar -- medido el
2026-08-17: n=144 -> 144 items en 1 de 2 corridas y 55 en la otra, y flaky
incluso a n=6. El camino nuevo pide un INDICE de capitulos y luego el esquema de
cada capitulo por separado (lotes de GEN_OUTLINE_BATCH), CUENTA los items de cada
lote y reintenta. Este script no confia en eso: corre el camino nuevo N veces por
cada n y cuenta los items que salen.

Registra, por corrida:
  n, items devueltos, exacto (len == n), niveles, capitulos, error del plan,
  llamadas al backend, LOTES que necesitaron reintento (el parseo crudo que
  fallo), segundos.

Uso:
  venv312/Scripts/python.exe scripts/sondear_outline_lotes.py [salida.jsonl] \
      [--ns 24,40,100,144] [--reps 3]
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from node.inference_pipeline import _apply_qwen_template
from node.llama_backend import LlamaBackend, _LlamaServerBackend
from shattering.model_constants import COGNIA_SYSTEM_PROMPT, GEN_CHAT_TEMPERATURE

PORT = 8080
# El pedido IMPORTA: con el pedido corto de abajo salieron 6/6 outlines limpios,
# y con el pedido REAL del gate (el largo, con "al menos 700 palabras") 12 de 24
# titulos salieron encadenados. Se deja configurable para poder medir el mismo
# pedido con el que se va a correr.
PEDIDO = os.environ.get("COGNIA_SONDEO_PEDIDO", "").strip() or (
    "Escribe un manual exhaustivo y coherente en espanol sobre INGENIERIA DE "
    "SISTEMAS DISTRIBUIDOS: fundamentos, modelos de consistencia, consenso "
    "(Paxos/Raft), replicacion, particionado, tolerancia a fallos, relojes "
    "logicos, colas de mensajes, almacenamiento, observabilidad, seguridad y "
    "patrones de diseno."
)


def _cadena_degenerada(items: list) -> int:
    """Cuantos titulos son una EXTENSION del anterior (el modelo en bucle).

    Medido el 2026-08-18 en un ensayo de 24 secciones: el conteo daba 24/24 y
    24 titulos distintos, pero del 12 al 23 el modelo iba encadenando
    'Modelos de Consistencia de Sesgo' -> '... Total' -> '... Parcial' ->
    '... Parcial Total' ... Doce secciones (el 50% del documento) sobre un tema
    inventado. El conteo NO ve esto: los strings son todos distintos."""
    n = 0
    for a, b in zip(items, items[1:]):
        pa, pb = a.strip().lower(), b.strip().lower()
        if pb.startswith(pa) or pa.startswith(pb):
            n += 1
    return n


def main(argv: list) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("--") else Path("sondeo_outline.jsonl")
    ns = [24, 40, 100, 144]
    reps = 3
    for i, a in enumerate(argv):
        if a == "--ns":
            ns = [int(x) for x in argv[i + 1].split(",")]
        if a == "--reps":
            reps = int(argv[i + 1])

    impl = _LlamaServerBackend(Path("adoptado.gguf"), port=PORT)
    if impl._proc is not None:
        print("ABORTO: se levanto un server nuevo, no se adopto el vivo")
        return 2
    be = LlamaBackend(impl)
    print(f"[ctx] n_ctx_efectivo={be.n_ctx_efectivo()}", flush=True)

    prompt = _apply_qwen_template(PEDIDO, COGNIA_SYSTEM_PROMPT)

    # Instrumentacion: cuantas llamadas al backend y cuantos parseos crudos NO
    # dieron el numero pedido (= reintentos que el camino nuevo absorbe).
    cont = {"gen": 0, "parse_ok": 0, "parse_mal": 0, "detalle": []}
    gen_real = be.generate
    parse_real = LlamaBackend._parse_outline

    def gen_spy(*a, **k):
        cont["gen"] += 1
        return gen_real(*a, **k)

    def parse_spy(text, max_sections):
        items = parse_real(text, max_sections)
        if len(items) == max_sections:
            cont["parse_ok"] += 1
        else:
            cont["parse_mal"] += 1
            cont["detalle"].append({"pedi": max_sections, "parsee": len(items)})
        return items

    be.generate = gen_spy
    be._parse_outline = parse_spy

    fh = out.open("w", encoding="utf-8")
    filas = []
    for n in ns:
        for r in range(reps):  # noqa: PLR1702
            cont.update({"gen": 0, "parse_ok": 0, "parse_mal": 0, "detalle": []})
            t0 = time.time()
            tasks, bloques, meta = be._plan_outline(prompt, n, GEN_CHAT_TEMPERATURE)
            dt = time.time() - t0
            fila = {
                "n": n, "rep": r + 1, "items": len(tasks), "exacto": len(tasks) == n,
                "niveles": meta["niveles"], "lote": meta["lote"],
                "capitulos": len(meta["capitulos"]), "error": meta["error"],
                "llamadas": cont["gen"], "parse_ok": cont["parse_ok"],
                "parse_mal": cont["parse_mal"], "reintentos": list(cont["detalle"]),
                "s": round(dt, 1),
                "bloques_len": len(bloques),
                "cadena_degenerada": _cadena_degenerada(tasks),
                "titulos": list(tasks),
            }
            filas.append(fila)
            fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
            fh.flush()
            resumen = {k: v for k, v in fila.items() if k != "titulos"}
            print("  " + json.dumps(resumen, ensure_ascii=False), flush=True)

    fh.close()
    print("\n[RESUMEN]", flush=True)
    for n in ns:
        f = [x for x in filas if x["n"] == n]
        ex = sum(1 for x in f if x["exacto"])
        rein = sum(x["parse_mal"] for x in f)
        seg = sum(x["s"] for x in f) / max(1, len(f))
        deg = [x["cadena_degenerada"] for x in f]
        print(f"  n={n:4d}  exactos {ex}/{len(f)}  "
              f"lotes_reintentados={rein}  s_medio={seg:.1f}  "
              f"titulos_en_cadena={deg}", flush=True)
    return 0 if all(x["exacto"] for x in filas) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
