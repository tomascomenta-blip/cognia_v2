r"""
M0 / GATE G1 (A-018) — ¿el ahorro de banda de la atención SLIDING-WINDOW (SWA) se
materializa con los kernels CPU REALES de llama.cpp en el i3?

Esta es LA pregunta que decide la arquitectura del backbone v1 (00_READINESS / 11_plan_maestro):
  - RAMA A (híbrido): mayoría capas de estado fijo + minoría SWA. Sólo es viable SI la SWA
    aplana el coste de decode y la RAM de KV al crecer el contexto L (vs atención full O(L)).
  - RAMA B (fallback, madura HOY): Transformer denso GQA + KV-cache 4-bit.

Precedente de que el ahorro teórico de bytes NO se materializa solo (exp007): int8 naïve en numpy
fue 8-10× MÁS LENTO sin kernel especializado. G1 mide el caso REAL en el hardware objetivo.

QUÉ MIDE (sobre el i3, llama-server b9391, CPU puro, n_gpu_layers=0), por longitud de contexto L:
  - decode tok/s(L)  — si SWA aplana y full cae con L, la SWA gana banda (señal a favor de RAMA A).
  - prefill tok/s(L)
  - tamaño de KV-cache (MiB) que el server reserva — full crece ∝ L; SWA se acota a la ventana.

CÓMO DECIDE (regla pre-registrada, recalibrable en M0):
  RAMA A si, al pasar de L=2048 a L=16384, el modelo SWA conserva >=70% de su decode tok/s Y su
  KV(MiB) se aplana (no crece ∝ L), MIENTRAS el full pierde decode y su KV crece ∝ L.
  Si la SWA NO aplana en CPU (o el operador no tiene kernel eficiente) -> RAMA B.

USO (stdlib puro, corre con venv312 sin dependencias):
  # 1) modelo FULL-attention (ya presente en el repo):
  .\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py \
      --gguf model_shards\qwen-coder-3b-q4\Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf \
      --label qwen3b_full
  # 2) modelo SWA-nativo (descargar 1 GGUF Gemma-2/3 o Phi-3; ver M0_G1_G2_ejecucion.md):
  .\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py \
      --gguf model_shards\gemma2-2b\gemma-2-2b-it-Q4_K_M.gguf --label gemma2_swa
  # 3) comparar e imprimir el veredicto G1:
  .\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py --compare

  Smoke rápido (verifica que el harness corre, L cortos):
  .\venv312\Scripts\python.exe cognia_x\construccion\m0_g1_bandwidth.py --gguf <full.gguf> --label x --smoke
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
BINARY = REPO / "node" / "llama-server.exe"
OUT = Path(__file__).resolve().parent / "results_g1"
OUT.mkdir(parents=True, exist_ok=True)

PORT = 8097                       # puerto dedicado a G1 (no choca con prod 8088 ni bench 8099)
N_THREADS = max(1, (os.cpu_count() or 4) - 1)    # 3 en el i3 (el 4to hilo daña, exp medido)
SERVER_BOOT_TIMEOUT = 240         # s (modelos grandes + ctx grande tardan en arrancar)

# Longitudes de contexto a barrer (tokens de prefill aprox). El contraste vive en L grande.
# Rango elegido para caber en el ctx nativo de un GGUF SWA chico (Gemma-2-2B = 8192).
LENGTHS = [512, 2048, 4096, 8192]
SMOKE_LENGTHS = [256, 1024]
N_PREDICT = 96                    # tokens de decode medidos por punto (ignore_eos -> exacto)
SMOKE_N_PREDICT = 24

# Filler para construir prompts de ~L tokens. Repetimos hasta exceder L (1 palabra ~ 1 token).
_FILLER = ("El sistema mide la velocidad de decodificacion en funcion de la longitud del contexto "
           "para decidir si la atencion de ventana deslizante conserva ancho de banda en CPU. ")


def _port_free() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) != 0
    finally:
        s.close()


def _health() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


# Patrones del log de llama.cpp para el tamaño de KV-cache (varían por versión/arquitectura).
_KV_PATTERNS = [
    re.compile(r"KV self size\s*=\s*([\d.]+)\s*MiB", re.I),
    re.compile(r"KV cache size\s*=\s*([\d.]+)\s*MiB", re.I),
    re.compile(r"kv_cache.*?size\s*=\s*([\d.]+)\s*MiB", re.I),
    re.compile(r"KV buffer size\s*=\s*([\d.]+)\s*MiB", re.I),
]


def _parse_kv_mib(log_text: str) -> float | None:
    """Suma TODOS los tamaños de KV-cache reportados (los modelos SWA reportan varios buffers:
    uno acotado por la ventana + a veces uno global). Devuelve el total en MiB, o None."""
    total = 0.0
    found = False
    for pat in _KV_PATTERNS:
        for m in pat.finditer(log_text):
            total += float(m.group(1))
            found = True
        if found:
            break  # usa el primer patrón que matchee (evita doble conteo entre patrones)
    return round(total, 1) if found else None


def launch(gguf: Path, ctx: int) -> tuple[subprocess.Popen | None, Path]:
    log = OUT / "server_g1.log"
    cmd = [str(BINARY), "--model", str(gguf), "--port", str(PORT),
           "--ctx-size", str(ctx), "--n-gpu-layers", "0",
           "--parallel", "1",                    # 1 sola secuencia -> KV/ctx limpios (sin split en 4 slots)
           "--threads", str(N_THREADS), "--threads-batch", str(N_THREADS),
           "--flash-attn", "on"]                 # SIN --log-disable: por si el build loguea el KV
    fh = open(log, "w", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    deadline = time.time() + SERVER_BOOT_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            fh.flush()
            return None, log                      # murió al arrancar
        if _health():
            time.sleep(0.5)                       # deja que termine de loguear el KV size
            fh.flush()
            return proc, log
        time.sleep(0.5)
    proc.kill()
    return None, log


def make_prompt(target_tokens: int) -> str:
    # El filler tiene ~30 palabras; la tokenización infla ~1.5x (medido). Apuntamos POR DEBAJO del
    # target (reps≈target/50 -> ~0.9*target tokens) para NUNCA exceder el ctx; se reporta el prompt_n real.
    reps = max(1, target_tokens // 50)
    return (_FILLER * reps)


def _rss_mib(pid: int) -> float | None:
    """RSS (working set, MiB) del proceso server vía PowerShell WorkingSet64 (entero crudo en bytes ->
    locale-independiente, a diferencia de tasklist que cambia el formato por idioma). Best-effort.
    El delta de RSS entre ctx chico y grande aísla el crecimiento de la KV-cache (los pesos son fijos)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).WorkingSet64"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if out:
            return round(int(out.split()[0]) / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def gen(prompt: str, n_predict: int) -> dict:
    payload = json.dumps({
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.0,
        "seed": 0,
        "cache_prompt": False,      # prefill limpio cada punto
        "ignore_eos": True,         # decodifica EXACTO n_predict tokens
        "stop": [],
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion", data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.loads(r.read())
    wall = time.time() - t0
    tim = data.get("timings", {}) or {}
    return {
        "decode_tps": tim.get("predicted_per_second"),
        "prefill_tps": tim.get("prompt_per_second"),
        "prompt_n": tim.get("prompt_n"),
        "predicted_n": tim.get("predicted_n") or data.get("tokens_predicted"),
        "wall_s": round(wall, 2),
    }


def measure_model(gguf: Path, label: str, lengths: list[int], n_predict: int) -> dict:
    assert BINARY.is_file(), f"falta binario: {BINARY}"
    assert gguf.is_file(), f"falta GGUF: {gguf}"
    out = {"label": label, "model": gguf.name, "threads": N_THREADS,
           "n_predict": n_predict, "cpu_count": os.cpu_count(), "binary": BINARY.name,
           "points": [], "errors": []}
    for L in lengths:
        if not _port_free():
            print(f"[g1] puerto {PORT} ocupado; abortando", flush=True)
            break
        ctx = L + n_predict + 256
        print(f"\n[g1] {label} | L~{L} | ctx={ctx} | arrancando server...", flush=True)
        proc, log = launch(gguf, ctx)
        if proc is None:
            tail = log.read_text(encoding="utf-8", errors="ignore")[-1200:]
            print(f"[g1] {label} L~{L} NO arrancó. log tail:\n{tail}", flush=True)
            out["errors"].append({"L": L, "log_tail": tail})
            continue
        try:
            kv_mib = _parse_kv_mib(log.read_text(encoding="utf-8", errors="ignore"))
            m = gen(make_prompt(L), n_predict)
            rss_mib = _rss_mib(proc.pid)
            row = {"L": L, "ctx": ctx, "kv_mib": kv_mib, "rss_mib": rss_mib, **m}
            out["points"].append(row)
            print(f"[g1] {label:>14} | L~{L:>6} (real {m['prompt_n']}) | "
                  f"decode={_fmt(m['decode_tps'])} tok/s | prefill={_fmt(m['prefill_tps'])} | "
                  f"KV={kv_mib} | RSS={rss_mib} MiB", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[g1] {label} L~{L} ERROR: {e!r}", flush=True)
            out["errors"].append({"L": L, "error": repr(e)})
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
            time.sleep(1.0)
    (OUT / f"g1_{label}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    return out


def _fmt(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "  -  "


def _retention(points: list[dict], short_L: int, long_L: int) -> float | None:
    """decode_tps(long_L) / decode_tps(short_L): cuánta velocidad conserva al crecer L."""
    d = {p["L"]: p.get("decode_tps") for p in points if p.get("decode_tps")}
    if short_L in d and long_L in d and d[short_L]:
        return round(d[long_L] / d[short_L], 3)
    return None


def _mem_growth(points: list[dict], short_L: int, long_L: int) -> tuple[float | None, str]:
    """Crecimiento de memoria de la KV al pasar de short_L a long_L. Prefiere kv_mib (si el build lo
    loguea); si no, usa el DELTA de RSS sobre el RSS de short_L (aísla la KV; los pesos son fijos)."""
    kv = {p["L"]: p.get("kv_mib") for p in points if p.get("kv_mib")}
    if short_L in kv and long_L in kv and kv[short_L]:
        return round(kv[long_L] / kv[short_L], 3), "kv_mib"
    rss = {p["L"]: p.get("rss_mib") for p in points if p.get("rss_mib")}
    if short_L in rss and long_L in rss:
        base = rss[short_L]
        # crecimiento relativo de RSS (incluye pesos fijos -> el ratio subestima, pero el SIGNO/aplanamiento es válido)
        return round(rss[long_L] / base, 3) if base else None, "rss_total"
    return None, "n/a"


def compare() -> None:
    files = sorted(OUT.glob("g1_*.json"))
    if not files:
        print("[g1] no hay resultados aún. Corré primero con --gguf <full> y --gguf <swa>.")
        return
    models = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    print("\n================ G1 — decode tok/s y KV-cache vs longitud de contexto ================")
    for mdl in models:
        print(f"\n# {mdl['label']}  ({mdl['model']}, threads={mdl['threads']}, n_predict={mdl['n_predict']})")
        print(f"{'L':>8} | {'prompt_n':>8} | {'decode tok/s':>12} | {'prefill tok/s':>13} | {'KV MiB':>8} | {'RSS MiB':>9}")
        print("-" * 72)
        for p in mdl["points"]:
            print(f"{p['L']:>8} | {str(p.get('prompt_n')):>8} | {_fmt(p.get('decode_tps')):>12} | "
                  f"{_fmt(p.get('prefill_tps')):>13} | {str(p.get('kv_mib')):>8} | {str(p.get('rss_mib')):>9}")
    # Veredicto pre-registrado (recalibrable): retención de decode y crecimiento de memoria de 2048->8192.
    lo, hi = 2048, 8192
    print(f"\n---------------- VEREDICTO G1 (retención decode + crecimiento memoria, {lo}->{hi}) -----------")
    verdict_rows = []
    for mdl in models:
        ret = _retention(mdl["points"], lo, hi)
        mg, src = _mem_growth(mdl["points"], lo, hi)
        verdict_rows.append((mdl["label"], ret, mg))
        print(f"  {mdl['label']:>16} | retención decode {lo}->{hi} = {ret} | mem growth = {mg} ({src})")
    swa = [r for r in verdict_rows if r[1] is not None and any(k in r[0].lower() for k in ("swa", "gemma", "phi", "mistral"))]
    full = [r for r in verdict_rows if r not in swa and r[1] is not None]
    if swa:
        name, ret, mg = swa[0]
        full_ret = full[0][1] if full else None
        # RAMA A si el SWA conserva >=70% del decode Y lo conserva MEJOR que el full (la ventana ayuda en CPU).
        ramaA = (ret is not None and ret >= 0.70) and (full_ret is None or ret >= full_ret + 0.05)
        print(f"\n  REGLA: RAMA A (híbrido) viable si el SWA conserva >=70% del decode al crecer L Y lo conserva")
        print(f"         MEJOR que el full (>=+0.05). Si no -> RAMA B (GQA denso, atención plena, madura HOY).")
        print(f"  -> SWA '{name}' retención={ret} vs full retención={full_ret}  =>  "
              f"{'RAMA A VIABLE (la SWA aplana el decode en CPU)' if ramaA else 'RAMA B (la SWA NO aplana el decode en CPU)'}")
        print(f"     (memoria: SWA growth={mg} — si <full, la ventana acota la KV; señal secundaria)")
    else:
        print("\n  (Falta el modelo SWA: corré con un GGUF Gemma-2/3, Phi-3 o Mistral-SWA y --label con 'swa'/'gemma'/'phi'.)")
    print("==========================================================================================\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="G1/A-018 — banda de SWA vs atención full en CPU (i3)")
    ap.add_argument("--gguf", type=str, default=None, help="ruta al GGUF a medir")
    ap.add_argument("--label", type=str, default=None, help="etiqueta (incluí 'swa'/'gemma'/'phi' para el modelo SWA)")
    ap.add_argument("--smoke", action="store_true", help="L cortos + n_predict chico (verifica que corre)")
    ap.add_argument("--lengths", type=str, default=None, help="CSV de longitudes (override)")
    ap.add_argument("--n_predict", type=int, default=None)
    ap.add_argument("--compare", action="store_true", help="imprime la tabla comparativa + veredicto G1")
    args = ap.parse_args()

    if args.compare:
        compare()
        return
    if not args.gguf or not args.label:
        ap.error("se requiere --gguf y --label (o --compare)")

    lengths = SMOKE_LENGTHS if args.smoke else LENGTHS
    if args.lengths:
        lengths = [int(x) for x in args.lengths.split(",")]
    n_predict = (SMOKE_N_PREDICT if args.smoke else N_PREDICT) if args.n_predict is None else args.n_predict

    gguf = Path(args.gguf)
    if not gguf.is_absolute():
        gguf = REPO / gguf
    measure_model(gguf, args.label, lengths, n_predict)
    print(f"\n[g1] listo. Resultados en {OUT / ('g1_' + args.label + '.json')}. "
          f"Cuando tengas FULL y SWA, corré: python {Path(__file__).name} --compare")


if __name__ == "__main__":
    main()
