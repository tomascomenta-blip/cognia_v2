# H4: cascade compression vs immutable-snapshot SELECTION. Both arms, 8 cycles.
import json, urllib.request, re, time, random
BASE="http://127.0.0.1:8080"
def comp(prompt,n=700,temp=0.2):
    r=urllib.request.Request(BASE+"/completion",data=json.dumps(
        {"prompt":prompt,"n_predict":n,"temperature":temp,"cache_prompt":False}).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=900) as f:
        j=json.loads(f.read().decode()); return j["content"], j["timings"]
def strip_think(t): return re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()
def chat(sysp,usr,n=700,temp=0.2):
    p=f"<|im_start|>system\n{sysp}<|im_end|>\n<|im_start|>user\n{usr}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    c,tm=comp(p,n=n,temp=temp); return strip_think(c),tm

R=[
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
ALL="\n".join(R)
IDS=[x[:3] for x in R]
def ids_in(t): return sorted(set(re.findall(r"\bR\d{2}\b", t)))

CHATTER=("El agente exploro el repo, abrio 12 ficheros, probo tres comandos que fallaron por "
 "un typo, reinstalo una dependencia, leyo documentacion, discutio consigo mismo sobre nombres "
 "de variables, y finalmente escribio una funcion auxiliar. Hubo ruido: trazas, warnings de "
 "deprecacion, y un intento de usar una ruta relativa que no existia. ")

# ---------- ARM 1: CASCADE (resumen de resumen) ----------
state=("OBJETIVO: migrar el servicio de pagos.\nRESTRICCIONES VIGENTES:\n"+ALL+
       "\nESTADO: ciclo 0, nada hecho aun.")
casc=[]
for cyc in range(1,9):
    usr=(f"Contexto de la sesion actual:\n{state}\n\nActividad del ciclo {cyc}:\n{CHATTER*3}\n\n"
         "Comprime TODO lo anterior en un resumen de trabajo para la siguiente sesion. "
         "Debe caber en unas 200 palabras. Conserva lo que importe para seguir trabajando.")
    out,tm=chat("Eres un agente que comprime su propio estado antes de reiniciar la sesion.",usr,n=900)
    surv=ids_in(out)
    casc.append({"cycle":cyc,"n_ids":len(surv),"ids":surv,"chars":len(out),
                 "prompt_n":tm["prompt_n"],"s":round((tm["prompt_ms"]+tm["predicted_ms"])/1000,2)})
    print(json.dumps(casc[-1]),flush=True)
    state=out

# ---------- ARM 2: IMMUTABLE SNAPSHOT + SELECTION ----------
subtasks=["preparar la rama y el entorno","cambiar el esquema de la tabla de pagos",
 "escribir el cliente HTTP al proveedor","guardar importes y fechas de las transacciones",
 "anadir logging y manejo de errores","escribir los tests","preparar el despliegue",
 "revisar rendimiento y cache"]
sel_hist=[]; seen=set()
prev="ciclo 0: nada hecho"
for cyc,st in enumerate(subtasks,1):
    usr=(f"ALMACEN INMUTABLE DE RESTRICCIONES (no cambia nunca):\n{ALL}\n\n"
         f"ESTADO ANTERIOR: {prev}\nSUBTAREA DE ESTE CICLO: {st}\n\n"
         "Selecciona SOLO las restricciones que necesitas cargar para este ciclo. "
         "Responde unicamente con la lista de identificadores separados por comas, maximo 6.")
    out,tm=chat("Eres el recuperador de memoria de un agente. Eliges que cargar en la ventana.",usr,n=120)
    sel=ids_in(out)[:6]
    seen|=set(sel)
    sel_hist.append({"cycle":cyc,"subtask":st,"selected":sel,"cum_coverage":len(seen)})
    print(json.dumps(sel_hist[-1]),flush=True)
    prev=f"ciclo {cyc}: {st} hecho aplicando {','.join(sel)}"

never=sorted(set(IDS)-seen)
res={"cascade":casc,"selection":sel_hist,
     "cascade_final_ids":casc[-1]["n_ids"],
     "selection_cum_coverage":len(seen),"never_selected":never,"n_never":len(never)}
print(json.dumps({"cascade_ids_by_cycle":[c["n_ids"] for c in casc],
                  "selection_cum_coverage_by_cycle":[s["cum_coverage"] for s in sel_hist],
                  "never_selected":never},indent=1),flush=True)
json.dump(res,open("h4.json","w"),indent=1)
