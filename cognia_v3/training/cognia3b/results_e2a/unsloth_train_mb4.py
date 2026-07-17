
import json, math, os, random, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
SEED = 20260707; EPOCHS = 2; LR = 1e-4; SEQ = 1024; MB = 4  # mb4 -> 92 steps (igualado a t_r16_all)
from unsloth import FastLanguageModel
import torch
sys.path.insert(0, "/kaggle/working")
from e2a_shared import find_model_dir, carga_train_json, lotes_packed_json

model_dir = find_model_dir()
torch.manual_seed(SEED); random.seed(SEED)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_dir, max_seq_length=SEQ, load_in_4bit=True, dtype=None)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=SEED)
ejemplos = carga_train_json(tokenizer)
lotes = lotes_packed_json(ejemplos, SEQ, MB)
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=LR)
from torch.optim.lr_scheduler import CosineAnnealingLR
sched = CosineAnnealingLR(opt, T_max=len(lotes) * EPOCHS)
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
adir = "/kaggle/working/adapters/u_r16_all_mb4"
model.save_pretrained(adir); tokenizer.save_pretrained(adir)
out = {"u_r16_all_mb4": {"steps": len(losses), "tok_s_util": round(tok/dt, 1),
    "wall_s": round(dt, 1), "loss_ini": round(sum(losses[:5])/5, 4),
    "loss_fin": round(sum(losses[-5:])/5, 4),
    "nan": any(math.isnan(l) for l in losses)}}
print("BRAZO u_r16_all_mb4", json.dumps(out["u_r16_all_mb4"]), flush=True)
with open("/kaggle/working/unsloth_train.json", "w") as f:
    json.dump(out, f)
print("UNSLOTH_TRAIN_DONE", flush=True)
