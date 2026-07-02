r"""
XH-P2DIAG — diagnóstico del gate GP2-1 (Belebele 35.2% < 40% en P2-K1, regla pre-registrada:
harness roto → diagnosticar ANTES de entrenar). XSC (mismo scorer NLL) dio sano (65.3%) y MGSM
también → el problema es específico del FORMATO Belebele, no del scorer.

Prueba 3 formatos sobre los mismos 200 ítems (base NF4, mirando SOLO el base — el formato
elegido se aplicará idéntico a base y adapter, así el delta queda insesgado):
  A. continuación-NLL media/token (el actual de P2-K1)     — control
  B. continuación-NLL SUMA (sin normalizar por largo)      — ¿sesgo de longitud?
  C. letra-NLL: opciones listadas A) B) C) D) en el prompt, se scorea ' A'..' D'
     (formato estándar para instruct-3B; el paper Iberian sugiere que va mejor)
Salida: p2diag_results.json. USO local: --smoke (sin modelo, valida construcción de prompts).
"""
import argparse
import json
import subprocess
import sys
import time

RESULTS_PATH = "p2diag_results.json"
N_ITEMS = 200
LETTERS = (" A", " B", " C", " D")


def _ensure_bitsandbytes():
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print(f"[bnb] pip -> rc={r.returncode} ({tail[-1] if tail else '-'})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[bnb] pip fallo: {e}", flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401
        return tuple(int(x) for x in importlib.metadata.version("bitsandbytes")
                     .split(".")[:3]) >= (0, 46, 1)
    except Exception:  # noqa: BLE001
        return False


def find_model_dir():
    import glob
    import os
    cands = [os.path.dirname(p) for p in glob.glob("/kaggle/input/**/config.json", recursive=True)]
    pool = [c for c in cands if "3b-instruct" in c.lower()] or cands
    pool.sort(key=len)
    return pool[0]


def prompt_continuation(r):
    return (f"Pasaje: {r['flores_passage']}\n\nPregunta: {r['question']}\nRespuesta:",
            [" " + r[f"mc_answer{k}"] for k in (1, 2, 3, 4)])


def prompt_letter(r):
    ops = "\n".join(f"{letter}) {r[f'mc_answer{k}']}" for letter, k in
                    zip("ABCD", (1, 2, 3, 4)))
    return (f"Pasaje: {r['flores_passage']}\n\nPregunta: {r['question']}\n\n{ops}\n\n"
            f"Responde únicamente con la letra de la opción correcta.", list(LETTERS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        r = {"flores_passage": "P", "question": "Q", "mc_answer1": "a1", "mc_answer2": "a2",
             "mc_answer3": "a3", "mc_answer4": "a4", "correct_answer_num": "2"}
        p1, o1 = prompt_continuation(r)
        p2, o2 = prompt_letter(r)
        assert o1[1] == " a2" and o2 == list(LETTERS) and "B) a2" in p2
        print("[smoke] prompts OK")
        return
    t0 = time.time()
    use_bnb = _ensure_bitsandbytes()
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from datasets import load_dataset
    device = "cuda"
    model_dir = find_model_dir()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.float16,
                               bnb_4bit_use_double_quant=True) if use_bnb else None
    model = AutoModelForCausalLM.from_pretrained(model_dir, quantization_config=quant,
                                                 torch_dtype=torch.float16, device_map={"": 0},
                                                 trust_remote_code=True)
    model.eval()

    @torch.no_grad()
    def option_nlls(prompt, options):
        """→ [(media, suma)] por opción."""
        pre = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                            tokenize=False, add_generation_prompt=True)
        pre_ids = tokenizer(pre, add_special_tokens=False)["input_ids"]
        outs = []
        seqs = [pre_ids + tokenizer(o, add_special_tokens=False)["input_ids"] for o in options]
        maxlen = max(len(s) for s in seqs)
        pad = tokenizer.pad_token_id
        inp = torch.full((len(seqs), maxlen), pad, dtype=torch.long)
        att = torch.zeros((len(seqs), maxlen), dtype=torch.long)
        for j, s in enumerate(seqs):
            inp[j, :len(s)] = torch.tensor(s)
            att[j, :len(s)] = 1
        inp, att = inp.to(device), att.to(device)
        logp = F.log_softmax(model(input_ids=inp, attention_mask=att).logits.float(), dim=-1)
        for j, s in enumerate(seqs):
            pos = torch.arange(len(pre_ids) - 1, len(s) - 1, device=device)
            tgt = inp[j, len(pre_ids):len(s)]
            lp = logp[j, pos, :].gather(1, tgt[:, None])
            outs.append((-float(lp.mean()), -float(lp.sum())))
        return outs

    bele = load_dataset("facebook/belebele", "spa_Latn", split="test")
    rows = list(bele)[:N_ITEMS]
    counts = {"A_cont_media": 0, "B_cont_suma": 0, "C_letra": 0}
    t1 = time.time()
    for i, r in enumerate(rows):
        ans = int(r["correct_answer_num"]) - 1
        p, opts = prompt_continuation(r)
        nlls = option_nlls(p, opts)
        counts["A_cont_media"] += int(min(range(4), key=lambda k: nlls[k][0]) == ans)
        counts["B_cont_suma"] += int(min(range(4), key=lambda k: nlls[k][1]) == ans)
        pl, letters = prompt_letter(r)
        nl = option_nlls(pl, letters)
        counts["C_letra"] += int(min(range(4), key=lambda k: nl[k][0]) == ans)
        if (i + 1) % 50 == 0:
            print(f"[diag] {i + 1}/{N_ITEMS} " +
                  " ".join(f"{k}={v / (i + 1):.3f}" for k, v in counts.items()), flush=True)
    out = {"experiment": "xh_p2diag", "n": len(rows),
           "acc": {k: round(v / len(rows), 4) for k, v in counts.items()},
           "eval_minutes": round((time.time() - t1) / 60, 1),
           "minutes_total": round((time.time() - t0) / 60, 1)}
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    best = max(out["acc"], key=out["acc"].get)
    print(f"[diag] FINAL {out['acc']} -> mejor formato: {best}", flush=True)


if __name__ == "__main__":
    main()
