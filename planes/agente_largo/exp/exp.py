import json, time, subprocess, urllib.request, threading, statistics, sys

BASE="http://127.0.0.1:8080"

def post(path, obj, timeout=1800):
    d=json.dumps(obj).encode()
    r=urllib.request.Request(BASE+path, data=d, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode())

def vram():
    out=subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],
                       capture_output=True,text=True).stdout.strip().splitlines()[0]
    return int(out)

class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.vals=[]; self.stop=False
    def run(self):
        while not self.stop:
            try: self.vals.append(vram())
            except Exception: pass
            time.sleep(0.25)

def ntok(text):
    return len(post("/tokenize", {"content":text})["tokens"])

# filler text: pseudo-random-ish prose so it is not trivially compressible by cache
import random
random.seed(7)
WORDS=["registro","modulo","commit","hipotesis","verificador","contexto","token","estado","plan",
       "restriccion","decision","hecho","ciclo","snapshot","agente","critico","provenance","confianza",
       "latencia","prefill","cache","memoria","jerarquica","deriva","instruccion","reset","sesion"]
def filler(approx_tokens):
    # ~1.3 tokens/word for spanish on qwen; overshoot then trim
    n=int(approx_tokens*1.1)
    return " ".join(random.choice(WORDS)+str(random.randint(0,9999)) for _ in range(n))

results={}

def run_prefill(n_target, label, sample=False):
    txt=filler(n_target)
    body={"prompt": txt+"\n\nResponde solo con la palabra OK.", "n_predict":1, "temperature":0, "cache_prompt": False}
    s=None
    if sample:
        s=Sampler(); s.start()
    t0=time.time()
    r=post("/completion", body)
    dt=time.time()-t0
    if s:
        s.stop=True; s.join()
    tm=r.get("timings",{})
    rec={"label":label,"wall_s":round(dt,3),
         "prompt_n": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"),
         "prompt_per_second": tm.get("prompt_per_second"),
         "predicted_per_second": tm.get("predicted_per_second")}
    if s:
        rec["vram_min"]=min(s.vals); rec["vram_max"]=max(s.vals); rec["vram_samples"]=len(s.vals)
    print(json.dumps(rec), flush=True)
    return rec

print(json.dumps({"vram_idle_pre":vram()}), flush=True)
out=[]
for n in [500, 2000, 8000, 16000, 32000]:
    out.append(run_prefill(n, f"prefill_{n}", sample=True))
    time.sleep(1)
print(json.dumps({"vram_idle_post":vram()}), flush=True)
json.dump(out, open(sys.argv[1],"w"), indent=1)
