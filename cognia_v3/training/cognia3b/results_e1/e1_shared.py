
import glob, json, os, random
SEED = 20260707
def find_model_dir():
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len); return pool[0]
def carga_train_json(tokenizer):
    hits = glob.glob("/kaggle/input/**/e1_train.jsonl", recursive=True)
    hits.sort(key=len)
    ejemplos = []
    with open(hits[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            pre = "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n" % r["prompt"]
            full = pre + "%s<|im_end|>" % r["completion"]
            ids_pre = tokenizer(pre, add_special_tokens=False)["input_ids"]
            ids_full = tokenizer(full, add_special_tokens=False)["input_ids"]
            ejemplos.append({"ids": ids_full, "prompt_len": len(ids_pre)})
    rng = random.Random(SEED); rng.shuffle(ejemplos)
    return ejemplos
def lotes_packed_json(ejemplos, seq, mb):
    filas, fila, lab, restante = [], [], [], seq
    for e in ejemplos:
        x = e["ids"][:seq]
        if len(x) > restante:
            if fila: filas.append((fila, lab))
            fila, lab, restante = [], [], seq
        y = list(x); pl = min(e["prompt_len"], len(x)); y[:pl] = [-100]*pl
        fila += x; lab += y; restante -= len(x)
    if fila: filas.append((fila, lab))
    lotes = []
    for i in range(0, len(filas), mb):
        chunk = filas[i:i+mb]
        if len(chunk) < mb: break
        ids = [f + [0]*(seq-len(f)) for f, _ in chunk]
        att = [[1]*len(f) + [0]*(seq-len(f)) for f, _ in chunk]
        labs = [l + [-100]*(seq-len(l)) for _, l in chunk]
        lotes.append((ids, att, labs))
    return lotes
