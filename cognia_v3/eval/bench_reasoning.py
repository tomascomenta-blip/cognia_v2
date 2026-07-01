r"""
BENCH REASONING — calidad de respuestas del modelo REAL, verificable y e2e (TAREA 3).

Raíz que ataca: el stack no tiene NINGÚN eval de razonamiento verificable ni CoT estructurado
(recon 2026-07-01): benchmark_code mide código (40% pass@1) y baseline.py usa keyword-matching
débil. Acá: 16 problemas de razonamiento con respuesta ENTERA exacta (verificación determinista,
sin LLM-juez) + 4 de seguimiento de instrucciones de formato (compliance por regex/JSON estricto).

CONDICIONES (mejoras candidatas — se queda lo que mida mejor, se descarta el resto):
  direct : pregunta + formato de respuesta, temp=0 (baseline del sistema deployado)
  cot    : + "Pensá paso a paso" antes de responder, temp=0 (¿el CoT explícito paga en un 3B?)
  sc3    : cot a temp=0.7 con 3 seeds y voto por mayoría (¿self-consistency paga su costo 3x?)
Los 4 items de formato corren en direct y cot (¿el CoT ROMPE el seguimiento de formato?).

Corre contra el sistema REAL deployado: LlamaBackend.try_load() (llama-server + GGUF + LoRA si
LLAMA_LORA_PATH está seteada — se registra en el JSON). Para reproducibilidad matar llama-server.exe
antes (gotcha MANAGER_LOG: el backend ADOPTA un server vivo con otra config).

USO:
  venv312\Scripts\python.exe -m cognia_v3.eval.bench_reasoning --smoke     # 3 items, solo direct
  venv312\Scripts\python.exe -m cognia_v3.eval.bench_reasoning             # batería completa
"""
import argparse
import datetime
import json
import re
import time
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

# ── batería: respuesta ENTERA exacta, verificada a mano al escribir cada item ──────────────────────
ITEMS = [
    ("m01", "Un cuaderno cuesta 350 pesos y una lapicera 120 pesos. Compro 3 cuadernos y 4 lapiceras "
            "y pago con 2000 pesos. ¿Cuántos pesos me dan de vuelto?", 470),
    ("m02", "Un tren sale a las 09:40 y viaja 2 horas 45 minutos. ¿A qué hora llega? Respondé la hora "
            "como un número de 4 dígitos HHMM (ej: las 14:05 son 1405).", 1225),
    ("m03", "Tengo 84 caramelos y los reparto en partes iguales entre 7 chicos. Después cada chico "
            "regala 3 caramelos. ¿Cuántos caramelos le quedan a cada chico?", 9),
    ("m04", "Una remera cuesta 1200 pesos después de aplicarle 25% de descuento. ¿Cuál era el precio "
            "original en pesos?", 1600),
    ("m05", "Un auto consume 8 litros cada 100 km. ¿Cuántos litros consume en un viaje de 350 km?", 28),
    ("m06", "María tiene el triple de la edad de Juan. Juntos suman 48 años. ¿Cuántos años tiene María?", 36),
    ("m07", "Un tanque de 900 litros está lleno al 40%. Se agregan 180 litros. ¿Cuántos litros hay "
            "ahora en el tanque?", 540),
    ("m08", "Compro 5 cajas con 24 huevos cada una. En el viaje se rompen 17 huevos. ¿Cuántos huevos "
            "sanos quedan?", 103),
    ("m09", "Un albañil coloca 45 ladrillos por hora. Trabaja 6 horas por día durante 4 días. "
            "¿Cuántos ladrillos coloca en total?", 1080),
    ("m10", "El doble de un número menos 14 es igual a 36. ¿Cuál es el número?", 25),
    ("m11", "Una pileta se llena con dos canillas a la vez: una tira 30 litros por minuto y la otra "
            "20 litros por minuto. ¿Cuántos minutos tardan en llenar 2500 litros entre las dos?", 50),
    ("m12", "En una clase de 32 alumnos, 3/8 son varones. ¿Cuántas mujeres hay?", 20),
    ("l01", "Ana es más alta que Berta. Carla es más baja que Berta. Diana es más alta que Ana. "
            "¿Cuántas de estas personas son más bajas que Ana?", 2),
    ("l02", "Un caracol sube 3 metros de día y resbala 2 metros de noche. El pozo mide 10 metros. "
            "¿En qué día (número) llega arriba?", 8),
    ("l03", "Si pasado mañana es jueves, ¿qué día fue ayer? Respondé con el número del día de la "
            "semana (lunes=1, martes=2, ... domingo=7).", 1),
    ("l04", "Tengo cartas numeradas del 1 al 20. Saco todas las que son múltiplos de 3. "
            "¿Cuántas cartas me quedan?", 14),
]

# formato: (id, prompt, check_fn_name, esperado). compliance = respeta el formato EXACTO pedido.
FORMAT_ITEMS = [
    ("f01", 'Calculá 17 por 23. Respondé ÚNICAMENTE con un objeto JSON exactamente así: '
            '{"respuesta": numero} — sin ningún otro texto, sin markdown.', "json_respuesta", 391),
    ("f02", 'Listá los primeros 5 números primos. Respondé ÚNICAMENTE con un JSON exactamente así: '
            '{"primos": [lista de numeros]} — sin ningún otro texto.', "json_primos", [2, 3, 5, 7, 11]),
    ("f03", "Calculá 144 dividido 12, más 5. Respondé ÚNICAMENTE con el número en dígitos, "
            "nada más (ni palabras, ni puntuación).", "solo_numero", 17),
    ("f04", "Escribí la palabra hola exactamente 3 veces separadas por comas, sin espacios y sin "
            "ningún otro texto.", "exacto", "hola,hola,hola"),
]

ANSWER_TAG = ("\n\nEscribí la respuesta final en la ÚLTIMA línea con este formato exacto:\n"
              "RESPUESTA: <número>")
COT_TAG = ("\n\nPensá paso a paso: mostrá el razonamiento en pasos numerados y recién al final "
           "escribí la ÚLTIMA línea con este formato exacto:\nRESPUESTA: <número>")


def extract_int(text):
    """Último 'RESPUESTA: n'; fallback: último entero del texto. None si no hay."""
    ms = re.findall(r"RESPUESTA\s*:\s*\$?\s*(-?[\d][\d.,]*)", text, re.IGNORECASE)
    cand = ms[-1] if ms else None
    if cand is None:
        nums = re.findall(r"-?\d[\d.,]*", text)
        cand = nums[-1] if nums else None
    if cand is None:
        return None
    c = cand.strip().rstrip(".,")
    c = c.replace(".", "").replace(",", "")     # respuestas son ENTEROS: separadores fuera
    try:
        return int(c)
    except ValueError:
        return None


def check_format(kind, expected, text):
    """(compliance, correct) para los items de formato."""
    t = text.strip()
    if kind == "json_respuesta":
        try:
            obj = json.loads(t)
            return True, obj.get("respuesta") == expected
        except Exception:  # noqa: BLE001
            return False, extract_int(t) == expected
    if kind == "json_primos":
        try:
            obj = json.loads(t)
            return True, obj.get("primos") == expected
        except Exception:  # noqa: BLE001
            return False, [int(n) for n in re.findall(r"\d+", t)][:5] == expected
    if kind == "solo_numero":
        return bool(re.fullmatch(r"-?\d+", t)), extract_int(t) == expected
    if kind == "exacto":
        return t == expected, t == expected
    return False, False


def gen(backend, user_prompt, max_tokens, temperature, seed):
    from node.inference_pipeline import _apply_qwen_template
    from shattering.model_constants import COGNIA_SYSTEM_PROMPT
    prompt = _apply_qwen_template(user_prompt, system=COGNIA_SYSTEM_PROMPT)
    t0 = time.time()
    out = backend.generate(prompt, max_tokens=max_tokens, temperature=temperature,
                           seed=seed, cache_prompt=False)
    return out, time.time() - t0


def run_condition(backend, items, cond, log):
    """cond: 'direct' | 'cot' | 'sc3'. Devuelve {id: {pred, ok, wall_s, [votes]}}."""
    res = {}
    for iid, q, ans in items:
        if cond == "direct":
            out, dt = gen(backend, q + ANSWER_TAG, 96, 0.0, 0)
            pred = extract_int(out)
        elif cond == "cot":
            out, dt = gen(backend, q + COT_TAG, 400, 0.0, 0)
            pred = extract_int(out)
        else:                                   # sc3: CoT a temp 0.7, 3 seeds, voto mayoría
            votes, dt = [], 0.0
            for seed in (1, 2, 3):
                out, d1 = gen(backend, q + COT_TAG, 400, 0.7, seed)
                dt += d1
                votes.append(extract_int(out))
            valid = [v for v in votes if v is not None]
            pred = Counter(valid).most_common(1)[0][0] if valid else None
        ok = (pred == ans)
        res[iid] = {"pred": pred, "expected": ans, "ok": ok, "wall_s": round(dt, 1)}
        if cond == "sc3":
            res[iid]["votes"] = votes
        log(f"  [{cond}:{iid}] pred={pred} esperado={ans} {'OK' if ok else 'X'} ({dt:.0f}s)")
    return res


def run_format(backend, cond, log):
    res = {}
    for fid, q, kind, expected in FORMAT_ITEMS:
        extra = COT_TAG.replace("RESPUESTA: <número>", "tu respuesta en el formato pedido") \
            if cond == "cot" else ""
        out, dt = gen(backend, q + extra, 300 if cond == "cot" else 120, 0.0, 0)
        comp, corr = check_format(kind, expected, out)
        res[fid] = {"compliance": comp, "correct": corr, "wall_s": round(dt, 1),
                    "raw": out[:200]}
        log(f"  [fmt-{cond}:{fid}] compliance={comp} correct={corr} ({dt:.0f}s)")
    return res


def summarize(block):
    oks = [r["ok"] for r in block.values()]
    wall = sum(r["wall_s"] for r in block.values())
    return {"acc": round(sum(oks) / len(oks), 4), "n": len(oks), "wall_s": round(wall, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="3 items, solo direct")
    ap.add_argument("--conds", type=str, default="direct,cot,sc3")
    args = ap.parse_args()

    from node.llama_backend import LlamaBackend
    backend = LlamaBackend.try_load()
    if backend is None:
        raise SystemExit("No se pudo cargar LlamaBackend (¿GGUF/llama-server?)")
    info = getattr(backend, "info", lambda: {})()
    print(f"[bench_reasoning] backend={info}", flush=True)

    items = ITEMS[:3] if args.smoke else ITEMS
    conds = ["direct"] if args.smoke else [c.strip() for c in args.conds.split(",")]
    out = {"experiment": "bench_reasoning", "timestamp": datetime.datetime.now().isoformat(),
           "backend_info": str(info), "n_items": len(items), "conds": conds, "results": {},
           "format": {}, "summary": {}}
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_reasoning_{ts}.json"

    def log(s):
        print(s, flush=True)

    def save():
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    for cond in conds:
        log(f"\n==== {cond} ====")
        out["results"][cond] = run_condition(backend, items, cond, log)
        out["summary"][cond] = summarize(out["results"][cond])
        save()

    if not args.smoke:
        for cond in ("direct", "cot"):
            log(f"\n==== formato ({cond}) ====")
            fr = run_format(backend, cond, log)
            out["format"][cond] = fr
            out["summary"][f"format_{cond}"] = {
                "compliance": round(sum(r["compliance"] for r in fr.values()) / len(fr), 4),
                "correct": round(sum(r["correct"] for r in fr.values()) / len(fr), 4)}
            save()

    log("\n==== RESUMEN ====")
    for k, v in out["summary"].items():
        log(f"  {k}: {v}")
    save()
    log(f"\n[bench_reasoning] resultados -> {out_path}")


if __name__ == "__main__":
    main()
