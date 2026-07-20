
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; EPOCHS = 2; LR = 1e-4; SEQ = 1024; MB = 8
BRAZOS = [
    {"nombre": "u_r8_qkvo",  "r": 8,  "targets": ["q_proj","k_proj","v_proj","o_proj"], "neft": 0.0},
    {"nombre": "u_r16_all",  "r": 16, "targets": ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], "neft": 0.0},
    {"nombre": "u_r16_neft", "r": 16, "targets": ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], "neft": 5.0},
]
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from e1_shared import find_model_dir, carga_train_json, lotes_packed_json

model_dir = find_model_dir()
out = {}
for brazo in BRAZOS:
    torch.manual_seed(SEED); random.seed(SEED)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_dir, max_seq_length=SEQ, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=brazo["r"], lora_alpha=2*brazo["r"], lora_dropout=0.05,
        target_modules=brazo["targets"], use_gradient_checkpointing="unsloth",
        random_state=SEED)
    ejemplos = carga_train_json(tokenizer)
    lotes = lotes_packed_json(ejemplos, SEQ, MB)
    hook = None
    if brazo["neft"] > 0:
        emb = model.get_input_embeddings()
        alpha = brazo["neft"]
        def neft_hook(mod, inp, salida):
            if mod.training:
                dims = salida.shape[-2] * salida.shape[-1]
                mag = alpha / (dims ** 0.5)
                return salida + torch.empty_like(salida).uniform_(-mag, mag)
            return salida
        hook = emb.register_forward_hook(neft_hook)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR)
    from torch.optim.lr_scheduler import CosineAnnealingLR
    total_steps = len(lotes) * EPOCHS
    sched = CosineAnnealingLR(opt, T_max=total_steps)
    model.train()
    losses = []; t0 = time.time(); tok = 0
    for ep in range(EPOCHS):
        for ids, att, lab in lotes:
            x = torch.tensor(ids, device="cuda"); a = torch.tensor(att, device="cuda")
            y = torch.tensor(lab, device="cuda")
            loss = model(input_ids=x, attention_mask=a, labels=y).loss
            loss.backward(); opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            losses.append(loss.item()); tok += int(a.sum().item())
    dt = time.time() - t0
    if hook: hook.remove()
    adir = "/kaggle/working/adapters/%s" % brazo["nombre"]
    model.save_pretrained(adir); tokenizer.save_pretrained(adir)
    out[brazo["nombre"]] = {"steps": len(losses), "tok_s_util": round(tok/dt, 1),
        "wall_s": round(dt, 1), "loss_ini": round(sum(losses[:5])/5, 4),
        "loss_fin": round(sum(losses[-5:])/5, 4),
        "nan": any(math.isnan(l) for l in losses)}
    print("BRAZO", brazo["nombre"], json.dumps(out[brazo["nombre"]]), flush=True)
    del model, opt; torch.cuda.empty_cache()
with open("/kaggle/working/unsloth_train.json", "w") as f:
    json.dump(out, f)
print("UNSLOTH_TRAIN_DONE", flush=True)
