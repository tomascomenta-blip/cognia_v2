
import json, math, time, sys, glob, os
res = {"instalado": True}
try:
    from unsloth import FastLanguageModel
    import torch
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [d for d in cands if "3b" in d.lower()] or cands
    pool.sort(key=len)
    model_dir = pool[0]
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_dir, max_seq_length=1024, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
        use_gradient_checkpointing="unsloth", random_state=20260706)
    hits = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
    pares = []
    with open(hits[0], encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if "prompt" in r and "completion" in r:
                    pares.append(r)
            except Exception:
                pass
            if len(pares) >= 400:
                break
    textos = ["<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s<|im_end|>" % (r["prompt"], r["completion"]) for r in pares]
    # docs "packed": concatenar pares hasta ~1024 tokens (utilizacion ~1.0)
    enc_all = [tokenizer(t, add_special_tokens=False)["input_ids"] for t in textos]
    docs, fila = [], []
    for e in enc_all:
        if len(fila) + len(e) > 1024:
            if fila:
                docs.append(fila)
            fila = []
        fila += e
    if fila:
        docs.append(fila)
    # brazos: (mb, packed?) - mb16 solo packed (la CE fusionada de unsloth
    # deberia bancar los logits que OOMearon el path transformers a mb8)
    for mb, packed in ((4, False), (8, False), (8, True), (16, True)):
        if packed:
            enc = list(docs)
        else:
            enc = [x[:1024] for x in enc_all]
        while len(enc) < mb * 12:
            enc = enc + enc
        pad = tokenizer.pad_token_id or tokenizer.eos_token_id
        lotes = []
        for i in range(0, len(enc) - mb + 1, mb):
            chunk = enc[i:i+mb]
            ids = [x + [pad]*(1024-len(x)) for x in chunk]
            att = [[1]*len(x) + [0]*(1024-len(x)) for x in chunk]
            lab = [x + [-100]*(1024-len(x)) for x in chunk]
            lotes.append((ids, att, lab))
        clave = "mb%d%s" % (mb, "_pack" if packed else "")
        try:
            params = [p for p in model.parameters() if p.requires_grad]
            opt = torch.optim.AdamW(params, lr=1e-4)
            torch.cuda.reset_peak_memory_stats()
            steps = max(6, math.ceil(80000 / (mb*1024)))
            model.train()
            t0 = None; tok = 0; util = 0
            for step, (ids, att, lab) in enumerate(lotes[:3+steps]):
                if step == 3:
                    torch.cuda.synchronize(); t0 = time.time()
                x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
                y = torch.tensor(lab, device="cuda")
                out = model(input_ids=x, attention_mask=a, labels=y)
                out.loss.backward()
                opt.step(); opt.zero_grad(set_to_none=True)
                if step >= 3:
                    tok += mb*1024; util += int(a.sum().item())
            torch.cuda.synchronize()
            dt = time.time() - t0
            res[clave] = {"tok_s_seq": round(tok/dt, 1), "tok_s_util": round(util/dt, 1),
                          "vram_alloc_gb": round(torch.cuda.max_memory_allocated()/1e9, 2)}
            del opt
        except torch.cuda.OutOfMemoryError as e:
            res[clave] = {"error": "OOM: %s" % str(e)[:150]}
        import gc as _gc
        _gc.collect(); torch.cuda.empty_cache()
except Exception as e:
    res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
with open("/kaggle/working/unsloth_probe.json", "w") as f:
    json.dump(res, f)
print("UNSLOTH_PROBE_DONE", json.dumps(res)[:400])
