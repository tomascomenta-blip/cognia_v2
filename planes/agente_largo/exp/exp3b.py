import json, urllib.request, random, re, time
BASE="http://127.0.0.1:8080"
def comp(prompt,n=32,temp=0.0):
    r=urllib.request.Request(BASE+"/completion",data=json.dumps(
        {"prompt":prompt,"n_predict":n,"temperature":temp,"cache_prompt":False}).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=300) as f: return json.loads(f.read().decode())["content"]
def strip_think(t):
    return re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()

random.seed(2026)
N=60
pairs=[(random.randint(1000,9999), random.randint(1000,9999)) for _ in range(N)]

def ask_exec(a,b):
    p=("<|im_start|>system\nEres un calculador. Responde SOLO con el numero final, sin texto ni pasos.<|im_end|>\n"
       f"<|im_start|>user\nCalcula {a} * {b}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
    t=strip_think(comp(p,n=20))
    m=re.findall(r"\d[\d\.,\s]*", t)
    if not m: return None
    try: return int(re.sub(r"[^\d]","",m[0]))
    except: return None

def ask_critic(a,b,z):
    p=("<|im_start|>system\nEres un verificador critico y riguroso cuya unica mision es detectar errores. "
       "Responde SOLO con SI o NO.<|im_end|>\n"
       f"<|im_start|>user\nOtro agente afirma que {a} * {b} = {z}\n"
       "Verifica la afirmacion. Responde SOLO SI (es correcta) o NO (es incorrecta).<|im_end|>\n"
       "<|im_start|>assistant\n<think>\n\n</think>\n\n")
    t=strip_think(comp(p,n=8)).upper()
    if t.startswith("SI") or t.startswith("S\u00cd"): return True
    if t.startswith("NO"): return False
    return None

rows=[]; t0=time.time()
for a,b in pairs:
    got=ask_exec(a,b); rows.append({"a":a,"b":b,"gt":a*b,"exec":got,"ok":got==a*b})
acc=sum(r["ok"] for r in rows)/len(rows)
wrong=[r for r in rows if not r["ok"] and r["exec"] is not None]
print(json.dumps({"exec_accuracy":round(acc,3),"n_wrong":len(wrong)}),flush=True)

def rate(items):
    d=n=0
    for a,b,z,expect_false in items:
        v=ask_critic(a,b,z)
        if v is None: continue
        n+=1
        d += (v is False) if expect_false else (v is True)
    return d,n

A=[(r["a"],r["b"],r["exec"],True) for r in wrong]                       # own errors
B=[(r["a"],r["b"],r["gt"]+random.choice([-3000,-700,700,3000,11000]),True) for r in wrong]  # injected errors, same problems
C=[(r["a"],r["b"],r["gt"],False) for r in rows]                          # correct -> should say SI
dA,nA=rate(A); dB,nB=rate(B); dC,nC=rate(C)
res={"exec_accuracy":round(acc,3),
 "A_own_errors_detected":f"{dA}/{nA}","A_rate":round(dA/nA,3) if nA else None,
 "B_injected_errors_detected":f"{dB}/{nB}","B_rate":round(dB/nB,3) if nB else None,
 "C_correct_accepted":f"{dC}/{nC}","C_accept_rate":round(dC/nC,3) if nC else None,
 "wall_s":round(time.time()-t0,1)}
print(json.dumps(res,indent=1),flush=True)
json.dump({"res":res,"rows":rows},open("h3b.json","w"),indent=1)
