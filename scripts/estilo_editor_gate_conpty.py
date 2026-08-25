# Puerta REAL del gancho /estilo -> editor desde el REPL (ConPTY 100x30).
# Teclea /estilo en el REPL vivo, navega al prompt.etiqueta, escribe 'jarvis',
# Ctrl-S, Esc; comprueba alt-screen entra/sale, 'estilo: ... (cerrado)' y que
# el prompt siguiente dice jarvis. Guarda y restaura el estilo.json del dueno.
import os, re, shutil, sys, threading, time
from winpty import PtyProcess
ROOT = r"C:\Users\usuario\Desktop\cognia_v2"
PY = r"C:\Users\usuario\Desktop\cognia_v2\venv312\Scripts\python.exe"
AQUI = os.environ.get("ESTILO_GATE_DIR") or os.path.join(ROOT, "logs")
os.makedirs(AQUI, exist_ok=True)
OUT = os.path.join(AQUI, "gate_repl_editor_raw.txt")
casa = os.path.join(os.path.expanduser("~"), ".cognia")
est = os.path.join(casa, "estilo.json"); bak = est + ".bak"
copia = {p: (open(p, "rb").read() if os.path.exists(p) else None) for p in (est, bak)}
env = dict(os.environ); env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "COLORTERM": "truecolor", "COGNIA_SPINNER": "0",
                                              "COGNIA_EFIMERO": "1"})  # gate sin rastro en la memoria del dueno (2026-08-25)
for k in ("NO_COLOR", "COGNIA_REMOTO", "COGNIA_ANIMACION"): env.pop(k, None)
proc = PtyProcess.spawn([PY, "-m", "cognia"], cwd=ROOT, env=env, dimensions=(30, 100))
buf = []; ultimo = [time.time()]
def lector():
    while True:
        try: d = proc.read(4096)
        except Exception: break
        if not d:
            if not proc.isalive(): break
            time.sleep(0.03); continue
        buf.append(d); ultimo[0] = time.time()
threading.Thread(target=lector, daemon=True).start()
def cap(): return "".join(buf)
def esperar(marca, t=60):
    fin = time.time() + t
    while time.time() < fin:
        if marca in cap(): return True
        time.sleep(0.1)
    return False
def quieto(s=1.0, t=30):
    fin = time.time() + t
    while time.time() < fin:
        if time.time() - ultimo[0] > s: return True
        time.sleep(0.1)
    return False
res = {}
try:
    res["prompt1"] = esperar("\u27a4", 90); quieto(1.5)
    n0 = len(cap())
    proc.write("/estilo\r")
    res["editor_abre"] = esperar("VISTA PREVIA", 30); quieto(0.8)
    for _ in range(7): proc.write("\x1b[B"); time.sleep(0.15)
    proc.write("\r"); time.sleep(0.4); proc.write("\r"); time.sleep(0.4)
    for _ in range(6): proc.write("\x7f"); time.sleep(0.08)
    proc.write("jarvis"); time.sleep(0.4); proc.write("\r"); time.sleep(0.4)
    proc.write("\x13"); res["guardado"] = esperar("guardado ", 10); time.sleep(0.4)
    proc.write("\x1b"); time.sleep(0.6)
    res["vuelve_repl"] = esperar("estilo:", 20); quieto(1.5)
    tramo = cap()[n0:]
    res["alt_in"] = "\x1b[?1049h" in tramo; res["alt_out"] = "\x1b[?1049l" in tramo
    res["orden_alt"] = res["alt_in"] and res["alt_out"] and tramo.index("\x1b[?1049h") < tramo.rindex("\x1b[?1049l")
    # el prompt que el REPL dibuja al volver del editor tiene que decir jarvis
    tras = cap()[cap().rindex("\x1b[?1049l"):]
    res["prompt_jarvis"] = "jarvis\u27a4" in re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", tras)
    proc.write("/estilo reset\r"); esperar("[Si]", 10); time.sleep(0.3); proc.write("\r")
    esperar("al default", 10); quieto(1.0)
    proc.write("/salir\r"); esperar("Hasta luego", 15); time.sleep(1.0)
finally:
    try: proc.terminate(True)
    except Exception: pass
    open(OUT, "w", encoding="utf-8").write(cap())
    for p, c in copia.items():
        if c is None:
            if os.path.exists(p): os.remove(p)
        else: open(p, "wb").write(c)
limpio = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", "", cap())
m = re.search(r"estilo: [^\n]*", limpio)
print("RESULTADO", res, "| linea:", m.group(0)[:100] if m else None, "| bytes", len(cap()))
print("restaurado dueno:", all((open(p,'rb').read() if os.path.exists(p) else None) == c for p, c in copia.items()))
print("PUERTA:", "PASA" if all(res.get(k) for k in ("prompt1","editor_abre","guardado","vuelve_repl","orden_alt","prompt_jarvis")) else "NO PASA")
