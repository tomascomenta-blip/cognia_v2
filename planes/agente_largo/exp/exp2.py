import json, time, urllib.request, random, sys, subprocess
BASE="http://127.0.0.1:8080"
def post(path,obj,timeout=3600):
    r=urllib.request.Request(BASE+path,data=json.dumps(obj).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=timeout) as f: return json.loads(f.read().decode())
def vram():
    return int(subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],
            capture_output=True,text=True).stdout.strip().splitlines()[0])
random.seed(11)
W=["registro","modulo","commit","hipotesis","verificador","contexto","token","estado","plan",
   "restriccion","decision","hecho","ciclo","snapshot","agente","critico","provenance","confianza"]
def filler(n): return " ".join(random.choice(W)+str(random.randint(0,9999)) for _ in range(n))

out=[]
# E2: decode speed vs context depth. n_predict=200 fixed.
for words,label in [(80,"ctx~500"),(1700,"ctx~10k"),(5400,"ctx~32k"),(11000,"ctx~65k"),(22000,"ctx~130k")]:
    p=filler(words)+"\n\nEscribe un parrafo largo sobre la memoria de un agente. No pares antes de 200 tokens."
    t0=time.time(); r=post("/completion",{"prompt":p,"n_predict":200,"temperature":0.7,"cache_prompt":False}); dt=time.time()-t0
    tm=r["timings"]
    rec={"exp":"decode_vs_depth","label":label,"prompt_n":tm["prompt_n"],
         "prefill_s":round(tm["prompt_ms"]/1000,2),"prefill_tok_s":round(tm["prompt_per_second"],1),
         "decoded_n":tm["predicted_n"],"decode_s":round(tm["predicted_ms"]/1000,2),
         "decode_tok_s":round(tm["predicted_per_second"],2),"wall_s":round(dt,2),"vram":vram()}
    out.append(rec); print(json.dumps(rec),flush=True)

# E3: what the RESET throws away -- prefix cache reuse
base=filler(5400)
p1=base+"\n\nPregunta 1: resume en una linea."
p2=base+"\n\nPregunta 2: resume en una linea distinta."
t0=time.time(); r=post("/completion",{"prompt":p1,"n_predict":16,"temperature":0,"cache_prompt":True}); a=time.time()-t0
tm=r["timings"]; print(json.dumps({"exp":"cache","step":"cold","prompt_n":tm["prompt_n"],"n_cached":r.get("tokens_cached"),"prefill_s":round(tm["prompt_ms"]/1000,2),"wall_s":round(a,2)}),flush=True)
t0=time.time(); r=post("/completion",{"prompt":p2,"n_predict":16,"temperature":0,"cache_prompt":True}); b=time.time()-t0
tm=r["timings"]; print(json.dumps({"exp":"cache","step":"warm_same_prefix","prompt_n":tm["prompt_n"],"prompt_n_processed":tm.get("prompt_n"),"prefill_s":round(tm["prompt_ms"]/1000,2),"wall_s":round(b,2)}),flush=True)
# now simulate the RESET: brand new unrelated prefix of same size
p3=filler(5400)+"\n\nPregunta 3: resume en una linea."
t0=time.time(); r=post("/completion",{"prompt":p3,"n_predict":16,"temperature":0,"cache_prompt":True}); c=time.time()-t0
tm=r["timings"]; print(json.dumps({"exp":"cache","step":"after_reset_new_prefix","prompt_n":tm["prompt_n"],"prefill_s":round(tm["prompt_ms"]/1000,2),"wall_s":round(c,2)}),flush=True)
