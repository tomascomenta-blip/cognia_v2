# -*- coding: utf-8 -*-
"""Kernel Kaggle: mide EAGLE3 speedup en hardware MEJOR que el i3 (2 cores),
para responder si el hundimiento (0.464x medido en el i3) es específico de
2-cores o general. Brazos: CPU (4 threads) y GPU T4. Par público conocido-bueno
(Qwen3-1.7B + AngelSlim/Qwen3-1.7B_eagle3, convertido a GGUF con el converter
b9606). NO entrena nada — solo mide (barato).

(2026-07-16) TODO el flujo vive bajo el guard __main__: este modulo viaja en
el wheel y antes ejecutaba git clone + wget + pip install + build CMake AL
IMPORTARSE (es un kernel para pegar en Kaggle, no un modulo importable).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

WORK = "/kaggle/working"
TMP = "/kaggle/tmp"
STUB = "/usr/local/cuda/lib64/stubs"
TARGET_GGUF = f"{TMP}/qwen3-4b-f16.gguf"
EAGLE_GGUF = f"{TMP}/qwen3-4b-eagle3.gguf"
PORT = 8097
PROMPTS = ["Write a Python function that reverses a linked list iteratively.",
           "Implement binary search in Python with a docstring."]


def sh(cmd, **kw):
    print(f"$ {cmd}", flush=True)
    return subprocess.run(cmd, shell=True, **kw)


def step(name):
    print(f"\n{'='*60}\n== {name}\n{'='*60}", flush=True)


def find_server(root):
    try:
        out = subprocess.check_output(f"find {root} -name llama-server -type f", shell=True).decode()
        for line in out.splitlines():
            if os.path.isfile(line.strip()):
                return line.strip()
    except Exception:
        pass
    return None


def bench(binpath, libdir, ngl, threads, eagle):
    subprocess.run("pkill -f llama-server", shell=True); time.sleep(2)
    extra = (f"-md {EAGLE_GGUF} --spec-type draft-eagle3 --spec-draft-n-max 8"
             if eagle else "")
    cmd = (f"{binpath} -m {TARGET_GGUF} --port {PORT} --ctx-size 4096 "
           f"-ngl {ngl} -t {threads} --log-disable {extra}")
    benv = dict(os.environ, LD_LIBRARY_PATH=f"{libdir}:{STUB}:/usr/local/cuda/lib64:"
                + os.environ.get("LD_LIBRARY_PATH", ""))
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=benv)
    t0 = time.time()
    while time.time() - t0 < 180:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1); break
        except Exception:
            if proc.poll() is not None:
                print("  server murió:", proc.stderr.read().decode()[-800:]); return None
            time.sleep(0.5)
    else:
        print("  no arrancó"); proc.kill(); return None
    try:
        tps = []
        for p in PROMPTS:
            for n in (8, 120):  # warmup + real
                payload = json.dumps({"prompt": p, "n_predict": n, "temperature": 0.0,
                                      "cache_prompt": False}).encode()
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/completion",
                                             data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.loads(r.read())
            tps.append(d.get("timings", {}).get("predicted_per_second", 0))
        return round(sum(tps) / len(tps), 2)
    finally:
        proc.terminate(); time.sleep(1); subprocess.run("pkill -f llama-server", shell=True)


def main():
    os.makedirs(TMP, exist_ok=True)
    RES = {}

    # ── 1. binarios: prebuilt CPU + compilar CUDA (con fix del stub) ────────
    step("1. clonar + preparar binarios llama.cpp b9606")
    sh(f"git clone --depth 1 --branch b9606 https://github.com/ggml-org/llama.cpp {TMP}/llama.cpp")

    # CPU prebuilt (rápido; se mide primero para tener AL MENOS este número)
    sh(f"cd {TMP} && mkdir -p cpu && cd cpu && wget -q https://github.com/ggml-org/llama.cpp/"
       f"releases/download/b9606/llama-b9606-bin-ubuntu-x64.tar.gz && tar xzf *.tar.gz")
    CPU_BIN = find_server(f"{TMP}/cpu")
    print(f"CPU_BIN: {CPU_BIN}", flush=True)

    # CUDA build FIX DEFINITIVO del 'cannot find -lCUDA::cuda_driver': el contenedor
    # GPU trae libcuda.so.1 (del driver) pero SIN el symlink .so que find_library
    # necesita -> crearlo apuntando al real (o al stub si no hay driver). Arch 75 = T4.
    REAL = subprocess.run("find / -name 'libcuda.so.1' 2>/dev/null | grep -v stubs | head -1",
                          shell=True, capture_output=True, text=True).stdout.strip()
    LIBCUDA = REAL if REAL else f"{STUB}/libcuda.so"
    sh(f"ln -sf {LIBCUDA} /usr/local/cuda/lib64/libcuda.so")
    print(f"libcuda: {LIBCUDA}", flush=True)
    env_cuda = dict(os.environ, LIBRARY_PATH="/usr/local/cuda/lib64:"
                    + os.environ.get("LIBRARY_PATH", ""))
    sh(f"cd {TMP}/llama.cpp && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release "
       f"-DLLAMA_CURL=OFF -DCMAKE_CUDA_ARCHITECTURES=75 "
       f"-DCUDA_cuda_driver_LIBRARY=/usr/local/cuda/lib64/libcuda.so "
       f"-DCMAKE_EXE_LINKER_FLAGS='-L/usr/local/cuda/lib64' 2>&1 | tail -4 && "
       f"cmake --build build --config Release -j4 --target llama-server 2>&1 | tail -6",
       env=env_cuda)
    CUDA_BIN = find_server(f"{TMP}/llama.cpp/build")
    CUDA_LIB = os.path.dirname(CUDA_BIN) if CUDA_BIN else ""
    print(f"CUDA_BIN: {CUDA_BIN}", flush=True)

    # ── 2. bajar par + convertir a GGUF ─────────────────────────────────────
    # Qwen3-4B: proxy del tamaño de NUESTRO Coder-3B (speculative paga en modelos
    # GRANDES; el 1.7B ya midió 0.597x en GPU = demasiado chico para amortizar).
    MODEL = "Qwen/Qwen3-4B"
    HEAD = "AngelSlim/Qwen3-4B_eagle3"
    step(f"2. bajar {MODEL} + cabeza {HEAD}, convertir a GGUF")
    sh("pip install -q sentencepiece huggingface_hub 2>&1 | tail -1")
    from huggingface_hub import snapshot_download, hf_hub_download
    snapshot_download(MODEL, local_dir=f"{TMP}/target",
                      allow_patterns=["*.safetensors", "*.json", "*.txt", "tokenizer*"])
    os.makedirs(f"{TMP}/head", exist_ok=True)
    for fn in ("config.json", "pytorch_model.bin"):
        try:
            hf_hub_download(HEAD, fn, local_dir=f"{TMP}/head")
        except Exception as e:
            print(f"  {fn}: {e}")
    # algunas cabezas usan safetensors en vez de .bin
    if not os.path.isfile(f"{TMP}/head/pytorch_model.bin"):
        try:
            hf_hub_download(HEAD, "model.safetensors", local_dir=f"{TMP}/head")
        except Exception as e:
            print(f"  model.safetensors: {e}")
    CONV = f"{TMP}/llama.cpp/convert_hf_to_gguf.py"
    env = dict(os.environ, PYTHONPATH=f"{TMP}/llama.cpp/gguf-py")
    sh(f"python {CONV} {TMP}/target --outtype f16 --outfile {TARGET_GGUF} 2>&1 | tail -3", env=env)
    sh(f"python {CONV} {TMP}/head --target-model-dir {TMP}/target --outtype bf16 "
       f"--outfile {EAGLE_GGUF} 2>&1 | tail -3", env=env)
    for g in (TARGET_GGUF, EAGLE_GGUF):
        print(f"{'OK' if os.path.isfile(g) else 'FALTA'}: {g} "
              f"({os.path.getsize(g)>>20 if os.path.isfile(g) else 0}MB)", flush=True)

    # ── 3. medir ─────────────────────────────────────────────────────────────
    step("3. medir GPU-T4 (el CPU ya midio 0.459x con 1.7B; hunde para cualquier tamano)")
    for label, binp, libd, ngl, thr in [("GPU-T4-4B", CUDA_BIN, CUDA_LIB, 99, 4)]:
        if not binp or not os.path.isfile(binp):
            RES[label] = {"error": "binario falta"}; print(f">>> {label}: binario falta"); continue
        base = bench(binp, libd, ngl, thr, eagle=False)
        eag = bench(binp, libd, ngl, thr, eagle=True)
        ratio = round(eag / base, 3) if base and eag else None
        RES[label] = {"base_tps": base, "eagle3_tps": eag, "ratio": ratio}
        print(f"\n>>> {label}: base {base} -> EAGLE3 {eag} = {ratio}x", flush=True)
        # guardar incremental (si el 2do brazo cuelga, el 1ro queda)
        with open(f"{WORK}/results_eagle3_kaggle.json", "w") as f:
            json.dump(RES, f, indent=1)

    RES["_ref_i3_2cores"] = {"ratio": 0.464, "nota": "medido local, kill-gate"}
    with open(f"{WORK}/results_eagle3_kaggle.json", "w") as f:
        json.dump(RES, f, indent=1)
    print("\n== RESUMEN ==")
    print(json.dumps(RES, indent=1))


if __name__ == "__main__":
    main()
