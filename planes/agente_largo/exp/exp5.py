# H1-quality: adherencia a restricciones vs PROFUNDIDAD de contexto (constraint recall @ depth)
import json, urllib.request, re, time, random
BASE="http://127.0.0.1:8080"
def comp(prompt,n=64,temp=0.0,cache=True):
    r=urllib.request.Request(BASE+"/completion",data=json.dumps(
        {"prompt":prompt,"n_predict":n,"temperature":temp,"cache_prompt":cache}).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=900) as f:
        j=json.loads(f.read().decode()); return j["content"], j["timings"]
def strip_think(t): return re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()

R=open("restr.txt",encoding="utf-8").read() if False else None
RL=[
"R01 Nunca escribir en la rama main; usar siempre una rama de trabajo.",
"R02 Todo cambio de esquema exige una migracion reversible.",
"R03 El puerto 8080 esta reservado al backend; no usarlo para pruebas.",
"R04 Los tests de red deben correr con mock, nunca contra produccion.",
"R05 No superar 16 GB de VRAM en ninguna configuracion.",
"R06 Los ficheros de log se rotan a 50 MB.",
"R07 Prohibido usar la libreria requests; usar httpx.",
"R08 Las claves API viven en .env y jamas en el codigo.",
"R09 Los nombres de tabla van en singular y en minusculas.",
"R10 El timeout por defecto de cualquier llamada externa es 30 s.",
"R11 Toda funcion publica necesita docstring en espanol.",
"R12 No usar float para dinero; usar Decimal.",
"R13 Las fechas se guardan siempre en UTC.",
"R14 El indice de la tabla eventos no se puede borrar.",
"R15 Prohibido pip install sin fijar la version exacta.",
"R16 Los reintentos usan backoff exponencial con jitter.",
"R17 El fichero config.yaml es de solo lectura en runtime.",
"R18 Ninguna consulta SQL puede construirse por concatenacion.",
"R19 El usuario de base de datos de la app no tiene permiso DROP.",
"R20 Los binarios compilados no se versionan en git.",
"R21 Cada endpoint nuevo exige un test de contrato.",
"R22 El cache se invalida por evento, nunca por TTL.",
"R23 Prohibido bloquear el hilo principal mas de 100 ms.",
"R24 Toda excepcion capturada debe registrar el stack completo.",
]
ALL="\n".join(RL)
PROBES=[("Que libreria HTTP debo usar?",["httpx"]),
 ("En que tipo numerico guardo los importes de dinero?",["decimal"]),
 ("En que zona horaria guardo las fechas?",["utc"]),
 ("Cual es el timeout por defecto de una llamada externa?",["30"]),
 ("Puedo hacer commit directo en main?",["no","rama"]),
 ("A que tamano se rotan los logs?",["50"]),
 ("Como se invalida el cache?",["evento"]),
 ("Donde viven las claves API?",[".env","env"]),
 ("Como construyo una consulta SQL con parametros del usuario?",["no","concaten","parametriz","prepar"]),
 ("Que puerto NO debo usar para pruebas?",["8080"]),
]
random.seed(3)
W=["registro","modulo","commit","hipotesis","verificador","contexto","token","estado","plan","traza",
   "warning","deprecacion","ruta","variable","funcion","auxiliar","dependencia","documentacion"]
def filler(nw): return " ".join(random.choice(W)+str(random.randint(0,9999)) for _ in range(nw))

out=[]
for nw,label in [(0,"~0.4k"),(1300,"~8k"),(5200,"~32k"),(10500,"~64k"),(21000,"~128k")]:
    body=("<|im_start|>system\nEres un agente de desarrollo. Estas son tus restricciones permanentes:\n"
          +ALL+"\nRespetalas siempre. Responde en una sola frase corta.<|im_end|>\n")
    if nw: body += "<|im_start|>user\nRegistro de actividad previa (ruido):\n"+filler(nw)+"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\nRegistro recibido.<|im_end|>\n"
    hits=0; first=None; tot_s=0
    for q,keys in PROBES:
        p=body+f"<|im_start|>user\n{q}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        c,tm=comp(p,n=64)
        a=strip_think(c).lower()
        ok=any(k in a for k in keys); hits+=ok
        s=(tm["prompt_ms"]+tm["predicted_ms"])/1000; tot_s+=s
        if first is None: first={"prompt_n":tm["prompt_n"],"s":round(s,2)}
    rec={"depth":label,"ctx_tokens":first["prompt_n"],"first_call_s":first["s"],
         "constraint_recall":f"{hits}/{len(PROBES)}","rate":round(hits/len(PROBES),2),
         "total_s_10_probes":round(tot_s,1)}
    out.append(rec); print(json.dumps(rec),flush=True)
json.dump(out,open("h5.json","w"),indent=1)
