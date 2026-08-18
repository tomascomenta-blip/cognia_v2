"""Mide el rendimiento REAL por worker de /largo --delegado contra el :8080 VIVO.

Metodo (obligatorio, ver la tarea):
  - Adopta el server que ya corre (LlamaBackend sobre _LlamaServerBackend, _proc=None).
    NO levanta otro server ni le cambia flags.
  - Cuenta tokens con POST /tokenize del propio server (nunca len//4). Ademas
    guarda el contador del generador (tokens_predicted sumado por generate_long)
    para poder reportar el error entre ambos.
  - n = 6 secciones DISTINTAS (outline real generado por el mismo camino que
    generate_delegated) y DOS brazos INTERCALADOS, alternando cual va primero
    en cada par para no regalarle el prefijo cacheado siempre al mismo brazo.

Brazos:
  A = prompt de worker ACTUAL (node/llama_backend.py:1656-1660)
  B = el mismo + "Escribe un minimo de 700 palabras."

Salida: JSONL por worker a stdout y al fichero que se pase como argv[1].
"""
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from node.llama_backend import LlamaBackend, _LlamaServerBackend
from shattering.model_constants import GEN_CHAT_TEMPERATURE

PORT = 8080
BASE = f"http://127.0.0.1:{PORT}"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("medicion_worker.jsonl")

# Mismo escenario que /largo --delegado --tokens 200000: per_task = min(5000,
# target//n_tasks) = 5000. Con 6 tareas y target 30000 sale el MISMO cap por
# worker (5000) sin pagar 40 workers.
PEDIDO = ("Escribe una guia tecnica completa y exhaustiva sobre el diseno, la "
          "implementacion y la operacion de sistemas de agentes de IA que corren "
          "modelos de lenguaje locales en una sola GPU de consumo.")
N_TASKS = 6
TARGET_TOKENS = 30000
PER_TASK = 5000
PRESUPUESTO_S = 1500.0   # corta en frontera de par si se pasa


def tokenize(texto: str) -> int:
    """Tokens REALES del texto segun el tokenizer del server (POST /tokenize)."""
    if not texto:
        return 0
    req = urllib.request.Request(
        f"{BASE}/tokenize",
        data=json.dumps({"content": texto}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return len(json.loads(resp.read()).get("tokens", []))


def main() -> int:
    impl = _LlamaServerBackend(Path("adoptado.gguf"), port=PORT)
    if impl._proc is not None:
        print("ABORTO: se levanto un server nuevo, no se adopto el vivo")
        return 2
    be = LlamaBackend(impl)
    print(f"[ctx] n_ctx_efectivo={be.n_ctx_efectivo()}", flush=True)

    # ---- outline REAL, por el mismo camino que generate_delegated ------------
    outline_prompt = be._append_to_user_turn(
        PEDIDO,
        f"Primero, devuelve SOLO un esquema de exactamente {N_TASKS} secciones "
        f"para responder lo anterior: una por linea, numeradas (1., 2., ...), con un "
        f"titulo corto cada una. Sin texto adicional."
    )
    # El outline es FLAKY: en 1 de 7 corridas medidas el 14B devolvio la lista
    # entera en una linea y _parse_outline saco 3 items. Reintentar hasta 3
    # veces (el outline cuesta ~2 s) en vez de abortar la medicion entera.
    tasks = []
    for intento in range(3):
        t0 = time.time()
        outline_text = be.generate(outline_prompt, max_tokens=max(128, N_TASKS * 32),
                                   temperature=GEN_CHAT_TEMPERATURE)
        tasks = be._parse_outline(outline_text or "", N_TASKS)
        print(f"[outline] intento {intento+1}: {len(tasks)} items en "
              f"{time.time()-t0:.1f}s", flush=True)
        if len(tasks) >= N_TASKS:
            break
    for i, t in enumerate(tasks):
        print(f"   {i+1}. {t}", flush=True)
    if len(tasks) < N_TASKS:
        print(f"ABORTO: el outline parseo {len(tasks)} < {N_TASKS} secciones")
        return 3
    outline_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(tasks))

    fh = OUT.open("w", encoding="utf-8")
    filas = []
    t_ini = time.time()

    def correr(idx: int, sec: str, brazo: str):
        extra = (f"Esquema:\n{outline_block}\n\n"
                 f"Escribe SOLO la seccion {idx+1}: {sec}. No repitas las otras secciones.")
        if brazo == "B":
            extra += " Escribe un minimo de 700 palabras."
        sec_prompt = be._append_to_user_turn(PEDIDO, extra)
        t = time.time()
        res = be.generate_long(sec_prompt, max_total_tokens=PER_TASK,
                               temperature=GEN_CHAT_TEMPERATURE)
        dt = time.time() - t
        if res is None:
            fila = {"seccion": idx + 1, "titulo": sec, "brazo": brazo,
                    "fallo": True, "s": round(dt, 1)}
        else:
            texto = res["text"] or ""
            fila = {
                "seccion": idx + 1, "titulo": sec, "brazo": brazo,
                "tok_tokenize": tokenize(texto),
                "tok_contador": res["total_tokens"],
                "rondas": res["rounds"],
                "stop": res["stop_reason"],
                "chars": len(texto),
                "palabras": len(texto.split()),
                "s": round(dt, 1),
            }
        filas.append(fila)
        fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
        fh.flush()
        print("  " + json.dumps(fila, ensure_ascii=False), flush=True)

    for i, sec in enumerate(tasks):
        if time.time() - t_ini > PRESUPUESTO_S:
            print(f"[presupuesto] corte tras {i} pares ({time.time()-t_ini:.0f}s)",
                  flush=True)
            break
        # alterna el brazo que va primero: el segundo de cada par hereda el
        # prefijo cacheado, y eso no debe favorecer siempre al mismo brazo.
        orden = ("A", "B") if i % 2 == 0 else ("B", "A")
        for brazo in orden:
            correr(i, sec, brazo)

    fh.close()
    total_s = time.time() - t_ini

    def resumen(brazo):
        v = [f["tok_tokenize"] for f in filas
             if f.get("brazo") == brazo and not f.get("fallo")]
        if not v:
            return None
        eos = [f for f in filas if f.get("brazo") == brazo and f.get("stop") == "eos"]
        return {
            "n": len(v), "min": min(v), "max": max(v),
            "mediana": statistics.median(v),
            "media": round(statistics.mean(v), 1),
            "p25": round(statistics.quantiles(v, n=4)[0], 1) if len(v) >= 4 else None,
            "p75": round(statistics.quantiles(v, n=4)[2], 1) if len(v) >= 4 else None,
            "iqr": (round(statistics.quantiles(v, n=4)[2]
                          - statistics.quantiles(v, n=4)[0], 1) if len(v) >= 4 else None),
            "eos_frac": f"{len(eos)}/{len(v)}",
        }

    print("\n[RESUMEN]", flush=True)
    print("A(actual)  " + json.dumps(resumen("A")), flush=True)
    print("B(700pal)  " + json.dumps(resumen("B")), flush=True)
    ok = [f for f in filas if not f.get("fallo")]
    tot_tok = sum(f["tok_tokenize"] for f in ok)
    print(f"total_s={total_s:.0f} workers={len(ok)} tok_total={tot_tok} "
          f"tok_s_pared={tot_tok/total_s:.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
