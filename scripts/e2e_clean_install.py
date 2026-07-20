# -*- coding: utf-8 -*-
"""E2E de INSTALACIÓN LIMPIA (simula un computador Windows diferente):

  1. venv NUEVO (sin nada del repo) + pip install del wheel local.
  2. COGNIA_HOME temporal; SIN LLAMA_GGUF_PATH/LLAMA_SERVER_PATH/LLAMA_LORA_PATH
     heredadas (en otra máquina no existen).
  3. `cognia install-model` REAL: GGUF 1.9GB de HF + llama-server b9391 de
     GitHub + fleet del release fleet-v1.
  4. Verificación: desde el venv limpio, apply_config + LlamaBackend.try_load
     → fleet cargado, el experto contesta como Cognia, la base contesta distinto.

Uso:  .\\venv312\\Scripts\\python.exe scripts/e2e_clean_install.py <workdir>
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "_clean_install_e2e").resolve()
VENV = WORK / "venv_clean"
HOME = WORK / "cognia_home"
CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""),
          flush=True)


def limpio_env():
    env = dict(os.environ)
    for k in ("LLAMA_GGUF_PATH", "LLAMA_SERVER_PATH", "LLAMA_LORA_PATH",
              "SHARD_WEIGHTS_DIR"):
        env.pop(k, None)
    env["COGNIA_HOME"] = str(HOME)
    env["PYTHONUTF8"] = "1"
    return env


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    py = VENV / "Scripts" / "python.exe"

    if not py.is_file():
        print("== 1. venv limpio ==", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)

    wheels = sorted((REPO / "dist_test").glob("cognia_ai-*.whl"))
    assert wheels, "no hay wheel en dist_test/ (pip wheel . --no-deps -w dist_test)"
    print(f"== 2. pip install {wheels[-1].name} ==", flush=True)
    r = subprocess.run([str(py), "-m", "pip", "install", "--quiet", str(wheels[-1])],
                       capture_output=True, text=True, timeout=1800)
    check("pip install del wheel", r.returncode == 0, (r.stderr or "")[-200:])

    print("== 3. cognia install-model (descarga REAL) ==", flush=True)
    r = subprocess.run([str(py), "-m", "cognia", "install-model"],
                       env=limpio_env(), capture_output=True, text=True,
                       timeout=3 * 3600, cwd=str(WORK))
    salida = (r.stdout or "") + (r.stderr or "")
    print(salida[-1500:], flush=True)
    check("install-model exit 0", r.returncode == 0)
    gguf = HOME / "models" / "qwen-coder-3b-q4" / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    check("GGUF descargado (>1.5GB)", gguf.is_file() and gguf.stat().st_size > 1.5 * (1 << 30),
          f"{gguf.stat().st_size / (1<<30):.2f} GB" if gguf.is_file() else "no existe")
    check("llama-server descargado",
          (HOME / "bin" / "llama-b9391" / "llama-server.exe").is_file())
    check("fleet descargado",
          (HOME / "models" / "qwen-coder-3b-q4" / "adapters.json").is_file() and
          (HOME / "models" / "qwen-coder-3b-q4" / "cognia3b_v2_f16.gguf").is_file())

    print("== 4. inferencia real desde el venv limpio ==", flush=True)
    # matar cualquier llama-server previo: si el backend ADOPTA un server de
    # esta maquina la verificacion es falsa (leccion medida 2026-07-08)
    subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"],
                   capture_output=True)
    probe = WORK / "probe.py"
    probe.write_text('''
import json, os
from cognia.first_run import apply_config
apply_config()
from node.llama_backend import LlamaBackend
b = LlamaBackend.try_load()
assert b is not None, "backend no levanto"
res = {"fleet": b.fleet_experts}
P = ("<|im_start|>system\\nEres un asistente \\u00fatil.<|im_end|>\\n"
     "<|im_start|>user\\n\\u00bfQui\\u00e9n sos?<|im_end|>\\n<|im_start|>assistant\\n")
b.activate_expert("accion")
res["experto"] = (b.generate(P, max_tokens=60, temperature=0.0) or "")[:150]
b.activate_expert(None)
res["base"] = (b.generate(P, max_tokens=60, temperature=0.0) or "")[:150]
print("PROBE_JSON:" + json.dumps(res, ensure_ascii=False))
''', encoding="utf-8")
    r = subprocess.run([str(py), str(probe)], env=limpio_env(),
                       capture_output=True, text=True, timeout=1200, cwd=str(WORK))
    out = (r.stdout or "") + (r.stderr or "")
    linea = next((l for l in out.splitlines() if l.startswith("PROBE_JSON:")), "")
    print(out[-800:], flush=True)
    if linea:
        import json as _json
        res = _json.loads(linea[len("PROBE_JSON:"):])
        check("fleet cargado en maquina limpia", res.get("fleet") == ["accion"], str(res.get("fleet")))
        check("experto contesta como Cognia", "cognia" in res.get("experto", "").lower(),
              res.get("experto", "")[:100])
        check("base NO contesta como Cognia", "cognia" not in res.get("base", "").lower(),
              res.get("base", "")[:100])
    else:
        check("probe corrio", False, out[-300:])

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E INSTALACION LIMPIA: {len(CHECKS) - len(fallos)}/{len(CHECKS)} checks OK")
    if fallos:
        print("FALLARON:", fallos)
        sys.exit(1)


if __name__ == "__main__":
    main()
