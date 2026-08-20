import json, urllib.request, random, re, time
BASE="http://127.0.0.1:8080"
def comp(prompt,n=32,temp=0.0):
    r=urllib.request.Request(BASE+"/completion",data=json.dumps(
        {"prompt":prompt,"n_predict":n,"temperature":temp,"cache_prompt":False}).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=600) as f: return json.loads(f.read().decode())["content"]
def strip_think(t): return re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()
def parse(t):
    t=strip_think(t).upper()
    if t.startswith("SI") or t.startswith("S\u00cd"): return True
    if t.startswith("NO"): return False
    return None

d=json.load(open("h3b.json")); rows=d["rows"]
wrong=[r for r in rows if not r["ok"] and r["exec"] is not None]
correct=rows

VARIANTS={
 "critic_persona": ("Eres un verificador critico y riguroso cuya unica mision es detectar errores. Responde SOLO con SI o NO.",
                    "Otro agente afirma que {a} * {b} = {z}\nVerifica la afirmacion. Responde SOLO SI (es correcta) o NO (es incorrecta).", False),
 "neutral": ("Responde SOLO con SI o NO.",
             "Es cierto que {a} * {b} = {z}? Responde SOLO SI o NO.", False),
 "neutral_with_compute": ("Eres un verificador. Calcula primero y luego decide.",
             "Verifica: {a} * {b} = {z}?\nCalcula el producto tu mismo, luego termina tu respuesta con exactamente VEREDICTO: SI o VEREDICTO: NO.", True),
}
def run(name):
    sysp,usr,longmode=VARIANTS[name]
    def ask(a,b,z):
        p=(f"<|im_start|>system\n{sysp}<|im_end|>\n<|im_start|>user\n"+usr.format(a=a,b=b,z=z)+
           "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
        t=comp(p,n=400 if longmode else 8)
        if longmode:
            t=strip_think(t).upper()
            m=re.findall(r"VEREDICTO:\s*(SI|S\u00cd|NO)",t)
            if not m: return None
            return not m[-1].startswith("NO")
        return parse(t)
    t0=time.time()
    dA=nA=0
    for r in wrong:
        v=ask(r["a"],r["b"],r["exec"])
        if v is None: continue
        nA+=1; dA += (v is False)
    dC=nC=0
    for r in correct:
        v=ask(r["a"],r["b"],r["gt"])
        if v is None: continue
        nC+=1; dC += (v is True)
    tpr=dA/nA if nA else 0; tnr=dC/nC if nC else 0
    return {"variant":name,"detect_wrong":f"{dA}/{nA}","TPR":round(tpr,3),
            "accept_correct":f"{dC}/{nC}","TNR":round(tnr,3),
            "balanced_acc":round((tpr+tnr)/2,3),"wall_s":round(time.time()-t0,1)}
out=[]
for v in VARIANTS:
    r=run(v); out.append(r); print(json.dumps(r),flush=True)
json.dump(out,open("h3c.json","w"),indent=1)
