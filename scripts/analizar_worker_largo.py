"""Resume el JSONL de medir_worker_largo_delegado.py: tabla, mediana, dispersion,
fraccion de eos, tareas necesarias para 200k y pared estimada."""
import json
import math
import statistics
import sys
from pathlib import Path

filas = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
ok = [f for f in filas if not f.get("fallo")]

print(f"{'sec':>3} {'brazo':>5} {'tok/tokenize':>12} {'tok/contador':>12} "
      f"{'err':>5} {'rondas':>6} {'stop':>6} {'palabras':>8} {'s':>6} titulo")
for f in ok:
    err = f["tok_contador"] - f["tok_tokenize"]
    print(f"{f['seccion']:>3} {f['brazo']:>5} {f['tok_tokenize']:>12} "
          f"{f['tok_contador']:>12} {err:>+5} {f['rondas']:>6} {f['stop']:>6} "
          f"{f['palabras']:>8} {f['s']:>6.1f} {f['titulo'][:40]}")

errs = [f["tok_contador"] - f["tok_tokenize"] for f in ok]
print(f"\n[tokenize vs contador] error medio {statistics.mean(errs):+.1f} tok, "
      f"max |err| {max(abs(e) for e in errs)}, "
      f"error relativo max {max(abs(e)/f['tok_tokenize'] for e, f in zip(errs, ok))*100:.2f}%")


def bloque(nombre, sel):
    v = sorted(f["tok_tokenize"] for f in sel)
    if not v:
        return
    eos = sum(1 for f in sel if f["stop"] == "eos")
    q = statistics.quantiles(v, n=4) if len(v) >= 4 else [None, None, None]
    seg = sum(f["s"] for f in sel)
    print(f"{nombre:<22} n={len(v):<3} mediana={statistics.median(v):<8.0f} "
          f"media={statistics.mean(v):<8.1f} min={v[0]:<6} max={v[-1]:<6} "
          f"p25={q[0] if q[0] is None else round(q[0])} p75={q[2] if q[2] is None else round(q[2])} "
          f"eos={eos}/{len(v)} tok_s={sum(v)/seg:.1f}")


print()
for nombre, sel in (("A actual", [f for f in ok if f["brazo"] == "A"]),
                    ("B min700palabras", [f for f in ok if f["brazo"] == "B"]),
                    ("A sin seccion1", [f for f in ok if f["brazo"] == "A" and f["seccion"] != 1]),
                    ("B sin seccion1", [f for f in ok if f["brazo"] == "B" and f["seccion"] != 1]),
                    ("TODOS", ok)):
    bloque(nombre, sel)

# Netos APAREADOS intra-corrida (la unica evidencia valida: la varianza entre
# corridas de esta maquina es de +-34 pts).
pares = {}
for f in ok:
    pares.setdefault(f["seccion"], {})[f["brazo"]] = f
netos = [(s, d["B"]["tok_tokenize"] - d["A"]["tok_tokenize"])
         for s, d in sorted(pares.items()) if "A" in d and "B" in d]
if netos:
    v = [n for _, n in netos]
    print(f"\n[neto apareado B-A] {netos}")
    print(f"  mediana={statistics.median(v):+.0f} media={statistics.mean(v):+.1f} "
          f"signos B>A={sum(1 for x in v if x > 0)}/{len(v)}")

print()
for nombre, sel in (("A actual", [f for f in ok if f["brazo"] == "A"]),
                    ("B min700palabras", [f for f in ok if f["brazo"] == "B"])):
    v = [f["tok_tokenize"] for f in sel]
    if not v:
        continue
    M = statistics.median(v)
    tok_s = sum(v) / sum(f["s"] for f in sel)
    n200 = math.ceil(200000 / M)
    print(f"{nombre:<22} M={M:.0f} -> workers para 200k = {n200}; "
          f"pared = {200000/tok_s/60:.0f} min ({200000/tok_s/3600:.1f} h) a {tok_s:.1f} tok/s")
