# -*- coding: utf-8 -*-
"""REPRO MINIMA — el corte ANTES DEL PRIMER FRAME no lo cuenta NADIE.

Encontrado por el verificador independiente el 2026-08-17, DESPUES de cerrar
el defecto #5. El defecto #5 cerro el agujero de los tokens GENERADOS (los
frames de contenido, exactos: 132/132 tres veces contra /tokenize). Queda
este caso: si el usuario corta mientras el server todavia esta en el PREFILL,
no llego ni un frame -> usage={} -> registrar({}) suma 0, y sin_prompt() —el
contador que el contrato de workflows.py:70 declara como "lo que impide que
el agujero crezca sin verse"— tampoco tica, porque solo cuenta los usages con
completion Y sin prompt.

MEDIDO: prompt de 6.869 tokens prefilleado, presupuesto.gastado()=0,
presupuesto.sin_prompt()=0. La UNICA constancia es la linea de journal con
usage_desconocido=true.

    venv312\Scripts\python.exe scripts\repro_corte_en_prefill.py
"""
import json
import os
import sys
import threading
import time
import urllib.request

RAIZ = r"C:\Users\usuario\Desktop\cognia_v2"
import tempfile
SCR = os.environ.get("COGNIA_TMP") or os.path.join(tempfile.gettempdir(), "cognia_repro_prefill")
os.makedirs(SCR, exist_ok=True)
os.environ["COGNIA_WORKFLOWS_DIR"] = os.path.join(SCR, "wf")
sys.path.insert(0, RAIZ)
from cognia.agent import workflows as wf                # noqa: E402

URL = "http://127.0.0.1:8080"


def _post(ruta, carga):
    req = urllib.request.Request(
        URL + ruta, data=json.dumps(carga).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


# Prompt LARGO y UNICO por corrida: sin cache de KV el prefill tarda, y ahi es
# donde cae el corte.
SEMILLA = str(time.time())
PROMPT = ("Analiza el siguiente registro y escribi un informe larguisimo. "
          "Marca unica " + SEMILLA + ". ") + (
    "Linea de registro con datos de red, latencias, rutas y errores. " * 400)

p_tpl = _post("/apply-template", {"messages": [{"role": "user",
                                                "content": PROMPT}]})["prompt"]
P_TOK = len(_post("/tokenize", {"content": p_tpl, "add_special": True})["tokens"])
print(f"prompt REAL (plantilla aplicada, /tokenize): {P_TOK} tokens")

c = wf.corrida("prefill", presupuesto_tokens=500000,
               print_fn=lambda *_a, **_k: None, total_agentes=1,
               interactivo=True)
aid = f"{c.run_id}#pasos.1@1"
caja = {}


def _th():
    caja["r"] = wf.agente(c, PROMPT, max_tokens=2048, indice=1, total=1,
                          fase="pasos", etiqueta="prefill")


th = threading.Thread(target=_th, daemon=True)
th.start()
time.sleep(0.8)                 # dentro de la llamada, antes del 1er token
r_can = wf.cancelar_agente(aid)
th.join(180)
fin = c.cerrar(ok=False, resumen="prefill")

J = [json.loads(l) for l in open(os.path.join(SCR, "wf", c.run_id,
                                              "journal.jsonl"),
                                 encoding="utf-8") if l.strip()]
cortes = [d for d in J if d.get("tipo") == "corte"]
print("cancelar_agente ->", r_can["estado"])
print("lineas corte:", json.dumps(cortes, ensure_ascii=False)[:400])
print(f"presupuesto.gastado()   = {c.presupuesto.gastado()}")
print(f"presupuesto.estimados() = {c.presupuesto.estimados()}")
print(f"presupuesto.sin_prompt()= {c.presupuesto.sin_prompt()}")
print(f"WorkflowFin.tokens={fin.tokens} tokens_estimados={fin.tokens_estimados}")
print()
hubo_llamada = bool(cortes)
desc = cortes[0].get("usage_desconocido") if cortes else None
chars = cortes[0].get("descartado_chars") if cortes else None
print(f"VEREDICTO: hubo llamada al server = {hubo_llamada}; "
      f"usage_desconocido={desc}; descartado_chars={chars}")
print(f"  el server prefilleo ~{P_TOK} tokens y el presupuesto conto "
      f"{c.presupuesto.gastado()}")
print(f"  sin_prompt() —el contador que declara el agujero— vale "
      f"{c.presupuesto.sin_prompt()}")
