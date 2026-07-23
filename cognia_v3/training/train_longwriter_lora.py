# -*- coding: utf-8 -*-
"""QLoRA-style LoRA de RESPUESTAS LARGAS para MiniCPM5-1B (idea del dueno).

Hipotesis (correcta y con precedente, LongWriter): el modelo NO responde largo por un
SESGO DE LONGITUD aprendido (emite EOS temprano), no por arquitectura. MiniCPM5-1B
tiene contexto 131072 -> el techo es el sesgo, no el contexto. Un LoRA sobre salidas
LARGAS y completas corre ese sesgo.

Datos: THUDM/LongWriter-6k (long.jsonl, 6000 ejemplos, respuestas hasta ~40k tokens).
bf16 + peft LoRA (sin QLoRA 4-bit: el 1B cabe), gradient_checkpointing, bs=1, SFT
completion-only. SEQLEN cap por VRAM (vocab 130K -> logits son el sumidero). Se
seleccionan ejemplos COMPLETOS que caben (no se truncan: truncar ensena a cortar).

Gate pre-registrado: longitud de salida (tokens) LoRA >= 2x base en prompts held-out.

RESULTADO MEDIDO (2026-07-23, RTX 5060 Ti, SEQLEN=3072, 1200 ejemplos, 2 epocas,
loss 2.10 -> 1.94):
  BASE  longitud mediana = 1525 tokens
  LoRA  longitud mediana = 2904 tokens  (x1.9; un output toco el tope de 4096)
  GATE: NO PASA por poco (exigia x2.0, dio x1.9). NO se cablea a nada.
Honestidades:
  - La hipotesis se valida DIRECCIONALMENTE: el sesgo de longitud es aprendible
    (MiniCPM5-1B tiene contexto 131072, asi que el techo no es la arquitectura).
  - El texto largo es COHERENTE (intro -> secciones -> conclusion, sin loops). El
    ratio de "tokens distintos" bajo (0.35 vs 0.5) resulto un proxy ENGANOSO: es
    vocabulario tecnico repetido, no repeticion patologica (verificado leyendo el texto).
  - REGRESION REAL: entrenado con LongWriter-6k (EN/ZH), el LoRA responde en INGLES a
    prompts en ESPANOL. Para un usuario hispanohablante eso es inaceptable -> hace falta
    mezclar datos largos en espanol antes de usarlo.
  - Errores factuales propios de un 1B. El objetivo real de esta receta es el cerebro
    grande (14B), no un 1B; aqui se demuestra la tecnica y el arreglo de memoria.

LECCION DE MEMORIA (costosa): con secuencias de longitud VARIABLE el asignador CUDA se
fragmenta, la VRAM reservada trepa al limite, hay spillover a shared memory (WDDM) y el
tiempo por paso SUBE (medido 3s -> 60s en 550 pasos) hasta que el driver mata el proceso
(exit 4, sin traceback). Sintoma diagnostico: VRAM allocated estable pero s/paso creciendo.
FIX: padding a longitud FIJA + attention_mask -> 8.4GB y 1.44s/paso constantes.
(expandable_segments no esta soportado en Windows.) Guardar checkpoints periodicos.

Uso: python -m cognia_v3.training.train_longwriter_lora train|eval  (env SEQLEN, EPOCHS)
"""
import os, sys, json, random, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, PeftModel
from huggingface_hub import hf_hub_download

M = "openbmb/MiniCPM5-1B"
ADAPTER = os.path.expanduser("~/.cognia/loras/minicpm_largo")
IM_END = 130073
SEED = 20260723
SEQLEN = int(os.environ.get("SEQLEN", "2048"))
MIN_TOK = int(os.environ.get("MIN_TOK", "900"))   # respuesta minima (tokens) para "larga"
MAX_EJEMPLOS = int(os.environ.get("MAX_EJEMPLOS", "1400"))
EPOCHS = int(os.environ.get("EPOCHS", "1"))


def _tok():
    return AutoTokenizer.from_pretrained(M, trust_remote_code=True)


def _pares(rows):
    for r in rows:
        msgs = r.get("messages", [])
        user = next((m["content"] for m in msgs if m.get("role") == "user"), None)
        asst = next((m["content"] for m in msgs if m.get("role") == "assistant"), None)
        if user and asst and len(asst) > 2000:
            yield user, asst


def _preparar(tok):
    p = hf_hub_download("THUDM/LongWriter-6k", "long.jsonl", repo_type="dataset")
    rows = [json.loads(l) for l in open(p, encoding="utf-8")]
    random.Random(SEED).shuffle(rows)
    ejs, held = [], []
    for user, asst in _pares(rows):
        enc = tok.apply_chat_template(
            [{"role": "user", "content": user}], tokenize=True,
            add_generation_prompt=True, enable_thinking=False, return_dict=True)
        pids = list(enc["input_ids"])
        cids = tok(asst, add_special_tokens=False)["input_ids"] + [IM_END]
        total = len(pids) + len(cids)
        if len(cids) < MIN_TOK or total > SEQLEN:
            continue
        ids = pids + cids
        labels = [-100] * len(pids) + cids
        if len(held) < 12:                 # aparta unos pocos para eval de coherencia
            held.append(user)
            continue
        ejs.append((ids, labels))
        if len(ejs) >= MAX_EJEMPLOS:
            break
    return ejs, held


def entrenar():
    random.seed(SEED); torch.manual_seed(SEED)
    tok = _tok()
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    print(f"[data] preparando (SEQLEN={SEQLEN}, min_tok={MIN_TOK})...", flush=True)
    ejs, _ = _preparar(tok)
    lens = [len(e[0]) for e in ejs]
    print(f"[data] {len(ejs)} ejemplos | tokens/seq: min={min(lens)} med={sum(lens)//len(lens)} max={max(lens)}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(M, trust_remote_code=True, dtype=torch.bfloat16).to("cuda")
    model.config.use_cache = False
    cfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.gradient_checkpointing_enable(); model.enable_input_require_grads()
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    model.train()
    for ep in range(EPOCHS):
        random.shuffle(ejs)
        tot, n, t0 = 0.0, 0, time.time()
        for ids, labels in ejs:
            # PADDING A LONGITUD FIJA (SEQLEN): memoria constante por paso -> sin
            # fragmentacion/spillover progresivo (la causa del crash a variable-len).
            npad = SEQLEN - len(ids)
            ii = torch.tensor([ids + [pad] * npad]).to("cuda")
            ll = torch.tensor([labels + [-100] * npad]).to("cuda")
            am = torch.tensor([[1] * len(ids) + [0] * npad]).to("cuda")
            out = model(input_ids=ii, attention_mask=am, labels=ll)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); opt.zero_grad()
            tot += float(out.loss); n += 1
            if n % 50 == 0:
                print(f"  ep{ep+1} {n}/{len(ejs)} loss={tot/n:.4f} "
                      f"VRAM={torch.cuda.max_memory_allocated()/1e9:.1f}GB {(time.time()-t0)/n:.2f}s/paso", flush=True)
            if n % 300 == 0:      # checkpoint: no perder el progreso si se corta
                os.makedirs(ADAPTER, exist_ok=True)
                model.save_pretrained(ADAPTER)
                print(f"  [checkpoint] adapter guardado en paso {n}", flush=True)
        print(f"epoch {ep+1}/{EPOCHS} loss={tot/max(1,n):.4f} {time.time()-t0:.0f}s", flush=True)
    os.makedirs(ADAPTER, exist_ok=True)
    model.save_pretrained(ADAPTER)
    print("adapter ->", ADAPTER, flush=True)


PROMPTS_EVAL = [
    "Escribe un ensayo largo, detallado y bien estructurado sobre la historia de la inteligencia artificial, con muchas secciones.",
    "Write a comprehensive, in-depth guide (several thousand words) to starting and maintaining a home vegetable garden.",
    "Explica en profundidad, con multiples secciones y ejemplos, como funciona un motor de combustion interna de principio a fin.",
    "Escribe una historia larga y envolvente sobre una expedicion a Marte, con desarrollo de personajes y varios capitulos.",
]


def _generar(model, tok, prompt, maxnew):
    inp = tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=True,
                                  add_generation_prompt=True, return_tensors="pt",
                                  return_dict=True, enable_thinking=False).to("cuda")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=maxnew, do_sample=True, temperature=0.7,
                             top_p=0.9, repetition_penalty=1.05, pad_token_id=tok.eos_token_id)
    gen = out[0, inp["input_ids"].shape[1]:]
    txt = tok.decode(gen, skip_special_tokens=True)
    return len(gen), txt


def evaluar():
    tok = _tok()
    maxnew = min(SEQLEN, 4096)
    base = AutoModelForCausalLM.from_pretrained(M, trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()

    def medir(model, etq):
        largos = []
        for p in PROMPTS_EVAL:
            n, txt = _generar(model, tok, p, maxnew)
            # ratio de tokens distintos como proxy grueso de no-degeneracion
            toks = txt.split()
            distinto = len(set(toks)) / max(1, len(toks))
            largos.append(n)
            print(f"  [{etq}] {n} tokens (distinct={distinto:.2f}) :: {p[:45]}...", flush=True)
        med = sorted(largos)[len(largos)//2]
        print(f"[{etq}] longitud mediana = {med} tokens", flush=True)
        return med

    mb = medir(base, "BASE")
    lora = PeftModel.from_pretrained(base, ADAPTER).eval()
    ml = medir(lora, "LoRA")
    print(f"\nGATE (LoRA >> BASE en longitud): base={mb} lora={ml} tokens -> "
          f"{'PASA' if ml >= 2*mb and ml >= 1500 else 'REVISAR'} (x{ml/max(1,mb):.1f})", flush=True)


if __name__ == "__main__":
    {"train": entrenar, "eval": evaluar}.get(sys.argv[1] if len(sys.argv) > 1 else "train", entrenar)()
