# Adherencia CONDUCTUAL (no declarativa) a restricciones vs profundidad
import json, urllib.request, re, random
BASE="http://127.0.0.1:8080"
def comp(prompt,n=700,temp=0.4,seed=0):
    r=urllib.request.Request(BASE+"/completion",data=json.dumps(
        {"prompt":prompt,"n_predict":n,"temperature":temp,"cache_prompt":True,"seed":seed}).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=900) as f:
        j=json.loads(f.read().decode()); return j["content"], j["timings"]
def strip_think(t): return re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()
RL=open("R.txt",encoding="utf-8").read()
random.seed(5)
W=["registro","modulo","commit","traza","warning","deprecacion","ruta","variable","funcion","dependencia"]
def filler(nw): return " ".join(random.choice(W)+str(random.randint(0,9999)) for _ in range(nw))

TASK=("Escribe una funcion Python `cobrar(cliente_id, importe)` que llame por HTTP al API del proveedor "
      "de pagos, guarde la transaccion con su importe y su fecha, y maneje los errores. Solo el codigo.")
# checks conductuales: (nombre, regla_ok, regla_violacion)
def score(code):
    c=code.lower()
    out={}
    out["R07_httpx"] = ("httpx" in c) and not re.search(r"\bimport requests\b|requests\.(get|post)", c)
    out["R12_decimal"] = ("decimal" in c) and not re.search(r"\bfloat\(", c)
    out["R10_timeout30"] = bool(re.search(r"timeout\s*=\s*30", c))
    out["R13_utc"] = ("utc" in c)
    out["R11_docstring"] = bool(re.search(r'"""', code))
    out["R24_stack"] = bool(re.search(r"exc_info|traceback|\.exception\(", c))
    return out

res=[]
for nw,label in [(0,"~0.4k"),(5200,"~32k"),(21000,"~128k")]:
    body=("<|im_start|>system\nEres un agente de desarrollo. Restricciones permanentes:\n"+RL+
          "\nRespetalas SIEMPRE al escribir codigo.<|im_end|>\n")
    if nw: body += "<|im_start|>user\nRegistro previo (ruido):\n"+filler(nw)+"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\nRecibido.<|im_end|>\n"
    agg={}; n=4
    for s in range(n):
        p=body+f"<|im_start|>user\n{TASK}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        c,tm=comp(p,seed=s)
        sc=score(strip_think(c))
        for k,v in sc.items(): agg[k]=agg.get(k,0)+int(v)
    tot=sum(agg.values()); mx=len(agg)*n
    rec={"depth":label,"ctx":tm["prompt_n"],"n_muestras":n,
         "por_restriccion":{k:f"{v}/{n}" for k,v in agg.items()},
         "adherencia_global":f"{tot}/{mx}","rate":round(tot/mx,3)}
    res.append(rec); print(json.dumps(rec,ensure_ascii=False),flush=True)
json.dump(res,open("h6.json","w"),indent=1)
